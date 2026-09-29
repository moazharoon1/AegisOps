# AegisOps — Shared Contracts

This is the binding agreement between every workstream. Code in `control-plane/aegisops/domain`,
`control-plane/aegisops/ports`, `control-plane/aegisops/security`, `control-plane/aegisops/container.py`
and `control-plane/aegisops/api/{schemas.py,routes/v1.py}` is the executable form of this document.
If something here is ambiguous, the code wins; if you must change a contract, say so explicitly in your
final report (do not silently change it).

---

## 1. Repository layout and ownership

| Path | Owner (workstream) | Notes |
|---|---|---|
| `control-plane/aegisops/domain/`, `ports/`, `security/`, `config.py`, `container.py`, `storage/inmemory.py` | Orchestrator (contracts) | Read-only for workstreams. Additive helpers allowed only when reported. |
| `control-plane/aegisops/storage/` (except inmemory), `api/`, `intake/`, `incidents/`, `governance/`, `worker/`, `observability/` (self-metrics) | **core** | DynamoDB repos, artifacts, outbox, API, auth, SSE, intake, lifecycle, governance, worker loop |
| `control-plane/aegisops/mcp/` | **mcp** | 3 MCP servers, real backends, auth middleware, gateway (`ToolInvoker`) |
| `control-plane/aegisops/knowledge/`, `runbooks/` | **knowledge** | Runbooks, chunking, embeddings, pgvector + lexical hybrid retrieval, memory store |
| `control-plane/aegisops/llm/`, `agents/`, `workflow/`, `reports/` | **agents** | Providers (live/record/replay/deterministic), 9 agents, LangGraph workflow, compaction, postmortems |
| `control-plane/aegisops/executor/`, `verification/`, `changes/` | **executor** | Deterministic executor, verification, change recorder & known-good snapshots |
| `control-plane/aegisops/sim/`, `scenarios/` | **sim** | In-process simulated world, scenario catalog, cluster injectors, sim-controller service |
| `control-plane/aegisops/cli/` | **cli** | `aegis` Typer CLI over the HTTP API |
| `demo-app/` | **demo-app** | E-commerce services + traffic generator + image |
| `deploy/`, `scripts/`, root `Makefile` | **platform** (+ **observability** for `deploy/observability/`) | Kind, Calico, Helm charts, emulators, databases, bootstrap |
| `frontend/` | **frontend** | React + TS + Vite + Tailwind dashboard |
| `evaluation/` | **evaluation** | Case catalog, runners, metrics, results |
| `docs/`, `README.md` | **docs** | Final documentation |

Tests live in `control-plane/tests/<area>/` matching the package you own.

## 2. Global conventions

* Python 3.12, `uv` (venv at `control-plane/.venv`). Run tools with `uv run ...` from `control-plane/`.
* **Do not edit `control-plane/pyproject.toml` or run `uv add`.** If you need a package, install it with
  `uv pip install <pkg>==<ver>` for local testing and list it in your final report; the orchestrator
  adds it to the lockfile. Pinned dependencies already include FastAPI, Pydantic v2, LangGraph 1.2,
  `mcp` 2.2 (server class: `mcp.server.mcpserver.MCPServer`), OpenAI SDK 3.x (Responses API), boto3,
  kubernetes, psycopg 3 + pgvector, tiktoken, typer, structlog, prometheus-client, moto (dev), respx (dev).
* All I/O ports are `async`. boto3 / kubernetes clients are called through `asyncio.to_thread`.
* Datetimes are timezone-aware UTC. IDs come from `domain.common.new_id(prefix)` (ULID-based, sortable);
  incidents use `INC-<n>` from an atomic counter starting at 1001.
* Every component takes a `Clock` (`ports.clock.SystemClock` / `VirtualClock`) instead of calling `datetime.now()`.
* Logs: structlog JSON to stdout. **Never log secret values, approval tokens or session tokens**; pass
  anything derived from external data through `security.redaction.redact()` first.
* Tests: `uv run pytest tests/<area>`; markers `cluster` (needs Kind) and `live` (paid OpenAI) are
  excluded by default. **Never call the paid OpenAI API from tests.** Lint: `uv run ruff check aegisops tests`.
* Disk is limited (~20 GB free): remove throwaway containers/images you create; never pull images you do not need.

## 3. Runtime topology (Kind cluster `aegisops`)

| Namespace | Workloads |
|---|---|
| `production` | `storefront`, `checkout-service`, `payment-service`, `inventory-service`, `notification-worker` (Deployments, 2 replicas each), `shop-db` (PostgreSQL 16 StatefulSet, `max_connections=40`) + `shop-db-exporter` (postgres_exporter) |
| `simulation` | `traffic-generator`, `sim-controller` (fault injection harness; not part of AegisOps) |
| `cloud-sim` | `aws-sim` (LocalStack 4.14.0 community, port 4566), `dynamodb` (DynamoDB Local, port 8000, persistent) |
| `aegisops` | `aegisops-api` (8000), `aegisops-worker`, `mcp-diagnostics` / `mcp-knowledge` / `mcp-mutations` (8080, path `/mcp`), `aegis-db` (PostgreSQL 16 + pgvector), `aegisops-ui` (nginx 8080; proxies `/api` to the API) |
| `observability` | Prometheus + Alertmanager + kube-state-metrics, Loki, Tempo, OpenTelemetry Collector, Grafana |

* Host ports (Kind `extraPortMappings`): dashboard + API `http://localhost:${AEGIS_DASHBOARD_PORT:-8080}` (NodePort 30080),
  Grafana `http://localhost:${AEGIS_GRAFANA_PORT:-3000}` (NodePort 30300). Databases and MCP servers are never exposed.
* CNI: Calico (Kind default CNI disabled) so NetworkPolicies are enforced. Default-deny ingress per namespace plus explicit allows.
* Durable data: repo-local `.data/` is mounted into the node (`extraMounts` → `/aegisops-data`) and used via hostPath
  PersistentVolumes for DynamoDB Local, `aegis-db`, artifacts (`/aegisops-data/artifacts`) and `shop-db`.
  `make down` deletes the cluster but keeps `.data/`; `make up` recreates and re-attaches it; `make reset` wipes (asks first).
* Images (built locally, loaded with `kind load`): `aegisops/control-plane:0.1.0` (api, worker, mcp servers, sim-controller —
  selected by command), `aegisops/shop:0.1.0` (all demo services + traffic generator — selected by `SERVICE`),
  `aegisops/ui:0.1.0`.

### In-cluster endpoints (defaults in `aegisops.config.Settings`)

| Setting | Default |
|---|---|
| `AWS_ENDPOINT_URL` | `http://aws-sim.cloud-sim.svc.cluster.local:4566` |
| `AEGIS_DYNAMODB_ENDPOINT_URL` | `http://dynamodb.cloud-sim.svc.cluster.local:8000` |
| `AEGIS_DATABASE_URL` | `postgresql://aegisops:<generated>@aegis-db.aegisops.svc.cluster.local:5432/aegisops` |
| `AEGIS_PROMETHEUS_URL` | `http://prometheus-server.observability.svc.cluster.local` |
| `AEGIS_ALERTMANAGER_URL` | `http://prometheus-alertmanager.observability.svc.cluster.local:9093` |
| `AEGIS_LOKI_URL` | `http://loki.observability.svc.cluster.local:3100` |
| `AEGIS_TEMPO_URL` | `http://tempo.observability.svc.cluster.local:3200` |
| OTLP (apps) | `http://otel-collector.observability.svc.cluster.local:4318` (HTTP) / `:4317` (gRPC) |
| `AEGIS_MCP_*_URL` | `http://mcp-<name>.aegisops.svc.cluster.local:8080/mcp` |
| `AEGIS_SIM_CONTROLLER_URL` | `http://sim-controller.simulation.svc.cluster.local:8080` |

If the observability workstream uses different service names, it updates these defaults via Helm values
(env vars on the control-plane Deployments) and records the final names in this file.

## 4. Demonstration application contract (`demo-app/`)

All services: Python 3.12 FastAPI, port **8080**, `/healthz` (liveness), `/readyz` (readiness — process health only,
**never** dependent on downstreams/DB so faults show as errors, not unavailability), `/metrics` (Prometheus),
JSON logs to stdout, OpenTelemetry traces (W3C propagation), request timeouts on every outbound call.
Labels on pods: `app: <deployment-name>`, `app.kubernetes.io/name`, `app.kubernetes.io/part-of: shop`.
Pod annotations: `prometheus.io/scrape: "true"`, `prometheus.io/port: "8080"`, `prometheus.io/path: /metrics`.
Common env: `SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `AWS_ENDPOINT_URL`, `AWS_REGION=us-east-1`,
`AWS_ACCESS_KEY_ID=test`, `AWS_SECRET_ACCESS_KEY=test`, `LOG_LEVEL`.

| Service | Behaviour | Config (ConfigMap via `envFrom`) | Other env / mounts |
|---|---|---|---|
| `storefront` | `GET /products` (→ inventory), `POST /checkout` (→ checkout). Returns 502/503/504 when downstream fails. | `storefront-config`: `CHECKOUT_SERVICE_URL`, `INVENTORY_SERVICE_URL`, `REQUEST_TIMEOUT_MS` | |
| `checkout-service` | `POST /checkout`: reserve stock (inventory) → charge (payment, `Authorization: Bearer <key>`) → publish order event to SQS `payment-events` → 200. Loads the payment key from Secrets Manager `shop/payment-api-key` (AWSCURRENT) **at startup only**; exposes the loaded *version id* (never the value) as a metric. Validates `PAYMENT_RETRY_POLICY` ∈ {`none`,`fixed`,`exponential`} during a warm-up `WARMUP_DELAY_SECONDS` (default 6) after start: invalid → logs `config_validation_failed` with the exception and exits 1 (after readiness already passed ⇒ realistic CrashLoopBackOff + 5xx). | `checkout-config`: `PAYMENT_SERVICE_URL=http://payment-service.production.svc.cluster.local:8080`, `INVENTORY_SERVICE_URL`, `REQUEST_TIMEOUT_MS=2000`, `PAYMENT_EVENTS_QUEUE=payment-events` | Deployment env: `PAYMENT_RETRY_POLICY=exponential`, `PAYMENT_API_KEY_SECRET_ID=shop/payment-api-key`, `WARMUP_DELAY_SECONDS=6`. Annotation `aegisops.io/aws-secrets: shop/payment-api-key` |
| `payment-service` | `POST /charge`: simulated payment provider; validates bearer key against keys mounted from K8s Secret `payment-provider-keys` (`/etc/payment-provider/keys`, one per line); 401 on mismatch. | `payment-config`: `PAYMENT_LATENCY_MS=40` | secret volume |
| `inventory-service` | `GET /products`, `POST /reserve`: PostgreSQL via a **fixed-size** pool (`min=max=DB_POOL_SIZE`); each reservation holds its connection for `DB_QUERY_HOLD_MS`. Pool open failures must not crash the process: retry in background, return 503 for DB requests, log `db_connection_failed`. | `inventory-config`: `DB_POOL_SIZE=5`, `DB_QUERY_HOLD_MS=40`, `DB_ACQUIRE_TIMEOUT_MS=1000` | `DATABASE_URL` from K8s Secret `shop-db-credentials` |
| `notification-worker` | Long-polls SQS `payment-events`; `WORKER_CONCURRENCY` handlers per pod; each message takes `PROCESSING_TIME_MS`; messages with `"poison": true` or malformed JSON fail (no delete ⇒ redelivery ⇒ DLQ per redrive policy). Idempotent by `order_id`. | `notification-config`: `PAYMENT_EVENTS_QUEUE=payment-events`, `WORKER_CONCURRENCY=2`, `PROCESSING_TIME_MS=400` | |
| `traffic-generator` (ns `simulation`) | Continuous browse + checkout load against storefront. Control API: `GET/PUT /config` `{browse_rps, checkout_rps}` (defaults 5 / 4), `GET /stats`. | env `STOREFRONT_URL` | |

### Metrics (names are a contract; the observability backends query exactly these)

| Metric | Type | Labels |
|---|---|---|
| `http_server_requests_total` | counter | `service, method, route, status` |
| `http_server_request_duration_seconds` | histogram | `service, method, route` |
| `http_client_requests_total` | counter | `service, peer, status, error_type` — `status` is the HTTP code or `error`; `error_type` ∈ `none, http_401, http_403, http_4xx, http_5xx, dns_resolution, connection_refused, timeout, connection_error` |
| `http_client_request_duration_seconds` | histogram | `service, peer` |
| `app_info` | gauge (1) | `service, version` |
| `app_secret_loaded_info` | gauge (1) | `service, secret_id, version_id` (never the value) |
| `db_pool_size` / `db_pool_connections_in_use` / `db_pool_connections_open` | gauge | `service` |
| `db_pool_acquire_wait_seconds` | histogram | `service` |
| `db_errors_total` | counter | `service, error` (`too_many_connections, timeout, other`) |
| `queue_messages_published_total` | counter | `service, queue` |
| `queue_messages_consumed_total` | counter | `service, queue, outcome` (`success, failed`) |
| `queue_message_processing_seconds` | histogram | `service, queue` |
| `queue_message_age_seconds` | histogram | `service, queue` (age at receipt, from `sent_at` in the body) |
| `queue_consumer_busy_ratio` | gauge | `service, queue` |
| `queue_consumer_concurrency` | gauge | `service, queue` |
| `queue_message_failures_total` | counter | `service, queue, reason` (`poison, malformed, processing_error`) |
| `aws_sdk_errors_total` | counter | `service, aws_service, operation, error_code` |
| `orders_total` | counter | `service, outcome` (checkout: `success, failed`) |
| `payment_charges_total` | counter | `service, outcome` (payment: `success, auth_rejected, error`) |
| `loadgen_requests_total` / `loadgen_request_duration_seconds` | counter / histogram | `endpoint, status` |
| `sqs_queue_messages_visible` / `_in_flight` / `_delayed` | gauge | `queue` — from a small SQS exporter (observability workstream; polls GetQueueAttributes every 15 s) |
| postgres_exporter: `pg_stat_activity_count`, `pg_settings_max_connections` | gauge | standard |
| kube-state-metrics: `kube_deployment_status_replicas_unavailable`, `kube_pod_container_status_restarts_total`, `kube_pod_container_status_waiting_reason` | | standard |

### Logs
One JSON object per line: `timestamp` (ISO-8601), `level` (`info|warning|error`), `service`, `message`, `event`
(snake_case), `trace_id`, `span_id`, plus context (`peer`, `status`, `error_type`, `order_id`, `exception`).
Scenario-relevant events: `config_validation_failed`, `dependency_request_failed`, `payment_charge_rejected`,
`db_connection_failed`, `db_pool_exhausted`, `message_processing_failed`, `secret_loaded` (version id only).
Loki labels: `namespace`, `pod`, `container`, and **`service_name`** = the pod's `app` label (setting
`AEGIS_LOKI_SERVICE_LABEL`).

### SQS message (`payment-events`)
`{"order_id": "...", "amount_cents": 1234, "currency": "USD", "sent_at": "<iso>", "trace_id": "..."}`.

## 5. AWS emulation and seeded resources

* **LocalStack `localstack/localstack:4.14.0@sha256:3ebc37595918b8accb852f8048fef2aff047d465167edd655528065b07bc364a`**
  — last open-source community release (archived repo), no token. `SERVICES=sqs,s3,secretsmanager,events,sts`.
  Optional: with `LOCALSTACK_AUTH_TOKEN` set, the platform may run the current unified image instead.
  State is not persisted: the bootstrap job re-seeds on every `make up` (idempotent).
* **DynamoDB Local** (`amazon/dynamodb-local`, `-sharedDb -dbPath /data`, persistent volume). The control plane creates its
  own tables at startup (`aegisops.storage.dynamodb.ensure_tables`), all prefixed `aegisops-`.
* Seeded by the platform bootstrap job:
  * SQS `payment-events` (redrive → `payment-events-dlq`, maxReceiveCount 3, visibility timeout 30 s);
    `aegisops-workflow` (redrive → `aegisops-workflow-dlq`, maxReceiveCount 5).
  * EventBridge bus `aegisops-events`; rule `aegisops-workflow-route` with pattern `{"source": ["aegisops.control-plane"]}`
    → target SQS `aegisops-workflow`.
  * S3 bucket `aegisops-artifacts`.
  * Secrets Manager `shop/payment-api-key`: value = synthetic key `sk_canary_<random>` generated once and stored in
    `.data/bootstrap/payment-api-key` (so re-seeding restores the same valid value). The same value is written to K8s
    Secret `payment-provider-keys` in `production`.
* Worker messages: the outbox relay publishes `PutEvents` (source `aegisops.control-plane`, detail-type = message kind,
  detail = `WorkflowMessage` JSON). The worker accepts either an EventBridge envelope (`detail`) or a raw `WorkflowMessage`.

## 6. Control-plane processes

| Process | Command | K8s ServiceAccount / RBAC | Keys mounted |
|---|---|---|---|
| API | `aegisops-api` (uvicorn, port 8000) | `aegisops-api` — none | `session.pem`, `session.pub.pem`, `approval.pem` |
| Worker | `aegisops-worker` (queue consumer, outbox relay, reconciler, change recorder loop) | `aegisops-worker` — read-only on `production` (deployments, replicasets, configmaps, pods) | `service.pem` |
| MCP diagnostics | `aegisops-mcp --server diagnostics` | `mcp-diagnostics` — get/list/watch pods, pods/log, events, deployments, replicasets, configmaps, services, endpoints in `production`. **No secrets.** | `service.pub.pem` |
| MCP knowledge | `aegisops-mcp --server knowledge` | none (DynamoDB + Postgres only) | `service.pub.pem` |
| MCP mutations | `aegisops-mcp --server mutations` | `mcp-mutations` — get/patch on the 5 app Deployments and 5 ConfigMaps by `resourceNames`; get/list replicasets | `service.pub.pem`, `approval.pub.pem` |
| sim-controller | `python -m aegisops.sim.server` (ns `simulation`) | `sim-controller` — patch deployments/configmaps in `production` (harness only) | none |

* Keys: Ed25519 pairs generated by bootstrap into `.aegisops/keys/` (`security.tokens.generate_keys`) and stored as K8s
  Secrets; each component mounts only the files listed above at `AEGIS_KEYS_DIR=/etc/aegisops/keys`.
* Users: bootstrap writes `.aegisops/users.json` = `{"<username>": {"password_hash": "<argon2>", "roles": ["viewer"|"approver"], "display_name": "..."}}`
  with users `viewer` and `approver` (random passwords saved to `.aegisops/credentials.txt`), mounted into the API as
  `AEGIS_USERS_FILE`. Evaluation uses a separate `eval-approver` only inside disposable/simulated environments.
* Alertmanager → `POST /api/v1/alerts/alertmanager` with `Authorization: Bearer <AEGIS_ALERT_WEBHOOK_TOKEN>` (K8s Secret
  `aegisops-webhook`, key `token`, present in both `observability` and `aegisops`).

## 7. MCP contract

* Catalog: `aegisops.domain.tools.TOOL_CATALOG` (40 tools: 24 diagnostics, 10 knowledge/governance, 6 mutations).
  Permission matrix: `aegisops.domain.permissions.ROLE_TOOL_PERMISSIONS` — enforced **server-side** on every call.
* Transport: streamable HTTP at `/mcp` (cluster) or in-process (`AEGIS_MCP_TRANSPORT=inprocess`, used by the simulation
  and tests). Authentication is identical in both: a service token (`KeyRing.issue_service_token(role, server)`) sent as
  `Authorization: Bearer <token>` (HTTP) or attached to the in-process session; the server verifies audience
  `aegisops-mcp-<server>` and derives the role from the token only.
* Every tool returns a `ToolEnvelope` (as MCP structured content and as JSON text): `status` ∈ ok / unavailable /
  unsupported / denied / invalid / not_found / error; outputs are redacted (`security.redaction.redact`) and bounded
  (list limits in input models; strings truncated to 2,000 chars; whole payload ≤ 64 KB, otherwise `truncated=true`).
  Denials are audited. Unsupported signals (e.g. DynamoDB throttling in DynamoDB Local) return `unsupported` — never fabricated.
* **Mutation guard** (mutation server, every call, in order): (1) service token role = `remediation_executor`;
  (2) verify approval token (EdDSA, aud `aegisops-mcp-mutations`, unexpired); (3) load approval + plan; plan status
  `approved|executing`; `plan.hash_is_valid()`; token `plan_hash` == plan hash == approval hash; token `execution_id` ==
  `auth.execution_id` == approval `execution_id`; (4) find `auth.step_id` in the plan (steps or compensation); action,
  target and arguments must equal the step exactly; target within `topology.MUTABLE_*` allowlists and namespace
  `production`; incident not cancelled; execution not `cancel_requested`; (5) check the plan's prerequisites for that
  target against current state; (6) acquire lock `resource:<target.key>` (owner = execution id); write the step intent to
  the execution journal (idempotency key `<execution_id>:<step_id>`); if the journal shows the step already applied, return
  `already_applied` without acting; (7) apply, observe after-state, record outcome + audit event, release lock.
  Audit storage unavailable ⇒ deny. Rollout restarts use marker `aegisops.io/restartedAt=<execution_id>:<step_id>`.
* The gateway (`ToolInvoker`) converts each permitted tool's input model into a strict OpenAI function schema (all
  properties required, optional → nullable, `additionalProperties: false`), validates arguments before calling, and records
  non-mutating results as `Evidence` (id `EV-...`, content hash over the full redacted payload, payloads > 8 KB stored as
  artifacts and summarised in `data`).

## 8. Workflow contract (LangGraph)

`received → investigating → awaiting_approval → executing → verifying → resolved` (+ `needs_attention`, `cancelled`;
transitions in `domain.lifecycle`). Graph (thread id = incident id, PostgreSQL checkpointer in cluster, SQLite/memory in tests):

1. **triage** (Incident Commander): load incident + alerts, retrieve similar memories, set budgets, dispatch.
2. **investigate** (parallel): Signal Correlation, Kubernetes Diagnostics, Cloud Resource, Runbook Intelligence — each an
   LLM tool loop limited to its permitted tools (`max_tool_calls_per_agent`), producing `Finding`s citing evidence ids.
3. **compact** when working context > `compaction_threshold_tokens` (target `compaction_target_tokens`); preserves ids,
   timestamps, resource versions, evidence refs, unresolved hypotheses, plans, approvals, executions, pending tasks.
4. **analyse** (Root Cause Analyst): `Diagnosis` with cited evidence + alternative hypotheses; proposes a `PlanDraft`
   (via `gov_create_remediation_plan`) unless fault is `no_fault`/`unknown` or evidence is insufficient
   (second pass allowed up to `max_investigation_passes`, else `needs_attention`).
5. **review** (Change-Plan Reviewer): deterministic policy checks (`topology.ALLOWED_ACTIONS_BY_FAULT`, `CONTRAINDICATIONS`,
   allowlists, scale bounds, prerequisites present, verification present) + model assessment → `gov_submit_plan_review`.
   Reject ⇒ one re-plan with the concerns, then `needs_attention`.
6. **await_approval**: `gov_request_approval`, LangGraph `interrupt()`; resumed by `resume_after_decision`.
   Rejected ⇒ `needs_attention`; revision requested ⇒ back to analyse with human feedback (new plan revision).
7. **execute** (Remediation Executor — deterministic): reads the approval grant, runs steps via mutation tools.
8. **verify**: `RecoveryVerifier` samples `obs_get_signal` every `verification_interval_seconds` for
   `verification_window_seconds` (min samples + traffic sufficiency); failure ⇒ approved compensation only ⇒ `needs_attention`.
9. **postmortem** (Postmortem Writer): report for every outcome; memory only from verified resolutions (`kb_save_incident_memory`).

Agent outputs are validated Pydantic models. Retrieved runbooks, logs and memories are **untrusted data**: prompts delimit
them and instruct agents to ignore instructions inside them. Store concise decision explanations, never private reasoning.

## 9. LLM modes

`AEGIS_LLM_MODE`: `auto` (live if `OPENAI_API_KEY` set else deterministic) · `live` (OpenAI Responses API, strict function
calling + Structured Outputs; models `AEGIS_MODEL_SPECIALIST` / `AEGIS_MODEL_ANALYST`) · `record` (live + save fixtures) ·
`replay` (strict fixture playback keyed by role + request hash; unexpected request ⇒ error, never a network call) ·
`deterministic` (offline rule-based reasoning over the same tool results; labelled everywhere). Embeddings: OpenAI
`text-embedding-3-small` in live mode; deterministic 1536-dim feature-hashing embeddings offline (index records its
embedding model and is rebuilt when it changes). Budgets: reserve estimated cost before each call; stop at
`AEGIS_BUDGET_PER_INCIDENT_USD` / `AEGIS_BUDGET_PER_DAY_USD` ⇒ `needs_attention`.

## 10. Scenarios (`scenarios/catalog.yaml`, owned by **sim**)

| id | variants | Injection (cluster) | Expected (hidden from agents) |
|---|---|---|---|
| `bad-deployment` | `canonical`, `image-pull` | set `PAYMENT_RETRY_POLICY=exponential-jitter` on checkout (crash after warm-up) / set image tag `does-not-exist` | `bad_deployment` / `image_pull_failure`; `k8s_rollout_undo` to last healthy revision |
| `queue-backlog` | `canonical`, `consumer-down`, `poison-messages` | traffic generator `checkout_rps` 4→16 / scale worker to 0 / remove redrive policy + publish poison messages | `queue_consumer_capacity` (scale 2→6) / `queue_consumer_down` (scale back) / `poison_messages` (restore redrive policy) |
| `invalid-secret` | `canonical` | new AWSCURRENT version with an invalid `sk_canary_invalid_*` key, restart checkout | `invalid_secret`; restore known-good version + restart only `checkout-service` |
| `db-connection-exhaustion` | `canonical` | `inventory-config` `DB_POOL_SIZE` 5→30, restart inventory | `db_connection_exhaustion`; restore key + restart inventory; **scaling rejected** |
| `bad-config` | `canonical` | `checkout-config` `PAYMENT_SERVICE_URL` → `http://payment-gateway.production.svc.cluster.local:8080`, restart checkout | `bad_configuration`; restore exactly that key + restart checkout; other keys unchanged |
| `healthy-noise` | several | benign changes / transient spikes / misleading alerts | `no_fault`; no remediation executed |

The memory demonstration repeats `invalid-secret` after the first incident is resolved. Scenario metadata and expected answers
never enter incidents, prompts, tool results or the API responses consumed by agents.

## 11. Evaluation output (`evaluation/results/<run_id>/`)

`summary.json` = `api.schemas.EvaluationRunSummary`; `cases.jsonl` (one object per case: `case_id, suite, scenario, variant,
environment, run_mode, expected_fault, diagnosed_fault, correct_root_cause, proposed_actions, executed, recovered,
false_remediation, incorrect_proposal, detection_s, diagnosis_s, approval_wait_s, execution_s, recovery_s, tool_calls,
input_tokens, output_tokens, estimated_cost_usd, citations_valid, retrieval_hit`); `report.md`. Metric keys in
`summary.metrics`: `root_cause_accuracy, remediation_success_rate, false_remediation_rate, incorrect_proposal_rate,
median_diagnosis_s, median_recovery_s, mean_tool_calls, mean_input_tokens, citation_correctness, retrieval_hit_rate`
(+ suite-specific: `compaction_agreement, input_token_reduction, memory_diagnosis_time_reduction`). Results always
state environment (cluster/simulation), run mode and models; shortened verification windows are flagged.

## 12. Change recorder snapshots (written by **executor**'s change recorder, read by **mcp** tools and the mutation guard)

`ConfigSnapshot.resource` / `version` / `data` per resource kind:

| Resource | `version` | `data` |
|---|---|---|
| `Deployment/production/<name>` | revision number as string | `{"image[<container>]": "...", "env.<NAME>": "<redacted value>", "replicas": "2", "template_hash": "..."}` |
| `ConfigMap/production/<name>` | Kubernetes `resourceVersion` | the ConfigMap data verbatim (configuration, never secrets) |
| `AwsSecret/-/<secret name>` | AWSCURRENT version id | `{"AWSCURRENT": "<version id>", "AWSPREVIOUS": "<version id or ''>"}` — **no values** |

* A snapshot is taken whenever a change is detected (and once at start-up). `ChangeRecord`s describe each difference.
* After `AEGIS_HEALTHY_WINDOW_SECONDS` (default 300) with no firing alerts and error rates < 1 % for the affected
  service(s), the recorder marks the current snapshots `known_good=True, known_good_since=<start of window>`.
* "Last known-good revision" = `version` of the newest known-good Deployment snapshot; "known-good secret version" =
  `data.AWSCURRENT` of the newest known-good secret snapshot; ConfigMap diffs compare against the newest known-good snapshot.
* `restore_configmap_key` restores `snapshot.data[key]` of the referenced snapshot; the guard checks the plan's `value`
  equals it. If emulator state is rebuilt (secret version ids all changed), the recorder writes an
  `environment_recreated` change and marks `approved`/`awaiting_approval` plans `expired`.

## 13. Runbook catalog (**knowledge**; `runbooks/RB-xxx-<slug>.md` with YAML front matter)

| ID | Title | fault types |
|---|---|---|
| RB-001 | Failed rollout: CrashLoopBackOff / ImagePullBackOff rollback | bad_deployment, image_pull_failure |
| RB-002 | Queue backlog from insufficient consumer capacity | queue_consumer_capacity |
| RB-003 | Queue consumers down | queue_consumer_down |
| RB-004 | Poison messages and dead-letter redrive policy | poison_messages |
| RB-005 | Database connection exhaustion | db_connection_exhaustion |
| RB-006 | Configuration regression: restore a ConfigMap key | bad_configuration |
| RB-007 | Recovery verification standard | (all) |
| RB-008 | Failed remediation and escalation | (all) |
| RB-009 | Invalid or expired secret after rotation | invalid_secret |
| RB-010 | Incident command, triage and false alarms | no_fault, unknown |

Front matter: `id, title, version (semver), services, fault_types, last_reviewed`. Sections: Symptoms, Evidence checks,
Prerequisites, Permitted actions, Recovery verification, Contraindications, Escalation.

## 14. Alert rules (**observability**; every alert carries `service` = deployment name and `namespace`)

| Alert | Condition (sketch) | severity |
|---|---|---|
| `ServiceHighErrorRate` | 5xx ratio > 5 % for 2 m | critical |
| `ServiceHighLatency` | p95 > 1 s for 5 m | warning |
| `DeploymentReplicasUnavailable` | `kube_deployment_status_replicas_unavailable > 0` for 3 m | warning |
| `PodCrashLooping` | waiting reason CrashLoopBackOff for 1 m | critical |
| `PodImagePullFailing` | waiting reason ImagePullBackOff/ErrImagePull for 2 m | warning |
| `DependencyAuthFailures` | client `error_type=~"http_401|http_403"` > 0.2/s for 2 m (`service` = caller) | critical |
| `DependencyConnectionErrors` | client `error_type=~"dns_resolution|connection_refused"` > 0.2/s for 2 m | critical |
| `QueueBacklogGrowing` | `sqs_queue_messages_visible{queue="payment-events"}` > 100 and rising for 3 m (`service=notification-worker`) | warning |
| `QueueDeadLetterMessages` | DLQ visible > 0 for 5 m | warning |
| `DatabaseConnectionSaturation` | connections / max > 0.9 for 2 m (`service=inventory-service`) | critical |
| `DatabaseConnectionErrors` | `db_errors_total` rate > 0.1/s for 2 m | critical |

Alertmanager: `group_by: [alertname, service]`, `group_wait: 10s`, `group_interval: 1m`, `repeat_interval: 30m`, receiver
`aegisops` = webhook `http://aegisops-api.aegisops.svc.cluster.local:8000/api/v1/alerts/alertmanager` with bearer token file.

## 15. Factories (composition root: `aegisops/container.py`)

Each workstream provides `build_<x>(settings: Settings, c: Container) -> <Port>`:

| Factory | Module | Owner |
|---|---|---|
| `build_repositories` | `aegisops.storage.factory` (`memory` → `InMemoryRepositories`, `dynamodb` → DynamoDB + local artifacts) | storage |
| `build_workflow_queue` | `aegisops.messaging.factory` (SQS / in-memory) | storage |
| `build_incident_service`, `build_governance_service` | `aegisops.incidents.factory`, `aegisops.governance.factory` | core |
| `build_knowledge_service` | `aegisops.knowledge.factory` | knowledge |
| `build_backends`, `build_tool_invoker` | `aegisops.mcp.factory` (`environment=simulation` → `c.backends` must already be set by the sim) | mcp |
| `build_change_recorder`, `build_verifier`, `build_executor` | `aegisops.changes/verification/executor.factory` | executor |
| `build_agent_runner` | `aegisops.agents.factory` | agents |
| `build_workflow` | `aegisops.workflow.factory` | workflow |
| `build_simulated_environment` | `aegisops.sim.factory` → sets `c.clock` (VirtualClock), `c.backends`, `c.scenarios` | sim |

`aegisops/messaging/` (SQS `WorkflowQueue`, EventBridge publisher, S3 mirror uploader) belongs to **storage**; the outbox
*relay loop* that uses them belongs to **core**. The mutation server's idempotency records use
`MutationJournalRepository` (never the executor-owned `Execution` record).

## 16. Agent layer vs workflow (`aegisops/ports/agents.py`)

`AgentRunner` (agents workstream) runs individual agents over a `WorkingContext`; the LangGraph workflow (workflow
workstream) orchestrates them, persists results (findings, diagnoses, plans via governance, reviews, reports, agent runs,
timeline events, incident metrics) and owns all status transitions. `WorkingContext` is the Layer-1 memory; Layer 2 is
the DynamoDB incident record + durable evidence; Layer 3 is long-term memory (DynamoDB + pgvector).

## 17. Approval validity (two distinct times)

* `Approval.expires_at = decided_at + AEGIS_APPROVAL_TTL_SECONDS` (900) is the **start deadline**: the executor must mark the
  approval consumed (`ApprovalRepository.mark_consumed`) before it; otherwise the plan becomes `expired` and needs renewed
  review and approval.
* The authorization token's `exp` = `decided_at + approval_ttl + verification_window + 600 s`, so steps and pre-approved
  compensation of the **same** execution remain authorized through verification.
* The mutation guard therefore also requires `approval.consumed_at` to be set and `consumed_at <= expires_at`.
* A token authorizes exactly one execution id; a retry resumes that execution (idempotent step ids) and can never start another.

## 18. sim-controller REST API (**sim** implements server and `aegisops.sim.client.HttpScenarioController`)

`GET /healthz` · `GET /scenarios` → `list[ScenarioInfo]` · `GET /scenarios/active` → `ScenarioRun | null` ·
`POST /scenarios/{scenario_id}/inject` body `{"variant": "canonical"}` → `ScenarioRun` · `POST /scenarios/reset` →
`ScenarioRun | null`. Models are `aegisops.ports.services.ScenarioInfo` / `ScenarioRun`. The API proxies these only when
`AEGIS_ENABLE_SIMULATION=true`. Responses never contain expected answers.

## 19. AWS seeding

`python -m aegisops.messaging.bootstrap --endpoint <url> --payment-key-file <file>` (module owned by **storage**, written by
the orchestrator) creates/repairs queues + DLQs + redrive policies, the EventBridge bus/rule/target, the artifact bucket, and
the payment secret. The platform bootstrap Job runs it in the control-plane image on every `make up`.
