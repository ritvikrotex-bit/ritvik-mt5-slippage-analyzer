# Slippage Analyzer — Engine

Pure Python engine for analyzing client slippage in MT5 broker reports.
The math is verified end-to-end on the example file; UI comes next.

## What's here

| File | Purpose |
|------|---------|
| `config.py` | Regex patterns, header tokens, contract sizes per symbol |
| `comment_parser.py` | `parse_trigger("[tp 4779.90]")` → `("TP", 4779.90)` |
| `slippage.py` | The unified formula — `compute_slippage(...)` |
| `parser.py` | Reads Excel, finds Deals section, filters valid rows |
| `test_slippage.py` | 8 worked examples from the spec — must pass |
| `run_analysis.py` | CLI: end-to-end pipeline + audit print |
| `PROMPT_FOR_CLAUDE_CODE.md` | Paste this into Claude Code to build the UI |
| `requirements.txt` | Dependencies |

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the 8-case self-test
python test_slippage.py

# Expected: 8/8 PASS

# 3. Run the full pipeline on the example file
python run_analysis.py ReportHistory-1316script.xlsx

# Expected output includes:
#   Valid TP/SL deals     : 64
#   Reconciliation check  : 64 valid + 213 skipped = 277  OK
#   BUY;SL=21  BUY;TP=11  SELL;SL=21  SELL;TP=11
#   TOTAL client USD     : -201.70
```

## The single rule (memorize this)

```
client_points = trigger - executed    when type = BUY    (closes short)
client_points = executed - trigger    when type = SELL   (closes long)
```

Type alone determines the sign. TP vs SL is for categorization only.

## Next step

Open `PROMPT_FOR_CLAUDE_CODE.md` and paste the contents into Claude Code
(Opus 4.7) in VSCode with this folder open. Claude Code will read the
engine files, verify the numbers, then build `app.py` (Streamlit UI).
