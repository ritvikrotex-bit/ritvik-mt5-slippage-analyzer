"""
Pending-order fill slippage analysis (Phase 2).

This package is intentionally isolated from the TP/SL engine:
  - It defines its own PendingSlippageResult dataclass.
  - It carries its own copy of the unified slippage formula.
  - It does NOT import from files/slippage.py, files/parser.py,
    files/comment_parser.py, or files/test_slippage.py.

The only allowed coupling is reading constants from config.py
(CONTRACT_SIZES, DEFAULT_CONTRACT_SIZE, and the Phase-2 additions).
See LOGIC_LOCK.md §10 for the full separation contract.
"""
