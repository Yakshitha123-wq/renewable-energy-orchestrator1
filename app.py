"""Control-room dashboard for the Renewable Energy Orchestrator.

Run:  streamlit run app.py
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.config import STEP_HOURS, STEPS_PER_DAY
from src.controllers import CONTROLLERS
from src.dispatch import run_step
from src.scenarios import demo_day
from src.simulator import GridSimulator

# ---------------------------------------------------------------- design tokens
C = {
    "panel": "#E6E8EA", "surface": "#F7F8F9", "ink": "#1E2830", "muted": "#66737D",
    "line": "#C9CED3", "solar": "#C98A0B", "wind": "#2C7BB6", "storage": "#1F8A70",
    "grid": "#5B6770", "alarm": "#C0392B", "warn": "#B7860B",
}
FONT = "Barlow, 'Segoe UI', sans-serif"

st.set_page_config(page_title="Renewable Energy Orchestrator", page_icon="⚡", layout="wide")

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Semi+Condensed:wght@500;600&display=swap');
.stApp, .stApp p, .stApp label, .stApp button, .stApp input, .stApp textarea,
.stApp h1, .stApp h2, .stApp h3, .stApp li, .stApp td, .stApp th {{ font-family: {FONT}; }}
[data-testid="stIconMaterial"] {{ font-family: 'Material Symbols Rounded' !important; }}
.block-container {{ padding-top: 1.4rem; max-width: 1400px; }}
.topbar {{ display:flex; justify-content:space-between; align-items:flex-end; gap:1rem;
  border-bottom:2px solid {C['ink']}; padding-bottom:.6rem; margin-bottom:.8rem; flex-wrap:wrap; }}
.topbar h1 {{ font-size:1.65rem; font-weight:700; margin:0; color:{C['ink']}; letter-spacing:-.01em; }}
.topbar .sub {{ color:{C['muted']}; font-size:.95rem; margin-top:.15rem; }}
.clock {{ text-align:right; }}
.clock .t {{ font-family:'Barlow Semi Condensed',sans-serif; font-size:2.1rem; font-weight:600;
  font-variant-numeric:tabular-nums; line-height:1; color:{C['ink']}; }}
.clock .d {{ color:{C['muted']}; font-size:.9rem; }}
.daybar {{ height:4px; background:{C['line']}; margin-top:.35rem; width:220px; margin-left:auto; }}
.daybar span {{ display:block; height:4px; background:{C['ink']}; }}
.alarms {{ display:flex; gap:.5rem; flex-wrap:wrap; margin-bottom:.9rem; }}
.chip {{ padding:.35rem .7rem; font-size:.92rem; border-left:4px solid; background:{C['surface']}; }}
.chip.active {{ border-color:{C['alarm']}; color:{C['ink']}; }}
.chip.active b {{ color:{C['alarm']}; }}
.chip.alert {{ border-color:{C['warn']}; }}
.chip.alert b {{ color:{C['warn']}; }}
.chip.ok {{ border-color:{C['storage']}; color:{C['muted']}; }}
.readings {{ background:{C['surface']}; border:1px solid {C['line']}; padding:.4rem 1rem; }}
.reading {{ display:flex; justify-content:space-between; align-items:baseline;
  padding:.55rem 0; border-bottom:1px solid {C['line']}; }}
.reading:last-child {{ border-bottom:none; }}
.reading .k {{ color:{C['muted']}; font-size:.95rem; }}
.reading .v {{ font-family:'Barlow Semi Condensed',sans-serif; font-size:1.45rem; font-weight:600;
  font-variant-numeric:tabular-nums; color:{C['ink']}; }}
.reading .v.bad {{ color:{C['alarm']}; }}
.reading .v small {{ font-size:.85rem; color:{C['muted']}; font-weight:500; margin-left:.2rem; }}
.decision {{ background:{C['surface']}; border-left:4px solid {C['ink']}; padding:.7rem 1rem;
  margin:.2rem 0 1rem; font-size:1.02rem; }}
.decision .who {{ color:{C['muted']}; font-size:.88rem; margin-bottom:.15rem; }}
.empty {{ color:{C['muted']}; padding:1.2rem 0; }}
svg.flow {{ width:100%; height:auto; display:block; font-family:{FONT}; }}
svg.flow .box {{ fill:{C['surface']}; stroke:{C['line']}; }}
svg.flow .track {{ fill:{C['panel']}; }}
svg.flow .ttl {{ font-size:16px; font-weight:600; fill:{C['ink']}; }}
svg.flow .num {{ font-family:'Barlow Semi Condensed',sans-serif; font-size:17px; font-weight:600; fill:{C['ink']}; }}
svg.flow .lbl {{ font-size:13.5px; fill:{C['muted']}; font-variant-numeric:tabular-nums; }}
svg.flow .fwd {{ animation: flow 1.2s linear infinite; }}
svg.flow .rev {{ animation: flow 1.2s linear infinite reverse; }}
@keyframes flow {{ to {{ stroke-dashoffset: -32; }} }}
@media (prefers-reduced-motion: reduce) {{ svg.flow .fwd, svg.flow .rev {{ animation:none; }} }}
</style>
""", unsafe_allow_html=True)

EVENT_LABELS = {
    "cloud_cover": "Heavy cloud cover", "storm": "Storm", "battery_outage": "Battery fault",
    "price_spike": "Price spike", "demand_surge": "Demand surge",
    "transmission_limit": "Export line limit", "maintenance": "Maintenance",
}
SCENARIOS = {"Demo day (7 disruptions)": True, "Calm day (no scheduled events)": False}


# ---------------------------------------------------------------- state
def reset(seed: int, scenario: str) -> None:
    sim = GridSimulator(seed=seed)
    if SCENARIOS[scenario]:
        demo_day(sim)
    st.session_state.sim = sim
    st.session_state.last = None


if "sim" not in st.session_state:
    reset(42, "Demo day (7 disruptions)")
sim: GridSimulator = st.session_state.sim


def advance(n: int, controller_name: str) -> None:
    ctrl = CONTROLLERS[controller_name]()
    for _ in range(n):
        if sim.step >= STEPS_PER_DAY:
            break
        st.session_state.last = run_step(sim, ctrl)


# ---------------------------------------------------------------- sidebar controls
with st.sidebar:
    st.subheader("Run the day")
    mode = st.radio("Who is in control", list(CONTROLLERS), index=0,
                    help="The optimizer and the AI agent join this list as they are built.")
    st.caption(CONTROLLERS[mode].description)
    done = sim.step >= STEPS_PER_DAY
    c1, c2 = st.columns(2)
    if c1.button("+15 min", width="stretch", disabled=done):
        advance(1, mode)
        st.rerun()
    if c2.button("+1 hour", width="stretch", disabled=done):
        advance(4, mode)
        st.rerun()
    if st.button("Run to end of day", width="stretch", disabled=done, type="primary"):
        advance(STEPS_PER_DAY, mode)
        st.rerun()

    st.divider()
    st.subheader("Trigger a disruption")
    kind = st.selectbox("Disruption", list(EVENT_LABELS), format_func=EVENT_LABELS.get)
    params = {}
    if kind == "cloud_cover":
        params["level"] = st.slider("Cloud cover", 0.5, 1.0, 0.85, 0.05)
    elif kind == "storm":
        params["wind_ms"] = st.slider("Wind speed (m/s)", 15, 32, 26)
    elif kind == "battery_outage":
        params["battery"] = st.selectbox("Battery", list(sim.batteries))
    elif kind == "price_spike":
        params["multiplier"] = st.slider("Price multiplier", 1.2, 3.0, 1.8, 0.1)
    elif kind == "demand_surge":
        params["consumer"] = st.selectbox("Consumer", [c.name for c in sim.config.consumers])
        params["extra_mw"] = st.slider("Extra demand (MW)", 5, 60, 25, 5)
    elif kind == "transmission_limit":
        params["max_export_mw"] = st.slider("Export limit (MW)", 0, 150, 60, 10)
    elif kind == "maintenance":
        params["asset"] = st.selectbox("Asset", [f.name for f in sim.config.solar + sim.config.wind])
    minutes = st.slider("Duration (minutes)", 15, 240, 60, 15)
    if st.button("Trigger now", width="stretch", disabled=done):
        sim.inject_now(kind, duration_steps=minutes // 15, **params)
        st.rerun()

    st.divider()
    st.subheader("Start over")
    scenario = st.selectbox("Scenario", list(SCENARIOS))
    seed = st.number_input("Weather seed", 0, 9999, 42, help="Same seed, same weather: fair comparisons.")
    if st.button("Reset day", width="stretch"):
        reset(int(seed), scenario)
        st.rerun()

# ---------------------------------------------------------------- header + alarms
obs = sim.observe()
shown_step = min(sim.step, STEPS_PER_DAY)
clock = (sim.start + pd.Timedelta(minutes=15 * shown_step))
st.markdown(f"""
<div class="topbar">
  <div><h1>Renewable Energy Orchestrator</h1>
  <div class="sub">5 solar farms, 3 wind farms, 2 batteries, 5 industrial consumers. Controller: {mode}</div></div>
  <div class="clock"><div class="t">{'24:00' if done else clock.strftime('%H:%M')}</div>
  <div class="d">{sim.start.strftime('%a %d %b %Y')}, step {shown_step} of {STEPS_PER_DAY}</div>
  <div class="daybar"><span style="width:{100 * shown_step / STEPS_PER_DAY:.1f}%"></span></div></div>
</div>""", unsafe_allow_html=True)

chips = [f'<div class="chip active"><b>Active</b> {e}</div>' for e in obs["active_events"]]
chips += [f'<div class="chip alert"><b>Coming up</b> {e}</div>' for e in obs["alerts"]]
if not chips:
    chips = ['<div class="chip ok">No active disruptions or alerts</div>']
st.markdown(f'<div class="alarms">{"".join(chips)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- power-flow diagram
def flow_line(x1, y1, x2, y2, mw, color, toward_end=True):
    if mw < 0.5:
        return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{C["line"]}" stroke-width="2"/>'
    w = min(3 + mw / 12, 16)
    cls = "fwd" if toward_end else "rev"
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-opacity=".25" stroke-width="{w}"/>'
            f'<line class="{cls}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
            f'stroke-width="{max(2, w / 3):.1f}" stroke-dasharray="6 10"/>')


def diagram(obs, last) -> str:
    """Single-line power-flow diagram: sources left, bus in the middle, loads and grid right."""
    if last:
        o, flows, s = last[1]["obs"], last[1]["battery_flow"], last[1]["summary"]
    else:
        o, flows, s = obs, {k: 0.0 for k in obs["batteries"]}, None
    solar, wind = o["solar_mw"], o["wind_mw"]
    batt = sim.observe()["batteries"]
    imp, exp_, curt, dr = ((s["import_mw"], s["export_mw"], s["curtail_mw"], s["dr_mw"]) if s else (0, 0, 0, 0))
    caps = {f.name: f.capacity_mw for f in sim.config.solar + sim.config.wind}
    LX, LW, BX, RX, RW, ROW = 4, 250, 395, 540, 256, 22
    parts = []

    def box(x, y, w, h, title, value="", vcolor=None):
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" class="box"/>')
        parts.append(f'<text x="{x + 14}" y="{y + 26}" class="ttl">{title}</text>')
        if value:
            fill = f' fill="{vcolor}"' if vcolor else ""
            parts.append(f'<text x="{x + w - 14}" y="{y + 26}" class="num" text-anchor="end"{fill}>{value}</text>')

    def farms(y, title, data, color):
        h = 44 + ROW * len(data)
        box(LX, y, LW, h, title, f"{sum(data.values()):.0f} MW", color)
        for i, (name, mw) in enumerate(data.items()):
            yy = y + 44 + i * ROW
            frac = mw / caps[name] if caps[name] else 0
            parts.append(f'<text x="{LX + 14}" y="{yy + 11}" class="lbl">{name}</text>')
            parts.append(f'<rect x="{LX + 90}" y="{yy + 1}" width="110" height="11" class="track"/>')
            parts.append(f'<rect x="{LX + 90}" y="{yy + 1}" width="{110 * frac:.1f}" height="11" fill="{color}"/>')
            parts.append(f'<text x="{LX + LW - 14}" y="{yy + 11}" class="lbl" text-anchor="end">{mw:.0f}</text>')
        return y + h / 2, h

    ys, hs = farms(28, "Solar", solar, C["solar"])
    yw, hw = farms(28 + hs + 14, "Wind", wind, C["wind"])
    yb = 28 + hs + 14 + hw + 14
    box(LX, yb, LW, 44 + ROW * 2 + 8, "Storage")
    total_flow = sum(flows.values())
    for i, (name, b) in enumerate(batt.items()):
        yy = yb + 44 + i * (ROW + 4)
        f = flows.get(name, 0.0)
        state = "offline" if not b["available"] else ("charging" if f > 0.5 else "discharging" if f < -0.5 else "idle")
        col = C["alarm"] if not b["available"] else C["storage"]
        parts.append(f'<text x="{LX + 14}" y="{yy + 12}" class="lbl">{name}</text>')
        parts.append(f'<rect x="{LX + 82}" y="{yy}" width="56" height="15" class="track" stroke="{col}"/>')
        parts.append(f'<rect x="{LX + 82}" y="{yy}" width="{56 * b["soc"]:.1f}" height="15" fill="{col}"/>')
        parts.append(f'<text x="{LX + 146}" y="{yy + 12}" class="lbl">{b["soc"]:.0%}</text>')
        parts.append(f'<text x="{LX + LW - 14}" y="{yy + 12}" class="lbl" text-anchor="end" fill="{col}">{state}</text>')
    hb = 44 + ROW * 2 + 8

    dem = o["demand_mw"]
    hc = 44 + ROW * len(dem)
    box(RX, 28, RW, hc, "Industrial demand", f"{sum(dem.values()) - dr:.0f} MW")
    for i, (name, mw) in enumerate(dem.items()):
        yy = 28 + 44 + i * ROW
        parts.append(f'<text x="{RX + 14}" y="{yy + 11}" class="lbl">{name}</text>')
        parts.append(f'<text x="{RX + RW - 14}" y="{yy + 11}" class="lbl" text-anchor="end">{mw:.0f}</text>')
    yg, hg = 28 + hc + 14, 112
    gnet = imp - exp_
    gtxt = f"Buying {imp:.0f} MW" if imp > 0.5 else f"Selling {exp_:.0f} MW" if exp_ > 0.5 else "Balanced"
    box(RX, yg, RW, hg, "Grid", gtxt)
    parts.append(f'<text x="{RX + 14}" y="{yg + 54}" class="lbl">Price ₹{o["price_inr_mwh"]:,.0f}/MWh</text>')
    parts.append(f'<text x="{RX + 14}" y="{yg + 76}" class="lbl">Export limit {o["max_export_mw"]:.0f} MW</text>')
    parts.append(f'<text x="{RX + 14}" y="{yg + 98}" class="lbl">Frequency {o["grid_frequency_hz"]:.2f} Hz</text>')
    if curt > 0.5:
        parts.append(f'<text x="{RX + RW - 14}" y="{yg + 98}" class="lbl" text-anchor="end" '
                     f'fill="{C["alarm"]}">Wasting {curt:.0f} MW</text>')

    bottom = max(yb + hb, yg + hg)
    lines = [
        f'<line x1="{BX}" y1="28" x2="{BX}" y2="{bottom}" stroke="{C["ink"]}" stroke-width="6"/>',
        f'<text x="{BX}" y="16" class="lbl" text-anchor="middle">Portfolio bus</text>',
        flow_line(LX + LW, ys, BX, ys, sum(solar.values()), C["solar"]),
        flow_line(LX + LW, yw, BX, yw, sum(wind.values()), C["wind"]),
        flow_line(LX + LW, yb + hb / 2, BX, yb + hb / 2, abs(total_flow), C["storage"], toward_end=total_flow < 0),
        flow_line(BX, 28 + hc / 2, RX, 28 + hc / 2, sum(dem.values()) - dr, C["ink"]),
        flow_line(BX, yg + hg / 2, RX, yg + hg / 2, abs(gnet), C["grid"], toward_end=gnet < 0),
    ]
    return (f'<svg class="flow" viewBox="0 0 800 {bottom + 6:.0f}" role="img" '
            f'aria-label="Live power flow between assets, consumers and the grid">{"".join(lines + parts)}</svg>')


# ---------------------------------------------------------------- main panel
hist = sim.history_frame()
left, right = st.columns([2.2, 1], gap="large")
with left:
    st.markdown(diagram(obs, st.session_state.last), unsafe_allow_html=True)
with right:
    if hist.empty:
        cost = carbon = curtailed = unserved = 0.0
        share = None
    else:
        cost = hist.total_cost_inr.sum()
        carbon = hist.carbon_t.sum()
        curtailed = hist.curtail_mw.sum() * STEP_HOURS
        unserved = hist.unserved_mw.sum() * STEP_HOURS
        demand_e = hist.demand_mw.sum() * STEP_HOURS
        share = min(1.0, (hist.renewable_used_mw.sum() - hist.export_mw.sum()).clip(min=0) * STEP_HOURS
                    / demand_e) if demand_e else None
    st.markdown(f"""
<div class="readings">
 <div class="reading"><span class="k">Total cost so far</span><span class="v">₹{cost / 1e5:,.1f}<small>lakh</small></span></div>
 <div class="reading"><span class="k">Carbon from grid power</span><span class="v">{carbon:,.0f}<small>tCO2</small></span></div>
 <div class="reading"><span class="k">Own clean power share</span><span class="v">{'–' if share is None else f'{share:.0%}'}</span></div>
 <div class="reading"><span class="k">Clean power wasted</span><span class="v{' bad' if curtailed > 1 else ''}">{curtailed:,.0f}<small>MWh</small></span></div>
 <div class="reading"><span class="k">Demand not served</span><span class="v{' bad' if unserved > 0.01 else ''}">{unserved:,.1f}<small>MWh</small></span></div>
</div>""", unsafe_allow_html=True)
    st.caption("Total cost includes energy bought minus sold, carbon, battery wear and demand response payments.")

if st.session_state.last:
    st.markdown(f'<div class="decision"><div class="who">Latest decision, {st.session_state.last[1]["obs"]["time"][-5:]}</div>'
                f'{st.session_state.last[0].reason}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="decision"><div class="who">Ready</div>Choose who is in control, then advance time '
                'from the sidebar. Trigger disruptions at any moment to see how the controller reacts.</div>',
                unsafe_allow_html=True)


def style(fig, height):
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=40, b=10), paper_bgcolor=C["surface"],
                      plot_bgcolor=C["surface"], font=dict(family=FONT, color=C["ink"], size=13),
                      legend=dict(orientation="h", yanchor="top", y=-0.06, x=0), hovermode="x unified")
    fig.update_xaxes(gridcolor=C["panel"], linecolor=C["line"])
    fig.update_yaxes(gridcolor=C["panel"], linecolor=C["line"], zeroline=False)
    return fig


tab_day, tab_fc, tab_assets, tab_log = st.tabs(["Day so far", "Next 4 hours", "Assets", "Event and decision log"])

with tab_day:
    if hist.empty:
        st.markdown('<div class="empty">Nothing has happened yet. Advance time to fill these charts.</div>',
                    unsafe_allow_html=True)
    else:
        t = pd.to_datetime(hist.time)
        day_range = [sim.start, sim.start + pd.Timedelta(hours=24)]
        fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                            subplot_titles=("Generation and demand (MW)", "Battery charge level",
                                            "Market price (₹/MWh)", "Grid exchange (MW, + buying, − selling)"),
                            row_heights=[0.34, 0.2, 0.2, 0.26])
        fig.add_trace(go.Scatter(x=t, y=hist.solar_mw, name="Solar", stackgroup="g", line=dict(width=0),
                                 fillcolor=C["solar"]), 1, 1)
        fig.add_trace(go.Scatter(x=t, y=hist.wind_mw, name="Wind", stackgroup="g", line=dict(width=0),
                                 fillcolor=C["wind"]), 1, 1)
        fig.add_trace(go.Scatter(x=t, y=hist.demand_mw, name="Demand", line=dict(color=C["ink"], width=2.5)), 1, 1)
        for name, dash in zip(sim.batteries, ("solid", "dot")):
            fig.add_trace(go.Scatter(x=t, y=hist[f"{name}_soc"] * 100, name=name,
                                     line=dict(color=C["storage"], dash=dash, width=2)), 2, 1)
        fig.add_trace(go.Scatter(x=t, y=hist.price, name="Price", line=dict(color=C["grid"], width=2),
                                 showlegend=False), 3, 1)
        fig.add_trace(go.Bar(x=t, y=hist.import_mw, name="Buying", marker_color=C["grid"]), 4, 1)
        fig.add_trace(go.Bar(x=t, y=-hist.export_mw, name="Selling", marker_color=C["storage"]), 4, 1)
        fig.add_trace(go.Bar(x=t, y=-hist.curtail_mw, name="Wasted", marker_color=C["alarm"]), 4, 1)
        fig.update_layout(barmode="relative", bargap=0.1)
        fig.update_yaxes(range=[0, 100], ticksuffix="%", row=2, col=1)
        half = pd.Timedelta(minutes=7.5)
        run_start = None
        for i, ev in enumerate(list(hist.events) + [""]):
            if ev and run_start is None:
                run_start = i
            elif not ev and run_start is not None:
                fig.add_vrect(x0=t[run_start] - half, x1=t[i - 1] + half, fillcolor=C["alarm"],
                              opacity=0.07, line_width=0)
                run_start = None
        fig.update_xaxes(range=day_range, tickformat="%H:%M", dtick=2 * 3600 * 1000)
        st.plotly_chart(style(fig, 860), width="stretch")
        st.caption("Faint red bands mark times when a disruption was active.")

with tab_fc:
    if done:
        st.markdown('<div class="empty">The day is over. Reset to start a new one.</div>', unsafe_allow_html=True)
    else:
        fc = sim.forecast(16)
        ren = fc.solar_mw + fc.wind_mw
        ren_sd = (fc.solar_std ** 2 + fc.wind_std ** 2) ** 0.5
        fig = make_subplots(rows=1, cols=2, subplot_titles=("Clean power vs demand (expected, with likely range)",
                                                            "Expected price (₹/MWh)"))
        fig.add_trace(go.Scatter(x=fc.time, y=ren + ren_sd, line=dict(width=0), showlegend=False,
                                 hoverinfo="skip"), 1, 1)
        fig.add_trace(go.Scatter(x=fc.time, y=(ren - ren_sd).clip(lower=0), fill="tonexty", line=dict(width=0),
                                 fillcolor="rgba(44,123,182,.18)", name="Likely range", hoverinfo="skip"), 1, 1)
        fig.add_trace(go.Scatter(x=fc.time, y=ren, name="Solar + wind", line=dict(color=C["wind"], width=2.5)), 1, 1)
        fig.add_trace(go.Scatter(x=fc.time, y=fc.demand_mw, name="Demand", line=dict(color=C["ink"], width=2.5)), 1, 1)
        fig.add_trace(go.Scatter(x=fc.time, y=fc.price + fc.price_std, line=dict(width=0), showlegend=False,
                                 hoverinfo="skip"), 1, 2)
        fig.add_trace(go.Scatter(x=fc.time, y=fc.price - fc.price_std, fill="tonexty", line=dict(width=0),
                                 fillcolor="rgba(91,103,112,.18)", showlegend=False, hoverinfo="skip"), 1, 2)
        fig.add_trace(go.Scatter(x=fc.time, y=fc.price, name="Price", line=dict(color=C["grid"], width=2.5)), 1, 2)
        st.plotly_chart(style(fig, 380), width="stretch")
        st.caption("Uncertainty widens further ahead. Announced events (storms, maintenance, line limits) are "
                   "already in this forecast; surprises such as battery faults are not.")

with tab_assets:
    a1, a2, a3 = st.columns(3)
    with a1:
        st.markdown("**Generation**")
        rows = [{"Asset": f.name, "Type": "Solar", "Capacity MW": f.capacity_mw, "Now MW": obs["solar_mw"][f.name]}
                for f in sim.config.solar]
        rows += [{"Asset": f.name, "Type": "Wind", "Capacity MW": f.capacity_mw, "Now MW": obs["wind_mw"][f.name]}
                 for f in sim.config.wind]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with a2:
        st.markdown("**Batteries**")
        st.dataframe(pd.DataFrame([{"Battery": k, "Charge": f"{b['soc']:.0%}", "Stored MWh": b["energy_mwh"],
                                    "Can charge MW": b["max_charge_mw"], "Can discharge MW": b["max_discharge_mw"],
                                    "Online": "Yes" if b["available"] else "No"}
                                   for k, b in obs["batteries"].items()]),
                     hide_index=True, width="stretch")
    with a3:
        st.markdown("**Consumers**")
        st.dataframe(pd.DataFrame([{"Consumer": c.name, "Now MW": obs["demand_mw"][c.name],
                                    "Flexible": f"{c.flexible_share:.0%}"} for c in sim.config.consumers]),
                     hide_index=True, width="stretch")

with tab_log:
    def status(e):
        if e.active(sim.step):
            return "Active"
        return "Finished" if sim.step >= e.start_step + e.duration_steps else "Scheduled"
    st.markdown("**Disruptions**")
    if sim.events:
        st.dataframe(pd.DataFrame([{"Status": status(e), "Event": e.description,
                                    "Known in advance": "Yes" if e.announced else "No"} for e in sim.events]),
                     hide_index=True, width="stretch")
    else:
        st.markdown('<div class="empty">No disruptions yet. Trigger one from the sidebar.</div>',
                    unsafe_allow_html=True)
    st.markdown("**Decisions**")
    if hist.empty:
        st.markdown('<div class="empty">Decisions appear here as time advances.</div>', unsafe_allow_html=True)
    else:
        log = hist[["time", "decision", "import_mw", "export_mw", "charge_mw", "discharge_mw", "total_cost_inr"]].copy()
        log["time"] = log.time.str[-5:]
        log.columns = ["Time", "Decision", "Buy MW", "Sell MW", "Charge MW", "Discharge MW", "Cost ₹"]
        st.dataframe(log.iloc[::-1].round(1), hide_index=True, width="stretch", height=360)
