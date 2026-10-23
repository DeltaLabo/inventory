from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from inventory import build_inventory, filter_inventory, load_data, validate_data
from forms import addition_form, settings, withdrawal_form
from github_inventory import GitHubError, GitHubInventory


ROOT = Path(__file__).resolve().parent
IMAGE_BASE = "https://raw.githubusercontent.com/DeltaLabo/inventory_pictures/main/inventory_images_ready"


@st.cache_data(ttl=3600, max_entries=512, show_spinner=False)
def image_url(code):
    for extension in ("png", "jpg"):
        url = f"{IMAGE_BASE}/{code}.{extension}"
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
    issues = validate_data(details, locations)
    if issues:
        with st.expander(f"Datos por revisar ({len(issues)})"):
            for issue in issues:
                st.write(f"• {issue}")

    inventory = build_inventory(details, locations)
    search = st.text_input("Buscar por código, descripción, fabricante, modelo o ubicación")
    types = sorted(inventory["type"].unique(), key=str.casefold)
    selected_type = st.selectbox("Tipo", ["Todos", *types])
    type_rows = inventory if selected_type == "Todos" else inventory[inventory["type"] == selected_type]
    subtypes = sorted(type_rows["subtype"].unique(), key=str.casefold)
    selected_subtype = st.selectbox("Subtipo", ["Todos", *subtypes])
    results = filter_inventory(inventory, search, selected_type, selected_subtype)
    st.caption(f"{len(results)} registros")
    st.download_button(
        "Descargar resultados CSV", results.to_csv(index=False).encode("utf-8-sig"),
        file_name="inventario.csv", mime="text/csv",
    )
    show_images = st.checkbox("Mostrar imágenes", value=False)
    if results.empty:
        st.info("No se encontraron coincidencias.")
        return

    labels = {
        "code": "Código", "description": "Descripción", "manufacturer": "Fabricante",
        "model": "Modelo", "location": "Ubicación", "sublocation": "Compartimento",
        "units": "Unidades registradas", "available": "Disponible", "status": "Observaciones",
    }
    st.dataframe(results[list(labels)].rename(columns=labels), hide_index=True, width="stretch")
    if show_images:
        codes = results["code"].drop_duplicates().tolist()
        pages = max(1, (len(codes) + 11) // 12)
        page = st.number_input("Página de imágenes", min_value=1, max_value=pages, step=1)
        for code in codes[(page - 1) * 12:page * 12]:
            url = image_url(code)
            if url:
                st.image(url, caption=code, width=150)
            else:
                st.caption(f"{code}: sin imagen")


def main():
    st.set_page_config(page_title="Inventario DeltaLAB", layout="wide")
    st.title("Delta LAB")
    st.caption("Escuela de Ingeniería Electromecánica — Tecnológico de Costa Rica")
    config = settings()
    client = None
    try:
        if config["token"]:
            try:
                details, locations = live_data(config["token"], config["repository"], config["branch"])
                client = GitHubInventory(config["token"], config["repository"], config["branch"])
            except (GitHubError, ValueError) as error:
                st.warning("No se pudo actualizar desde GitHub. Se muestra la copia local y los cambios están temporalmente deshabilitados.")
                details, locations = load_data(ROOT)
        else:
            details, locations = load_data(ROOT)
    except (OSError, ValueError, pd.errors.ParserError) as error:
        st.error(f"No se pudo cargar el inventario: {error}")
        st.stop()
    action = st.radio("¿Qué querés hacer?", ("Consultar", "Ingresar", "Retirar"), horizontal=True)
    if action == "Ingresar":
        addition_form(client, details, locations, config["add_password"])
    elif action == "Retirar":
        withdrawal_form(client, details, locations, config["withdraw_password"], live_data.clear)
    else:
        st.subheader("Inventario")
        if client and st.button("Actualizar existencias"):
            live_data.clear()
            st.rerun()
        browse(details, locations)


if __name__ == "__main__":
    main()
