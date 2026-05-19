"""
Order <-> Deal matching for pending-fill slippage.

Joins filled pending Orders with their opening Deals (Direction = "in")
by Order ID. Surfaces full reconciliation:

  - 1-to-1 matches
  - 1-to-N matches (partial fills / multi-LP routing) — collapsed via VWAP
  - filled orders with NO matching in-deal (suspicious for state=filled)
  - in-deals with NO matching pending order (market opens — expected)
  - duplicate Order IDs in the filled-pending set (should not happen)
"""
from collections import defaultdict
from typing import Any, Dict, List


def match_orders_to_deals(
    filled_pendings: List[Dict[str, Any]],
    in_deals: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Args:
        filled_pendings: list from extract_orders()['filled_pendings']
        in_deals:        list from extract_in_deals()['in_deals']

    Returns dict with:
        matched               : list of (order_dict, deal_dict) pairs (1:1)
        partial_or_multi      : list of (order_dict, [deal_dict, ...]) for 1:N
        orders_without_deal   : list of order_dicts that had no matching deal
        deals_without_order   : list of deal_dicts whose order_id had no order
        duplicate_orders      : list of order_dicts whose order_id was duplicated
        reconciliation        : dict of counts for audit
    """
    # Index in-deals by order_id (may have multiples for partial fills).
    deals_by_order: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for d in in_deals:
        deals_by_order[d["order_id"]].append(d)

    # Index pending orders by order_id (should be unique).
    orders_by_id: Dict[Any, Dict[str, Any]] = {}
    duplicate_orders: List[Dict[str, Any]] = []
    for o in filled_pendings:
        oid = o["order_id"]
        if oid in orders_by_id:
            duplicate_orders.append(o)
        else:
            orders_by_id[oid] = o

    matched: List = []
    partial_or_multi: List = []
    orders_without_deal: List = []

    for oid, order in orders_by_id.items():
        deals = deals_by_order.get(oid, [])
        if len(deals) == 0:
            orders_without_deal.append(order)
        elif len(deals) == 1:
            matched.append((order, deals[0]))
        else:
            partial_or_multi.append((order, deals))

    pending_order_ids = set(orders_by_id.keys())
    deals_without_order = [d for d in in_deals if d["order_id"] not in pending_order_ids]

    reconciliation = {
        "filled_pendings_total":       len(filled_pendings),
        "filled_pendings_unique_ids":  len(orders_by_id),
        "filled_pendings_duplicate":   len(duplicate_orders),
        "in_deals_total":              len(in_deals),
        "matched_1to1":                len(matched),
        "matched_1toN":                len(partial_or_multi),
        "orders_without_deal":         len(orders_without_deal),
        "deals_without_pending_order": len(deals_without_order),
    }

    return {
        "matched":              matched,
        "partial_or_multi":     partial_or_multi,
        "orders_without_deal":  orders_without_deal,
        "deals_without_order":  deals_without_order,
        "duplicate_orders":     duplicate_orders,
        "reconciliation":       reconciliation,
    }


def aggregate_partial_fills(
    order: Dict[str, Any],
    deals: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Collapse multiple opening deals for one order into a single
    volume-weighted execution record. Used when a single pending order
    produces several fills (partial liquidity, multi-LP routing).

    Returns a synthetic deal dict with:
        executed_price : VWAP across the fills
        volume         : sum of fill volumes
        deal_id        : list of all underlying deal IDs (for audit)
        time           : earliest fill time
    """
    if not deals:
        raise ValueError("aggregate_partial_fills called with empty deals list")
    total_vol = sum(d["volume"] for d in deals)
    if total_vol <= 0:
        raise ValueError("Total volume across deals is non-positive")
    vwap = sum(d["executed_price"] * d["volume"] for d in deals) / total_vol
    return {
        "time":           min(d["time"] for d in deals),
        "deal_id":        [d["deal_id"] for d in deals],
        "order_id":       order["order_id"],
        "symbol":         deals[0]["symbol"],
        "type":           deals[0]["type"],
        "volume":         total_vol,
        "executed_price": vwap,
        "comment":        f"AGGREGATED {len(deals)} fills",
    }
