"""
Parse TP/SL trigger info from broker comment strings.

Handles all observed and reasonably foreseeable formats:
  - [tp 4779.90]       <- standard MT5
  - [sl 4779.90]
  - [TP 4779.90]       <- case variations
  - [ tp  4779.90 ]    <- whitespace
  - [tp 4,779.90]      <- comma thousands separator
  - [tp 4779,90]       <- European decimal comma
  - [t/p 4779.90]      <- localized variants (fallback regex)
  - "filled [tp 100]"  <- extra text around it (re.search not re.match)
"""
from typing import Optional, Tuple
from config import COMMENT_RE_PRIMARY, COMMENT_RE_FALLBACK


def _normalize_number(price_str: str) -> Optional[float]:
    """
    Convert a captured number string to float.
    Handles: "4779.90", "4,779.90", "4779,90", "4.779,90"
    """
    s = price_str.strip()
    if not s:
        return None

    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        # Both present — assume the rightmost is the decimal mark.
        # Example: "4,779.90" (US) -> last is "."  -> remove commas.
        #          "4.779,90" (EU) -> last is ","  -> remove dots, swap comma.
        if s.rfind(".") > s.rfind(","):
            s = s.replace(",", "")
        else:
            s = s.replace(".", "").replace(",", ".")
    elif has_comma and not has_dot:
        # Only comma — treat as decimal separator (European)
        s = s.replace(",", ".")
    # only dot or neither: nothing to do

    try:
        return float(s)
    except ValueError:
        return None


def parse_trigger(comment) -> Optional[Tuple[str, float]]:
    """
    Extract (trigger_type, trigger_price) from a broker comment.

    Returns:
        tuple ("TP"|"SL", price)  on success
        None                       if comment doesn't contain a recognizable trigger

    Never raises. Caller should treat None as "skip this row".
    """
    if comment is None:
        return None
    s = str(comment)
    if not s:
        return None

    # Try primary pattern first
    m = COMMENT_RE_PRIMARY.search(s)
    if m:
        trigger = m.group(1).upper()
        price = _normalize_number(m.group(2))
        if price is not None:
            return (trigger, price)

    # Fallback for [t/p 100], [s.l 100], etc.
    m = COMMENT_RE_FALLBACK.search(s)
    if m:
        first = m.group(1).lower()
        second = m.group(2).lower()
        # First letter says T or S, second says P or L
        if first == "t" and second == "p":
            trigger = "TP"
        elif first == "s" and second == "l":
            trigger = "SL"
        else:
            return None
        price = _normalize_number(m.group(3))
        if price is not None:
            return (trigger, price)

    return None
