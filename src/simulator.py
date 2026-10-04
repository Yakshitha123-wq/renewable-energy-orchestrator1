"""Stochastic grid simulator.

Every 15 minutes it produces a new situation: solar and wind output, industrial demand,
market prices, grid frequency, battery state and active events (battery failures, storms,
price spikes, ...). It also produces forecasts whose uncertainty grows with the horizon.

The orchestrator agent only ever sees `observe()` and `forecast()`, just like a real
operator who sees SCADA readings and weather/market forecasts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import DEFAULT_PORTFOLIO, STEP_HOURS, STEP_MINUTES, STEPS_PER_DAY, PortfolioConfig

# Event kinds and whether they are announced in advance (shown as alerts/in forecasts)
EVENT_KINDS = {
    "cloud_cover": False,        # params: level (0-1)
    "storm": True,               # params: wind_ms
    "battery_outage": False,     # params: battery
    "price_spike": False,        # params: multiplier
    "demand_surge": False,       # params: consumer, extra_mw
    "transmission_limit": True,  # params: max_export_mw
    "maintenance": True,         # params: asset (a solar or wind farm name)
}


@dataclass
class Event:
    kind: str
    start_step: int
    duration_steps: int
    params: dict = field(default_factory=dict)
    announced: bool = False
    description: str = ""

    def active(self, step: int) -> bool:
        return self.start_step <= step < self.start_step + self.duration_steps

    def upcoming(self, step: int, lookahead: int) -> bool:
        return step < self.start_step <= step + lookahead


class Battery:
    """Battery with charge/discharge limits, efficiency losses, SoC bounds and wear cost."""

    def __init__(self, spec, soc: float = 0.5):
        self.spec = spec
        self.soc = soc
        self.available = True
        self.throughput_mwh = 0.0

    @property
    def energy_mwh(self) -> float:
        return self.soc * self.spec.capacity_mwh

    def max_charge_mw(self) -> float:
        if not self.available:
            return 0.0
        room = max(0.0, (self.spec.max_soc - self.soc) * self.spec.capacity_mwh)
        return min(self.spec.max_charge_mw, room / (self.spec.efficiency * STEP_HOURS))

    def max_discharge_mw(self) -> float:
        if not self.available:
            return 0.0
        stored = max(0.0, (self.soc - self.spec.min_soc) * self.spec.capacity_mwh)
        return min(self.spec.max_discharge_mw, stored * self.spec.efficiency / STEP_HOURS)

    def apply(self, charge_mw: float = 0.0, discharge_mw: float = 0.0) -> dict:
        """Apply one 15-min set-point. Requests are clipped to physical limits."""
        if charge_mw > 1e-9 and discharge_mw > 1e-9:
            raise ValueError("A battery cannot charge and discharge in the same step")
        c = min(max(charge_mw, 0.0), self.max_charge_mw())
        d = min(max(discharge_mw, 0.0), self.max_discharge_mw())
        delta_mwh = (c * self.spec.efficiency - d / self.spec.efficiency) * STEP_HOURS
        self.soc = float(np.clip(self.soc + delta_mwh / self.spec.capacity_mwh, 0.0, 1.0))
        moved = (c + d) * STEP_HOURS
        self.throughput_mwh += moved
        return {
            "charge_mw": c,
            "discharge_mw": d,
            "soc": self.soc,
            "degradation_cost": moved * self.spec.degradation_cost_per_mwh,
        }

    def status(self) -> dict:
        return {
            "soc": round(self.soc, 4),
            "energy_mwh": round(self.energy_mwh, 2),
            "capacity_mwh": self.spec.capacity_mwh,
            "available": self.available,
            "max_charge_mw": round(self.max_charge_mw(), 2),
            "max_discharge_mw": round(self.max_discharge_mw(), 2),
            "efficiency": self.spec.efficiency,
            "degradation_cost_per_mwh": self.spec.degradation_cost_per_mwh,
        }


# ---------- physics and market shapes (pure functions, reused by the forecaster) ----------

def clear_sky_factor(hour: float) -> float:
    """0 at night, peaks at solar noon. Sunrise ~06:00, sunset ~18:00 (October, India)."""
    if hour <= 6.0 or hour >= 18.0:
        return 0.0
    return math.sin(math.pi * (hour - 6.0) / 12.0) ** 1.3


def wind_power_fraction(speed_ms: float, farm) -> float:
    """Standard turbine power curve: cubic between cut-in and rated, zero above cut-out."""
    if speed_ms < farm.cut_in_ms or speed_ms >= farm.cut_out_ms:
        return 0.0
    if speed_ms >= farm.rated_ms:
        return 1.0
    return ((speed_ms - farm.cut_in_ms) / (farm.rated_ms - farm.cut_in_ms)) ** 3


def demand_profile(profile: str, hour: float) -> float:
    if profile == "day_shift":
        return 1.0 if 9 <= hour < 18 else 0.4
    if profile == "two_shift":
        return 0.5 if (hour >= 22 or hour < 6) else 1.0
    return 1.0  # flat, 24x7 process load


def price_profile(hour: float) -> float:
    """₹/MWh shape: cheap at night, dip at solar noon, sharp evening peak."""
    base = 3_200
    morning = 1_800 * math.exp(-(((hour - 9.0) / 1.5) ** 2))
    solar_dip = -900 * math.exp(-(((hour - 13.0) / 2.5) ** 2))
    evening = 5_200 * math.exp(-(((hour - 19.5) / 1.8) ** 2))
    return base + morning + solar_dip + evening


class GridSimulator:
    CLOUD_MEAN, CLOUD_PERSIST, CLOUD_NOISE = 0.25, 0.92, 0.05
    WIND_MEAN, WIND_PERSIST, WIND_NOISE = 8.5, 0.95, 0.7
    ALERT_LOOKAHEAD = 16  # announced events become visible 4 hours ahead

    def __init__(self, config: PortfolioConfig = DEFAULT_PORTFOLIO, seed: int = 42,
                 start: str = "2026-10-05 00:00", initial_soc: float = 0.5):
        self.config = config
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.start = pd.Timestamp(start)
        self.step = 0
        self.batteries = {s.name: Battery(s, initial_soc) for s in config.batteries}
        self.events: list[Event] = []
        self.cloud = self.CLOUD_MEAN
        self.wind_ms = 8.0
        self.history: list[dict] = []
        self.current: dict = {}
        self._compute_current()

    # ---------------- time helpers ----------------
    @property
    def time(self) -> pd.Timestamp:
        return self.start + pd.Timedelta(minutes=STEP_MINUTES * self.step)

    def hour_at(self, step: int) -> float:
        return ((step % STEPS_PER_DAY) * STEP_MINUTES) / 60.0

    @staticmethod
    def step_of(clock: str, day: int = 0) -> int:
        """'18:30' -> step index on the given day."""
        h, m = (int(x) for x in clock.split(":"))
        return day * STEPS_PER_DAY + (h * 60 + m) // STEP_MINUTES

    # ---------------- events ----------------
    def schedule(self, kind: str, at_step: int, duration_steps: int,
                 announced: bool | None = None, **params) -> Event:
        if kind not in EVENT_KINDS:
            raise ValueError(f"Unknown event kind '{kind}'. Options: {list(EVENT_KINDS)}")
        if kind == "battery_outage" and params.get("battery") not in self.batteries:
            raise ValueError(f"Unknown battery {params.get('battery')}")
        ev = Event(kind, at_step, duration_steps, params,
                   EVENT_KINDS[kind] if announced is None else announced)
        ev.description = self._describe(ev)
        self.events.append(ev)
        if ev.active(self.step):
            self._compute_current()
        return ev

    def inject_now(self, kind: str, duration_steps: int = 4, **params) -> Event:
        """Trigger an event immediately (used by the dashboard's 'chaos' buttons)."""
        return self.schedule(kind, self.step, duration_steps, **params)

    def _describe(self, ev: Event) -> str:
        start = (self.start + pd.Timedelta(minutes=STEP_MINUTES * ev.start_step)).strftime("%H:%M")
        mins = ev.duration_steps * STEP_MINUTES
        p = ev.params
        text = {
            "cloud_cover": f"Heavy cloud cover ({p.get('level', 0.85):.0%})",
            "storm": f"Storm with winds up to {p.get('wind_ms', 26)} m/s",
            "battery_outage": f"{p.get('battery')} unavailable (fault)",
            "price_spike": f"Market price spike x{p.get('multiplier', 1.6)}",
            "demand_surge": f"{p.get('consumer')} demand +{p.get('extra_mw', 20)} MW",
            "transmission_limit": f"Export line limited to {p.get('max_export_mw', 80)} MW",
            "maintenance": f"Planned maintenance on {p.get('asset')}",
        }[ev.kind]
        return f"{text} from {start} for {mins} min"

    def _active(self, kind: str, step: int | None = None, announced_only: bool = False) -> list[Event]:
        s = self.step if step is None else step
        return [e for e in self.events
                if e.kind == kind and e.active(s) and (e.announced or not announced_only)]

    # ---------------- dynamics ----------------
    def _cloud_target(self, step: int, announced_only: bool = False) -> float:
        target = self.CLOUD_MEAN
        for e in self._active("cloud_cover", step, announced_only):
            target = max(target, e.params.get("level", 0.85))
        if self._active("storm", step, announced_only):
            target = max(target, 0.9)
        return target

    def _wind_target(self, step: int, announced_only: bool = False) -> float:
        hour = self.hour_at(step)
        target = self.WIND_MEAN + 1.5 * math.cos(2 * math.pi * (hour - 3) / 24)  # windier at night
        for e in self._active("storm", step, announced_only):
            target = max(target, e.params.get("wind_ms", 26))
        return target

    def _advance_weather(self) -> None:
        ct = self._cloud_target(self.step)
        phi_c = 0.6 if ct > self.CLOUD_MEAN else self.CLOUD_PERSIST  # events move weather fast
        self.cloud = float(np.clip(ct + phi_c * (self.cloud - ct)
                                   + self.rng.normal(0, self.CLOUD_NOISE), 0, 1))
        wt = self._wind_target(self.step)
        phi_w = 0.5 if self._active("storm") else self.WIND_PERSIST
        self.wind_ms = float(np.clip(wt + phi_w * (self.wind_ms - wt)
                                     + self.rng.normal(0, self.WIND_NOISE), 0, 35))

    def _under_maintenance(self, step: int, announced_only: bool = False) -> set:
        return {e.params.get("asset") for e in self._active("maintenance", step, announced_only)}

    def _solar(self, step: int, cloud: float, noisy: bool, announced_only: bool = False) -> dict:
        clear = clear_sky_factor(self.hour_at(step))
        down = self._under_maintenance(step, announced_only)
        out = {}
        for f in self.config.solar:
            local = float(np.clip(cloud + (self.rng.normal(0, 0.05) if noisy else 0), 0, 1))
            mw = f.capacity_mw * f.performance * 0.85 * clear * (1 - 0.75 * local)
            out[f.name] = 0.0 if f.name in down else float(np.clip(mw, 0, f.capacity_mw))
        return out

    def _wind(self, step: int, wind_ms: float, noisy: bool, announced_only: bool = False) -> dict:
        down = self._under_maintenance(step, announced_only)
        out = {}
        for f in self.config.wind:
            v = wind_ms * f.site_factor + (self.rng.normal(0, 0.6) if noisy else 0)
            out[f.name] = 0.0 if f.name in down else f.capacity_mw * wind_power_fraction(v, f)
        return out

    def _demand(self, step: int, noisy: bool, announced_only: bool = False) -> dict:
        hour = self.hour_at(step)
        surges = self._active("demand_surge", step, announced_only)
        out = {}
        for c in self.config.consumers:
            mw = c.base_mw * demand_profile(c.profile, hour)
            if noisy:
                mw *= 1 + self.rng.normal(0, 0.02)
            mw += sum(e.params.get("extra_mw", 20) for e in surges if e.params.get("consumer") == c.name)
            out[c.name] = max(0.0, float(mw))
        return out

    def _price(self, step: int, noisy: bool, announced_only: bool = False) -> float:
        p = price_profile(self.hour_at(step))
        if noisy:
            p *= 1 + self.rng.normal(0, 0.04)
        for e in self._active("price_spike", step, announced_only):
            p *= e.params.get("multiplier", 1.6)
        m = self.config.market
        return float(np.clip(p, m.price_floor, m.price_cap))

    def _export_limit(self, step: int, announced_only: bool = False) -> float:
        lim = self.config.grid.max_export_mw
        for e in self._active("transmission_limit", step, announced_only):
            lim = min(lim, e.params.get("max_export_mw", 80))
        return lim

    def _compute_current(self) -> None:
        s = self.step
        for name, b in self.batteries.items():
            b.available = not any(e.params.get("battery") == name for e in self._active("battery_outage", s))
        solar = self._solar(s, self.cloud, noisy=True)
        wind = self._wind(s, self.wind_ms, noisy=True)
        demand = self._demand(s, noisy=True)
        surge_mw = sum(e.params.get("extra_mw", 20) for e in self._active("demand_surge", s))
        hour = self.hour_at(s)
        m = self.config.market
        self.current = {
            "solar": solar, "wind": wind, "demand": demand,
            "price": self._price(s, noisy=True),
            "frequency": float(self.config.grid.nominal_frequency_hz
                               + self.rng.normal(0, 0.015) - 0.002 * surge_mw),
            "max_export_mw": self._export_limit(s),
            "dr_incentive": m.dr_incentive_peak if 17 <= hour < 22 else m.dr_incentive_offpeak,
        }

    # ---------------- public API used by the agent ----------------
    def observe(self) -> dict:
        c = self.current
        flexible = sum(c["demand"][k.name] * k.flexible_share for k in self.config.consumers)
        m = self.config.market
        return {
            "step": self.step,
            "time": self.time.strftime("%Y-%m-%d %H:%M"),
            "hour": self.hour_at(self.step),
            "solar_mw": {k: round(v, 2) for k, v in c["solar"].items()},
            "wind_mw": {k: round(v, 2) for k, v in c["wind"].items()},
            "solar_total_mw": round(sum(c["solar"].values()), 2),
            "wind_total_mw": round(sum(c["wind"].values()), 2),
            "demand_mw": {k: round(v, 2) for k, v in c["demand"].items()},
            "demand_total_mw": round(sum(c["demand"].values()), 2),
            "flexible_demand_mw": round(flexible, 2),
            "price_inr_mwh": round(c["price"], 1),
            "carbon_price_inr_t": m.carbon_price,
            "grid_emission_factor_t_mwh": m.grid_emission_factor,
            "dr_incentive_inr_mwh": c["dr_incentive"],
            "grid_frequency_hz": round(c["frequency"], 3),
            "max_import_mw": self.config.grid.max_import_mw,
            "max_export_mw": c["max_export_mw"],
            "batteries": {k: b.status() for k, b in self.batteries.items()},
            "weather": {"cloud_cover": round(self.cloud, 3), "wind_speed_ms": round(self.wind_ms, 2)},
            "active_events": [e.description for e in self.events if e.active(self.step)],
            "alerts": [e.description for e in self.events
                       if e.announced and e.upcoming(self.step, self.ALERT_LOOKAHEAD)],
        }

    def forecast(self, horizon: int = 16) -> pd.DataFrame:
        """Expected values and uncertainty for the next `horizon` steps.

        Uses only information an operator would have: current weather, typical patterns
        and announced events. Surprises (unannounced events, noise) are not in it.
        Uncertainty (std) grows with the square root of lead time.
        """
        rows = []
        cloud, wind = self.cloud, self.wind_ms
        solar_cap = sum(f.capacity_mw for f in self.config.solar)
        wind_cap = sum(f.capacity_mw for f in self.config.wind)
        for k in range(1, horizon + 1):
            s = self.step + k
            ct = self._cloud_target(s, announced_only=True)
            cloud = ct + self.CLOUD_PERSIST * (cloud - ct)
            wt = self._wind_target(s, announced_only=True)
            wind = wt + self.WIND_PERSIST * (wind - wt)
            solar = sum(self._solar(s, cloud, False, True).values())
            wind_mw = sum(self._wind(s, wind, False, True).values())
            demand = sum(self._demand(s, False, True).values())
            price = self._price(s, False, True)
            lead = math.sqrt(k)
            rows.append({
                "step": s,
                "time": (self.start + pd.Timedelta(minutes=STEP_MINUTES * s)).strftime("%H:%M"),
                "solar_mw": solar, "solar_std": 0.03 * solar_cap * lead * clear_sky_factor(self.hour_at(s)),
                "wind_mw": wind_mw, "wind_std": min(0.35 * wind_cap, 0.025 * wind_cap * lead),
                "demand_mw": demand, "demand_std": 0.01 * demand * lead,
                "price": price, "price_std": 0.03 * price * lead,
                "max_export_mw": self._export_limit(s, announced_only=True),
            })
        return pd.DataFrame(rows)

    def advance(self, record: dict | None = None) -> None:
        """Log this step (with whatever actions the agent took) and move 15 minutes ahead."""
        obs = self.observe()
        row = {
            "step": obs["step"], "time": obs["time"],
            "solar_mw": obs["solar_total_mw"], "wind_mw": obs["wind_total_mw"],
            "demand_mw": obs["demand_total_mw"], "price": obs["price_inr_mwh"],
            "cloud": obs["weather"]["cloud_cover"], "wind_ms": obs["weather"]["wind_speed_ms"],
            "max_export_mw": obs["max_export_mw"], "frequency": obs["grid_frequency_hz"],
            "events": "; ".join(obs["active_events"]),
        }
        for name, b in self.batteries.items():
            row[f"{name}_soc"] = round(b.soc, 4)
            row[f"{name}_available"] = b.available
        if record:
            row.update(record)
        self.history.append(row)
        self.step += 1
        self._advance_weather()
        self._compute_current()

    def history_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.history)
