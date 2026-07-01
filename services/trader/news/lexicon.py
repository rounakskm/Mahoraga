"""Finance sentiment + urgency word lists for the lexicon classifier.

Deterministic, dependency-free. `POSITIVE`/`NEGATIVE` are signed sentiment tokens;
`URGENCY_TRIGGERS` map a market-moving phrase to an impact weight — any hit pushes a
classification toward CRITICAL. Matching is case-insensitive, whole-word for the
single-token sentiment lists and substring for the (often multi-word) triggers.
"""

from __future__ import annotations

# Signed sentiment tokens (whole-word, lowercased match).
POSITIVE: frozenset[str] = frozenset(
    {
        "beat",
        "beats",
        "surge",
        "surges",
        "surged",
        "upgrade",
        "upgraded",
        "rally",
        "rallies",
        "rallied",
        "record",
        "gain",
        "gains",
        "gained",
        "jump",
        "jumps",
        "jumped",
        "soar",
        "soars",
        "soared",
        "outperform",
        "strong",
        "growth",
        "profit",
        "raised",
        "boost",
        "boosted",
        "bullish",
        "rebound",
        "recovery",
        "wins",
        "approval",
        "approved",
    }
)

NEGATIVE: frozenset[str] = frozenset(
    {
        "miss",
        "misses",
        "missed",
        "plunge",
        "plunges",
        "plunged",
        "downgrade",
        "downgraded",
        "cut",
        "cuts",
        "bankruptcy",
        "bankrupt",
        "halt",
        "halted",
        "probe",
        "fraud",
        "lawsuit",
        "recall",
        "warning",
        "warns",
        "slump",
        "slumps",
        "tumble",
        "tumbled",
        "sink",
        "sinks",
        "sank",
        "loss",
        "losses",
        "weak",
        "decline",
        "declines",
        "fell",
        "drop",
        "drops",
        "dropped",
        "crash",
        "selloff",
        "bearish",
        "default",
        "hawkish",
        "layoffs",
        "slashes",
        "slashed",
    }
)

# Market-moving phrases -> impact weight (substring match, lowercased).
# A hit escalates the classification toward CRITICAL.
URGENCY_TRIGGERS: dict[str, float] = {
    "fomc": 0.9,
    "rate hike": 0.9,
    "rate cut": 0.8,
    "halt": 0.85,
    "halted": 0.85,
    "bankruptcy": 0.95,
    "sec probe": 0.9,
    "sec investigation": 0.9,
    "guidance cut": 0.85,
    "cuts guidance": 0.85,
    "war": 0.9,
    "default": 0.9,
    "recession": 0.8,
    "emergency": 0.85,
    "downgrade": 0.6,
    "recall": 0.6,
    "fraud": 0.85,
}
