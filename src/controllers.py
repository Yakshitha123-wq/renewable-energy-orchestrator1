"""Controllers that decide what to do each 15 minutes.

These two are the comparison baselines. The optimizer (Day 2) and the AI agent (Day 4)
plug in with the same `decide(sim) -> Decision` interface.
"""
from .dispatch import Decision


class NoOrchestration:
    name = "No orchestration"
    description = "Batteries stay idle. Surplus is sold, shortfalls are bought."

    def decide(self, sim) -> Decision:
        return Decision(reason="No orchestration: batteries idle, grid absorbs the imbalance.")


class SimpleRules:
    name = "Simple rules"
    description = "Charge batteries with any surplus, discharge them during any shortfall."

    def decide(self, sim) -> Decision:
        o = sim.observe()
        net = o["solar_total_mw"] + o["wind_total_mw"] - o["demand_total_mw"]
        plan, remaining = {}, abs(net)
        for name, b in o["batteries"].items():
            cap = b["max_charge_mw"] if net > 0 else b["max_discharge_mw"]
            mw = min(cap, remaining)
            remaining -= mw
            plan[name] = mw if net > 0 else -mw
        if net > 0:
            why = f"Surplus of {net:.0f} MW, so charging batteries with what they can take."
        else:
            why = f"Shortfall of {-net:.0f} MW, so discharging batteries before buying from the grid."
        return Decision(battery_mw=plan, reason=f"Simple rules: {why}")


CONTROLLERS = {c.name: c for c in (NoOrchestration, SimpleRules)}
