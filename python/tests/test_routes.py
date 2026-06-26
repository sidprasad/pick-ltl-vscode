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


def _seed(formula, atoms):
    return {
        "formula": formula,
        "explanation": "",
        "atoms": [{"name": a, "meaning": a} for a in atoms],
    }


def test_build_does_not_500_on_malformed_seed(client):
    # A malformed model formula must not blow up the build route (it used to
    # surface as an LTLParseError -> HTTP 400). The valid seed still yields a pool.
    resp = client.post(
        "/api/candidates/build",
        json={"prompt": "p", "seeds": [_seed("G(a ->", ["a", "b"]), _seed("G(a -> F(b))", ["a", "b"])]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["candidate_states"], "expected candidates from the valid seed"
    assert any("not valid LTL" in w for w in body["warnings"])


def test_build_all_malformed_seeds_is_no_result(client):
    resp = client.post(
        "/api/candidates/build",
        json={"prompt": "p", "seeds": [_seed("F(", ["a"])]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["candidate_states"] == []
    assert body["mode"] == "no_result"


def _voting_session():
    return _session_with(["G(a -> F(b))"])


def test_classify_invalid_classification_is_400_not_500(client):
    # A bad classification value is client error, not a server crash. It used to
    # raise an uncaught ValueError -> HTTP 500 with a traceback.
    resp = client.post(
        "/api/session/classify",
        json={"session": _voting_session(), "trace": "a;cycle{a}", "classification": "banana"},
    )
    assert resp.status_code == 400
    assert "classification" in resp.get_json()["error"].lower()


def test_reclassify_out_of_range_index_is_400_not_500(client):
    resp = client.post(
        "/api/session/reclassify",
        json={"session": _voting_session(), "history_index": 99, "classification": "accept"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]


def test_unknown_route_stays_404(client):
    # The catch-all error handler must not turn HTTP errors into 500s.
    assert client.get("/api/does-not-exist").status_code == 404


def test_validate_trace_route_marks_valid_and_invalid(client):
    resp = client.post(
        "/api/trace/validate",
        json={"traces": ["a & b; cycle{!a}", "cycle{a}", "a & b", "cyckle{a}", ""]},
    )
    assert resp.status_code == 200
    results = resp.get_json()["results"]
    by_trace = {r["trace"]: r for r in results}

    assert by_trace["a & b; cycle{!a}"]["valid"] is True
    assert by_trace["a & b; cycle{!a}"]["error"] is None
    assert by_trace["cycle{a}"]["valid"] is True

    # A trace with no cycle is the most common user mistake; the reason says so.
    assert by_trace["a & b"]["valid"] is False
    assert "cycle" in by_trace["a & b"]["error"].lower()

    assert by_trace["cyckle{a}"]["valid"] is False
    assert by_trace[""]["valid"] is False
    assert "empty" in by_trace[""]["error"].lower()


def test_validate_trace_route_rejects_non_list(client):
    resp = client.post("/api/trace/validate", json={"traces": "a;cycle{a}"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]
