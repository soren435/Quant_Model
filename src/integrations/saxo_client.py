"""
Saxo Bank OpenAPI client — dotenv-based bearer-token auth, simulation-first.

Token setup (one-time):
    1. Copy .env.example to .env in the project root.
    2. Set SAXO_ACCESS_TOKEN to your Saxo bearer token.
    3. Set SAXO_ENV to "sim" (simulation gateway) or "live" (real trading).
    4. Restart the app — the token is loaded automatically.

Public API (all methods return plain dicts — no Streamlit dependency):

    client = SaxoClient()                  # reads .env; auto-detects state
    client.is_connected()                  # True in SIMULATION, SIM_API, or CONNECTED
    client.get_connection_state()          # ConnectionState enum value
    client.status()                        # UI-friendly status dict
    client.get_account_info()              # always returns a dict
    client.get_cash_balance()              # always returns a dict
    client.lookup_instrument(ticker)       # dict | None
    client.build_order_payload(...)        # dict (does not submit)
    client.simulate_order(payload)         # dict — always dry-run, no real trade
    client.place_order(payload, confirmed) # dict — real only if live+confirmed

Connection states:
    SIMULATION    — no token; returns internal mock data, no API calls
    SIM_API       — SAXO_ENV=sim + token; real API calls to sim gateway, no real money
    NOT_CONNECTED — SAXO_ENV=live, no SAXO_ACCESS_TOKEN set
    CONNECTED     — SAXO_ENV=live, valid token present
    AUTH_ERROR    — last API call returned an auth/network error

Saxo OpenAPI endpoints (reference):
    API gateway:  gateway.saxobank.com/sim/openapi  (sim)
                  gateway.saxobank.com/openapi       (live)
    Account:      GET  /port/v1/accounts/me
    Balance:      GET  /port/v1/balances/me
    Instruments:  GET  /ref/v1/instruments/
    Orders:       POST /trade/v2/orders
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from enum import Enum

# Load .env if python-dotenv is installed (optional dependency)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# SaxoAuth is imported lazily inside __init__ to avoid circular imports
# and to keep the client usable even without the auth module.
try:
    from src.integrations.saxo_auth import SaxoAuth as _SaxoAuth
    _AUTH_OK = True
except ImportError:
    _AUTH_OK = False


# ── Logging setup ──────────────────────────────────────────────────────────────

_LOG_DIR  = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "execution_log.jsonl")
os.makedirs(_LOG_DIR, exist_ok=True)

_fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(message)s"))
_logger = logging.getLogger("saxo_client")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    _logger.addHandler(_fh)


def _log(event: str, data: dict) -> str:
    """Write a JSON-Lines entry and return a human-readable summary string."""
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source":    "saxo_client",
        "event":     event,
        **data,
    }
    _logger.info(json.dumps(entry, ensure_ascii=False, default=str))
    return f"[{entry['timestamp']}] SAXO/{event.upper()}: {json.dumps(data, default=str)}"


# ── Connection state ───────────────────────────────────────────────────────────

class ConnectionState(str, Enum):
    """Possible broker connection states exposed to the UI."""
    SIMULATION    = "simulation"     # no token — internal mock data, no API calls
    SIM_API       = "sim_api"        # token + sim gateway — real calls, no real money
    NOT_CONNECTED = "not_connected"  # live env, no valid token
    CONNECTED     = "connected"      # live env, authenticated
    AUTH_ERROR    = "auth_error"     # last API call returned an auth/network error


# State → display label and colour hint for the UI
_STATE_LABELS: dict[ConnectionState, tuple[str, str]] = {
    ConnectionState.SIMULATION:    ("🟡 Simulation",    "orange"),
    ConnectionState.SIM_API:       ("🟢 SIM API",       "green"),
    ConnectionState.NOT_CONNECTED: ("⚪ Not Connected",  "grey"),
    ConnectionState.CONNECTED:     ("🟢 Connected",      "green"),
    ConnectionState.AUTH_ERROR:    ("🔴 Auth Error",     "red"),
}


# ── Simulation mock data ───────────────────────────────────────────────────────

_MOCK_BALANCE: dict = {
    "AccountId":                 "DEMO-12345678",
    "Currency":                  "DKK",
    "CashAvailableForTrading":   100_000.00,
    "TotalValue":                100_000.00,
    "MarginAvailableForTrading": 100_000.00,
    "_mode":                     "local_simulation",
}

# UIC numbers used for simulated instrument lookups
_MOCK_UICS: dict[str, int] = {
    "SPY": 1082832, "QQQ": 1082833, "IEF": 1082834,
    "TLT": 1082835, "AGG": 1082836, "GLD": 1082837,
    "VTI": 1082838, "IWDA": 1082839,
}


# ═══════════════════════════════════════════════════════════════════════════════

class SaxoClient:
    """
    Saxo Bank OpenAPI client with simulation-first architecture.

    Reads SAXO_ACCESS_TOKEN and SAXO_ENV from the environment (via .env).
    Defaults to simulation mode when no token is present or SAXO_ENV=sim.

    Args:
        simulation_mode: Optional override for simulation/live mode.
                         When None (default), determined by SAXO_ENV env var.
    """

    _SIM_BASE  = "https://gateway.saxobank.com/sim/openapi"
    _LIVE_BASE = "https://gateway.saxobank.com/openapi"

    def __init__(self, simulation_mode: bool | None = None) -> None:
        saxo_env  = os.getenv("SAXO_ENV", "sim").strip().lower()

        self._auth_error:      str | None = None
        self._use_sim_gateway: bool       = (saxo_env != "live")
        self._base = self._SIM_BASE if self._use_sim_gateway else self._LIVE_BASE

        # Prefer SaxoAuth (handles refresh). Fall back to bare env token.
        if _AUTH_OK:
            self._auth: _SaxoAuth | None = _SaxoAuth()
        else:
            self._auth = None

        # Resolve initial token
        self._token: str | None = self._resolve_token()

        # simulation_mode = use internal mock data (no real API calls).
        # Auto-detect: mock only when no token is available.
        if simulation_mode is None:
            self.simulation_mode = not bool(self._token)
        else:
            self.simulation_mode = simulation_mode

        _log("client_init", {
            "saxo_env":         saxo_env,
            "token_set":        bool(self._token),
            "auth_module":      _AUTH_OK,
            "simulation_mode":  self.simulation_mode,
            "use_sim_gateway":  self._use_sim_gateway,
        })

    def _resolve_token(self) -> str | None:
        """Return a valid token via SaxoAuth (with auto-refresh) or bare env var."""
        if self._auth is not None:
            try:
                return self._auth.get_valid_token()
            except Exception:
                pass
        # Fallback: raw env token (no refresh)
        raw = os.getenv("SAXO_ACCESS_TOKEN", "").strip()
        return raw or None

    def _fresh_token(self) -> str | None:
        """Re-resolve token before each API call so refreshes are picked up."""
        self._token = self._resolve_token()
        return self._token

    # ── Connection state ───────────────────────────────────────────────────────

    def get_connection_state(self) -> ConnectionState:
        """
        Return the current connection state.

          - simulation_mode=True           → SIMULATION (internal mock, no API calls)
          - token + sim gateway            → SIM_API (real calls to sim endpoint)
          - last API call failed           → AUTH_ERROR
          - live, no token                 → NOT_CONNECTED
          - live, token present            → CONNECTED
        """
        if self.simulation_mode:
            return ConnectionState.SIMULATION
        if self._auth_error:
            return ConnectionState.AUTH_ERROR
        if not self._token:
            return ConnectionState.NOT_CONNECTED
        if self._use_sim_gateway:
            return ConnectionState.SIM_API
        return ConnectionState.CONNECTED

    def is_connected(self) -> bool:
        """
        Return True if the client can service requests.

        True in SIMULATION (mock), SIM_API (sim gateway), and CONNECTED (live).
        """
        return self.get_connection_state() in (
            ConnectionState.SIMULATION,
            ConnectionState.SIM_API,
            ConnectionState.CONNECTED,
        )

    def status(self) -> dict:
        """
        Return a status dict safe for display in the UI.

        Keys: state, label, colour, simulation_mode, token_set,
              authenticated, auth_error, base_url
        """
        state = self.get_connection_state()
        label, colour = _STATE_LABELS[state]
        return {
            "state":            state.value,
            "label":            label,
            "colour":           colour,
            "simulation_mode":  self.simulation_mode,
            "use_sim_gateway":  self._use_sim_gateway,
            "token_set":        bool(self._token),
            "authenticated":    state in (ConnectionState.SIM_API, ConnectionState.CONNECTED),
            "auth_error":       self._auth_error,
            "base_url":         self._base,
        }

    # ── Account ────────────────────────────────────────────────────────────────

    def get_account_info(self) -> dict:
        """
        Return account details.

        Always returns a dict with at minimum:
            connected (bool)
            AccountId (str | None)
            Currency  (str | None)
            status    (str)  — "local_simulation" | "sim_api" | "connected" |
                               "not_connected" | "error"
            _mode     (str)  — "local_simulation" | "sim_api" | "live"

        Additional keys may be present when connected to a real account.
        The "error" key is added (with an error message) when status="error".
        """
        if self.simulation_mode:
            return {
                "connected":  True,
                "AccountId":  "DEMO-12345678",
                "AccountKey": "DEMO-KEY",
                "ClientKey":  "DEMO-CLIENT-KEY",
                "Currency":   "DKK",
                "status":     "local_simulation",
                "raw":        {},
            }

        if not self._token:
            return {
                "connected":  False,
                "AccountId":  None,
                "AccountKey": None,
                "ClientKey":  None,
                "Currency":   None,
                "status":     "not_connected",
                "raw":        {},
            }

        mode = "sim_api" if self._use_sim_gateway else "live_api"
        try:
            result = self._get("/port/v1/accounts/me")
            if not isinstance(result, dict) or not result:
                raise ValueError("Empty or invalid response from /port/v1/accounts/me.")

            # The API returns {"Data": [...], "__count": N} — unwrap first item
            data_list = result.get("Data")
            account = data_list[0] if isinstance(data_list, list) and data_list else result

            self._auth_error = None
            return {
                "connected":  True,
                "AccountId":  account.get("AccountId"),
                "AccountKey": account.get("AccountKey"),
                "ClientKey":  account.get("ClientKey"),
                "Currency":   account.get("Currency"),
                "status":     mode,
                "raw":        account,
            }
        except Exception as exc:
            self._auth_error = str(exc)
            _log("get_account_info_error", {"error": str(exc)})
            return {
                "connected":  False,
                "AccountId":  None,
                "AccountKey": None,
                "ClientKey":  None,
                "Currency":   None,
                "status":     "error",
                "raw":        {},
                "error":      str(exc),
            }

    def get_cash_balance(self) -> dict:
        """
        Return available cash balance.

        Always returns a dict with at least:
            connected (bool)
            cash      (float | None)
            currency  (str | None)
            status    (str)  — "local_simulation" | "sim_api" | "live_api" | "error"
            raw       (dict) — full API response or empty dict
        """
        if self.simulation_mode or not self._token:
            mock = _MOCK_BALANCE
            return {
                "connected": True,
                "cash":      mock["CashAvailableForTrading"],
                "currency":  mock["Currency"],
                "status":    "local_simulation",
                "raw":       mock,
            }

        mode = "sim_api" if self._use_sim_gateway else "live_api"
        try:
            result = self._get("/port/v1/balances/me")
            if not isinstance(result, dict) or not result:
                raise ValueError("Empty or invalid response from /port/v1/balances/me.")
            self._auth_error = None
            return {
                "connected": True,
                "cash":      result.get("CashAvailableForTrading"),
                "currency":  result.get("Currency"),
                "status":    mode,
                "raw":       result,
            }
        except Exception as exc:
            self._auth_error = str(exc)
            _log("get_cash_balance_error", {"error": str(exc)})
            return {
                "connected": False,
                "cash":      None,
                "currency":  None,
                "status":    "error",
                "raw":       {},
                "error":     str(exc),
            }

    # ── Instruments ────────────────────────────────────────────────────────────

    # Exchanges preferred for US-listed ETFs (NYSE Arca is the primary one).
    # These are the lowercase exchange suffixes found in Saxo's Symbol field
    # (e.g. "SPY:arcx" → exchange suffix "arcx").
    _ETF_PREFERRED_EXCHANGES: frozenset[str] = frozenset(
        {"arcx", "xnas", "xnys", "xase", "bats"}
    )

    # Asset types queried when the caller does not specify one.
    # The Saxo ref/v1/instruments endpoint accepts only one AssetTypes value
    # per request, so we issue one request per type and merge the results.
    _DEFAULT_ASSET_TYPES: tuple[str, ...] = ("Etf", "EtcEtp", "Stock")

    @staticmethod
    def _parse_symbol(raw_symbol: str) -> tuple[str, str]:
        """
        Split a Saxo symbol string into (ticker, exchange).

        The Saxo instruments endpoint returns Symbol as "TICKER:exchange"
        (e.g. "SPY:arcx", "IEF:arcx").  For symbols without a colon the
        exchange part is returned as an empty string.
        """
        if ":" in raw_symbol:
            parts = raw_symbol.split(":", 1)
            return parts[0].upper(), parts[1].lower()
        return raw_symbol.upper(), ""

    def _score_instrument(self, candidate: dict, ticker: str) -> int:
        """
        Return a ranking score for a candidate instrument (higher = better).

        Scoring rules:
          +100  ticker part of Symbol matches the requested ticker exactly
                (case-insensitive); e.g. "SPY:arcx" → ticker "SPY"
          + 20  AssetType is "Etf" or "EtcEtp"
          + 10  exchange suffix is a preferred US venue
          +  5  exchange suffix is "arcx" (NYSE Arca — primary ETF venue)
        """
        score = 0
        raw_symbol = candidate.get("Symbol", "")
        sym_ticker, sym_exchange = self._parse_symbol(raw_symbol)
        asset_type = candidate.get("AssetType", "")

        if sym_ticker == ticker.upper():
            score += 100

        if asset_type.lower() in ("etf", "etcetp"):
            score += 20

        if sym_exchange in self._ETF_PREFERRED_EXCHANGES:
            score += 10

        if sym_exchange == "arcx":
            score += 5

        return score

    def lookup_instrument(
        self,
        ticker:     str,
        asset_type: str | None = None,
        *,
        top:        int = 10,
    ) -> dict | None:
        """
        Look up a Saxo instrument by ticker symbol using ranked selection.

        Issues one API request per asset type (the Saxo ref endpoint only
        accepts a single AssetTypes value), merges all results, scores each
        candidate, and returns the highest-scoring match.

        Scoring prefers (in order):
          1. Exact ticker match — Symbol "SPY:arcx" → ticker "SPY"
          2. ETF / EtcEtp asset type
          3. Preferred US exchange (NYSE Arca > NASDAQ / NYSE)

        The full scored candidate list is stored in
        ``self._last_lookup_candidates`` for inspection / debugging.

        Returns a dict with at least 'Identifier' (UIC), 'AssetType',
        'Symbol', and 'Description', or None if not found.
        Returns simulated data in simulation mode or when no token is set.

        Args:
            ticker:     Ticker symbol (e.g. "SPY", "IWDA").
            asset_type: Saxo AssetType to filter by (e.g. "Etf", "Stock").
                        When None (default), queries "Etf", "EtcEtp", and
                        "Stock" in separate requests and merges results.
            top:        Results to fetch per asset-type request (default 10).
        """
        self._last_lookup_candidates: list[dict] = []

        if not ticker or not ticker.strip():
            return None

        ticker_clean = ticker.strip().upper()

        if self.simulation_mode or not self._token:
            mock = self._mock_instrument(ticker_clean, asset_type or "Etf")
            self._last_lookup_candidates = [mock]
            return mock

        asset_types: tuple[str, ...] = (
            (asset_type,) if asset_type
            else self._DEFAULT_ASSET_TYPES
        )

        # One request per asset type; merge into a single candidate pool.
        all_candidates: list[dict] = []
        for at in asset_types:
            params: dict = {
                "Keywords":   ticker_clean,
                "AssetTypes": at,
                "$top":       top,
            }
            try:
                result = self._get("/ref/v1/instruments/", params=params)
            except Exception:
                continue   # skip this asset type on error; others may succeed
            if not isinstance(result, dict):
                continue
            data = result.get("Data")
            if isinstance(data, list):
                all_candidates.extend(c for c in data if isinstance(c, dict))

        if not all_candidates:
            return None

        # Deduplicate by Identifier (UIC) — keep first occurrence
        seen: set[int] = set()
        unique: list[dict] = []
        for c in all_candidates:
            uid = c.get("Identifier")
            if uid not in seen:
                seen.add(uid)
                unique.append(c)

        # Score every candidate and sort descending
        scored: list[tuple[int, dict]] = [
            (self._score_instrument(c, ticker_clean), c)
            for c in unique
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        # Store annotated candidates for debugging / inspection
        self._last_lookup_candidates = [
            {**c, "_score": s} for s, c in scored
        ]

        best_score, best = scored[0]
        _log("lookup_instrument", {
            "ticker":          ticker_clean,
            "candidates_seen": len(scored),
            "top_score":       best_score,
            "top_symbol":      best.get("Symbol"),
        })

        return best

    def debug_lookup(self, ticker: str, asset_type: str | None = None) -> None:
        """
        Print the top instrument candidates for *ticker* to stdout.

        Calls lookup_instrument() internally, then prints each candidate with
        its score, UIC, AssetType, Symbol, Description, and ExchangeId.
        Useful for verifying the ranking logic during development.

        Example::

            client.debug_lookup("SPY")
            client.debug_lookup("IEF")
        """
        best = self.lookup_instrument(ticker, asset_type)
        candidates = getattr(self, "_last_lookup_candidates", [])

        print(f"\n── lookup_instrument({ticker!r}) ─────────────────────────")
        if best:
            print(
                f"  Best match : UIC={best.get('Identifier')}  "
                f"AssetType={best.get('AssetType')}  "
                f"Symbol={best.get('Symbol')}  "
                f"Desc={best.get('Description', '')}"
            )
        else:
            print("  Best match : None")
        print(f"  Candidates ({len(candidates)} scored):")
        for i, c in enumerate(candidates[:10]):   # show at most 10
            print(
                f"  [{i+1:2d}] score={c.get('_score'):>4}  "
                f"UIC={str(c.get('Identifier')):<10}  "
                f"AssetType={c.get('AssetType', ''):<12}  "
                f"Symbol={c.get('Symbol', ''):<14}  "
                f"Desc={c.get('Description', '')[:50]}"
            )
        print()

    def _mock_instrument(self, ticker: str, asset_type: str) -> dict:
        """Return a simulated instrument lookup result."""
        return {
            "Uic":          _MOCK_UICS.get(ticker, 9_000_000 + abs(hash(ticker)) % 1_000_000),
            "Symbol":       ticker,
            "Description":  f"{ticker} (simulated instrument lookup)",
            "AssetType":    asset_type,
            "CurrencyCode": "USD",
            "_simulated":   True,
        }

    # ── Orders ─────────────────────────────────────────────────────────────────

    def build_order_payload(
        self,
        uic:        int,
        asset_type: str,
        buy_sell:   str,
        amount:     int,
        order_type: str = "Market",
    ) -> dict:
        """
        Build a Saxo-compatible order payload dict.

        Does NOT submit the order. Pass the result to simulate_order() or
        place_order() to execute.

        Args:
            uic:        Saxo Universal Instrument Code (from lookup_instrument).
            asset_type: Saxo AssetType string (e.g. "Stock", "Etf").
            buy_sell:   "Buy" or "Sell".
            amount:     Number of whole shares / units.
            order_type: "Market" (default) or "Limit".
        """
        if buy_sell not in ("Buy", "Sell"):
            raise ValueError(f"buy_sell must be 'Buy' or 'Sell', got: {buy_sell!r}")
        if amount <= 0:
            raise ValueError(f"amount must be a positive integer, got: {amount}")

        return {
            "Uic":           uic,
            "AssetType":     asset_type,
            "BuySell":       buy_sell,
            "Amount":        amount,
            "OrderType":     order_type,
            "ManualOrder":   True,
            "OrderDuration": {"DurationType": "DayOrder"},
            "_simulation":   self.simulation_mode,
            "_built_at":     datetime.now().isoformat(timespec="seconds"),
        }

    def simulate_order(self, payload: dict) -> dict:
        """
        Perform a dry-run of an order without sending anything to the broker.

        Always safe — never places a real trade regardless of any setting.

        Returns:
            Dict with keys: success, simulated (True), order_id, message, payload
        """
        if not isinstance(payload, dict):
            return {
                "success":   False,
                "simulated": True,
                "order_id":  None,
                "message":   "Invalid payload — expected a dict.",
                "payload":   payload,
            }

        order_id = f"SIM-{abs(hash(str(payload))) % 1_000_000:06d}"
        result = {
            "success":   True,
            "simulated": True,
            "order_id":  order_id,
            "message":   (
                "Dry-run successful — no real trade was placed. "
                "Set SAXO_ENV=live in .env and pass confirmed=True to execute."
            ),
            "payload":   payload,
        }
        _log("order_simulated", {"order_id": order_id, "payload": payload})
        return result

    def place_order(self, payload: dict, confirmed: bool = False) -> dict:
        """
        Submit an order — simulation or live, depending on current state.

        Safety gate: a real order is placed only when BOTH conditions hold:
          1. simulation_mode is False
          2. confirmed is True

        In all other cases the order is dry-run via simulate_order().

        Returns:
            Dict with keys: success, simulated, order_id, message, payload
        """
        if self.simulation_mode or not confirmed:
            return self.simulate_order(payload)

        if not self._token:
            err = "Not authenticated — cannot place a live order."
            _log("order_rejected", {"reason": err})
            return {"success": False, "simulated": False,
                    "order_id": None, "message": err, "payload": payload}

        if not _REQUESTS_OK:
            err = "`requests` library not available."
            return {"success": False, "simulated": False,
                    "order_id": None, "message": err, "payload": payload}

        try:
            resp_data = self._post("/trade/v2/orders", body=payload)
            if not isinstance(resp_data, dict):
                raise ValueError("Unexpected response format from orders endpoint.")
            order_id = resp_data.get("OrderId", "UNKNOWN")
            _log("order_placed_live", {"order_id": order_id, "payload": payload})
            return {
                "success":   True,
                "simulated": False,
                "order_id":  order_id,
                "message":   "Live order placed successfully.",
                "payload":   payload,
            }
        except Exception as exc:
            _log("order_error", {"error": str(exc), "payload": payload})
            return {
                "success":   False,
                "simulated": False,
                "order_id":  None,
                "message":   str(exc),
                "payload":   payload,
            }

    # ── HTTP helpers (live path only) ──────────────────────────────────────────

    def _auth_headers(self) -> dict:
        token = self._fresh_token() or self._token or ""
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        """Authenticated GET to the Saxo API. Returns parsed JSON or None."""
        if not _REQUESTS_OK:
            return None
        try:
            resp = _requests.get(
                f"{self._base}{path}",
                headers=self._auth_headers(),
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            _log("http_get_error", {"path": path, "error": str(exc)})
            raise

    def _post(self, path: str, body: dict) -> dict:
        """Authenticated POST to the Saxo API. Raises on HTTP errors."""
        if not _REQUESTS_OK:
            raise RuntimeError("`requests` library not available.")
        resp = _requests.post(
            f"{self._base}{path}",
            headers=self._auth_headers(),
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
