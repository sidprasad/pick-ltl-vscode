from __future__ import annotations

import re


OPERATORS = ["<->", "->", "U", "G", "F", "X", "&", "|", "!"]


def operator_signature(formula: str) -> set[str]:
    signature = set()
    for token in OPERATORS:
        if token in formula:
            signature.add(token)
    return signature


def rank_formulas(seed_formula: str, formulas: list[dict]) -> list[dict]:
    seed_signature = operator_signature(seed_formula)

    def score(item: dict):
        formula = item["formula"]
        signature = operator_signature(formula)
        return (
            len(signature.symmetric_difference(seed_signature)),
            abs(len(formula) - len(seed_formula)),
            -len(item.get("equivalents", [])),
        )

    return sorted(formulas, key=score, reverse=True)
