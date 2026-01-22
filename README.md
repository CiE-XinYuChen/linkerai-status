# LinkerAI Status

A Python/Flask-powered status page with a LinkerAI-branded, JavaScript-driven frontend. It polls configurable health endpoints, surfaces component-level status, and records lightweight incident history. Also includes a friendly error page for unexpected failures.

## Quick start

1) Install deps:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Configure monitors by copying the example and editing endpoints, timeouts, and intervals:
```bash
cp config.example.yaml config.yaml
# edit config.yaml to match your services
```
You can also point to another file via `STATUS_CONFIG=/path/to/custom.yaml`.

3) Run the status site:
```bash
python app.py
# open http://localhost:5000
```

## Configuration

`config.yaml` supports:
- `poll_interval_seconds`: How often to re-check endpoints.
- `timeout_seconds`: Default HTTP timeout if a service override is not provided.
- `slow_threshold_ms`: Responses slower than this are marked as `degraded_performance`.
- `max_incidents`: How many incidents to keep in memory.
- `services`: List of components to monitor:
  - `name`: Display name in the UI.
  - `component`: Group or area (shown with the name).
  - `url`: The health endpoint to request.
  - `method`: HTTP verb (default `GET`).
  - `expected_statuses`: Accepted HTTP codes (default `[200]`).
  - `timeout_seconds`: Optional override per service.
  - `headers`: Optional custom headers (e.g., `Accept: application/json` for JSON health checks).
  - `verify_ssl`: Set to `false` to skip TLS verification (only for endpoints with mismatched/invalid certs).
  - `reachable_only`: Set to `true` if any successful connection (any HTTP status) counts as operational—useful for simple reachability checks like https://ota.linkerai.cn/.

## Routes
- `/`: Main status page (auto-updates through background polling).
- `/api/status`: JSON view of the latest snapshot.
- `/errors`: Friendly error page that reuses the status layout.
- `/healthz`: Lightweight app health check.

## Notes
- The server records an incident whenever a monitor transitions from `operational` to a non-OK state, preserving the last `max_incidents` entries.
- Frontend auto-fetches `/api/status` on an interval (see `poll_interval_seconds`) to update UI without page reloads.
