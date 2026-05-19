# LOGIC_LOCK — Slippage Math Specification

> This document is the **single source of truth** for slippage math in this
> project. Any code change that contradicts this document is a defect.
> The 16 fixture cases at the bottom are the empirical contract.

---

## 1. Scope

Two independent slippage event types are calculated in this project:

| Event type | Trigger source | Where it appears |
|---|---|---|
| **TP/SL close** | `[tp ...]` / `[sl ...]` in Deal comment | Deals section, Direction = "out" |
| **Pending fill** | Requested `Price` in Orders row | Orders section state="filled", matched to Deals.Direction="in" by Order ID |

**These two are computed and reported separately.** They share the same
mathematical formula but live in separate code paths.

---

## 2. The unified math (immutable)

One rule covers every case. Type alone determines the sign.

```
client_points = reference_price - executed_price       when type = BUY  (any subtype)
client_points = executed_price - reference_price       when type = SELL (any subtype)
```

Where:

- **type** is `"buy"` or `"sell"` (the base direction of the closing or filling order)
- **reference_price** is:
  - the TP or SL trigger price (for TP/SL closes)
  - the requested Price from the Orders row (for pending fills)
- **executed_price** is the actual fill price from the Deals section

**Subtype** (TP, SL, LIMIT, STOP, STOP_LIMIT) is for **bucket labeling
only**. It never enters the math.

### Sign interpretation

| client_points | impact |
|---|---|
| `> 0` | POSITIVE (good for client) |
| `< 0` | NEGATIVE (bad for client) |
| `= 0` | ZERO (no slippage) |

### USD impact

```
client_usd = client_points × volume × contract_size
```

`contract_size` is per-symbol (e.g. XAUUSD = 100 oz/lot). If unknown,
`client_usd` is reported as None / unavailable.

---

## 3. Buckets

| Event type | Buckets |
|---|---|
| TP_SL_CLOSE | BUY;SL, BUY;TP, SELL;SL, SELL;TP |
| PENDING_FILL | BUY;LIMIT, BUY;STOP, BUY;STOP_LIMIT, SELL;LIMIT, SELL;STOP, SELL;STOP_LIMIT |

Bucket strings are immutable identifiers used in storage, filters, and UI.

---

## 4. Data flow

### TP/SL close (existing — unchanged)

```
Deals row
    ├── Direction == "out"        (filter)
    ├── Comment matches [tp/sl]   (parse)
    └── Type (buy/sell), Price    (compute)
→ SlippageResult (event_type = TP_SL_CLOSE)
```

### Pending fill (new — separate path)

```
Orders row                          Deals row (in)
    ├── State == "filled"               ├── Direction == "in"
    ├── Type is pending (limit/        └── Order ID
    │   stop/stop limit)
    ├── Price (requested)
    └── Order ID
              │                                │
              └──────── JOIN by Order ID ──────┘
                            │
                            ▼
                  reference = Orders.Price
                  executed  = Deals.Price
                  type      = "buy" or "sell" (derived from Orders.Type)
                            │
                            ▼
               PendingSlippageResult (event_type = PENDING_FILL)
```

---

## 5. Filters (immutable)

### TP/SL close filters (Deals section)

| Field | Rule |
|---|---|
| Direction | must equal `"out"` |
| Comment | must match `\[\s*(tp\|sl)\s*([\d.,]+)\s*\]` (case-insensitive) |
| Type | must be `"buy"` or `"sell"` (lowercase, normalized) |
| Volume, Price | must be numeric and > 0 |

### Pending fill filters

**Orders section:**

| Field | Rule |
|---|---|
| State | must equal `"filled"` |
| Type | must be in `{buy limit, sell limit, buy stop, sell stop, buy stop limit, sell stop limit}` |
| Price (requested) | must be numeric and > 0 |
| filled_volume (from `requested/filled` pair) | must be > 0 |
| Order ID | must not be null |

**Deals section (for matching):**

| Field | Rule |
|---|---|
| Direction | must equal `"in"` |
| Type | must be `"buy"` or `"sell"` |
| Order ID | must not be null |

**Match rule:** `Orders.Order ID == Deals.Order ID` for `Direction = "in"`.

---

## 6. Edge cases (immutable handling)

| Case | Behavior |
|---|---|
| 1 order → 1 deal | Normal match. |
| 1 order → N deals (partial fill / multi-LP) | Aggregate via **volume-weighted average price** before slippage calculation. |
| 1 order → 0 deals (state=filled but no deal) | Surface as warning. Do NOT count toward slippage totals. |
| 1 deal → 0 orders (Direction=in but no parent pending) | Expected for market orders. Not an error. |
| Canceled / rejected / expired orders | Ignored entirely. Never appear in slippage results. |
| `out by` deals (hedged closes) | Ignored in TP/SL calculation (no trigger). |
| `client_points = 0` | Reported as ZERO impact (separate category, not folded into POSITIVE or NEGATIVE). |

---

## 7. Required fields in result records

Both `SlippageResult` (TP/SL) and `PendingSlippageResult` MUST contain:

- `event_type` — `"TP_SL_CLOSE"` or `"PENDING_FILL"`
- `bucket` — one of the 10 bucket strings above
- `order_type` — `"buy"` or `"sell"` (base direction)
- `reference_price` — TP/SL trigger or requested price
- `executed_price` — actual fill
- `volume`
- `client_points` (signed: positive = good for client)
- `raw_diff_points` — `executed_price - reference_price` (unsigned, for audit)
- `impact` — `"POSITIVE"`, `"NEGATIVE"`, or `"ZERO"`
- `client_usd` — points × volume × contract_size, or None

`PendingSlippageResult` additionally MUST contain:

- `order_id` — the Order ID used for matching
- `deal_id` — the Deal ID (or list of deal IDs if aggregated)
- `order_subtype` — full subtype e.g. `"BUY_STOP"`, `"SELL_STOP_LIMIT"`
- `was_aggregated` — boolean, true if this was a 1-to-N partial-fill match

---

## 8. Reconciliation requirement (immutable)

Both analyses MUST produce a reconciliation count where:

```
total_rows_in_section = rows_used + rows_skipped (sum across reasons)
```

If this does not balance, the analysis is invalid and must error visibly.

For pending fills, an additional reconciliation:

```
filled_pendings_total = matched_1to1 + matched_1toN + orders_without_deal
```

This must also balance.

---

## 9. The 16-case fixture (empirical contract)

These cases define the math. **All 16 must pass on every code change.**

### TP/SL CLOSE CASES (8)

| # | Bucket | type | ref | exec | points | impact |
|---|---|---|---|---|---|---|
| 1 | BUY;SL | buy | 100 | 101 | -1 | NEGATIVE |
| 2 | BUY;SL | buy | 100 | 99 | +1 | POSITIVE |
| 3 | BUY;TP | buy | 50 | 51 | -1 | NEGATIVE |
| 4 | BUY;TP | buy | 50 | 49 | +1 | POSITIVE |
| 5 | SELL;SL | sell | 70 | 71 | +1 | POSITIVE |
| 6 | SELL;SL | sell | 70 | 69 | -1 | NEGATIVE |
| 7 | SELL;TP | sell | 150 | 151 | +1 | POSITIVE |
| 8 | SELL;TP | sell | 150 | 149 | -1 | NEGATIVE |

### PENDING FILL CASES (8)

| # | Bucket | subtype | req | exec | points | impact |
|---|---|---|---|---|---|---|
| 9 | BUY;LIMIT | buy limit | 100 | 99 | +1 | POSITIVE |
| 10 | BUY;LIMIT | buy limit | 100 | 101 | -1 | NEGATIVE |
| 11 | SELL;LIMIT | sell limit | 100 | 101 | +1 | POSITIVE |
| 12 | SELL;LIMIT | sell limit | 100 | 99 | -1 | NEGATIVE |
| 13 | BUY;STOP | buy stop | 100 | 99 | +1 | POSITIVE |
| 14 | BUY;STOP | buy stop | 100 | 101 | -1 | NEGATIVE |
| 15 | SELL;STOP | sell stop | 100 | 101 | +1 | POSITIVE |
| 16 | SELL;STOP | sell stop | 100 | 99 | -1 | NEGATIVE |

---

## 10. Separation principle (immutable)

The pending-fill code must **never**:

- Modify any function in the existing TP/SL path
- Alter the existing `SlippageResult` dataclass
- Merge pending results into the TP/SL results list
- Share mutable state with the TP/SL analysis
- Be reachable from any TP/SL UI tab or report

The two analyses can share **read-only inputs**:

- `CONTRACT_SIZES` constant from config
- The Excel file path (each parser opens its own workbook)

That is the only permitted coupling.

---

## 11. Expected output on the reference Excel file

`ReportHistory-1316script.xlsx` is the canonical test file. A correct
implementation produces:

**TP/SL close analysis:**

| Bucket | Total | USD |
|---|---|---|
| BUY;SL | 21 | -585.80 |
| BUY;TP | 11 | +1,378.75 |
| SELL;SL | 21 | -1,114.35 |
| SELL;TP | 11 | +119.70 |
| **Total** | **64** | **-201.70** |

**Pending fill analysis:**

| Bucket | Total | USD |
|---|---|---|
| BUY;LIMIT | 21 | +23.28 |
| BUY;STOP | 38 | -1,768.45 |
| SELL;LIMIT | 20 | +23.52 |
| SELL;STOP | 37 | -1,924.85 |
| **Total** | **116** | **-3,646.50** |

Reconciliation: 116 filled pendings matched to 116 in-deals, 0 orphans,
0 partials, 0 duplicates. 20 in-deals have no parent pending (market
orders, expected).

If your implementation differs from any number above, the math is wrong.
