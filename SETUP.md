# LinkedIn and Gmail outreach

Python 3.11+; use a project-local virtual environment as shown below. This is a single-user CLI, not a hosted multi-user login service. Anchor runs the browser agent; SurrealDB stores drafts and delivery state. LinkedIn and Gmail are accessed through their websites in your manually authenticated browser. No LinkedIn messaging API or Gmail OAuth client is required for this browser workflow.

## 1. Configure

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
source .venv/bin/activate
cp .env.example .env
# Edit .env with your Anchor API key and SurrealDB connection settings.
python outreach.py --help
```

Every CLI command automatically loads `.env` from the directory containing `outreach.py`, including when launched from another working directory. No `source` or manual export is needed. Existing environment variables take precedence over `.env` values. Loading uses [python-dotenv](https://bbc2.github.io/python-dotenv/), which supports quoted values, comments, and `${VARIABLE}` expansion. A missing `.env` is fine when settings are already provided through the environment.

In a new terminal, activate `.venv` again or run `.venv/bin/python outreach.py session` directly. Activating the virtual environment selects the project's Python dependencies; `.env` configuration is loaded automatically either way.

Use your SurrealDB Cloud HTTP(S) instance origin as `SURREAL_URL`, without `/rpc`. Set namespace, database, and instance credentials, or an appropriate database token. Keep these on your machine, never in git. This adapter supports instance basic authentication or bearer tokens, not the separate Surreal Cloud management API token. Use TLS for remote services.

For an isolated local demo with Docker:

```bash
docker run --rm --name outreach-db -p 127.0.0.1:8000:8000 \
  surrealdb/surrealdb:v2.3.10 start --user root --pass demo-only memory
```

Set `SURREAL_URL=http://127.0.0.1:8000`, `SURREAL_USER=root`, `SURREAL_PASS=demo-only`, namespace/database `outreach`. Memory mode is disposable; use Cloud or a persistent database for retained history.

## 2. Start a browser and sign in

```bash
python outreach.py session
```

Open the returned `live_view_url` privately. Navigate to LinkedIn and/or Gmail and sign in yourself, completing any MFA. Keep the session `id`. You can also use an already-running Anchor session by passing its ID directly to `send`.

Session troubleshooting: the CLI reports the HTTP status with guidance. HTTP 400 means Anchor rejected request parameters; its [session API schema](https://docs.anchorbrowser.io/api-reference/browser-sessions/start-browser-session) requires `browser.headless` to be `{"active": false}`, not the boolean `false`. HTTP 401/403 indicates credentials or access permissions, HTTP 402 indicates insufficient credits, and HTTP 429 indicates a rate/concurrency limit. Provider response bodies and private URLs are omitted from CLI errors.

Browser login is provider-dependent: Google or LinkedIn may reject a cloud browser or ask for verification. If that happens, stop and resolve it manually; this CLI does not bypass verification. Login success must be checked in the live browser.

Optional persistence after signing in:

```bash
python outreach.py save-profile --session SESSION_UUID --name personal-outreach
python outreach.py end-session --session SESSION_UUID
python outreach.py session --profile personal-outreach
```

Anchor stores the new profile when the source session terminates. Use a new profile name when creating one; resume existing profiles with `session --profile`. Browser cookies remain with Anchor, not in SurrealDB. Session creation disables video recording; browser automation still processes the pages and messages you ask it to operate on. Treat live-view/CDP links as private access credentials. Sessions expire after 60 minutes, or 15 idle minutes; end them when finished.

## 3. Create a draft

Write your message to a UTF-8 text file (for example `message.txt`), then:

```bash
python outreach.py draft --channel linkedin \
  --recipient https://www.linkedin.com/in/EXACT-PROFILE/ \
  --body-file message.txt

python outreach.py draft --channel gmail \
  --recipient person@example.com --subject 'Follow-up' --body-file message.txt
```

The command returns a draft `key`. LinkedIn requires a specific profile URL; Gmail requires one email address. This version stores your supplied text; it does not generate outreach copy or discover contacts automatically.

## 4. Review and send

```bash
python outreach.py show DRAFT_UUID
python outreach.py send DRAFT_UUID --session SESSION_UUID
```

The send command displays the exact stored recipient and message. Type `SEND` to submit one browser task. Cancellation does not contact Anchor. No messages are sent by session setup, draft creation, or review.

The agent is instructed to verify the recipient, use the supplied text, and stop on ambiguous recipients, payment, or authentication challenges. These are agent instructions, not a deterministic guarantee about website behavior. Review the result in the live browser.

## 5. Inspect history

```bash
python outreach.py history
python outreach.py end-session --session SESSION_UUID
```

Delivery states:

| State | Meaning |
| --- | --- |
| `draft` | Stored, never claimed for sending. |
| `attempting` | Atomically claimed; may be running or interrupted. |
| `reported_sent` | Agent returned structured confirmation with evidence; verify in the browser. |
| `needs_review` | Failure, block, missing evidence, or uncertain delivery. |

Only `draft` can be claimed. Attempts are never automatically retried. If a process dies after claiming or a database write fails after delivery, inspect the browser before doing anything else; `attempting` also requires reconciliation. A new draft permits a new attempt, so do not create one until you have checked for prior delivery.

The database stores recipient, subject, body, and status. It does not store account passwords, API keys, cookies, or raw browser responses. There is no public server to expose this personal workflow.

## Document ingestion: originals and extracted text

The CLI can download public documents from weather, climate, defense, and energy sources and store **both the exact downloaded file and extracted text** in SurrealDB. It uses the same automatically loaded `.env` database settings. A database password (`SURREAL_PASS`) or database bearer token (`SURREAL_TOKEN`) is required; Anchor credentials alone do not provide database access.

Install/update dependencies inside the project environment:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Give the ingest command a direct document URL (replace the example URL with your source). Categories are `weather`, `climate`, `defense`, and `energy`:

```bash
.venv/bin/python outreach.py documents ingest \
  --url 'https://YOUR-SOURCE/report.pdf' \
  --category climate --title 'Climate report'

.venv/bin/python outreach.py documents list
.venv/bin/python outreach.py documents list --category energy
.venv/bin/python outreach.py documents show DOCUMENT_KEY
.venv/bin/python outreach.py documents search 'renewable energy' --category energy
```

Ingest returns a 64-character `key`, source and redirected URLs, source host, filename, MIME type, download timestamp, optional ETag/Last-Modified, byte size, SHA-256, chunk counts, and extraction status. Re-ingesting the same source URL, category, and file content returns the existing document (`already_stored: true`); changed content at the same URL is a separate version. Different source URLs/categories retain separate provenance even for identical files. The original title and first download timestamp are retained for duplicates.

Restore either version of a document to a new local output file:

```bash
.venv/bin/python outreach.py documents export DOCUMENT_KEY --output report.pdf
.venv/bin/python outreach.py documents export DOCUMENT_KEY --text --output report.txt
```

Export verifies the full original/text SHA-256 before writing and refuses to overwrite existing files. The original is stored in the database, not merely linked by URL or retained only on local disk.

### Storage and extraction

- `document`: published metadata/manifest, including original and text checksums.
- `document_blob`: ordered 256 KiB chunks stored as native SurrealDB `bytes`. JSON transport uses unpadded base64 and `encoding::base64::decode()`; export uses `encoding::base64::encode()`.
- `document_text`: ordered 16,000-character extracted-text chunks for retrieval and simple case-insensitive substring search. Search returns at most 20 matching chunks from published documents, optionally filtered by category; phrases spanning chunk boundaries are not matched.

The `document` table also holds the agent runtime's retrieved-text records. Each CLI lists its own representation: `outreach.py documents` handles downloaded-file manifests, while `python -m document_store` handles captured text. Both workflows can use the same namespace/database.

Each chunk is sent in its own request, below the default 4 MiB HTTP RPC request ceiling. The manifest is written only after all chunk writes succeed. An interrupted upload does not appear in document listings/search; retrying the same ingest overwrites its deterministic chunk IDs and completes it. Abandoned partial uploads can leave unpublished chunks. This workflow uses SurrealDB 2.3+ record/bytes APIs, without requiring experimental file buckets or external object storage. It requires permission to read/write these three tables (which are auto-created as schemaless tables in an unrestricted demo database).

Text extraction supports digitally generated PDFs (`pypdf`), static HTML, and plain-text formats including TXT, Markdown, CSV, JSON, and XML. Extraction status is `extracted`, `no_text`, `encrypted`, `unsupported`, or `failed`; failures include an exception type. Original files are retained even when extraction is unavailable. Scanned/image-only PDFs need a later OCR step. HTML extraction reads the downloaded response, without running JavaScript or distinguishing a site's login/error page from ordinary HTML. Unsupported formats such as DOCX/ZIP are retained as originals with no extracted text.

Downloads are limited to 50 MiB per document and use public HTTP(S) URLs directly. Start with the exact report/download links from your chosen sources; this command ingests one URL at a time. Website discovery, scheduled collection, and authenticated browser downloads can be connected once source sites are selected.

References: [SurrealDB bytes](https://surrealdb.com/docs/surrealql/datamodel/bytes), [base64 functions](https://surrealdb.com/docs/surrealql/functions/database/encoding), [RPC limits](https://surrealdb.com/docs/surrealdb/integration/rpc), [UPSERT](https://surrealdb.com/docs/surrealql/statements/upsert), [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).

## Validation

```bash
python -m unittest discover -s tests -v
python -m compileall -q outreach.py documents.py
```

Offline tests exercise recipient validation, parameterized conditional delivery claims, provider response handling, and reuse of the signed-in session. Real LinkedIn/Gmail delivery requires your credentials and a live acceptance test. No real messages were sent during implementation.

Document tests exercise actual PDF extraction, encrypted/blank PDFs, HTML text, byte-for-byte multi-chunk exports, checksums, duplicate detection, interrupted-upload recovery, and download limits against an offline recording database. Optional real-database tests start a disposable in-memory SurrealDB process and a local HTTP document server, then verify ingestion, category filtering, search, original/text exports, and a 5 MiB original-file round trip. These tests do not use your `.env` database or require your credentials. They were validated against SurrealDB 2.3.10 and are enabled in CI.

If you have a local SurrealDB binary, enable those integration tests with:

```bash
SURREAL_TEST_BINARY=/path/to/surreal .venv/bin/python -m unittest discover -s tests -v
```

Without that setting, the three real-database tests are skipped. These checks also verify that runtime text capture and downloaded-file storage coexist in the same database. Uploads to your own instance still require the database connection settings described above.

## API references

- [Anchor sessions](https://docs.anchorbrowser.io/quickstart/create-session)
- [Anchor profile persistence](https://docs.anchorbrowser.io/api-reference/profiles/create-profile)
- [Anchor web task API](https://docs.anchorbrowser.io/api-reference/ai-tools/perform-web-task)
- [SurrealDB HTTP/RPC](https://surrealdb.com/docs/reference/rest-api)

## Operator workspace UI skeleton

```bash
python -m operator_app.server --port 8080
```

Open **http://127.0.0.1:8080** on the machine running the command. No Python dependencies are needed. The server binds only to loopback and serves static files from `operator_app/static`, not the repository or environment files.

The NYC venue map, monthly calendar/agenda, event metrics, activity filters, and event detail panel share a selected event. Click a venue card or calendar event to change context. Use the arrows to browse months. Activity rows open read-only detail dialogs. All fixtures are fictional, labeled mock, and contain no connected account data. The plan-event button explains the next step rather than pretending to save a plan.

- `operator_app/models.py`: reusable typed dataclasses and enums for organizations, locations, venues, events, activities, metrics, and the workspace envelope.
- `operator_app/mock_data.py`: sole source of sample records and their relationships.
- `GET /api/workspace`: serialized model data with explicit mock provenance, schema version, and Eastern-time timestamps.
- `operator_app/static/`: responsive UI with keyboard-accessible controls and native dialogs.

Leaflet and fonts load from public CDNs, and map tiles come from OpenStreetMap. If map assets cannot load, venue cards remain available. Leaflet attribution is retained. No social provider is connected by the UI, and its buttons do not execute the outreach CLI. This change is a UI skeleton, not a production hosted service.
