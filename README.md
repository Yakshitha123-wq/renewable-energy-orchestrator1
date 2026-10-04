# Renewable Energy Orchestrator

An agentic AI system that autonomously manages a renewable energy portfolio (5 solar farms, 3 wind farms, 2 battery storage systems, industrial consumers, grid connection and market access), re-planning every 15 minutes to minimise cost and carbon while keeping the grid reliable.

Built for **ET AI Hackathon: Agentic Edition (Accenture), Problem 4: Utilities – Renewable Energy Orchestrator**.

Built by Yakshitha. AI pair-programming assistance (Claude) was used for code generation and review; all design decisions, testing and presentation are my own.

> Status: **Day 1 complete**: grid simulator, control-room dashboard, baseline controllers. Optimizer, AI agent and reliability tests are in progress.

## How it works (target architecture)

| Layer | Role |
|---|---|
| **Grid simulator** (`src/simulator.py`) | Generates solar, wind, demand, prices, grid frequency, battery state and disruption events every 15 min, plus forecasts with growing uncertainty |
| **Optimizer** (Day 2–3) | Linear program that computes the best set of actions under physical limits and the chosen trade-off between goals |
| **LLM agent** (Day 4) | Observes, reasons about events, chooses goal weights, calls tools, re-plans, recovers from failures and explains decisions |
| **Dashboard** (`app.py`) | Control-room view: live power-flow diagram, alarms, running cost/carbon, forecasts, event and decision log, buttons to trigger disruptions |

## Project structure

```
src/config.py      Portfolio assets, grid limits, market assumptions
src/simulator.py   Stochastic 15-minute grid simulator with events and forecasts
src/scenarios.py   Ready-made "bad day" scenario with every disruption type
src/dispatch.py    Applies any controller's decision under physical limits; cost, carbon and reliability accounting
src/controllers.py Baseline controllers: no orchestration, simple rules
app.py             Streamlit control-room dashboard
run_sim.py         Runs one day with no orchestration (baseline) and saves a chart
tests/             Automated tests
```

## Setup

Requires Python 3.10+.

```bash
git clone <your-repo-url>
cd renewable-energy-orchestrator
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then add your API key (needed from Day 4)
```

## Run

```bash
streamlit run app.py      # open the control-room dashboard in your browser
python run_sim.py          # simulate a day with no orchestration; writes outputs/day1_baseline.png
python -m pytest -q        # run the tests
```

## Simulated disruptions

Cloud cover, storms (turbines cut out above 25 m/s), battery faults, price spikes, industrial demand surges, transmission line limits and planned maintenance. Announced events (storms, maintenance, line limits) appear as alerts 4 hours ahead and in forecasts; the rest are surprises the agent must react to.

## Key assumptions

All values are in `src/config.py`: prices in ₹/MWh with a ₹10,000 cap, grid emission factor 0.71 tCO2/MWh, assumed carbon price ₹2,000/tCO2, battery wear cost ₹600 per MWh moved.

## Dashboard design

The dashboard follows high-performance HMI practice used in real grid control rooms (ISA-101): a calm grey
background, with colour reserved for meaning (amber solar, blue wind, teal storage, red only for alarms and waste).
The power-flow diagram shows every asset, the portfolio bus, consumers and the grid; line thickness is megawatts
and the moving dashes show direction. All controllers are settled by the same `dispatch.settle()` so comparisons are fair.
