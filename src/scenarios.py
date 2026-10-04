"""Ready-made event scenarios for demos and testing."""
from .simulator import GridSimulator


def demo_day(sim: GridSimulator, day: int = 0) -> None:
    """A 'bad day' that exercises every kind of disruption from the problem statement."""
    at = lambda clock: GridSimulator.step_of(clock, day)  # noqa: E731
    sim.schedule("cloud_cover", at("11:00"), 8, level=0.85)                 # clouds cut solar
    sim.schedule("battery_outage", at("14:00"), 12, battery="BESS-2")       # one battery fails
    sim.schedule("maintenance", at("16:00"), 8, asset="Wind-3")             # planned maintenance
    sim.schedule("price_spike", at("18:30"), 4, multiplier=1.6)             # prices spike
    sim.schedule("demand_surge", at("19:45"), 6, consumer="Steel plant", extra_mw=25)
    sim.schedule("transmission_limit", at("21:00"), 8, max_export_mw=80)    # line congestion
    sim.schedule("storm", at("22:30"), 6, wind_ms=26)                       # storm: turbines cut out for safety
