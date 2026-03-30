# Bicameral MCP — Decision Ledger for Your Codebase

Every software team makes hundreds of verbal decisions per week — in meetings, PRDs, Slack threads, and huddles. None of those decisions are linked to the code that implements (or fails to implement) them.

**Bicameral MCP** is a local MCP server that ingests meeting transcripts and PRDs, builds a structured graph of decisions mapped to code symbols, and continuously tracks whether those decisions are reflected, drifting, or lost as the codebase evolves.

> **One-liner**: A provenance-aware decision layer for your codebase — paste a transcript, get a living map of what was decided and what was actually built.

---

## The Problem: 5 SDLC Friction Points

| Smell | What Happens | Fix |
|-------|-------------|-----------|
| **CONSTRAINT_LOST** | A rate limit or compliance rule surfaces mid-sprint instead of at design time | `bicameral.search` — pre-flight context before coding |
| **CONTEXT_SCATTERED** | The "why" behind a decision is split across Slack, Notion, and someone's memory | `bicameral.ingest` — normalizes intent from any source into a unified graph |
| **DECISION_UNDOCUMENTED** | A verbal "let's do X" never lands in a ticket or ADR | `bicameral.status` — tracks what was decided vs what was built |
| **REPEATED_EXPLANATION** | Same context tax paid twice — once to design, once to engineering | `bicameral.search` + `get_neighbors` — retrieves full decision provenance |
| **TRIBAL_KNOWLEDGE** | Only one person knows why the system works the way it does | `bicameral.drift` — surfaces institutional memory tied to code |

General-purpose AI can shred a PRD into user stories, but it goes deaf the moment code hits production. **Bicameral's wedge is post-commit drift detection** — knowing that a decision made three weeks ago is now inconsistent with what actually shipped.

---

## Quickstart

### One-command setup

```bash
uvx bicameral-mcp setup
```

This launches an interactive wizard that:
1. Detects your repo (from cwd or prompts you)
2. Installs the MCP config into Claude Code and/or Claude Desktop automatically

That's it. The server builds its code index on first tool call.

### Manual config

If you prefer to configure manually, add to your MCP config:

```json
{
  "mcpServers": {
    "bicameral": {
      "command": "uvx",
      "args": ["bicameral-mcp"],
      "env": {
        "REPO_PATH": "/path/to/your/repo"
      }
    }
  }
}
```

### Local development

```bash
cd pilot/mcp
pip install -e ".[test]"
bicameral-mcp setup           # interactive config
bicameral-mcp --smoke-test    # verify tools
bicameral-mcp                 # start MCP server (stdio)
```

No LLM provider credentials needed — all retrieval is deterministic.

---

## 9 MCP Tools

### Decision Ledger (5 tools)

| Tool | Purpose | Auto-triggers |
|------|---------|---------------|
| `bicameral.ingest` | Ingest a normalized source payload (transcript, PRD, Slack export) and advance the source cursor | — |
| `bicameral.status` | Surface implementation status of all tracked decisions (reflected / drifted / pending / ungrounded) | — |
| `bicameral.search` | Pre-flight: find past decisions relevant to a feature before writing code | `link_commit(HEAD)` |
| `bicameral.drift` | Code review: surface decisions that touch symbols in a file, flagging divergence | `link_commit(HEAD)` |
| `bicameral.link_commit` | Sync a commit into the ledger — updates content hashes, re-evaluates drift | — |

### Code Locator (4 tools)

| Tool | Purpose | Requires |
|------|---------|----------|
| `validate_symbols` | Fuzzy-match candidate symbol names against the codebase index (rapidfuzz + SQLite) | Indexed repo |
| `search_code` | BM25 text search + structural graph traversal, ranked via RRF fusion | Indexed repo |
| `get_neighbors` | 1-hop graph traversal around a symbol (callers, callees, imports, inheritance) | Indexed repo |
| `extract_symbols` | Tree-sitter symbol extraction from a source file | — |

---

## How the Tools Compose

### Pre-flight (before coding)
```
bicameral.search("add rate limiting") → surfaces prior constraints
validate_symbols(["RateLimiter"]) → confirms code entities exist
search_code("rate limit middleware") → locates relevant code
get_neighbors(symbol_id) → understands blast radius
```

### Code review (before merging)
```
bicameral.drift("payments/processor.py") → surfaces decisions touching this file
extract_symbols("payments/processor.py") → enumerates current symbols
bicameral.status(filter="drifted") → full drift report
```

### Ingestion (after a meeting)
```
bicameral.ingest(transcript_payload) → extracts intents, maps to code
bicameral.link_commit("HEAD") → syncs latest commit state
bicameral.status(since="2026-03-20") → shows what's reflected vs pending
```

---

## Architecture

```
Host Model (Claude Code / Cursor / Claude Desktop)
  │  MCP stdio transport
  ▼
server.py — 9 tools, tool dispatch
  ├── handlers/          ← 5 ledger tool handlers
  │   ├── ingest.py
  │   ├── decision_status.py
  │   ├── search_decisions.py
  │   ├── detect_drift.py
  │   └── link_commit.py
  ├── adapters/          ← adapter layer
  │   ├── ledger.py      → SurrealDBLedgerAdapter (singleton)
  │   └── code_locator.py → RealCodeLocatorAdapter (lazy init)
  ├── ledger/            ← SurrealDB v2 embedded
  │   ├── adapter.py, client.py, queries.py
  │   ├── schema.py      ← canonical table/index definitions
  │   └── status.py      ← content-hash drift derivation
  └── code_locator/      ← deterministic retrieval
      ├── tools/          (validate, search, neighbors)
      ├── indexing/       (tree-sitter, SQLite, graph builder)
      ├── retrieval/      (BM25, sqlite-vec)
      └── fusion/         (RRF)
```

**Storage**: SurrealDB v2 embedded (`surrealkv://` persistent or `memory://` for tests) + SQLite (symbol index, BM25, graph edges). No external server required.

**Zero nested LLM calls**. The host model orchestrates tool calls directly. All retrieval is deterministic: tree-sitter + BM25 + graph traversal.

---

## Status Derivation

Decision status is a pure function computed at query time — never stored:

| Condition | Status | Meaning |
|-----------|--------|---------|
| No `code_region` mapped | **ungrounded** | Intent captured but no matching code found |
| Symbol absent at git ref | **pending** | Code not yet written |
| `content_hash` differs | **drifted** | Code changed since decision was recorded |
| `content_hash` matches | **reflected** | Code matches intent |

This makes Bicameral immune to rebase, squash, and cherry-pick — status is always re-derivable from `(intent, git_ref)`.

---

## Environment Variables

| Var | Default | Purpose |
|-----|---------|---------|
| `REPO_PATH` | `.` | Path to the repo being analyzed |
| `SURREAL_URL` | `surrealkv://~/.bicameral/ledger.db` | SurrealDB URL. Use `memory://` for tests. |
| `CODE_LOCATOR_SQLITE_DB` | `$REPO_PATH/.bicameral/code-graph.db` | Override code index location |

---

## Tests & CI

Tests run via GitHub Actions on PRs to `main` (`pilot/mcp/**` paths). All phases use real adapters with `SURREAL_URL=memory://`.

```bash
cd pilot/mcp && source .venv/bin/activate
pytest tests/ -v   # run everything locally
```

| Phase | Tests | What |
|-------|-------|------|
| **Phase 1** | `test_phase1_code_locator.py` | Code locator tools against real indexed repo |
| **Phase 2** | `test_phase2_ledger.py` | SurrealDB ledger adapter with `memory://` |
| **Phase 3** | `test_phase3_integration.py` | Full E2E structured around 5 SDLC failure modes |

Phase 3 tests produce JSON artifacts (`test-results/e2e/`) with full tool responses and SurrealDB graph dumps for qualitative review. These are uploaded as CI artifacts and embedded in the HTML test report.

---

## Visual Documentation

See [`visual-plan/plans/`](visual-plan/plans/) for rendered architecture docs:

- **[bicameral-mcp-system.html](visual-plan/plans/bicameral-mcp-system.html)** — consolidated system architecture, swimlane diagrams, graph schema
- **[code-locator-optionA-plus.html](visual-plan/plans/code-locator-optionA-plus.html)** — code locator deep-dive (indexing, RRF fusion, benchmarks)
- **[version-control-management.html](visual-plan/plans/version-control-management.html)** — git integration design
- **[bicameral-business-model.html](visual-plan/plans/bicameral-business-model.html)** — PLG go-to-market strategy
