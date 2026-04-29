# Development Cycle

**Audience**: contributors, release managers (Jin), and anyone shipping a change
to `BicameralAI/bicameral-mcp`. This document is the contract — if you are about
to open a branch, write a PR, cut a release, or close an issue, follow what is
written here. Deviations require a META_LEDGER entry explaining why.

**Repo topology** (as of v0.13.0, post-Phase-4):

```text
contributor fork (e.g. Knapp-Kevin/bicameral-mcp)
         │  feature branches live here
         ▼
BicameralAI/bicameral-mcp
   ├── dev      ← integration branch; CI green, code complete, NOT shipped
   └── main     ← shipped; tagged; users pull from here
```

Two branches, one direction of flow: **feature → dev → main**. Nothing else
merges to `main` except `dev` (and the rare hotfix — see §10).

---

## 1. Lifecycle map

```
┌──────────┐   ┌────────┐   ┌──────────┐   ┌─────┐   ┌─────────────┐   ┌──────┐   ┌────────┐
│  Issue   │──▶│ Branch │──▶│ Feature  │──▶│ dev │──▶│  Release PR │──▶│ main │──▶│  Tag   │
│ (#nnn)   │   │ named  │   │   PR     │   │     │   │  (dev→main) │   │      │   │ vX.Y.Z │
│          │   │ /<n>-x │   │ → dev    │   │     │   │             │   │      │   │        │
└──────────┘   └────────┘   └──────────┘   └─────┘   └─────────────┘   └──────┘   └────────┘
     │              │            │           │              │             │           │
     │              │       Closes #nnn      │              │             │      GitHub
     │              │       on squash        │       Bumps version,       │      Release
     │              │            │           │       CHANGELOG flip,      │      published
     │              │            ▼           │       milestone close      │           │
     │              │      CI must pass      │              │             │           ▼
     │              │      QOR seal in       │              ▼             │    Help/training
     │              │      META_LEDGER       │      Squash-merge          │    docs published
     │              │                        │      OR merge commit       │
     ▼              ▼                        ▼                            ▼
 Milestone:    Branch name:                Issue auto-closed,    User-facing release;
 vX.Y.Z        <issue#>-<short-slug>       milestone open        upstream consumers
                                           ("pending release")    pull from main
```

**One rule of thumb**: any work that touches user-visible behavior must traverse
every box in that diagram. No back-doors to `main`.

---

## 2. Issues

### 2.1 Creating

- **Title**: imperative, scoped. `feat(codegenome): semantic drift evaluation in resolve_compliance`,
  not "add drift evaluation".
- **Required labels** (apply at least one of each axis):
  - **Type**: `feat`, `fix`, `docs`, `chore`, `test`, `refactor`, `perf`, `security`.
  - **Surface**: `tool`, `skill`, `ledger`, `code-locator`, `codegenome`, `infra`, `docs-only`.
  - **Risk**: `risk:L1` (cosmetic), `risk:L2` (logic), `risk:L3` (security/auth/persistence).
- **Milestone**: attach to the next-up release (`v0.14.0`). If you don't know
  which release it lands in, attach to `vNext-triage` and let Jin re-assign.
- **Body template** (see `.github/ISSUE_TEMPLATE/`):
  - **Why**: one paragraph. The product decision this serves.
  - **What**: the smallest change that satisfies "Why".
  - **Out of scope**: explicit exclusions. Stops scope creep at PR-review time.
  - **Acceptance**: bullet list of testable conditions. CI green is implied; add
    behavioural checks ("`link_commit` returns `auto_resolved_count` ≥ 0").

### 2.2 Closure

`Closes #X` in a PR body **fires when that PR's HEAD merges into its BASE**, not
when work reaches `main`. PRs target `dev`, so issues close at the dev-merge.

Why we keep auto-close on dev: closure tracks "the work is in code", milestones
track "the work is shipped". Two signals, two artifacts.

### 2.3 Reopening

If a hotfix or follow-up reveals the dev work was wrong, **reopen the original
issue** rather than filing a new one — keeps history threaded. Add a comment
linking the regression's hotfix PR.

---

## 3. Branches

### 3.1 Naming

`<issue#>-<short-slug>` from a fork.

```
Knapp-Kevin/codegenome-phase-4-qor    ← acceptable (descriptive slug)
Knapp-Kevin/61-drift-classifier       ← preferred (issue-numbered)
Knapp-Kevin/main                      ← never push feature work to fork's main
Knapp-Kevin/dev                       ← does not exist (BicameralAI/dev is canonical)
```

A fork's `dev` branch is **not** maintained. The integration branch is exactly
one place: `BicameralAI/dev`.

### 3.2 Branching off

Always branch off `BicameralAI/dev`, never `main`. `dev` is what other in-flight
work has integrated against; `main` is a moving snapshot of the last release.

```bash
git fetch BicameralAI dev
git checkout -b 61-drift-classifier BicameralAI/dev
```

### 3.3 Stacking

Stacked PRs (PR B depends on PR A's branch) are tolerated for short windows
(< 48 h). Rebase the stack onto `dev` the moment the bottom PR merges. Long
stacks compound merge-conflict risk and review fatigue.

---

## 4. Pull Requests

### 4.1 Targeting

**All feature/fix PRs target `dev`.** The release PR (and only the release PR)
targets `main`. CI workflows enforce both: `pull_request: branches: [main, dev]`.

### 4.2 Title

`<type>(<surface>): <imperative summary>` — the same shape as the issue title.
The squash commit message inherits this; loose PR titles produce ugly history.

### 4.3 Body — required sections

```markdown
## Summary
1–3 bullets, user-facing outcome.

## Linked issues
Closes #61
Refs #60 (depends on continuity matcher landed there)

## Plan / Audit / Seal
- Plan: docs/Planning/plan-codegenome-phase-4.md (v3, content hash sha256:911171cf…)
- Audit: META_LEDGER Entry #13, chain hash 21ac210f… — verdict PASS
- Seal:  META_LEDGER Entry #14, chain hash 0ebcf69b…

## Test plan
- [ ] `pytest tests/test_codegenome_drift_classifier.py -q` (32/32)
- [ ] `pytest tests/test_m3_benchmark.py -q` (5/5)
- [ ] regression: `pytest -q` (189/189)
```

The Plan/Audit/Seal section is **mandatory for any PR > 100 LOC or risk:L2+**.
Smaller PRs may use `Plan: trivial; risk:L1`.

### 4.4 Reviewers

- Code-owner from `CODEOWNERS` is auto-requested.
- **Risk:L3 PRs**: require a second reviewer + a security-pass note in the
  description.
- **Risk:L2 PRs**: one reviewer.
- **Risk:L1 PRs** (typo, comment fixes, dep bumps from Dependabot with green
  CI): owner self-merge after CI is green.

### 4.5 CI gates

Every PR to `dev` must show green on:

- `test-mcp-regression` — pytest with `SURREAL_URL=memory://`.
- `lint` — ruff/black/mypy as configured.
- `build` — package builds, imports resolve.

Red CI blocks merge. Don't ask reviewers to look at red PRs.

### 4.6 Review feedback discipline

CodeRabbit, Devin, and human reviewers all leave comments. The author's job:

- **Address** every actionable comment with a commit or a reply justifying
  decline.
- **Resolve** the conversation thread only after addressing.
- **Never** push `--force` on a PR with active review threads — comments lose
  their line anchors. Use `--force-with-lease` only after a `git fetch`, and
  call it out in a PR comment so reviewers re-fetch.

---

## 5. Merging to `dev`

### 5.1 Strategy

**Squash-merge.** One commit per PR on `dev`. The squash subject = PR title; the
body = PR body's `## Summary` + `Closes #X`.

Why squash, not merge-commit: `dev` history is read by humans deciding
"what's pending release". One line per shipped change keeps that view legible.

### 5.2 Pre-merge checklist (for the merger)

- [ ] CI green
- [ ] All review threads resolved
- [ ] Milestone attached on the PR (== same milestone as the issue)
- [ ] Plan / Audit / Seal references exist for non-trivial PRs
- [ ] CHANGELOG `## Unreleased` updated (or PR explicitly states "no user-visible change")

### 5.3 Post-merge

- Issue auto-closes (via `Closes #X`).
- Milestone progress bar advances.
- Branch may be deleted (GitHub default).
- If the work shipped a new tool / new tool field / changed default, the matching
  `pilot/mcp/skills/<tool>/SKILL.md` **must** be in the same squash commit
  (project rule from `CLAUDE.md`). Reviewers reject silently-mismatched skill
  contracts.

---

## 6. Release cycle

### 6.1 Cadence

- **Minor releases** (`v0.X.0`): roughly every 2–3 weeks, when the milestone is
  full and `dev` is stable.
- **Patch releases** (`v0.X.Y`): as needed for bug fixes that can't wait.
- **Major release** (`v1.0.0`): scheduled; not driven by milestone fill.

Jin owns the call on "is `dev` ready to ship". Heuristic: milestone closed-issue
count covers the headline features, and CI on `dev` HEAD has been green for ≥ 24 h.

### 6.2 Version selection

Semver applies:

- **PATCH** — bug fix only, no public-API change, no schema migration.
- **MINOR** — new tool / new tool field / new schema migration that is **additive**
  with a registered `_migrate_vN_to_vN+1` and bumped `SCHEMA_COMPATIBILITY` map.
- **MAJOR** — breaking change to a tool's request/response shape, or a destructive
  schema migration, or a CLI flag rename.

If the change is borderline, round **up**. Schema-migrating PRs are never PATCH.

### 6.3 The release PR (`dev` → `main`)

Jin opens this PR. It targets `main`, base = `main`, head = `dev`.

**Title**: `release: v0.13.0`

**Body**:

```markdown
## Release v0.13.0

### Headline
One sentence the README and Twitter post can both quote.

### Included issues
Closes milestone v0.13.0
- #61 — CodeGenome Phase 4 (semantic drift evaluation)
- #75 — <…>
- …

### Schema
- Migrates ledger v13 → v14 (additive: CHANGEFEED on compliance_check,
  semantic_status, evidence_refs)

### Breaking changes
None. (or: list each.)

### Documentation
- CHANGELOG.md — v0.13.0 section
- skills/bicameral-sync/SKILL.md — Phase 3+4 callout updated
- README.md — bumped feature list (if applicable)
- New: docs/DEV_CYCLE.md
```

### 6.4 Pre-release checklist

Jin runs through this before merging the release PR:

- [ ] **CHANGELOG flip** — move `## Unreleased` content under `## [v0.13.0] - 2026-04-29`.
      Add a fresh empty `## Unreleased` block at the top.
- [ ] **Version bump** — update `pyproject.toml` / `__init__.py` / wherever the
      canonical version lives.
- [ ] **`SCHEMA_COMPATIBILITY` map** — confirm the new schema version maps to the
      new release version (e.g. `14: "0.13.0"`).
- [ ] **Skill files** — every changed skill is committed in `pilot/mcp/skills/`,
      not just in `.claude/skills/`.
- [ ] **Help / training docs** (see §8) — published for any feature on the
      "user-touching" list.
- [ ] **Demo readiness** — at least one demo script (§11) covers each headline
      feature.
- [ ] **CI on `dev` HEAD** — green for ≥ 24 h.
- [ ] **Milestone** — every issue under it is closed.

### 6.5 Merging the release PR

**Strategy**: **merge-commit**, not squash. `main` is meant to preserve the
release boundary in history; a merge commit ("`Merge dev into main for
v0.13.0`") gives `git log main` a clean release-by-release walk.

```bash
git checkout main
git pull
git merge --no-ff dev -m "release: v0.13.0"
git push
```

GitHub's UI "Create a merge commit" button does the same.

### 6.6 Tagging

Immediately after the merge:

```bash
git tag -a v0.13.0 -m "Release v0.13.0 — CodeGenome Phase 4 (semantic drift)"
git push --tags
```

Tag format: `vMAJOR.MINOR.PATCH`. Annotated, never lightweight. The annotation
body is the headline sentence from the release PR.

### 6.7 GitHub Release

Create a Release object on GitHub from the tag (`gh release create v0.13.0` or
the UI):

**Title**: `v0.13.0 — CodeGenome Phase 4 (semantic drift)`

**Body**: copy/paste the CHANGELOG section for this version, then append:

```markdown
---

## Documentation
- [Migration notes](https://…/docs/migrations/v0.13.md) — schema v13 → v14
- [User guide for semantic drift evaluation](https://…/docs/guides/semantic-drift.md)
- [Demo: cosmetic-vs-semantic auto-resolve](https://…/docs/demos/04-drift-classifier.md)

## Verification
Merkle seal: 0ebcf69b…
META_LEDGER entries: #11 (VETO), #12 (PASS), #13 (PASS post-rebase), #14 (seal)
```

**Attachments**: none for now (we ship via PyPI/source). When we ship binaries,
attach platform builds here.

### 6.8 Post-release

- Close the milestone.
- Open the next milestone (`v0.14.0`).
- Announce: README badge bump, project README "Latest" line, optional Slack /
  Discord drop. Use the headline sentence verbatim.

---

## 7. CHANGELOG.md conventions

We follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely.

**Top of file at all times**:

```markdown
## [Unreleased]

### Added
- (work in flight that's already merged to dev)

### Changed
### Fixed
### Schema
### Security
```

When Jin cuts a release, he replaces `[Unreleased]` with the version + date,
then prepends a fresh empty `[Unreleased]` block.

**Section ordering** (preserve even when empty — drop a section only at release
flip): `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Schema`,
`Security`.

**One bullet per logical change**, not per file. User-facing language. Internal
governance details (chain hashes, verdicts) stay out of CHANGELOG; they live in
META_LEDGER.

---

## 8. Documentation requirements per release

Some features ship with code only. Some ship with code **plus** mandatory docs.
Use this matrix:

| Feature class | User-touching? | Docs required |
|---|---|---|
| New MCP tool | yes | `pilot/mcp/skills/<tool>/SKILL.md` + entry in `README.md#tools` |
| New tool field / new status value | yes | Update every skill that renders the field |
| New schema migration | indirect | `docs/migrations/vN.md` — what changes, automatic or manual |
| New caller-facing helper (e.g. `ensure_ledger_synced`) | yes | `docs/guides/<feature>.md` user guide |
| New deterministic primitive (e.g. continuity matcher) | yes | demo script in `docs/demos/` |
| Bug fix without behavior change | no | CHANGELOG entry only |
| Internal refactor | no | CHANGELOG entry only ("Changed: …") |
| Performance improvement | no, unless > 2× | CHANGELOG entry; `> 2×` adds a `docs/perf/` note |
| Security fix | yes | CHANGELOG `### Security` entry + `SECURITY.md` advisory if disclosed |

**Help docs go in**: `docs/guides/<feature>.md`. Structure:

```markdown
# <Feature> — User Guide

## What it does
One paragraph.

## When you'd use it
Bulleted scenarios.

## Quickstart
Smallest end-to-end example.

## Reference
Tool name, request shape, response shape, error modes.

## See also
Links to related guides + demo script.
```

**Training docs** (longer-form, multi-step walkthroughs intended to teach a
concept, not just document a tool) go in `docs/training/<topic>.md`. These are
optional unless the feature introduces a concept the user must internalize
(example: "what does `pending` vs `reflected` mean?" — that's training, not
reference).

---

## 9. Skill file rule (project-specific, mandatory)

From `CLAUDE.md`:

> Any change to an MCP tool's behavior — new fields in a response, new status
> values, changed defaults, new tool calls, deprecated params — **must ship
> with a matching update to the relevant `pilot/mcp/skills/*/SKILL.md`** in the
> same commit.

This is enforced at review time. `pilot/mcp/skills/` is canonical;
`.claude/skills/bicameral-*/SKILL.md` copies are stale and slated for deletion.

---

## 10. Hotfix path (main → main → dev)

When `main` has a bug that can't wait for the next release:

```
                                    ┌──── tag v0.13.1 ────┐
main ─────●─────────────────────────●─────────────────────●─────▶
           \                       /                       \
            └── hotfix/0.13.1 ────┘                         │
                                                            │ merge or
                                                            │ cherry-pick
                                                            ▼
dev  ─────────────────────────────────────────────────────●─────▶
```

1. Branch from `main` (not `dev`): `hotfix/0.13.1-<slug>`.
2. Smallest possible diff. No tangential cleanup.
3. PR targets `main`. Reviewer approves; CI green.
4. Merge to `main`, tag `v0.13.1`, GitHub Release.
5. **Immediately** sync to `dev`: either merge `main` into `dev` or cherry-pick
   the hotfix commit. Resolve conflicts. Push. Don't let `dev` and `main`
   diverge in opposite directions for more than an hour.

Hotfixes never carry feature work — feature work goes through the normal
feature → dev → release cycle.

---

## 11. Roles

| Role | Owner | Responsibilities |
|---|---|---|
| **Contributor** | anyone | Open issues, branch off `dev`, open PRs to `dev`, address review feedback, keep skill files in sync. |
| **Reviewer** | code-owners | Block on red CI, Razor violations, missing skill updates, missing Plan/Audit/Seal references on non-trivial PRs. |
| **Release manager** | Jin | Decide release cadence, open release PR, run pre-release checklist, merge to `main`, tag, publish GitHub Release, manage milestones. |
| **Doc steward** | rotating | Verify the §8 matrix is satisfied before each release. |
| **Governance steward** | QOR-chain owner | Verify META_LEDGER chain integrity at each release seal. |

Single-maintainer fallback: if Jin is offline, the release waits. We do not
unilaterally promote `dev` → `main`.

---

## 12. Demo scripts

Every shipped feature should have at least one runnable demo that takes a
viewer from "I don't know what this does" to "I see the value" in under 5
minutes. Demos live in `docs/demos/<NN>-<slug>.md` and follow the same template:

```markdown
# Demo NN: <Title>

**Audience**: <e.g. "first-time evaluator">
**Time**: <≤ 5 min>
**Prereqs**: <repo cloned, deps installed, MCP server running>

## What you'll see
1-paragraph spoiler.

## Setup
Copy-pasteable shell block.

## Walkthrough
Numbered steps, each with the exact tool call / command and the expected
output (truncated where it makes sense).

## What just happened
Plain-English read of the result. Tie it back to the user-value claim.

## Next
Pointer to the user guide and related demos.
```

Below: four demo scripts that cover the project's headline functionality. Each
one should be authored as a standalone file and kept in sync with the matching
skill / tool.

### Demo 01 — First decision bind, search, drift detect

**Path**: `docs/demos/01-first-bind.md`
**Audience**: "I just installed bicameral-mcp; what's the loop?"

**Storyline**:

1. `bicameral.bind` a decision: *"all monetary calculations use `Decimal`,
   never `float`"*. Show that the tool returns a region-id and a content hash.
2. `bicameral.search_decisions` for the keyword `"monetary"`. Show the just-bound
   decision returns at the top.
3. Edit the bound region: change `Decimal` to `float` in the linked file.
4. `bicameral.detect_drift`. Show that the region surfaces with status
   `drifted`.
5. Restore the file. Re-run. Status flips back to `reflected`.

**Value claim**: "Your decisions are now first-class artifacts — searchable,
hash-anchored, and drift-detected without you running anything by hand."

### Demo 02 — Commit-sync loop (post-commit hook → resolve_compliance)

**Path**: `docs/demos/02-commit-sync.md`
**Audience**: "How does this play with my actual git workflow?"

**Storyline**:

1. Show the post-commit hook installed (`.git/hooks/post-commit`) calling
   `bicameral-mcp link_commit HEAD`.
2. Edit a bound region. `git commit`.
3. Show the hook output: `bicameral: new commit detected`.
4. Show `_pending_compliance_checks` injected into the next tool response.
5. Walk through the `bicameral-sync` skill: read region → reason → batched
   `resolve_compliance(verdicts=[...])`.
6. Show the final ledger state: N reflected, N drifted, 0 pending.

**Value claim**: "Compliance is computed automatically on every commit, not
quarterly by a human auditor."

### Demo 03 — Continuity matcher: function rename auto-redirect (Phase 3)

**Path**: `docs/demos/03-continuity-rename.md`
**Audience**: "What happens when I refactor?"

**Storyline**:

1. Bind a decision to a function `calculate_tax_v1`.
2. Rename the function to `compute_tax`. Move it to a different file. Commit.
3. Naïvely: the binding would orphan and the decision would go `ungrounded`.
4. With `BICAMERAL_CODEGENOME_ENHANCE_DRIFT=1`: `link_commit` runs the
   continuity matcher pre-pass.
5. Show the response's `continuity_resolutions` list:
   `semantic_status: identity_renamed`, the binding redirected, no manual
   action needed.

**Value claim**: "Refactoring no longer breaks your decision graph. The matcher
recognises moved or renamed code and updates bindings automatically."

### Demo 04 — Cosmetic-vs-semantic drift classifier (Phase 4)

**Path**: `docs/demos/04-drift-classifier.md`
**Audience**: "Why does this not flag every whitespace change as drift?"

**Storyline**:

1. Bind a decision to a function. Capture the baseline ledger state.
2. **Cosmetic change**: re-format the docstring; re-order imports. Commit.
   Run `link_commit`. Show `auto_resolved_count: 1`, status flips to
   `compliant` with `semantic_status: semantically_preserved`. Zero LLM calls.
3. **Semantic change**: change the threshold inside the function from 100
   to 50. Commit. Run `link_commit`. Show the region appears in
   `pending_compliance_checks` with a `pre_classification` hint
   (`verdict: uncertain`, signals breakdown).
4. Walk through the LLM-side reasoning the `bicameral-sync` skill applies to
   issue the `drifted` verdict.
5. Show the M3 benchmark: 30 cases × 7 languages, 0% false-positive rate on
   the cosmetic-only set.

**Value claim**: "The classifier handles the easy 80% deterministically, leaves
only genuinely ambiguous cases for the LLM, and never costs you a token on a
docstring tweak."

### Authoring rules for new demos

- Run the demo end-to-end on a fresh clone before committing it. Demos that
  drift become anti-marketing.
- If the demo depends on a feature flag (`BICAMERAL_CODEGENOME_ENHANCE_DRIFT`,
  etc.), say so in **Prereqs**.
- If the demo records output, store the recording in `docs/demos/recordings/`
  next to the script. Keep recordings under 30 MB.
- Update the demo whenever the underlying tool's response shape changes —
  this is enforced under §9 (skill rule).

---

## 13. When in doubt

- **"Does this need a release PR?"** — If `main`'s SHA would change, yes.
- **"Should I close this issue?"** — `Closes #X` in the PR body, then yes
  (auto on dev-merge).
- **"Should I bump the version?"** — Only Jin bumps the version, only at
  release time.
- **"Can I commit a skill change separately from the tool change?"** — No.
  Same commit, same PR.
- **"Should I write a guide for this?"** — Use the §8 matrix. If the row says
  "yes", yes.
- **"Is this a hotfix or a feature?"** — Hotfix is for a regression on `main`
  that broke a user. Everything else is a feature.

---

**Owner**: Jin (release manager) + repo maintainers.
**Last reviewed**: 2026-04-29.
**Change protocol**: amendments require a META_LEDGER entry + a PR labeled
`docs:dev-cycle`.
