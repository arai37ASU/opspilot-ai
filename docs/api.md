# OpsPilot API

The API serves the SLA breach model and verified operational metrics. It is a FastAPI application (`src/opspilot/api/`); interactive documentation, generated from the code, is at `/docs` when it is running.

## Running it

The API needs the database loaded and the model built (see the README):

```bash
python -m opspilot.modeling.train
```

**In Docker** (database and API together):

```bash
docker compose --profile api up -d --build
```

**Locally**, against the database container:

```bash
uvicorn opspilot.api.main:app --port 8000
```

Configuration comes from environment variables: `DATABASE_URL` (required), `OPSPILOT_MODEL_DIR` (default `models`), `OPSPILOT_REPORTS_DIR` (default `reports/modeling`) and `OPSPILOT_POOL_MAX_SIZE` (default 5). Locally they are read from `.env`.

## Endpoints

| Method and path | Purpose |
|---|---|
| `GET /health` | 200 when the database answers and the model is loaded; 503 otherwise |
| `GET /model` | The deployed model, its threshold and features, the commit it was evaluated from, and its test metrics |
| `POST /predictions` | Score a new ticket at creation time |
| `GET /tickets/{ticket_id}/risk` | Score a stored ticket from the features it had at creation |
| `GET /metrics/overview` | Headline KPIs for a date range (`start`, `end`, both optional) |
| `GET /metrics/teams` | Per-team KPIs for a date range |
| `GET /metrics/trend` | Monthly volume and breach rate |
| `GET /metrics/analysis` | The catalog of saved analysis queries |
| `GET /metrics/analysis/{file}/{query}` | The rows of one analysis query |

### Scoring a new ticket

```bash
curl -X POST localhost:8000/predictions -H 'Content-Type: application/json' -d '{
  "created_at": "2025-09-03T19:30:00",
  "priority": "P2",
  "subcategory": "projector_display",
  "assigned_team": "Classroom Technology",
  "requester_type": "faculty",
  "channel": "phone"
}'
```

The response includes `risk` (probability of breaching), `flagged` (risk at or above the threshold of 0.457), the three `reasons` that moved the risk most, and the exact `inputs` the model received. For this ticket the risk is about 98%: it arrived 12.5 hours before the desk opens, is P2, and has an 8-hour target. The same ticket at 09:30 scores about 17%.

Features that depend on the queue (backlog, recent similar tickets, recent breach rates) are computed from the database as of `created_at`, using the same rules as training. `tests/test_online_features.py` checks that they match the training features exactly.

### Errors

| Status | When |
|---|---|
| 404 | Unknown ticket id or analysis query |
| 422 | A field is missing or invalid (for example `priority: "P9"`), or the ticket cannot be scored: unknown subcategory or team, a priority with no SLA policy (P1 service requests), a date outside the data, or a date range with `start` after `end` |
| 503 | From `/health`, when the database is unreachable |

## Design notes

- **One code path for features.** Training data and live requests are converted to model inputs by the same function, and the serving query is tested for exact parity with the training view, including tickets created in the same second.
- **Verified numbers only.** The metrics endpoints run SQL from the repository and are checked against the saved analysis results. Clients choose a query by name; the API never accepts SQL.
- **Explanations from the model itself.** Reasons are SHAP values computed by XGBoost on exactly the input the model scored.
- **The container** runs as a non-root user, has a health check on `/health`, excludes `.env` and local data, and reads the model from a read-only mount. GPU libraries that XGBoost installs on Linux are removed (predictions were checked to be identical), which cut the image from 1.59 GB to 924 MB.

## Limitations

- **No authentication.** The API is bound to localhost; authentication is part of deployment.
- **Historical data only.** The synthetic data ends on 2025-12-31, so `created_at` must fall inside it. A live system would score at the current time.
- **Current headcount.** `agents` in `/metrics/teams` is today's headcount; past staffing changes are not stored.
- **Editable install in the image.** SQL files are found relative to the source tree, so the image installs the package in editable mode. Packaging the SQL as package data would remove this.
