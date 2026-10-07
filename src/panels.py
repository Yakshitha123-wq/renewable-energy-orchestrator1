"""Dashboard panels added on Day 2: 'Compare controllers' and 'Optimizer plan'.

Kept out of app.py so the main file stays readable. Colours and the chart style
helper are passed in so the panels match the rest of the control-room design.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from .config import STEP_HOURS, STEPS_PER_DAY
from .controllers import CONTROLLERS
from .dispatch import run_step
from .optimizer import MODES
from .scenarios import demo_day
from .simulator import GridSimulator


@st.cache_data(show_spinner=False)
def simulate_day(controller_name: str, seed: int, with_events: bool) -> pd.DataFrame:
    """One full day under one controller. Same seed and events for every controller = fair test."""
    sim = GridSimulator(seed=seed)
    if with_events:
        demo_day(sim)
    ctrl = CONTROLLERS[controller_name]()
    rows = []
    cap = sum(b.spec.capacity_mwh for b in sim.batteries.values())
    for _ in range(STEPS_PER_DAY):
        _, r = run_step(sim, ctrl)
        s = r["summary"]
        rows.append({
            "time": sim.start + pd.Timedelta(minutes=15 * len(rows)),
            "cost": s["total_cost_inr"] - s["carbon_cost_inr"], "carbon_t": s["carbon_t"],
            "curtail_mwh": s["curtail_mw"] * STEP_HOURS, "unserved_mwh": s["unserved_mw"] * STEP_HOURS,
            "stored_mwh": sum(b.energy_mwh for b in sim.batteries.values()), "capacity_mwh": cap,
        })
    return pd.DataFrame(rows)


def render_compare(C: dict, style, seed: int, with_events: bool) -> None:
    st.markdown("**Same day, same weather, same disruptions: who runs the portfolio best?**")
    st.caption("Every controller faces identical conditions and is judged by the same physics and cost accounting. "
               "Running cost = money spent on power, demand response, battery wear and lost load (the carbon "
               "charge is shown separately so the trade-off is visible). Uses the sidebar scenario and seed.")
    if "compare_on" not in st.session_state:
        st.session_state.compare_on = False
    if st.button("Run comparison", type="primary", key="run_compare"):
        st.session_state.compare_on = True
    if not st.session_state.compare_on:
        st.markdown('<div class="empty">Press Run comparison to simulate the full day under every controller '
                    '(about 15 seconds the first time).</div>', unsafe_allow_html=True)
        return

    with st.spinner("Simulating 96 decisions per controller..."):
        days = {name: simulate_day(name, seed, with_events) for name in CONTROLLERS}
    base_name, best_name = "No orchestration", "Optimizer"
    tot = {n: {"cost": d.cost.sum(), "co2": d.carbon_t.sum(), "waste": d.curtail_mwh.sum(),
               "unserved": d.unserved_mwh.sum(), "reserve": d.stored_mwh.min()} for n, d in days.items()}

    b, o = tot[base_name], tot[best_name]
    saved, saved_pct = b["cost"] - o["cost"], 100 * (1 - o["cost"] / b["cost"])
    co2_saved, co2_pct = b["co2"] - o["co2"], 100 * (1 - o["co2"] / b["co2"])
    st.markdown(
        f'<div class="decision"><div class="who">Result for this day (balanced optimizer vs no orchestration)</div>'
        f'Running cost down <b>₹{saved / 1e5:,.1f} lakh ({saved_pct:.0f}%)</b>, carbon down '
        f'<b>{co2_saved:,.0f} tCO2 ({co2_pct:.0f}%)</b>, with <b>{o["unserved"]:.1f} MWh</b> of demand left '
        f'unserved. Pick a different priority and the numbers move: see the trade-off chart below.</div>',
        unsafe_allow_html=True)

    names = list(days)
    cheapest = min(t["cost"] for t in tot.values())
    greenest = min(t["co2"] for t in tot.values())
    for row in (names[:3], names[3:]):
        for col, name in zip(st.columns(3), row):
            t = tot[name]
            tags = (" · lowest cost" if t["cost"] == cheapest else "") + (" · lowest carbon" if t["co2"] == greenest else "")
            col.markdown(
                f'<div class="readings"><div class="reading"><span class="k"><b>{name}</b>{tags}</span></div>'
                f'<div class="reading"><span class="k">Running cost</span><span class="v">₹{t["cost"] / 1e5:,.1f}<small>lakh</small></span></div>'
                f'<div class="reading"><span class="k">Carbon</span><span class="v">{t["co2"]:,.0f}<small>tCO2</small></span></div>'
                f'<div class="reading"><span class="k">Lowest battery reserve</span><span class="v">{t["reserve"]:,.0f}<small>MWh</small></span></div>'
                f'<div class="reading"><span class="k">Demand not served</span>'
                f'<span class="v{" bad" if t["unserved"] > 0.01 else ""}">{t["unserved"]:,.1f}<small>MWh</small></span></div></div>',
                unsafe_allow_html=True)

    palette = {"No orchestration": C["grid"], "Simple rules": C["warn"], "Optimizer: Cheapest": C["wind"],
               "Optimizer": C["storage"], "Optimizer: Greenest": "#4F9D2F", "Optimizer: Reliability first": C["alarm"]}
    st.markdown("**Trade-off: what each priority costs and saves**")
    sc = go.Figure()
    for name, t in tot.items():
        sc.add_trace(go.Scatter(x=[t["cost"] / 1e5], y=[t["co2"]], mode="markers+text", name=name,
                                text=[name.replace("Optimizer: ", "")], textposition="top center",
                                marker=dict(size=16, color=palette.get(name, C["ink"])), showlegend=False))
    sc.update_xaxes(title="Running cost (₹ lakh), lower is better")
    sc.update_yaxes(title="Carbon (tCO2), lower is better")
    st.plotly_chart(style(sc, 380), width="stretch")
    st.caption("Bottom-left is best. Cheapest, Balanced and Greenest slide along the cost-versus-carbon frontier; "
               "Reliability first deliberately pays more to keep a battery reserve against storms and outages.")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                        subplot_titles=("Cumulative running cost (₹ lakh)", "Energy held in batteries (MWh)"))
    for name, d in days.items():
        color = palette.get(name, C["ink"])
        width = 3 if name == best_name else 2
        fig.add_trace(go.Scatter(x=d.time, y=d.cost.cumsum() / 1e5, name=name,
                                 line=dict(color=color, width=width), legendgroup=name), 1, 1)
        fig.add_trace(go.Scatter(x=d.time, y=d.stored_mwh, name=name, showlegend=False,
                                 line=dict(color=color, width=width), legendgroup=name), 2, 1)
    st.plotly_chart(style(fig, 560), width="stretch")
    st.caption("Look at the evening: optimizer modes hold energy through the cheap midday hours and release it "
               "at the price peak, while simple rules have already emptied the batteries.")


def render_plan(sim, C: dict, style) -> None:
    st.markdown("**What the optimizer plans for the next 10 hours, from this moment**")
    if sim.step >= STEPS_PER_DAY:
        st.markdown('<div class="empty">The day is over. Reset the day to see a new plan.</div>',
                    unsafe_allow_html=True)
        return
    by_name = {m.name: m for m in MODES}
    mode = st.selectbox("Priority to plan for", list(by_name), index=1, key="plan_mode",
                        help="See how the same moment is planned differently for each priority.")
    st.caption(by_name[mode].description)
    try:
        p = by_name[mode]().plan(sim)
    except Exception as err:  # keep the dashboard alive if the solver fails
        st.warning(f"The optimizer could not produce a plan right now: {err}")
        return

    H, T = STEP_HOURS, len(p["price"])
    x = [sim.time + pd.Timedelta(minutes=15 * k) for k in range(T)]
    net_batt = (p["charge"] - p["discharge"]).sum(axis=1)               # + charging, - discharging
    stored = []
    level = sum(b.energy_mwh for b in sim.batteries.values())
    for t in range(T):
        for i, name in enumerate(p["names"]):
            eff = sim.batteries[name].spec.efficiency
            level += (p["charge"][t, i] * eff - p["discharge"][t, i] / eff) * H
        stored.append(level)
    grid = p["import"] - p["export"]

    peak_i = int(np.argmax(p["price"]))
    c_mwh, d_mwh = p["charge"].sum() * H, p["discharge"].sum() * H
    st.markdown(
        f'<div class="decision"><div class="who">Plan summary</div>'
        f'Buy low, sell high: charge <b>{c_mwh:,.0f} MWh</b>, discharge <b>{d_mwh:,.0f} MWh</b>. '
        f'Highest expected price <b>₹{p["price"][peak_i]:,.0f}/MWh at {x[peak_i]:%H:%M}</b>. '
        f'Only the first 15 minutes are applied; the plan is rebuilt every step with fresh data.</div>',
        unsafe_allow_html=True)

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                        subplot_titles=("Expected market price (₹/MWh)",
                                        "Battery action (MW, + charging, − discharging)",
                                        "Planned battery energy (MWh) and grid exchange (MW, + buying)"),
                        row_heights=[0.28, 0.36, 0.36], specs=[[{}], [{}], [{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=x, y=p["price"], name="Price", line=dict(color=C["ink"], width=2.5)), 1, 1)
    fig.add_trace(go.Bar(x=x, y=np.where(net_batt > 0, net_batt, 0), name="Charging",
                         marker_color=C["storage"]), 2, 1)
    fig.add_trace(go.Bar(x=x, y=np.where(net_batt < 0, net_batt, 0), name="Discharging",
                         marker_color=C["solar"]), 2, 1)
    fig.add_trace(go.Scatter(x=x, y=stored, name="Stored energy", line=dict(color=C["storage"], width=2.5)),
                  3, 1, secondary_y=False)
    fig.add_trace(go.Scatter(x=x, y=grid, name="Grid exchange", line=dict(color=C["grid"], width=2, dash="dot")),
                  3, 1, secondary_y=True)
    fig.update_layout(barmode="relative")
    st.plotly_chart(style(fig, 640), width="stretch")
    st.caption("Plan uses the forecast, so it knows announced events (storms, maintenance, line limits) but "
               "not surprises. That is why it is re-planned every 15 minutes.")