"""Credential loader. Reads credentials.json (gitignored)."""
from __future__ import annotations
import json
from dataclasses import dataclass
from .config import CREDENTIALS_PATH


@dataclass(frozen=True)
class Credentials:
    email: str
    password: str


def load_credentials() -> Credentials:
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CREDENTIALS_PATH}. Copy credentials.example.json to "
            f"credentials.json and fill in your BRAIN email/password."
        )
    with CREDENTIALS_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    email = data.get("email", "").strip()
    password = data.get("password", "")
    if not email or not password:
        raise ValueError("credentials.json must contain non-empty 'email' and 'password'.")
    return Credentials(email=email, password=password)
