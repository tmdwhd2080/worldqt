"""Runner: submits simulations, analyzes results, and logs every attempt to disk.

Designed for an interactive loop where the caller (human or LLM) writes the
expression, calls ``run_attempt``, reads the feedback, and rewrites the
expression. Each attempt is saved under ``alphas/<idea>/attempt_NN_*``.
"""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .client import BrainClient
from .config import ALPHAS_DIR, DEFAULT_SETTINGS, PASS_CRITERIA, PassCriteria
from .analyzer import analyze_result, Analysis
from .validator import validate_expression, ValidationResult


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_idea_name(idea: str) -> str:
    clean = _SAFE_NAME.sub("_", idea.strip()).strip("_")
    return clean[:80] or "alpha"


@dataclass
class AttemptRecord:
    idea: str
    attempt: int
    expression: str
    settings: dict[str, Any]
    validation: ValidationResult
    analysis: Analysis
    alpha_id: str | None
    raw_result: dict[str, Any]
    folder: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "idea": self.idea,
            "attempt": self.attempt,
            "expression": self.expression,
            "settings": self.settings,
            "alpha_id": self.alpha_id,
            "validation": {
                "ok": self.validation.ok,
                "unknown": self.validation.unknown,
                "operators_used": sorted(set(self.validation.operators_used)),
                "datafields_used": sorted(set(self.validation.datafields_used)),
            },
            "analysis": self.analysis.to_dict(),
        }


class Runner:
    """High-level driver for one alpha idea.

    Usage pattern for an iteration loop:

        runner = Runner("breakout_capital_flow")
        rec = runner.run_attempt(expression_v1)
        if not rec.analysis.passed:
            # read rec.analysis.feedback, rewrite expression, then:
            rec = runner.run_attempt(expression_v2)
    """

    def __init__(
        self,
        idea: str,
        settings: dict[str, Any] | None = None,
        criteria: PassCriteria = PASS_CRITERIA,
        client: BrainClient | None = None,
        strict_validation: bool = False,
    ):
        self.idea = idea
        self.safe_idea = _safe_idea_name(idea)
        self.criteria = criteria
        self.settings = {**DEFAULT_SETTINGS, **(settings or {})}
        self.client = client
        self.strict_validation = strict_validation
        self.attempts: list[AttemptRecord] = []

        ALPHAS_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.folder = ALPHAS_DIR / f"{ts}_{self.safe_idea}"
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "idea.txt").write_text(idea, encoding="utf-8")

    def _client(self) -> BrainClient:
        if self.client is None:
            self.client = BrainClient()
            self.client.authenticate()
        return self.client

    def run_attempt(
        self,
        expression: str,
        settings_override: dict[str, Any] | None = None,
        note: str = "",
    ) -> AttemptRecord:
        attempt_no = len(self.attempts) + 1
        settings = {**self.settings, **(settings_override or {})}

        validation = validate_expression(expression)
        if self.strict_validation and not validation.ok:
            analysis = Analysis(
                passed=False,
                summary=f"Validation failed — unknown identifiers: {validation.unknown}",
                feedback=[
                    f"Unknown identifiers in expression: {sorted(set(validation.unknown))}. "
                    "Every name must be a documented operator or datafield from data/."
                ],
            )
            rec = self._finalize(
                attempt_no, expression, settings, validation, analysis,
                alpha_id=None, raw_result={}, note=note,
            )
            return rec

        client = self._client()
        raw = client.run_simulation(expression, settings)
        analysis = analyze_result(raw, self.criteria)
        alpha_id = raw.get("alpha_id")

        return self._finalize(
            attempt_no, expression, settings, validation, analysis,
            alpha_id=alpha_id, raw_result=raw, note=note,
        )

    def _finalize(
        self,
        attempt_no: int,
        expression: str,
        settings: dict[str, Any],
        validation: ValidationResult,
        analysis: Analysis,
        alpha_id: str | None,
        raw_result: dict[str, Any],
        note: str,
    ) -> AttemptRecord:
        rec = AttemptRecord(
            idea=self.idea,
            attempt=attempt_no,
            expression=expression,
            settings=settings,
            validation=validation,
            analysis=analysis,
            alpha_id=alpha_id,
            raw_result=raw_result,
            folder=self.folder,
        )
        self.attempts.append(rec)
        self._write_attempt_files(rec, note)
        return rec

    def _write_attempt_files(self, rec: AttemptRecord, note: str) -> None:
        stem = f"attempt_{rec.attempt:02d}"
        # Raw alpha expression (single source of truth for this attempt)
        (self.folder / f"{stem}_expression.txt").write_text(rec.expression, encoding="utf-8")
        # Summary + feedback (what the next iteration should read)
        feedback_lines = [
            f"# Attempt {rec.attempt} — idea: {rec.idea}",
            f"# passed: {rec.analysis.passed}",
            f"# summary: {rec.analysis.summary}",
            "",
            "## Settings",
            json.dumps(rec.settings, indent=2),
            "",
            "## Expression",
            rec.expression,
            "",
            "## Validation",
            f"ok={rec.validation.ok}",
            f"operators_used={sorted(set(rec.validation.operators_used))}",
            f"datafields_used={sorted(set(rec.validation.datafields_used))}",
            f"unknown={sorted(set(rec.validation.unknown))}",
            "",
            "## Checks",
        ]
        for c in rec.analysis.checks:
            feedback_lines.append(
                f"- [{('PASS' if c.passed else 'FAIL')}] {c.name}: value={c.value} limit={c.limit}"
            )
        if rec.analysis.feedback:
            feedback_lines.extend(["", "## Feedback", *rec.analysis.feedback])
        if note:
            feedback_lines.extend(["", "## Note", note])
        (self.folder / f"{stem}_feedback.md").write_text(
            "\n".join(feedback_lines), encoding="utf-8"
        )
        # Full JSON record for programmatic reads
        (self.folder / f"{stem}_record.json").write_text(
            json.dumps(rec.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        # Raw simulation response (biggest; useful for debugging)
        (self.folder / f"{stem}_raw.json").write_text(
            json.dumps(rec.raw_result, indent=2, default=str),
            encoding="utf-8",
        )

    def best_attempt(self) -> AttemptRecord | None:
        passing = [a for a in self.attempts if a.analysis.passed]
        if passing:
            return passing[-1]
        return self.attempts[-1] if self.attempts else None
