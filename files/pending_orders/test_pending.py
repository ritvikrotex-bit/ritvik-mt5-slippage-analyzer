"""
Pending-order fixture: the 8 worked examples (cases 9..16) from
LOGIC_LOCK.md §9. These MUST all pass before any user data is processed.

Cases:
  BUY LIMIT  (requested=100)  executed=99  -> POSITIVE (+1)
  BUY LIMIT  (requested=100)  executed=101 -> NEGATIVE (-1)
  SELL LIMIT (requested=100)  executed=101 -> POSITIVE (+1)
  SELL LIMIT (requested=100)  executed=99  -> NEGATIVE (-1)
  BUY STOP   (requested=100)  executed=99  -> POSITIVE (+1)
  BUY STOP   (requested=100)  executed=101 -> NEGATIVE (-1)
  SELL STOP  (requested=100)  executed=101 -> POSITIVE (+1)
  SELL STOP  (requested=100)  executed=99  -> NEGATIVE (-1)
"""
from pending_orders.pending_slippage import compute_pending_slippage


# (description, subtype, requested, executed, expected_impact, expected_points)
PENDING_CASES = [
    ("BUY LIMIT  exec<req",   "buy limit",   100.0,  99.0, "POSITIVE",  1.0),
    ("BUY LIMIT  exec>req",   "buy limit",   100.0, 101.0, "NEGATIVE", -1.0),
    ("SELL LIMIT exec>req",   "sell limit",  100.0, 101.0, "POSITIVE",  1.0),
    ("SELL LIMIT exec<req",   "sell limit",  100.0,  99.0, "NEGATIVE", -1.0),
    ("BUY STOP   exec<req",   "buy stop",    100.0,  99.0, "POSITIVE",  1.0),
    ("BUY STOP   exec>req",   "buy stop",    100.0, 101.0, "NEGATIVE", -1.0),
    ("SELL STOP  exec>req",   "sell stop",   100.0, 101.0, "POSITIVE",  1.0),
    ("SELL STOP  exec<req",   "sell stop",   100.0,  99.0, "NEGATIVE", -1.0),
]


def run_fixture() -> bool:
    """Run all 8 pending cases. Print a table. Return True iff every case passed."""
    all_passed = True
    print(f"{'#':<2} {'Case':<22} {'Bucket':<14} {'Expect':<9} {'Got':<9} {'Pts':>6}  Result")
    print("-" * 76)
    for i, (desc, sub, rp, ep, want_imp, want_pts) in enumerate(PENDING_CASES, 1):
        r = compute_pending_slippage(sub, rp, ep, volume=1.0)
        ok = (r.impact == want_imp) and (abs(r.client_points - want_pts) < 1e-9)
        all_passed = all_passed and ok
        mark = "PASS" if ok else "FAIL"
        print(f"{i:<2} {desc:<22} {r.bucket:<14} {want_imp:<9} {r.impact:<9} "
              f"{r.client_points:>+6.2f}  {mark}")
    print("-" * 76)
    if all_passed:
        print("ALL 8 PENDING CASES PASSED. The formula is wired correctly.")
    else:
        print("ONE OR MORE PENDING CASES FAILED. Do NOT use this build on real data.")
    return all_passed


if __name__ == "__main__":
    import sys
    sys.exit(0 if run_fixture() else 1)
