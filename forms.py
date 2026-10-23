"""The two password-protected inventory forms; browsing never requires login."""

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
    if kind == "addition":
        st.success("Solicitud enviada. Las unidades se incorporan cuando se apruebe y fusione la solicitud.")
        st.link_button("Ver solicitud en GitHub", result)
    else:
        st.success(f"Retiro registrado. Disponible después del retiro: {result}.")
    if st.button("Registrar otro ingreso" if kind == "addition" else "Registrar otro retiro"):
        st.session_state.pop(f"{kind}_result", None)
        st.session_state.pop(f"{kind}_id", None)
        # Clear old form fields, especially the password, before another action.
        for key in list(st.session_state):
            if key.startswith(f"{kind}_field_"):
                del st.session_state[key]
        st.rerun()
    return True


def product_label(row):
    description = row["description"] or row["model"] or row["subtype"] or "Descripción pendiente"
    return f"{description} · {row['code']}"


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
    if mode != "Producto nuevo":
        eligible = details[~details["code"].duplicated(keep=False)]
        if eligible.empty:
            st.info("No hay productos con identificación única para seleccionar.")
            return
        products = {row["code"]: product_label(row) for _, row in eligible.iterrows()}
        existing_code = st.selectbox("Producto", sorted(products, key=products.get), format_func=products.get)
    with st.form("addition_form"):
        item = {}
        if existing_code is None:
            for name, label in (
                ("description", "Descripción"), ("type", "Tipo"), ("subtype", "Subtipo"),
                ("manufacturer", "Fabricante (opcional)"), ("model", "Modelo (opcional)"),
            ):
                item[name] = st.text_input(label, key=f"addition_field_{name}", max_chars=300)
        quantity = st.number_input("Cantidad que ingresa", min_value=1, max_value=1000000, step=1, key="addition_field_quantity")
        location = st.text_input("Caja / ubicación", key="addition_field_location", max_chars=80)
        sublocation = st.text_input("Compartimento", key="addition_field_sublocation", max_chars=80)
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
