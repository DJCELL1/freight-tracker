from datetime import date

import pandas as pd
import streamlit as st

import eta as eta_calc
import ocr
import parser
import store

st.subheader("Add manifest")
st.caption(
    "Drop in the despatch manifest pack — the manifest page plus its delivery "
    "dockets. Scanned packs are read with OCR, so check the parse below before "
    "saving; anything you correct here is what gets tracked."
)

uploaded = st.file_uploader("Manifest PDF", type="pdf", label_visibility="collapsed")

if uploaded is None:
    st.session_state.pop("parsed", None)
    st.stop()

# Re-parse only when a different file arrives, so edits on the review form
# survive the rerun that every widget interaction triggers.
if st.session_state.get("parsed_file") != uploaded.name:
    with st.spinner("Reading the manifest…"):
        try:
            st.session_state["parsed"] = parser.parse(uploaded)
            st.session_state["parsed_file"] = uploaded.name
        except (parser.ManifestParseError, ocr.PdfReadError) as e:
            st.session_state.pop("parsed", None)
            st.error(str(e))
            st.stop()

shipment = st.session_state.get("parsed")
if not shipment:
    st.stop()

if shipment["ocr_used"]:
    st.warning(
        "This pack had no text layer, so it was read by OCR. Scanned numbers are "
        "usually right but worth a glance — order numbers were cross-checked "
        "against the delivery dockets.",
        icon="🔍",
    )

st.markdown("**Check the shipment**")
col1, col2, col3 = st.columns(3)
manifest_no = col1.text_input("Manifest no.", value=shipment.get("manifest_no") or "")
despatch_date = col2.date_input(
    "Left Vic on", value=eta_calc.to_date(shipment.get("despatch_date")) or date.today()
)
origin = col3.text_input(
    "Origin", value=shipment.get("origin") or store.get_setting("default_origin")
)
col4, col5 = st.columns(2)
carrier_ref = col4.text_input("Carrier / consignment ref", value=shipment.get("carrier_ref") or "")
despatch_time = col5.text_input("Despatch time", value=shipment.get("despatch_time") or "")

transit_days, business_days = store.get_transit_rule()
projected = eta_calc.eta_date(despatch_date, transit_days, business_days)
st.info(
    f"ETA **{projected:%A %d %B %Y}** — {transit_days} "
    f"{'working' if business_days else 'calendar'} days after despatch.",
    icon="🚚",
)

st.markdown("**Check the orders**")
edited = st.data_editor(
    pd.DataFrame([
        {
            "Order": c["order_no"],
            "Deliver to": c["company"] or "",
            "Address": c["address"] or "",
            "Customer PO": c["external_doc"] or "",
            "Docket": c["docket_no"] or "",
            "Items": len(c["lines"]),
            "Qty": sum(l["qty"] for l in c["lines"]),
        }
        for c in shipment["consignments"]
    ]),
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    disabled=["Items", "Qty"],
    key="consignment_editor",
)

with st.expander("Item lines read off the dockets"):
    for consignment in shipment["consignments"]:
        st.markdown(f"**{consignment['order_no']}** — {consignment['docket_no'] or 'no docket no.'}")
        if consignment["lines"]:
            st.dataframe(
                pd.DataFrame(consignment["lines"]).rename(columns={
                    "item_code": "Code", "description": "Description", "qty": "Qty", "uom": "UOM",
                }),
                use_container_width=True, hide_index=True,
            )
        else:
            st.caption("No item lines could be read off this docket.")

if not manifest_no.strip():
    st.error("A manifest number is needed to save — it is how a re-uploaded pack is recognised.")
    st.stop()

if st.button("Save shipment", type="primary"):
    shipment["manifest_no"] = manifest_no.strip()
    shipment["despatch_date"] = despatch_date.isoformat()
    shipment["despatch_time"] = despatch_time.strip()
    shipment["carrier_ref"] = carrier_ref.strip()
    shipment["origin"] = origin.strip()
    for consignment, (_, row) in zip(shipment["consignments"], edited.iterrows()):
        consignment["order_no"] = str(row["Order"]).strip()
        consignment["company"] = str(row["Deliver to"]).strip()
        consignment["address"] = str(row["Address"]).strip()
        consignment["external_doc"] = str(row["Customer PO"]).strip()
        consignment["docket_no"] = str(row["Docket"]).strip()

    saved, action = store.save_shipment(shipment, source_file=uploaded.name)
    st.session_state.pop("parsed", None)
    st.session_state.pop("parsed_file", None)
    st.success(
        f"**{saved}** {action} — {len(shipment['consignments'])} order(s) tracked, "
        f"ETA {projected:%a %d %b}. See the Dashboard."
    )
