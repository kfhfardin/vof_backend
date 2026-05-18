# Web Verifier — High-Level Design

**Version:** 0.1 (Draft — companion to Voice of the Field HLD v0.6)
**Status:** Design Review
**Owners:** Engineering
**Depends on:** VotF HLD §7 (Key Flows), §8.2 (MiniAgent), §8.7 (Skills), §9 (Correction & Provenance), §11 (Third-Party Integration Contracts), §12 (Smoke Tests)

> **What this is.** A verification gate that sits between claim extraction and any brain / caller-memory write. For each org-wide claim a Rep made on a call, the verifier checks the open web, attaches the verdict to the write as provenance and a trust tag, and — on contradiction — opens a Manager-adjudicated `CorrectionIntake` rather than silently dropping the Rep's claim. Built on the §8.2 `MiniAgent` extension point with browser-harness wrapped behind an internal client. Caller-specific claims are never web-verified.

---

## 1. Overview

The Workspace Brain compounds from a single trust source today: a Rep said it on a call. That's a strong signal but not a complete one. Reps misremember, conflate accounts, and sometimes report what they *expect* the customer to do instead of what was decided. The web is an imperfect but independent second source: hiring announcements show up on LinkedIn, pricing on company sites, funding on Crunchbase, layoffs in the press.

The Web Verifier introduces a per-claim verification step that runs **after extraction, before any write hardens**. It produces one of three verdicts (`corroborated` / `unconfirmed` / `contradicted`), attaches the verdict to the write, and — only on contradiction — opens a `CorrectionIntake` for the Manager. **The Rep's claim is always written.** The verifier annotates, it does not gatekeep.

---

## 2. Goals and Non-Goals

### 2.1 Goals

1. Every org-wide claim entering the Workspace Brain carries a verifier verdict and, when corroborated or contradicted, a list of web sources in its provenance.
2. Contradictions surface to the Manager as a `CorrectionIntake`, never as a silent overwrite or silent drop.
3. The Brain UI can render a trust band per page (corroborated / unverified / contested) without schema changes downstream.
4. Verification respects the §2 scope boundary: caller-specific claims and caller-memory writes are never sent to the verifier.
5. The verifier is a §8.2 MiniAgent; skills it depends on are §8.7 first-class artifacts with quality bars and eval gates.

### 2.2 Non-Goals

- Verifying caller-specific style, sentiment, or interpersonal observations. The open web has nothing to say about whether Sarah at Acme prefers a security-led pitch.
- Adjudicating between Rep and web. The system reports the disagreement; the Manager decides.
- Real-time mid-call verification. Hot-path latency budget (§15) makes this infeasible. Verification is strictly post-call.
- A general-purpose web-research tool. The verifier checks specific claims against specific signals. Open-ended web research is a separate (Phase 1+) MiniAgent.

---

## 3. Glossary Additions

| Term | Definition |
|---|---|
| **Claim** | A subject-predicate-object triple extracted from a transcript, with the source utterance retained for audit. E.g., `(acme-corp, hired_as_cto, "Jane Doe")`. |
| **Verdict** | The verifier's output per claim: `corroborated` / `unconfirmed` / `contradicted`, plus confidence, evidence, and (for contradictions) a `contradiction_detail`. |
| **Trust tag** | A label attached to a brain page or claim reflecting verifier state: `web_corroborated`, `unverified_web`, `contradicts_web_source`. |
| **Verifiable-against-web** | A boolean on each extracted claim, set by the `classifier` skill, indicating whether the open web is a plausible adjudicator for this *kind* of claim. False for style, sentiment, internal sales process, and most caller-specific observations. |

---

## 4. Where It Sits in the Pipeline

The verifier is inserted between Stage 3 (classification) and Stage 4 (brain seed / caller memory write) of the VotF §7 ingestion flow. It runs in the post-call worker fan-out alongside the existing summarizer and action-item extractor (Phase Map item 14).

```
transcript
  ├─→ summarizer                       (existing)
  ├─→ action_item_extractor            (existing)
  ├─→ entity_extractor                 (existing in Phase 1)
  ├─→ classifier                       (existing — now emits verifiable_against_web)
  │       │
  │       ├─→ caller_memory_writer     ← caller-specific items skip verifier entirely
  │       │
  │       └─→ web_verifier  ◄──── NEW
  │              │
  │              └─→ brain_seeder      ← writes with verdict-derived tags
  │                     │
  │                     └─→ correction_intake (only on contradicted)
  └─→ ...
```

Two routing rules at the classifier → writer handoff:

1. `target_store = caller_memory` **bypasses the verifier**. No exceptions.
2. `verifiable_against_web = false` on an org-wide claim **bypasses the verifier** and writes with tag `unverified_web` automatically. (No point spinning up a browser session to "verify" that the customer was annoyed.)

The verifier only runs when both the scope and the claim type warrant it. This is a cost lever as much as a correctness one.

---

## 5. Data Model

Three additions, no schema reshapes.

### 5.1 `ClaimVerification` table

```python
class ClaimVerification(Base):
    id: UUID
    workspace_id: UUID
    call_id: UUID                       # provenance origin
    claim_subject: str                  # entity slug, e.g. "accounts/acme-corp"
    claim_predicate: str                # e.g. "hired_as_cto"
    claim_object: str
    claim_source_utterance: str         # verbatim, for the Manager to read
    status: Literal["corroborated", "unconfirmed", "contradicted"]
    confidence: float
    web_sources: list[WebSource]        # url, snippet, fetched_at, domain_skill_used
    contradiction_detail: str | None
    created_at: datetime
    correction_intake_id: UUID | None   # set if contradiction opened a correction
```

### 5.2 Brain page tag extensions

`BrainPage.tags` (already exists) gains three reserved values: `web_corroborated`, `unverified_web`, `contradicts_web_source`. Tags compose: a page can carry both `manager_authoritative` and `contradicts_web_source` (Manager has reviewed; verdict retained for audit).

### 5.3 `CorrectionIntake` source extension

Per VotF §9, `CorrectionIntake.origin` is already an enum. Add one variant:

```
origin: Literal["manager", "rep_callback", "system_web_verifier"]
```

A `system_web_verifier`-originated correction renders in the Manager's review queue with both sides shown — the Rep's claim verbatim, the web evidence, the timestamp of each. The Manager picks one (or writes a third value). Standard `§9` correction cascade applies downstream.

---

## 6. The MiniAgent Contract

```python
class ClaimVerifierInput(BaseModel):
    workspace_id: UUID
    call_id: UUID
    claim: ExtractedClaim
    scope: Literal["org_wide", "both"]   # caller_specific never reaches here

class ClaimVerifierResult(BaseModel):
    verdict: VerificationVerdict
    correction_intake_id: UUID | None    # set if contradicted

class WebVerifierAgent(MiniAgent):
    name = "web_verifier"
    trigger = "queue"

    async def run(self, ctx: AgentContext, inputs: ClaimVerifierInput) -> ClaimVerifierResult:
        plan = await Skill.load(
            "web_verifier_planner",
            workspace_id=inputs.workspace_id,
        ).run(inputs.claim)

        if not plan.verifiable:
            return self._unconfirmed_result(reason="no_authoritative_source")

        bu_name = f"votf-ws-{inputs.workspace_id}-verify-{ctx.run_id}"
        evidence: list[WebSource] = []
        async with self._browser_session(bu_name) as session:
            for step in plan.steps[: ctx.config.verifier.max_pages_per_claim]:
                page = await session.fetch_page(step.url, skill=step.domain_skill)
                if page.ok:
                    evidence.append(page.to_web_source())

        verdict = await Skill.load("web_verifier_adjudicator").run(
            claim=inputs.claim, evidence=evidence,
        )

        ci_id = None
        if verdict.status == "contradicted":
            ci_id = await ctx.corrections.open(
                workspace_id=inputs.workspace_id,
                origin="system_web_verifier",
                claim=inputs.claim,
                contradiction=verdict.contradiction_detail,
                web_sources=evidence,
                target_user_id=ctx.workspace.manager_id,
            )

        await ctx.db.write(ClaimVerification(verdict=verdict, ...))
        return ClaimVerifierResult(verdict=verdict, correction_intake_id=ci_id)
```

The brain_seeder consumes the verdict and chooses tags. The verifier never writes to the brain directly — same discipline §8.2 mini-agents follow elsewhere.

---

## 7. Skills (§8.7 Additions)

Three new skill directories:

- **`skills/web_verifier_planner/`** — given a claim, return `(verifiable: bool, steps: [(url, domain_skill, expected_signal)])`. Quality bar: precision on "should this be verified at all." Bias toward `verifiable=false`; over-eager verification is the failure mode that costs money.
- **`skills/web_verifier_adjudicator/`** — given a claim and evidence pages, return `(status, confidence, contradiction_detail)`. Quality bar: **low false-corroboration rate.** Saying "the web confirms this" when it doesn't is the dangerous failure; saying "unconfirmed" when corroboration exists is merely a missed opportunity.
- **`skills/contradiction_reporter/`** — formats the contradiction for the Manager's review surface. Quality bar: faithful presentation of both sides; never frames the Rep as wrong before the Manager has reviewed.

The `classifier` skill (§8.7 existing) gains one output field:

```python
class ClassificationOutput(BaseModel):
    # ... existing fields ...
    verifiable_against_web: bool      # new in classifier v0.4
```

This is a single-version-bump change to an existing skill, gated through the same eval CI.

---

## 8. Caller Memory vs. Brain Posture

Explicit because it affects routing:

- **Workspace Brain, scope=`ORG_WIDE` or `BOTH` (org half):** verifier runs.
- **Workspace Brain, scope=`BOTH` (caller half):** verifier does not run on the caller half.
- **Caller Memory (Supermemory):** verifier never runs. Writes go through unchanged.
- **Raw sources:** verifier does not run. Raw documents are evidence, not claims.

The branch lives at the classifier → writer handoff and is one conditional, not a new pipeline.

---

## 9. Integration with §9 (Correction & Provenance)

Three reuses of existing machinery, no new concepts:

1. **Provenance is multi-source.** A `web_corroborated` brain page cites the call and the web source(s) jointly. The §9 `Provenance` table already supports multiple `source_ref`s per claim.
2. **Contradictions are CorrectionIntakes with a new origin.** All §9 cascade behavior (downstream pages that cite the corrected claim get re-flagged) applies unchanged.
3. **`manager_authoritative` wins.** Once a Manager resolves a contradiction in the Rep's favor, the page is locked and re-verification is suppressed. The verifier checks the `manager_authoritative` flag before running and skips already-locked claims. (Open question §14.2 in the parent doc about field-level vs. page-level locking applies unchanged here.)

---

## 10. §12 Smoke Probe

Per §12.10, adding the verifier means adding `smoke/web_verifier.py`. Roughly:

```python
class WebVerifierProbe(Probe):
    name = "web_verifier"
    required_env = ["BROWSER_USE_API_KEY", "LLM_API_KEY", "SMOKE_VERIFIER_FIXTURE_CLAIM"]

    def checks_for_mode(self):
        self.check("cloud_auth", self._auth)
        self.check("planner_skill_loads", self._planner_loads)
        self.check("adjudicator_skill_loads", self._adjudicator_loads)
        if self.mode in ("smoke", "repair"):
            self.check("end_to_end_corroborated", self._happy_path_corroborated,
                       fix_hint="Fixture claim should resolve to corroborated; check fixture URL freshness.")
            self.check("end_to_end_contradicted", self._happy_path_contradicted)
            self.check("session_teardown_billable_stopped", self._stop_session,
                       fix_hint="Stray cloud sessions bill until timeout.")
```

The end-to-end checks use frozen fixture claims (one designed to corroborate against a stable Wikipedia-style URL, one designed to contradict). The fixtures are pinned and updated through the same skill-evals review process — drift in the upstream web page is treated as a fixture-maintenance task, not a verifier bug.

---

## 11. Bounds & Cost

Per-Workspace config knobs (under `workspace.config.verifier.*`):

| Knob | Default | Purpose |
|---|---|---|
| `max_claims_per_call` | 5 | Hard cap on claims sent to the verifier per call |
| `max_pages_per_claim` | 3 | Pages fetched per verification |
| `skip_below_classifier_confidence` | 0.7 | Don't verify what's already heading to NeedsReview |
| `session_timeout_ms` | 30000 | Bound cloud-session billing per claim |
| `disabled` | false | Workspace-level kill switch |

**Cost shape.** Per call: up to 5 claims × up to 3 pages × ~$0.002 per page (cloud session amortized) + ~5 LLM calls (planner + adjudicator). Order-of-magnitude $0.05–0.15 per call at the cap, less in practice. Feeds into the per-Workspace cost telemetry §14.4 calls for.

---

## 12. Phase Placement

Phase 1, alongside Phase Map item 14 (post-call summarization + action items). The verifier shares the post-call worker, the entity-extractor output, and the existing IntakeBuffer pipeline. Three new Phase Map rows:

| # | Priority | Phase | Component Work |
|---|---|---|---|
| 14a | Classifier `verifiable_against_web` field | 1 | Bump `classifier` skill to v0.4; eval gate on the new field |
| 14b | Web verifier MiniAgent + skills | 1 | `web_verifier` agent; `web_verifier_planner`, `web_verifier_adjudicator`, `contradiction_reporter` skills; `ClaimVerification` table; browser-harness client wrapper |
| 14c | Correction surface for system-originated contradictions | 1 | `CorrectionIntake.origin = system_web_verifier`; Manager review UI shows both sides; cascade integration |

Phase 0 ships without it. The brain still writes from Rep claims; trust tags default to `unverified_web` once the schema lands. Lighting up the verifier in Phase 1 is additive — no Phase 0 data needs to be re-processed.

---

## 13. Open Questions

- **Evidence freshness.** A 2-year-old LinkedIn page saying "Jane Doe, CTO" doesn't corroborate today's claim that she's *still* CTO. The adjudicator skill needs a freshness heuristic and a way to distinguish "evidence states the claim" from "evidence is consistent with the claim being newly true." Pinning in `skills/web_verifier_adjudicator/SKILL.md` quality_bar before build.
- **What counts as "the web."** Wikipedia? LinkedIn (often gated)? Crunchbase (paywalled fields)? The planner's allowed-source list needs to be explicit and per-claim-type, not "anything Google returns."
- **Repeat verification.** If a page is `unverified_web` today because no source existed, do we re-verify in a week when the press release lands? Likely yes for a bounded window; mechanism is a candidate Phase 2 `verifier_retry` cron.
- **Rep visibility.** When the Rep-side FE ships (Phase 1+), do Reps see that their claim was contradicted before the Manager has reviewed? Leaning no — the Manager adjudicates first. Confirm with product.

---

## 14. Risks

- **False corroboration is the dangerous failure.** A page that *looks* like it confirms a claim but doesn't, accepted by the adjudicator, hardens a wrong claim with a falsely-confident tag. Mitigation: the adjudicator's quality_bar is precision-weighted on corroboration, not recall; eval set includes adversarial near-misses.
- **Reps lose trust if "contradicted" feels accusatory.** The `contradiction_reporter` skill's quality bar exists for exactly this reason. The Manager's review UI must lead with the Rep's claim verbatim, web evidence second, and never auto-resolve.
- **Cost creep.** Five claims per call × 1000 calls/month × all Workspaces stacks. The bounds in §11 are the first defense; per-Workspace cost dashboards are the second.
- **Browser Use Cloud as a critical dependency.** If the cloud is down, the verifier degrades to "unconfirmed" for all claims — does not block writes. Verified by the §12 smoke probe's upstream-down exit code path.
- **Skill drift.** The planner's allowed-source list and the adjudicator's freshness heuristic both encode editorial judgment that will rot. The §8.7 CHANGELOG and quality_bar discipline applies; quarterly review of both skills is a candidate Phase 1+ ops rhythm.
