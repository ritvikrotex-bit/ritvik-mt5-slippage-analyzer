"""
Streamlit UI for the MT5 broker slippage analyzer.

This file contains NO slippage math. All numerical computation goes
through compute_slippage() in slippage.py. If you find yourself
recomputing trigger - executed anywhere here, stop — that means the
engine contract is broken.
"""
import contextlib
import io
import tempfile
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from config import CONTRACT_SIZES, DEFAULT_CONTRACT_SIZE
from parser import extract_deals
from slippage import SlippageResult, compute_slippage
from test_slippage import run_fixture


st.set_page_config(page_title="Slippage Analyzer", layout="wide")


# ---------------------------------------------------------------------------
# Self-test panel
# ---------------------------------------------------------------------------
@st.cache_data
def _cached_self_test() -> Tuple[bool, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = run_fixture()
    return ok, buf.getvalue()


def _contract_size_for(symbol) -> Optional[float]:
    """Look up the built-in default contract size for a symbol (None if unknown)."""
    if not symbol:
        return DEFAULT_CONTRACT_SIZE
    base = str(symbol).split(".")[0].split("#")[0].upper()
    return CONTRACT_SIZES.get(base, DEFAULT_CONTRACT_SIZE)


st.title("Slippage Analyzer")

engine_ok, fixture_log = _cached_self_test()
if engine_ok:
    st.success("Self-test 8/8 ✓")
else:
    st.error("MATH BROKEN, app disabled — fixture failed. Do not trust any results.")
    with st.expander("Fixture output", expanded=True):
        st.code(fixture_log)


# ---------------------------------------------------------------------------
# File uploader
# ---------------------------------------------------------------------------
uploaded = st.file_uploader(
    "Upload MT5 history report",
    type=["xlsx", "xlsm"],
    disabled=not engine_ok,
)

if uploaded is None:
    st.info("Drop an MT5 history XLSX above to begin.")
    st.stop()


with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
    tmp.write(uploaded.getbuffer())
    tmp_path = tmp.name


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------
try:
    data = extract_deals(tmp_path)
except Exception as e:
    st.error(f"Parser failed: {type(e).__name__}: {e}")
    st.stop()


# ---------------------------------------------------------------------------
# Detection audit panel
# ---------------------------------------------------------------------------
with st.expander("Detection audit", expanded=True):
    c1, c2, c3 = st.columns(3)
    c1.text(f"Sheet: {data['sheet_name']}")
    c2.text(f"Header row: {data['header_row']}")
    c3.text(f"Total rows: {data['total_rows']}")

    valid_n = len(data["valid_deals"])
    skipped_n = sum(data["skipped"].values())
    reconciled = valid_n + skipped_n
    if reconciled == data["total_rows"]:
        st.success(
            f"Reconciliation PASS: {valid_n} valid + {skipped_n} skipped = "
            f"{reconciled} (total {data['total_rows']})"
        )
    else:
        st.error(
            f"Reconciliation FAIL: {valid_n} valid + {skipped_n} skipped = "
            f"{reconciled} but total processed = {data['total_rows']}"
        )

    if data["skipped"]:
        skip_df = pd.DataFrame(
            sorted(data["skipped"].items(), key=lambda kv: -kv[1]),
            columns=["Reason", "Count"],
        )
        st.dataframe(skip_df, hide_index=True, use_container_width=False)

    unmatched = data.get("unmatched_comments") or []
    if unmatched:
        st.markdown(
            f"**Unmatched suspicious comments** "
            f"(showing {min(20, len(unmatched))} of {len(unmatched)}):"
        )
        st.code("\n".join(unmatched[:20]))


# Early exit: zero valid deals — show audit, suppress metrics
if not data["valid_deals"]:
    st.info("No valid TP/SL deals found.")
    st.stop()


# ---------------------------------------------------------------------------
# Contract size editor (user-supplied, per-symbol)
# ---------------------------------------------------------------------------
st.subheader("Contract sizes")
st.caption(
    "Symbols extracted from the report. Type a contract size per symbol "
    "(units per 1 lot). Defaults pre-fill from config.py where known; "
    "blank rows mark Client Slippage in QC as unknown."
)

raw_symbols = sorted({
    str(d["symbol"]) for d in data["valid_deals"] if d.get("symbol")
})
editor_rows = []
for sym in raw_symbols:
    default = _contract_size_for(sym)
    editor_rows.append({
        "Symbol": sym,
        "Contract Size": float(default) if default is not None else None,
    })
editor_df = pd.DataFrame(editor_rows)

edited = st.data_editor(
    editor_df,
    column_config={
        "Symbol": st.column_config.TextColumn(disabled=True),
        "Contract Size": st.column_config.NumberColumn(
            help="Units per 1 lot. Leave blank to mark slippage in QC as unknown.",
            min_value=0.0,
            step=1.0,
            format="%.4f",
        ),
    },
    hide_index=True,
    num_rows="fixed",
    use_container_width=False,
    key="contract_editor",
)

user_contract_sizes: Dict[str, Optional[float]] = {}
for _, row in edited.iterrows():
    val = row["Contract Size"]
    if pd.isna(val) or val is None or float(val) <= 0:
        user_contract_sizes[row["Symbol"]] = None
    else:
        user_contract_sizes[row["Symbol"]] = float(val)


# ---------------------------------------------------------------------------
# Compute slippage for every valid row (single pass — UI never recomputes math)
# ---------------------------------------------------------------------------
results: List[Tuple[Dict[str, Any], SlippageResult]] = []
unknown_symbols = set()
for d in data["valid_deals"]:
    cs = user_contract_sizes.get(str(d["symbol"]))
    if cs is None:
        unknown_symbols.add(d["symbol"])
    r = compute_slippage(
        order_type=d["type"],
        trigger_type=d["trigger_type"],
        trigger_price=d["trigger_price"],
        executed_price=d["executed_price"],
        volume=d["volume"],
        contract_size=cs,
    )
    results.append((d, r))

if unknown_symbols:
    st.warning(
        f"Contract size missing for: {sorted(unknown_symbols)}. "
        "Fill the table above to compute Client Slippage in QC for these symbols."
    )


# ---------------------------------------------------------------------------
# Bucket summary
# ---------------------------------------------------------------------------
buckets: Dict[str, Dict[str, Any]] = defaultdict(
    lambda: {
        "total": 0,
        "POSITIVE": 0,
        "NEGATIVE": 0,
        "ZERO": 0,
        "points": 0.0,
        "qc": 0.0,
        "qc_known": True,
    }
)
for _, r in results:
    b = buckets[r.bucket]
    b["total"] += 1
    b[r.impact] += 1
    b["points"] += r.client_points
    if r.client_usd is None:
        b["qc_known"] = False
    else:
        b["qc"] += r.client_usd

BUCKET_ORDER = ["BUY;SL", "BUY;TP", "SELL;SL", "SELL;TP"]

st.subheader("Bucket summary")
cols = st.columns(4)
for col, name in zip(cols, BUCKET_ORDER):
    v = buckets.get(name)
    with col:
        st.markdown(f"### {name}")
        if v is None:
            st.metric("Total", 0)
            st.caption("No deals in this bucket")
        else:
            st.metric("Total", v["total"])
            st.metric("Positive", v["POSITIVE"])
            st.metric("Negative", v["NEGATIVE"])

# Bucket table
bucket_rows = []
grand = {"Total": 0, "Pos": 0, "Neg": 0, "Zero": 0, "Points": 0.0, "QC": 0.0,
         "_qc_known": True}
for name in BUCKET_ORDER:
    v = buckets.get(name, {"total": 0, "POSITIVE": 0, "NEGATIVE": 0, "ZERO": 0,
                           "points": 0.0, "qc": 0.0, "qc_known": True})
    bucket_rows.append({
        "Bucket": name,
        "Total": v["total"],
        "Pos": v["POSITIVE"],
        "Neg": v["NEGATIVE"],
        "Zero": v["ZERO"],
        "Slippage in Points": round(v["points"], 4),
        "Slippage in QC": round(v["qc"], 2) if v["qc_known"] else None,
    })
    grand["Total"] += v["total"]
    grand["Pos"] += v["POSITIVE"]
    grand["Neg"] += v["NEGATIVE"]
    grand["Zero"] += v["ZERO"]
    grand["Points"] += v["points"]
    if v["qc_known"]:
        grand["QC"] += v["qc"]
    else:
        grand["_qc_known"] = False

bucket_rows.append({
    "Bucket": "TOTAL",
    "Total": grand["Total"],
    "Pos": grand["Pos"],
    "Neg": grand["Neg"],
    "Zero": grand["Zero"],
    "Slippage in Points": round(grand["Points"], 4),
    "Slippage in QC": round(grand["QC"], 2) if grand["_qc_known"] else None,
})
bucket_df = pd.DataFrame(bucket_rows)
st.dataframe(
    bucket_df.style.format(
        {"Slippage in Points": "{:+.4f}", "Slippage in QC": "{:+,.2f}"},
        na_rep="—",
    ),
    hide_index=True,
    use_container_width=False,
)


# ---------------------------------------------------------------------------
# Live example per bucket
# ---------------------------------------------------------------------------
with st.expander("Worked example per bucket", expanded=False):
    seen = set()
    for d, r in results:
        if r.bucket in seen:
            continue
        seen.add(r.bucket)
        if r.order_type == "buy":
            arith = f"{r.trigger_price} - {r.executed_price} = {r.client_points:+.4f} points"
        else:
            arith = f"{r.executed_price} - {r.trigger_price} = {r.client_points:+.4f} points"
        qc_str = f"{r.client_usd:+,.2f}" if r.client_usd is not None else "—"
        st.markdown(f"#### {r.bucket}")
        st.text(
            f"Time                       : {d['time']}\n"
            f"Deal                       : {d['deal']}    Order : {d['order']}\n"
            f"Symbol                     : {d['symbol']}    Volume: {d['volume']}\n"
            f"Trigger                    : {r.trigger_type} @ {r.trigger_price}\n"
            f"Executed                   : {r.executed_price}\n"
            f"Formula                    : {arith}\n"
            f"Impact                     : {r.impact}\n"
            f"Client Slippage in Points  : {r.client_points:+.4f}\n"
            f"Client Slippage in QC      : {qc_str}"
        )


# ---------------------------------------------------------------------------
# Per-trade results dataframe
# ---------------------------------------------------------------------------
def _coerce_time(v):
    if isinstance(v, datetime):
        return v
    if v is None:
        return None
    s = str(v).strip()
    for fmt in (
        "%Y.%m.%d %H:%M:%S.%f",
        "%Y.%m.%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


trade_rows = []
for d, r in results:
    t = _coerce_time(d["time"])
    trade_rows.append({
        "Time": t if t is not None else d["time"],
        "Deal": d["deal"],
        "Symbol": d["symbol"],
        "Type": r.order_type.upper(),
        "Volume": r.volume,
        "Trigger Type": r.trigger_type,
        "Trigger Price": r.trigger_price,
        "Executed Price": r.executed_price,
        "Client Slippage in Points": round(r.client_points, 4),
        "Client Slippage in QC": round(r.client_usd, 2) if r.client_usd is not None else None,
        "Impact": r.impact,
        "Comment": d["comment"],
    })
trade_df = pd.DataFrame(trade_rows)


st.subheader("Per-trade results")

# Filters
f_cols = st.columns([2, 1, 1, 1, 2])
symbols_all = sorted(trade_df["Symbol"].dropna().unique().tolist())
sel_symbols = f_cols[0].multiselect("Symbol", options=symbols_all, default=symbols_all)
sel_type = f_cols[1].selectbox("Type", options=["All", "BUY", "SELL"], index=0)
sel_trigger = f_cols[2].selectbox("Trigger", options=["All", "TP", "SL"], index=0)
sel_impact = f_cols[3].selectbox(
    "Impact", options=["All", "POSITIVE", "NEGATIVE", "ZERO"], index=0
)

# Date range
time_series = pd.to_datetime(trade_df["Time"], errors="coerce")
has_dates = time_series.notna().any()
if has_dates:
    dmin = time_series.min().date()
    dmax = time_series.max().date()
    sel_dates = f_cols[4].date_input(
        "Date range", value=(dmin, dmax), min_value=dmin, max_value=dmax
    )
else:
    sel_dates = None

# Apply filters
filtered_df = trade_df.copy()
if sel_symbols:
    filtered_df = filtered_df[filtered_df["Symbol"].isin(sel_symbols)]
if sel_type != "All":
    filtered_df = filtered_df[filtered_df["Type"] == sel_type]
if sel_trigger != "All":
    filtered_df = filtered_df[filtered_df["Trigger Type"] == sel_trigger]
if sel_impact != "All":
    filtered_df = filtered_df[filtered_df["Impact"] == sel_impact]
if has_dates and isinstance(sel_dates, tuple) and len(sel_dates) == 2:
    d_start, d_end = sel_dates
    ts = pd.to_datetime(filtered_df["Time"], errors="coerce")
    mask = (ts.dt.date >= d_start) & (ts.dt.date <= d_end)
    filtered_df = filtered_df[mask.fillna(False)]


def _row_color(row):
    if row["Impact"] == "POSITIVE":
        return ["background-color: #d4edda"] * len(row)
    if row["Impact"] == "NEGATIVE":
        return ["background-color: #f8d7da"] * len(row)
    return [""] * len(row)


if filtered_df.empty:
    st.info("No valid TP/SL deals found in this view.")
else:
    styled = filtered_df.style.apply(_row_color, axis=1).format(
        {
            "Volume": "{:.2f}",
            "Trigger Price": "{:.4f}",
            "Executed Price": "{:.4f}",
            "Client Slippage in Points": "{:+.4f}",
            "Client Slippage in QC": "{:+,.2f}",
        },
        na_rep="—",
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Aggregate metrics (after filters)
# ---------------------------------------------------------------------------
if not filtered_df.empty:
    st.subheader("Aggregate (filtered)")
    qc_series = filtered_df["Client Slippage in QC"]
    points_series = filtered_df["Client Slippage in Points"]
    any_unknown_qc = qc_series.isna().any()

    m1, m2, m3, m4 = st.columns(4)
    if any_unknown_qc:
        m1.metric(
            "Total Client Slippage (QC)",
            "—",
            delta=f"{points_series.sum():+.4f} pts",
        )
    else:
        m1.metric(
            "Total Client Slippage (QC)",
            f"{qc_series.sum():+,.2f}",
            delta=f"{points_series.sum():+.4f} pts",
        )
    m2.metric(
        "Avg per trade (QC)",
        "—" if any_unknown_qc else f"{qc_series.mean():+,.2f}",
    )
    m3.metric(
        "Worst trade (QC)",
        "—" if any_unknown_qc else f"{qc_series.min():+,.2f}",
    )
    m4.metric(
        "Best trade (QC)",
        "—" if any_unknown_qc else f"{qc_series.max():+,.2f}",
    )


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------
st.subheader("Download")
dl_cols = st.columns(2)

csv_bytes = filtered_df.to_csv(index=False).encode("utf-8")
dl_cols[0].download_button(
    label="Download CSV (filtered trades)",
    data=csv_bytes,
    file_name="slippage_trades.csv",
    mime="text/csv",
)

xlsx_buf = io.BytesIO()
with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
    filtered_df.to_excel(writer, sheet_name="Trades", index=False)
    bucket_df.to_excel(writer, sheet_name="BucketSummary", index=False)

    audit_rows = [
        {"Field": "Sheet", "Value": data["sheet_name"]},
        {"Field": "Header row", "Value": data["header_row"]},
        {"Field": "Total rows", "Value": data["total_rows"]},
        {"Field": "Valid deals", "Value": len(data["valid_deals"])},
        {"Field": "Skipped deals", "Value": sum(data["skipped"].values())},
    ]
    pd.DataFrame(audit_rows).to_excel(writer, sheet_name="Audit", index=False, startrow=0)
    skip_df_dl = pd.DataFrame(
        sorted(data["skipped"].items(), key=lambda kv: -kv[1]),
        columns=["Reason", "Count"],
    )
    skip_df_dl.to_excel(writer, sheet_name="Audit", index=False,
                        startrow=len(audit_rows) + 2)
    contract_size_dl = edited.copy()
    contract_size_dl.to_excel(writer, sheet_name="Audit", index=False,
                              startrow=len(audit_rows) + 4 + len(skip_df_dl))
    if data.get("unmatched_comments"):
        pd.DataFrame({"Unmatched comments": data["unmatched_comments"]}).to_excel(
            writer,
            sheet_name="Audit",
            index=False,
            startrow=len(audit_rows) + 6 + len(skip_df_dl) + len(contract_size_dl),
        )

dl_cols[1].download_button(
    label="Download XLSX (3 sheets)",
    data=xlsx_buf.getvalue(),
    file_name="slippage_report.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
