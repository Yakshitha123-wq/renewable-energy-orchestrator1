import pytest

from src.config import STEPS_PER_DAY
from src.scenarios import demo_day
from src.simulator import GridSimulator


def run_day(seed=1, events=True):
    sim = GridSimulator(seed=seed)
    if events:
        demo_day(sim)
    obs = []
    for _ in range(STEPS_PER_DAY):
        obs.append(sim.observe())
        sim.advance()
    return sim, obs


def test_solar_is_zero_at_night():
    _, obs = run_day()
    for o in obs:
        if o["hour"] < 6 or o["hour"] >= 18:
            assert o["solar_total_mw"] == 0


def test_outputs_within_capacity():
    sim, obs = run_day()
    caps = {f.name: f.capacity_mw for f in sim.config.solar + sim.config.wind}
    for o in obs:
        for name, mw in {**o["solar_mw"], **o["wind_mw"]}.items():
            assert 0 <= mw <= caps[name] + 1e-6
        assert sim.config.market.price_floor <= o["price_inr_mwh"] <= sim.config.market.price_cap


def test_same_seed_is_reproducible():
    _, a = run_day(seed=7)
    _, b = run_day(seed=7)
    assert [o["demand_total_mw"] for o in a] == [o["demand_total_mw"] for o in b]


def test_battery_respects_limits():
    sim = GridSimulator()
    b = sim.batteries["BESS-1"]
    for _ in range(40):
        b.apply(charge_mw=999)
    assert b.soc <= b.spec.max_soc + 1e-9
    for _ in range(40):
        b.apply(discharge_mw=999)
    assert b.soc >= b.spec.min_soc - 1e-9
    with pytest.raises(ValueError):
        b.apply(charge_mw=10, discharge_mw=10)


def test_battery_outage_and_recovery():
    sim = GridSimulator()
    sim.schedule("battery_outage", at_step=2, duration_steps=3, battery="BESS-2")
    seen = []
    for _ in range(7):
        seen.append(sim.observe()["batteries"]["BESS-2"]["available"])
        sim.advance()
    assert seen == [True, True, False, False, False, True, True]
    assert sim.observe()["batteries"]["BESS-2"]["max_charge_mw"] > 0


def test_storm_cuts_out_high_wind_turbines():
    sim = GridSimulator(seed=3)
    sim.schedule("storm", at_step=0, duration_steps=20, wind_ms=30)
    for _ in range(10):
        sim.advance()
    assert sim.observe()["wind_total_mw"] < 20  # turbines shut down above cut-out speed


def test_announced_events_appear_as_alerts_and_in_forecast():
    sim = GridSimulator()
    sim.schedule("transmission_limit", at_step=8, duration_steps=8, max_export_mw=60)
    sim.schedule("price_spike", at_step=8, duration_steps=4, multiplier=2.0)  # surprise
    assert any("Export line" in a for a in sim.observe()["alerts"])
    assert not any("price spike" in a.lower() for a in sim.observe()["alerts"])
    fc = sim.forecast(16)
    assert fc.loc[fc.step == 8, "max_export_mw"].item() == 60


def test_forecast_uncertainty_grows():
    fc = GridSimulator().forecast(16)
    assert fc.demand_std.iloc[-1] > fc.demand_std.iloc[0]
    assert len(fc) == 16
