"""Password-protected storage creation and audited removal."""

import streamlit as st

from scripts.forms import operation_id, password_matches, product_label
from scripts.github_inventory import GitHubError
from scripts.inventory import bag_key
import scripts.staff as staff_directory
from scripts.storage import removal_preview


@st.cache_data(ttl=15, max_entries=4, show_spinner=False)
def live_management(token, repository, branch):
    from scripts.github_inventory import GitHubInventory
    return GitHubInventory(token, repository, branch).management_snapshot()


def management(client, config, on_saved):
    st.subheader("Manage devices and storage")
    st.caption("Create boxes and bags, delete empty storage, or remove devices using the addition password. Previous movements and audit records are kept.")
    if client is None or not config["add_password"]:
        st.info("Management is not enabled yet.")
        return
    if "management_result" in st.session_state:
        st.success("Management change saved.")
        if st.button("Make another change"):
            for key in list(st.session_state):
                if key.startswith("management_"):
                    del st.session_state[key]
            st.rerun()
        return
    if st.button("Refresh management data"):
        live_management.clear()
        st.session_state.pop("management_preview", None)
        st.rerun()
    try:
        snapshot = live_management(config["token"], config["repository"], config["branch"])
        people = dict(staff_directory.load_staff())
    except (GitHubError, ValueError) as error:
        st.error(str(error))
        return
    choices = {"Add box": "add_box", "Add bag": "add_bag", "Delete device": "delete_product",
               "Delete device from one bag": "delete_stock", "Delete box": "delete_box", "Delete bag": "delete_bag"}
    action = choices[st.selectbox("Management action", list(choices), key="management_action")]
    boxes = sorted({row["location"] for row in snapshot["storage"]}, key=str.casefold)
    st.caption(f"{len(boxes)} boxes registered, including empty boxes.")
    with st.expander("Registered boxes and bags"):
        st.dataframe(snapshot["storage"], hide_index=True, width="stretch")
    target = {}
    if action == "add_box":
        target["location"] = st.text_input("New box", max_chars=80, key="management_new_box").strip()
    elif action in ("add_bag", "delete_box", "delete_bag"):
        if not boxes:
            st.info("Create a box first.")
            return
        target["location"] = st.selectbox("Box", boxes, key="management_box")
        if action == "add_bag":
            target["sublocation"] = str(st.number_input("New bag", min_value=0, step=1, key="management_new_bag"))
        elif action == "delete_bag":
            bags = sorted({bag_key(row["sublocation"]) for row in snapshot["storage"]
                           if row["location"] == target["location"] and row["sublocation"]},
                          key=lambda value: (0, int(value)) if value.isascii() and value.isdigit() else (1, value.casefold()))
            if not bags:
                st.info("This box has no bags.")
                return
            target["sublocation"] = st.selectbox("Bag", bags, key="management_bag")
    else:
        labels = {row["code"]: product_label(row) for row in snapshot["details"]}
        for row in snapshot["locations"]:
            labels.setdefault(row["code"], row["code"])
        if not labels:
            st.info("No devices to remove.")
            return
        target["code"] = st.selectbox("Device", sorted(labels, key=labels.get), format_func=labels.get, key="management_device")
        if action == "delete_stock":
            slots = sorted({(row["location"], row["sublocation"]) for row in snapshot["locations"] if row["code"] == target["code"]})
            if not slots:
                st.info("This device has no storage entries.")
                return
            target["location"], target["sublocation"] = st.selectbox("Box and bag", slots,
                format_func=lambda slot: f"Box {slot[0]} / bag {slot[1]}", key="management_slot")
    context = (action, tuple(sorted(target.items())))
    if st.session_state.get("management_context") != context:
        st.session_state["management_context"] = context
        st.session_state.pop("management_preview", None)
        st.session_state.pop("management_id", None)
        for name, value in (("confirm", False), ("password", ""), ("reason", ""), ("person", None)):
            st.session_state[f"management_field_{name}"] = value
    deleting = action.startswith("delete_")
    expected = None
    if deleting:
        if st.button("Preview removal"):
            try:
                # Freeze the reviewed rows across reruns and automatic cache expiry.
                st.session_state["management_preview"] = removal_preview(snapshot, action, target)
                st.session_state["management_field_confirm"] = False
            except ValueError as error:
                st.error(str(error))
        expected = st.session_state.get("management_preview")
        if expected is None:
            return
        if action in ("delete_box", "delete_bag") and expected["locations"]:
            st.info("Only empty boxes and bags can be deleted. Move their devices in Edit or remove their device storage entries first, then refresh the preview.")
            st.dataframe(expected["locations"], hide_index=True, width="stretch")
            return
        st.warning("This removes the records shown below and their current stock quantities.")
        if action in ("delete_box", "delete_bag", "delete_stock"):
            st.caption("Device records and historical movements remain in the catalog and history. No stock is moved elsewhere.")
        else:
            st.caption("The device will be removed from the catalog and all its boxes and bags.")
        for name, title in (("details", "Device records"), ("locations", "Stock entries"), ("storage", "Boxes and bags")):
            if expected[name]:
                st.write(title)
                st.dataframe(expected[name], hide_index=True, width="stretch")
    request_id = operation_id("management")
    with st.form("management_form"):
        person_id = st.selectbox("Recorded by", list(people), index=None, format_func=lambda code: f"{people[code]} ({code})",
                                key="management_field_person")
        reason = st.text_input("Reason", max_chars=300, key="management_field_reason")
        confirmed = st.checkbox("I reviewed the preview and confirm this removal", key="management_field_confirm") if deleting else True
        password = st.text_input("Addition password", type="password", key="management_field_password")
        submitted = st.form_submit_button("Remove selected records" if deleting else "Create storage")
    if submitted:
        if not password_matches(password, config["add_password"]):
            st.error("Incorrect password.")
            return
        if not confirmed:
            st.error("Review the preview and confirm the removal.")
            return
        try:
            if person_id not in people:
                raise ValueError("Select a staff member from the directory.")
            result = client.manage(request_id, action, target, expected, people[person_id], reason, assistant_id=person_id)
        except (GitHubError, ValueError) as error:
            st.error(str(error))
            return
        st.session_state["management_result"] = result
        st.session_state.pop("management_field_password", None)
        live_management.clear()
        on_saved()
        st.rerun()
