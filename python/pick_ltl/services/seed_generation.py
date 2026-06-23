from __future__ import annotations

import json
import re

from ..llm.base import ProviderError
from ..llm.manager import build_provider
from ..ltl.ltlnode import LTLNode, LTLParseError, parse_ltl_string
from ..ltl.traceprocessor import getFormulaLiterals
from ..session.models import AtomSpec, SeedFormulaResult


ATOM_RE = re.compile(r"^[a-z0-9]+$")
FORMULA_PREFIX_RE = re.compile(r"^(?:ltl|formula)\s*:\s*", re.IGNORECASE)
FORMULA_TOKEN_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
ESCAPED_OPERATOR_RE = re.compile(r"\\+(X|AFTER|NEXT_STATE|F|EVENTUALLY|G|ALWAYS|U|UNTIL)\b", re.IGNORECASE)
UNICODE_REPLACEMENTS = {
    "¬": "!",
    "∧": "&",
    "∨": "|",
    "→": "->",
    "⇒": "->",
    "↔": "<->",
    "◇": "F",
    "□": "G",
}
OPERATOR_WORDS = {"X", "AFTER", "NEXT_STATE", "F", "EVENTUALLY", "G", "ALWAYS", "U", "UNTIL"}


SEED_SYSTEM_PROMPT = """You are an LTL-generation assistant.
Given a natural-language temporal requirement, generate exactly two plausible and meaningfully different LTL formulas using one shared atom glossary.

Return ONLY a single JSON object with this shape:
{
  "atoms": [
    {"name": "<atom>", "meaning": "<what it means>"}
  ],
  "seeds": [
    {"formula": "<LTL_FORMULA_1>", "explanation": "<SHORT_EXPLANATION_1>"},
    {"formula": "<LTL_FORMULA_2>", "explanation": "<SHORT_EXPLANATION_2>"}
  ],
  "warnings": ["<optional warning 1>", "<optional warning 2>"]
}

Output rules:
- Output must be valid JSON. No backticks, comments, or extra text.
- "atoms" must be an array of objects with keys "name" and "meaning".
- "seeds" must contain exactly 2 items.
- Each seed item must have a string "formula" and a short string "explanation".
- The two formulas should be genuinely different plausible interpretations, not formatting variants of each other.
- "warnings" must be an array. Use [] when there are no warnings.

LTL syntax rules:
- Use ASCII LTL only.
- Unary operators: G, F, X, !
- Binary operators: U, &, |, ->
- Grouping: parentheses ()
- Proposition names must be lowercase letters/digits only, like r, b, p1, req, grant
- Do not use backslashes anywhere in the formula.
- Do not escape operators or parentheses.
- Do not use LaTeX syntax.
- Do not use English words like ALWAYS or EVENTUALLY in the formula; use G and F instead.
- Do not use alternate formulas or prose outside the JSON object.
- Both formulas must use the same atom glossary.

Valid formula examples:
- G(r -> F(b))
- G(req -> F(grant))
- X(p1)
- (r U g)

Invalid formula examples:
- \\G (r \\U b)
- \\(G(r)\\)
- $G(r)$
- ALWAYS(r)
- EVENTUALLY(b)
"""


SEED_REPAIR_SYSTEM_PROMPT = """You repair malformed LTL model output.
Given an original natural-language requirement and a previous malformed result, extract or repair exactly two plausible LTL formulas using one shared atom glossary and return only one JSON object.

Return ONLY a single JSON object with this shape:
{
  "atoms": [
    {"name": "<atom>", "meaning": "<what it means>"}
  ],
  "seeds": [
    {"formula": "<LTL_FORMULA_1>", "explanation": "<SHORT_EXPLANATION_1>"},
    {"formula": "<LTL_FORMULA_2>", "explanation": "<SHORT_EXPLANATION_2>"}
  ],
  "warnings": ["<optional warning 1>", "<optional warning 2>"]
}

Output rules:
- Output must be valid JSON. No backticks, comments, or extra text.
- Return exactly two repaired formulas, not alternatives.
- Preserve the intended meaning of the original requirement when possible.
- If the previous result already suggests formulas, repair/extract them rather than inventing completely different interpretations.

LTL syntax rules:
- Use ASCII LTL only.
- Unary operators: G, F, X, !
- Binary operators: U, &, |, ->
- Grouping: parentheses ()
- Proposition names must be lowercase letters/digits only, like r, b, p1, req, grant
- Do not use backslashes anywhere in the formula.
- Do not use LaTeX syntax.
"""


def _normalize_atom_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return normalized


def _normalize_formula_token(match: re.Match[str]) -> str:
    token = match.group(0)
    upper = token.upper()
    if upper in OPERATOR_WORDS:
        return upper
    return _normalize_atom_name(token)


def _sanitize_formula(formula: str) -> str:
    normalized = str(formula).strip()
    normalized = normalized.strip("`$")
    normalized = normalized.replace("\\\\", "\\")
    normalized = normalized.replace("\\(", "(").replace("\\)", ")")
    normalized = normalized.replace("\\[", "(").replace("\\]", ")")
    normalized = normalized.replace("\\{", "(").replace("\\}", ")")
    normalized = ESCAPED_OPERATOR_RE.sub(lambda match: match.group(1).upper(), normalized)
    for source, target in UNICODE_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)
    if normalized.startswith("```") and normalized.endswith("```"):
        normalized = "\n".join(normalized.splitlines()[1:-1]).strip()
    normalized = FORMULA_PREFIX_RE.sub("", normalized).strip()
    normalized = FORMULA_TOKEN_RE.sub(_normalize_formula_token, normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _normalize_atoms(formula: str, raw_atoms: list[dict]) -> list[AtomSpec]:
    atoms: list[AtomSpec] = []
    seen: set[str] = set()
    for item in raw_atoms:
        atom = AtomSpec.from_dict(item if isinstance(item, dict) else {})
        atom.name = _normalize_atom_name(atom.name)
        if not atom.name or atom.name in seen or not ATOM_RE.match(atom.name):
            continue
        if not atom.meaning:
            atom.meaning = atom.name
        atoms.append(atom)
        seen.add(atom.name)

    formula_atoms = sorted(getFormulaLiterals(formula))
    for atom_name in formula_atoms:
        if atom_name not in seen:
            atoms.append(AtomSpec(name=atom_name, meaning=atom_name))
            seen.add(atom_name)
    return atoms


def _normalize_atoms_from_many(formulas: list[str], raw_atoms: list[dict]) -> list[AtomSpec]:
    merged_atoms: list[AtomSpec] = []
    seen = set()

    for item in raw_atoms:
        atom = AtomSpec.from_dict(item if isinstance(item, dict) else {})
        atom.name = _normalize_atom_name(atom.name)
        if not atom.name or atom.name in seen or not ATOM_RE.match(atom.name):
            continue
        if not atom.meaning:
            atom.meaning = atom.name
        merged_atoms.append(atom)
        seen.add(atom.name)

    for formula in formulas:
        for atom_name in sorted(getFormulaLiterals(formula)):
            if atom_name in seen:
                continue
            merged_atoms.append(AtomSpec(name=atom_name, meaning=atom_name))
            seen.add(atom_name)

    return merged_atoms


def _parse_formula_or_raise(formula: str) -> str:
    normalized_formula = _sanitize_formula(formula)
    return str(parse_ltl_string(normalized_formula))


def _repair_seed_payload(provider, prompt: str, payload: dict, malformed_formulas: list[str]) -> dict:
    repair_payload = provider.complete_json(
        SEED_REPAIR_SYSTEM_PROMPT,
        "\n".join(
            [
                f"Original requirement:\n{prompt.strip()}",
                "",
                "Malformed formulas:",
                *[f"- {formula}" for formula in malformed_formulas],
                "",
                "Previous JSON object:",
                json.dumps(payload, ensure_ascii=True),
            ]
        ),
    )
    repaired_warnings = repair_payload.get("warnings", [])
    if isinstance(repaired_warnings, list):
        repair_payload["warnings"] = [
            str(item).strip() for item in repaired_warnings if str(item).strip()
        ] + ["Initial model output required formula repair."]
    else:
        repair_payload["warnings"] = ["Initial model output required formula repair."]
    return repair_payload


def _raw_seed_entries(payload: dict) -> list[dict]:
    seeds = payload.get("seeds")
    if isinstance(seeds, list):
        return [item for item in seeds if isinstance(item, dict)]
    if isinstance(payload.get("formula"), str):
        return [{"formula": payload.get("formula"), "explanation": payload.get("explanation", "")}]
    return []


def _dedupe_seed_results(seeds: list[SeedFormulaResult]) -> list[SeedFormulaResult]:
    deduped: list[SeedFormulaResult] = []
    seen: list[str] = []

    for seed in seeds:
        if seed.formula in seen or any(LTLNode.equiv(seed.formula, other) for other in seen):
            continue
        deduped.append(seed)
        seen.append(seed.formula)
    return deduped


def _parse_seed_payload(payload: dict) -> list[SeedFormulaResult]:
    raw_entries = _raw_seed_entries(payload)
    warnings = [str(item).strip() for item in payload.get("warnings", []) if str(item).strip()]
    parsed_formulas: list[str] = []
    normalized_entries: list[tuple[str, str]] = []

    for entry in raw_entries:
        formula = str(entry.get("formula", "")).strip()
        if not formula:
            continue
        parsed_formula = _parse_formula_or_raise(formula)
        explanation = str(entry.get("explanation", "")).strip() or "Seed formula proposed by the language model."
        parsed_formulas.append(parsed_formula)
        normalized_entries.append((parsed_formula, explanation))

    atoms = _normalize_atoms_from_many(parsed_formulas, payload.get("atoms", []))
    return _dedupe_seed_results(
        [
            SeedFormulaResult(formula=formula, explanation=explanation, atoms=atoms, warnings=warnings)
            for formula, explanation in normalized_entries
        ]
    )


def generate_seed_formulas(prompt: str, provider_payload: dict) -> list[SeedFormulaResult]:
    if not prompt.strip():
        raise ValueError("Prompt cannot be empty.")

    provider = build_provider(provider_payload)
    payload = provider.complete_json(SEED_SYSTEM_PROMPT, f"Description:\n{prompt.strip()}")
    try:
        seeds = _parse_seed_payload(payload)
    except LTLParseError as exc:
        malformed = [str(item.get("formula", "")).strip() for item in _raw_seed_entries(payload) if str(item.get("formula", "")).strip()]
        try:
            payload = _repair_seed_payload(provider, prompt, payload, malformed or ["<missing formula>"])
            seeds = _parse_seed_payload(payload)
        except (ProviderError, LTLParseError) as repair_exc:
            raise ProviderError(
                "Model returned invalid LTL formulas and the repair pass did not recover them. "
                "Try a more instruction-following model, revise the prompt, or use a model that follows structured output more reliably."
            ) from repair_exc

    if not seeds:
        raise ProviderError("Model did not return any valid LTL formulas.")

    if len(seeds) == 1:
        if "Only one distinct initial formula survived validation." not in seeds[0].warnings:
            seeds[0].warnings.append("Only one distinct initial formula survived validation.")
    return seeds


def generate_seed_formula(prompt: str, provider_payload: dict) -> SeedFormulaResult:
    return generate_seed_formulas(prompt, provider_payload)[0]
