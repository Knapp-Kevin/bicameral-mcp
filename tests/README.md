# MCP Regression Tests

Tests are gated by phase. Each phase gate is an env var. Run only what's implemented.

## Running tests

```bash
source .venv/bin/activate  # or: python -m pytest directly via .venv/bin/pytest

# Packaging / startup smoke
bicameral-mcp --smoke-test

# Phase 0 — always green (mocks only, no dependencies)
pytest tests/test_phase0_mocks.py -v

# Phase 1 — requires real code locator (Silong's work)
USE_REAL_CODE_LOCATOR=1 REPO_PATH=/path/to/repo pytest tests/test_phase1_code_locator.py -v

# Phase 2 — embedded SurrealDB path for tests
USE_REAL_LEDGER=1 SURREAL_URL=memory:// pytest tests/test_phase2_ledger.py -v

# Phase 3 — full integration (requires both)
USE_REAL_CODE_LOCATOR=1 USE_REAL_LEDGER=1 SURREAL_URL=memory:// REPO_PATH=/path/to/repo pytest tests/test_phase3_integration.py -v

# All phases at once (use for CI once all phases are complete)
pytest tests/ -v
```

## Phase status

| File | Passes without dependencies | Unblocked by |
|------|-----------------------------|--------------|
| `test_phase0_mocks.py` | YES | — |
| `test_phase1_code_locator.py` | NO | real code locator index + provider credentials |
| `test_phase2_ledger.py` | NO | `USE_REAL_LEDGER=1` + `memory://` or SurrealDB URL |
| `test_phase3_integration.py` | NO | Both Phase 1 + Phase 2 complete |

## What each phase validates

**Phase 0**: Contract shapes. Do all 4 tools return valid Pydantic types? Are all required fields present?

**Phase 1**: Code locator correctness. Do located file paths exist on disk? Are symbols real names from the repo? Is confidence in the expected range?

**Phase 2**: Ledger correctness. Is ingestion idempotent? Does BM25 search return relevant results? Does reverse traversal (file → decisions) work? Does `link_commit` update statuses correctly?

**Phase 3**: End-to-end pipeline. Does ingesting a sample transcript + running code locator + storing in graph + querying back produce a coherent result?

## Packaging smoke

The installable package surface is now the first startup check:

1. `pip install -r requirements.txt`
2. `bicameral-mcp --smoke-test`
3. Verify the command prints the 5 registered tool names
