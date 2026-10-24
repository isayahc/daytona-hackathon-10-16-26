# Getting started with Common Ground

Common Ground is a local event-planning workspace with a map, calendar, event drafts,
and a research evidence viewer. Start with the UI, then connect the research runner
when you are ready.

## Just want to try it?

Run `./run.sh` from the project folder, open
http://127.0.0.1:8080, and click **Plan an event**. Enter a name and date, then save.
That's enough to get started — the research setup below is optional.

## 1. Launch the UI

You need **Python 3.11+**. From the repository root:

```bash
./run.sh
```

This script starts both the frontend and backend. To change ports, use
`./run.sh --port 8081`.
On Windows without Bash, use `py -3 -m operator_app.server --port 8080` instead.
Open **http://127.0.0.1:8080**. Keep the terminal running; press **Ctrl+C** to stop.
The UI uses the Python standard library: no package installation, frontend build,
API keys, or database service is required.

## 2. Create your first event

1. Expand **Getting started** at the top of the workspace for the in-app walkthrough.
2. Choose **Plan an event** and enter a name, date, time, purpose, and audience.
   Select the Eastern time offset appropriate to your event date.
3. Optionally set a budget and participant target, then choose **Save event draft**.
4. Your draft is selected automatically. Use **Working on** to switch between events.
5. Choose **Export research brief** to download `event-brief.json`.

Drafts persist in `.operator/workspace.sqlite3`, relative to the directory where you
start the server. Restart from the same directory to keep using the same drafts.
To choose a different store:

```bash
python3 -m operator_app.server --port 8080 --database /path/to/workspace.sqlite3
```

Sample events and venue locations are fictional and labeled as such.

## 3. Set up research (optional)

In a second terminal at the repository root, create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-agent.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

Preview the five worker prompts with your downloaded brief:

```bash
python -m agent_runtime.research --brief ~/Downloads/event-brief.json --category energy --dry-run
```

Replace the brief path with its actual download location. Categories include
`weather`, `climate`, `defense`, and `energy`. A dry run creates no sandboxes and is
not an importable research report.

For live research, copy `.env.example` to `.env` **if you do not already have one**,
then configure `DAYTONA_API_KEY`, `OPENCODE_MODEL`, and the matching model-provider
credentials. See [Daytona configuration](DAYTONA.md) for exact settings and optional
document memory and tracing integrations.

Live research starts five Daytona sandboxes and uses your configured model provider;
service charges may apply.

```bash
python -m agent_runtime.research --brief ~/Downloads/event-brief.json --category energy --output event-research-report.json
```

## 4. Bring results into the workspace

1. Scroll to **Your event research desk** and choose **Import report**.
2. Select `event-research-report.json` from the repository root.
3. Review each worker's status, candidates, source links, and unanswered questions.
   Partial and failed runs are also displayed.

The report must belong to an event in this workspace, so run research using the
brief exported from that event. Imported reports stay in the current tab only.
Keep the report file and import it again after reloading the page.

## Event chat and party message drafts

1. Create or select an event in **Working on**.
2. Complete the agent dependency and `.env` setup in step 3 above. No separate
   frontend or chat server is needed: `./run.sh` starts everything.
3. Open **Event chat** in the bottom-right corner and describe your event needs, e.g.:

   > Plan a neighborhood repair day for 30 people. Ask venues about accessible
   > space, sponsors about tools, caterers about vegetarian lunch, and volunteers
   > about helping. Keep the messages friendly and concise.

4. Choose **Draft messages**. The agent runs in a Daytona sandbox; generation can
   take a few minutes and uses your Daytona/model-provider accounts.
5. Choose **View drafts** to see messages grouped by venues, sponsors, catering,
   and contacts. **Save edits** persists your changes; **Copy message** copies the
   subject and body. Messages are not sent.
6. Send a follow-up such as “Make the sponsor ask about donated supplies instead
   of money” to generate a revised set. The agent receives the three most recent
   requests and saved drafts as context.

The selected event is the context; chat does not create or change the event's date,
budget, or other saved fields. Linked parties are used by default. If you import a
research report first, up to three candidates per party category are used instead.
Unassigned parties get clearly marked recipient placeholders; sample parties remain
labeled fictional. One generation runs at a time across the local workspace.

Conversations and message drafts are saved in the same SQLite database as event
drafts. The UI displays the 20 most recent requests and the latest completed draft
set; a failed request leaves your previous drafts available. Unsaved edits remain
in the current tab only. If the server stops during a run, the next startup marks
the run as interrupted so you can submit again.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| `python3` is not found | Install Python 3.11+ or try `python` / `py -3`. |
| `No module named operator_app` | Run the command from the repository root. |
| Port 8080 is already in use | Start with `--port 8081`, then open http://127.0.0.1:8081. |
| Workspace cannot load | Keep the Python server running and open its HTTP URL rather than opening `index.html` directly. |
| Map is unavailable | External Leaflet/OpenStreetMap assets need network access; use the venue list instead. |
| Draft cannot be saved | Ensure the database directory is writable, or choose another path with `--database`. |
| Report belongs to another event | Open the original draft store and use a report generated from that event's exported brief. |

The server is a loopback-only local workspace. Outreach is a separate CLI workflow;
see [SETUP.md](SETUP.md). For research lifecycle and credentials, see [DAYTONA.md](DAYTONA.md).
