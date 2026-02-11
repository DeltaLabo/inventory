import streamlit as st
import pandas as pd
import requests

st.set_page_config(page_title='Inventario DeltaLAB')

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
    st.markdown("### Detalles:")
    st.dataframe(list, hide_index=True)

    # Mostrar imágenes debajo de la tabla
    st.markdown("### Imágenes asociadas:")
    for _, row in list.iterrows():
        st.write(f"**{row['code']}** - {row['description']}")

        found = False
        for ext in ["jpg", "png"]:
            image_url = f"https://raw.githubusercontent.com/DeltaLabo/inventary_pictures/main/inventory_images/{row['code']}.{ext}"
            response = requests.get(image_url)
            if response.status_code == 200:
                st.image(image_url, width=150)
                found = True
                break

        if not found:
            st.warning(f"No image found for code {row['code']}")

        st.write("---")
