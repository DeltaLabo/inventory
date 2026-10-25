"""Purchase requests and a complete quotation export, separate from physical stock."""

import pandas as pd
import streamlit as st

from scripts.forms import operation_id, password_matches, show_completed
from scripts.github_inventory import GitHubError, GitHubInventory, PURCHASE_COLUMNS, read_rows
from scripts.inventory import spreadsheet_csv


from scripts.paths import DATA_DIR
LABELS = {
    "project": "Project", "description": "Description", "manufacturer": "Manufacturer",
    "model": "Model", "quantity": "Quantity", "person": "Requested by",
    "link": "Product link", "notes": "Notes", "timestamp": "Requested at (UTC)", "id": "Request ID",
}


@st.cache_data(ttl=15, max_entries=4, show_spinner=False)
def live_purchases(token, repository, branch):
    return GitHubInventory(token, repository, branch).purchase_snapshot()


def quotation_frame(rows):
    frame = pd.DataFrame(rows, columns=PURCHASE_COLUMNS)
    return frame[list(LABELS)].rename(columns=LABELS)


def quotation_csv(rows):
    return spreadsheet_csv(quotation_frame(rows))


def purchase_form(client, password):
    st.subheader("Request a purchase")
    st.caption("Project, requester, quantity and product link are required. Use the withdrawal password to submit.")
    if show_completed("purchase"):
        return
    if client is None or not password:
        st.info("Purchase requests are not enabled yet.")
        return
    request_id = operation_id("purchase")
    with st.form("purchase_form"):
        description = st.text_input("Description", max_chars=300, key="purchase_field_description")
        quantity = st.number_input("Quantity requested", min_value=1, max_value=1000000, step=1, key="purchase_field_quantity")
        project = st.text_input("Project", max_chars=300, key="purchase_field_project")
        person = st.text_input("Requested by (name or initials)", max_chars=100, key="purchase_field_person")
        link = st.text_input("Product link", max_chars=2000, placeholder="https://…",
                             help="Paste the exact product or variant link from Amazon, Temu, AliExpress, MicroJPM or another supplier.", key="purchase_field_link")
        manufacturer = st.text_input("Manufacturer (optional)", max_chars=300, key="purchase_field_manufacturer")
        model = st.text_input("Model / variant (optional)", max_chars=300, key="purchase_field_model")
        notes = st.text_input("Specifications or notes (optional)", max_chars=300, key="purchase_field_notes")
        entered = st.text_input("Withdrawal password", type="password", key="purchase_field_password")
        submitted = st.form_submit_button("Add purchase request")
    if submitted:
        if not password_matches(entered, password):
            st.error("Incorrect password.")
            return
        try:
            with st.spinner("Saving purchase request in GitHub…"):
                result = client.request_purchase(request_id, description, quantity, project, person, link, manufacturer, model, notes)
        except (ValueError, GitHubError) as error:
            st.error(str(error))
            return
        st.session_state["purchase_result"] = result
        st.session_state.pop("purchase_field_password", None)
        live_purchases.clear()
        st.rerun()


def purchases(client, config):
    st.subheader("Purchases")
    st.caption("One shared list for quotations. Each request retains its project and requester. Submitting a request does not place an order or change inventory.")
    try:
        if client:
            if st.button("Refresh purchase list"):
                live_purchases.clear()
                st.rerun()
            rows = live_purchases(config["token"], config["repository"], config["branch"])
        else:
            path = DATA_DIR / "purchase_requests.csv"
            rows = read_rows(path.read_text(encoding="utf-8-sig"), PURCHASE_COLUMNS)[1] if path.exists() else []
            st.info("Showing the local purchase-list snapshot. Connect to GitHub to see the latest requests.")
    except (GitHubError, ValueError, OSError, pd.errors.ParserError):
        st.error("Could not load the purchase list. Refresh to try again; requests are temporarily disabled.")
        return
    st.download_button("Download full quotation list (CSV)", quotation_csv(rows),
                       file_name="purchase_quotation_list.csv", mime="text/csv")
    st.caption(f"{len(rows)} purchase requests")
    if rows:
        st.dataframe(quotation_frame(rows), hide_index=True, width="stretch",
                     column_config={"Product link": st.column_config.LinkColumn("Product link")})
    else:
        st.info("No purchase requests yet.")
    purchase_form(client, config["withdraw_password"])
