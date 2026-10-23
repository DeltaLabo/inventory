"""Password-protected inventory forms; browsing never requires login."""

import hmac
import os
from uuid import uuid4

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from github_inventory import GitHubError, stock_counts


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
        st.success("Solicitud enviada. Los cambios se aplican cuando se apruebe y fusione la solicitud.")
        st.link_button("Ver solicitud en GitHub", result)
    else:
        st.success(f"Retiro registrado. Disponible después del retiro: {result}.")
    button_label = {"addition": "Registrar otro ingreso", "edit": "Editar otro producto", "withdrawal": "Registrar otro retiro"}[kind]
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
    pending = f"Ficha pendiente ({row['previous_code']})" if row.get("previous_code") else "Descripción pendiente"
    description = row["description"] or row["model"] or row["subtype"] or pending
    return f"{description} · {row['code']}"


def addition_classification(details):
    create_new = "Crear nuevo…"
    types = sorted({value for value in details["type"] if value}, key=str.casefold)
    choice = st.selectbox("Tipo", [*types, create_new], index=None,
                          placeholder="Elegí un tipo", key="addition_field_type_choice")
    item_type = st.text_input("Nuevo tipo", max_chars=300, key="addition_field_new_type").strip() if choice == create_new else (choice or "")
    # Reuse the spelling of a known type rather than introduce a case variant.
    if choice == create_new:
        item_type = next((value for value in types if value.casefold() == item_type.casefold()), item_type)
    if st.session_state.get("addition_type_context") != item_type:
        st.session_state.pop("addition_field_subtype_choice", None)
        st.session_state.pop("addition_field_new_subtype", None)
        st.session_state["addition_type_context"] = item_type
    subtypes = sorted({value for value in details.loc[details["type"].eq(item_type), "subtype"] if value}, key=str.casefold)
    subtype_choice = st.selectbox("Subtipo", [*subtypes, create_new], index=None,
                                  placeholder="Elegí un subtipo", disabled=not item_type,
                                  key="addition_field_subtype_choice")
    subtype = st.text_input("Nuevo subtipo", max_chars=300, key="addition_field_new_subtype").strip() if subtype_choice == create_new else (subtype_choice or "")
    if subtype_choice == create_new:
        subtype = next((value for value in subtypes if value.casefold() == subtype.casefold()), subtype)
    return {"type": item_type, "subtype": subtype}


def addition_form(client, details, locations, password):
    st.subheader("Ingresar al inventario")
    st.caption("Completá los datos; el identificador se asigna automáticamente. El ingreso queda pendiente de aprobación.")
    if show_completed("addition"):
        return
    if client is None or not password:
        st.info("El registro de ingresos todavía no está habilitado.")
        return
    request_id = operation_id("addition")
    mode = st.radio("¿Qué vas a ingresar?", ("Producto nuevo", "Más unidades de un producto existente"))
    existing_code = None
    classification = {}
    if mode != "Producto nuevo":
        eligible = details[~details["code"].duplicated(keep=False)]
        if eligible.empty:
            st.info("No hay productos con identificación única para seleccionar.")
            return
        products = {row["code"]: product_label(row) for _, row in eligible.iterrows()}
        existing_code = st.selectbox("Producto", sorted(products, key=products.get), format_func=products.get)
    else:
        # Outside the form so subtypes update immediately when the type changes.
        classification = addition_classification(details)
        st.caption("Usá «Crear nuevo…» si falta una opción. Se incorpora al catálogo cuando se apruebe el ingreso.")
    # These rerun independently so occupancy is visible before submission.
    boxes = sorted({value for value in locations["location"] if value}, key=str.casefold)
    location = st.selectbox(
        "Caja / ubicación", boxes, index=None, accept_new_options=True,
        placeholder="Buscá o escribí una caja",
        help="Elegí una caja existente o escribí una nueva y presioná Enter. Se incorpora cuando se apruebe el ingreso.",
        key="addition_field_location",
    ) or ""
    compartment = st.number_input(
        "Compartimento", min_value=0, value=None, step=1,
        placeholder="Número de compartimento", key="addition_field_sublocation",
    )
    sublocation = "" if compartment is None else str(compartment)
    if location and compartment is not None:
        numbers = locations["sublocation"].map(lambda value: int(value) if value.isascii() and value.isdigit() else None)
        occupied = locations[locations["location"].eq(location) & numbers.eq(compartment)]
        if not occupied.empty:
            # Keep the existing spelling, e.g. 01, for exact CSV references.
            own_stock = occupied[occupied["code"].eq(existing_code)]
            sublocation = (own_stock if not own_stock.empty else occupied).iloc[0]["sublocation"]
            st.warning(f"El compartimento {compartment} de la caja {location} ya tiene productos registrados. Podés continuar y guardar otro producto en la misma bolsa.")
    with st.form("addition_form"):
        item = dict(classification)
        if existing_code is None:
            item["description"] = st.text_input("Descripción", key="addition_field_description", max_chars=300)
            manufacturers = {}
            for value in sorted(set(details["manufacturer"]), key=lambda value: (value.casefold(), value)):
                if value:
                    manufacturers.setdefault(value.casefold(), value)
            item["manufacturer"] = st.selectbox(
                "Fabricante (opcional)", list(manufacturers.values()), index=None, accept_new_options=True,
                placeholder="Buscá o escribí un fabricante",
                help="Escribí para buscar entre los existentes. Si no aparece, escribí el nombre nuevo y presioná Enter.",
                key="addition_field_manufacturer",
            ) or ""
            item["model"] = st.text_input("Modelo (opcional)", key="addition_field_model", max_chars=300)
        quantity = st.number_input("Cantidad que ingresa", min_value=1, max_value=1000000, step=1, key="addition_field_quantity")
        person = st.text_input("Responsable (nombre o iniciales)", key="addition_field_person", max_chars=100)
        project = st.text_input("Proyecto o nota (opcional)", key="addition_field_project", max_chars=300)
        entered = st.text_input("Contraseña de ingresos", type="password", key="addition_field_password")
        submitted = st.form_submit_button("Enviar para aprobación")
    if submitted:
        if not password_matches(entered, password):
            st.error("Contraseña incorrecta.")
            return
        try:
            with st.spinner("Enviando solicitud a GitHub…"):
                url = client.propose_addition(request_id, item, quantity, location, sublocation, person, project, existing_code)
        except (ValueError, GitHubError) as error:
            st.error(str(error))
            return
        st.session_state["addition_result"] = url
        st.session_state.pop("addition_field_password", None)
        st.rerun()


def withdrawal_form(client, details, locations, password, on_saved):
    st.subheader("Retirar del inventario")
    st.caption("El retiro descuenta existencias inmediatamente y guarda el responsable y la fecha en GitHub.")
    if show_completed("withdrawal"):
        return
    if client is None or not password:
        st.info("El registro de retiros todavía no está habilitado.")
        return
    request_id = operation_id("withdrawal")
    products = {row["code"]: product_label(row) for _, row in details[~details["code"].duplicated(keep=False)].iterrows()}
    repeated = locations.duplicated(["code", "location", "sublocation"], keep=False)
    choices = {}
    for _, row in locations[~repeated].iterrows():
        if row["code"] not in products or not row["location"] or not row["sublocation"]:
            continue
        try:
            _, available = stock_counts(row)
        except ValueError:
            continue
        if available > 0:
            key = (row["code"], row["location"], row["sublocation"])
            choices[key] = (f"{products[row['code']]} · caja {row['location']} / {row['sublocation']} · disponible {available}", available)
    if not choices:
        st.info("No hay existencias disponibles con identificación y ubicación verificables.")
        return
    selected = st.selectbox("Producto y ubicación", sorted(choices, key=lambda key: choices[key][0]), format_func=lambda key: choices[key][0])
    with st.form("withdrawal_form"):
        quantity = st.number_input("Cantidad que retirás", min_value=1, max_value=choices[selected][1], step=1, key="withdrawal_field_quantity")
        person = st.text_input("Responsable (nombre o iniciales)", key="withdrawal_field_person", max_chars=100)
        project = st.text_input("Proyecto o nota (opcional)", key="withdrawal_field_project", max_chars=300)
        entered = st.text_input("Contraseña de retiros", type="password", key="withdrawal_field_password")
        submitted = st.form_submit_button("Registrar retiro")
    if submitted:
        if not password_matches(entered, password):
            st.error("Contraseña incorrecta.")
            return
        try:
            with st.spinner("Guardando retiro en GitHub…"):
                remaining = client.withdraw(request_id, *selected, quantity, person, project)
        except (ValueError, GitHubError) as error:
            st.error(str(error))
            return
        st.session_state["withdrawal_result"] = remaining
        st.session_state.pop("withdrawal_field_password", None)
        on_saved()
        st.rerun()


def edit_form(client, details, locations, password):
    st.subheader("Editar producto")
    st.caption("Corregí una ficha existente. Se conserva su identificador y los cambios quedan pendientes de aprobación.")
    if show_completed("edit"):
        return
    if client is None or not password:
        st.info("La edición todavía no está habilitada.")
        return
    request_id = operation_id("edit")
    eligible = details[~details["code"].duplicated(keep=False)]
    if eligible.empty:
        st.info("No hay productos con identificación única para editar.")
        return
    products = {row["code"]: product_label(row) for _, row in eligible.iterrows()}
    code = st.selectbox("Producto a editar", sorted(products, key=products.get), format_func=products.get)
    correct_stock = st.checkbox("Corregir ubicación o cantidades")
    selected_stock = None
    if correct_stock:
        rows = locations[locations["code"].eq(code)]
        rows = rows[~rows.duplicated(["location", "sublocation"], keep=False)]
        if rows.empty:
            st.info("No hay una ubicación única para corregir. Para agregar existencias, usá Ingresar.")
            return
        choices = {(row["location"], row["sublocation"]): row.to_dict() for _, row in rows.iterrows()}
        slot = st.selectbox("Ubicación a corregir", list(choices), format_func=lambda key: f"Caja {key[0]} / {key[1]}")
        selected_stock = choices[slot]
        try:
            stock_counts(selected_stock)
        except ValueError:
            st.info("Los saldos originales de esta ubicación son inválidos; revisalos en el CSV antes de editar desde la app.")
            return
    context = (code, (selected_stock["location"], selected_stock["sublocation"]) if selected_stock else None)
    if st.session_state.get("edit_context") != context:
        for key in list(st.session_state):
            if key.startswith("edit_field_"):
                del st.session_state[key]
        st.session_state["edit_context"] = context
        st.session_state["edit_original_item"] = eligible[eligible["code"].eq(code)].iloc[0].to_dict()
        st.session_state["edit_original_stock"] = selected_stock
    original_item = st.session_state["edit_original_item"]
    original_stock = st.session_state["edit_original_stock"]
    with st.form("edit_form"):
        updated_item = {}
        for name, label in (
            ("description", "Descripción"), ("type", "Tipo"), ("subtype", "Subtipo"),
            ("manufacturer", "Fabricante (opcional)"), ("model", "Modelo (opcional)"),
            ("value", "Valor / especificación (opcional)"), ("package", "Encapsulado (opcional)"),
            ("info", "Información adicional (opcional)"),
        ):
            updated_item[name] = st.text_input(label, value=original_item[name], key=f"edit_field_{name}")
        updated_stock = None
        if original_stock:
            updated_stock = {
                "location": st.text_input("Caja / ubicación", value=original_stock["location"], key="edit_field_location", max_chars=80),
                "sublocation": st.text_input("Compartimento", value=original_stock["sublocation"], key="edit_field_sublocation", max_chars=80),
                "units": st.number_input("Unidades registradas (saldo corregido)", min_value=0, value=int(original_stock["units"]), step=1, key="edit_field_units"),
                "available": st.number_input("Disponible (saldo corregido)", min_value=0, value=int(original_stock["available"]), step=1, key="edit_field_available"),
            }
        person = st.text_input("Responsable (nombre o iniciales)", key="edit_field_person", max_chars=100)
        reason = st.text_input("Motivo de la corrección", key="edit_field_reason", max_chars=300)
        entered = st.text_input("Contraseña de ingresos", type="password", key="edit_field_password")
        submitted = st.form_submit_button("Enviar corrección para aprobación")
    if submitted:
        if not password_matches(entered, password):
            st.error("Contraseña incorrecta.")
            return
        try:
            with st.spinner("Enviando corrección a GitHub…"):
                url = client.propose_edit(request_id, code, original_item, updated_item, person, reason, original_stock, updated_stock)
        except (ValueError, GitHubError) as error:
            st.error(str(error))
            return
        st.session_state["edit_result"] = url
        st.session_state.pop("edit_field_password", None)
        st.rerun()
