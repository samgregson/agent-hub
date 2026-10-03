# Foundation operations

This runbook covers the Agent Hub API, web app, and database. The hosting platform owns sign-in and ingress. Keep the API and PostgreSQL off public networks. Use `AGENT_HUB_ENVIRONMENT=production` and `AGENT_HUB_IDENTITY_MODE=trusted_header` for the API, and configure the same private API URL for Next.js.

## Start and health

Run database migrations (`alembic -c apps/api/alembic.ini upgrade head`) before routing traffic to a new API image. The current API image runs migrations before Uvicorn starts, so deploy one API replica at a time until migration coordination is externalized. The API startup reconciles unfinished Agent, Batch, and Transform Runs. A Run that was interrupted for approval remains available for a decision; abandoned running work receives an explicit failure.

Probe `/health/live` to check that the API process responds and `/health/ready` to check its PostgreSQL connection. The web container exposes `/api/health/live` and `/api/health/ready`, with readiness forwarded to the API. A remote MCP server is optional and must not gate core readiness.

On shutdown, stop accepting new requests, let in-flight requests finish within the hosting platform's grace period, then stop the API. The API closes its Deep Agent/checkpointer resources during application shutdown. A restart may turn an unfinished Run into an explicit abandoned failure; users can start a new Run from the persisted Thread.

## Backup and restore

Agent Hub application records and LangGraph checkpoint tables live in the same PostgreSQL database. Back up the **whole database**, including schema and checkpoint tables, rather than selecting application tables. Keep the backup encrypted, access-controlled, and outside the database host. Record the API image revision and migration revision with each backup. Test a restore after schema changes and on the same schedule as the platform's recovery policy.

Example commands for a PostgreSQL service named `postgres` and database `agent_hub`:

```sh
# Backup while the application is running. Use the platform's secret store for
# credentials; do not include them in command arguments or shell history.
pg_dump --host=postgres --username=agent_hub --dbname=agent_hub \
  --format=custom --no-owner --file=agent-hub.dump

# Restore into a newly created, empty database on an isolated PostgreSQL
# instance. Never overwrite the live database to test a backup.
createdb --host=restore-postgres --username=agent_hub agent_hub_restore
pg_restore --host=restore-postgres --username=agent_hub \
  --dbname=agent_hub_restore --no-owner --exit-on-error agent-hub.dump
```

Point a test API instance at the restored database, using the recorded image revision. Check `/health/ready`, list a known Project and its Threads and Artifacts, and resume or inspect a known checkpointed Thread. Check that a Run left active at backup time is reconciled on API startup. Verify the migration revision before attempting an upgrade. Keep the restore isolated until those checks pass. For production recovery, stop writes, restore into a new database, verify it, then switch the private API connection to the restored database.

CI runs `scripts/foundation-restore-drill.py` with `AGENT_HUB_ALLOW_RESTORE_DRILL=1` only against its isolated PostgreSQL service. The drill seeds two Threads, a portable Artifact with Run provenance, and a LangGraph checkpoint, then verifies all of them in the restored database. Do not set that guard on a shared or production database.

## Incident signals

Alert when API or web readiness fails, migrations fail, PostgreSQL storage or connection capacity approaches its limit, Run failure rates rise, or MCP calls repeatedly time out. Review abandoned Runs after restarts, failed approval resumes, and failed backup or restore checks. Do not place model prompts, tool arguments, Artifact payloads, credentials, or raw identity headers in logs or metrics labels.

The API emits one JSON access record per request with a server-generated `request_id`, route template, method, status, and elapsed milliseconds. It returns that identifier in `X-Request-Id` and uses it for application error context where a Project identity is resolved. Access records omit request paths, query strings, headers, and bodies. Run Uvicorn with `--no-access-log` so its default logger does not reintroduce raw paths and query strings. Preserve the structured fields when collecting logs; do not add payload capture.

The private API exposes process-local Prometheus metrics at `/metrics`: request totals and duration histograms labeled by method, route template, and status. Scrape every API replica separately. Query strings, Project IDs, subjects, and payloads are never metric labels. The `/metrics` endpoint is not forwarded by the web app.

The API emits JSON `trace_span` records for each HTTP request and for remote MCP discovery, tool calls, and App resource reads inside that request. The root span's `trace_id` equals `X-Request-Id`; child spans carry its `parent_span_id`. Spans contain only operation names, reviewed Plugin IDs, route templates, outcome, and duration. Collect these logs into the platform's trace search using `trace_id`; never add tool arguments, prompt text, raw paths, or headers as span attributes.

Durable audit evidence is recorded in the owning records: Agent Runs retain approval decisions and request IDs, Artifact Documents retain creating and last-changing Thread/Run or user-action provenance, and Batch Runs retain their initiator and idempotency key. Each Artifact create, replacement, and deletion also inserts a payload-free row in `artifact_audit_events` in the same PostgreSQL transaction as the change. It records the version and actor reference, including the deleting Project subject. Back up these records with PostgreSQL. Access logs provide the correlated HTTP status for those changes.

The API rejects request bodies larger than `AGENT_HUB_REQUEST_BODY_MAX_BYTES` (4 MB by default) with HTTP 413 before parsing them. This limit applies to declared and streamed bodies. Increase it only alongside the Project file and Plugin payload limits for a use case that requires larger requests.

Each API process admits at most `AGENT_HUB_PLUGIN_MAX_CONCURRENT_CALLS` (default 8) concurrent remote operations and `AGENT_HUB_PLUGIN_MAX_CALLS_PER_MINUTE` (default 120) starts per Plugin. Discovery, tool calls, and App resource reads share this budget. Excess work fails immediately; App requests receive HTTP 429 so the user can retry. These are per-replica safeguards, so account for replica count when setting upstream traffic limits.

## Monitoring assets

`ops/prometheus/agent-hub-rules.yml` provides alerts for a failed API scrape, sustained 5xx responses, high p95 latency, and repeated 429 responses. Configure a private Prometheus scrape job named `agent-hub-api` for every API replica and load this file through `rule_files`. The `up` signal reports scraper reachability; `/health/ready` still needs a separate platform readiness probe. See the [Prometheus alerting rule format](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/).

`ops/grafana/agent-hub-overview.json` is an importable API overview dashboard. Its panels expect a Prometheus data source with UID `prometheus`; replace that UID on import if the platform uses another one. See [Grafana's dashboard JSON model](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/view-dashboard-json-model/). Keep the scrape endpoint and dashboard inside the private operations network.
