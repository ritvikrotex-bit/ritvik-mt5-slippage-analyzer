"""
Configuration constants for the slippage analyzer.
Edit CONTRACT_SIZES to add more instruments.
"""
import re

# ---------------------------------------------------------------------------
# Comment regex — primary pattern matches MT5 format: [tp 4779.90] / [sl 4779.90]
# Case-insensitive, tolerant of whitespace, tolerant of comma decimals (European).
# ---------------------------------------------------------------------------
COMMENT_RE_PRIMARY = re.compile(
    r"\[\s*(tp|sl)\s*([\d.,]+)\s*\]",
    re.IGNORECASE,
)

# Fallback pattern for non-standard broker comments: [t/p 100], [s.l 100], [t-p 100]
COMMENT_RE_FALLBACK = re.compile(
    r"\[\s*([ts])\s*[/\.\-\\]?\s*([pl])\s*([\d.,]+)\s*\]",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Header detection — we find the Deals header by token matching, not by row
# number. A row is the header if at least MIN_HEADER_MATCHES of these tokens
# appear in it (case-insensitive).
# ---------------------------------------------------------------------------
REQUIRED_HEADER_TOKENS = {
    "time", "deal", "symbol", "type", "direction",
    "volume", "price", "order", "commission", "comment",
}
MIN_HEADER_MATCHES = 6
MUST_HAVE_TOKENS = {"deal", "direction"}  # disambiguates Deals from Positions/Orders headers

# ---------------------------------------------------------------------------
# Row filtering
# ---------------------------------------------------------------------------
VALID_DIRECTION = "out"
VALID_TYPES = {"buy", "sell"}

# ---------------------------------------------------------------------------
# Contract sizes per symbol (used for USD slippage). Strip suffixes (.lp, .r, #)
# before lookup. DEFAULT is used when symbol unknown — a warning is logged.
# ---------------------------------------------------------------------------
CONTRACT_SIZES = {
    "XAUUSD": 100,      # gold: 100 oz / lot
    "XAGUSD": 5000,     # silver: 5000 oz / lot
    "XPTUSD": 100,      # platinum
    "XPDUSD": 100,      # palladium
    "EURUSD": 100000,   # FX majors: 100k units / standard lot
    "GBPUSD": 100000,
    "USDJPY": 100000,
    "USDCHF": 100000,
    "AUDUSD": 100000,
    "USDCAD": 100000,
    "NZDUSD": 100000,
    "BTCUSD": 1,        # crypto: 1 coin / lot
    "ETHUSD": 1,
}
DEFAULT_CONTRACT_SIZE = None  # None -> USD column shows as "unknown" rather than wrong


# ===========================================================================
# Phase 2 additions — pending order analysis.
# Append-only. Constants above this line are immutable (LOGIC_LOCK.md §10).
# ===========================================================================

# Orders section header detection. Sits above the Deals section in MT5
# reports: Open Time | Order | Symbol | Type | Volume | Price | S/L | T/P
# | Time | State | Comment.
ORDERS_REQUIRED_HEADER_TOKENS = {
    "open time", "order", "symbol", "type", "volume",
    "price", "s / l", "t / p", "time", "state",
}
ORDERS_MIN_HEADER_MATCHES = 6
ORDERS_MUST_HAVE_TOKENS = {"state", "open time"}

# Only "filled" orders correspond to executed deals worth slippage analysis.
VALID_ORDER_STATE = "filled"

# Pending order types we calculate slippage for. Market 'buy'/'sell' orders
# from the Orders section are NOT included — those have no requested price
# distinct from the market itself.
PENDING_ORDER_TYPES = {
    "buy limit",
    "sell limit",
    "buy stop",
    "sell stop",
    "buy stop limit",
    "sell stop limit",
}
