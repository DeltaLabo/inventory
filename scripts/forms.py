"""Password-protected inventory forms; browsing never requires login."""

import hmac
import os
from uuid import uuid4

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from scripts.github_inventory import GitHubError, required, stock_units
import scripts.staff as staff_directory
from scripts.inventory import bag_key


def settings():
    def get(name, default=""):
        if name in os.environ:
            return os.environ[name]
        try:
            return str(st.secrets.get(name, default))
        except (FileNotFoundError, StreamlitSecretNotFoundError):
            return default

    return {
        "token": get("GITHUB_TOKEN"),
        "repository": get("INVENTORY_REPOSITORY", "DeltaLabo/inventory"),
        "branch": get("INVENTORY_BRANCH", "main"),
        "add_password": get("INVENTORY_ADD_PASSWORD"),
        "withdraw_password": get("INVENTORY_WITHDRAW_PASSWORD"),
    }


def password_matches(entered, expected):
    return bool(expected) and hmac.compare_digest(entered.encode("utf-8"), expected.encode("utf-8"))


def operation_id(kind):
    key = f"{kind}_id"
    if key not in st.session_state:
        st.session_state[key] = uuid4().hex
    return st.session_state[key]


def show_completed(kind):
    result = st.session_state.get(f"{kind}_result")
    if result is None:
        return False
    if kind in ("addition", "edit"):
        st.success("Addition saved. Stock is updated immediately." if kind == "addition" else "Changes saved. Inventory is updated immediately.")
        if isinstance(result, dict):
            st.caption(f"Product: {result['code']} · Record: {result['id']}")
    elif kind == "purchase":
        st.success("Purchase request recorded. It is now included in the quotation list.")
    else:
        st.success(f"Withdrawal recorded. Remaining after this withdrawal: {result}.")
    button_label = {"addition": "Record another addition", "edit": "Edit another product", "withdrawal": "Record another withdrawal", "purchase": "Request another purchase"}[kind]
    if st.button(button_label):
        st.session_state.pop(f"{kind}_result", None)
        st.session_state.pop(f"{kind}_id", None)
        if kind == "edit":
            for key in ("edit_context", "edit_original_item", "edit_original_stock"):
                st.session_state.pop(key, None)
        # Clear old form fields, especially the password, before another action.
        for key in list(st.session_state):
            if key.startswith(f"{kind}_field_"):
                del st.session_state[key]
        st.rerun()
    return True


def product_label(row):
    pending = f"Incomplete record ({row['previous_code']})" if row.get("previous_code") else "Description missing"
    description = row["description"] or row["model"] or row["subtype"] or pending
    return f"{description} · {row['code']}"


def addition_classification(details):
    create_new = "Create new…"
    types = sorted({value for value in details["type"] if value}, key=str.casefold)
    choice = st.selectbox("Type", [*types, create_new], index=None,
                          placeholder="Choose a type", key="addition_field_type_choice")
    item_type = st.text_input("New type", max_chars=300, key="addition_field_new_type").strip() if choice == create_new else (choice or "")
    # Reuse the spelling of a known type rather than introduce a case variant.
    if choice == create_new:
        item_type = next((value for value in types if value.casefold() == item_type.casefold()), item_type)
    if st.session_state.get("addition_type_context") != item_type:
        st.session_state.pop("addition_field_subtype_choice", None)
        st.session_state.pop("addition_field_new_subtype", None)
        st.session_state["addition_type_context"] = item_type
    subtypes = sorted({value for value in details.loc[details["type"].eq(item_type), "subtype"] if value}, key=str.casefold)
    subtype_choice = st.selectbox("Subtype", [*subtypes, create_new], index=None,
                                  placeholder="Choose a subtype", disabled=not item_type,
                                  key="addition_field_subtype_choice")
    subtype = st.text_input("New subtype", max_chars=300, key="addition_field_new_subtype").strip() if subtype_choice == create_new else (subtype_choice or "")
    if subtype_choice == create_new:
        subtype = next((value for value in subtypes if value.casefold() == subtype.casefold()), subtype)
    return {"type": item_type, "subtype": subtype}


def addition_storage(locations, existing_code=None):
    if existing_code:
        assigned = locations[locations["code"].eq(existing_code)]
        if not assigned.empty:
            if assigned.duplicated(["location", "sublocation"]).any() or assigned[["location", "sublocation"]].eq("").any().any():
                st.info("Review this product's box and bag in Edit before adding units.")
                return None
            slots = list(zip(assigned["location"], assigned["sublocation"]))
            slot = slots[0] if len(slots) == 1 else st.selectbox(
                "Registered box and bag", slots,
                format_func=lambda value: f"Box {value[0]} / bag {value[1]}",
            )
            st.caption(f"Units will be added to box {slot[0]}, bag {slot[1]}.")
            return slot
        st.info("This product has no registered box or bag. Set them for its first stock entry.")
    # These rerun independently so occupancy is visible before submission.
    boxes = sorted({value for value in locations["location"] if value}, key=str.casefold)
    location = st.selectbox(
        "Box", boxes, index=None, accept_new_options=True,
        placeholder="Search for or enter a box",
        help="Choose an existing box or type a new one and press Enter. It becomes available after saving the addition.",
        key="addition_field_location",
    ) or ""
    compartment = st.number_input(
        "Bag", min_value=0, value=None, step=1,
        placeholder="Bag number", key="addition_field_sublocation",
    )
    sublocation = "" if compartment is None else str(compartment)
    if location and compartment is not None:
        numbers = locations["sublocation"].map(lambda value: int(value) if value.isascii() and value.isdigit() else None)
        occupied = locations[locations["location"].eq(location) & numbers.eq(compartment)]
        if not occupied.empty:
            sublocation = occupied.iloc[0]["sublocation"]
            st.warning(f"Bag {compartment} in box {location} already contains products. You can continue and store another product in the same bag.")
    return location, sublocation


def addition_form(client, details, locations, password, on_saved=None):
    st.subheader("Add to inventory")
    st.caption("New product IDs are assigned automatically. Your addition is saved immediately using the addition password.")
    if show_completed("addition"):
        return
    if client is None or not password:
        st.info("Additions are not enabled yet.")
        return
    request_id = operation_id("addition")
    mode = st.radio("What would you like to add?", ("New product", "Restock an existing product"))
    existing_code = None
    classification = {}
    if mode != "New product":
        eligible = details[~details["code"].duplicated(keep=False)]
        if eligible.empty:
            st.info("No products with unique IDs are available to select.")
            return
        products = {row["code"]: product_label(row) for _, row in eligible.iterrows()}
        existing_code = st.selectbox("Product", sorted(products, key=products.get), format_func=products.get)
    else:
        # Outside the form so subtypes update immediately when the type changes.
        classification = addition_classification(details)
        st.caption("Use “Create new…” if an option is missing. It joins the catalog when the addition is saved.")
    storage = addition_storage(locations, existing_code)
    if storage is None:
        return
    location, sublocation = storage
    with st.form("addition_form"):
        item = dict(classification)
        if existing_code is None:
            item["description"] = st.text_input("Description", key="addition_field_description", max_chars=300)
            manufacturers = {}
            for value in sorted(set(details["manufacturer"]), key=lambda value: (value.casefold(), value)):
                if value:
                    manufacturers.setdefault(value.casefold(), value)
            item["manufacturer"] = st.selectbox(
                "Manufacturer (optional)", list(manufacturers.values()), index=None, accept_new_options=True,
                placeholder="Search for or enter a manufacturer",
                help="Type to search existing manufacturers. If there is no match, enter a new name and press Enter.",
                key="addition_field_manufacturer",
            ) or ""
            item["model"] = st.text_input("Model (optional)", key="addition_field_model", max_chars=300)
        quantity = st.number_input("Quantity to add", min_value=1, max_value=1000000, step=1, key="addition_field_quantity")
        person = st.text_input("Recorded by (name or initials)", key="addition_field_person", max_chars=100)
        project = st.text_input("Project or note (optional)", key="addition_field_project", max_chars=300)
        entered = st.text_input("Addition password", type="password", key="addition_field_password")
        submitted = st.form_submit_button("Save addition")
    if submitted:
        if not password_matches(entered, password):
            st.error("Incorrect password.")
            return
        try:
            with st.spinner("Saving addition in GitHub…"):
                result = client.add(request_id, item, quantity, location, sublocation, person, project, existing_code)
        except (ValueError, GitHubError) as error:
            st.error(str(error))
            return
        st.session_state["addition_result"] = result
        st.session_state.pop("addition_field_password", None)
        if on_saved:
            on_saved()
        st.rerun()


def withdrawal_form(client, details, locations, password, on_saved):
    st.subheader("Withdraw from inventory")
    st.caption("Withdrawals reduce stock immediately and record the person and timestamp in GitHub.")
    if show_completed("withdrawal"):
        return
    if client is None or not password:
        st.info("Withdrawals are not enabled yet.")
        return
    request_id = operation_id("withdrawal")
    products = {row["code"]: product_label(row) for _, row in details[~details["code"].duplicated(keep=False)].iterrows()}
    repeated = locations.duplicated(["code", "location", "sublocation"], keep=False)
    choices = {}
    for _, row in locations[~repeated].iterrows():
        if row["code"] not in products or not row["location"] or not row["sublocation"]:
            continue
        try:
            units = stock_units(row)
        except ValueError:
            continue
        if units > 0:
            key = (row["code"], row["location"], row["sublocation"])
            choices[key] = (f"{products[row['code']]} · box {row['location']} / bag {row['sublocation']} · units {units}", units)
    if not choices:
        st.info("No available stock has a verifiable product ID, box and bag.")
        return
    if st.button("Refresh staff list"):
        staff_directory.refresh_staff()
        st.session_state.pop("withdrawal_field_person", None)
        st.rerun()
    try:
        assistants = dict(staff_directory.load_staff())
    except staff_directory.StaffDirectoryError as error:
        st.error(str(error))
        return
    selected = st.selectbox("Product, box and bag", sorted(choices, key=lambda key: choices[key][0]), format_func=lambda key: choices[key][0])
    with st.form("withdrawal_form"):
        quantity = st.number_input("Quantity to withdraw", min_value=1, max_value=choices[selected][1], step=1, key="withdrawal_field_quantity")
        assistant_id = st.selectbox("Recorded by", list(assistants), index=None,
                                     placeholder="Search for your name",
                                     format_func=lambda code: f"{assistants[code]} ({code})",
                                     key="withdrawal_field_person")
        project = st.text_input("Project", key="withdrawal_field_project", max_chars=300,
                                help="Required so withdrawals can be tracked by project.")
        entered = st.text_input("Withdrawal password", type="password", key="withdrawal_field_password")
        submitted = st.form_submit_button("Record withdrawal")
    if submitted:
        if not password_matches(entered, password):
            st.error("Incorrect password.")
            return
        try:
            with st.spinner("Saving withdrawal in GitHub…"):
                project = required(project, "Project")
                if assistant_id not in assistants:
                    raise ValueError("Select a staff member from the directory.")
                remaining = client.withdraw(request_id, *selected, quantity, assistants[assistant_id], project,
                                             assistant_id=assistant_id)
        except (ValueError, GitHubError) as error:
            st.error(str(error))
            return
        st.session_state["withdrawal_result"] = remaining
        st.session_state.pop("withdrawal_field_password", None)
        on_saved()
        st.rerun()


def refresh_edit_staff():
    staff_directory.refresh_staff()
    st.session_state["edit_field_person"] = None


def edit_form(client, details, locations, password, on_saved=None):
    st.subheader("Edit product")
    st.caption("Correct an existing record. Its ID stays unchanged; changes are saved immediately using the addition password.")
    if show_completed("edit"):
        return
    if client is None or not password:
        st.info("Editing is not enabled yet.")
        return
    try:
        assistants = dict(staff_directory.load_staff())
    except staff_directory.StaffDirectoryError as error:
        st.error(str(error))
        st.button("Refresh staff list", key="edit_refresh_staff", on_click=refresh_edit_staff)
        return
    request_id = operation_id("edit")
    eligible = details[~details["code"].duplicated(keep=False)]
    if eligible.empty:
        st.info("No products with unique IDs are available to edit.")
        return
    st.caption("Find a product by its box and bag, or leave both filters on All to browse the full catalog.")
    box = st.selectbox("Find in box", [None, *sorted({value for value in locations["location"] if value}, key=str.casefold)],
                       format_func=lambda value: "All boxes" if value is None else value, key="edit_filter_box")
    matching = locations if box is None else locations[locations["location"].eq(box)]
    bags = {bag_key(value) for value in matching["sublocation"] if value}
    bags = sorted(bags, key=lambda value: (0, int(value)) if value.isascii() and value.isdigit() else (1, value.casefold()))
    bag = st.selectbox("Find in bag", [None, *bags],
                       format_func=lambda value: "All bags" if value is None else value, key="edit_filter_bag")
    if bag is not None:
        matching = matching[matching["sublocation"].map(bag_key).eq(bag)]
    filter_context = (box, bag)
    if st.session_state.get("edit_filter_context") != filter_context:
        for key in ("edit_product_choice", "edit_stock_choice", "edit_correct_stock"):
            st.session_state.pop(key, None)
        st.session_state["edit_filter_context"] = filter_context
    filtering = box is not None or bag is not None
    if filtering:
        eligible = eligible[eligible["code"].isin(matching["code"])]
        if eligible.empty:
            st.info("No uniquely identified products match this box and bag. Choose another filter or All boxes / All bags.")
            return
        labels = {row["code"]: product_label(row) for _, row in eligible.iterrows()}
        contents = matching[matching["code"].isin(labels)].copy()
        contents["product"] = contents["code"].map(labels)
        st.dataframe(contents[["product", "location", "sublocation", "units"]].rename(columns={
            "product": "Product", "location": "Box", "sublocation": "Bag", "units": "Units",
        }), hide_index=True, width="stretch")
        st.caption(f"{len(eligible)} products match. Select one below to correct its record or stock.")
    products = {row["code"]: product_label(row) for _, row in eligible.iterrows()}
    code = st.selectbox("Product to edit", sorted(products, key=products.get), format_func=products.get, key="edit_product_choice")
    correct_stock = st.checkbox("Correct box, bag or quantities", value=filtering, key="edit_correct_stock")
    selected_stock = None
    if correct_stock:
        rows = locations[locations["code"].eq(code)]
        if filtering:
            rows = rows[rows.index.isin(matching.index)]
        rows = rows[~rows.duplicated(["location", "sublocation"], keep=False)]
        if rows.empty:
            st.info("The box and bag are not uniquely defined. Use Add to register stock.")
            return
        choices = {(row["location"], row["sublocation"]): row.to_dict() for _, row in rows.iterrows()}
        stock_context = (code, box, bag)
        if st.session_state.get("edit_stock_context") != stock_context:
            st.session_state.pop("edit_stock_choice", None)
            st.session_state["edit_stock_context"] = stock_context
        slot = st.selectbox("Box and bag to correct", list(choices), format_func=lambda key: f"Box {key[0]} / bag {key[1]}", key="edit_stock_choice")
        selected_stock = choices[slot]
        try:
            stock_units(selected_stock)
        except ValueError:
            st.info("The original stock counts for this box and bag are invalid; review the CSV before editing in the app.")
            return
    context = (code, (selected_stock["location"], selected_stock["sublocation"]) if selected_stock else None)
    if st.session_state.get("edit_context") != context:
        for key in list(st.session_state):
            if key.startswith("edit_field_"):
                del st.session_state[key]
        st.session_state["edit_context"] = context
        st.session_state["edit_original_item"] = eligible[eligible["code"].eq(code)].iloc[0].to_dict()
        st.session_state["edit_original_stock"] = selected_stock
        # Explicit values tell the browser to replace existing keyed widgets.
        # Deleting state alone can leave the previous product visible in a form.
        for name in ("description", "type", "subtype", "manufacturer", "model", "value", "package", "info"):
            st.session_state[f"edit_field_{name}"] = st.session_state["edit_original_item"][name]
        if selected_stock:
            for name in ("location", "sublocation"):
                st.session_state[f"edit_field_{name}"] = selected_stock[name]
            st.session_state["edit_field_units"] = int(selected_stock["units"])
        st.session_state["edit_field_person"] = None
        for name in ("reason", "password"):
            st.session_state[f"edit_field_{name}"] = ""
    original_item = st.session_state["edit_original_item"]
    original_stock = st.session_state["edit_original_stock"]
    if st.session_state.get("edit_field_person") not in assistants:
        st.session_state["edit_field_person"] = None
    with st.form("edit_form"):
        updated_item = {}
        for name, label in (
            ("description", "Description"), ("type", "Type"), ("subtype", "Subtype"),
            ("manufacturer", "Manufacturer (optional)"), ("model", "Model (optional)"),
            ("value", "Value / specification (optional)"), ("package", "Package (optional)"),
            ("info", "Additional information (optional)"),
        ):
            updated_item[name] = st.text_input(label, key=f"edit_field_{name}")
        updated_stock = None
        if original_stock:
            updated_stock = {
                "location": st.text_input("Box", key="edit_field_location", max_chars=80),
                "sublocation": st.text_input("Bag", key="edit_field_sublocation", max_chars=80),
                "units": st.number_input("Units (available now)", min_value=0, step=1, key="edit_field_units"),
            }
        assistant_id = st.selectbox("Recorded by", list(assistants), index=None,
                                    placeholder="Search for your name",
                                    format_func=lambda code: f"{assistants[code]} ({code})",
                                    key="edit_field_person")
        reason = st.text_input("Reason for correction", key="edit_field_reason", max_chars=300)
        entered = st.text_input("Addition password", type="password", key="edit_field_password")
        submitted = st.form_submit_button("Save changes")
    st.button("Refresh staff list", key="edit_refresh_staff", on_click=refresh_edit_staff)
    if submitted:
        if not password_matches(entered, password):
            st.error("Incorrect password.")
            return
        try:
            with st.spinner("Saving changes in GitHub…"):
                if assistant_id not in assistants:
                    raise ValueError("Select a staff member from the directory.")
                result = client.edit(request_id, code, original_item, updated_item, assistants[assistant_id], reason,
                                     original_stock, updated_stock, assistant_id=assistant_id)
        except (ValueError, GitHubError) as error:
            st.error(str(error))
            return
        st.session_state["edit_result"] = result
        st.session_state.pop("edit_field_password", None)
        if on_saved:
            on_saved()
        st.rerun()
