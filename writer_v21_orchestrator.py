"""Writer V2.1 orchestration with fail-closed semantic verification.

This is a deliberately small extraction from ``generate.generate_candidate_v2``.
It reuses the existing Writer V2.1 writer, claim inventory, deterministic
traceability, validator, scorer, critic, and targeted-repair primitives while
fixing one promotion-critical control-flow flaw:

    critic unavailable/malformed != zero semantic violations.

A candidate may enter the selectable pool only after complete semantic coverage
for hook + every beat + payoff. One bounded semantic retry is allowed across the
ENTIRE candidate run, and only after the current round is mechanically and
structurally clean enough that the retry can materially advance selection or
creative repair. Provider outage is never treated as a script defect and never
causes a provenance rewrite.

The module has no publishing/render side effects. ``generate.py`` can delegate to
this function after evidence is satisfactory; until then it is independently
bakeoff/testable on an isolated branch.
"""
from __future__ import annotations

import json
from typing import Any

import generate as G
import writer_v2 as W
import writer_v2_repair as R
import writer_v21_semantic_gate as SG


MAX_SEMANTIC_RETRIES_PER_RUN = 1


def _parse_call(raw: str | None, default_error: str) -> tuple[dict[str, Any] | None, str | None]:
    if raw is None:
        return None, default_error
    obj, err = G._v2_parse_json_obj(raw)
    return obj, err


def _call_critic(prompt: str, calls: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    raw, _ = G._v2_structured_call(prompt, R.CRITIC_SCHEMA, "critic_verdict", calls)
    return _parse_call(raw, "critic call failed on every provider")


def _parse_repair(raw: str | None) -> tuple[dict[str, Any] | None, str | None]:
    if raw is None:
        return None, "repair call failed on every provider"
    obj, err = G._v2_parse_json_obj(raw)
    if not err:
        return obj, None
    # Preserve Claude's live-observed compatibility with a bare JSON repair
    # array from a non-structured fallback. The envelope is cosmetic; beat
    # indices/claim IDs are still revalidated after merge on the next round.
    try:
        bare = json.loads(raw)
        if isinstance(bare, list):
            return {"repairs": bare}, None
    except Exception:  # noqa: BLE001
        pass
    return None, err


def generate_candidate_v21(
    fact,
    job_name="CURIOSITY_ITCH",
    recent_treatments=None,
    avoid_topics="",
    cta_style="SAVE_WORTHY",
    use_structured=True,  # retained for call-site compatibility / debug surface
):
    """Generate one Writer V2.1 candidate with semantic verification load-bearing.

    Network-invocation ceiling at MAX_REPAIR_ROUNDS=2:
      1 initial draft + 3 normal critics + 2 repairs + at most 1 semantic retry
      = 7 structured-call invocations worst case.

    The extra call is globally bounded to ONE per entire candidate run. It is
    spent only when a round has no hard mechanical violation and no validate()
    failure, i.e. when complete semantic/craft feedback can actually determine
    acceptance or the next quality repair. This avoids burning retries while a
    known mechanical defect already dictates the repair target.
    """
    treatment = W.select_treatment((fact or {}).get("id"), recent_treatments)
    dossier = G.research_dossier(fact) if fact else []
    grounded = bool(dossier)
    claim_inventory = W.build_claim_inventory(fact, dossier_facts=dossier, grounded=grounded)
    prompt = W.build_writer_prompt_v2(
        treatment,
        claim_inventory,
        avoid_topics=avoid_topics,
        visual_evidence=(fact or {}).get("queries"),
    )
    calls: list[dict[str, Any]] = []
    debug: dict[str, Any] = {
        "orchestrator": "writer_v21_semantic_failclosed_v1",
        "treatment": treatment,
        "prompt_chars": len(prompt),
        "prompt_tokens_est": G.estimate_tokens(prompt),
        "grounded": grounded,
        "provenance_note": claim_inventory.get("provenance_note"),
        "claim_count": len(claim_inventory.get("claims") or []),
        "rounds": [],
        "calls": calls,
        "semantic_retry_budget": MAX_SEMANTIC_RETRIES_PER_RUN,
        "semantic_retries_used": 0,
    }

    raw, _ = G._v2_structured_call(prompt, W.WRITER_V2_SCHEMA, "writer_v2_output", calls)
    if raw is None:
        debug.update(error="initial draft call failed on every provider", total_calls=len(calls), accepted=False)
        return None, debug
    writer_out, err = G._v2_parse_json_obj(raw)
    if err:
        debug.update(error=err, raw=(raw or "")[:500], total_calls=len(calls), accepted=False)
        return None, debug

    candidates: list[dict[str, Any]] = []
    round_idx = 0
    stalled = False
    semantic_retry_used = False

    while True:
        num_beats = len(writer_out.get("beats") or [])
        mech_violations = R.check_traceability(writer_out, claim_inventory)
        mech_hard = R.hard_violations(mech_violations)
        manifest = W.assemble_manifest_v2(
            writer_out,
            fact,
            treatment,
            job_name=job_name,
            cta_style=cta_style,
            banned_query_re=G.UNSTOCKABLE_Q,
        )
        validate_err = G.validate(manifest, job_name, fact=fact)
        score = None if validate_err else G.score_script(manifest, fact=fact, cta_style=cta_style)
        score_overall = score.get("overall") if (score and G._clears_quality_floor(score)) else None

        critic_prompt = R.build_critic_prompt(writer_out, claim_inventory, mech_violations)
        critic_verdict, critic_error = _call_critic(critic_prompt, calls)
        coverage_ok, coverage_errors, covered_indices = SG.validate_semantic_coverage(
            critic_verdict, num_beats
        )

        # Spend at most ONE extra critic invocation across the whole candidate
        # run, and only when no known mechanical/validate problem already tells
        # us what to repair. This retry can rescue semantic verification OR give
        # the craft diagnosis needed to repair an otherwise-clean but sub-floor
        # candidate. It never becomes an unbounded provider-contention loop.
        critic_attempts = 1
        if (not coverage_ok and not mech_hard and not validate_err and not semantic_retry_used):
            semantic_retry_used = True
            debug["semantic_retries_used"] = 1
            retry_prompt = (
                critic_prompt
                + "\n\nRETRY REQUIREMENT: the prior critic response was unavailable or did not provide "
                  "one valid claim_support verdict for EVERY beat_index (hook, all beats, payoff). "
                  "Return the exact schema completely. Do not omit any beat_index."
            )
            critic_verdict, retry_error = _call_critic(retry_prompt, calls)
            critic_attempts = 2
            if retry_error:
                critic_error = "; retry: " + retry_error if critic_error else retry_error
            coverage_ok, coverage_errors, covered_indices = SG.validate_semantic_coverage(
                critic_verdict, num_beats
            )

        if coverage_ok:
            semantic_violations = R.derive_semantic_violations(critic_verdict, num_beats)
            semantic_failure = None
            critic_avg = R.critic_average(critic_verdict)
            effective_critic = critic_verdict
        else:
            semantic_violations = []
            reason = "; ".join(coverage_errors) or critic_error or "semantic critic unavailable"
            semantic_failure = SG.SemanticCoverageFailure(reason)
            critic_avg = None
            # A structurally incomplete critic response is not trustworthy as a
            # creative-director signal either. Do not let malformed semantic
            # coverage drive hook/payoff/naturalness rewrites.
            effective_critic = None

        candidate_hard = list(mech_hard) + list(semantic_violations)
        if semantic_failure is not None:
            candidate_hard.append(semantic_failure)

        round_info = {
            "round": round_idx,
            "mechanical_violation_count": len(mech_violations),
            "mechanical_hard_count": len(mech_hard),
            "semantic_verified": coverage_ok,
            "semantic_critic_attempts": critic_attempts,
            "semantic_covered_indices": list(covered_indices),
            "semantic_coverage_errors": list(coverage_errors),
            "semantic_violation_count": len(semantic_violations),
            "violations": [v.to_dict() for v in (mech_violations + semantic_violations)[:30]],
            "validate_err": validate_err,
            "score": score,
            "score_clears_floor": score_overall is not None,
            "critic_avg": critic_avg,
            "critic_error": critic_error,
            "critic_verdict": critic_verdict,
            "stalled_going_in": stalled,
            "hook": manifest.get("hook"),
            "payoff": manifest.get("payoff"),
            "beats": [s.get("voiceover") for s in manifest.get("scenes", [])],
        }
        if semantic_failure is not None:
            round_info["semantic_gate_failure"] = semantic_failure.reason
        debug["rounds"].append(round_info)

        candidates.append({
            "writer_out": writer_out,
            "manifest": manifest,
            "hard_violations": candidate_hard,
            "validate_err": validate_err,
            "score": score_overall,
            "critic_avg": critic_avg,
            "semantic_verified": coverage_ok,
        })

        # Provider/shape failure is not a script provenance defect. Real
        # mechanical or validate defects may still be repaired. If those are
        # absent, an unverifiable round has no safe repair target and stops.
        plan = R.classify_repair(
            mech_hard,
            semantic_violations if coverage_ok else [],
            validate_err,
            effective_critic,
            num_beats,
        )
        if not coverage_ok and not mech_hard and not validate_err:
            plan = {
                "repair_type": "NONE",
                "target_beats": [],
                "diagnosis": "semantic verification unavailable; candidate cannot be accepted",
                "must_preserve": [],
                "tier": 0,
            }
        round_info["repair_plan"] = plan

        if round_idx >= R.MAX_REPAIR_ROUNDS:
            break
        if plan["repair_type"] == "NONE":
            break

        repair_prompt = R.build_repair_prompt(
            writer_out, claim_inventory, treatment, plan, stalled=stalled
        )
        repair_raw, _ = G._v2_structured_call(
            repair_prompt, R.REPAIR_SCHEMA, "repair_output", calls
        )
        repair_out, repair_error = _parse_repair(repair_raw)
        if repair_error:
            round_info["repair_error"] = repair_error
            break

        new_writer_out = R.merge_repair(
            writer_out,
            (repair_out or {}).get("repairs") or [],
            num_beats=num_beats,
        )
        stalled = R.detect_stall(
            writer_out,
            new_writer_out,
            plan.get("target_beats") or [],
            num_beats,
        )
        writer_out = new_writer_out
        round_idx += 1

    best = R.select_best_candidate(candidates)
    debug["repair_rounds"] = round_idx
    debug["total_calls"] = len(calls)
    debug["structured_invocation_ceiling"] = 7
    if best is None:
        debug["accepted"] = False
        debug["validate_err"] = candidates[-1]["validate_err"] if candidates else "no candidate produced"
        if candidates and not any(c.get("semantic_verified") for c in candidates):
            debug["error"] = "no candidate obtained complete semantic verification"
        return None, debug

    debug["accepted"] = True
    debug["score"] = best["score"]
    debug["validate_err"] = None
    manifest = best["manifest"]
    manifest["_quality"] = best["score"]
    manifest["_semantic_verified"] = True
    return manifest, debug
