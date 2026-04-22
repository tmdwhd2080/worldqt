"""CLI entry: test authentication, run a single attempt, or search operator/datafield.

Examples:
    python main.py auth
    python main.py search-op ts_rank
    python main.py search-field close
    python main.py validate 'ts_rank(close, 252)'
    python main.py run "breakout_idea" "ts_rank(close, 252)"
"""
from __future__ import annotations
import argparse
import sys

from alpha_system.client import BrainClient, BrainAuthError
from alpha_system.registry import get_registry
from alpha_system.validator import validate_expression
from alpha_system.runner import Runner


def cmd_auth(_args: argparse.Namespace) -> int:
    try:
        client = BrainClient()
        client.authenticate()
        print("Authentication OK. Session established.")
        return 0
    except BrainAuthError as e:
        print(f"Authentication failed: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2


def cmd_search_op(args: argparse.Namespace) -> int:
    reg = get_registry()
    q = args.query.lower()
    hits = [op for name, op in reg.operators.items() if q in name.lower()]
    for op in hits[:50]:
        print(f"{op.name:30s}  [{op.category}] {op.description[:80]}")
    print(f"\n{len(hits)} matches")
    return 0


def cmd_search_field(args: argparse.Namespace) -> int:
    reg = get_registry()
    q = args.query.lower()
    hits = [
        f for f in reg.datafields.values()
        if q in f.id.lower() or q in f.description.lower()
    ]
    for f in hits[:50]:
        print(f"{f.id:40s}  [{f.universe} delay={f.delay}] {f.description[:80]}")
    print(f"\n{len(hits)} matches (showing first 50)")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    result = validate_expression(args.expression)
    print(result.report())
    return 0 if result.ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    runner = Runner(idea=args.idea, strict_validation=args.strict)
    rec = runner.run_attempt(args.expression, note=args.note or "")
    print(f"Attempt {rec.attempt} — passed={rec.analysis.passed}")
    print(f"  {rec.analysis.summary}")
    if rec.analysis.feedback:
        print("\nFeedback:")
        for line in rec.analysis.feedback:
            print(f"  {line}")
    print(f"\nLogs written to: {rec.folder}")
    return 0 if rec.analysis.passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="WorldQuant BRAIN alpha iteration system")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth", help="Test BRAIN credentials").set_defaults(func=cmd_auth)

    p = sub.add_parser("search-op", help="Search operators")
    p.add_argument("query")
    p.set_defaults(func=cmd_search_op)

    p = sub.add_parser("search-field", help="Search datafields")
    p.add_argument("query")
    p.set_defaults(func=cmd_search_field)

    p = sub.add_parser("validate", help="Validate an expression uses only allowed names")
    p.add_argument("expression")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("run", help="Run one simulation attempt")
    p.add_argument("idea", help="Short name for the idea folder")
    p.add_argument("expression", help="FASTEXPR alpha expression")
    p.add_argument("--strict", action="store_true",
                   help="Refuse to submit if validator flags unknown identifiers")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
