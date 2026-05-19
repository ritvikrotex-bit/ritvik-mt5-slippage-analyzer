"""
CLI entry point for pending-order fill slippage analysis.

Usage:
    python -m pending_orders.run_pending_analysis path/to/ReportHistory-XXX.xlsx

Pipeline:
  1. Run the 8-case pending fixture. Abort on failure.
  2. Parse Orders section + Deals direction='in'.
  3. Match orders to deals by Order ID (matcher.match_orders_to_deals).
  4. Aggregate partial fills via VWAP (matcher.aggregate_partial_fills).
  5. Compute slippage with compute_pending_slippage.
  6. Print reconciliation, per-bucket totals, and one live example per bucket.

This module is intentionally isolated from the TP/SL engine. It does not
import from files/slippage.py, files/parser.py, files/comment_parser.py,
or files/test_slippage.py.
"""
import sys
from collections import defaultdict
from typing import List

from config import CONTRACT_SIZES, DEFAULT_CONTRACT_SIZE

from pending_orders.orders_parser import extract_orders, extract_in_deals
from pending_orders.matcher import match_orders_to_deals, aggregate_partial_fills
from pending_orders.pending_slippage import (
    PendingSlippageResult,
    compute_pending_slippage,
)
from pending_orders.test_pending import run_fixture


def _contract_size_for(symbol):
    if not symbol:
        return DEFAULT_CONTRACT_SIZE
    base = str(symbol).split(".")[0].split("#")[0].upper()
    return CONTRACT_SIZES.get(base, DEFAULT_CONTRACT_SIZE)


def _hr(c="="):
    print(c * 78)


def _arith(r: PendingSlippageResult) -> str:
    if r.order_type == "buy":
        return f"{r.reference_price} - {r.executed_price} = {r.client_points:+.4f}"
    return f"{r.executed_price} - {r.reference_price} = {r.client_points:+.4f}"


def analyze(filepath: str) -> None:
    _hr()
    print("STEP 0: PENDING FIXTURE (8 worked examples)")
    _hr()
    if not run_fixture():
        print("\nABORTING: pending fixture failed. The math is broken.")
        sys.exit(1)
    print()

    _hr()
    print(f"STEP 1: PARSE ORDERS + IN-DEALS  (file: {filepath})")
    _hr()

    orders = extract_orders(filepath)
    in_deals = extract_in_deals(filepath)

    print(f"ORDERS SECTION")
    print(f"  Sheet              : {orders['sheet_name']}")
    print(f"  Header at row      : {orders['header_row']}")
    print(f"  Total order rows   : {orders['total_rows']}")
    print(f"  Filled pendings    : {len(orders['filled_pendings'])}")
    print(f"  State counts       : {orders['state_counts']}")
    if orders["skipped"]:
        print(f"  Skipped reasons:")
        for reason, count in sorted(orders["skipped"].items(), key=lambda x: -x[1]):
            print(f"      {reason:<48s} {count:>4d}")

    print(f"\nDEALS SECTION (Direction='in')")
    print(f"  Header at row      : {in_deals['header_row']}")
    print(f"  In-deals total     : {len(in_deals['in_deals'])}")

    _hr()
    print("STEP 2: ORDER <-> DEAL MATCHING")
    _hr()
    match = match_orders_to_deals(orders["filled_pendings"], in_deals["in_deals"])
    rec = match["reconciliation"]
    print(f"  1-to-1 matches               : {rec['matched_1to1']}")
    print(f"  1-to-N matches (partial)     : {rec['matched_1toN']}")
    print(f"  Orders without deal          : {rec['orders_without_deal']}  "
          f"(suspicious if >0)")
    print(f"  In-deals without parent      : {rec['deals_without_pending_order']}  "
          f"(market opens — expected)")
    print(f"  Duplicate order IDs          : {rec['filled_pendings_duplicate']}")

    if rec["orders_without_deal"] > 0:
        print(f"\n  WARNING: orders with no matching in-deal:")
        for o in match["orders_without_deal"][:5]:
            print(f"      Order {o['order_id']} ({o['type']}) requested @ {o['requested_price']}")

    _hr()
    print("STEP 3: COMPUTE PENDING SLIPPAGE")
    _hr()
    results: List = []
    unknown_symbols = set()
    for order, deal in match["matched"]:
        cs = _contract_size_for(order["symbol"])
        if cs is None:
            unknown_symbols.add(order["symbol"])
        r = compute_pending_slippage(
            order_subtype=order["type"],
            requested_price=order["requested_price"],
            executed_price=deal["executed_price"],
            volume=deal["volume"],
            contract_size=cs,
            order_id=order["order_id"],
            deal_id=deal["deal_id"],
            was_aggregated=False,
        )
        results.append((order, deal, r))

    for order, deals in match["partial_or_multi"]:
        cs = _contract_size_for(order["symbol"])
        if cs is None:
            unknown_symbols.add(order["symbol"])
        agg = aggregate_partial_fills(order, deals)
        r = compute_pending_slippage(
            order_subtype=order["type"],
            requested_price=order["requested_price"],
            executed_price=agg["executed_price"],
            volume=agg["volume"],
            contract_size=cs,
            order_id=order["order_id"],
            deal_id=agg["deal_id"],
            was_aggregated=True,
        )
        results.append((order, agg, r))

    if unknown_symbols:
        print(f"  WARNING: contract size unknown for: {sorted(unknown_symbols)}")
        print(f"           USD slippage will not be computed for these.\n")

    _hr()
    print("STEP 4: BUCKET SUMMARY")
    _hr()
    buckets = defaultdict(lambda: {"total": 0, "POSITIVE": 0, "NEGATIVE": 0,
                                    "ZERO": 0, "points": 0.0, "usd": 0.0,
                                    "usd_known": True})
    for _, _, r in results:
        b = buckets[r.bucket]
        b["total"] += 1
        b[r.impact] += 1
        b["points"] += r.client_points
        if r.client_usd is None:
            b["usd_known"] = False
        else:
            b["usd"] += r.client_usd

    print(f"{'Bucket':<18} {'Total':>6} {'Pos':>5} {'Neg':>5} {'Zero':>5} "
          f"{'Points':>12} {'USD':>14}")
    print("-" * 78)
    grand = {"total": 0, "POSITIVE": 0, "NEGATIVE": 0, "ZERO": 0,
             "points": 0.0, "usd": 0.0}
    grand_usd_known = True
    for name in ("BUY;LIMIT", "BUY;STOP", "BUY;STOP_LIMIT",
                 "SELL;LIMIT", "SELL;STOP", "SELL;STOP_LIMIT"):
        v = buckets.get(name)
        if v is None or v["total"] == 0:
            continue
        usd_str = f"{v['usd']:>14,.2f}" if v["usd_known"] else f"{'unknown':>14}"
        print(f"{name:<18} {v['total']:>6} {v['POSITIVE']:>5} {v['NEGATIVE']:>5} "
              f"{v['ZERO']:>5} {v['points']:>+12.4f} {usd_str}")
        for k in grand:
            grand[k] += v[k]
        if not v["usd_known"]:
            grand_usd_known = False
    print("-" * 78)
    grand_usd_str = f"{grand['usd']:>14,.2f}" if grand_usd_known else f"{'unknown':>14}"
    print(f"{'TOTAL':<18} {grand['total']:>6} {grand['POSITIVE']:>5} "
          f"{grand['NEGATIVE']:>5} {grand['ZERO']:>5} "
          f"{grand['points']:>+12.4f} {grand_usd_str}")
    print()

    _hr()
    print("STEP 5: ONE LIVE EXAMPLE PER BUCKET")
    _hr()
    seen = set()
    for order, deal, r in results:
        if r.bucket in seen:
            continue
        seen.add(r.bucket)
        print(f"\n  {r.bucket}")
        print(f"    Order ID        : {r.order_id}")
        print(f"    Subtype         : {order['type']}")
        print(f"    Open time       : {order['open_time']}")
        print(f"    Fill time       : {order.get('fill_time', '—')}")
        print(f"    Symbol / Volume : {order['symbol']} / {r.volume}")
        print(f"    Requested @     : {r.reference_price}")
        print(f"    Executed @      : {r.executed_price}")
        print(f"    Deal ID         : {r.deal_id}")
        print(f"    Formula         : {_arith(r)}")
        print(f"    Impact          : {r.impact}")
        if r.client_usd is not None:
            print(f"    Client USD      : {r.client_usd:+,.2f}")
        if r.was_aggregated:
            print(f"    NOTE            : Aggregated from partial fills (VWAP)")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pending_orders.run_pending_analysis <path-to-broker-report.xlsx>")
        sys.exit(2)
    analyze(sys.argv[1])
