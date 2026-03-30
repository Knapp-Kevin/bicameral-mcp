"""SurrealDB schema for the decision ledger.

Targets SurrealDB 2.x embedded via Python SDK (surrealdb>=1.0.0).
Uses SEARCH ANALYZER syntax (v2 compatible, not FULLTEXT ANALYZER which is v3+).

To initialise: await init_schema(client)
"""

from __future__ import annotations

from .client import LedgerClient

# Analyzers
_ANALYZERS = [
    # Business language: transcripts, PRDs, intents
    "DEFINE ANALYZER biz_analyzer TOKENIZERS blank, class, punct FILTERS lowercase, ascii, snowball(english)",
    # Code symbols: CamelCase + snake_case aware
    "DEFINE ANALYZER code_analyzer TOKENIZERS class, camel FILTERS lowercase, ascii",
]

# Core tables
_TABLES = [
    # intent — a decision/requirement extracted from a meeting or PRD
    "DEFINE TABLE intent SCHEMAFULL CHANGEFEED 30d INCLUDE ORIGINAL",
    "DEFINE FIELD description    ON intent TYPE string",
    "DEFINE FIELD rationale      ON intent TYPE string DEFAULT ''",
    "DEFINE FIELD feature_hint   ON intent TYPE string DEFAULT ''",
    "DEFINE FIELD source_type    ON intent TYPE string",
    "DEFINE FIELD source_ref     ON intent TYPE string DEFAULT ''",
    "DEFINE FIELD meeting_date   ON intent TYPE string DEFAULT ''",
    "DEFINE FIELD speakers       ON intent TYPE array DEFAULT []",
    "DEFINE FIELD status         ON intent TYPE string DEFAULT 'ungrounded' "
    "ASSERT $value IN ['reflected', 'drifted', 'pending', 'ungrounded']",
    "DEFINE FIELD created_at     ON intent TYPE datetime DEFAULT time::now()",
    # BM25 full-text index on description (SEARCH ANALYZER = v2 syntax)
    "DEFINE INDEX idx_intent_fts ON intent FIELDS description SEARCH ANALYZER biz_analyzer BM25(1.2, 0.75) HIGHLIGHTS",

    # symbol — a named code entity (function, class, file)
    "DEFINE TABLE symbol SCHEMAFULL",
    "DEFINE FIELD name           ON symbol TYPE string",
    "DEFINE FIELD file_path      ON symbol TYPE string",
    "DEFINE FIELD sym_type       ON symbol TYPE string",
    "DEFINE FIELD last_seen      ON symbol TYPE datetime DEFAULT time::now()",
    "DEFINE FIELD hit_count      ON symbol TYPE int DEFAULT 0",
    "DEFINE INDEX idx_sym_name   ON symbol FIELDS name SEARCH ANALYZER code_analyzer BM25(1.2, 0.75)",
    "DEFINE INDEX idx_sym_file   ON symbol FIELDS file_path",

    # code_region — a specific span within a file (tied to a symbol)
    "DEFINE TABLE code_region SCHEMAFULL CHANGEFEED 30d INCLUDE ORIGINAL",
    "DEFINE FIELD file_path      ON code_region TYPE string",
    "DEFINE FIELD symbol_name    ON code_region TYPE string",
    "DEFINE FIELD start_line     ON code_region TYPE int",
    "DEFINE FIELD end_line       ON code_region TYPE int",
    "DEFINE FIELD purpose        ON code_region TYPE string DEFAULT ''",
    "DEFINE FIELD repo           ON code_region TYPE string DEFAULT ''",
    "DEFINE FIELD pinned_commit  ON code_region TYPE string DEFAULT ''",
    "DEFINE FIELD content_hash   ON code_region TYPE string DEFAULT ''",
    "DEFINE INDEX idx_region_sym  ON code_region FIELDS symbol_name",
    "DEFINE INDEX idx_region_file ON code_region FIELDS repo, file_path",

    # vocab_cache — fast repeated query→symbols lookups
    "DEFINE TABLE vocab_cache SCHEMAFULL",
    "DEFINE FIELD query_text     ON vocab_cache TYPE string",
    "DEFINE FIELD repo           ON vocab_cache TYPE string",
    "DEFINE FIELD symbols        ON vocab_cache TYPE array DEFAULT []",
    "DEFINE FIELD hit_count      ON vocab_cache TYPE int DEFAULT 0",
    "DEFINE FIELD last_hit       ON vocab_cache TYPE datetime DEFAULT time::now()",
    "DEFINE INDEX idx_vocab_query ON vocab_cache FIELDS query_text SEARCH ANALYZER biz_analyzer BM25(1.2, 0.75)",
    "DEFINE INDEX idx_vocab_repo  ON vocab_cache FIELDS repo",

    # ledger_sync — idempotency cursor (last synced commit per repo)
    "DEFINE TABLE ledger_sync SCHEMAFULL",
    "DEFINE FIELD repo               ON ledger_sync TYPE string",
    "DEFINE FIELD last_synced_commit ON ledger_sync TYPE string",
    "DEFINE FIELD synced_at          ON ledger_sync TYPE datetime DEFAULT time::now()",
    "DEFINE INDEX idx_sync_repo ON ledger_sync FIELDS repo UNIQUE",

    # source_cursor — upstream ingestion checkpoint per source stream
    "DEFINE TABLE source_cursor SCHEMAFULL",
    "DEFINE FIELD repo            ON source_cursor TYPE string",
    "DEFINE FIELD source_type     ON source_cursor TYPE string",
    "DEFINE FIELD source_scope    ON source_cursor TYPE string DEFAULT 'default'",
    "DEFINE FIELD cursor          ON source_cursor TYPE string DEFAULT ''",
    "DEFINE FIELD last_source_ref ON source_cursor TYPE string DEFAULT ''",
    "DEFINE FIELD synced_at       ON source_cursor TYPE datetime DEFAULT time::now()",
    "DEFINE FIELD status          ON source_cursor TYPE string DEFAULT 'ok'",
    "DEFINE FIELD error           ON source_cursor TYPE string DEFAULT ''",
    "DEFINE INDEX idx_source_cursor ON source_cursor FIELDS repo, source_type, source_scope UNIQUE",
]

# Edge tables
_EDGES = [
    # intent → symbol (vocabulary bridge)
    "DEFINE TABLE maps_to SCHEMAFULL TYPE RELATION IN intent OUT symbol",
    "DEFINE FIELD confidence ON maps_to TYPE float ASSERT $value >= 0 AND $value <= 1",
    "DEFINE FIELD provenance ON maps_to TYPE object DEFAULT {}",
    "DEFINE FIELD created_at ON maps_to TYPE datetime DEFAULT time::now()",

    # symbol → code_region (code locator result)
    "DEFINE TABLE implements SCHEMAFULL TYPE RELATION IN symbol OUT code_region",
    "DEFINE FIELD confidence ON implements TYPE float ASSERT $value >= 0 AND $value <= 1",
    "DEFINE FIELD verified   ON implements TYPE bool DEFAULT false",
    "DEFINE FIELD created_at ON implements TYPE datetime DEFAULT time::now()",

    # code_region → code_region (structural dependency)
    "DEFINE TABLE depends_on SCHEMAFULL TYPE RELATION IN code_region OUT code_region",
    "DEFINE FIELD edge_type  ON depends_on TYPE string",
    "DEFINE FIELD created_at ON depends_on TYPE datetime DEFAULT time::now()",
]


async def init_schema(client: LedgerClient) -> None:
    """Create all tables, indexes, and analyzers. Idempotent (DEFINE is safe to re-run)."""
    all_statements = _ANALYZERS + _TABLES + _EDGES
    await client.execute_many(all_statements)
