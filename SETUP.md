# LinkedIn and Gmail outreach

Python 3.11+; standard library only. This is a single-user CLI, not a hosted multi-user login service. Anchor runs the browser agent; SurrealDB stores drafts and delivery state. LinkedIn and Gmail are accessed through their websites in your manually authenticated browser. No LinkedIn messaging API or Gmail OAuth client is required for this browser workflow.

## 1. Configure

```bash
cp .env.example .env
# Edit .env with your Anchor API key and SurrealDB connection settings.
set -a
source .env
set +a
python outreach.py --help
```

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

## Validation

```bash
python -m unittest discover -s tests -v
python -m compileall -q outreach.py
```

Offline tests exercise recipient validation, parameterized conditional delivery claims, provider response handling, and reuse of the signed-in session. Real LinkedIn/Gmail delivery requires your credentials and a live acceptance test. No real messages were sent during implementation.

## API references

- [Anchor sessions](https://docs.anchorbrowser.io/quickstart/create-session)
- [Anchor profile persistence](https://docs.anchorbrowser.io/api-reference/profiles/create-profile)
- [Anchor web task API](https://docs.anchorbrowser.io/api-reference/ai-tools/perform-web-task)
- [SurrealDB HTTP/RPC](https://surrealdb.com/docs/reference/rest-api)
