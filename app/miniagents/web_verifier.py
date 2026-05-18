"""F5 web verifier mini-agent.

Per LLD §F5 (collapsed variant): one skill call, one web fetch, one
ClaimVerification row written per claim. The skill (owned by the
skills-build agent under skills/web_verifier/) plans + adjudicates in a
single pass; this mini-agent does the surrounding glue:

  1. Reuse a recent corroborated row if one exists (30d freshness window).
  2. Derive a single candidate URL (heuristic: account-slug -> bare domain,
     otherwise google search). Fetch it.
  3. Hand (claim, evidence_text, evidence_url) to the `web_verifier` skill.
  4. Persist the resulting ClaimVerification row. If the verdict is
     "contradicted" we'd open a CorrectionIntake; the corrections service
     doesn't expose an `open` method yet, so we log a TODO and stash the
     contradiction detail on the row.

The fan-out helper at the bottom is what `post_call` will call once F6's
wiring agent hooks it in.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from app.db.app_session import app_session
from app.db.repositories.claim_verifications_repo import ClaimVerificationsRepo
from app.db.repositories.workspaces_repo import WorkspacesRepo
from app.logging import get_logger
from app.services.web_verifier.browser_client import (
    BrowserSession,
    PageFetchResult,
    browser_session,
)
from app.skills import SkillContext, SkillRegistry

log = get_logger(__name__)


@dataclass(frozen=True)
class ExtractedClaim:
    subject: str
    predicate: str
    object: str
    source_utterance: str
    scope: str  # "org_wide" | "both" | "caller_specific"
    classifier_confidence: float = 0.8


@dataclass(frozen=True)
class ClaimVerifierInput:
    workspace_id: UUID
    call_id: UUID
    claim: ExtractedClaim


@dataclass(frozen=True)
class VerificationVerdict:
    status: str  # corroborated / unconfirmed / contradicted
    confidence: float
    evidence_url: str | None = None
    evidence_snippet: str | None = None
    contradiction_detail: str | None = None
    reasoning: str = ""

    @classmethod
    def unconfirmed(cls, reason: str, error_str: str | None = None) -> VerificationVerdict:
        suffix = f" ({error_str})" if error_str else ""
        return cls(
            status="unconfirmed",
            confidence=0.0,
            reasoning=f"unconfirmed: {reason}{suffix}",
        )


@dataclass(frozen=True)
class ClaimVerifierResult:
    verdict: VerificationVerdict
    correction_intake_id: UUID | None
    claim_verification_id: UUID


# ---------------------------------------------------------------------------
# URL planning heuristic
# ---------------------------------------------------------------------------


def _plan_candidate_url(claim: ExtractedClaim) -> str:
    """Pick a single URL to fetch for this claim.

    Subject conventions match the brain page slugs produced by F2/F4:
    `accounts/<slug>`, `people/<slug>`, etc. For accounts we try the
    obvious `https://www.<slug>.com`. For everything else we fall back
    to a Google search of predicate+object+subject.
    """
    subj = (claim.subject or "").strip().lower()
    if subj.startswith("accounts/"):
        slug = subj[len("accounts/"):].strip("/")
        slug = slug.replace("_", "-")
        if slug:
            return f"https://www.{slug}.com"
    # Fallback: search.
    from urllib.parse import quote_plus

    query = " ".join(
        part for part in (claim.predicate, claim.object, claim.subject) if part
    )
    return f"https://www.google.com/search?q={quote_plus(query)}"


# ---------------------------------------------------------------------------
# Skill bridge
# ---------------------------------------------------------------------------


def _skill_inputs(
    workspace_id: UUID, claim: ExtractedClaim, fetch: PageFetchResult
) -> dict[str, Any]:
    """Build the dict the web_verifier skill expects.

    Matches skills/web_verifier/schema.py: requires workspace_id at the top
    level and claim.scope (org_wide | both - caller_specific is filtered
    upstream in the fan-out).
    """
    # Map "caller_specific" or unexpected scopes to "both" defensively;
    # the fan-out is supposed to filter these out before reaching here.
    scope = claim.scope if claim.scope in ("org_wide", "both") else "both"
    return {
        "workspace_id": str(workspace_id),
        "claim": {
            "subject": claim.subject,
            "predicate": claim.predicate,
            "object": claim.object,
            "source_utterance": claim.source_utterance,
            "scope": scope,
        },
        "evidence_text": fetch.text or "",
        "evidence_url": fetch.url,
        "fetch_ok": fetch.ok,
    }


def _verdict_from_skill(out: Any, fallback_url: str | None) -> VerificationVerdict:
    """Best-effort conversion of skill output -> VerificationVerdict.

    The skill's exact output schema is owned elsewhere; we look up fields
    permissively so we can ship before that schema is locked in.
    """
    def _get(key: str, default: Any = None) -> Any:
        if hasattr(out, key):
            return getattr(out, key)
        if isinstance(out, dict):
            return out.get(key, default)
        return default

    status = str(_get("status", "unconfirmed"))
    if status not in ("corroborated", "unconfirmed", "contradicted"):
        status = "unconfirmed"
    confidence_raw = _get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    return VerificationVerdict(
        status=status,
        confidence=confidence,
        evidence_url=_get("evidence_url") or fallback_url,
        evidence_snippet=_get("evidence_snippet"),
        contradiction_detail=_get("contradiction_detail"),
        reasoning=str(_get("reasoning", "")),
    )


# ---------------------------------------------------------------------------
# Per-claim run
# ---------------------------------------------------------------------------


async def _load_workspace_org_id(workspace_id: UUID) -> UUID | None:
    async with app_session() as session:
        ws = await WorkspacesRepo(session).get_by_id(workspace_id)
        return ws.organization_id if ws else None


async def run_web_verifier(inputs: ClaimVerifierInput) -> ClaimVerifierResult:
    claim = inputs.claim

    # --- 1. Freshness reuse ------------------------------------------------
    async with app_session() as session:
        repo = ClaimVerificationsRepo(session)
        existing = await repo.find_existing_corroborated(
            workspace_id=inputs.workspace_id,
            claim_subject=claim.subject,
            claim_predicate=claim.predicate,
            claim_object=claim.object,
            within_days=30,
        )
        if existing is not None:
            log.info(
                "web_verifier_reused_corroborated",
                workspace_id=str(inputs.workspace_id),
                call_id=str(inputs.call_id),
                claim_subject=claim.subject,
                source_row_id=str(existing.id),
            )
            return ClaimVerifierResult(
                verdict=VerificationVerdict(
                    status="corroborated",
                    confidence=existing.confidence,
                    evidence_url=existing.evidence_url,
                    evidence_snippet=existing.evidence_snippet,
                    reasoning="reused_recent_corroborated",
                ),
                correction_intake_id=existing.correction_intake_id,
                claim_verification_id=existing.id,
            )

    # TODO(post-F5): once BrainProvider exposes `manager_authoritative`
    # cleanly via try_get_page(), short-circuit here with an
    # `unconfirmed("manager_authoritative_lock")` to match LLD §F5.

    # --- 2. Plan + fetch ---------------------------------------------------
    url = _plan_candidate_url(claim)
    session_name = f"verify-{uuid4().hex[:8]}"
    async with browser_session(name=session_name, timeout_ms=30_000) as browser:
        fetch = await browser.fetch_page(url)

    # --- 3. Skill adjudication --------------------------------------------
    verdict: VerificationVerdict
    try:
        skill = SkillRegistry.get("web_verifier")
    except KeyError:
        log.warning(
            "web_verifier_skill_not_registered",
            call_id=str(inputs.call_id),
            claim_subject=claim.subject,
        )
        verdict = VerificationVerdict.unconfirmed("skill_not_registered")
    else:
        try:
            skill_inputs = _skill_inputs(inputs.workspace_id, claim, fetch)
            input_obj = skill.input_schema.model_validate(skill_inputs)
            ctx = SkillContext(workspace_id=inputs.workspace_id)
            skill_out = await skill.run(input_obj, ctx)
            verdict = _verdict_from_skill(skill_out, fallback_url=fetch.url)
        except Exception as e:  # noqa: BLE001
            log.exception(
                "web_verifier_skill_failed",
                call_id=str(inputs.call_id),
                claim_subject=claim.subject,
            )
            verdict = VerificationVerdict.unconfirmed(
                "skill_error", error_str=f"{type(e).__name__}: {e}"
            )

    # --- 4. Contradiction -> CorrectionIntake -----------------------------
    correction_intake_id: UUID | None = None
    org_id = await _load_workspace_org_id(inputs.workspace_id)
    if verdict.status == "contradicted" and org_id is not None:
        from app.services.correction_intake import open_correction_intake

        try:
            async with app_session() as session:
                ws_repo = WorkspacesRepo(session)
                workspace = await ws_repo.get_by_id(inputs.workspace_id)
                target_user_id = workspace.manager_user_id if workspace else None
                if target_user_id is not None:
                    correction_intake_id = await open_correction_intake(
                        session,
                        workspace_id=inputs.workspace_id,
                        organization_id=org_id,
                        target_user_id=target_user_id,
                        origin="system_web_verifier",
                        source_ref_id=inputs.call_id,
                        payload={
                            "contradiction": verdict.contradiction_detail,
                            "evidence_url": verdict.evidence_url,
                            "evidence_snippet": verdict.evidence_snippet,
                            "source_utterance": claim.source_utterance,
                            "claim": {
                                "subject": claim.subject,
                                "predicate": claim.predicate,
                                "object": claim.object,
                            },
                        },
                    )
                    await session.commit()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "web_verifier_correction_intake_open_failed",
                call_id=str(inputs.call_id),
                error=str(e),
            )

    # --- 5. Persist --------------------------------------------------------
    if org_id is None:
        org_id = await _load_workspace_org_id(inputs.workspace_id)
    if org_id is None:
        # Workspace vanished out from under us — extremely unlikely, but
        # don't crash the fan-out.
        log.warning(
            "web_verifier_workspace_missing_at_persist",
            workspace_id=str(inputs.workspace_id),
        )
        return ClaimVerifierResult(
            verdict=VerificationVerdict.unconfirmed("workspace_missing"),
            correction_intake_id=None,
            claim_verification_id=uuid4(),
        )

    async with app_session() as session:
        repo = ClaimVerificationsRepo(session)
        row = await repo.create(
            workspace_id=inputs.workspace_id,
            organization_id=org_id,
            call_id=inputs.call_id,
            claim_subject=claim.subject,
            claim_predicate=claim.predicate,
            claim_object=claim.object,
            claim_source_utterance=claim.source_utterance,
            status=verdict.status,  # type: ignore[arg-type]
            confidence=verdict.confidence,
            evidence_url=verdict.evidence_url,
            evidence_snippet=verdict.evidence_snippet,
            contradiction_detail=verdict.contradiction_detail,
            correction_intake_id=correction_intake_id,
        )
        await session.commit()
        row_id = row.id

    return ClaimVerifierResult(
        verdict=verdict,
        correction_intake_id=correction_intake_id,
        claim_verification_id=row_id,
    )


# ---------------------------------------------------------------------------
# Fan-out (called by post_call worker once wiring agent integrates it)
# ---------------------------------------------------------------------------


async def web_verifier_fanout(
    *,
    workspace_id: UUID,
    call_id: UUID,
    claims: list[ExtractedClaim],
) -> list[VerificationVerdict]:
    """Verify up to N claims for a single call in parallel.

    Config lives at `ManagerWorkspace.config["verifier"]`:
        disabled (bool, default False)
        max_claims_per_call (int, default 5)
        skip_below_classifier_confidence (float, default 0.7)
    """
    if not claims:
        return []

    async with app_session() as session:
        ws = await WorkspacesRepo(session).get_by_id(workspace_id)
    cfg: dict[str, Any] = {}
    if ws is not None:
        cfg = (ws.config or {}).get("verifier", {}) or {}

    if cfg.get("disabled", False):
        log.info(
            "web_verifier_fanout_disabled",
            workspace_id=str(workspace_id),
            call_id=str(call_id),
            n_claims=len(claims),
        )
        return [VerificationVerdict.unconfirmed("verifier_disabled") for _ in claims]

    max_claims = int(cfg.get("max_claims_per_call", 5))
    floor = float(cfg.get("skip_below_classifier_confidence", 0.7))

    # Scope filter: caller-specific claims never reach the verifier per LLD §F5.
    web_scoped = [c for c in claims if c.scope in ("org_wide", "both")]
    capped = sorted(web_scoped, key=lambda c: -c.classifier_confidence)[:max_claims]
    target = [c for c in capped if c.classifier_confidence >= floor]

    if not target:
        reason = "no_web_scoped_claims" if not web_scoped else "below_confidence_floor"
        return [VerificationVerdict.unconfirmed(reason) for _ in claims]

    results = await asyncio.gather(
        *(
            run_web_verifier(
                ClaimVerifierInput(
                    workspace_id=workspace_id, call_id=call_id, claim=c
                )
            )
            for c in target
        ),
        return_exceptions=True,
    )

    verdicts: list[VerificationVerdict] = []
    for r in results:
        if isinstance(r, BaseException):
            verdicts.append(
                VerificationVerdict.unconfirmed("verifier_error", error_str=repr(r))
            )
        else:
            verdicts.append(r.verdict)
    return verdicts


# Re-export so callers can keep `from app.services.web_verifier.browser_client import ...`
# if they prefer, but the mini-agent is self-contained.
__all__ = [
    "ClaimVerifierInput",
    "ClaimVerifierResult",
    "ExtractedClaim",
    "VerificationVerdict",
    "run_web_verifier",
    "web_verifier_fanout",
    "BrowserSession",
]
