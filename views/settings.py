from datetime import date

import streamlit as st

import eta as eta_calc
import store

st.subheader("Settings")

st.markdown("**Transit allowance**")
st.caption("How long freight takes to reach you after it leaves Vic. This drives every ETA.")

transit_days, business_days = store.get_transit_rule()
col1, col2 = st.columns(2)
new_days = col1.number_input("Days in transit", min_value=1, max_value=60, value=transit_days, step=1)
new_business = col2.toggle(
    "Count working days only",
    value=business_days,
    help="Off: plain calendar days, weekends included. On: weekends are skipped.",
)

example = eta_calc.eta_date(date.today(), new_days, new_business)
st.info(f"Freight leaving Vic today would be due **{example:%A %d %B %Y}**.", icon="🚚")

st.markdown("**Default origin**")
default_origin = st.text_input(
    "Used when the sender's address can't be read off a scanned pack",
    value=store.get_setting("default_origin"),
)

if st.button("Save settings", type="primary"):
    store.set_setting("transit_days", int(new_days))
    store.set_setting("business_days", "1" if new_business else "0")
    store.set_setting("default_origin", default_origin.strip())
    st.success("Saved — ETAs on the dashboard recalculate straight away.")

st.divider()
st.markdown("**Tracked manifests**")
manifests = {}
for row in store.get_consignments():
    manifests.setdefault(row["manifest_no"], []).append(row)

if not manifests:
    st.caption("No manifests uploaded yet.")
else:
    for manifest_no, rows in manifests.items():
        left, right = st.columns([4, 1])
        left.markdown(
            f"**{manifest_no}** — left {eta_calc.to_date(rows[0]['despatch_date']):%d %b %Y}, "
            f"{len(rows)} order(s), from `{rows[0]['source_file'] or 'unknown file'}`"
        )
        if right.button("Delete", key=f"del_{manifest_no}"):
            store.delete_shipment(manifest_no)
            st.rerun()
