from __future__ import annotations

from .models import Match, PlanAction, PlanItem


def build_plan(matches: list[Match], *, confidence: float = 0.85) -> list[PlanItem]:
    # A download gets one decision. Close contenders are deliberately surfaced
    # for review rather than turning a ranking accident into an import.
    grouped: dict[str, list[Match]] = {}
    for match in matches:
        grouped.setdefault(match.download.id, []).append(match)
    plan: list[PlanItem] = []
    for download_matches in grouped.values():
        ranked = sorted(download_matches, key=lambda item: item.score, reverse=True)
        match = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None
        if match.score >= confidence and (
            runner_up is None or match.score - runner_up.score >= 0.10
        ):
            explanation = (
                f"clear match for {match.candidate.title} ({match.score:.2f}); "
                + "; ".join(match.reasons)
            )
            plan.append(PlanItem(PlanAction.IMPORT, match, explanation, True))
        elif match.score >= 0.25:
            contender = (
                f"; next candidate {runner_up.candidate.title} ({runner_up.score:.2f})"
                if runner_up
                else ""
            )
            explanation = (
                f"ambiguous match for {match.candidate.title} ({match.score:.2f})"
                f"{contender}; review candidates and provenance"
            )
            plan.append(PlanItem(PlanAction.REVIEW, match, explanation, False))
        else:
            plan.append(
                PlanItem(PlanAction.SKIP, match, "confidence below matching threshold", False)
            )
    return plan
