import pandas as pd
import requests
import streamlit as st

from scripts.inventory import bag_key, build_inventory, filter_inventory, load_data, validate_data
from scripts.forms import addition_form, edit_form, settings, withdrawal_form
from scripts.github_inventory import GitHubError, GitHubInventory
from scripts.purchases import purchases
from scripts.withdrawal_history import live_withdrawals, withdrawal_history


from scripts.paths import DATA_DIR, ASSETS_DIR
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


def clear_browse_filters():
    st.session_state.update(browse_search="", browse_type="All", browse_subtype="All",
                            browse_box=None, browse_bag=None)


def browse(details, locations):
    inventory = build_inventory(details, locations)
    st.button("Clear filters", on_click=clear_browse_filters)
    search = st.text_input("Search by code, description, manufacturer, model, box or bag", key="browse_search")
    st.caption("All filters work together. Subtypes depend on the type; bags depend on the box. Leave a filter on All to include everything in that category.")
    type_column, subtype_column, box_column, bag_column = st.columns(4)
    types = sorted(inventory["type"].unique(), key=str.casefold)
    if st.session_state.get("browse_type", "All") not in ["All", *types]:
        st.session_state["browse_type"] = "All"
    selected_type = type_column.selectbox("Type", ["All", *types], key="browse_type")
    type_rows = inventory if selected_type == "All" else inventory[inventory["type"] == selected_type]
    subtypes = sorted({value for value in type_rows["subtype"] if value}, key=str.casefold)
    if st.session_state.get("browse_subtype", "All") not in ["All", *subtypes]:
        st.session_state["browse_subtype"] = "All"
    selected_subtype = subtype_column.selectbox("Subtype", ["All", *subtypes], key="browse_subtype")
    boxes = sorted({value for value in inventory["location"] if value}, key=str.casefold)
    if st.session_state.get("browse_box") not in [None, *boxes]:
        st.session_state["browse_box"] = None
    box = box_column.selectbox("Box", [None, *boxes], key="browse_box",
                               format_func=lambda value: "All boxes" if value is None else value)
    box_rows = filter_inventory(inventory, box=box)
    bags = sorted({bag_key(value) for value in box_rows["sublocation"] if value},
                  key=lambda value: (0, int(value)) if value.isascii() and value.isdigit() else (1, value.casefold()))
    if st.session_state.get("browse_bag") not in [None, *bags]:
        st.session_state["browse_bag"] = None
    bag = bag_column.selectbox("Bag", [None, *bags], key="browse_bag",
                               format_func=lambda value: "All bags" if value is None else value)
    results = filter_inventory(inventory, search, selected_type, selected_subtype, box, bag)
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
        "units": "Units", "status": "Notes",
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
    st.set_page_config(page_title="Delta LAB inventory", layout="wide")
    st.logo(str(ASSETS_DIR / "images" / "logo.png"))
    st.title("Delta LAB inventory")
    st.caption("Electromechanical Engineering School - Tecnológico de Costa Rica")
    config = settings()
    client = None
    try:
        if config["token"]:
            try:
                details, locations = live_data(config["token"], config["repository"], config["branch"])
                client = GitHubInventory(config["token"], config["repository"], config["branch"])
            except (GitHubError, ValueError) as error:
                st.warning("Could not refresh from GitHub. Showing the local copy; changes are temporarily disabled.")
                details, locations = load_data(DATA_DIR)
        else:
            details, locations = load_data(DATA_DIR)
    except (OSError, ValueError, pd.errors.ParserError) as error:
        st.error(f"Could not load inventory: {error}")
        st.stop()
    action = st.radio("What would you like to do?", ("Browse", "Add", "Edit", "Withdraw", "Purchases", "History"), horizontal=True)
    if action == "Add":
        addition_form(client, details, locations, config["add_password"], live_data.clear)
    elif action == "Edit":
        issues = validate_data(details, locations)
        if issues:
            with st.expander(f"Data to review ({len(issues)})"):
                for issue in issues:
                    st.write(f"• {issue}")
        edit_form(client, details, locations, config["add_password"], live_data.clear)
    elif action == "Withdraw":
        def on_withdrawal_saved():
            live_data.clear()
            live_withdrawals.clear()
        withdrawal_form(client, details, locations, config["withdraw_password"], on_withdrawal_saved)
    elif action == "Purchases":
        purchases(client, config)
    elif action == "History":
        withdrawal_history(client, config, details)
    else:
        st.subheader("Inventory")
        if client and st.button("Refresh stock"):
            live_data.clear()
            st.rerun()
        browse(details, locations)


if __name__ == "__main__":
    main()
