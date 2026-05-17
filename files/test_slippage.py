"""
Self-test fixture: the 8 worked examples from the spec.

These MUST all pass before the app processes any user data. If even one
fails, the analyzer is not safe to use — the math is broken somewhere.

Each case maps exactly to the user's original specification:

  1. BUY;SL  (closing a short, hit SL)
       SL=100, executed=101 -> NEGATIVE (-1)
       SL=100, executed= 99 -> POSITIVE (+1)
  2. BUY;TP  (closing a short, hit TP)
       TP= 50, executed= 51 -> NEGATIVE (-1)
       TP= 50, executed= 49 -> POSITIVE (+1)
  3. SELL;SL (closing a long, hit SL)
       SL= 70, executed= 71 -> POSITIVE (+1)
       SL= 70, executed= 69 -> NEGATIVE (-1)
  4. SELL;TP (closing a long, hit TP)
       TP=150, executed=151 -> POSITIVE (+1)
       TP=150, executed=149 -> NEGATIVE (-1)
"""
from slippage import compute_slippage


CASES = [
    # (description,           type,    trig, trig_price, executed, expected_impact, expected_points)
    ("BUY;SL  exec>trig",     "buy",  "SL", 100.0, 101.0, "NEGATIVE", -1.0),
    ("BUY;SL  exec<trig",     "buy",  "SL", 100.0,  99.0, "POSITIVE",  1.0),
    ("BUY;TP  exec>trig",     "buy",  "TP",  50.0,  51.0, "NEGATIVE", -1.0),
    ("BUY;TP  exec<trig",     "buy",  "TP",  50.0,  49.0, "POSITIVE",  1.0),
    ("SELL;SL exec>trig",     "sell", "SL",  70.0,  71.0, "POSITIVE",  1.0),
    ("SELL;SL exec<trig",     "sell", "SL",  70.0,  69.0, "NEGATIVE", -1.0),
    ("SELL;TP exec>trig",     "sell", "TP", 150.0, 151.0, "POSITIVE",  1.0),
    ("SELL;TP exec<trig",     "sell", "TP", 150.0, 149.0, "NEGATIVE", -1.0),
]


def run_fixture() -> bool:
    """Run all 8 cases. Print a table. Return True iff every case passed."""
    all_passed = True
    print(f"{'#':<2} {'Case':<22} {'Bucket':<10} {'Expect':<9} {'Got':<9} {'Pts':>6}  Result")
    print("-" * 72)
    for i, (desc, t, tt, tp, ep, want_imp, want_pts) in enumerate(CASES, 1):
        r = compute_slippage(t, tt, tp, ep, volume=1.0)
        ok = (r.impact == want_imp) and (abs(r.client_points - want_pts) < 1e-9)
        all_passed = all_passed and ok
        mark = "PASS" if ok else "FAIL"
        print(f"{i:<2} {desc:<22} {r.bucket:<10} {want_imp:<9} {r.impact:<9} "
              f"{r.client_points:>+6.2f}  {mark}")
    print("-" * 72)
    if all_passed:
        print("ALL 8 CASES PASSED. The formula is wired correctly.")
    else:
        print("ONE OR MORE CASES FAILED. Do NOT use this build on real data.")
    return all_passed


if __name__ == "__main__":
    import sys
    sys.exit(0 if run_fixture() else 1)
