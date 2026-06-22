"""The standard governed credit-model development workflow.

The control flow is fixed here (invariant I2). Stages call kernel tools *by name*
— the harness that runs this workflow must register tools with these names and
contracts:

    profile()                      -> commits lineage (columns, schema hash)
    train_candidate(features)      -> commits candidates.<id> (gated by feature rails)
    validate(model_id)             -> commits candidates.<id>.{validated, disparate_impact}
    record_fairness_override(model_id) -> commits candidates.<id>.analyst_approved

Open nodes are routed by the StageContext: feature selection is a ``judgment``
node (an Advisor proposes the feature set; the kernel's feature rail gates the
commit, so a proposal never reaches state ungated — I3). Fairness and promotion
are human gates the workflow owns explicitly, rather than burying them in a tool.
"""

from __future__ import annotations

from typing import Any

from ..stage import Stage, StageContext, StageOutcome, Workflow

WORKFLOW_ID = "credit-model-development"
WORKFLOW_VERSION = "1"


def _s1_profile(ctx: StageContext) -> StageOutcome:
    res = ctx.call("profile", {}, turn_id="S1_profile")
    if not res.ok:
        return StageOutcome(status="failed", reason=res.error and str(res.error))
    return StageOutcome(status="ok")


def _s2_features(ctx: StageContext) -> StageOutcome:
    plan = ctx.scratch.get("plan")
    context = {
        "columns": ctx.state.get("columns", []),
        "strategies": list(getattr(plan, "candidate_strategies", ())),
        "candidates": ctx.state.get("candidates", {}),
        "last_reason": ctx.scratch.get("last_reason"),
    }
    res = ctx.decide(
        node="feature_set",
        kind="judgment",
        question=(
            "Propose a feature set for a probability-of-default model. Exclude the "
            "protected attribute and likely proxies; the feature rail will reject violations."
        ),
        then_tool="train_candidate",
        context=context,
        turn_id="S2_features",
    )
    if not res.ok:
        reason = res.error and str(res.error)
        if res.violations:
            reason = "; ".join(f"{v.rail_id}: {v.message}" for v in res.violations)
        ctx.scratch["last_reason"] = reason
        return StageOutcome(status="retry", reason=reason)
    ctx.scratch["model_id"] = res.result.model_id
    return StageOutcome(status="ok", data={"model_id": res.result.model_id})


def _make_s3_validate(di_threshold: float):
    def _s3_validate(ctx: StageContext) -> StageOutcome:
        model_id = ctx.scratch.get("model_id")
        if not model_id:
            return StageOutcome(status="failed", reason="no candidate to validate")
        res = ctx.call("validate", {"model_id": model_id}, turn_id="S3_validate")
        if not res.ok:
            reason = res.error and str(res.error)
            ctx.scratch["last_reason"] = reason
            return StageOutcome(status="retry", reason=reason)

        di = res.result.disparate_impact
        # Adversarial critic runs before the human is asked (advisory findings).
        findings = ctx.critique(model_id=model_id, reports={"disparate_impact": di})
        flags = "; ".join(f"{f.category}:{f.severity}" for f in findings)

        if di < di_threshold:
            decision = ctx.gate(
                trigger="fairness_review",
                proposal=(
                    f"{model_id} disparate impact {di:.2f} < {di_threshold:.2f}. "
                    f"Critic findings: {flags or 'none'}. "
                    f"Approve to override (recorded), deny to require mitigation, or halt."
                ),
            )
            if decision.halt:
                return StageOutcome(status="halt", reason="analyst halted at fairness review")
            if decision.approved:
                ctx.call("record_fairness_override", {"model_id": model_id}, turn_id="S3_validate")
                return StageOutcome(status="ok", data={"model_id": model_id, "override": True})
            ctx.scratch["last_reason"] = f"fairness denied for {model_id} (DI {di:.2f})"
            return StageOutcome(status="retry", reason="analyst denied; mitigate and retrain")
        return StageOutcome(status="ok", data={"model_id": model_id})

    return _s3_validate


def _s4_promote(ctx: StageContext) -> StageOutcome:
    model_id = ctx.scratch.get("model_id")
    decision = ctx.gate(
        trigger="promotion",
        proposal=f"Promote candidate {model_id}? The finalize promotion gate will run over final state.",
    )
    if decision.halt:
        return StageOutcome(status="halt", reason="analyst halted at promotion")
    if decision.approved:
        return StageOutcome(status="ok", data={"model_id": model_id})
    return StageOutcome(status="failed", reason="promotion declined")


def _s5_document(ctx: StageContext) -> StageOutcome:
    # Documentation is authored by the Scribe at finalize; this stage marks the
    # transition so the stage trace records that the run reached documentation.
    return StageOutcome(status="ok")


def _transition(state: dict[str, Any], stage_id: str, outcome: StageOutcome) -> str:
    if outcome.status == "halt":
        return "HALT"
    if stage_id == "S1_profile":
        return "S2_features" if outcome.status == "ok" else "HALT"
    if stage_id == "S2_features":
        return "S3_validate" if outcome.status == "ok" else "S2_features"
    if stage_id == "S3_validate":
        if outcome.status == "ok":
            return "S4_promote"
        if outcome.status == "retry":
            return "S2_features"
        return "HALT"
    if stage_id == "S4_promote":
        return "S5_document" if outcome.status == "ok" else "HALT"
    if stage_id == "S5_document":
        return "DONE"
    return "DONE"


def credit_workflow(*, di_threshold: float = 0.80) -> Workflow:
    """Build the standard credit-model development workflow."""
    return Workflow(
        id=WORKFLOW_ID,
        version=WORKFLOW_VERSION,
        stages=(
            Stage("S1_profile", _s1_profile, "Profile the dataset; commit lineage."),
            Stage("S2_features", _s2_features, "Propose a feature set (judgment) and train."),
            Stage("S3_validate", _make_s3_validate(di_threshold), "Validate; critic + fairness gate."),
            Stage("S4_promote", _s4_promote, "Human promotion sign-off."),
            Stage("S5_document", _s5_document, "Reach documentation; Scribe writes at finalize."),
        ),
        transition=_transition,
        budget_stage="S2_features",
    )


__all__ = ["WORKFLOW_ID", "WORKFLOW_VERSION", "credit_workflow"]
