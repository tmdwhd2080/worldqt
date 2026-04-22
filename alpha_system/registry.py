"""Loads allowed operators and datafields from the CSVs in data/."""
from __future__ import annotations
import csv
from dataclasses import dataclass, field
from functools import lru_cache
from .config import OPERATORS_CSV, DATAFIELDS_CSV


@dataclass(frozen=True)
class Operator:
    name: str
    category: str
    scope: str
    definition: str
    description: str
    level: str


@dataclass(frozen=True)
class DataField:
    id: str
    description: str
    region: str
    delay: int
    universe: str
    type: str
    category: str


class Registry:
    """Lookups for operators and datafields. Loaded once, cached in-process."""

    def __init__(self) -> None:
        self.operators: dict[str, Operator] = {}
        self.datafields: dict[str, DataField] = {}
        self._load_operators()
        self._load_datafields()

    def _load_operators(self) -> None:
        with OPERATORS_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                self.operators[name] = Operator(
                    name=name,
                    category=(row.get("category") or "").strip(),
                    scope=(row.get("scope") or "").strip(),
                    definition=(row.get("definition") or "").strip(),
                    description=(row.get("description") or "").strip(),
                    level=(row.get("level") or "").strip(),
                )

    def _load_datafields(self) -> None:
        with DATAFIELDS_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fid = (row.get("id") or "").strip()
                if not fid:
                    continue
                try:
                    delay = int(float(row.get("delay") or 0))
                except (TypeError, ValueError):
                    delay = 0
                # Keep the first occurrence; many fields are duplicated across universes.
                if fid in self.datafields:
                    continue
                self.datafields[fid] = DataField(
                    id=fid,
                    description=(row.get("description") or "").strip(),
                    region=(row.get("region") or "").strip(),
                    delay=delay,
                    universe=(row.get("universe") or "").strip(),
                    type=(row.get("type") or "").strip(),
                    category=(row.get("category") or "").strip(),
                )

    def is_operator(self, name: str) -> bool:
        return name in self.operators

    def is_datafield(self, name: str) -> bool:
        return name in self.datafields


@lru_cache(maxsize=1)
def get_registry() -> Registry:
    return Registry()
