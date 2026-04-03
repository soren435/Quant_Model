"""
PKCE (Proof Key for Code Exchange) helpers — RFC 7636.

PKCE eliminates the need for a client secret by proving that the party
exchanging the authorization code is the same party that initiated the flow.

Flow:
    1. Generate a random code_verifier (high-entropy random string).
    2. Derive code_challenge = BASE64URL(SHA256(code_verifier)).
    3. Send code_challenge in the authorize request.
    4. Send code_verifier in the token exchange request.
    5. The authorization server verifies: SHA256(code_verifier) == code_challenge.

All functions are pure (no side effects) and safe to call from any thread.
"""
from __future__ import annotations

import base64
import hashlib
import secrets


def generate_code_verifier(length: int = 64) -> str:
    """
    Generate a cryptographically random code_verifier.

    RFC 7636 §4.1: The code verifier is a high-entropy cryptographic random
    string using unreserved characters [A-Z / a-z / 0-9 / "-" / "." / "_" / "~"]
    with a minimum length of 43 and maximum length of 128.

    Args:
        length: Number of random bytes before base64url encoding.
                The resulting string will be longer than `length`.
                Default 64 → ~86 character verifier (well within 128 max).

    Returns:
        URL-safe base64-encoded random string with padding stripped.
    """
    return secrets.token_urlsafe(length)


def generate_code_challenge(code_verifier: str) -> str:
    """
    Derive the S256 code_challenge from a code_verifier.

    code_challenge = BASE64URL(SHA256(ASCII(code_verifier)))

    Args:
        code_verifier: The plain-text verifier string.

    Returns:
        URL-safe base64-encoded SHA-256 digest, without padding.
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_state() -> str:
    """
    Generate a cryptographically random state nonce for CSRF protection.

    The state value is stored in session_state before the authorize redirect
    and validated when the callback arrives. A mismatch indicates a CSRF attempt.

    Returns:
        32-byte URL-safe random string (~43 characters).
    """
    return secrets.token_urlsafe(32)
