"""Turns an operating decision into physical results and cost/carbon accounting for one 15-min step.

Every controller (no orchestration, simple rules, the optimizer and the AI agent) produces a
`Decision`. `settle()` applies it to the simulated grid under physical limits, so all
controllers are judged by exactly the same rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import STEP_HOURS

VALUE_OF_LOST_LOAD = 50_000.0  # ₹/MWh penalty for demand that could not be served (assumption)


@dataclass
class Decision:
    battery_mw: dict = field(default_factory=dict)  # per battery: + charge, - discharge
    curtail_mw: float = 0.0                         # renewable output deliberately not used
    demand_response_mw: float = 0.0                 # flexible load reduced/shifted (paid incentive)
    reason: str = ""                                # plain-language explanation


def settle(sim, decision: Decision) -> dict:
    """Apply a decision to the current step. Returns detailed flows and accounting."""
    obs = sim.observe()
    m = sim.config.market
    gen = obs["solar_total_mw"] + obs["wind_total_mw"]
    curtail = min(max(decision.curtail_mw, 0.0), gen)
    dr = min(max(decision.demand_response_mw, 0.0), obs["flexible_demand_mw"])
    demand = obs["demand_total_mw"] - dr

    charge = discharge = wear = 0.0
    battery_flow = {}
    for name, b in sim.batteries.items():
        sp = decision.battery_mw.get(name, 0.0)
        r = b.apply(charge_mw=max(sp, 0.0), discharge_mw=max(-sp, 0.0))
        charge += r["charge_mw"]
        discharge += r["discharge_mw"]
        wear += r["degradation_cost"]
        battery_flow[name] = r["charge_mw"] - r["discharge_mw"]

    net = gen - curtail + discharge - charge - demand          # >0 surplus, <0 shortfall
    export = min(max(net, 0.0), obs["max_export_mw"])
    forced_curtail = max(net, 0.0) - export                     # line full: power has nowhere to go
    imp = min(max(-net, 0.0), obs["max_import_mw"])
    unserved = max(-net, 0.0) - imp                             # reliability failure

    h = STEP_HOURS
    price = obs["price_inr_mwh"]
    energy_cost = (imp - export) * price * h
    carbon_t = imp * m.grid_emission_factor * h
    carbon_cost = carbon_t * m.carbon_price
    dr_cost = dr * obs["dr_incentive_inr_mwh"] * h
    unserved_cost = unserved * VALUE_OF_LOST_LOAD * h
    total_curtail = curtail + forced_curtail

    return {
        "obs": obs,
        "battery_flow": battery_flow,
        "summary": {
            "charge_mw": round(charge, 3), "discharge_mw": round(discharge, 3),
            "import_mw": round(imp, 3), "export_mw": round(export, 3),
            "curtail_mw": round(total_curtail, 3), "dr_mw": round(dr, 3),
            "unserved_mw": round(unserved, 3),
            "energy_cost_inr": energy_cost, "carbon_t": carbon_t, "carbon_cost_inr": carbon_cost,
            "dr_cost_inr": dr_cost, "wear_cost_inr": wear, "unserved_cost_inr": unserved_cost,
            "total_cost_inr": energy_cost + carbon_cost + dr_cost + wear + unserved_cost,
            "renewable_used_mw": round(gen - total_curtail, 3),
            "decision": decision.reason,
        },
    }


def run_step(sim, controller) -> tuple[Decision, dict]:
    """One full control cycle: decide, apply, log, move 15 minutes ahead."""
    decision = controller.decide(sim)
    result = settle(sim, decision)
    sim.advance(result["summary"])
    return decision, result
