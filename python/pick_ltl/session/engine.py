from __future__ import annotations

import time

from ..ltl.spotutils import generate_two_distinguishing_words, is_trace_satisfied
from ..services.final_result import build_final_result
from ..services.seed_generation import generate_seed_formulas
from ..services.candidate_builder import create_initial_session
from .models import CandidateFormulaState, SessionState, TraceClassification, TracePair


ELIMINATION_THRESHOLD = 2


def _matching_candidates(trace: str, candidates: list[CandidateFormulaState]) -> list[str]:
    matches = []
    for candidate in candidates:
        try:
            if is_trace_satisfied(trace, candidate.formula):
                matches.append(candidate.formula)
        except Exception:
            continue
    return matches


def _reset_candidates(session: SessionState) -> None:
    for candidate in session.candidate_states:
        candidate.positive_votes = 0
        candidate.negative_votes = 0
        candidate.eliminated = False


def _apply_history_item(candidates: list[CandidateFormulaState], item: TraceClassification) -> None:
    matches = _matching_candidates(item.trace, candidates)
    item.matching_candidates = matches

    if item.classification == "unsure":
        return

    for candidate in candidates:
        does_match = candidate.formula in matches
        contradiction = (item.classification == "accept" and not does_match) or (
            item.classification == "reject" and does_match
        )
        if contradiction:
            candidate.negative_votes += 1
            threshold = candidate.elimination_threshold or ELIMINATION_THRESHOLD
            if candidate.negative_votes >= threshold:
                candidate.eliminated = True
        elif item.classification == "accept" and does_match:
            candidate.positive_votes += 1


def _set_result(session: SessionState, title: str, candidate: CandidateFormulaState | None, message: str, mode: str) -> SessionState:
    session.mode = mode
    session.message = message
    session.current_pair = None
    session.final_result = build_final_result(candidate, title=title, message=message)
    return session


def _recalculate_session(session: SessionState) -> SessionState:
    _reset_candidates(session)
    session.current_pair = None
    session.final_result = None
    session.exhausted = False

    for item in session.history:
        _apply_history_item(session.candidate_states, item)

    active = session.active_candidates()
    if len(session.candidate_states) == 1 and session.mode == "single_candidate":
        candidate = session.candidate_states[0]
        return _set_result(session, "We could only get this one.", candidate, session.message or "We could only get this one.", "single_candidate")
    if len(active) == 0:
        return _set_result(session, "No Candidate Survived", None, "All candidates were eliminated.", "no_result")
    if len(active) == 1 and active[0].positive_votes >= 1:
        return _set_result(session, "Final Formula", active[0], "One candidate remains with supporting evidence.", "final_result")

    session.mode = "voting"
    session.message = ""
    return session


def next_pair(session: SessionState) -> SessionState:
    active = session.active_candidates()
    if len(active) == 0:
        return _set_result(session, "No Candidate Survived", None, "All candidates were eliminated.", "no_result")

    if session.mode == "single_candidate":
        return _set_result(session, "We could only get this one.", active[0], session.message or "We could only get this one.", "single_candidate")

    if len(active) == 1 and active[0].positive_votes >= 1:
        return _set_result(session, "Final Formula", active[0], "One candidate remains with supporting evidence.", "final_result")

    try:
        trace1, trace2 = generate_two_distinguishing_words(
            [candidate.formula for candidate in active],
            excluded_words=[item.trace for item in session.history],
        )
    except Exception:
        session.exhausted = True
        session.current_pair = None
        session.message = "Unable to generate more distinguishing traces. You can add your own traces or pick one of the remaining candidates."
        return session

    session.exhausted = False
    session.current_pair = TracePair(
        trace1=trace1,
        trace2=trace2,
        matches1=_matching_candidates(trace1, active),
        matches2=_matching_candidates(trace2, active),
    )
    return session


def classify_trace(session: SessionState, trace: str, classification: str, source: str = "pair") -> SessionState:
    if classification not in {"accept", "reject", "unsure"}:
        raise ValueError("Classification must be one of: accept, reject, unsure.")

    matches = _matching_candidates(trace, session.candidate_states)
    session.history.append(
        TraceClassification(
            trace=trace,
            classification=classification,
            matching_candidates=matches,
            source=source,
            timestamp=int(time.time() * 1000),
        )
    )
    return _recalculate_session(session)


def reclassify_trace(session: SessionState, history_index: int, classification: str) -> SessionState:
    if classification not in {"accept", "reject", "unsure"}:
        raise ValueError("Classification must be one of: accept, reject, unsure.")
    if history_index < 0 or history_index >= len(session.history):
        raise ValueError("History index is out of bounds.")

    session.history[history_index].classification = classification
    session.history[history_index].timestamp = int(time.time() * 1000)
    return _recalculate_session(session)


def add_manual_examples(session: SessionState, accept_traces: list[str], reject_traces: list[str]) -> SessionState:
    for trace in [item.strip() for item in accept_traces if item.strip()]:
        session = classify_trace(session, trace, "accept", source="manual")
    for trace in [item.strip() for item in reject_traces if item.strip()]:
        session = classify_trace(session, trace, "reject", source="manual")
    return session


def finalize_session(session: SessionState, formula: str | None = None) -> SessionState:
    candidate = None
    if formula:
        candidate = next((item for item in session.candidate_states if item.formula == formula), None)
    if candidate is None:
        active = session.active_candidates()
        candidate = active[0] if active else None
    return _set_result(session, "Final Formula" if formula else session.final_result.title if session.final_result else "Final Formula", candidate, session.message, "final_result")


def refine_session(session: SessionState, new_prompt: str) -> SessionState:
    seeds = generate_seed_formulas(new_prompt, session.provider)
    refined = create_initial_session(new_prompt, session.provider, seeds)
    for item in session.history:
        refined = classify_trace(refined, item.trace, item.classification, source=item.source)
    return refined
