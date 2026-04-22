"""Ad-hoc driver to iterate on the 52-week-high + capital-flow idea.

Run a single expression when invoked; prints summary + feedback.

Usage:
    python run_iteration.py v1
"""
from __future__ import annotations
import sys
import io
import json
from alpha_system.runner import Runner
from alpha_system.validator import validate_expression

# Force UTF-8 stdout so Windows cp949 console doesn't choke on symbols.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

IDEA = "52w_high_cap_flow_long_short"

EXPRESSIONS = {
    "v1": "(ts_rank(close, 252) - 0.5) * ts_decay_linear(ts_delta(rank(cap), 21), 10)",
    # v2: decouple price from flow. Use volume surge (5d mean / 60d mean) as the
    # flow proxy — independent of price so we aren't double-counting momentum.
    # zscore at the end → better weight distribution.
    "v2": (
        "zscore("
        "  (ts_rank(close, 252) - 0.5) "
        "  * ts_decay_linear(ts_mean(volume, 5) / ts_mean(volume, 60) - 1, 10)"
        ")"
    ),
    # v3: flip sign of v2 — if negative Sharpe is due to reversal-dominant regime
    # on TOP3000, inverted signal should give positive Sharpe.
    "v3": (
        "-1 * zscore("
        "  (ts_rank(close, 252) - 0.5) "
        "  * ts_decay_linear(ts_mean(volume, 5) / ts_mean(volume, 60) - 1, 10)"
        ")"
    ),
    # v4: true flow via short-interest decline (price-independent positioning).
    # Thesis: near 52w high + short interest falling (short-covering / shorts
    # capitulating) = real institutional flow confirming breakout → LONG;
    # near 52w high + short interest rising = SHORT.
    "v4": (
        "zscore("
        "  (ts_rank(close, 252) - 0.5) "
        "  * -1 * ts_decay_linear(ts_delta(news_short_interest, 20), 10)"
        ")"
    ),
    # v5: true flow via analyst_revision_rank_derivative (cov=1.0, proven).
    # Thesis: near 52w high + analysts revising estimates UP = real fundamental
    # flow confirming breakout → LONG. Opposite on downward revisions = SHORT.
    "v5": (
        "zscore("
        "  (ts_rank(close, 252) - 0.5) "
        "  * ts_decay_linear(analyst_revision_rank_derivative, 20)"
        ")"
    ),
}

SETTINGS_BY_VERSION: dict[str, dict] = {
    # version-specific setting overrides go here (e.g., {"decay": 4, "neutralization": "INDUSTRY"})
}


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python run_iteration.py <version>  (versions: {list(EXPRESSIONS)})")
        return 2
    version = sys.argv[1]
    if version not in EXPRESSIONS:
        print(f"Unknown version '{version}'. Available: {list(EXPRESSIONS)}")
        return 2
    expr = EXPRESSIONS[version]
    settings_override = SETTINGS_BY_VERSION.get(version, {}) or None

    print(f"=== {IDEA} / {version} ===")
    print(f"Expression: {expr}")
    if settings_override:
        print(f"Settings override: {settings_override}")
    print()

    # Validate offline first
    v = validate_expression(expr)
    print("--- Validation ---")
    print(v.report())
    print()
    if not v.ok:
        print("ABORT: unknown identifiers present.")
        return 1

    runner = Runner(idea=IDEA, strict_validation=True)
    rec = runner.run_attempt(expr, settings_override=settings_override, note=version)

    print("--- Analysis ---")
    print(f"passed={rec.analysis.passed}")
    print(f"summary: {rec.analysis.summary}")
    print()
    print("--- Checks ---")
    for c in rec.analysis.checks:
        mark = "PASS" if c.passed else "FAIL"
        print(f"  [{mark}] {c.name}: value={c.value} limit={c.limit}")
    if rec.analysis.feedback:
        print()
        print("--- Feedback ---")
        for line in rec.analysis.feedback:
            print(line)
    print()
    print(f"Alpha id: {rec.alpha_id}")
    print(f"Logs: {rec.folder}")
    return 0 if rec.analysis.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
