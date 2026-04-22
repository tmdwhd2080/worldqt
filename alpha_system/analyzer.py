"""Parse BRAIN simulation results, compare against pass criteria, emit feedback."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from .config import PASS_CRITERIA, PassCriteria


@dataclass
class CheckResult:
    name: str
    passed: bool
    value: Any = None
    limit: Any = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Analysis:
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    competitions: list[str] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "stats": self.stats,
            "competitions": self.competitions,
            "checks": [
                {"name": c.name, "passed": c.passed, "value": c.value, "limit": c.limit}
                for c in self.checks
            ],
            "feedback": self.feedback,
            "summary": self.summary,
        }


# Hint templates per failing check — these are what we surface back to the
# calling session so the next iteration of the expression has guidance.
_REMEDIATION: dict[str, str] = {
    "LOW_SHARPE": (
        "Sharpe below cutoff. Strengthen the signal: try (a) combining with a "
        "complementary factor (e.g. value + momentum), (b) winsorizing with "
        "winsorize() or zscore(), (c) stronger neutralization, or (d) ts_decay_linear "
        "to smooth noise."
    ),
    "LOW_FITNESS": (
        "Fitness below 1.0. Fitness ~= Sharpe * sqrt(|Returns|/max(Turnover, 0.125)). "
        "Either raise returns (stronger signal) or lower turnover (add ts_decay_linear, "
        "ts_mean, or increase decay setting)."
    ),
    "HIGH_TURNOVER": (
        "Turnover above 70%. Smooth the signal: wrap with ts_decay_linear(x, N) where "
        "N is 5–20, or raise the 'decay' setting, or use ts_mean to dampen day-to-day jumps."
    ),
    "LOW_TURNOVER": (
        "Turnover below 1% (signal barely trades). Either the signal is too static "
        "(try shorter ts_* windows) or is constant within the universe (add cross-sectional "
        "transforms like rank() or zscore())."
    ),
    "CONCENTRATED_WEIGHT": (
        "Weights concentrated in too few names. Apply rank() or zscore() for "
        "cross-sectional distribution; lower truncation if appropriate; or check "
        "the signal isn't dominated by a handful of outliers."
    ),
    "LOW_SUB_UNIVERSE_SHARPE": (
        "Sub-universe Sharpe below cutoff (alpha fails on a smaller universe). "
        "The edge is likely universe-specific. Make the signal more universal: "
        "use rank/zscore, avoid small-cap-only effects, or add robust normalizations."
    ),
    "SELF_CORRELATION": (
        "Too correlated with an existing submitted alpha. Add an orthogonal factor "
        "or invert the dominant driver."
    ),
    "UNITS": (
        "Unit mismatch. Ensure terms inside add/subtract/compare share units; "
        "apply rank() or zscore() to make inputs dimensionless."
    ),
    "MATCHES_COMPETITION": (
        "Competition match failed. Verify the simulation settings (region=USA, "
        "universe=TOP3000, delay=1, language=FASTEXPR) match the IQC 2026 Stage 1 requirements."
    ),
    "IS_LADDER_SHARPE": (
        "Ladder (rolling) Sharpe too low. Signal is unstable across sub-periods — "
        "add smoothing or a more stationary transform."
    ),
}


def _extract_stats(is_block: dict[str, Any]) -> dict[str, Any]:
    keys = ("sharpe", "fitness", "turnover", "returns", "drawdown", "margin",
            "longCount", "shortCount")
    return {k: is_block.get(k) for k in keys}


def _check_from_api(raw: dict[str, Any]) -> CheckResult:
    name = raw.get("name", "UNKNOWN")
    result = (raw.get("result") or "").upper()
    passed = result == "PASS"
    return CheckResult(
        name=name,
        passed=passed,
        value=raw.get("value"),
        limit=raw.get("limit"),
        raw=raw,
    )


def _derived_checks(stats: dict[str, Any], sub_sharpe: float | None, criteria: PassCriteria
                    ) -> list[CheckResult]:
    """Fallback checks computed locally when the API doesn't surface them.

    The platform normally returns its own check array; this only fires if a
    field is absent so we still produce a useful verdict.
    """
    out: list[CheckResult] = []

    sharpe = stats.get("sharpe")
    if isinstance(sharpe, (int, float)):
        out.append(CheckResult(
            name="LOW_SHARPE_DERIVED",
            passed=sharpe >= criteria.sharpe_min,
            value=sharpe, limit=criteria.sharpe_min,
        ))
    fitness = stats.get("fitness")
    if isinstance(fitness, (int, float)):
        out.append(CheckResult(
            name="LOW_FITNESS_DERIVED",
            passed=fitness >= criteria.fitness_min,
            value=fitness, limit=criteria.fitness_min,
        ))
    turnover = stats.get("turnover")
    if isinstance(turnover, (int, float)):
        hi_ok = turnover <= criteria.turnover_max
        lo_ok = turnover >= criteria.turnover_min
        out.append(CheckResult(
            name="TURNOVER_RANGE_DERIVED",
            passed=(hi_ok and lo_ok),
            value=turnover,
            limit=(criteria.turnover_min, criteria.turnover_max),
        ))
    if isinstance(sub_sharpe, (int, float)):
        out.append(CheckResult(
            name="LOW_SUB_UNIVERSE_SHARPE_DERIVED",
            passed=sub_sharpe >= criteria.sub_universe_sharpe_min,
            value=sub_sharpe, limit=criteria.sub_universe_sharpe_min,
        ))
    return out


def _competition_names(alpha: dict[str, Any]) -> list[str]:
    comps = alpha.get("competitions") or []
    names: list[str] = []
    for c in comps:
        if isinstance(c, dict):
            n = c.get("name") or c.get("id")
            if n:
                names.append(str(n))
        elif isinstance(c, str):
            names.append(c)
    return names


def _feedback_line(check: CheckResult) -> str:
    base = _REMEDIATION.get(
        check.name,
        _REMEDIATION.get(check.name.replace("_DERIVED", ""), ""),
    )
    detail = f"[{check.name}] value={check.value} limit={check.limit}"
    return f"{detail}\n  → {base}" if base else detail


def analyze_result(result: dict[str, Any], criteria: PassCriteria = PASS_CRITERIA
                   ) -> Analysis:
    """Turn a ``BrainClient.run_simulation`` result into an Analysis."""
    alpha = result.get("alpha") or {}
    status = result.get("status")
    message = result.get("message")

    if status != "COMPLETE" or not alpha:
        return Analysis(
            passed=False,
            summary=f"Simulation did not complete: status={status} message={message}",
            feedback=[f"Simulation error: {message or status}"],
        )

    is_block = alpha.get("is") or {}
    stats = _extract_stats(is_block)
    sub_sharpe = is_block.get("subUniverseSharpe") or is_block.get("subuniverseSharpe")
    if sub_sharpe is not None:
        stats["subUniverseSharpe"] = sub_sharpe

    api_checks_raw = is_block.get("checks") or alpha.get("checks") or []
    checks = [_check_from_api(c) for c in api_checks_raw]

    # Fill gaps for any criterion the API didn't return a check for.
    have = {c.name for c in checks}
    wanted = {"LOW_SHARPE", "LOW_FITNESS", "HIGH_TURNOVER", "LOW_TURNOVER",
              "LOW_SUB_UNIVERSE_SHARPE"}
    if not (wanted & have):
        checks.extend(_derived_checks(stats, sub_sharpe, criteria))

    competitions = _competition_names(alpha)
    comp_ok = all(
        any(required in name for name in competitions)
        for required in criteria.required_competitions
    ) if competitions else False
    checks.append(CheckResult(
        name="MATCHES_COMPETITION",
        passed=comp_ok,
        value=competitions,
        limit=list(criteria.required_competitions),
    ))

    passed = all(c.passed for c in checks)
    feedback = [_feedback_line(c) for c in checks if not c.passed]

    summary_parts = [
        f"passed={passed}",
        f"sharpe={stats.get('sharpe')}",
        f"fitness={stats.get('fitness')}",
        f"turnover={stats.get('turnover')}",
        f"subSharpe={stats.get('subUniverseSharpe')}",
        f"returns={stats.get('returns')}",
    ]
    summary = " | ".join(summary_parts)

    return Analysis(
        passed=passed,
        checks=checks,
        stats=stats,
        competitions=competitions,
        feedback=feedback,
        summary=summary,
    )
