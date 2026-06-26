"""Candidate building: semantic deduplication and pool invariants."""

import pytest

pytest.importorskip("spot")

from pick_ltl.ltl.ltlnode import LTLNode
from pick_ltl.ltl.spotutils import is_degenerate
from pick_ltl.ltl.traceprocessor import getFormulaLiterals
from pick_ltl.services.candidate_builder import (
    MUTATION_EXPLANATIONS,
    SYNTACTIC_MUTATION_DEVIATION,
    build_candidates,
    create_initial_session,
    drop_degenerate_candidate_states,
)
from pick_ltl.session.models import AtomSpec, CandidateFormulaState, CandidateOrigin, SeedFormulaResult

VALID_ORIGINS = {"seed", "semantic_mutation", "syntactic_mutation"}


def seed(formula, atoms):
    return SeedFormulaResult(
        formula=formula,
        explanation="",
        atoms=[AtomSpec(name=a, meaning=a) for a in atoms],
        warnings=[],
    )


def _seed_origin_formulas(candidates):
    return [c.formula for c in candidates if c.origin.kind == "seed"]


def test_identical_seeds_collapse_to_one():
    candidates = build_candidates([seed("F(a)", ["a"]), seed("F(a)", ["a"])])
    assert len(_seed_origin_formulas(candidates)) == 1


def test_semantically_equivalent_seeds_collapse():
    # F(F(a)) is logically equivalent to F(a); only one should seed the pool.
    candidates = build_candidates([seed("F(a)", ["a"]), seed("F(F(a))", ["a"])])
    assert len(_seed_origin_formulas(candidates)) == 1


def test_distinct_seeds_both_survive():
    candidates = build_candidates([seed("F(a)", ["a"]), seed("G(a)", ["a"])])
    seeds_present = _seed_origin_formulas(candidates)
    assert len(seeds_present) == 2
    # Neither pair of seed candidates is equivalent.
    assert not LTLNode.equiv(seeds_present[0], seeds_present[1])


@pytest.mark.parametrize(
    "formula,atoms",
    [
        ("G(r -> F(b))", ["r", "b"]),
        ("F(g)", ["g"]),
        ("G(a -> X(b))", ["a", "b"]),
        ("a U b", ["a", "b"]),
    ],
)
def test_pool_is_pairwise_semantically_distinct(formula, atoms):
    """The core dedup invariant: no two produced candidates are SPOT-equivalent."""
    candidates = build_candidates([seed(formula, atoms)])
    formulas = [c.formula for c in candidates]
    for i in range(len(formulas)):
        for j in range(i + 1, len(formulas)):
            assert not LTLNode.equiv(formulas[i], formulas[j]), (
                f"equivalent candidates survived dedup: {formulas[i]} <=> {formulas[j]}"
            )


def test_unsatisfiable_seed_is_dropped():
    # `G(a <-> F(!a))` is unsatisfiable; it must never enter the pool, even
    # though it is the seed. The satisfiable seed alongside it survives.
    candidates = build_candidates(
        [seed("G(a <-> F(!a))", ["a"]), seed("F(a)", ["a"])]
    )
    formulas = [c.formula for c in candidates]
    assert formulas, "expected a non-empty pool from the satisfiable seed"
    assert not any(is_degenerate(f) for f in formulas), formulas
    assert any(LTLNode.equiv(f, "F(a)") for f in formulas)


def _cand(formula):
    return CandidateFormulaState(formula=formula, explanation="", origin=CandidateOrigin(kind="seed"))


def test_drop_degenerate_candidate_states_filters_unparseable_unsat_and_tautology():
    # Mirrors what the import route does: strip formulas that don't parse, plus
    # empty/universal languages; keep the real ones.
    states = [
        _cand("G(a -> "),           # malformed
        _cand("G(a <-> F(!a))"),    # unsatisfiable
        _cand("G(a | !a)"),         # tautology
        _cand("F(a)"),
        _cand("G(a -> X(b))"),
    ]
    kept = [c.formula for c in drop_degenerate_candidate_states(states)]
    assert kept == ["F(a)", "G(a -> X(b))"]


def test_malformed_seed_does_not_abort_build():
    # A single malformed formula from the model must not crash the build; the
    # valid seed still yields a usable pool.
    candidates = build_candidates([seed("G(a ->", ["a", "b"]), seed("G(a -> F(b))", ["a", "b"])])
    formulas = [c.formula for c in candidates]
    assert formulas, "valid seed should still produce candidates"
    assert any(LTLNode.equiv(f, "G(a -> F(b))") for f in formulas)
    assert all("G(a ->" != f for f in formulas), "malformed seed must not enter the pool"


def test_all_malformed_seeds_yields_empty_pool_without_raising():
    assert build_candidates([seed("F(", ["a"]), seed("a & & b", ["a", "b"])]) == []


def test_create_initial_session_flags_skipped_malformed_seeds():
    session = create_initial_session(
        "p", {}, [seed("G(a ->", ["a", "b"]), seed("G(a -> F(b))", ["a", "b"])]
    )
    assert session.candidate_states, "valid seed should survive"
    assert any("not valid LTL" in w for w in session.warnings)


def test_create_initial_session_all_malformed_is_no_result():
    session = create_initial_session("p", {}, [seed("F(", ["a"])])
    assert session.candidate_states == []
    assert session.mode == "no_result"
    assert session.message


# The model can return perfectly well-formed JSON whose `formula` field is not
# valid LTL. These cases exercise that path with the kind of garbage models
# actually emit:
#   "G a &"     -> trailing binary operator with no right operand
#   "XXX (b))"  -> unbalanced parenthesis (note: "XXX(b)" alone is VALID — three
#                  nested Next operators — so the rejection is purely structural)
WELLFORMED_JSON_BAD_FORMULA = [
    ("G a &", ["a", "b"]),
    ("XXX (b))", ["a", "b"]),
]


@pytest.mark.parametrize("bad_formula,atoms", WELLFORMED_JSON_BAD_FORMULA)
def test_malformed_formula_in_valid_json_is_skipped_not_fatal(bad_formula, atoms):
    # A malformed formula riding in otherwise-valid JSON is parsed-and-skipped; it
    # never enters the pool, and a valid sibling seed still yields candidates.
    candidates = build_candidates([seed(bad_formula, atoms), seed("G(a -> F(b))", atoms)])
    formulas = [c.formula for c in candidates]
    assert formulas, "valid sibling seed should still yield a pool"
    assert any(LTLNode.equiv(f, "G(a -> F(b))") for f in formulas)
    assert bad_formula not in formulas, "malformed formula must not enter the pool"


def test_skipped_warning_reports_partial_count():
    # One of two interpretations is malformed: the warning names the count so the
    # user understands why the pool is smaller than the model's answer.
    session = create_initial_session(
        "p", {}, [seed("G a &", ["a", "b"]), seed("G(a -> F(b))", ["a", "b"])]
    )
    assert session.candidate_states, "valid seed should survive"
    warning = next((w for w in session.warnings if "not valid LTL" in w), None)
    assert warning is not None, session.warnings
    assert "1 of 2" in warning
    assert "was not valid LTL" in warning


def test_all_malformed_example_formulas_yield_no_result_with_full_count():
    session = create_initial_session(
        "p", {}, [seed("G a &", ["a"]), seed("XXX (b))", ["b"])]
    )
    assert session.candidate_states == []
    assert session.mode == "no_result"
    assert session.message
    warning = next((w for w in session.warnings if "not valid LTL" in w), None)
    assert warning is not None, session.warnings
    assert "2 of 2" in warning
    assert "were not valid LTL" in warning


def test_no_candidate_is_degenerate():
    # No produced candidate may be unsatisfiable or a tautology: such a formula
    # accepts nothing / everything, so it can never be eliminated and stalls the
    # distinguishing loop. Exercises seeds known to spawn an unsatisfiable
    # semantic mutant (e.g. `G(e <-> F(!e))`).
    seeds = [
        seed("G((e <-> X(!e)) & !(e & h))", ["e", "h"]),
        seed("G(a -> X(b))", ["a", "b"]),
        seed("F(a <-> X(!a))", ["a"]),
    ]
    candidates = build_candidates(seeds)
    degenerate = [c.formula for c in candidates if is_degenerate(c.formula)]
    assert not degenerate, f"degenerate candidates survived: {degenerate}"


def test_allowed_atoms_pins_alphabet_on_refine():
    # With the proposition set pinned (as refine does), a seed that introduces a
    # new proposition is dropped, and no produced candidate references it — so
    # earlier classifications (traces over the original atoms) stay meaningful.
    seeds = [
        seed("G(a -> X(b))", ["a", "b", "c"]),
        seed("G(a -> c)", ["a", "b", "c"]),
    ]
    candidates = build_candidates(seeds, allowed_atoms={"a", "b"})
    formulas = [c.formula for c in candidates]
    assert any(LTLNode.equiv(f, "G(a -> X(b))") for f in formulas), formulas
    for c in candidates:
        assert "c" not in getFormulaLiterals(c.formula), c.formula


def test_initial_build_does_not_drop_seeds_by_atoms():
    # Without an explicit allowed_atoms (initial build), the alphabet is derived
    # from the seeds and seeds are not dropped for their own literals.
    candidates = build_candidates([seed("G(a -> c)", ["a", "c"])])
    assert any(LTLNode.equiv(f.formula, "G(a -> c)") for f in candidates)


def test_candidates_use_only_seed_atoms():
    atoms = {"r", "b"}
    candidates = build_candidates([seed("G(r -> F(b))", list(atoms))])
    for c in candidates:
        assert set(getFormulaLiterals(c.formula)).issubset(atoms), c.formula


def test_every_candidate_has_positive_threshold_and_valid_origin():
    candidates = build_candidates([seed("G(r -> F(b))", ["r", "b"])])
    assert candidates, "expected at least one candidate"
    for c in candidates:
        assert c.elimination_threshold >= 1
        assert c.origin.kind in VALID_ORIGINS


def test_seed_formula_is_present_in_pool():
    candidates = build_candidates([seed("G(r -> F(b))", ["r", "b"])])
    assert any(LTLNode.equiv(c.formula, "G(r -> F(b))") for c in candidates)


def test_mutation_explanations_combine_seed_text_and_misconception():
    seed_text = "whenever r holds, b holds eventually"
    seeds = [
        SeedFormulaResult(
            formula="G(r -> F(b))",
            explanation=seed_text,
            atoms=[AtomSpec("r", "r"), AtomSpec("b", "b")],
            warnings=[],
        )
    ]
    candidates = build_candidates(seeds)

    # The seed candidate keeps its own text verbatim.
    seed_candidate = next(c for c in candidates if c.origin.kind == "seed")
    assert seed_candidate.explanation == seed_text

    mutations = [c for c in candidates if c.origin.kind in ("semantic_mutation", "syntactic_mutation")]
    assert mutations, "expected at least one mutation-derived candidate"
    for c in mutations:
        # Leads with the seed's text (what this candidate is a deviation of)...
        assert c.explanation.startswith(seed_text.rstrip(". ")), c.explanation
        # ...then appends the deviation description.
        assert len(c.explanation) > len(seed_text)
        if c.origin.kind == "semantic_mutation" and c.origin.misconception_code in MUTATION_EXPLANATIONS:
            assert MUTATION_EXPLANATIONS[c.origin.misconception_code] in c.explanation
        if c.origin.kind == "syntactic_mutation":
            assert SYNTACTIC_MUTATION_DEVIATION in c.explanation
