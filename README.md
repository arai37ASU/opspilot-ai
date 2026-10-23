# opspilot-ai
AI-powered operational analytics platform for service request analysis, SLA risk prediction, and management insights.

## Current status

Built so far:

- Project requirements: [docs/project_requirements.md](docs/project_requirements.md)
- Synthetic service-desk dataset design: [docs/dataset_design.md](docs/dataset_design.md)
- A reproducible generator for that dataset (`src/opspilot/data_generation/`), with tests
- A PostgreSQL schema with constraints and a transactional CSV loader (`sql/schema/`, `src/opspilot/db/`)
- SQL data-quality checks with a command-line runner (`sql/checks/`)
- Business analysis queries with saved results (`sql/analysis/`, `reports/sql/`), written up in [docs/sql_analysis.md](docs/sql_analysis.md)
- A leakage-safe feature view for SLA breach prediction (`sql/features/`), built by the loader
- Exploratory analysis notebooks (`notebooks/`), written up in [docs/eda_findings.md](docs/eda_findings.md), ending in a recorded plan for the SLA breach model

Not built yet: ML models, API, dashboard, AI insight layer, deployment.

## Setup

Requires Python 3.11 or later.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Generating the dataset

```bash
python -m opspilot.data_generation.generate --seed 42 --output-dir data/raw
```

This writes `tickets.csv` and four reference tables (`teams`, `sla_policies`, `subcategories`, `calendar_days`) to `data/raw/` and prints a calibration summary. Generated data is not committed; the same seed always reproduces the same files.

## Database

PostgreSQL 17 runs in Docker. Copy `.env.example` to `.env` and set a password, then:

```bash
docker compose up -d
```

This starts the `opspilot` database and an `opspilot_test` database used only by tests. Data persists in a Docker volume; `docker compose down -v` deletes it.

Load the generated CSVs (rerunnable; the whole load is one transaction):

```bash
python -m opspilot.db.load --data-dir data/raw
```

The schema is in [sql/schema/](sql/schema/).

Run the data-quality checks (exits with status 1 if any error-level check fails):

```bash
python -m opspilot.db.checks
```

The checks are plain SQL in [sql/checks/data_quality.sql](sql/checks/data_quality.sql); each returns the rows that break one rule.

Run the business analysis queries in [sql/analysis/](sql/analysis/) and save each result as CSV:

```bash
python -m opspilot.db.analysis --output-dir reports/sql
```

## Notebooks

With the database running and loaded:

```bash
jupyter lab
```

Open the notebooks in `notebooks/` and run all cells from the top. They save charts to `reports/figures/` and confidence intervals to `reports/stats/`.

## Running tests

```bash
pytest
```

Tests marked `db` need the database container and are skipped when it is not running.
