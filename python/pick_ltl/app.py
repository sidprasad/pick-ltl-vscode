from __future__ import annotations

from . import flask_compat  # noqa: F401

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from .api.routes import bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(bp)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        # Last line of defence: never let an unhandled exception reach the
        # extension as an HTML traceback (which it can't parse, so it shows an
        # opaque "Backend error (HTTP 500)"). Anything not already handled by a
        # more specific handler becomes a clean JSON 500. Real HTTP errors
        # (404/405/...) pass through unchanged.
        if isinstance(error, HTTPException):
            return error
        return jsonify({"error": f"Unexpected backend error: {error}"}), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
