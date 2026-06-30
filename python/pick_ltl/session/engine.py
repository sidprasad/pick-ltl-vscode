from __future__ import annotations

import time

from ..ltl.spotutils import (
    generate_distinguishing_trace_pool,
    generate_two_distinguishing_words,
    is_trace_satisfied,
)
from ..services.final_result import build_final_result
from .models import CandidateFormulaState, SessionState, TraceClassification, TracePair


ELIMINATION_THRESHOLD = 2


def _is_finalizable(candidate: CandidateFormulaState) -> bool:
    """A candidate may be presented as the final formula only once the user has
    positively confirmed it — i.e. accepted at least one trace it matches.
    Surviving elimination alone (never being contradicted) is not enough: a
    formula the user only ever rejected examples *against* has never been shown
    to actually capture what they want."""
    return candidate.positive_votes >= 1


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
    if len(active) == 0:
        return _set_result(session, "No Candidate Survived", None, "All candidates were eliminated.", "no_result")
    if len(active) == 1 and (session.history or len(session.candidate_states) == 1):
        # Exactly one candidate remains — either the sole survivor of
        # elimination, or the only one we could build. It may only be presented
        # as the final formula once the user has positively confirmed it
        # (>=1 upvote). Until then, stay in voting so next_pair can show a
        # confirming example the user can accept.
        sole = active[0]
        if _is_finalizable(sole):
            return _finalize_sole(session, sole)
        session.mode = "voting"
        session.message = ""
        return session

    session.mode = "voting"
    session.message = ""
    return session


def _finalize_sole(session: SessionState, sole: CandidateFormulaState) -> SessionState:
    """Finalize the one remaining candidate. Keep the 'only one we could build'
    framing when the pool only ever held a single candidate."""
    if len(session.candidate_states) == 1:
        return _set_result(session, "We could only get this one.", sole, session.message or "We could only get this one.", "single_candidate")
    return _set_result(session, "Final Formula", sole, "One candidate remains consistent with your answers.", "final_result")


def _confirmation_pair(session: SessionState, sole: CandidateFormulaState) -> tuple[str, str] | None:
    """Two fresh, distinct traces to confirm the lone candidate: one it
    *accepts* (the upvote opportunity) shown first, paired with one it rejects.
    Returns None when no fresh accepted trace can be generated."""
    seen = [item.trace for item in session.history]
    try:
        words = [w for w in generate_two_distinguishing_words([sole.formula], excluded_words=seen) if w]
    except Exception:
        words = []
    if len(words) < 2:
        return None
    accepts = [w for w in words if sole.formula in _matching_candidates(w, [sole])]
    if not accepts:
        return None
    first = accepts[0]
    second = next((w for w in words if w != first), None)
    if not second:
        return None
    return first, second


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


def _select_best_candidate(session: SessionState) -> CandidateFormulaState | None:
    """The best-effort pick when we stop without fully converging: the live
    candidate the user has most *positively confirmed* — most upvotes, breaking
    ties toward the least-contradicted. Returns None when no surviving candidate
    has a confirming upvote yet (we won't crown a formula the user never accepted
    an example for). Falls back to the full pool only if every candidate is
    already eliminated (shouldn't happen on the staleness path, which runs with
    >=2 live candidates)."""
    pool = session.active_candidates() or session.candidate_states
    confirmed = [c for c in pool if c.positive_votes >= 1]
    if not confirmed:
        return None
    return max(confirmed, key=lambda c: (c.positive_votes, -c.negative_votes))


def _note_pair_progress(session: SessionState, active: list[CandidateFormulaState]) -> None:
    """Update the no-progress counter once per completed pair. A pair is *stale*
    only when it left the live candidate set exactly as it was — nothing
    eliminated. Any change resets the streak: an elimination (real progress), but
    also a reclassify that revives or swaps candidates (a correction, which must
    not be charged as another stale pair). The first call only seeds the
    baseline."""
    signature = sorted(candidate.formula for candidate in active)
    if session.last_active_signature is None:
        session.last_active_signature = signature
        return
    if signature == session.last_active_signature:
        session.pairs_without_progress += 1
    else:
        session.pairs_without_progress = 0
    session.last_active_signature = signature


def next_pair(session: SessionState) -> SessionState:
    active = session.active_candidates()
    _note_pair_progress(session, active)
    if len(active) == 0:
        return _set_result(session, "No Candidate Survived", None, "All candidates were eliminated.", "no_result")

    if len(active) == 1 and (session.history or len(session.candidate_states) == 1):
        sole = active[0]
        # Reaching a sole survivor is maximal progress; clear the stale counter so
        # repeated confirmation pairs (while we solicit an upvote) can't inflate it
        # and then trip the safety valve if the user later reopens >=2 candidates.
        session.pairs_without_progress = 0
        if _is_finalizable(sole):
            return _finalize_sole(session, sole)
        # Not yet confirmed: solicit an upvote with a trace the candidate accepts
        # (paired with one it rejects), rather than declaring it final unseen.
        confirm = _confirmation_pair(session, sole)
        if confirm is None:
            session.exhausted = True
            session.current_pair = None
            session.message = (
                "Couldn't generate an example to confirm the remaining formula. "
                "Add your own accepting trace, or pick it from the candidates."
            )
            return session
        trace1, trace2 = confirm
        session.mode = "voting"
        session.exhausted = False
        session.current_pair = TracePair(
            trace1=trace1,
            trace2=trace2,
            matches1=_matching_candidates(trace1, active),
            matches2=_matching_candidates(trace2, active),
        )
        return session

    # No-progress safety valve. SPOT can almost always hand us *another*
    # distinguishing pair, so "we ran out of questions" is rarely the thing that
    # stops us — the real signal is that the answers stopped narrowing the field.
    # After max_pairs_without_progress completed pairs with no elimination, stop
    # asking and surface the best match so far rather than looping indefinitely.
    if session.pairs_without_progress >= session.max_pairs_without_progress:
        best = _select_best_candidate(session)
        n = session.pairs_without_progress
        if best is not None:
            return _set_result(
                session,
                "Best match so far",
                best,
                f"We stopped narrowing: the last {n} comparisons ruled nothing out. "
                "This is the closest match to your answers — accept it, or revise your "
                "description to keep refining.",
                "final_result",
            )
        # No surviving candidate has a confirming example yet, so there's no
        # honest "best" to crown. Surface the standstill and let the user add an
        # accepting trace or pick a candidate.
        session.exhausted = True
        session.current_pair = None
        session.message = (
            f"We stopped narrowing: the last {n} comparisons ruled nothing out, and no "
            "candidate has an accepted example yet. Add a trace that should match, or pick "
            "a candidate below."
        )
        return session

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
