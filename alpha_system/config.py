"""Configuration: endpoints, pass criteria, default simulation settings."""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ALPHAS_DIR = ROOT / "alphas"
CREDENTIALS_PATH = ROOT / "credentials.json"

OPERATORS_CSV = DATA_DIR / "brain_operators (1).csv"
DATAFIELDS_CSV = DATA_DIR / "IQC_brain_datafields (1).csv"

BRAIN_API_BASE = "https://api.worldquantbrain.com"
AUTH_URL = f"{BRAIN_API_BASE}/authentication"
SIMULATIONS_URL = f"{BRAIN_API_BASE}/simulations"
ALPHAS_URL = f"{BRAIN_API_BASE}/alphas"


@dataclass(frozen=True)
class PassCriteria:
    """Thresholds derived from the IQC 2026 Stage 1 screenshot."""
    sharpe_min: float = 1.25
    fitness_min: float = 1.0
    sub_universe_sharpe_min: float = -0.16
    turnover_min: float = 0.01
    turnover_max: float = 0.70
    required_competitions: tuple[str, ...] = (
        "International Quant Championship 2026 Stage 1",
    )


PASS_CRITERIA = PassCriteria()

DEFAULT_SETTINGS: dict[str, Any] = {
    "instrumentType": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 0,
    "neutralization": "SUBINDUSTRY",
    "truncation": 0.08,
    "pasteurization": "ON",
    "unitHandling": "VERIFY",
    "nanHandling": "OFF",
    "language": "FASTEXPR",
    "visualization": False,
}

SIMULATION_POLL_INTERVAL = 5.0
SIMULATION_MAX_WAIT = 600.0
