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
