# MENNBridge — Cross-Agent Memory Controller

AI coding agents lose all context the moment you switch tools mid-project —
Codex doesn't know what Claude Code decided an hour ago, and Claude Code
doesn't know what Codex already tried and ruled out. MENNBridge is an MCP
server that sits between your agents and a shared memory store, giving every
agent working on a project the same structured, decaying, conflict-aware
memory of decisions, failures, blockers, and progress.

## The Problem

When you switch from Codex to Claude Code mid-project, the new agent is
blind. It sees the files on disk but has no idea what decisions were made,
what's already been tried and failed, what's currently blocking progress, or
where the last agent left off. It re-derives context from scratch, repeats
work, and sometimes repeats mistakes another agent already ruled out.
MENNBridge solves this by giving agents a shared, structured handoff brief
instead of a blank slate.

## How It Works

MENNBridge exposes two MCP tools:

- **`get_context()`** — call this once at the start of a session, before any
  other work. Returns a handoff brief: current state, the next step a
  previous agent left off at, prior decisions, failed attempts, active
  bottlenecks, and recent test results and progress.
- **`checkpoint(summary, status, files_changed)`** — call this when you
  finish a task, hit a blocker, or are about to hand off. A cheap
  keyword gate decides whether the summary contains anything worth keeping;
  if so, extraction into typed memories happens in the background (via Groq)
  and the call returns immediately.

MENNBridge is a **called service, not a background monitor** — it does no
polling and holds no state between calls. It wakes up only when an agent
calls `get_context()` or `checkpoint()`, does its work, and goes back to
being inert. All memory content lives in SharedMENN, a separate MCP server;
MENNBridge is the controller and typed schema in front of it, plus a
dashboard for inspecting what's stored.

Since MCP clients differ in what they support, the same context is also
exposed as three read-only **MCP resources** (`mennbridge://context`,
`mennbridge://memories`, `mennbridge://status`) for clients — like Codex —
that can read resources via `list_mcp_resources` / `read_mcp_resource` but
can't call tools on external MCP servers.

### Example handoff brief

```
CURRENT STATE: Implementing MCP resource endpoints so Codex can read
project context without tool calls.

NEXT STEP:
• Add tests for the three new resources and verify the /mcp/ discovery
  endpoint lists them.

DECISIONS MADE:
• Use fastmcp's @mcp.resource() decorator instead of a custom resource
  registry.
• Keep resource reads unauthenticated internally, same trust boundary as
  the two MCP tools.

WHAT WAS TRIED AND FAILED:
• Gating resources on manager_paused — dropped it, resources are reads,
  not "work" the way tool calls are.

ACTIVE BOTTLENECKS:
• None currently.

RECENT TEST RESULTS:
• 58 backend tests passing, 5 skipped (Postgres-backed tests need
  TEST_DATABASE_URL).

RECENT PROGRESS:
• Added mennbridge://context, mennbridge://memories, mennbridge://status
  resources.
```

## Memory Types

| Type | Description | Decay behavior |
|---|---|---|
| `decision` | A choice made and why (e.g. "chose FastAPI over Flask") | Never decays — always in the brief |
| `failed_attempt` | Something tried that didn't work, so it isn't retried | Never decays — always in the brief |
| `bottleneck` | An active blocker preventing progress | 30-day half-life |
| `progress` | A completed unit of work | 14-day half-life |
| `test_result` | Outcome of a test run | 7-day half-life |
| `current_state` | Singleton — where the project stands right now | 3-day half-life |
| `next_step` | Singleton — what the next agent should do first | 3-day half-life |

`decision` and `failed_attempt` are permanent and are always fetched in
full (up to a per-type cap) regardless of current relevance — a new agent
must see every decision and every failed attempt, not just the ones related
to whatever the project happens to be doing right now. `current_state` and
`next_step` are singletons: storing a new one supersedes the old one rather
than adding to a list. Everything else decays on a per-type half-life until
a developer manually reinforces it back to full importance from the
dashboard's Decay Tracker panel.

## Architecture

```
   Claude Code                Codex
  (MCP client)             (MCP client)
        │                        │
        │ get_context()          │ list_mcp_resources()
        │ checkpoint()           │ read_mcp_resource()
        │                        │
        └───────────┬────────────┘
                     ▼
        ┌────────────────────────┐
        │  MENNBridge MCP Server │
        │   (FastAPI + FastMCP)  │
        └────────────┬───────────┘
                     │  │
                     │  └──────────────┐
                     ▼                 ▼
        ┌────────────────────┐  ┌─────────────┐
        │     SharedMENN      │  │  Dashboard  │
        │ (ChromaDB + Postgres│  │  UI (React) │
        │  memory store)      │  │             │
        └─────────────────────┘  └─────────────┘
```

## Tech Stack

| Layer | Technology |
|---|---|
| MCP server | FastMCP on FastAPI — streamable-HTTP (`/mcp`) and SSE (`/sse`) transports |
| Memory store | SharedMENN (ChromaDB + Postgres metadata) — separate, existing MCP server |
| Memory extraction | Groq (Llama 3.1 8B Instant) — background extraction from `checkpoint()` summaries |
| Event log | PostgreSQL via `asyncpg` — dashboard event history and session bookkeeping only, not memory content |
| Dashboard backend | FastAPI REST API + WebSocket (`/dashboard`) |
| Dashboard frontend | React 18 + Vite |
| Deployment | Docker Compose (`postgres`, `backend`, `frontend`) |
| Tests | pytest + pytest-asyncio |

## Verified Cross-Agent Demo

This isn't just a design on paper — bidirectional cross-agent memory
sharing between an Anthropic agent and an OpenAI agent has been verified
live on the same project:

- Claude Code stored decisions, fixes, and test results via `checkpoint()`.
- Codex (OpenAI) read the full handoff brief through the
  `mennbridge://context` MCP resource — no tool call required.
- Codex then wrote 9 memories back to the same project.
- Both agents showed up on the dashboard's Agent Status panel at the same
  time, each with its own session and memory count.
- **Proven:** two heterogeneous AI agents, from two different vendors,
  reading and writing the same structured project memory.

## Quick Start

### Prerequisites

- Docker + Docker Compose
- A running [SharedMENN](#) instance — MENNBridge does not start or bundle
  SharedMENN itself, it only connects to it
- A free Groq API key from [console.groq.com](https://console.groq.com)

### Setup

```bash
git clone https://github.com/sharan1304/Memory_Bridge
cd Memory_Bridge
cp .env.example .env
```

Fill in `.env`:

- `GROQ_API_KEY` — your Groq key
- `SHAREDMENN_URL` — wherever your SharedMENN server is already running
- `DATABASE_URL` — leave as the Docker Compose default unless you're not
  using Docker
- `MENNBRIDGE_PROJECT` — the project identifier this deployment serves

Then start everything:

```bash
docker compose up --build -d
```

This starts three containers: `postgres` (schema applied automatically on
first boot), `backend` (FastAPI + MCP server on `PORT`, default 8001), and
`frontend` (the dashboard on port 3000).

### Connect Claude Code

Add MENNBridge as a project-level MCP server, e.g. in `.mcp.json`
(substitute your actual `PORT` from `.env`):

```json
{
  "mcpServers": {
    "mennbridge": {
      "type": "http",
      "url": "http://localhost:8001/mcp"
    }
  }
}
```

### Connect Codex

Add MENNBridge to your Codex MCP config (`~/.codex/config.toml`):

```toml
[mcp_servers.mennbridge]
url = "http://localhost:8001/mcp"
```

Codex will see `get_context` and `checkpoint` as tools where supported, and
can always fall back to reading `mennbridge://context`,
`mennbridge://memories`, and `mennbridge://status` as resources.

### Dashboard

Open **http://localhost:3000** for the developer-facing dashboard — a
project switcher plus six panels (see below).

## Dashboard Panels

| Panel | Shows |
|---|---|
| Live Feed | Real-time stream of `get_context`/`checkpoint` calls over a WebSocket, as agents make them |
| Memory Browser | All stored memories for the selected project, grouped by type, with inline edit/delete |
| Conflict Monitor | Pairs of active, same-type memories that are similar but not identical — a proxy for "these two facts might disagree" |
| Agent Status | Each agent's latest session and how many memories it has written, so you can see who did what |
| Decay Tracker | Non-permanent memories ranked by current (decayed) importance, with a manual reinforce action |
| Routing Rules | UI scaffold for future keyword-based project routing — not wired to any backend logic yet; project routing today is explicit via `MENNBRIDGE_PROJECT` |

## API Reference

MCP server (`/mcp`, streamable-HTTP; also served over SSE at `/sse`):

| Tool / Resource | Description |
|---|---|
| `get_context` (tool) | Returns the handoff brief for the deployment's configured project |
| `checkpoint` (tool) | Stores a session summary; triggers background memory extraction if signal is found |
| `mennbridge://context` (resource) | Same handoff brief as `get_context`, readable without a tool call |
| `mennbridge://memories` (resource) | All active memories for the project, as a JSON array |
| `mennbridge://status` (resource) | Just current state and next step, as short text |

Dashboard REST API (`/dashboard`, consumed by the frontend, not the agents):

| Endpoint | Description |
|---|---|
| `GET /dashboard/projects` | Distinct project IDs this deployment has logged events for |
| `GET /dashboard/memories` | All memories for a project |
| `GET /dashboard/memories/{id}` | A single memory |
| `PATCH /dashboard/memories/{id}` | Edit a memory's content |
| `DELETE /dashboard/memories/{id}` | Delete a memory (repairs any supersede chain it was the head of) |
| `POST /dashboard/memories` | Manually create a memory from the dashboard |
| `POST /dashboard/manager/pause` | Pause the manager — `get_context`/`checkpoint` refuse to do work |
| `POST /dashboard/manager/resume` | Resume the manager |
| `GET /dashboard/events` | Recent `get_context`/`checkpoint` call history for a project |
| `GET /dashboard/agents` | Latest session and memory count per agent |
| `GET /dashboard/conflicts` | Flagged pairs of similar, possibly-contradictory memories |
| `GET /dashboard/decay` | Non-permanent memories ranked by current decayed importance |
| `POST /dashboard/decay/{id}/reinforce` | Reset a memory's importance back to 1.0 |
| `WS /dashboard/ws` | Live event stream for the Live Feed panel |

Other:

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness check, returns the configured project ID |
| `GET /mcp` | Human-readable discovery for `curl` — lists registered tools and resources |

## Research Context

MENNBridge addresses three open problems in multi-agent memory systems:

1. **Temporal / decay-aware memory** — not everything an agent learns stays
   relevant forever; MENNBridge scores importance on a per-type half-life
   instead of treating all memories as equally durable.
2. **Cross-agent conflict governance** — when two agents (or two sessions of
   the same agent) reach different conclusions, that needs to surface to a
   human rather than silently overwrite or silently coexist.
3. **Structured handoff between heterogeneous AI agents** — agents from
   different vendors, with different tool-calling capabilities, need a
   common context format that works whether the client supports MCP tools,
   MCP resources, or both.

Related work: [MemGPT](https://arxiv.org/abs/2310.08560),
[A-MEM](https://arxiv.org/abs/2502.12110), and the
[Model Context Protocol specification](https://modelcontextprotocol.io).

## Test Results

- **58 backend tests passing** (5 skipped — Postgres-backed tests that need
  `TEST_DATABASE_URL`), run with `pytest` + `pytest-asyncio` against an
  in-memory fake SharedMENN server.
- **Live verified:** Claude Code and Codex cross-agent handoff — see
  [Verified Cross-Agent Demo](#verified-cross-agent-demo) above.

## Running backend tests

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
```

A handful of Postgres-backed tests (`tests/test_events_db.py`, part of
`tests/test_dashboard_api.py`) are skipped unless `TEST_DATABASE_URL` points
at a scratch Postgres database with `db/init.sql` applied:

```bash
docker run -d -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=mennbridge -p 55432:5432 postgres:15-alpine
docker exec -e PGPASSWORD=postgres <container> psql -U postgres -d mennbridge -f - < db/init.sql
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/mennbridge python -m pytest -q
```

## Fallback: run without Docker

If you'd rather not containerize the backend/frontend during development,
`run.sh` runs Postgres in Docker but the backend and frontend directly with
your local `python3`/`node`, reading the same root `.env`:

```bash
./run.sh
```

Ctrl+C stops everything (backend, frontend, and the Postgres container)
cleanly.
