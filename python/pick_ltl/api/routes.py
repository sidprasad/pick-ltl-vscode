from __future__ import annotations

from .. import flask_compat  # noqa: F401

from flask import Blueprint, jsonify, render_template, request
from requests import RequestException

from ..api.schemas import ApiError, json_error, normalize_provider_payload, require_json
from ..config import load_settings, save_settings
from ..llm.base import ProviderError
from ..llm.manager import build_provider
from ..ltl.ltlnode import LTLParseError
from ..services.candidate_builder import create_initial_session
from ..services.seed_generation import generate_seed_formulas
from ..session.engine import add_manual_examples, finalize_session, next_pair, classify_trace, refine_session, reclassify_trace
from ..session.storage import normalize_session_payload


bp = Blueprint("pick_ltl", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())


@bp.route("/api/settings", methods=["POST"])
def post_settings():
    payload = require_json()
    settings = save_settings(normalize_provider_payload(payload))
    return jsonify(settings)


@bp.route("/api/settings/test", methods=["POST"])
def test_settings():
    payload = require_json()
    provider = build_provider(normalize_provider_payload(payload))
    return jsonify(provider.test_connection())


@bp.route("/api/models", methods=["GET", "POST"])
def get_models():
    if request.method == "POST":
        payload = require_json()
        provider = build_provider(normalize_provider_payload(payload))
    else:
        provider = build_provider(load_settings())
    return jsonify({"models": provider.list_models()})


@bp.route("/api/seed/generate", methods=["POST"])
def generate_seed():
    payload = require_json()
    prompt = str(payload.get("prompt", "")).strip()
    provider = normalize_provider_payload(payload.get("provider", {}) if isinstance(payload.get("provider"), dict) else load_settings())
    seeds = generate_seed_formulas(prompt, provider)
    primary_seed = seeds[0]
    response = primary_seed.to_dict()
    response["seeds"] = [seed.to_dict() for seed in seeds]
    return jsonify(response)


@bp.route("/api/candidates/build", methods=["POST"])
def build_candidates():
    payload = require_json()
    prompt = str(payload.get("prompt", "")).strip()
    provider = normalize_provider_payload(payload.get("provider", {}) if isinstance(payload.get("provider"), dict) else load_settings())
    seeds_payload = payload.get("seeds")
    if payload.get("regenerate_seed"):
        seeds = generate_seed_formulas(prompt, provider)
    elif isinstance(seeds_payload, list):
        from ..session.models import SeedFormulaResult

        seeds = [SeedFormulaResult.from_dict(item) for item in seeds_payload if isinstance(item, dict)]
    else:
        seed_payload = payload.get("seed")
        if not isinstance(seed_payload, dict):
            raise ApiError("Expected a seed payload.")
        from ..session.models import SeedFormulaResult

        seeds = [SeedFormulaResult.from_dict(seed_payload)]
    session = create_initial_session(prompt, provider, seeds)
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


@bp.route("/api/session/refine", methods=["POST"])
def api_refine():
    payload = require_json()
    session = normalize_session_payload(payload.get("session", {}))
    prompt = str(payload.get("prompt", "")).strip() or session.prompt
    return jsonify(refine_session(session, prompt).to_dict())


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
    return jsonify(session.to_dict())


@bp.errorhandler(ApiError)
def handle_api_error(error: ApiError):
    return json_error(str(error), status_code=error.status_code)


@bp.errorhandler(ProviderError)
def handle_provider_error(error: ProviderError):
    return json_error(str(error), status_code=400)


@bp.errorhandler(LTLParseError)
def handle_ltl_parse_error(error: LTLParseError):
    return json_error(str(error), status_code=400)


@bp.errorhandler(RequestException)
def handle_request_error(error: RequestException):
    return json_error(f"Failed to contact the model provider: {error}", status_code=502)


@bp.errorhandler(RuntimeError)
def handle_runtime_error(error: RuntimeError):
    return json_error(str(error), status_code=500)
