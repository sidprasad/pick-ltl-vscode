from __future__ import annotations

import random
from contextlib import contextmanager

from ..ltl.ltlnode import LTLNode, parse_ltl_string
from ..ltl.spotutils import generate_distinguishing_words, is_degenerate, is_trace_satisfied
from ..ltl.traceprocessor import getFormulaLiterals
from ..mutation.ranking import rank_formulas
from ..mutation.semantic import MisconceptionCode, getAllApplicableMisconceptions
from ..mutation.syntactic import applyRandomMutationNotEquivalentTo
from ..session.models import CandidateFormulaState, CandidateOrigin, SeedFormulaResult, SessionState


MUTATION_EXPLANATIONS = {
    MisconceptionCode.Precedence.value: "Groups one part of the rule differently from the main interpretation.",
    MisconceptionCode.BadStateIndex.value: "Shifts when a sub-rule is expected to happen.",
    MisconceptionCode.BadStateQuantification.value: "Changes whether part of the property is meant to hold always or eventually.",
    MisconceptionCode.ExclusiveU.value: "Treats the until-condition as more exclusive than the seed interpretation.",
    MisconceptionCode.ImplicitF.value: "Drops an eventuality requirement from the seed interpretation.",
    MisconceptionCode.ImplicitG.value: "Drops an always/for-all-future requirement from the seed interpretation.",
    MisconceptionCode.OtherImplicit.value: "Under-constrains the seed interpretation by removing part of the temporal structure.",
    MisconceptionCode.WeakU.value: "Reads an until-condition as if the right side may never need to happen.",
}
SYNTACTIC_MUTATION_DEVIATION = "Operator-level variant of the seed interpretation."
DEFAULT_ELIMINATION_THRESHOLD = 2


def _mutation_explanation(seed: SeedFormulaResult, deviation: str) -> str:
    """Explanation for a mutation-derived candidate: the seed's own text (what
    interpretation it deviates from) followed by how this candidate deviates."""
    base = (seed.explanation or "").strip() or seed.formula
    if not base:
        return deviation
    return f"{base.rstrip('. ')}. {deviation}"


@contextmanager
def deterministic_random(seed: str):
    state = random.getstate()
    random.seed(seed)
    try:
        yield
    finally:
        random.setstate(state)


def _is_degenerate(formula: str) -> bool:
    """is_degenerate, but never raises — on any SPOT error we keep the candidate
    (a spurious survivor is less harmful than silently losing a valid formula)."""
    try:
        return is_degenerate(formula)
    except Exception:
        return False


def _normalize_formula(formula: str, allowed_atoms: set[str]) -> str | None:
    try:
        normalized = str(parse_ltl_string(formula))
    except Exception:
        return None

    if allowed_atoms and not set(getFormulaLiterals(normalized)).issubset(allowed_atoms):
        return None

    # Drop mutants whose language is empty (unsatisfiable) or universal
    # (tautology). They accept nothing / everything, so no answer ever
    # contradicts them — an unsatisfiable mutant in particular survives every
    # "reject" classification as a phantom "perfect" candidate and starves the
    # distinguishing-trace search.
    if _is_degenerate(normalized):
        return None

    return normalized


def drop_degenerate_candidate_states(
    candidate_states: list[CandidateFormulaState],
) -> list[CandidateFormulaState]:
    """Remove candidates whose language is empty (unsatisfiable) or universal
    (tautology). Used at every entry point — freshly built pools *and* imported
    sessions — so a degenerate formula never enters the distinguishing loop."""
    return [c for c in candidate_states if not _is_degenerate(c.formula)]


def _is_equivalent(formula: str, existing: list[str]) -> bool:
    for other in existing:
        try:
            if LTLNode.equiv(formula, other):
                return True
        except Exception:
            # If SPOT cannot decide equivalence for this pair, keep both rather
            # than crash the whole candidate build. A spurious near-duplicate is
            # far less harmful than losing the entire pool.
            continue
    return False


def _count_distinguishing_witnesses(formula1: str, formula2: str, limit: int = DEFAULT_ELIMINATION_THRESHOLD) -> int:
    """Count DISTINCT traces that distinguish the two formulas, up to `limit`.

    Only counts a witness when SPOT confirms it separates them (`match1 !=
    match2`), so it never *over*-counts — the result is a lower bound on the true
    number of distinguishing words. That direction is the safe one: the
    elimination threshold derived from it is never set higher than the formulas
    can actually witness.
    """
    excluded: list[str] = []
    distinguishing: list[str] = []

    for _ in range(limit):
        try:
            witness_a, witness_b = generate_distinguishing_words(formula1, formula2, exclude=excluded)
        except Exception:
            break

        progress = False
        for witness in (witness_a, witness_b):
            if not witness or witness in excluded:
                continue
            excluded.append(witness)
            try:
                match1 = is_trace_satisfied(witness, formula1)
                match2 = is_trace_satisfied(witness, formula2)
            except Exception:
                continue
            if match1 != match2:
                distinguishing.append(witness)
                progress = True
                if len(distinguishing) >= limit:
                    return limit
        if not progress:
            break

    return len(distinguishing)


def _assign_dynamic_thresholds(candidates: list[CandidateFormulaState], default_threshold: int = DEFAULT_ELIMINATION_THRESHOLD) -> None:
    """Set the elimination threshold to the **minimum number of distinguishing
    words between any two candidates** (capped at `default_threshold`, floored
    at 1), shared by all candidates.

    A candidate is eliminated after this many contradicting classifications.
    Requiring more contradictions tolerates more user mislabels, but we can never
    require more than the *closest* pair of candidates can actually witness —
    otherwise that pair could never be resolved and the loop would stall. So the
    threshold is the smallest pairwise distinguishing-word count (each counted up
    to the cap). Equivalent pairs (count 0) cannot occur after dedup and are
    ignored defensively. Mirrors pick-regex.
    """
    for candidate in candidates:
        candidate.elimination_threshold = default_threshold
    if len(candidates) < 2:
        return

    threshold = default_threshold
    for index, candidate in enumerate(candidates):
        for other in candidates[index + 1:]:
            count = _count_distinguishing_witnesses(candidate.formula, other.formula, limit=default_threshold)
            if count >= 1:
                threshold = min(threshold, count)

    threshold = max(1, threshold)
    for candidate in candidates:
        candidate.elimination_threshold = threshold


def _merge_atoms(seeds: list[SeedFormulaResult]) -> list:
    merged = []
    seen = set()
    for seed in seeds:
        for atom in seed.atoms:
            if atom.name in seen:
                continue
            merged.append(atom)
            seen.add(atom.name)
    return merged


def build_candidates(seeds: list[SeedFormulaResult]) -> list[CandidateFormulaState]:
    if not seeds:
        return []

    allowed_atoms = {atom.name for atom in _merge_atoms(seeds)}
    candidates: list[CandidateFormulaState] = []
    seen_formulas: list[str] = []

    for seed in seeds:
        if seed.formula in seen_formulas or _is_equivalent(seed.formula, seen_formulas):
            continue
        # Drop a seed whose language is empty (unsatisfiable) or universal
        # (tautology) right at the start: it accepts nothing / everything, so it
        # can never be eliminated and only pollutes the pool. Mutants are caught
        # later by _normalize_formula; seeds are caught here.
        if _is_degenerate(seed.formula):
            continue
        candidates.append(
            CandidateFormulaState(
                formula=seed.formula,
                explanation=seed.explanation,
                origin=CandidateOrigin(kind="seed"),
            )
        )
        seen_formulas.append(seed.formula)

    for seed in seeds:
        node = parse_ltl_string(seed.formula)
        semantic_pool: list[dict] = []

        with deterministic_random(seed.formula):
            for result in getAllApplicableMisconceptions(node):
                formula = _normalize_formula(str(result.node), allowed_atoms)
                if not formula or formula in seen_formulas or _is_equivalent(formula, seen_formulas):
                    continue
                code = result.misconception.value
                deviation = MUTATION_EXPLANATIONS.get(code, "Conceptual variant of the seed interpretation.")
                semantic_pool.append(
                    {
                        "formula": formula,
                        "explanation": _mutation_explanation(seed, deviation),
                        "origin": CandidateOrigin(kind="semantic_mutation", misconception_code=code),
                    }
                )

        for item in rank_formulas(seed.formula, semantic_pool):
            if item["formula"] in seen_formulas or _is_equivalent(item["formula"], seen_formulas):
                continue
            seen_formulas.append(item["formula"])
            candidates.append(
                CandidateFormulaState(
                    formula=item["formula"],
                    explanation=item["explanation"],
                    origin=item["origin"],
                )
            )

    if len(candidates) < 2:
        for seed in seeds:
            node = parse_ltl_string(seed.formula)
            existing_nodes = [parse_ltl_string(candidate.formula) for candidate in candidates]
            attempts = 0
            while len(candidates) < 2 and attempts < 64:
                attempts += 1
                with deterministic_random(f"{seed.formula}:{attempts}"):
                    mutated = applyRandomMutationNotEquivalentTo(node, existing_nodes, maxAttempts=32)
                if mutated is None:
                    continue
                formula = _normalize_formula(str(mutated), allowed_atoms)
                if not formula or formula in seen_formulas or _is_equivalent(formula, seen_formulas):
                    continue
                seen_formulas.append(formula)
                existing_nodes.append(parse_ltl_string(formula))
                candidates.append(
                    CandidateFormulaState(
                        formula=formula,
                        explanation=_mutation_explanation(seed, SYNTACTIC_MUTATION_DEVIATION),
                        origin=CandidateOrigin(kind="syntactic_mutation", misconception_code=None),
                    )
                )

    _assign_dynamic_thresholds(candidates)
    return candidates


def create_initial_session(prompt: str, provider: dict, seeds: list[SeedFormulaResult]) -> SessionState:
    candidates = build_candidates(seeds)
    mode = "voting"
    message = ""
    if len(candidates) == 1:
        mode = "single_candidate"
        message = "We could only get this one."

    primary_seed = seeds[0] if seeds else None
    warnings: list[str] = []
    for seed in seeds:
        warnings.extend(seed.warnings)
    warnings = list(dict.fromkeys(warnings))

    return SessionState(
        prompt=prompt,
        provider=provider,
        seed=primary_seed,
        seeds=seeds,
        candidate_states=candidates,
        warnings=warnings,
        mode=mode,
        message=message,
    )
