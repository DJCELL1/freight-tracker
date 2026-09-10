from datetime import date

import pandas as pd
import streamlit as st

import eta as eta_calc
import store

STATUS_ICONS = {
    eta_calc.DELIVERED: "✅ Delivered",
    eta_calc.DUE_TODAY: "📦 Due today",
    eta_calc.OVERDUE: "⚠️ Overdue",
    eta_calc.IN_TRANSIT: "🚚 In transit",
}

st.subheader("What's left Vic")

transit_days, business_days = store.get_transit_rule()
rule = f"{transit_days} {'working' if business_days else 'calendar'} day{'s' if transit_days != 1 else ''}"
st.caption(
    f"Every order on every manifest you've uploaded, with an ETA of **despatch + {rule}**. "
    "Change the allowance on the Settings page."
)

rows = store.get_consignments()
if not rows:
    st.info("Nothing tracked yet — add a manifest PDF on the **Add manifest** page.")
    st.stop()

today = date.today()
for row in rows:
    row["eta"] = eta_calc.eta_date(row["despatch_date"], transit_days, business_days)
    row["status"] = eta_calc.status(row["eta"], today, row["delivered_on"])
    row["countdown"] = eta_calc.describe(row["eta"], today, row["delivered_on"])
    row["days_out"] = eta_calc.days_out(row["eta"], today)
    elapsed = (today - eta_calc.to_date(row["despatch_date"])).days
    total = max((row["eta"] - eta_calc.to_date(row["despatch_date"])).days, 1)
    row["progress"] = min(max(elapsed / total, 0.0), 1.0)

in_transit = [r for r in rows if r["status"] == eta_calc.IN_TRANSIT]
due_today = [r for r in rows if r["status"] == eta_calc.DUE_TODAY]
overdue = [r for r in rows if r["status"] == eta_calc.OVERDUE]
delivered = [r for r in rows if r["status"] == eta_calc.DELIVERED]

cols = st.columns(4)
cols[0].metric("On the road", len(in_transit))
cols[1].metric("Due today", len(due_today))
cols[2].metric("Overdue", len(overdue), delta=None if not overdue else "chase these", delta_color="inverse")
cols[3].metric("Delivered", len(delivered))

next_up = sorted(
    [r for r in rows if r["status"] != eta_calc.DELIVERED and r["days_out"] is not None],
    key=lambda r: r["days_out"],
)
if next_up:
    soonest = next_up[0]
    st.markdown(
        f"**Next in:** {soonest['order_no']} — left Vic "
        f"{eta_calc.to_date(soonest['despatch_date']):%a %d %b}, "
        f"due **{soonest['eta']:%a %d %b}** ({soonest['countdown']})."
    )

show_delivered = st.toggle("Include delivered", value=False)
visible = rows if show_delivered else [r for r in rows if r["status"] != eta_calc.DELIVERED]
if not visible:
    st.success("Nothing outstanding — everything uploaded has been marked delivered.")
    st.stop()

table = pd.DataFrame([
    {
        "Status": STATUS_ICONS[r["status"]],
        "Order": r["order_no"],
        "Left Vic": eta_calc.to_date(r["despatch_date"]),
        "ETA": r["eta"],
        "Countdown": r["countdown"],
        "Transit": r["progress"],
        "Customer PO": r["external_doc"] or "",
        "Docket": r["docket_no"] or "",
        "Items": r["line_count"],
        "Qty": r["total_qty"],
        "Deliver to": r["company"] or "",
        "Manifest": r["manifest_no"],
        "Carrier ref": r["carrier_ref"] or "",
    }
    for r in visible
])

st.dataframe(
    table,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Left Vic": st.column_config.DateColumn(format="ddd DD MMM"),
        "ETA": st.column_config.DateColumn(format="ddd DD MMM"),
        "Transit": st.column_config.ProgressColumn(
            "Transit", help="How far through the transit allowance this order is",
            min_value=0.0, max_value=1.0, format=" ",
        ),
    },
)

st.divider()
st.markdown("**What's in each order**")
for row in visible:
    header = f"{STATUS_ICONS[row['status']]} · {row['order_no']} · due {row['eta']:%a %d %b} · {row['countdown']}"
    with st.expander(header):
        left, right = st.columns([2, 1])
        with left:
            st.markdown(
                f"**Manifest** {row['manifest_no']} — left {row['origin'] or 'Vic'} on "
                f"{eta_calc.to_date(row['despatch_date']):%A %d %B %Y}"
                + (f" at {row['despatch_time']}" if row["despatch_time"] else "")
            )
            st.markdown(
                f"**Deliver to** {row['company'] or '—'}"
                + (f", {row['address']}" if row["address"] else "")
            )
            st.markdown(
                f"**Customer PO** {row['external_doc'] or '—'} · **Docket** {row['docket_no'] or '—'}"
                + (f" · **Carrier** {row['carrier_ref']}" if row["carrier_ref"] else "")
            )
            lines = store.get_lines(row["id"])
            if lines:
                st.dataframe(
                    pd.DataFrame(lines).rename(columns={
                        "item_code": "Code", "description": "Description",
                        "qty": "Qty", "uom": "UOM",
                    }),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.caption(
                    "No item lines came off this docket — the scan sheared the quantity "
                    "column off the page. The order itself is still tracked."
                )
        with right:
            if row["delivered_on"]:
                st.success(f"Delivered {eta_calc.to_date(row['delivered_on']):%d %b %Y}")
                if st.button("Undo delivery", key=f"undo_{row['id']}"):
                    store.mark_delivered(row["id"], None)
                    st.rerun()
            else:
                landed = st.date_input("Arrived on", value=today, key=f"date_{row['id']}")
                if st.button("Mark delivered", key=f"deliver_{row['id']}"):
                    store.mark_delivered(row["id"], landed.isoformat())
                    st.rerun()
            notes = st.text_area("Notes", value=row["notes"] or "", key=f"notes_{row['id']}", height=90)
            if notes != (row["notes"] or ""):
                store.set_notes(row["id"], notes)
