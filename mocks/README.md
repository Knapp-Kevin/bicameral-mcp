# Mock Registry

All mocks have been replaced with real implementations.

## Replaced Mocks

| Mock | Replaced by | Date | Phase |
|------|------------|------|-------|
| `mocks/code_locator.py` | `RealCodeLocatorAdapter` in `adapters/code_locator.py` | 2026-03-28 | Phase 1 |
| `mocks/decision_ledger.py` | `ledger/adapter.py::SurrealDBLedgerAdapter` | 2026-03-28 | Phase 2 |
