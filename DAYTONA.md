# Daytona + OpenCode + Arize runtime

Issue #2 uses **OpenCode as the base agent**, running inside a private Daytona sandbox. Python controls sandbox lifecycle and submits one or more agent turns. Arize's official OpenCode tracing adapter connects to Arize AX or Phoenix; no replacement agent framework is required.

## Setup

Python 3.11+ on your machine:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-agent.txt
cp .env.example .env
# Fill the relevant values, then load them:
set -a
source .env
set +a
```

Required:

- `DAYTONA_API_KEY`: a Daytona API key.
- `OPENCODE_MODEL`: the exact `provider/model` identifier available to your account.
- Credentials for that model provider. AWS Bedrock is supported through `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / optional `AWS_SESSION_TOKEN`, or `AWS_BEARER_TOKEN_BEDROCK`; set `AWS_REGION`. The local AWS profile/SSO files are not copied into the sandbox. For OpenAI, Anthropic, or Gemini use the matching API key variables in `.env.example`.

The default TypeScript sandbox must contain npm, Python 3, curl, and git. Set `DAYTONA_SNAPSHOT` to a prepared snapshot if your default image lacks them. The launcher checks for these tools before installation. It installs `opencode-ai@1.19.3`; the Python SDK is pinned to `daytona==0.224.1`.

## Run one nonprofit planning task

Create `task.txt` containing a request such as:

> Plan an NYC community repair workshop for 35 participants. Read context.json if available. Propose a budget, venue criteria, sponsor asks, and an evidence collection checklist. Distinguish fictional sample context from verified information. Prepare drafts only; do not contact anyone or make commitments.

To provide the same typed sample workspace used by the UI:

```bash
python -c 'from operator_app.server import workspace_json; from pathlib import Path; Path("demo-context.json").write_bytes(workspace_json())'
python -m agent_runtime --prompt-file task.txt --context demo-context.json
```

Or omit `--context` to run without a fixture. Only that explicit JSON file is uploaded; the runtime does not upload the repository, `.env`, or browser sessions. It passes the provider environment variables listed in `agent_runtime/runtime.py`. The Daytona, Anchor, and SurrealDB credentials are not forwarded to OpenCode.

The CLI prints the sandbox ID to stderr and emits a JSON result containing the OpenCode session ID and final text. Multiple prompt files continue the same session:

```bash
python -m agent_runtime --prompt-file task.txt --prompt-file followup.txt --context demo-context.json
```

The sandbox is deleted on completion, so continuation is within one command/context, not across separate CLI invocations. Save the printed outputs if needed. This runtime does not automatically persist final answers in SurrealDB or invoke the outreach CLI. Retrieved source documents are persisted when database settings are configured, as described below. The UI remains a mock-data skeleton.

## Five parallel event researchers

`agent_runtime.research` coordinates **exactly five independent Daytona sandboxes**
for one event brief. Each owns its own SDK client, OpenCode session, and filesystem;
the host runs them concurrently using a five-thread executor.

| Worker | Research output |
| --- | --- |
| `contacts` | Nonprofit organizers, experts, publicly listed professional contacts, supporting source pages |
| `venues` | Candidate spaces, booking contacts, accessibility, published capacity/pricing, unknown availability |
| `sponsors` | Mission-aligned prospective sponsors, partnership contacts, tailored sponsorship propositions |
| `catering` | Providers, inquiry channels, dietary options, published prices and draft inquiries |
| `proposals` | Event program propositions, audience benefits, agenda options and measurable outcomes |

### Configure and launch

Install both dependency sets and configure the existing `.env` settings:

```bash
.venv/bin/python -m pip install -r requirements.txt -r requirements-agent.txt
```

- `DAYTONA_API_KEY` and enough Daytona quota for five simultaneous sandboxes.
- `OPENCODE_MODEL` plus the matching provider credentials: OpenAI, Anthropic, Google,
  or AWS Bedrock (including `AWS_REGION`). Five workers also share provider rate limits.
- Optional `DAYTONA_SNAPSHOT`, tracing settings, and Spectron/direct-database settings.

The CLI loads the project `.env`; existing environment values take precedence.
Missing credentials fail before provisioning. `examples/event-research.json` contains
the proposed nonprofit Community Energy & Resilience Workshop. Replace its fictional
organizer/date with your own event details when appropriate. The brief requires an
organization and event with matching organizer ID, title, and timezone-aware start
time. Budget, end time, venue, attendees, and other ecosystem relationships are optional.
`location`, `objectives`, and `max_candidates` (1–10 per worker) guide research.

```bash
# Inspect all five role prompts without requiring credentials or creating resources.
.venv/bin/python -m agent_runtime.research \
  --brief examples/event-research.json --dry-run

# Provision five workers and collect one structured report.
.venv/bin/python -m agent_runtime.research \
  --brief examples/event-research.json --category energy \
  --timeout 300 --output event-research-report.json
```

Only the explicit brief and retrieved evidence enter each sandbox; the repository,
`.env`, browser sessions, Daytona API key, and storage credentials stay on the host.
Each sandbox receives only the selected model-provider credentials, requested tracing
setup, and `OPENCODE_ENABLE_EXA=1`, which enables OpenCode's built-in web search for
the pinned OpenCode release. No additional search API key is required. Workers discover
pages with `websearch` and read them with `webfetch`; search results alone are not saved
as source documents. Search-service availability and network access still affect results.

### Shared memory and consolidated results

All workers retrieve relevant stored passages and save completed webfetch results
through the same host-side document adapter. A lock serializes memory operations to
avoid concurrent duplicate-upload races; the web-research turns run concurrently.
With no database configured, research still runs and results report document storage
as `not_configured`. Configure Spectron to reuse fetched documents in later runs.

Progress and sandbox IDs go to stderr. JSON on stdout (and the optional output file)
includes:

- Run ID, event ID, timestamp, and `completed`, `partial`, or `failed` run status.
- One result per role, preserving successful output if another worker fails.
- Structured candidate lists grouped by role, source URLs, rationale, role-specific
  details, and open questions. Candidates remain proposals; results do not modify the
  event, register attendees, create commitments, or send outreach.
- Each worker's OpenCode session, retrieved-source citation map, saved document keys,
  observed completed web-search count and fetched URLs.
- Sandbox IDs and cleanup status: `not_created`, `delete_requested`, or `failed`.
  `delete_requested` means the SDK accepted deletion, not independently confirmed destruction.

A worker is `completed` only if it returns the expected JSON contract and emitted
at least one completed `websearch` and `webfetch` tool event. Otherwise it is
`incomplete` or `failed`; natural-language claims of browsing do not count as tool
evidence. Candidate `evidence_status=source_retrieved` means all its cited URLs were
read in that worker's turn or supplied from document memory. It does not independently
validate the model's claims; other candidates are `unverified`.

The CLI exits 0 for a completed run, 1 for partial/failed research, and 2 for invalid
configuration. A cleanup failure makes that worker fail while preserving its completed
research and sandbox ID for recovery. Other workers continue; failures are not retried.
The existing per-sandbox cleanup handles boot failures and turn errors. On keyboard
interruption, the executor waits for in-flight workers to finish their bounded work
and cleanup; interruption does not instantly terminate a remote command. Abrupt host
termination can still leave sandboxes requiring manual cleanup.

`--timeout` bounds each model turn, not the whole batch: provisioning, package/tracing
installation, document storage, and deletion take additional time. All workers use
the same model/category/tracing settings. The report is saved locally; fetched source
documents are persisted in configured memory. The read-only workspace UI does not yet
launch research jobs or automatically import candidate records.

### Verification

Offline tests use a barrier to prove all five researchers can be in flight together,
exercise the real runtime lifecycle with a simulated boot failure, preserve partial
results, label unobserved browsing, record cleanup failures, and serialize shared
memory operations. Live five-sandbox provisioning/search/inference requires Daytona
and model credentials and has not been verified in this environment.

## Enable Arize AX tracing

Set:

```dotenv
AGENT_TRACING=arize
ARIZE_API_KEY=your-key
ARIZE_SPACE_ID=your-space
ARIZE_PROJECT_NAME=nyc-nonprofit-operator
```

Then run the same command. The runtime installs the official `Arize-ai/coding-harness-tracing` OpenCode adapter from pinned revision `20b0635d55925dd7394171999df1cc25de85ec3f`, using its non-interactive installer. The adapter's plugin is installed inside the sandbox before OpenCode starts. The installer reads an explicit private dotenv file so project configuration works in unattended mode.

Prompt text, tool details, and tool output logging are disabled by default. Arize still receives execution metadata and tracing credentials must be scoped appropriately. Installation success is not proof of trace receipt: the result's `trace_delivery_verified` remains false until independently verified.

In Arize AX, open the configured project after a completed turn and verify a trace with LLM/tool spans. If it is missing, check `~/.arize/harness/logs/opencode.log` privately inside the running sandbox. For debugging, use the Python context interface below so you can inspect the sandbox before exit. The default CLI deletes it after the final result.

## Phoenix alternative

Set `AGENT_TRACING=phoenix`, `PHOENIX_ENDPOINT`, optional `PHOENIX_API_KEY`, and `PHOENIX_PROJECT`. The endpoint must be reachable from the remote sandbox. `localhost:6006` would refer to the sandbox itself, not your laptop. Hosted Phoenix or an appropriately reachable deployment avoids that mismatch.

Tracing defaults to **off**, allowing Daytona/OpenCode to run before observability credentials are ready. Requesting a backend without its required settings fails before creating a sandbox.

## Reuse from Python

```python
from agent_runtime import DaytonaOpenCodeRuntime, RuntimeConfig


def plan_event(model: str) -> str:
    """Run two planning turns in the same isolated OpenCode session."""
    with DaytonaOpenCodeRuntime(RuntimeConfig(model=model, tracing="arize")) as agent:
        first = agent.run("Draft a resource-conscious NYC nonprofit workshop plan. Do not contact anyone.")
        final = agent.run("Now add an evidence checklist for future sponsors and grants.")
        assert first.session_id == final.session_id
        return final.text
```

## Lifecycle and verification limits

- Private sandbox; no public OpenCode server/preview endpoint is created.
- Fixed subprocess commands read prompts from uploaded JSON rather than shell interpolation.
- Every turn has a timeout. Timeout/errors trigger cleanup, with no automatic retry.
- Normal exit, boot failure, exceptions, and keyboard interruption call sandbox deletion.
- Abrupt host termination/network loss can prevent deletion. The printed sandbox ID enables manual cleanup in Daytona; a 10-minute auto-stop and immediate deletion on stop are configured as fallback. A running process may keep a sandbox active; do not treat this as a guaranteed wall-clock cost cap.
- Provider credentials exist in the sandbox environment while the agent runs. Treat it as a trusted operator-owned agent environment. AGENTS.md instructs the agent to prepare drafts, preserve provenance, and leave external sends/commitments to the reviewed workflow.
- Offline lifecycle/parser tests and installed-SDK compatibility checks pass. Live Daytona provisioning, inference, and backend trace receipt require account credentials and have not been verified in this implementation environment.

## Sources

- [Daytona OpenCode integration](https://www.daytona.io/docs/en/guides/opencode/)
- [Daytona Python SDK](https://www.daytona.io/docs/en/python-sdk/)
- [OpenCode CLI](https://opencode.ai/docs/cli/)
- [OpenCode provider configuration](https://opencode.ai/docs/providers/)
- [Arize OpenCode tracing](https://github.com/Arize-ai/coding-harness-tracing/tree/main/tracing/opencode)

## Automatically save discovered documents to SurrealDB

With `SPECTRON_URL`, `SPECTRON_CONTEXT_ID`, and `SPECTRON_API_KEY` configured, the runtime automatically saves **completed OpenCode `webfetch` results at the end of each turn** to Spectron (SurrealDB Agent Memory). Alternatively, configure `SURREAL_URL` and the existing direct SurrealDB credentials. Spectron takes precedence when configured. No separate ingestion switch is required. It captures the retrieved text/Markdown/HTML representation, rather than claiming to store original binary files. See [Spectron setup and smoke test](SETUP.md#spectron--surrealdb-agent-memory).

Each `document` record contains:

- `key`: deterministic SHA-256 of the source URL and content checksum.
- `source_url`, `title`, `content`, `content_format`, `content_sha256`.
- `retrieved_at` (UTC), `source_session_id`, `source_tool_call_id`.
- `capture_method`, `is_truncated`, and `is_mock` provenance fields.

The reusable `Document` dataclass lives in `operator_app/models.py`. Repeated source/content pairs are upserted to the same record; changed content creates a different version. Upsert updates the latest retrieval metadata for that version; this is not a full history of every fetch occurrence. Different sources retain distinct records even if their text matches.

The host Python process writes to the selected storage backend. Database and Spectron credentials remain outside the Daytona sandbox. Agent results include `document_keys` and a `document_storage` status; without either backend configured, the status is explicitly `not_configured`.

Only actual completed `webfetch` outputs are captured. Links merely mentioned in a response, search snippets, subagent-internal fetches not emitted by the parent CLI, browser pages from Anchor, and binary PDF attachments are not automatically ingested by this adapter. For PDFs, ingest extracted text using the manual command below. Documents over 2 MiB must be explicitly split rather than silently truncated. A truncated tool output is labeled when the tool supplies that metadata.

Completed retrievals are processed before final-response parsing, including when a turn later reports an error. Backend errors fail the turn with the document version ID and preserve the original exception chain. A process/network interruption before the command output reaches the host cannot be captured by this end-of-turn adapter. There are no automatic retries of the agent turn; ingestion itself is idempotent.

Manual ingestion and retrieval (using the same environment as `outreach.py`):

```bash
python -m document_store ingest --url https://example.org/guide \
  --title 'Program guide' --text-file guide.txt --format text
python -m document_store list
python -m document_store show DOCUMENT_KEY
```

For the direct database backend, use your actual HTTP(S) SurrealDB instance origin in `SURREAL_URL`; `https://surrealdb` is not assumed to be your database endpoint. For Spectron, use the context endpoint and `SPECTRON_*` settings above. Run `.venv/bin/python smoke_surrealdb.py` to verify the selected backend. The Spectron path has been verified with a live webfetch-event ingestion, exact raw retrieval, checksum, listing, duplicate detection, and cleanup.
