---
name: bicameral-ingest
description: Ingest a meeting transcript or PRD into the decision ledger. Use when the user pastes a transcript, shares meeting notes, or wants to track decisions from a document.
---

# Bicameral Ingest

Ingest a source document into the decision ledger so its decisions are tracked against the codebase.

## When to use

- User pastes or references a meeting transcript
- User shares a PRD, design doc, or Slack thread
- User says "track these decisions" or "ingest this"

## Steps

1. Parse the user's input to identify the source content (transcript text, file path, or pasted content)
2. Call the `bicameral.ingest` MCP tool with a payload containing:
   - `payload.mappings[].span.text` — the raw text of each decision
   - `payload.mappings[].intent` — the extracted intent (what was decided)
   - `payload.mappings[].span.source_type` — "transcript", "prd", or "slack"
   - `payload.mappings[].span.speaker` — who said it (if known)
   - `payload.mappings[].span.source_ref` — meeting name/date for provenance
3. Report the results: how many intents were created, how many mapped to code, and which are ungrounded (no code match yet)

## Arguments

$ARGUMENTS — the transcript text, file path, or description of what to ingest

## Example

User: "Ingest our sprint planning notes from today"
→ Call `bicameral.ingest` with extracted decisions
→ Report: "3 decisions ingested, 2 mapped to code, 1 ungrounded (rate limiting — no implementation found yet)"
