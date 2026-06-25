from __future__ import annotations

from flask import Blueprint, jsonify

from ..api.schemas import ApiError, json_error, require_json
from ..ltl.ltlnode import LTLParseError
from ..services.candidate_builder import create_initial_session, drop_degenerate_candidate_states
from ..session.engine import (
    add_manual_examples,
    classify_trace,
    finalize_session,
    next_pair,
    reclassify_trace,
)
from ..session.models import SeedFormulaResult
from ..session.storage import normalize_session_payload


bp = Blueprint("pick_ltl", __name__)


@bp.route("/api/health", methods=["GET"])
def health():
    """Liveness probe used by the extension (src/sidecar.ts) to wait for the
    sidecar. Returns quickly and needs no spot, so it answers before the first
    (slow) spot import."""
    return jsonify({"status": "ok"})


@bp.route("/api/candidates/build", methods=["POST"])
def build_candidates():
    payload = require_json()
    prompt = str(payload.get("prompt", "")).strip()
    provider = payload.get("provider", {}) if isinstance(payload.get("provider"), dict) else {}
    seeds_payload = payload.get("seeds")
    if isinstance(seeds_payload, list):
        seeds = [SeedFormulaResult.from_dict(item) for item in seeds_payload if isinstance(item, dict)]
    else:
        seed_payload = payload.get("seed")
        if not isinstance(seed_payload, dict):
            raise ApiError("Expected a seed payload.")
        seeds = [SeedFormulaResult.from_dict(seed_payload)]
    # Optional: pin the proposition set (refine sends the original session's
    # atoms so the alphabet — and thus replayed classifications — stay valid).
    raw_atoms = payload.get("allowed_atoms")
    allowed_atoms = (
        {str(a).strip() for a in raw_atoms if str(a).strip()}
        if isinstance(raw_atoms, list) and raw_atoms
        else None
    )
    session = create_initial_session(prompt, provider, seeds, allowed_atoms=allowed_atoms)
    return jsonify(session.to_dict())


@bp.route("/api/session/next-pair", methods=["POST"])
def api_next_pair():
    payload = require_json()
    session = normalize_session_payload(payload.get("session", payload))
    return jsonify(next_pair(session).to_dict())


@bp.route("/api/session/classify", methods=["POST"])
def api_classify():
    payload = require_json()
    session = normalize_session_payload(payload.get("session", {}))
    trace = str(payload.get("trace", "")).strip()
    classification = str(payload.get("classification", "")).strip()
    source = str(payload.get("source", "pair"))
    return jsonify(classify_trace(session, trace, classification, source=source).to_dict())


@bp.route("/api/session/reclassify", methods=["POST"])
def api_reclassify():
    payload = require_json()
    session = normalize_session_payload(payload.get("session", {}))
    history_index = int(payload.get("history_index", -1))
    classification = str(payload.get("classification", "")).strip()
    return jsonify(reclassify_trace(session, history_index, classification).to_dict())


@bp.route("/api/session/examples", methods=["POST"])
def api_examples():
    payload = require_json()
    session = normalize_session_payload(payload.get("session", {}))
    accept_traces = payload.get("accept_traces", [])
    reject_traces = payload.get("reject_traces", [])
    return jsonify(add_manual_examples(session, accept_traces, reject_traces).to_dict())


@bp.route("/api/session/finalize", methods=["POST"])
def api_finalize():
    payload = require_json()
    session = normalize_session_payload(payload.get("session", {}))
    formula = payload.get("formula")
    return jsonify(finalize_session(session, formula=formula).to_dict())


@bp.route("/api/session/import", methods=["POST"])
def api_import():
    payload = require_json()
    session = normalize_session_payload(payload.get("session", payload))
    # Drop unsatisfiable/tautological candidates on the way in, so an imported
    # session (e.g. a previously exported JSON predating this filter) can't carry
    # a phantom candidate that survives every classification.
    session.candidate_states = drop_degenerate_candidate_states(session.candidate_states)
    return jsonify(session.to_dict())


@bp.errorhandler(ApiError)
def handle_api_error(error: ApiError):
    return json_error(str(error), status_code=error.status_code)


@bp.errorhandler(LTLParseError)
def handle_ltl_parse_error(error: LTLParseError):
    return json_error(str(error), status_code=400)


@bp.errorhandler(ValueError)
def handle_value_error(error: ValueError):
    # The engine raises ValueError for bad client input (e.g. an unknown
    # classification or an out-of-range history index). That's a 400, not an
    # uncaught 500 with a traceback — which is what it used to surface as.
    return json_error(str(error), status_code=400)


@bp.errorhandler(RuntimeError)
def handle_runtime_error(error: RuntimeError):
    return json_error(str(error), status_code=500)
