"""
Streamlit components for the Pending Fills tab.

Public entry: render(tmp_path, user_contract_sizes) -> None

The function expects:
  - tmp_path                : path to the uploaded MT5 xlsx
  - user_contract_sizes     : dict[symbol -> Optional[float]] from the shared
                              contract-size editor in app.py

It owns everything visible inside the second tab:
  - Audit panel (orders header, in-deals, match reconciliation)
  - 4-card bucket summary (only populated buckets)
  - Bucket table with totals
  - Worked example expander
  - Per-trade table with filters
  - Aggregate metrics
  - CSV + XLSX downloads

This module contains NO slippage math. All math goes through
pending_slippage.compute_pending_slippage.
"""
import io
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from pending_orders.matcher import aggregate_partial_fills, match_orders_to_deals
from pending_orders.orders_parser import extract_in_deals, extract_orders
from pending_orders.pending_slippage import (
    PendingSlippageResult,
    compute_pending_slippage,
)


BUCKET_ORDER = [
    "BUY;LIMIT", "BUY;STOP", "BUY;STOP_LIMIT",
    "SELL;LIMIT", "SELL;STOP", "SELL;STOP_LIMIT",
]


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


def render(tmp_path: str, user_contract_sizes: Dict[str, Optional[float]]) -> None:
    # -----------------------------------------------------------------
    # Parse
    # -----------------------------------------------------------------
    try:
        orders_data = extract_orders(tmp_path)
        in_deals_data = extract_in_deals(tmp_path)
    except Exception as e:
        st.error(f"Pending parser failed: {type(e).__name__}: {e}")
        return

    match = match_orders_to_deals(
        orders_data["filled_pendings"], in_deals_data["in_deals"]
    )
    rec = match["reconciliation"]

    # -----------------------------------------------------------------
    # Audit panel
    # -----------------------------------------------------------------
    with st.expander("Pending detection audit", expanded=True):
        c1, c2, c3 = st.columns(3)
        c1.text(f"Orders header row : {orders_data['header_row']}")
        c2.text(f"In-deals total    : {len(in_deals_data['in_deals'])}")
        c3.text(f"Order rows scanned: {orders_data['total_rows']}")

        st.markdown("**Order-to-deal reconciliation**")
        st.text(
            f"1-to-1 matches               : {rec['matched_1to1']}\n"
            f"1-to-N matches (partial)     : {rec['matched_1toN']}\n"
            f"Orders without deal          : {rec['orders_without_deal']}  "
            f"{'(suspicious)' if rec['orders_without_deal'] > 0 else ''}\n"
            f"In-deals without parent      : {rec['deals_without_pending_order']}  "
            f"(market opens — expected)\n"
            f"Duplicate order IDs          : {rec['filled_pendings_duplicate']}"
        )

        if orders_data["skipped"]:
            st.markdown("**Orders skipped**")
            skip_df = pd.DataFrame(
                sorted(orders_data["skipped"].items(), key=lambda kv: -kv[1]),
                columns=["Reason", "Count"],
            )
            st.dataframe(skip_df, hide_index=True, use_container_width=False)

        if match["orders_without_deal"]:
            st.warning(
                f"{len(match['orders_without_deal'])} filled orders with no matching in-deal."
            )

    if not match["matched"] and not match["partial_or_multi"]:
        st.info("No matched pending fills found.")
        return

    # -----------------------------------------------------------------
    # Compute slippage (single pass — UI never recomputes)
    # -----------------------------------------------------------------
    results: List[Tuple[Dict[str, Any], Dict[str, Any], PendingSlippageResult]] = []
    unknown_symbols = set()

    for order, deal in match["matched"]:
        cs = user_contract_sizes.get(str(order["symbol"]))
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
        cs = user_contract_sizes.get(str(order["symbol"]))
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
        st.warning(
            f"Contract size missing for: {sorted(unknown_symbols)}. "
            "Set it in the editor above to compute Client Slippage in QC."
        )

    # -----------------------------------------------------------------
    # Bucket summary
    # -----------------------------------------------------------------
    buckets: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "total": 0, "POSITIVE": 0, "NEGATIVE": 0, "ZERO": 0,
            "points": 0.0, "qc": 0.0, "qc_known": True,
        }
    )
    for _, _, r in results:
        b = buckets[r.bucket]
        b["total"] += 1
        b[r.impact] += 1
        b["points"] += r.client_points
        if r.client_usd is None:
            b["qc_known"] = False
        else:
            b["qc"] += r.client_usd

    populated = [name for name in BUCKET_ORDER if buckets.get(name, {}).get("total", 0) > 0]

    st.subheader("Bucket summary")
    if populated:
        cols = st.columns(max(len(populated), 1))
        for col, name in zip(cols, populated):
            v = buckets[name]
            with col:
                st.markdown(f"### {name}")
                st.metric("Total", v["total"])
                st.metric("Positive", v["POSITIVE"])
                st.metric("Negative", v["NEGATIVE"])

    # Bucket table (always shows all 6, missing ones zeroed out)
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

    # -----------------------------------------------------------------
    # Worked example per populated bucket
    # -----------------------------------------------------------------
    with st.expander("Worked example per bucket", expanded=False):
        seen = set()
        for order, deal, r in results:
            if r.bucket in seen:
                continue
            seen.add(r.bucket)
            if r.order_type == "buy":
                arith = (f"{r.reference_price} - {r.executed_price} = "
                         f"{r.client_points:+.4f} points")
            else:
                arith = (f"{r.executed_price} - {r.reference_price} = "
                         f"{r.client_points:+.4f} points")
            qc_str = f"{r.client_usd:+,.2f}" if r.client_usd is not None else "—"
            agg_note = "  (aggregated VWAP)" if r.was_aggregated else ""
            st.markdown(f"#### {r.bucket}")
            st.text(
                f"Order ID                   : {r.order_id}\n"
                f"Deal ID                    : {r.deal_id}{agg_note}\n"
                f"Subtype                    : {order['type']}\n"
                f"Open time                  : {order['open_time']}\n"
                f"Fill time                  : {order.get('fill_time', '—')}\n"
                f"Symbol / Volume            : {order['symbol']} / {r.volume}\n"
                f"Requested @                : {r.reference_price}\n"
                f"Executed @                 : {r.executed_price}\n"
                f"Formula                    : {arith}\n"
                f"Impact                     : {r.impact}\n"
                f"Client Slippage in Points  : {r.client_points:+.4f}\n"
                f"Client Slippage in QC      : {qc_str}"
            )

    # -----------------------------------------------------------------
    # Per-trade table
    # -----------------------------------------------------------------
    trade_rows = []
    for order, deal, r in results:
        open_t = _coerce_time(order["open_time"])
        fill_t = _coerce_time(order.get("fill_time"))
        deal_id_disp = (",".join(str(x) for x in r.deal_id)
                        if isinstance(r.deal_id, list) else r.deal_id)
        trade_rows.append({
            "Open Time": open_t if open_t is not None else order["open_time"],
            "Fill Time": fill_t if fill_t is not None else order.get("fill_time"),
            "Order ID": r.order_id,
            "Deal ID": deal_id_disp,
            "Symbol": order["symbol"],
            "Subtype": order["type"].upper(),
            "Volume": r.volume,
            "Requested Price": r.reference_price,
            "Executed Price": r.executed_price,
            "Client Slippage in Points": round(r.client_points, 4),
            "Client Slippage in QC": round(r.client_usd, 2) if r.client_usd is not None else None,
            "Impact": r.impact,
            "Aggregated": r.was_aggregated,
        })
    trade_df = pd.DataFrame(trade_rows)

    st.subheader("Per-trade results")

    f_cols = st.columns([2, 1, 1, 1, 2])
    symbols_all = sorted(trade_df["Symbol"].dropna().astype(str).unique().tolist())
    sel_symbols = f_cols[0].multiselect(
        "Symbol", options=symbols_all, default=symbols_all, key="pend_sym"
    )
    base_options = ["All", "BUY", "SELL"]
    sel_base = f_cols[1].selectbox("Base", options=base_options, index=0, key="pend_base")
    subtypes_all = sorted(trade_df["Subtype"].unique().tolist())
    sel_subtype = f_cols[2].selectbox(
        "Subtype", options=["All"] + subtypes_all, index=0, key="pend_sub"
    )
    sel_impact = f_cols[3].selectbox(
        "Impact", options=["All", "POSITIVE", "NEGATIVE", "ZERO"], index=0, key="pend_imp"
    )

    time_series = pd.to_datetime(trade_df["Fill Time"], errors="coerce")
    has_dates = time_series.notna().any()
    if has_dates:
        dmin = time_series.min().date()
        dmax = time_series.max().date()
        sel_dates = f_cols[4].date_input(
            "Fill date range",
            value=(dmin, dmax),
            min_value=dmin,
            max_value=dmax,
            key="pend_dates",
        )
    else:
        sel_dates = None

    filtered_df = trade_df.copy()
    if sel_symbols:
        filtered_df = filtered_df[filtered_df["Symbol"].astype(str).isin(sel_symbols)]
    if sel_base != "All":
        filtered_df = filtered_df[filtered_df["Subtype"].str.startswith(sel_base)]
    if sel_subtype != "All":
        filtered_df = filtered_df[filtered_df["Subtype"] == sel_subtype]
    if sel_impact != "All":
        filtered_df = filtered_df[filtered_df["Impact"] == sel_impact]
    if has_dates and isinstance(sel_dates, tuple) and len(sel_dates) == 2:
        d_start, d_end = sel_dates
        ts = pd.to_datetime(filtered_df["Fill Time"], errors="coerce")
        mask = (ts.dt.date >= d_start) & (ts.dt.date <= d_end)
        filtered_df = filtered_df[mask.fillna(False)]

    def _row_color(row):
        if row["Impact"] == "POSITIVE":
            return ["background-color: #d4edda"] * len(row)
        if row["Impact"] == "NEGATIVE":
            return ["background-color: #f8d7da"] * len(row)
        return [""] * len(row)

    if filtered_df.empty:
        st.info("No pending fills found in this view.")
    else:
        styled = filtered_df.style.apply(_row_color, axis=1).format(
            {
                "Volume": "{:.2f}",
                "Requested Price": "{:.4f}",
                "Executed Price": "{:.4f}",
                "Client Slippage in Points": "{:+.4f}",
                "Client Slippage in QC": "{:+,.2f}",
            },
            na_rep="—",
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)

    # -----------------------------------------------------------------
    # Aggregate metrics
    # -----------------------------------------------------------------
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

    # -----------------------------------------------------------------
    # Downloads
    # -----------------------------------------------------------------
    st.subheader("Download")
    dl_cols = st.columns(2)

    csv_bytes = filtered_df.to_csv(index=False).encode("utf-8")
    dl_cols[0].download_button(
        label="Download CSV (filtered pending trades)",
        data=csv_bytes,
        file_name="pending_slippage_trades.csv",
        mime="text/csv",
        key="pend_dl_csv",
    )

    xlsx_buf = io.BytesIO()
    with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
        filtered_df.to_excel(writer, sheet_name="PendingTrades", index=False)
        bucket_df.to_excel(writer, sheet_name="PendingBucketSummary", index=False)

        audit_rows = [
            {"Field": "Sheet", "Value": orders_data["sheet_name"]},
            {"Field": "Orders header row", "Value": orders_data["header_row"]},
            {"Field": "Order rows scanned", "Value": orders_data["total_rows"]},
            {"Field": "Filled pendings", "Value": len(orders_data["filled_pendings"])},
            {"Field": "In-deals total", "Value": len(in_deals_data["in_deals"])},
            {"Field": "Matched 1-to-1", "Value": rec["matched_1to1"]},
            {"Field": "Matched 1-to-N", "Value": rec["matched_1toN"]},
            {"Field": "Orders without deal", "Value": rec["orders_without_deal"]},
            {"Field": "Deals without parent", "Value": rec["deals_without_pending_order"]},
            {"Field": "Duplicate order IDs", "Value": rec["filled_pendings_duplicate"]},
        ]
        pd.DataFrame(audit_rows).to_excel(
            writer, sheet_name="PendingAudit", index=False, startrow=0
        )
        if orders_data["skipped"]:
            skip_df_dl = pd.DataFrame(
                sorted(orders_data["skipped"].items(), key=lambda kv: -kv[1]),
                columns=["Reason", "Count"],
            )
            skip_df_dl.to_excel(
                writer,
                sheet_name="PendingAudit",
                index=False,
                startrow=len(audit_rows) + 2,
            )

    dl_cols[1].download_button(
        label="Download XLSX (Pending: 3 sheets)",
        data=xlsx_buf.getvalue(),
        file_name="pending_slippage_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="pend_dl_xlsx",
    )
