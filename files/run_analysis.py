"""
CLI entry point: process a broker report end-to-end.

Usage:
    python run_analysis.py path/to/ReportHistory-XXX.xlsx

What it does:
    1. Runs the 8-case fixture test (compute_slippage on known inputs).
       If any fail, aborts before touching user data.
    2. Loads the Excel file, locates the Deals section.
    3. Extracts every row, filters to valid TP/SL closing deals.
    4. Runs the unified formula on each.
    5. Prints:
         - Reconciliation count (total / valid / skipped — must add up)
         - Per-bucket counts and USD totals
         - One worked example per bucket
         - Any unmatched-but-suspicious comments

This script intentionally has NO Streamlit / no UI. It is the engine.
The Streamlit UI will import these modules later, unchanged.
"""
import sys
from collections import defaultdict
from typing import List, Tuple

from parser import extract_deals
from slippage import compute_slippage, SlippageResult
from config import CONTRACT_SIZES, DEFAULT_CONTRACT_SIZE
from test_slippage import run_fixture


def _contract_size_for(symbol):
    """Strip suffix and look up. Returns None if unknown."""
    if not symbol:
        return DEFAULT_CONTRACT_SIZE
    base = str(symbol).split(".")[0].split("#")[0].upper()
    return CONTRACT_SIZES.get(base, DEFAULT_CONTRACT_SIZE)


def analyze(filepath: str) -> None:
    print("=" * 78)
    print("STEP 1: SELF-TEST (8 worked examples from spec)")
    print("=" * 78)
    if not run_fixture():
        print("\nABORTING: self-test failed. The math is broken.")
        sys.exit(1)
    print()

    print("=" * 78)
    print(f"STEP 2: PARSE EXCEL — {filepath}")
    print("=" * 78)
    data = extract_deals(filepath)
    print(f"Sheet                 : {data['sheet_name']}")
    print(f"Deals header at row   : {data['header_row']}")
    print(f"Total deal rows below : {data['total_rows']}")
    print(f"Valid TP/SL deals     : {len(data['valid_deals'])}")
    print(f"Skipped (with reasons):")
    for reason, count in sorted(data['skipped'].items(), key=lambda x: -x[1]):
        print(f"    {reason:<40s} {count:>4d}")
    reconciled = len(data['valid_deals']) + sum(data['skipped'].values())
    print(f"Reconciliation check  : {len(data['valid_deals'])} valid + "
          f"{sum(data['skipped'].values())} skipped = {reconciled} "
          f"(total processed: {data['total_rows']})  "
          f"{'OK' if reconciled == data['total_rows'] else 'MISMATCH'}")
    if data['unmatched_comments']:
        print(f"\nUnmatched suspicious comments ({len(data['unmatched_comments'])}):")
        for c in data['unmatched_comments'][:10]:
            print(f"    {c!r}")
    print()

    print("=" * 78)
    print("STEP 3: COMPUTE SLIPPAGE")
    print("=" * 78)
    results: List[Tuple[dict, SlippageResult]] = []
    unknown_symbols = set()
    for d in data['valid_deals']:
        cs = _contract_size_for(d['symbol'])
        if cs is None:
            unknown_symbols.add(d['symbol'])
        r = compute_slippage(
            order_type=d['type'],
            trigger_type=d['trigger_type'],
            trigger_price=d['trigger_price'],
            executed_price=d['executed_price'],
            volume=d['volume'],
            contract_size=cs,
        )
        results.append((d, r))

    if unknown_symbols:
        print(f"WARNING: contract size unknown for symbols: {sorted(unknown_symbols)}")
        print("         USD slippage will not be computed for these.\n")

    print("=" * 78)
    print("STEP 4: BUCKET SUMMARY")
    print("=" * 78)
    buckets = defaultdict(lambda: {"total": 0, "POSITIVE": 0, "NEGATIVE": 0, "ZERO": 0,
                                    "points": 0.0, "usd": 0.0, "usd_known": True})
    for _, r in results:
        b = buckets[r.bucket]
        b["total"] += 1
        b[r.impact] += 1
        b["points"] += r.client_points
        if r.client_usd is None:
            b["usd_known"] = False
        else:
            b["usd"] += r.client_usd

    print(f"{'Bucket':<10} {'Total':>6} {'Pos':>5} {'Neg':>5} {'Zero':>5} "
          f"{'Points':>12} {'USD':>14}")
    print("-" * 78)
    grand = {"total": 0, "POSITIVE": 0, "NEGATIVE": 0, "ZERO": 0, "points": 0.0, "usd": 0.0}
    for b in ("BUY;SL", "BUY;TP", "SELL;SL", "SELL;TP"):
        v = buckets.get(b, {"total": 0, "POSITIVE": 0, "NEGATIVE": 0, "ZERO": 0,
                            "points": 0.0, "usd": 0.0, "usd_known": True})
        usd_str = f"{v['usd']:>14,.2f}" if v['usd_known'] else f"{'unknown':>14}"
        print(f"{b:<10} {v['total']:>6} {v['POSITIVE']:>5} {v['NEGATIVE']:>5} "
              f"{v['ZERO']:>5} {v['points']:>+12.2f} {usd_str}")
        for k in grand:
            grand[k] += v[k]
    print("-" * 78)
    print(f"{'TOTAL':<10} {grand['total']:>6} {grand['POSITIVE']:>5} "
          f"{grand['NEGATIVE']:>5} {grand['ZERO']:>5} "
          f"{grand['points']:>+12.2f} {grand['usd']:>14,.2f}")
    print()

    print("=" * 78)
    print("STEP 5: ONE LIVE EXAMPLE PER BUCKET (for manual verification)")
    print("=" * 78)
    seen = set()
    for d, r in results:
        if r.bucket in seen:
            continue
        seen.add(r.bucket)
        arith = (f"{r.trigger_price} - {r.executed_price}" if r.order_type == "buy"
                 else f"{r.executed_price} - {r.trigger_price}")
        print(f"\n  {r.bucket}")
        print(f"    Time          : {d['time']}")
        print(f"    Deal / Order  : {d['deal']} / {d['order']}")
        print(f"    Symbol / Vol  : {d['symbol']} / {d['volume']}")
        print(f"    Trigger       : {r.trigger_type} @ {r.trigger_price}")
        print(f"    Executed at   : {r.executed_price}")
        print(f"    Formula       : {arith} = {r.client_points:+.4f} points")
        print(f"    Impact        : {r.impact}")
        if r.client_usd is not None:
            print(f"    Client USD    : {r.client_usd:+,.2f}")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_analysis.py <path-to-broker-report.xlsx>")
        sys.exit(2)
    analyze(sys.argv[1])
