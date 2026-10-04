from src.config import STEPS_PER_DAY
from src.controllers import CONTROLLERS
from src.dispatch import Decision, run_step, settle
from src.scenarios import demo_day
from src.simulator import GridSimulator


def test_energy_balances_every_step_for_every_controller():
    for ctrl_cls in CONTROLLERS.values():
        sim = GridSimulator(seed=11)
        demo_day(sim)
        ctrl = ctrl_cls()
        for _ in range(STEPS_PER_DAY):
            obs = sim.observe()
            gen = obs["solar_total_mw"] + obs["wind_total_mw"]
            _, r = run_step(sim, ctrl)
            s = r["summary"]
            supply = gen - s["curtail_mw"] + s["discharge_mw"] + s["import_mw"] + s["unserved_mw"]
            use = obs["demand_total_mw"] - s["dr_mw"] + s["charge_mw"] + s["export_mw"]
            assert abs(supply - use) < 0.01
            assert s["export_mw"] <= obs["max_export_mw"] + 1e-6


def test_settle_clips_impossible_requests():
    sim = GridSimulator()
    r = settle(sim, Decision(battery_mw={"BESS-1": 999, "BESS-2": -999}, curtail_mw=-5, demand_response_mw=1e6))
    assert r["battery_flow"]["BESS-1"] <= sim.config.batteries[0].max_charge_mw + 1e-6
    assert r["summary"]["dr_mw"] <= sim.observe()["flexible_demand_mw"] + 1e-6
    assert r["summary"]["curtail_mw"] >= 0
