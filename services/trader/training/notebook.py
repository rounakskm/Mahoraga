"""Canonical markdown ledger (Phase-3 Layer-3, the Archivist's notebook).

A human-readable mirror of the search, with Postgres as the source of truth:

- `notes.md`           — one appended line per recorded experiment (the ledger).
- `do-not-repeat.md`   — candidates the loop has learned to avoid.
- `experiments/<hash>.md` — a per-candidate detail page (fitness + verdict + params).

The amendment's *regenerability* exit check is `regenerate_from_postgres(dsn)`:
`notes.md` must be reconstructible from `experiments.iterations` alone. The formatter
takes an optional injected `rows` list (`rows or _fetch(dsn)`) so it is testable
without a live DB.

No hard import-time dependency on `parse_metric` (a sibling task): `FitnessReport` is
referenced only under TYPE_CHECKING + `from __future__ import annotations`, so this
module imports even before parse_metric exists. `.record()` reads the report
duck-typed at call time.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # import only for type-checkers; no runtime dependency
    from services.trader.training.parse_metric import FitnessReport

_NOTES_HEADER = (
    "# Research Notes — Autoresearch Ledger\n\n"
    "> Regenerable from `experiments.iterations` via "
    "`Notebook.regenerate_from_postgres(dsn)`.\n\n"
    "| run | iter | candidate | fitness | sharpe | promoted | reason |\n"
    "|-----|------|-----------|---------|--------|----------|--------|\n"
)
_DNR_HEADER = (
    "# Do Not Repeat\n\n"
    "> Candidates the loop has learned to avoid.\n\n"
    "| candidate | reason |\n"
    "|-----------|--------|\n"
)


def _row_line(
    run_id: object, iteration: object, candidate_hash: object,
    fitness: object, sharpe: object, promoted: object, reason: object,
) -> str:
    return (
        f"| {run_id} | {iteration} | {candidate_hash} | "
        f"{float(fitness):.4f} | {float(sharpe):.4f} | "
        f"{bool(promoted)} | {str(reason).replace('|', '/')} |\n"
    )


class Notebook:
    """Markdown ledger rooted at `root` (e.g. `services/trader/research/`)."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.notes = self.root / "notes.md"
        self.do_not_repeat = self.root / "do-not-repeat.md"
        self.experiments = self.root / "experiments"

    def record(self, report: FitnessReport, run_id: str, iteration: int) -> None:
        """Write `experiments/<hash>.md` and append the `notes.md` ledger line."""
        self.experiments.mkdir(parents=True, exist_ok=True)
        page = (
            f"# Experiment `{report.candidate_hash}`\n\n"
            f"- run: `{run_id}`\n"
            f"- iteration: {iteration}\n"
            f"- fitness: {report.fitness:.4f}\n"
            f"- sharpe: {report.sharpe:.4f}\n"
            f"- quarterly_win_rate: {report.quarterly_win_rate:.4f}\n"
            f"- max_drawdown: {report.max_drawdown:.4f}\n"
            f"- promoted: {report.promoted}\n"
            f"- reason: {report.reason}\n\n"
            f"## Params\n\n```json\n{report.params}\n```\n"
        )
        (self.experiments / f"{report.candidate_hash}.md").write_text(page)

        if not self.notes.exists():
            self.notes.write_text(_NOTES_HEADER)
        with self.notes.open("a") as fh:
            fh.write(_row_line(
                run_id, iteration, report.candidate_hash,
                report.fitness, report.sharpe, report.promoted, report.reason,
            ))

    def mark_do_not_repeat(self, candidate_hash: str, reason: str) -> None:
        """Append a candidate to `do-not-repeat.md`."""
        if not self.do_not_repeat.exists():
            self.do_not_repeat.write_text(_DNR_HEADER)
        with self.do_not_repeat.open("a") as fh:
            fh.write(f"| {candidate_hash} | {str(reason).replace('|', '/')} |\n")

    def regenerate_from_postgres(
        self, dsn: str | None, rows: list[dict] | None = None
    ) -> None:
        """Rebuild `notes.md` from `experiments.iterations` (or an injected `rows`)."""
        source = rows if rows is not None else self._fetch(dsn)
        lines = [
            _row_line(
                r.get("run_id"), r.get("iteration"), r.get("candidate_hash"),
                r.get("fitness", 0.0), r.get("sharpe", 0.0),
                r.get("promoted", False), r.get("reason", ""),
            )
            for r in source
        ]
        self.notes.write_text(_NOTES_HEADER + "".join(lines))

    @staticmethod
    def _fetch(dsn: str | None) -> list[dict]:
        if not dsn:
            return []
        import psycopg  # noqa: PLC0415 (lazy: only when a DSN is set)

        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT run_id, iteration, candidate_hash, fitness, train_sharpe, "
                "promoted, reason FROM experiments.iterations ORDER BY run_id, iteration"
            )
            cols = ["run_id", "iteration", "candidate_hash", "fitness", "sharpe",
                    "promoted", "reason"]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
