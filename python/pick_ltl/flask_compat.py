"""Compatibility helpers for older Flask/newer Jinja environments."""

import jinja2
from markupsafe import Markup, escape


if not hasattr(jinja2, "escape"):
    jinja2.escape = escape
if not hasattr(jinja2, "Markup"):
    jinja2.Markup = Markup
