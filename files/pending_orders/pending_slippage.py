"""
Pending-order fill slippage math — isolated copy of the unified formula.

THE SINGLE RULE (identical to the TP/SL engine, intentionally duplicated
to preserve strict separation per LOGIC_LOCK.md §10):

    BUY-side  -> client gains when executed < reference
              -> client_points = reference - executed

    SELL-side -> client gains when executed > reference
              -> client_points = executed - reference

Where 'reference' is the requested Price from the Orders row, and the
base direction (buy/sell) is derived from the order subtype prefix.
Subtype (LIMIT / STOP / STOP_LIMIT) is for bucket labeling only — it
never enters the math.

Buckets (event_type = "PENDING_FILL"):
    BUY;LIMIT       BUY;STOP        BUY;STOP_LIMIT
    SELL;LIMIT      SELL;STOP       SELL;STOP_LIMIT
"""
from dataclasses import dataclass
from typing import Any, List, Optional, Union


# Recognized pending order subtypes (lowercase, as they appear in MT5 reports).
# Kept here as a local copy so this module is fully self-contained.
PENDING_ORDER_TYPES = {
    "buy limit",
    "sell limit",
    "buy stop",
    "sell stop",
    "buy stop limit",
    "sell stop limit",
}


@dataclass
class PendingSlippageResult:
    event_type: str                  # always "PENDING_FILL"
    bucket: str                      # "BUY;LIMIT", "SELL;STOP_LIMIT", etc.
    order_type: str                  # "buy" or "sell" (base direction)
    order_subtype: str               # full label e.g. "BUY_LIMIT", "SELL_STOP_LIMIT"
    reference_price: float           # requested price from Orders row
    executed_price: float            # actual fill price from Deals
    raw_diff_points: float           # executed - reference (sign tells market direction)
    client_points: float             # signed: positive = good for client
    impact: str                      # "POSITIVE", "NEGATIVE", "ZERO"
    volume: float
    client_usd: Optional[float] = None       # None if contract_size unavailable
    order_id: Any = None                     # the matched Order ID
    deal_id: Union[Any, List[Any]] = None    # single Deal ID, or list if aggregated
    was_aggregated: bool = False             # True iff this row came from a 1->N VWAP collapse


def compute_pending_slippage(
    order_subtype: str,
    requested_price: float,
    executed_price: float,
    volume: float,
    contract_size: Optional[float] = None,
    order_id: Any = None,
    deal_id: Union[Any, List[Any]] = None,
    was_aggregated: bool = False,
) -> PendingSlippageResult:
    """
    Apply the unified formula to a pending-order fill. Defensive on inputs.

    order_subtype: one of PENDING_ORDER_TYPES (e.g. "buy limit", "sell stop limit")
    requested_price: the Price from the Orders row (what the client asked for)
    executed_price: the Price from the matched in-deal (what they got)
    volume: the filled volume
    contract_size: units per 1 lot for the symbol; None -> client_usd is None

    Raises ValueError on inputs that the parser should already have filtered.
    """
    if order_subtype is None:
        raise ValueError("order_subtype is None")
    s = str(order_subtype).strip().lower()
    if s not in PENDING_ORDER_TYPES:
        raise ValueError(
            f"Unknown pending order subtype: {order_subtype!r}. "
            f"Expected one of: {sorted(PENDING_ORDER_TYPES)}"
        )

    # Derive base direction strictly by prefix.
    if s.startswith("buy"):
        base = "buy"
    elif s.startswith("sell"):
        base = "sell"
    else:
        raise ValueError(f"Cannot derive base direction from {order_subtype!r}")

    # Subtype label without the direction prefix.
    if s.startswith("buy "):
        kind = s[len("buy "):]
    elif s.startswith("sell "):
        kind = s[len("sell "):]
    else:
        kind = s
    kind_label = kind.upper().replace(" ", "_")  # "LIMIT", "STOP", "STOP_LIMIT"

    requested_price = float(requested_price)
    executed_price = float(executed_price)
    volume = float(volume)

    raw_diff = executed_price - requested_price

    if base == "buy":
        client_points = requested_price - executed_price
    else:
        client_points = executed_price - requested_price

    if client_points > 0:
        impact = "POSITIVE"
    elif client_points < 0:
        impact = "NEGATIVE"
    else:
        impact = "ZERO"

    client_usd = None
    if contract_size is not None and contract_size > 0:
        client_usd = client_points * volume * float(contract_size)

    return PendingSlippageResult(
        event_type="PENDING_FILL",
        bucket=f"{base.upper()};{kind_label}",
        order_type=base,
        order_subtype=f"{base.upper()}_{kind_label}",
        reference_price=requested_price,
        executed_price=executed_price,
        raw_diff_points=raw_diff,
        client_points=client_points,
        impact=impact,
        volume=volume,
        client_usd=client_usd,
        order_id=order_id,
        deal_id=deal_id,
        was_aggregated=was_aggregated,
    )
