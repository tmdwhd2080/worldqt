"""Validate that an alpha expression uses only allowed operators and datafields."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from .registry import Registry, get_registry

# FASTEXPR reserved words / group identifiers / constants that are NOT operators
# or datafields but are legal inside expressions.
_RESERVED = frozenset({
    "true", "false", "nan", "inf",
    # group identifiers commonly used with group_* operators
    "market", "sector", "industry", "subindustry", "country", "exchange",
    "densify", "pasteurize",
    # arithmetic/statistical helper args
    "filter", "constant", "std",
})

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class ValidationResult:
    ok: bool
    unknown: list[str] = field(default_factory=list)
    operators_used: list[str] = field(default_factory=list)
    datafields_used: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = []
        lines.append(f"ok={self.ok}")
        lines.append(f"operators: {sorted(set(self.operators_used))}")
        lines.append(f"datafields: {sorted(set(self.datafields_used))}")
        if self.unknown:
            lines.append(f"UNKNOWN (not in operators/datafields/reserved): {sorted(set(self.unknown))}")
        return "\n".join(lines)


def _strip_strings_and_comments(expr: str) -> str:
    """Remove double-quoted strings and line/block comments so we don't match inside them."""
    # Block comments /* ... */
    expr = re.sub(r"/\*.*?\*/", " ", expr, flags=re.DOTALL)
    # Line comments //... or # ...
    expr = re.sub(r"//[^\n]*", " ", expr)
    expr = re.sub(r"#[^\n]*", " ", expr)
    # Double-quoted strings
    expr = re.sub(r'"[^"]*"', " ", expr)
    # Single-quoted strings
    expr = re.sub(r"'[^']*'", " ", expr)
    return expr


def validate_expression(expression: str, registry: Registry | None = None) -> ValidationResult:
    """Scan the expression and classify every identifier.

    Returns a ValidationResult where ``unknown`` lists any identifier that is not
    a known operator, known datafield, or reserved keyword. ``ok`` is True iff
    ``unknown`` is empty.
    """
    reg = registry or get_registry()
    cleaned = _strip_strings_and_comments(expression)
    idents = _IDENT_RE.findall(cleaned)

    ops: list[str] = []
    fields_: list[str] = []
    unknown: list[str] = []
    for ident in idents:
        if ident in _RESERVED:
            continue
        if reg.is_operator(ident):
            ops.append(ident)
        elif reg.is_datafield(ident):
            fields_.append(ident)
        else:
            unknown.append(ident)
    return ValidationResult(
        ok=len(unknown) == 0,
        unknown=unknown,
        operators_used=ops,
        datafields_used=fields_,
    )
