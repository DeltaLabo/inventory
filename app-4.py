import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import csv
import os

st.set_page_config(page_title='Inventario DeltaLAB')

VALID_CODE = "DELTA2026"

try:
    '''
    # Delta LAB
    #### Inventario
    Escuela de Ingeniería Electromecánica - Tecnológico de Costa Rica
    '''

    # Cargar datos
    detail = pd.read_csv("details.csv").fillna("")
    types = detail["type"].unique()
    locati = pd.read_csv("locations.csv").fillna("")

    # Selección de tipo y subtipo
    type = st.selectbox('Type', types)
    subtypes = detail[detail["type"] == type]["subtype"].unique()
    subtype = st.selectbox('Subtype', subtypes)

    # Filtrar por tipo y subtipo
    list = detail[(detail["type"] == type) & (detail["subtype"] == subtype)]
    list = list.merge(locati, on='code', how='left')
    list.drop(columns=["info", "type", "subtype"], inplace=True)

    # 🔍 Campo de búsqueda por descripción
    search_term = st.text_input("Search by description")
    if search_term:
        list = list[list.astype(str).apply(lambda row: " ".join(row).lower(), axis=1).str.contains(search_term.lower())]

    if list.empty:
        st.warning("No se encontraron coincidencias")
    else:
        st.markdown("### Inventario:")

        for _, row in list.iterrows():
            with st.container():
                cols = st.columns([1, 3])
                with cols[0]:
                    found = False
                    for ext in ["jpg", "png"]:
                        image_url = f"https://raw.githubusercontent.com/DeltaLabo/inventary_pictures/main/inventory_images/{row['code']}.{ext}"
                        response = requests.get(image_url)
                        if response.status_code == 200:
                            st.image(image_url, width=150)
                            found = True
                            break
                    if not found:
                        st.warning("No image")

                with cols[1]:
                    st.markdown(f"**Código:** {row['code']}")
                    st.markdown(f"**Descripción:** {row['description']}")
                    if "location" in row:
                        st.markdown(f"**Ubicación:** {row['location']}")
                    if "sublocation" in row:
                        st.markdown(f"**Sublocalización:** {row['sublocation']}")

                    # Mostrar cantidad disponible actual
                    if "available" in row:
                        st.markdown(f"**Disponible:** {row['available']}")

                    # Nueva sección: registrar uso con responsable y código de verificación
                    qty = st.number_input(f"Cantidad a usar ({row['code']})", min_value=0, step=1, key=f"qty_{row['code']}")
                    user = st.text_input(f"Responsable ({row['code']})", key=f"user_{row['code']}")
                    code = st.text_input(f"Código de verificación ({row['code']})", type="password", key=f"code_{row['code']}")

                    if st.button(f"Registrar uso de {row['code']}", key=f"use_{row['code']}"):
                        if qty > 0 and user.strip() and code.strip():
                            if code == VALID_CODE:
                                log_file = "usage_log.csv"
                                if not os.path.exists(log_file):
                                    with open(log_file, "w", newline="", encoding="utf-8") as f:
                                        writer = csv.writer(f)
                                        writer.writerow(["timestamp", "code", "description", "quantity", "user"])
                                with open(log_file, "a", newline="", encoding="utf-8") as f:
                                    writer = csv.writer(f)
                                    writer.writerow([datetime.now().isoformat(), row['code'], row['description'], qty, user])

                                # Actualizar locations.csv
                                loc_df = pd.read_csv("locations.csv").fillna("")
                                if "available" in loc_df.columns:
                                    if row['code'] in loc_df['code'].values:
                                        loc_df.loc[loc_df['code'] == row['code'], 'available'] = (
                                            loc_df.loc[loc_df['code'] == row['code'], 'available'].astype(int) - qty
                                        )
                                        loc_df.to_csv("locations.csv", index=False)

                                        # Mostrar cantidad actualizada
                                        new_available = int(loc_df.loc[loc_df['code'] == row['code'], 'available'].values[0])
                                        st.success(f"Se registró el uso de {qty} unidades de {row['code']} por {user}. Nuevo disponible: {new_available}")
                                    else:
                                        st.error("El código no existe en locations.csv")
                                else:
                                    st.error("El archivo locations.csv no tiene columna 'available'")
                            else:
                                st.error("Código de verificación incorrecto.")
                        else:
                            st.error("Debe indicar cantidad, responsable y código de verificación antes de registrar.")
            st.markdown("---")

except Exception as e:
    st.error(f"Ocurrió un error: {e}")