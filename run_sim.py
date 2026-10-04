"""Day 1 check: run one simulated day with NO orchestration (batteries idle).

This 'do-nothing' baseline shows the problem the agent must solve:
midday surplus that gets wasted, evening shortfalls bought at peak prices,
and disruptions that nobody reacts to.

Usage:  python run_sim.py [--seed 42]
"""
import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src.config import STEP_HOURS, STEPS_PER_DAY  # noqa: E402
from src.scenarios import demo_day  # noqa: E402
from src.simulator import GridSimulator  # noqa: E402


def run(seed: int) -> None:
    sim = GridSimulator(seed=seed)
    demo_day(sim)
    m = sim.config.market

    for _ in range(STEPS_PER_DAY):
        o = sim.observe()
        net = o["solar_total_mw"] + o["wind_total_mw"] - o["demand_total_mw"]
        export = min(max(net, 0), o["max_export_mw"])
        curtail = max(net, 0) - export                      # surplus the line cannot carry
        imp = max(-net, 0)
        cost = (imp - export) * o["price_inr_mwh"] * STEP_HOURS
        carbon_t = imp * m.grid_emission_factor * STEP_HOURS
        sim.advance({"import_mw": imp, "export_mw": export, "curtail_mw": curtail,
                     "net_cost_inr": cost, "carbon_t": carbon_t})

    df = sim.history_frame()
    out = Path("outputs")
    out.mkdir(exist_ok=True)
    df.to_csv(out / "day1_baseline.csv", index=False)

    h = STEP_HOURS
    renewable = (df.solar_mw + df.wind_mw).sum() * h
    print("\n=== Simulated day: NO orchestration (baseline) ===")
    print(f"Demand                : {df.demand_mw.sum() * h:8.0f} MWh")
    print(f"Renewable generation  : {renewable:8.0f} MWh")
    print(f"Imported from grid    : {df.import_mw.sum() * h:8.0f} MWh")
    print(f"Exported to grid      : {df.export_mw.sum() * h:8.0f} MWh")
    print(f"Curtailed (wasted)    : {df.curtail_mw.sum() * h:8.0f} MWh")
    print(f"Net energy cost       : ₹{df.net_cost_inr.sum():,.0f}")
    print(f"Carbon from imports   : {df.carbon_t.sum():8.1f} tCO2 "
          f"(₹{df.carbon_t.sum() * m.carbon_price:,.0f} at carbon price)")
    print("\nEvents during the day:")
    for e in sim.events:
        print("  -", e.description)

    # ---- chart ----
    t = list(range(len(df)))
    ticks = list(range(0, len(df) + 1, 8))
    labels = [f"{(i * 15) // 60:02d}:00" for i in ticks]
    fig, ax = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    ax[0].stackplot(t, df.solar_mw, df.wind_mw, labels=["Solar", "Wind"],
                    colors=["#F2B134", "#4C9BE8"], alpha=0.85)
    ax[0].plot(t, df.demand_mw, color="black", lw=2, label="Demand")
    ax[0].set_ylabel("MW")
    ax[0].set_title("Generation vs demand (no orchestration)")
    ax[0].legend(loc="upper left")
    ax[1].plot(t, df.price, color="#C0392B")
    ax[1].set_ylabel("₹/MWh")
    ax[1].set_title("Market price")
    ax[2].bar(t, df.import_mw, color="#7F8C8D", label="Import")
    ax[2].bar(t, -df.export_mw, color="#27AE60", label="Export")
    ax[2].bar(t, -df.curtail_mw, bottom=-df.export_mw, color="#E74C3C", label="Curtailed")
    ax[2].axhline(0, color="black", lw=0.8)
    ax[2].set_ylabel("MW")
    ax[2].set_title("Grid exchange")
    ax[2].legend(loc="upper left")
    for a in ax:
        for i, ev in enumerate(df.events):
            if ev:
                a.axvspan(i - 0.5, i + 0.5, color="#9B59B6", alpha=0.07, lw=0)
    ax[2].set_xticks(ticks)
    ax[2].set_xticklabels(labels)
    fig.text(0.01, 0.005, "Shaded purple = disruption events active", fontsize=9, color="#6C3483")
    fig.tight_layout()
    fig.savefig(out / "day1_baseline.png", dpi=110)
    print(f"\nSaved {out / 'day1_baseline.csv'} and {out / 'day1_baseline.png'}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    run(p.parse_args().seed)
