"""Candidate building: semantic deduplication and pool invariants."""

import pytest

pytest.importorskip("spot")

from pick_ltl.ltl.ltlnode import LTLNode
from pick_ltl.ltl.traceprocessor import getFormulaLiterals
from pick_ltl.services.candidate_builder import build_candidates
from pick_ltl.session.models import AtomSpec, SeedFormulaResult

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
