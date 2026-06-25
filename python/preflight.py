"""Environment preflight for the PICK LTL sidecar.

Prints a single JSON line describing whether the interpreter can run the
backend. Always exits 0 — the caller (src/sidecar.ts) inspects the JSON so it
can give a precise "what's missing" message.
"""

import json
import sys


def _importable(module_name):
    try:
        __import__(module_name)
        return True
    except Exception:
        return False


def main():
    info = {
        "python": "%d.%d.%d" % sys.version_info[:3],
        "spot": _importable("spot"),
        "flask": _importable("flask"),
        "antlr4": _importable("antlr4"),
    }
    info["ok"] = bool(info["spot"] and info["flask"] and info["antlr4"])
    sys.stdout.write(json.dumps(info))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
