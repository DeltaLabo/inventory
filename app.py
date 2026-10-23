from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from inventory import build_inventory, filter_inventory, load_data, validate_data
from forms import addition_form, edit_form, settings, withdrawal_form
from github_inventory import GitHubError, GitHubInventory


ROOT = Path(__file__).resolve().parent
IMAGE_BASE = "https://raw.githubusercontent.com/DeltaLabo/inventory_pictures/main/inventory_images_ready"


@st.cache_data(ttl=3600, max_entries=512, show_spinner=False)
def image_url(code, previous_code=""):
    for image_code in dict.fromkeys(value for value in (code, previous_code) if value):
        for extension in ("png", "jpg"):
            url = f"{IMAGE_BASE}/{image_code}.{extension}"
            try:
                if requests.head(url, timeout=3).status_code == 200:
                    return url
            except requests.RequestException:
                return None
    return None


@st.cache_data(ttl=15, max_entries=4, show_spinner=False)
def live_data(token, repository, branch):
    return GitHubInventory(token, repository, branch).snapshot()


def browse(details, locations):
    inventory = build_inventory(details, locations)
    search = st.text_input("Search by code, description, manufacturer, model, box or bag")
    types = sorted(inventory["type"].unique(), key=str.casefold)
    selected_type = st.selectbox("Type", ["All", *types])
    type_rows = inventory if selected_type == "All" else inventory[inventory["type"] == selected_type]
    subtypes = sorted(type_rows["subtype"].unique(), key=str.casefold)
    selected_subtype = st.selectbox("Subtype", ["All", *subtypes])
    results = filter_inventory(inventory, search, selected_type, selected_subtype)
    st.caption(f"{len(results)} records")
    st.download_button(
        "Download results as CSV", results.to_csv(index=False).encode("utf-8-sig"),
        file_name="inventory.csv", mime="text/csv",
    )
    show_images = st.checkbox("Show images", value=False)
    if results.empty:
        st.info("No matches found.")
        return

    labels = {
        "code": "Code", "description": "Description", "manufacturer": "Manufacturer",
        "model": "Model", "location": "Box", "sublocation": "Bag",
        "units": "Recorded units", "available": "Available", "status": "Notes",
    }
    st.dataframe(results[list(labels)].rename(columns=labels), hide_index=True, width="stretch")
    if show_images:
        codes = results["code"].drop_duplicates().tolist()
        pages = max(1, (len(codes) + 11) // 12)
        page = st.number_input("Image page", min_value=1, max_value=pages, step=1)
        for code in codes[(page - 1) * 12:page * 12]:
            product = results[results["code"].eq(code)].iloc[0]
            url = image_url(code, product.get("previous_code", ""))
            if url:
                st.image(url, caption=code, width=150)
            else:
                st.caption(f"{code}: no image")


def main():
    st.set_page_config(page_title="DeltaLAB Inventory", layout="wide")
    st.title("Delta LAB")
    st.caption("School of Electromechanical Engineering — Costa Rica Institute of Technology")
    config = settings()
    client = None
    try:
        if config["token"]:
            try:
                details, locations = live_data(config["token"], config["repository"], config["branch"])
                client = GitHubInventory(config["token"], config["repository"], config["branch"])
            except (GitHubError, ValueError) as error:
                st.warning("Could not refresh from GitHub. Showing the local copy; changes are temporarily disabled.")
                details, locations = load_data(ROOT)
        else:
            details, locations = load_data(ROOT)
    except (OSError, ValueError, pd.errors.ParserError) as error:
        st.error(f"Could not load inventory: {error}")
        st.stop()
    action = st.radio("What would you like to do?", ("Browse", "Add", "Edit", "Withdraw"), horizontal=True)
    if action == "Add":
        addition_form(client, details, locations, config["add_password"])
    elif action == "Edit":
        issues = validate_data(details, locations)
        if issues:
            with st.expander(f"Data to review ({len(issues)})"):
                for issue in issues:
                    st.write(f"• {issue}")
        edit_form(client, details, locations, config["add_password"])
    elif action == "Withdraw":
        withdrawal_form(client, details, locations, config["withdraw_password"], live_data.clear)
    else:
        st.subheader("Inventory")
        if client and st.button("Refresh stock"):
            live_data.clear()
            st.rerun()
        browse(details, locations)


if __name__ == "__main__":
    main()
