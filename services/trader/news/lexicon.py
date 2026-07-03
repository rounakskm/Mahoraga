"""Finance sentiment + urgency word lists for the lexicon classifier.

Deterministic, dependency-free. `POSITIVE`/`NEGATIVE` are signed sentiment tokens;
`URGENCY_TRIGGERS` map a market-moving phrase to an impact weight — a severe hit
(weight >= 0.8) escalates a classification to CRITICAL, weaker hits to MATERIAL.
Matching is case-insensitive and whole-word everywhere: the sentiment lists are
token-set lookups, and each (often multi-word) trigger is compiled once at import
into a word-boundary regex (`TRIGGER_PATTERNS`) so "war" never matches "award",
"Warner" or "wary".
"""

from __future__ import annotations

import re

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
        "downgrades",
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

# Market-moving phrases -> impact weight (word-boundary match, lowercased).
# Weights >= 0.8 are the genuinely-severe, escalate-to-CRITICAL tier (FOMC
# decisions, rate moves, trading halts, bankruptcy, SEC probes, war, default,
# guidance cuts); weights < 0.8 are single-name routine events -> MATERIAL.
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
    "downgrades": 0.6,
    "recall": 0.6,
    "recalls": 0.6,
    "fraud": 0.85,
}

# Word-boundary regexes, compiled once at import. Multi-word phrases keep their
# internal spaces; \b anchors both ends so substrings never fire the trigger.
TRIGGER_PATTERNS: tuple[tuple[str, float, re.Pattern[str]], ...] = tuple(
    (phrase, weight, re.compile(r"\b" + re.escape(phrase) + r"\b"))
    for phrase, weight in URGENCY_TRIGGERS.items()
)
