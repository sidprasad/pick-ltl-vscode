"""HTTP route behavior for the stateless PICK backend."""

import pytest

pytest.importorskip("spot")

from pick_ltl.app import create_app


def _session_with(formulas):
    return {
        "version": 1,
        "prompt": "p",
        "provider": {},
        "seed": None,
        "seeds": [],
        "candidate_states": [
            {
                "formula": f,
                "explanation": "",
                "origin": {"kind": "seed", "misconception_code": None},
                "confidence": None,
                "equivalents": [],
                "positive_votes": 0,
                "negative_votes": 0,
                "elimination_threshold": 2,
                "eliminated": False,
            }
            for f in formulas
        ],
        "history": [],
        "mode": "voting",
        "warnings": [],
        "current_pair": None,
        "final_result": None,
        "exhausted": False,
        "message": "",
    }


@pytest.fixture
def client():
    return create_app().test_client()


def test_import_drops_degenerate_candidates(client):
    # `G(e <-> F(!e))` is unsatisfiable: it rejects every trace and would survive
    # every "reject" answer as a phantom candidate. Import must strip it while
    # keeping the satisfiable one.
    resp = client.post(
        "/api/session/import",
        json={"session": _session_with(["G((e <-> X(!e)) & !(e & h))", "G(e <-> F(!e))"])},
    )
    assert resp.status_code == 200
    formulas = [c["formula"] for c in resp.get_json()["candidate_states"]]
    assert len(formulas) == 1
    assert "F(!e)" not in formulas[0]


def test_import_keeps_satisfiable_candidates(client):
    formulas_in = ["F(a)", "G(a -> X(b))"]
    resp = client.post("/api/session/import", json={"session": _session_with(formulas_in)})
    assert resp.status_code == 200
    formulas_out = [c["formula"] for c in resp.get_json()["candidate_states"]]
    assert len(formulas_out) == len(formulas_in)
