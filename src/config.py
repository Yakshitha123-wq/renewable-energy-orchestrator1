"""Portfolio configuration: the assets the orchestrator manages, grid limits and market assumptions.

All numbers here are assumptions for a realistic Indian utility-scale portfolio.
Change them in one place and the whole system adapts.
"""
from dataclasses import dataclass, field

STEP_MINUTES = 15
STEP_HOURS = STEP_MINUTES / 60          # 0.25 h: converts MW (power) to MWh (energy) per step
STEPS_PER_DAY = 24 * 60 // STEP_MINUTES  # 96 decisions per day


@dataclass(frozen=True)
class SolarFarm:
    name: str
    capacity_mw: float
    performance: float = 1.0   # site factor: panel quality, soiling, local irradiance


@dataclass(frozen=True)
class WindFarm:
    name: str
    capacity_mw: float
    site_factor: float = 1.0   # local wind speed relative to the regional wind speed
    cut_in_ms: float = 3.0     # below this the turbine does not spin
    rated_ms: float = 12.0     # at/above this the turbine gives full power
    cut_out_ms: float = 25.0   # above this the turbine shuts down for safety


@dataclass(frozen=True)
class BatterySpec:
    name: str
    capacity_mwh: float
    max_charge_mw: float
    max_discharge_mw: float
    efficiency: float = 0.95               # one-way efficiency (round trip ~0.90)
    min_soc: float = 0.10                  # never drain below 10% (protects battery life)
    max_soc: float = 0.95                  # never fill above 95%
    degradation_cost_per_mwh: float = 600  # ₹ of battery wear per MWh moved in or out


@dataclass(frozen=True)
class Consumer:
    name: str
    base_mw: float
    profile: str            # "flat", "day_shift" or "two_shift"
    flexible_share: float   # share of load that can be shifted/reduced via demand response


@dataclass(frozen=True)
class GridLimits:
    max_import_mw: float = 250.0
    max_export_mw: float = 180.0       # transmission line capacity for selling power
    nominal_frequency_hz: float = 50.0


@dataclass(frozen=True)
class MarketSpec:
    price_cap: float = 10_000.0          # ₹/MWh (Indian power exchange ceiling)
    price_floor: float = 1_500.0         # ₹/MWh
    grid_emission_factor: float = 0.71   # tCO2 per MWh imported from the grid (Indian grid average, approx.)
    carbon_price: float = 2_000.0        # ₹ per tCO2, assumed shadow carbon price
    dr_incentive_peak: float = 6_000.0   # ₹/MWh paid to consumers for demand response at peak
    dr_incentive_offpeak: float = 2_000.0


@dataclass(frozen=True)
class PortfolioConfig:
    solar: tuple
    wind: tuple
    batteries: tuple
    consumers: tuple
    grid: GridLimits = field(default_factory=GridLimits)
    market: MarketSpec = field(default_factory=MarketSpec)


DEFAULT_PORTFOLIO = PortfolioConfig(
    solar=(
        SolarFarm("Solar-1", 120, 1.00),
        SolarFarm("Solar-2", 100, 0.98),
        SolarFarm("Solar-3", 130, 1.03),
        SolarFarm("Solar-4", 80, 0.97),
        SolarFarm("Solar-5", 70, 0.95),
    ),
    wind=(
        WindFarm("Wind-1", 80, site_factor=1.10),
        WindFarm("Wind-2", 60, site_factor=1.00),
        WindFarm("Wind-3", 50, site_factor=0.90),
    ),
    batteries=(
        BatterySpec("BESS-1", capacity_mwh=120, max_charge_mw=50, max_discharge_mw=50),
        BatterySpec("BESS-2", capacity_mwh=80, max_charge_mw=40, max_discharge_mw=40),
    ),
    consumers=(
        Consumer("Steel plant", 70, "flat", 0.10),
        Consumer("Data centre", 30, "flat", 0.05),
        Consumer("Cement works", 40, "two_shift", 0.20),
        Consumer("Textile mill", 30, "day_shift", 0.30),
        Consumer("Cold storage", 20, "flat", 0.40),
    ),
)
