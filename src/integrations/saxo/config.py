"""
Saxo OpenAPI — configuration loader.

Reads environment variables and exposes them as an immutable SaxoConfig dataclass.
All variables have sensible SIM-environment defaults except SAXO_CLIENT_ID,
which must always be set explicitly.

Environment variables:
    SAXO_CLIENT_ID     — app client ID from developer.saxobank.com  (required)
    SAXO_REDIRECT_URI  — must match the URI registered in the Saxo app
                         default: http://localhost:8501/
    SAXO_AUTH_BASE     — base URL for authorize + token endpoints
                         default: https://sim.logonvalidation.net
    SAXO_OPENAPI_BASE  — base URL for all OpenAPI calls
                         default: https://gateway.saxobank.com/sim/openapi
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SaxoConfig:
    client_id:    str
    redirect_uri: str
    auth_base:    str   # e.g. https://sim.logonvalidation.net
    openapi_base: str   # e.g. https://gateway.saxobank.com/sim/openapi

    @property
    def authorize_url(self) -> str:
        return f"{self.auth_base}/authorize"

    @property
    def token_url(self) -> str:
        return f"{self.auth_base}/token"


def load_config() -> SaxoConfig:
    """
    Load Saxo configuration from environment variables.

    Raises:
        KeyError: if SAXO_CLIENT_ID is not set.
    """
    client_id = os.environ.get("SAXO_CLIENT_ID", "").strip()
    if not client_id:
        raise KeyError(
            "SAXO_CLIENT_ID is not set. "
            "Register your app at developer.saxobank.com and add it to .env."
        )

    return SaxoConfig(
        client_id=client_id,
        redirect_uri=os.environ.get(
            "SAXO_REDIRECT_URI", "http://localhost:8501/"
        ).strip(),
        auth_base=os.environ.get(
            "SAXO_AUTH_BASE", "https://sim.logonvalidation.net"
        ).strip().rstrip("/"),
        openapi_base=os.environ.get(
            "SAXO_OPENAPI_BASE", "https://gateway.saxobank.com/sim/openapi"
        ).strip().rstrip("/"),
    )


def is_configured() -> bool:
    """Return True if the minimum required env var (SAXO_CLIENT_ID) is set."""
    return bool(os.environ.get("SAXO_CLIENT_ID", "").strip())
