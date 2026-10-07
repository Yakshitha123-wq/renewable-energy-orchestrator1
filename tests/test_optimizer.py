"""Reliability tests for the optimizer (Day 2)."""
import pytest

from src.config import STEPS_PER_DAY
from src.controllers import CONTROLLERS, NoOrchestration, SimpleRules
from src.dispatch import run_step
from src.optimizer import Cheapest, Greenest, Optimizer, ReliabilityFirst
from src.scenarios import demo_day
from src.simulator import GridSimulator


def run_day(controller, seed=42):
    sim = GridSimulator(seed=seed)
    demo_day(sim)
    cost = unserved = 0.0
    soc_ok = True
    for _ in range(STEPS_PER_DAY):
        _, r = run_step(sim, controller)
        s = r["summary"]
        cost += s["total_cost_inr"]
        unserved += s["unserved_mw"]
        for b in sim.batteries.values():
            soc_ok &= b.spec.min_soc - 1e-6 <= b.soc <= b.spec.max_soc + 1e-6
    return cost, unserved, soc_ok


def test_registered_as_a_controller():
    assert "Optimizer" in CONTROLLERS


def test_beats_baselines_on_demo_day():
    opt, _, _ = run_day(Optimizer())
    assert opt < run_day(SimpleRules())[0]
    assert opt < run_day(NoOrchestration())[0]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_never_breaks_rules(seed):
    _, unserved, soc_ok = run_day(Optimizer(), seed)
    assert unserved == 0
    assert soc_ok


def test_never_charges_and_discharges_same_battery():
    sim = GridSimulator(seed=7)
    demo_day(sim)
    opt = Optimizer()
    for _ in range(STEPS_PER_DAY):
        d = opt.decide(sim)
        assert all(isinstance(v, float) for v in d.battery_mw.values())  # one signed number per battery
        run_step(sim, opt)


def test_offline_battery_gets_no_setpoint_effect():
    sim = GridSimulator(seed=3)
    sim.inject_now("battery_outage", 8, battery="BESS-2")
    opt = Optimizer()
    plan = opt.plan(sim)
    i = plan["names"].index("BESS-2")
    assert plan["charge"][:, i].max() == 0 and plan["discharge"][:, i].max() == 0


def test_energy_balance_in_plan():
    sim = GridSimulator(seed=5)
    p = Optimizer().plan(sim)
    lhs = p["gen"] - p["curtail"] + p["discharge"].sum(1) - p["charge"].sum(1) - p["demand"] + p["dr"]
    rhs = p["export"] - p["import"] - p["unserved"]
    assert abs(lhs - rhs).max() < 1e-5


def test_falls_back_when_solver_fails(monkeypatch):
    sim = GridSimulator(seed=2)
    opt = Optimizer()
    monkeypatch.setattr(opt, "plan", lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
    d = opt.decide(sim)
    assert "fell back" in d.reason


# ---------------------------------------------------------------- Day 3: trade-off modes
def run_day_detail(controller, seed=42):
    sim = GridSimulator(seed=seed)
    demo_day(sim)
    money = co2 = unserved = 0.0
    lowest = 1e9
    for _ in range(STEPS_PER_DAY):
        _, r = run_step(sim, controller)
        s = r["summary"]
        money += s["total_cost_inr"] - s["carbon_cost_inr"]
        co2 += s["carbon_t"]
        unserved += s["unserved_mw"]
        lowest = min(lowest, sum(b.energy_mwh for b in sim.batteries.values()))
    return money, co2, unserved, lowest


def test_all_modes_registered():
    for name in ("Optimizer: Cheapest", "Optimizer", "Optimizer: Greenest", "Optimizer: Reliability first"):
        assert name in CONTROLLERS


def test_modes_trade_cost_against_carbon():
    cheap, green = run_day_detail(Cheapest()), run_day_detail(Greenest())
    assert cheap[0] < green[0]      # cheapest spends less money
    assert green[1] < cheap[1]      # greenest emits less carbon


def test_reliability_mode_keeps_reserve_and_serves_all_load():
    rel, bal = run_day_detail(ReliabilityFirst()), run_day_detail(Optimizer())
    assert rel[2] == 0 and bal[2] == 0
    assert rel[3] > bal[3]          # higher lowest-battery-level


@pytest.mark.parametrize("mode", [Cheapest, Optimizer, Greenest, ReliabilityFirst])
def test_every_mode_respects_battery_limits(mode):
    _, _, unserved, lowest = run_day_detail(mode(), seed=11)
    assert unserved == 0
    assert lowest >= 0.1 * 200 - 1e-6   # never below the 10% floor of 200 MWh total


def test_scenario_weights_are_normalised():
    sim = GridSimulator(seed=4)
    _, scen, *_ = Optimizer()._inputs(sim)
    assert abs(sum(s["w"] for s in scen) - 1) < 1e-9
    assert len(scen) == 3 and len(Cheapest()._inputs(sim)[1]) == 1