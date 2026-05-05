"""Iterate IVOL-based WorldQuant BRAIN alpha candidates until one passes.

The core thesis is fixed:
    - short unusually high idiosyncratic/implied volatility
    - long unusually low idiosyncratic/implied volatility

Run:
    python iterate_ivol.py --max-attempts 40

Requires credentials.json for live API simulation. Without credentials, the
script still validates all candidates against local operator/datafield CSVs.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alpha_system.config import CREDENTIALS_PATH
from alpha_system.client import BrainClient
from alpha_system.runner import Runner
from alpha_system.validator import validate_expression


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


IDEA = "ivol_short_high_long_low"


@dataclass(frozen=True)
class Candidate:
    name: str
    expression: str
    settings: dict[str, Any]
    note: str


BASE_SETTINGS: list[dict[str, Any]] = [
    {
        "universe": "TOP3000",
        "neutralization": "SUBINDUSTRY",
        "decay": 4,
        "truncation": 0.08,
    },
    {
        "universe": "TOP3000",
        "neutralization": "INDUSTRY",
        "decay": 6,
        "truncation": 0.06,
    },
    {
        "universe": "TOP3000",
        "neutralization": "SUBINDUSTRY",
        "decay": 10,
        "truncation": 0.05,
    },
    {
        "universe": "TOP3000",
        "neutralization": "SECTOR",
        "decay": 8,
        "truncation": 0.04,
    },
]


def ivol_spread(iv_days: int, hv_days: int | None = None) -> str:
    hv_days = hv_days or iv_days
    return (
        f"group_zscore(implied_volatility_mean_{iv_days}, subindustry) "
        f"- group_zscore(historical_volatility_{hv_days}, subindustry)"
    )


def low_ivol(expr: str) -> str:
    return f"-1 * rank(winsorize({expr}, std=4))"


def neutral(expr: str) -> str:
    return f"group_neutralize({expr}, subindustry)"


def smooth(expr: str, days: int = 5) -> str:
    return f"ts_decay_linear({expr}, {days})"


def build_candidates() -> list[Candidate]:
    """Generate a compact, high-probability IVOL search grid.

    Every expression keeps the main direction: higher abnormal IVOL gets a more
    negative score, lower abnormal IVOL gets a more positive score. Extra terms
    are gates or mild overlays chosen to improve robustness/turnover.
    """
    raw_signals: list[tuple[str, str, str]] = [
        (
            "unsystematic_60",
            "group_zscore(unsystematic_risk_last_60_days, subindustry)",
            "Smoother direct idiosyncratic risk field.",
        ),
        (
            "unsystematic_30",
            "group_zscore(unsystematic_risk_last_30_days, subindustry)",
            "Direct idiosyncratic risk field; high IVOL short, low IVOL long.",
        ),
        (
            "iv_and_unsys",
            "0.65 * (group_zscore(implied_volatility_mean_30, subindustry) "
            "- group_zscore(historical_volatility_30, subindustry)) "
            "+ 0.35 * group_zscore(unsystematic_risk_last_30_days, subindustry)",
            "Blend option abnormal IVOL and realized idiosyncratic risk.",
        ),
        (
            "iv_hv_30",
            ivol_spread(30),
            "ATM 30d implied volatility unusually high versus 30d realized volatility.",
        ),
        (
            "iv_hv_60",
            ivol_spread(60),
            "ATM 60d implied volatility unusually high versus 60d realized volatility.",
        ),
        (
            "iv_hv_90",
            ivol_spread(90),
            "ATM 90d implied volatility unusually high versus 90d realized volatility.",
        ),
        (
            "iv_short_realized_mid",
            "group_zscore(implied_volatility_mean_30, subindustry) "
            "- group_zscore(historical_volatility_90, subindustry)",
            "Short-term IV expensive versus slower realized volatility anchor.",
        ),
    ]

    overlays: list[tuple[str, str, str]] = [
        ("plain", "{base}", "pure abnormal IVOL rank reversal"),
        (
            "quality",
            "{base} + 0.15 * rank(return_equity)",
            "mild quality tilt: low-IVOL longs should be fundamentally cleaner",
        ),
        (
            "revision",
            "{base} + 0.15 * rank(analyst_revision_rank_derivative)",
            "mild analyst-revision support for the long book",
        ),
        (
            "sentiment",
            "{base} + 0.10 * rank(rp_css_earnings)",
            "small earnings-news sentiment overlay",
        ),
        (
            "anti_crowded",
            "{base} + 0.10 * rank(-1 * news_short_interest)",
            "avoid crowded/high-short-interest longs",
        ),
        (
            "mom_gate",
            "{base} * (0.75 + 0.50 * rank(ts_mean(returns, 20)))",
            "keeps IVOL core while reducing exposure to weak recent-return names",
        ),
    ]

    candidates: list[Candidate] = []
    for raw_name, raw_expr, raw_note in raw_signals:
        base = smooth(low_ivol(raw_expr), 5)
        for overlay_name, template, overlay_note in overlays:
            expr = f"zscore({neutral(template.format(base=base))})"
            for i, settings in enumerate(BASE_SETTINGS, start=1):
                candidates.append(
                    Candidate(
                        name=f"{raw_name}_{overlay_name}_s{i}",
                        expression=expr,
                        settings=settings,
                        note=f"{raw_note} Overlay: {overlay_note}.",
                    )
                )
    return candidates


def result_score(stats: dict[str, Any]) -> float:
    sharpe = stats.get("sharpe")
    fitness = stats.get("fitness")
    returns = stats.get("returns")
    turnover = stats.get("turnover")
    score = 0.0
    if isinstance(sharpe, (int, float)):
        score += 100.0 * sharpe
    if isinstance(fitness, (int, float)):
        score += 80.0 * fitness
    if isinstance(returns, (int, float)):
        score += 10.0 * returns
    if isinstance(turnover, (int, float)):
        score -= 10.0 * max(0.0, turnover - 0.35)
    return score


def main() -> int:
    parser = argparse.ArgumentParser(description="Run IVOL alpha candidates until pass.")
    parser.add_argument("--max-attempts", type=int, default=40)
    parser.add_argument("--start", type=int, default=1, help="1-based candidate index")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; no API calls")
    parser.add_argument("--retries", type=int, default=2, help="Retries per candidate after API errors")
    parser.add_argument("--request-timeout", type=float, default=120.0)
    args = parser.parse_args()

    candidates = build_candidates()
    selected = candidates[args.start - 1 : args.start - 1 + args.max_attempts]
    print(f"Generated {len(candidates)} candidates; selected {len(selected)}.")

    invalid: list[tuple[str, list[str]]] = []
    for c in selected:
        v = validate_expression(c.expression)
        if not v.ok:
            invalid.append((c.name, sorted(set(v.unknown))))
    if invalid:
        print("ABORT: invalid candidates found.")
        for name, unknown in invalid:
            print(f"  {name}: {unknown}")
        return 1

    print("Local validation OK for selected candidates.")
    if args.dry_run or not CREDENTIALS_PATH.exists():
        if not CREDENTIALS_PATH.exists():
            print(f"Live API skipped: {CREDENTIALS_PATH} not found.")
        for idx, c in enumerate(selected, start=args.start):
            print(f"\n[{idx}] {c.name}")
            print(f"settings={json.dumps(c.settings, sort_keys=True)}")
            print(c.expression)
        return 0

    runner = Runner(
        idea=IDEA,
        strict_validation=True,
        client=BrainClient(timeout=args.request_timeout),
    )
    best = None
    best_score = float("-inf")

    for idx, c in enumerate(selected, start=args.start):
        print(f"\n=== Attempt {idx}: {c.name} ===")
        print(f"Settings: {json.dumps(c.settings, sort_keys=True)}")
        rec = None
        for retry in range(args.retries + 1):
            try:
                rec = runner.run_attempt(c.expression, settings_override=c.settings, note=c.note)
                break
            except Exception as exc:
                print(f"API error on {c.name} try {retry + 1}/{args.retries + 1}: {type(exc).__name__}: {exc}")
                if retry >= args.retries:
                    print("Skipping candidate after retries.")
        if rec is None:
            continue
        stats = rec.analysis.stats
        score = result_score(stats)
        if score > best_score:
            best = rec
            best_score = score
        print(rec.analysis.summary)
        print(f"alpha_id={rec.alpha_id} passed={rec.analysis.passed}")
        if rec.analysis.feedback:
            for line in rec.analysis.feedback[:4]:
                print(f"  {line}")
        if rec.analysis.passed:
            print("\nPASS FOUND")
            print(f"candidate={c.name}")
            print(f"alpha_id={rec.alpha_id}")
            print(f"logs={rec.folder}")
            print(f"expression={c.expression}")
            print(f"settings={json.dumps(rec.settings, sort_keys=True)}")
            return 0

    print("\nNo passing alpha in selected attempts.")
    if best is not None:
        print(f"Best observed: attempt={best.attempt} alpha_id={best.alpha_id}")
        print(best.analysis.summary)
        print(f"expression={best.expression}")
        print(f"settings={json.dumps(best.settings, sort_keys=True)}")
        print(f"logs={best.folder}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
