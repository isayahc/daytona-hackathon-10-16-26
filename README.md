# Daytona HackSprint NYC — October 16, 2026

Hackathon workspace for the **Daytona HackSprint with Arize AI** in New York City. This README is a quick reference for builders, organizers, and judges.

## Daytona agent runtime

Run **OpenCode inside a private Daytona sandbox**, orchestrated from Python, with optional **Arize AX / Phoenix tracing**. Supports sequential turns and automatic sandbox cleanup. See [DAYTONA.md](DAYTONA.md) for provider credentials, setup, and verification limits.

```bash
pip install -r requirements-agent.txt
python -m agent_runtime --prompt-file task.txt
```

## Research document memory

### Five-worker event research

Run **five independent Daytona sandboxes in parallel** for public contacts,
venues, prospective sponsors, catering, and event propositions. Each uses OpenCode
web search and source-page retrieval, shares host-side document memory, and returns
structured candidates in one event-linked report.

```bash
.venv/bin/python -m pip install -r requirements.txt -r requirements-agent.txt
.venv/bin/python -m agent_runtime.research \
  --brief examples/event-research.json --category energy \
  --output event-research-report.json
```

Configure `DAYTONA_API_KEY`, `OPENCODE_MODEL`, and provider credentials in `.env`.
Use `--dry-run` to inspect the five research prompts without creating sandboxes.
See [parallel research setup, reports, and lifecycle](DAYTONA.md#five-parallel-event-researchers).

Completed OpenCode web fetches automatically save their retrieved text and provenance to SurrealDB when database settings are configured. Documents have reusable typed models, stable version IDs, checksums, and source URLs. See [automatic document ingestion](DAYTONA.md#automatically-save-discovered-documents-to-surrealdb).

With Spectron configured, ingest local PDF/DOCX/HTML/text files or public document
URLs, then search saved passages or let the agent retrieve them before each turn.
Topics: weather, climate, defense, and energy.

```bash
.venv/bin/python -m document_store ingest --url https://www.energy.gov/solar --category energy --title "DOE Solar Energy"
.venv/bin/python -m document_store search "community solar resilience" --category energy
.venv/bin/python -m agent_runtime --prompt-file examples/energy-research.txt --category energy
```

The agent command also requires Daytona and model-provider credentials. See
[document-grounded research](SETUP.md#document-grounded-research) for file uploads,
citation behavior, and retrieval limits.

## Operator workspace UI

A responsive NYC map, event calendar, and activity stream with linked event selection and clearly labeled fictional data. Shared Python domain models live in `operator_app/models.py`.

```bash
python -m operator_app.server --port 8080
```

Open http://127.0.0.1:8080. See [setup and scope](SETUP.md#operator-workspace-ui-skeleton). Tracks [Epic #5](https://github.com/isayahc/daytona-hackathon-10-16-26/issues/5).

## Outreach prototype

Use an authenticated **Anchor Browser** session to send a reviewed LinkedIn message or Gmail email, with drafts and delivery history stored in **SurrealDB**. Use a project-local virtual environment (see setup below); the CLI automatically loads your project `.env`.

**[Setup and demo walkthrough → SETUP.md](SETUP.md)**

## Research document ingestion

Download weather, climate, defense, and energy documents into SurrealDB, retaining original files, extracted PDF/HTML/plain text, source metadata, and SHA-256 checksums. The CLI supports category filtering, text search, duplicate detection, and verified file/text export. Run `.venv/bin/python outreach.py documents --help`; see the [document ingestion walkthrough](SETUP.md#document-ingestion-originals-and-extracted-text).

## Event links

- [Official event page and schedule](https://luma.com/hacksprint-nyc)
- [Devpost: requirements, prizes, and submission](https://daytona-hacksprint-nyc.devpost.com/)
- [Organizer's participant brief](https://branch-zinc-3e1.notion.site/Daytona-HackSprint-w-Arize-AI-NYC-October-2026-3e4147104f3280ac8e4cc8b19696b212)

**Submission deadline:** October 16, 2026 at **3:30 PM Eastern**. Finalist presentations begin at 4:00 PM; awards are at 4:45 PM. Teams may have up to four people. The presentation is **three minutes**, including slides and a live agent demonstration.

## Sponsors and getting started

Thank you to **Daytona**, host and organizer; **Arize AI**, Gold Partner and co-host; and event partners **AWS**, **ElevenLabs**, **Anchor Browser**, and **SurrealDB**.

The links below point to official product websites and documentation. Logos use the brands' GitHub organization avatars.

| Logo | Sponsor / partner | Platform | Get started |
| :---: | --- | --- | --- |
| <a href="https://www.daytona.io/"><img src="https://github.com/daytonaio.png?size=96" alt="Daytona logo" width="56" height="56"></a> | **[Daytona](https://www.daytona.io/)** — Host | Isolated sandboxes for running agent-generated code. | [Documentation and quick start](https://www.daytona.io/docs/) · [Dashboard / account](https://app.daytona.io/) |
| <a href="https://arize.com/"><img src="https://github.com/Arize-ai.png?size=96" alt="Arize AI logo" width="56" height="56"></a> | **[Arize AI](https://arize.com/)** — Gold Partner | Agent tracing, observability, evaluation, and experiments. | [Arize AX docs](https://arize.com/docs/ax) · [Phoenix docs](https://arize.com/docs/phoenix/) |
| <a href="https://aws.amazon.com/"><img src="https://github.com/aws.png?size=96" alt="AWS logo" width="56" height="56"></a> | **[AWS](https://aws.amazon.com/)** — Partner | Cloud infrastructure and services. | [AWS getting started](https://aws.amazon.com/getting-started/) |
| <a href="https://elevenlabs.io/"><img src="https://github.com/elevenlabs.png?size=96" alt="ElevenLabs logo" width="56" height="56"></a> | **[ElevenLabs](https://elevenlabs.io/)** — Partner | Voice and audio APIs for AI applications. | [Developer documentation](https://elevenlabs.io/docs/overview/intro) |
| <a href="https://anchorbrowser.io/"><img src="https://github.com/anchorbrowser.png?size=96" alt="Anchor Browser logo" width="56" height="56"></a> | **[Anchor Browser](https://anchorbrowser.io/)** — Partner | Browser infrastructure and web automation for agents. | [Documentation and getting started](https://docs.anchorbrowser.io/introduction) |
| <a href="https://surrealdb.com/"><img src="https://github.com/surrealdb.png?size=96" alt="SurrealDB logo" width="56" height="56"></a> | **[SurrealDB](https://surrealdb.com/)** — Partner | Database infrastructure for application data and agent memory. | [Getting started and documentation](https://surrealdb.com/docs) |

## Builder checklist

1. Review the participant brief and Devpost requirements.
2. Follow the relevant sponsor's getting-started link above.
3. Ask the organizers for event-specific credits and redemption instructions.
4. Build and demonstrate one complete agent workflow, including its safeguards.
5. Prepare slides and a live demo that fit the three-minute presentation.
6. Submit through Devpost before **3:30 PM Eastern**.

## For organizers and judges

The sponsor directory acknowledges the event partners; it does not claim that every platform has been integrated into this project. Implementation details, setup instructions, demo links, and evidence of sponsor usage will be documented as the build progresses.

The published judging criteria give equal weight to **impact potential**, **technical execution**, **creativity**, and **presentation** (25% each). Meaningful sponsor-tool usage is a bonus.

---

Event information is sourced from the [official Luma listing](https://luma.com/hacksprint-nyc) and [Devpost](https://daytona-hacksprint-nyc.devpost.com/). Sponsor names and logos belong to their respective owners.
