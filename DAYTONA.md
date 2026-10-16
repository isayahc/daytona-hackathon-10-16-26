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

With `SURREAL_URL` and the existing SurrealDB credentials configured, the runtime automatically ingests **completed OpenCode `webfetch` results at the end of each turn**. No separate ingestion switch is required. It captures the retrieved text/Markdown/HTML representation, rather than claiming to store original binary files.

Each `document` record contains:

- `key`: deterministic SHA-256 of the source URL and content checksum.
- `source_url`, `title`, `content`, `content_format`, `content_sha256`.
- `retrieved_at` (UTC), `source_session_id`, `source_tool_call_id`.
- `capture_method`, `is_truncated`, and `is_mock` provenance fields.

The reusable `Document` dataclass lives in `operator_app/models.py`. Repeated source/content pairs are upserted to the same record; changed content creates a different version. Upsert updates the latest retrieval metadata for that version; this is not a full history of every fetch occurrence. Different sources retain distinct records even if their text matches.

The host Python process writes to SurrealDB. Database credentials remain outside the Daytona sandbox. Agent results include `document_keys` and a `document_storage` status; without `SURREAL_URL`, the status is explicitly `not_configured`.

Only actual completed `webfetch` outputs are captured. Links merely mentioned in a response, search snippets, subagent-internal fetches not emitted by the parent CLI, browser pages from Anchor, and binary PDF attachments are not automatically ingested by this adapter. For PDFs, ingest extracted text using the manual command below. Documents over 2 MiB must be explicitly split rather than silently truncated. A truncated tool output is labeled when the tool supplies that metadata.

Completed retrievals are processed before final-response parsing, including when a turn later reports an error. Backend errors fail the turn with the document version ID and preserve the original exception chain. A process/network interruption before the command output reaches the host cannot be captured by this end-of-turn adapter. There are no automatic retries of the agent turn; ingestion itself is idempotent.

Manual ingestion and retrieval (using the same environment as `outreach.py`):

```bash
python -m document_store ingest --url https://example.org/guide \
  --title 'Program guide' --text-file guide.txt --format text
python -m document_store list
python -m document_store show DOCUMENT_KEY
```

Use your actual HTTP(S) SurrealDB instance origin in `SURREAL_URL`; `https://surrealdb` is not assumed to be your database endpoint. The existing local demo or your Surreal Cloud instance works with the same adapter. No live database write was performed during development; provide the instance credentials to verify the full workflow.
