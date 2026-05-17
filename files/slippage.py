"""
Core slippage math.

THE SINGLE RULE that handles all 4 scenarios:

    BUY closes a SHORT  -> client gains when executed < trigger
                        -> client_points = trigger - executed

    SELL closes a LONG  -> client gains when executed > trigger
                        -> client_points = executed - trigger

Type alone determines the sign. TP vs SL is categorization, not math.

This reduces the 4 user-facing scenarios to one branch, which is what
makes the implementation bulletproof — there is no fifth case the code
can forget about.

The 4 buckets for reporting:
    BUY;SL  - closing a short, hit stop loss
    BUY;TP  - closing a short, hit take profit
    SELL;SL - closing a long, hit stop loss
    SELL;TP - closing a long, hit take profit
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class SlippageResult:
    bucket: str                  # "BUY;SL", "BUY;TP", "SELL;SL", "SELL;TP"
    order_type: str              # "buy" or "sell" (lowercase, normalized)
    trigger_type: str            # "TP" or "SL" (uppercase, normalized)
    trigger_price: float
    executed_price: float
    raw_diff_points: float       # executed - trigger (sign tells direction of market move)
    client_points: float         # signed: positive = good for client
    impact: str                  # "POSITIVE", "NEGATIVE", "ZERO"
    volume: float
    client_usd: Optional[float] = None  # None if contract_size unavailable


def compute_slippage(
    order_type: str,
    trigger_type: str,
    trigger_price: float,
    executed_price: float,
    volume: float,
    contract_size: Optional[float] = None,
) -> SlippageResult:
    """
    Apply the unified formula. Defensive on inputs.

    Raises ValueError on inputs that cannot be classified — callers should
    have filtered these out at the parser stage, but we double-check here.
    """
    if order_type is None:
        raise ValueError("order_type is None")
    t = str(order_type).strip().lower()
    if t not in ("buy", "sell"):
        raise ValueError(f"Invalid order_type: {order_type!r}, expected 'buy' or 'sell'")

    if trigger_type is None:
        raise ValueError("trigger_type is None")
    tt = str(trigger_type).strip().upper()
    if tt not in ("TP", "SL"):
        raise ValueError(f"Invalid trigger_type: {trigger_type!r}, expected 'TP' or 'SL'")

    trigger_price = float(trigger_price)
    executed_price = float(executed_price)
    volume = float(volume)

    raw_diff = executed_price - trigger_price

    if t == "buy":
        client_points = trigger_price - executed_price
    else:  # sell
        client_points = executed_price - trigger_price

    if client_points > 0:
        impact = "POSITIVE"
    elif client_points < 0:
        impact = "NEGATIVE"
    else:
        impact = "ZERO"

    client_usd = None
    if contract_size is not None and contract_size > 0:
        client_usd = client_points * volume * float(contract_size)

    return SlippageResult(
        bucket=f"{t.upper()};{tt}",
        order_type=t,
        trigger_type=tt,
        trigger_price=trigger_price,
        executed_price=executed_price,
        raw_diff_points=raw_diff,
        client_points=client_points,
        impact=impact,
        volume=volume,
        client_usd=client_usd,
    )
