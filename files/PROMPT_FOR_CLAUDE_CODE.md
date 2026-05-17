# Claude Code Prompt — Broker Report Slippage Analyzer

> Paste this entire file into Claude Code (Opus 4.7) in VSCode as the
> opening prompt. Have the example file `ReportHistory-1316script.xlsx`
> in the same folder so Claude Code can read it directly.

---

## Role

You are building a **production-grade slippage analyzer** for MT5 broker
history reports. The output will be used in compliance reporting, so the
math must be exact and every dropped row must be auditable.

I have already designed the logic and the test fixture passes 8/8 on the
unified formula. **Your job is to take the working engine files I provide
and add a Streamlit UI around them — without changing the math.**

---

## What already exists (do not modify the math)

The repo contains these files. All five are tested and working — they
produce `−$201.70` net client slippage on the example file:

```
slippage_tool/
├── config.py            # Regex patterns, header tokens, contract sizes
├── comment_parser.py    # parse_trigger(comment) -> ("TP"|"SL", price) or None
├── slippage.py          # compute_slippage(...) -> SlippageResult
├── parser.py            # extract_deals(filepath) -> {valid_deals, skipped, ...}
├── test_slippage.py     # 8 fixture cases — MUST pass before any user data
├── run_analysis.py      # CLI entry point, useful as a reference for the UI
└── requirements.txt
```

**Phase 1 (you are here):** verify the engine on the example file, then
build the Streamlit UI on top. Do not touch `slippage.py` or
`comment_parser.py`. If you find a math bug, stop and tell me — do not
silently "fix" it.

---

## Domain context

### The 4 slippage scenarios (the entire problem)

A trade has an **original position** (long or short), a **trigger price**
(TP or SL set when the position was opened), and an **executed price**
(the actual fill when the trigger hit). Slippage is the difference, and
its **sign relative to the client** depends on which way the trade was.

| # | Closing Type | Trigger | Example | Client impact |
|---|---|---|---|---|
| 1 | BUY (closes short) | SL | SL=100, exec=101 | **NEGATIVE** (paid more) |
| 1 | BUY (closes short) | SL | SL=100, exec= 99 | **POSITIVE** (paid less) |
| 2 | BUY (closes short) | TP | TP= 50, exec= 51 | **NEGATIVE** |
| 2 | BUY (closes short) | TP | TP= 50, exec= 49 | **POSITIVE** |
| 3 | SELL (closes long) | SL | SL= 70, exec= 71 | **POSITIVE** (sold higher) |
| 3 | SELL (closes long) | SL | SL= 70, exec= 69 | **NEGATIVE** (sold lower) |
| 4 | SELL (closes long) | TP | TP=150, exec=151 | **POSITIVE** |
| 4 | SELL (closes long) | TP | TP=150, exec=149 | **NEGATIVE** |

### The unified formula (already implemented)

```
if order_type == "buy":   client_points = trigger - executed
if order_type == "sell":  client_points = executed - trigger
```

Type alone determines sign. TP vs SL is categorization only.

### Excel file structure (already implemented)

The file is an MT5 history export with three sections:
`Positions`, `Orders`, and `Deals`. **Only the Deals section is used.**
The Deals header looks like:

```
Time | Deal | Symbol | Type | Direction | Volume | Price | Order |
Commission | Fee | Swap | Profit | Balance | Comment
```

Filtering rules (already implemented in `parser.py`):
- Keep rows where `Direction == "out"` (closing trades)
- Keep rows where `Comment` matches `[tp PRICE]` or `[sl PRICE]`
- Drop everything else with an audit-trail entry

On the example file:
- 277 total rows below the header
- 64 valid TP/SL deals
- 213 skipped (136 `direction=in`, 52 `no_tp_sl_comment`, 20 `direction=out by`, 5 `direction_empty`)
- All 4 buckets populated: BUY;SL=21, BUY;TP=11, SELL;SL=21, SELL;TP=11

---

## Phase 1 acceptance criteria (do these in order)

### A. Verify the engine

1. Run `python test_slippage.py` — must show 8/8 PASS.
2. Run `python run_analysis.py ReportHistory-1316script.xlsx` — must show:
   - Reconciliation OK (64 + 213 = 277)
   - Bucket totals: BUY;SL=21, BUY;TP=11, SELL;SL=21, SELL;TP=11
   - Total client USD = `-201.70`

If anything differs from the above, STOP and report the discrepancy. Do
not proceed to UI work until the engine numbers match.

### B. Build `app.py` (Streamlit UI)

Single file, imports from the existing modules unchanged. Page layout:

1. **Title** — "Slippage Analyzer"

2. **Self-test panel (top, always visible)**
   - On every page load, run `test_slippage.run_fixture()`.
   - If 8/8 pass: green badge "Self-test 8/8 ✓".
   - If anything fails: red banner across full width — "MATH BROKEN, app
     disabled". Disable file upload until this clears.

3. **File uploader** — `st.file_uploader(type=["xlsx", "xlsm"])`

4. **Detection audit panel** (expander, default-expanded)
   Show, in this order:
   - Sheet name, header row index
   - Reconciliation: `total = valid + skipped` with PASS/FAIL
   - Skipped reasons as a small table sorted descending by count
   - List of unmatched suspicious comments (if any)

5. **Bucket summary** — 4 metric cards in a row, then a table:

   Card 1: BUY;SL — total / positive / negative
   Card 2: BUY;TP — total / positive / negative
   Card 3: SELL;SL — total / positive / negative
   Card 4: SELL;TP — total / positive / negative

   Below cards: the same data as a styled table with totals row.

6. **One live example per bucket** (expander, default-collapsed)
   Pull one row from each populated bucket. For each, display:
   - Time, Deal, Order, Symbol, Volume
   - `Trigger {TP/SL} @ {price}` and `Executed @ {price}`
   - The exact arithmetic: `"4779.90 - 4774.72 = +5.18 points"`
   - Impact label
   - Client USD

7. **Per-trade results table**
   Columns: Time, Deal, Symbol, Type, Volume, Trigger Type, Trigger Price,
   Executed Price, Client Points, Client USD, Impact, Comment.
   Row colors: light green for POSITIVE, light red for NEGATIVE, white for ZERO.
   Filters above the table: Symbol (multiselect), Type, Trigger Type,
   Impact, date range.

8. **Aggregate metrics** (after filters)
   - Total client slippage (points and USD)
   - Average per trade
   - Worst single trade (USD)
   - Best single trade (USD)

9. **Download buttons**
   - CSV of the filtered per-trade table
   - XLSX with three sheets: `Trades`, `BucketSummary`, `Audit`

### C. Edge cases the UI must handle gracefully

- Empty upload — show instructions, no error.
- File with no Deals section — show the parser's error message clearly,
  do not crash.
- File with deals but zero valid TP/SL rows — show audit panel with the
  skip reasons, blank result table, suppress the metrics with "No valid
  TP/SL deals found".
- Unknown symbol (no contract size) — show USD column as `—` for those
  rows, banner at top: "Contract size unknown for: XYZ. Add to config.py
  to enable USD calculation."
- Multiple sheets — parser already handles this; surface which sheet
  was used in the audit panel.

### D. What NOT to do

- Do NOT recompute slippage inside `app.py`. Always go through
  `slippage.compute_slippage()`.
- Do NOT add new fields to `SlippageResult` — extend in a wrapper if needed.
- Do NOT silently swallow parser errors. Use `st.error()` with the full
  exception message.
- Do NOT hardcode any row indices, column letters, or sheet names.
- Do NOT use `eval()`, `exec()`, or shell-out to system commands.

---

## How to start

1. Open this folder in VSCode.
2. Confirm the example file `ReportHistory-1316script.xlsx` is present.
3. Create a virtualenv and `pip install -r requirements.txt`.
4. Run `python test_slippage.py` — confirm 8/8.
5. Run `python run_analysis.py ReportHistory-1316script.xlsx` — confirm
   the bucket numbers match section "Phase 1 acceptance criteria, A".
6. Only after both pass, create `app.py` and run with
   `streamlit run app.py`.
7. Upload the example file in the browser. The bucket numbers shown in
   the UI must exactly match step 5.

---

## After Phase 1

Phase 2 (not now) will add:
- Multi-file comparison
- Symbol-level breakdowns and time-of-day heatmaps
- Configurable thresholds for "material slippage" alerts
- Export of a compliance-ready PDF report

Wait for Phase 1 to be reviewed and signed off before starting Phase 2.

---

## Expected first response from you

After reading this prompt, before writing any code, respond with:
1. Confirmation that you see all 5 engine files and the example .xlsx
2. The output of running `python test_slippage.py`
3. The bucket numbers from `python run_analysis.py ReportHistory-1316script.xlsx`
4. Then proceed to build `app.py`.
