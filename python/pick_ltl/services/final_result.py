from __future__ import annotations

from ..ltl.ltlnode import parse_ltl_string
from ..ltl.spotutils import generate_two_distinguishing_words, is_trace_satisfied
from ..session.models import CandidateFormulaState, FinalResult


def _safe_english(formula: str) -> str:
    try:
        return parse_ltl_string(formula).__to_english__()
    except Exception:
        return ""


def build_final_result(
    candidate: CandidateFormulaState | None,
    title: str,
    message: str = "",
) -> FinalResult:
    if candidate is None:
        return FinalResult(
            title=title,
            formula=None,
            explanation="",
            english="",
            examples_in=[],
            examples_out=[],
            message=message,
        )

    examples_in: list[str] = []
    examples_out: list[str] = []
    try:
        sample_traces = generate_two_distinguishing_words([candidate.formula], [])
        for trace in sample_traces:
            if is_trace_satisfied(trace, candidate.formula):
                examples_in.append(trace)
            else:
                examples_out.append(trace)
    except Exception:
        pass

    return FinalResult(
        title=title,
        formula=candidate.formula,
        explanation=candidate.explanation,
        english=_safe_english(candidate.formula),
        examples_in=examples_in,
        examples_out=examples_out,
        message=message,
    )

