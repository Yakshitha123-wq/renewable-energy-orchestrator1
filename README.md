# Renewable Energy Orchestrator

An agentic AI system that autonomously manages a renewable energy portfolio (5 solar farms, 3 wind farms, 2 battery storage systems, industrial consumers, grid connection and market access), re-planning every 15 minutes to minimise cost and carbon while keeping the grid reliable.

Built for **ET AI Hackathon: Agentic Edition (Accenture), Problem 4: Utilities – Renewable Energy Orchestrator**.

>

## How it works (target architecture)

| Layer | Role |
|---|---|
| **Grid simulator** (`src/simulator.py`) | Generates solar, wind, demand, prices, grid frequency, battery state and disruption events every 15 min, plus forecasts with growing uncertainty |
| **Optimizer** (Day 2–3) | Linear program that computes the best set of actions under physical limits and the chosen trade-off between goals |
| **LLM agent** (Day 4) | Observes, reasons about events, chooses goal weights, calls tools, re-plans, recovers from failures and explains decisions |
| **Dashboard** (Day 5) | Live view with buttons to inject events and watch the agent react |

## Project structure

```
src/config.py      Portfolio assets, grid limits, market assumptions
src/simulator.py   Stochastic 15-minute grid simulator with events and forecasts
src/scenarios.py   Ready-made "bad day" scenario with every disruption type
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
python run_sim.py          # simulate a day with no orchestration; writes outputs/day1_baseline.png
python -m pytest -q        # run the tests
```

## Simulated disruptions

Cloud cover, storms (turbines cut out above 25 m/s), battery faults, price spikes, industrial demand surges, transmission line limits and planned maintenance. Announced events (storms, maintenance, line limits) appear as alerts 4 hours ahead and in forecasts; the rest are surprises the agent must react to.

## Key assumptions

All values are in `src/config.py`: prices in ₹/MWh with a ₹10,000 cap, grid emission factor 0.71 tCO2/MWh, assumed carbon price ₹2,000/tCO2, battery wear cost ₹600 per MWh moved.
