
from __future__ import annotations

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix

from .config import STEP_HOURS
from .dispatch import VALUE_OF_LOST_LOAD, Decision

H = STEP_HOURS


class Optimizer:
    name = "Optimizer"
    description = ("Balanced: plans 10 hours ahead across three forecast scenarios, trading off cost, "
                   "carbon and reserve.")

    def __init__(self, horizon_steps: int = 40, spread_k: float = 1.0,
                 scenario_weights=(0.25, 0.5, 0.25), carbon_weight: float = 1.0,
                 wear_weight: float = 1.0, reserve_soc: float = 0.0,
                 terminal_value_factor: float = 0.9):
        self.horizon = horizon_steps
        self.spread_k = spread_k                    # how far apart the scenarios are (std deviations)
        self.scenario_weights = scenario_weights    # (stress, expected, good); 0 = ignore that scenario
        self.carbon_weight = carbon_weight          # 0 = ignore carbon, 1 = carbon price, >1 = greener
        self.wear_weight = wear_weight              # >1 = protect the batteries
        self.reserve_soc = reserve_soc              # keep batteries at least this full (0..1)
        self.terminal_value_factor = terminal_value_factor
        self.last_plan: dict | None = None

    # ------------------------------------------------------------------ inputs
    def _inputs(self, sim):
        """Step 0 = observed now. Steps 1..H = forecast, expanded into scenarios."""
        o = sim.observe()
        f = sim.forecast(self.horizon)
        m = sim.config.market
        k = self.spread_k
        hours = np.r_[o["hour"], [sim.hour_at(int(s)) for s in f.step]]
        dr_inc = np.where((hours >= 17) & (hours < 22), m.dr_incentive_peak, m.dr_incentive_offpeak)
        flex_ratio = o["flexible_demand_mw"] / max(o["demand_total_mw"], 1e-9)
        gen_mu = f.solar_mw.to_numpy() + f.wind_mw.to_numpy()
        gen_sd = f.solar_std.to_numpy() + f.wind_std.to_numpy()   # conservative: errors add up
        dem_mu, dem_sd = f.demand_mw.to_numpy(), f.demand_std.to_numpy()
        g0, d0 = o["solar_total_mw"] + o["wind_total_mw"], o["demand_total_mw"]
        scen = []
        for w, sign in zip(self.scenario_weights, (-1, 0, 1)):      # stress, expected, good
            if w <= 0:
                continue
            gen = np.r_[g0, np.maximum(gen_mu + sign * k * gen_sd, 0.0)]
            dem = np.r_[d0, np.maximum(dem_mu - sign * k * dem_sd, 0.0)]
            scen.append({"w": w, "gen": gen, "demand": dem,
                         "flex": np.r_[o["flexible_demand_mw"], dem[1:] * flex_ratio],
                         "label": {-1: "stress", 0: "expected", 1: "good"}[sign]})
        total = sum(s["w"] for s in scen)
        for s in scen:
            s["w"] /= total
        price = np.r_[o["price_inr_mwh"], f.price]
        export_cap = np.r_[o["max_export_mw"], f.max_export_mw]
        return o, scen, price, export_cap, dr_inc, hours

    # ------------------------------------------------------------------ the LP
    def plan(self, sim) -> dict:
        o, scen, price, export_cap, dr_inc, hours = self._inputs(sim)
        T, S = len(price), len(scen)
        m = sim.config.market
        names = list(sim.batteries)
        nb = len(names)
        K = 2 * nb + 5                                  # decision variables per step
        B = K + nb                                      # + battery energy at the end of the step
        N = B * (1 + S * (T - 1))

        def base(s, t):                                 # step 0 is shared by all scenarios
            return 0 if t == 0 else B + s * (T - 1) * B + (t - 1) * B
        CH = lambda s, t, b: base(s, t) + b                     # noqa: E731
        DIS = lambda s, t, b: base(s, t) + nb + b               # noqa: E731
        CURT = lambda s, t: base(s, t) + 2 * nb                 # noqa: E731
        EXP = lambda s, t: base(s, t) + 2 * nb + 1              # noqa: E731
        IMP = lambda s, t: base(s, t) + 2 * nb + 2              # noqa: E731
        DR = lambda s, t: base(s, t) + 2 * nb + 3               # noqa: E731
        UNS = lambda s, t: base(s, t) + 2 * nb + 4              # noqa: E731
        EN = lambda s, t, b: base(s, t) + K + b                 # noqa: E731

        c = np.zeros(N)
        lb, ub = np.zeros(N), np.zeros(N)
        v_end = self.terminal_value_factor * float(np.mean(price))
        e0 = {}
        for s in range(S):
            for t in range(T):
                if t == 0 and s > 0:
                    continue                            # shared block is filled once
                w = 1.0 if t == 0 else scen[s]["w"]
                sc = scen[s]
                for b, name in enumerate(names):
                    bat, spec = sim.batteries[name], sim.batteries[name].spec
                    e0[name] = bat.energy_mwh
                    ok = bat.available
                    lo = min(max(spec.min_soc, self.reserve_soc) * spec.capacity_mwh, bat.energy_mwh)
                    hi = max(spec.max_soc * spec.capacity_mwh, lo)
                    ub[CH(s, t, b)] = (bat.max_charge_mw() if t == 0 else spec.max_charge_mw) if ok else 0
                    ub[DIS(s, t, b)] = (bat.max_discharge_mw() if t == 0 else spec.max_discharge_mw) if ok else 0
                    wear = spec.degradation_cost_per_mwh * H * self.wear_weight * w
                    c[CH(s, t, b)] = c[DIS(s, t, b)] = wear
                    lb[EN(s, t, b)], ub[EN(s, t, b)] = lo, hi
                    if t == T - 1:
                        c[EN(s, t, b)] = -v_end * w
                ub[CURT(s, t)] = sc["gen"][t]
                ub[EXP(s, t)] = export_cap[t]
                ub[IMP(s, t)] = sim.config.grid.max_import_mw
                ub[DR(s, t)] = sc["flex"][t]
                ub[UNS(s, t)] = 1e6
                c[EXP(s, t)] = -price[t] * H * w
                c[IMP(s, t)] = (price[t] + m.grid_emission_factor * m.carbon_price * self.carbon_weight) * H * w
                c[DR(s, t)] = dr_inc[t] * H * w
                c[UNS(s, t)] = VALUE_OF_LOST_LOAD * H * w

        n_rows = S * T * (1 + nb)
        A = lil_matrix((n_rows, N))
        rhs = np.zeros(n_rows)
        r = 0
        for s in range(S):
            sc = scen[s]
            for t in range(T):
                A[r, CURT(s, t)], A[r, DR(s, t)] = -1, 1                    # energy balance
                A[r, EXP(s, t)], A[r, IMP(s, t)], A[r, UNS(s, t)] = -1, 1, 1
                for b in range(nb):
                    A[r, DIS(s, t, b)], A[r, CH(s, t, b)] = 1, -1
                rhs[r] = sc["demand"][t] - sc["gen"][t]
                r += 1
                for b, name in enumerate(names):                            # battery dynamics
                    eff = sim.batteries[name].spec.efficiency
                    A[r, EN(s, t, b)] = 1
                    A[r, CH(s, t, b)], A[r, DIS(s, t, b)] = -eff * H, H / eff
                    if t == 0:
                        rhs[r] = e0[name]
                    else:
                        A[r, EN(s, t - 1, b)] = -1
                    r += 1

        res = linprog(c, A_eq=A.tocsr(), b_eq=rhs, bounds=list(zip(lb, ub)), method="highs")
        if res.status != 0:
            raise RuntimeError(f"LP not solved: {res.message}")
        x = res.x
        main = max(range(S), key=lambda i: scen[i]["w"])           # the plan we show = most likely scenario
        sm = main
        plan = {
            "names": names, "hours": hours, "price": price,
            "gen": scen[sm]["gen"], "demand": scen[sm]["demand"],
            "charge": np.array([[x[CH(sm, t, b)] for b in range(nb)] for t in range(T)]),
            "discharge": np.array([[x[DIS(sm, t, b)] for b in range(nb)] for t in range(T)]),
            "curtail": np.array([x[CURT(sm, t)] for t in range(T)]),
            "dr": np.array([x[DR(sm, t)] for t in range(T)]),
            "import": np.array([x[IMP(sm, t)] for t in range(T)]),
            "export": np.array([x[EXP(sm, t)] for t in range(T)]),
            "unserved": np.array([x[UNS(sm, t)] for t in range(T)]),
            "objective_inr": float(res.fun),
            "scenarios": [s["label"] for s in scen],
        }
        self.last_plan = plan
        return plan

    # ------------------------------------------------------------------ controller API
    def decide(self, sim) -> Decision:
        try:
            p = self.plan(sim)
        except Exception as err:  # error recovery: never leave the grid without a decision
            from .controllers import SimpleRules  # local import avoids a circular import
            fallback = SimpleRules().decide(sim)
            fallback.reason = f"Optimizer failed ({err}); fell back to simple rules. {fallback.reason}"
            return fallback
        battery = {}
        for b, name in enumerate(p["names"]):
            net = p["charge"][0, b] - p["discharge"][0, b]
            battery[name] = float(net) if abs(net) > 1e-6 else 0.0   # never both at once
        return Decision(battery_mw=battery, curtail_mw=float(p["curtail"][0]),
                        demand_response_mw=float(p["dr"][0]),
                        reason=f"[{self.name}] " + self._explain(p, battery, self.reserve_soc))

    # ------------------------------------------------------------------ plain-language reason
    @staticmethod
    def _explain(p, battery, reserve) -> str:
        price_now, hours = p["price"][0], p["hours"]
        peak_i = int(np.argmax(p["price"][1:])) + 1
        peak_t = f"{int(hours[peak_i]):02d}:{int(round((hours[peak_i] % 1) * 60)):02d}"
        charge, discharge = sum(v for v in battery.values() if v > 0), -sum(v for v in battery.values() if v < 0)
        parts = []
        if charge > 0.5:
            parts.append(f"Charging {charge:.0f} MW: power is cheap now (₹{price_now:,.0f}/MWh) and "
                         f"₹{p['price'][peak_i]:,.0f} is expected around {peak_t}.")
        elif discharge > 0.5:
            parts.append(f"Discharging {discharge:.0f} MW: ₹{price_now:,.0f}/MWh is worth more than "
                         "the stored energy later, and it avoids buying from the grid.")
        else:
            parts.append("Batteries on hold: keeping the energy is worth more than using it now.")
        if reserve > 0:
            parts.append(f"Keeping at least {reserve:.0%} charge in reserve.")
        if p["dr"][0] > 0.5:
            parts.append(f"Demand response of {p['dr'][0]:.0f} MW is cheaper than buying at ₹{price_now:,.0f}/MWh.")
        if p["curtail"][0] > 0.5:
            parts.append(f"Curtailing {p['curtail'][0]:.0f} MW of renewables with no profitable use.")
        if p["unserved"][0] > 0.5:
            parts.append(f"WARNING: {p['unserved'][0]:.0f} MW cannot be served within limits.")
        return " ".join(parts)


# ---------------------------------------------------------------------- Day 3 trade-off modes
class Cheapest(Optimizer):
    name = "Optimizer: Cheapest"
    description = "Minimises money spent. Ignores carbon, plans on the expected forecast only."

    def __init__(self):
        super().__init__(scenario_weights=(0.0, 1.0, 0.0), carbon_weight=0.0)


class Greenest(Optimizer):
    name = "Optimizer: Greenest"
    description = "Cuts grid imports and carbon hard, even if it costs more."

    def __init__(self):
        super().__init__(carbon_weight=5.0)


class ReliabilityFirst(Optimizer):
    name = "Optimizer: Reliability first"
    description = "Keeps a battery reserve and plans for a bad forecast (storms, outages)."

    def __init__(self):
        super().__init__(scenario_weights=(0.5, 0.4, 0.1), spread_k=1.5, reserve_soc=0.4, wear_weight=1.5)


MODES = (Cheapest, Optimizer, Greenest, ReliabilityFirst)