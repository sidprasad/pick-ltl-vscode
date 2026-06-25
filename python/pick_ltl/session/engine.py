from __future__ import annotations

import time

from ..ltl.spotutils import generate_distinguishing_trace_pool, is_trace_satisfied
from ..services.final_result import build_final_result
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
    if len(active) == 1 and session.history:
        # Sole survivor of the elimination process: it is the one candidate
        # consistent with every answer so far. Finalize regardless of whether a
        # shown trace happened to land on its accept side (positive_votes) — with
        # one candidate left there is nothing further to distinguish.
        return _set_result(session, "Final Formula", active[0], "One candidate remains consistent with your answers.", "final_result")

    session.mode = "voting"
    session.message = ""
    return session


def _trace_signature(trace: str, candidates: list[CandidateFormulaState]) -> tuple[bool, ...]:
    """The acceptance signature of a trace: which active candidates accept it.
    Two traces with the same signature pose the *same* distinguishing question."""
    matches = set(_matching_candidates(trace, candidates))
    return tuple(candidate.formula in matches for candidate in candidates)


def _is_informative(signature: tuple[bool, ...]) -> bool:
    """A trace is informative iff it splits the active candidates — accepted by
    at least one and rejected by at least one. A trace accepted (or rejected) by
    *every* candidate cannot, on its own, eliminate a proper subset."""
    return any(signature) and not all(signature)


def _select_distinguishing_pair(
    pool: list[str],
    active: list[CandidateFormulaState],
    asked_signatures: set[tuple[bool, ...]],
) -> tuple[str, str] | None:
    """Pick two traces whose acceptance signatures are *distinct* and
    *informative* (each splits the active candidates). Both traces come from a
    pool that already excludes every previously-shown trace string, so we never
    repeat a trace and never emit a duplicate (trace1 == trace2) or
    non-distinguishing pair.

    The first trace always has an *informative* signature (it does the actual
    elimination work). The second has a different signature (so the pair is
    distinguishing and the two traces are never identical). When a second
    informative split exists we use it; otherwise — e.g. when the active
    candidates form a subsumption chain and only one informative partition
    exists — we show the lone discriminator alongside a trace accepted by *none*
    of the candidates (a clear "obviously-out" example). We *prefer* signatures
    not yet asked, falling back to a re-worded previously-asked partition so the
    elimination-threshold votes can still accumulate. Returns None only when no
    informative signature exists or fewer than two distinct signatures are
    available (then the caller exhausts).
    """
    by_signature: dict[tuple[bool, ...], str] = {}
    for trace in pool:
        signature = _trace_signature(trace, active)
        by_signature.setdefault(signature, trace)

    informative = [sig for sig in by_signature if _is_informative(sig)]
    if not informative or len(by_signature) < 2:
        return None

    def balance(sig: tuple[bool, ...]) -> int:
        accepts = sum(sig)
        return min(accepts, len(sig) - accepts)

    def hamming(a: tuple[bool, ...], b: tuple[bool, ...]) -> int:
        return sum(x != y for x, y in zip(a, b))

    # First trace: an informative signature, preferring fresh then balanced.
    informative.sort(key=lambda s: (s not in asked_signatures, balance(s)), reverse=True)
    first = informative[0]
    # Second trace: prefer fresh, then another informative split; failing that a
    # trace accepted by none (safe negative example); then most different.
    second = max(
        (s for s in by_signature if s != first),
        key=lambda s: (
            s not in asked_signatures,
            _is_informative(s),
            not any(s),  # accepted-by-none: the clean "obviously-out" partner
            hamming(first, s),
        ),
    )
    return by_signature[first], by_signature[second]


def next_pair(session: SessionState) -> SessionState:
    active = session.active_candidates()
    if len(active) == 0:
        return _set_result(session, "No Candidate Survived", None, "All candidates were eliminated.", "no_result")

    if session.mode == "single_candidate":
        return _set_result(session, "We could only get this one.", active[0], session.message or "We could only get this one.", "single_candidate")

    if len(active) == 1 and session.history:
        return _set_result(session, "Final Formula", active[0], "One candidate remains consistent with your answers.", "final_result")

    seen_strings = [item.trace for item in session.history]
    # Questions already posed, as signatures over the *current* active set.
    asked_signatures = {_trace_signature(item.trace, active) for item in session.history}

    try:
        pool = generate_distinguishing_trace_pool(
            [candidate.formula for candidate in active],
            excluded=seen_strings,
        )
    except Exception:
        pool = []

    chosen = _select_distinguishing_pair(pool, active, asked_signatures)
    if chosen is None:
        session.exhausted = True
        session.current_pair = None
        session.message = "Unable to generate more distinguishing traces. You can add your own traces or pick one of the remaining candidates."
        return session

    trace1, trace2 = chosen
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
