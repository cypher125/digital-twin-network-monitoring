# Digital Twin-Based Network Monitoring and Optimization System

HND final-year project, Department of Computer Science, Yaba College of Technology.

The system keeps a live virtual model, or *digital twin*, of a campus network, updated from monitoring data every minute. It forecasts the utilisation of every link and warns administrators before congestion happens. Administrators can also test changes, such as a link failure, more traffic, a reroute or an upgrade, on a detached copy of the model, without any path to the real network.

The design is Chapters 1–3 of the project report. The evaluation is done on a network emulator that stands in for the real campus network and provides ground truth for every measurement. The report itself and the drafts for its chapters stay out of the public repository until the report has been submitted.

## Start here

| If you want to… | Read |
|---|---|
| install and run it on a Windows laptop | [docs/INSTALL.md](docs/INSTALL.md) |
| run it in the cloud (API on Modal, dashboard on Vercel) | [docs/CLOUD.md](docs/CLOUD.md) |
| use the dashboard | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) |
| give the project defence demo | [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) |
| see how the build maps to Chapter 3, and what changed | [docs/AS_BUILT_NOTES.md](docs/AS_BUILT_NOTES.md) |
| see the plan, decisions and traceability matrix | [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) |
| see the evaluation evidence | [docs/evidence/](docs/evidence/), `backend/evaluation/results/` |
| look up a table or column | [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) |
| add a scenario type or a data source | [docs/EXTENDING.md](docs/EXTENDING.md) |

## What is in the repository

```
backend/                      Python 3.13 (uv): Django REST API and the Digital Twin Engine
  netemu/                     network emulator: the stand-in "real network" (topology, traffic, faults)
  data_collection/            network adapters (read-only) and preprocessing   (Figure 3.4, 1.0-2.0)
  digital_twin/
    network_model/            NetworkX graph of the network, routing, demands   (3.0)
    prediction_engine/        Random Forest forecasts and warnings              (4.0)
    simulation_engine/        what-if scenarios and recommendations             (5.0)
    runtime/                  the engine loop, persistence, simulation jobs
  apps/                       Django apps: twin (the six tables), api, accounts, lab
  config/                     Django settings (dev, test, prod, cloud)
  evaluation/                 experiments E1-E9 and their results (results/E*/)
  tests/                      unit and integration tests (pytest)
frontend/                     Next.js 16 dashboard (static build; a Next.js app on Vercel) and Playwright scripts
data/topologies/campus.yaml   the campus network: 34 devices, 43 links
deploy/                       setup, start and stop scripts, supervisor, Caddy configuration, Modal app
docs/                         guides, design notes, diagrams (docs/diagrams/), evidence
figures/                      the Chapter 3 figures as designed
```

## Running it (after installation)

```powershell
powershell -ExecutionPolicy Bypass -File deploy\start.ps1 -Speed 10      # demo speed: 10x network time
powershell -ExecutionPolicy Bypass -File deploy\stop.ps1
```

The dashboard opens at **https://localhost**.

## Tests and checks

From `backend\`, with `DATABASE_URL` set (the local PostgreSQL fallback works):

```powershell
.venv\Scripts\python.exe -m pytest -m "not slow"     # unit and integration tests
.venv\Scripts\python.exe -m pytest -m slow           # slow tests: history generation and model training
.venv\Scripts\ruff.exe check .
.venv\Scripts\lint-imports.exe                       # architecture rules (NFR5, G3)
```

From `frontend\`:

```powershell
npm run lint
npm run build
$env:DT_SENIOR = "<senior username>:<password>"; $env:DT_JUNIOR = "<junior username>:<password>"
node scripts/walkthrough.mjs --url https://localhost --surge   # UC1-UC4 walkthrough in Edge
```

The evaluation experiments are described in [docs/PROJECT_PLAN.md §11](docs/PROJECT_PLAN.md). Each one runs as `python -m evaluation.<module>` from `backend\` and writes its results to `backend/evaluation/results/`.
