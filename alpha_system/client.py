"""WorldQuant BRAIN REST API client.

Handles authentication, simulation submission, status polling, and alpha retrieval.
"""
from __future__ import annotations
import time
from typing import Any
import requests
from requests.auth import HTTPBasicAuth

from .config import (
    AUTH_URL,
    SIMULATIONS_URL,
    ALPHAS_URL,
    SIMULATION_POLL_INTERVAL,
    SIMULATION_MAX_WAIT,
)
from .credentials import Credentials, load_credentials


class BrainAuthError(RuntimeError):
    pass


class BrainSimulationError(RuntimeError):
    pass


class BrainClient:
    def __init__(self, credentials: Credentials | None = None, timeout: float = 30.0):
        self.credentials = credentials or load_credentials()
        self.session = requests.Session()
        self.timeout = timeout
        self._authenticated = False

    def authenticate(self) -> None:
        resp = self.session.post(
            AUTH_URL,
            auth=HTTPBasicAuth(self.credentials.email, self.credentials.password),
            timeout=self.timeout,
        )
        if resp.status_code == 201:
            self._authenticated = True
            return
        if resp.status_code == 401:
            raise BrainAuthError(
                "401 Unauthorized. Verify credentials.json email/password are correct."
            )
        # Some accounts require biometric/MFA — server responds 201 with a
        # persona payload that still needs an extra handshake. Surface it clearly.
        try:
            body = resp.json()
        except Exception:
            body = {"text": resp.text[:500]}
        raise BrainAuthError(
            f"Authentication failed (HTTP {resp.status_code}): {body}"
        )

    def _ensure_auth(self) -> None:
        if not self._authenticated:
            self.authenticate()

    def submit_simulation(self, expression: str, settings: dict[str, Any]) -> str:
        """Submit a regular alpha simulation. Returns the progress-URL for polling."""
        self._ensure_auth()
        payload = {
            "type": "REGULAR",
            "settings": settings,
            "regular": expression,
        }
        resp = self.session.post(SIMULATIONS_URL, json=payload, timeout=self.timeout)
        if resp.status_code == 401:
            # session expired — re-auth once
            self._authenticated = False
            self._ensure_auth()
            resp = self.session.post(SIMULATIONS_URL, json=payload, timeout=self.timeout)
        if resp.status_code not in (200, 201):
            raise BrainSimulationError(
                f"Simulation submit failed (HTTP {resp.status_code}): {resp.text[:500]}"
            )
        progress_url = resp.headers.get("Location") or resp.headers.get("location")
        if not progress_url:
            try:
                body = resp.json()
                progress_url = body.get("location") or body.get("Location")
            except Exception:
                pass
        if not progress_url:
            raise BrainSimulationError(
                "Simulation submit returned no Location header. "
                f"Headers: {dict(resp.headers)}, body: {resp.text[:300]}"
            )
        return progress_url

    def poll_simulation(
        self,
        progress_url: str,
        poll_interval: float = SIMULATION_POLL_INTERVAL,
        max_wait: float = SIMULATION_MAX_WAIT,
    ) -> dict[str, Any]:
        """Poll until the simulation completes. Returns the final progress payload."""
        self._ensure_auth()
        start = time.monotonic()
        while True:
            resp = self.session.get(progress_url, timeout=self.timeout)
            if resp.status_code == 401:
                self._authenticated = False
                self._ensure_auth()
                continue
            if resp.status_code not in (200, 201):
                raise BrainSimulationError(
                    f"Poll failed (HTTP {resp.status_code}): {resp.text[:500]}"
                )
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                # Still running. Wait the suggested amount then retry.
                try:
                    wait = float(retry_after)
                except ValueError:
                    wait = poll_interval
                if time.monotonic() - start + wait > max_wait:
                    raise BrainSimulationError(
                        f"Simulation exceeded max_wait={max_wait}s while still running."
                    )
                time.sleep(max(wait, 1.0))
                continue
            # No Retry-After → complete (or errored)
            try:
                body = resp.json()
            except Exception as e:
                raise BrainSimulationError(f"Non-JSON completion body: {e}: {resp.text[:300]}")
            return body

    def get_alpha(self, alpha_id: str) -> dict[str, Any]:
        self._ensure_auth()
        resp = self.session.get(f"{ALPHAS_URL}/{alpha_id}", timeout=self.timeout)
        if resp.status_code == 401:
            self._authenticated = False
            self._ensure_auth()
            resp = self.session.get(f"{ALPHAS_URL}/{alpha_id}", timeout=self.timeout)
        if resp.status_code != 200:
            raise BrainSimulationError(
                f"Get alpha failed (HTTP {resp.status_code}): {resp.text[:500]}"
            )
        return resp.json()

    def run_simulation(
        self,
        expression: str,
        settings: dict[str, Any],
        poll_interval: float = SIMULATION_POLL_INTERVAL,
        max_wait: float = SIMULATION_MAX_WAIT,
    ) -> dict[str, Any]:
        """High-level: submit → poll → fetch alpha. Returns combined result dict.

        Structure:
            {
              "progress": <progress payload>,
              "alpha": <alpha payload or None if simulation errored>,
              "alpha_id": <id or None>,
              "status": <"COMPLETE" | "ERROR" | "WARNING" | ...>,
              "message": <error message if any>,
            }
        """
        progress_url = self.submit_simulation(expression, settings)
        progress = self.poll_simulation(progress_url, poll_interval, max_wait)
        status = progress.get("status", "UNKNOWN")
        alpha_id = progress.get("alpha")
        message = progress.get("message")
        alpha = self.get_alpha(alpha_id) if alpha_id else None
        return {
            "progress": progress,
            "alpha": alpha,
            "alpha_id": alpha_id,
            "status": status,
            "message": message,
        }
