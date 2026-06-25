from __future__ import annotations

from . import flask_compat  # noqa: F401

from flask import Flask

from .api.routes import bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
