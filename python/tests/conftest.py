"""Shared pytest setup for the PICK backend tests.

These tests exercise the SPOT-backed engine. Each test module starts with
`pytest.importorskip("spot")`, so the suite `skip`s (not fails) when the
conda-forge `spot` package is absent — letting `pytest` run anywhere while CI
runs the real tests in the provisioned env.
"""

import os
import sys

# Make the vendored `pick_ltl` package importable without installing it.
_PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)
