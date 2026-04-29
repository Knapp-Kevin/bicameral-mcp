"""Governance package — semantic drift escalation policy engine.

Phases 1-3 of the governance plan (#108-#110):
  - contracts: ``GovernanceMetadata``, ``GovernanceFinding``,
    ``GovernancePolicyResult`` Pydantic models + ``derive_governance_metadata``
  - finding_factories: builders + ``consolidate()`` for collapsing findings
    per ``(decision_id, region_id)``
  - config: ``.bicameral/governance.yml`` parser; ``allow_blocking`` is
    locked to ``Literal[False]`` at the type level
  - engine: pure deterministic ``evaluate()`` orchestrator

Phase 4 (#112 HITL bypass flow) and Phase 5 (#111 docs) ship in
follow-up PRs.
"""
