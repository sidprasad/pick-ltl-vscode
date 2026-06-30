from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# After this many *completed* pairs that don't narrow the candidate set (no
# elimination, no convergence), the session stops asking and surfaces the best
# match so far. Settable per-session via SessionState.max_pairs_without_progress
# (the extension exposes it as the `pick-ltl.maxPairsWithoutProgress` setting).
DEFAULT_MAX_PAIRS_WITHOUT_PROGRESS = 3


@dataclass
class AtomSpec:
    name: str
    meaning: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "meaning": self.meaning}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AtomSpec":
        return cls(name=str(data.get("name", "")).strip(), meaning=str(data.get("meaning", "")).strip())


@dataclass
class SeedFormulaResult:
    formula: str
    explanation: str
    atoms: list[AtomSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula": self.formula,
            "explanation": self.explanation,
            "atoms": [atom.to_dict() for atom in self.atoms],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SeedFormulaResult":
        return cls(
            formula=str(data.get("formula", "")).strip(),
            explanation=str(data.get("explanation", "")).strip(),
            atoms=[AtomSpec.from_dict(item) for item in data.get("atoms", []) if isinstance(item, dict)],
            warnings=[str(item).strip() for item in data.get("warnings", []) if str(item).strip()],
        )


@dataclass
class CandidateOrigin:
    kind: str
    misconception_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "misconception_code": self.misconception_code}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateOrigin":
        return cls(kind=str(data.get("kind", "")).strip(), misconception_code=data.get("misconception_code"))


@dataclass
class CandidateFormulaState:
    formula: str
    explanation: str
    origin: CandidateOrigin
    confidence: float | None = None
    equivalents: list[str] = field(default_factory=list)
    positive_votes: int = 0
    negative_votes: int = 0
    elimination_threshold: int = 2
    eliminated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula": self.formula,
            "explanation": self.explanation,
            "origin": self.origin.to_dict(),
            "confidence": self.confidence,
            "equivalents": list(self.equivalents),
            "positive_votes": self.positive_votes,
            "negative_votes": self.negative_votes,
            "elimination_threshold": self.elimination_threshold,
            "eliminated": self.eliminated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateFormulaState":
        return cls(
            formula=str(data.get("formula", "")).strip(),
            explanation=str(data.get("explanation", "")).strip(),
            origin=CandidateOrigin.from_dict(data.get("origin", {}) if isinstance(data.get("origin"), dict) else {}),
            confidence=data.get("confidence"),
            equivalents=[str(item) for item in data.get("equivalents", [])],
            positive_votes=int(data.get("positive_votes", 0) or 0),
            negative_votes=int(data.get("negative_votes", 0) or 0),
            elimination_threshold=int(data.get("elimination_threshold", 2) or 2),
            eliminated=bool(data.get("eliminated", False)),
        )


@dataclass
class TracePair:
    trace1: str
    trace2: str
    matches1: list[str] = field(default_factory=list)
    matches2: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace1": self.trace1,
            "trace2": self.trace2,
            "matches1": list(self.matches1),
            "matches2": list(self.matches2),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TracePair":
        return cls(
            trace1=str(data.get("trace1", "")),
            trace2=str(data.get("trace2", "")),
            matches1=[str(item) for item in data.get("matches1", [])],
            matches2=[str(item) for item in data.get("matches2", [])],
        )


@dataclass
class TraceClassification:
    trace: str
    classification: str
    matching_candidates: list[str]
    source: str
    timestamp: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace": self.trace,
            "classification": self.classification,
            "matching_candidates": list(self.matching_candidates),
            "source": self.source,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TraceClassification":
        return cls(
            trace=str(data.get("trace", "")),
            classification=str(data.get("classification", "")),
            matching_candidates=[str(item) for item in data.get("matching_candidates", [])],
            source=str(data.get("source", "pair")),
            timestamp=int(data.get("timestamp", 0) or 0),
        )


@dataclass
class FinalResult:
    title: str
    formula: str | None
    explanation: str
    english: str
    examples_in: list[str] = field(default_factory=list)
    examples_out: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "formula": self.formula,
            "explanation": self.explanation,
            "english": self.english,
            "examples_in": list(self.examples_in),
            "examples_out": list(self.examples_out),
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FinalResult":
        return cls(
            title=str(data.get("title", "")),
            formula=data.get("formula"),
            explanation=str(data.get("explanation", "")),
            english=str(data.get("english", "")),
            examples_in=[str(item) for item in data.get("examples_in", [])],
            examples_out=[str(item) for item in data.get("examples_out", [])],
            message=str(data.get("message", "")),
        )


@dataclass
class SessionState:
    version: int = 1
    prompt: str = ""
    provider: dict[str, Any] = field(default_factory=dict)
    seed: SeedFormulaResult | None = None
    seeds: list[SeedFormulaResult] = field(default_factory=list)
    candidate_states: list[CandidateFormulaState] = field(default_factory=list)
    history: list[TraceClassification] = field(default_factory=list)
    mode: str = "prompt"
    warnings: list[str] = field(default_factory=list)
    current_pair: TracePair | None = None
    final_result: FinalResult | None = None
    exhausted: bool = False
    message: str = ""
    # Staleness tracking for the no-progress safety valve. `pairs_without_progress`
    # counts consecutive completed pairs that left the live candidate set *exactly*
    # as it was (nothing eliminated). `last_active_signature` is that set at the
    # previous pair (None = not yet measured); comparing the whole set — not just
    # its size — means a reclassify that revives or swaps candidates resets the
    # streak instead of being miscounted as another stale pair.
    pairs_without_progress: int = 0
    max_pairs_without_progress: int = DEFAULT_MAX_PAIRS_WITHOUT_PROGRESS
    last_active_signature: list[str] | None = None

    def active_candidates(self) -> list[CandidateFormulaState]:
        return [candidate for candidate in self.candidate_states if not candidate.eliminated]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "prompt": self.prompt,
            "provider": dict(self.provider),
            "seed": self.seed.to_dict() if self.seed else None,
            "seeds": [seed.to_dict() for seed in self.seeds],
            "candidate_states": [candidate.to_dict() for candidate in self.candidate_states],
            "history": [item.to_dict() for item in self.history],
            "mode": self.mode,
            "warnings": list(self.warnings),
            "current_pair": self.current_pair.to_dict() if self.current_pair else None,
            "final_result": self.final_result.to_dict() if self.final_result else None,
            "exhausted": self.exhausted,
            "message": self.message,
            "pairs_without_progress": self.pairs_without_progress,
            "max_pairs_without_progress": self.max_pairs_without_progress,
            "last_active_signature": (
                list(self.last_active_signature) if self.last_active_signature is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        seed = data.get("seed")
        seeds = data.get("seeds", [])
        pair = data.get("current_pair")
        result = data.get("final_result")
        parsed_seeds = [SeedFormulaResult.from_dict(item) for item in seeds if isinstance(item, dict)]
        parsed_seed = SeedFormulaResult.from_dict(seed) if isinstance(seed, dict) else (parsed_seeds[0] if parsed_seeds else None)
        return cls(
            version=int(data.get("version", 1) or 1),
            prompt=str(data.get("prompt", "")),
            provider=data.get("provider", {}) if isinstance(data.get("provider"), dict) else {},
            seed=parsed_seed,
            seeds=parsed_seeds if parsed_seeds else ([parsed_seed] if parsed_seed else []),
            candidate_states=[
                CandidateFormulaState.from_dict(item)
                for item in data.get("candidate_states", [])
                if isinstance(item, dict)
            ],
            history=[TraceClassification.from_dict(item) for item in data.get("history", []) if isinstance(item, dict)],
            mode=str(data.get("mode", "prompt")),
            warnings=[str(item) for item in data.get("warnings", [])],
            current_pair=TracePair.from_dict(pair) if isinstance(pair, dict) else None,
            final_result=FinalResult.from_dict(result) if isinstance(result, dict) else None,
            exhausted=bool(data.get("exhausted", False)),
            message=str(data.get("message", "")),
            pairs_without_progress=max(0, int(data.get("pairs_without_progress", 0) or 0)),
            max_pairs_without_progress=max(
                1,
                int(
                    data.get("max_pairs_without_progress", DEFAULT_MAX_PAIRS_WITHOUT_PROGRESS)
                    or DEFAULT_MAX_PAIRS_WITHOUT_PROGRESS
                ),
            ),
            last_active_signature=(
                [str(f) for f in data["last_active_signature"]]
                if isinstance(data.get("last_active_signature"), list)
                else None
            ),
        )
