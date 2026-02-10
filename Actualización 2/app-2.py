import streamlit as st
import pandas as pd

# Configuración de la página
st.set_page_config(page_title='Inventario DeltaLAB')

# Encabezado
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

# Unir con ubicaciones
list = list.merge(locati, on='code', how='left')

# Eliminar columnas innecesarias
list.drop(columns=["info", "type", "subtype"], inplace=True)

# 🔍 Campo de búsqueda por descripción
search_term = st.text_input("Search by description")

if search_term:
    # Filtrar por cualquier coincidencia en las columnas
    list = list[list.astype(str).apply(lambda row: " ".join(row).lower(), axis=1).str.contains(search_term.lower())]

if list.empty:
    st.warning("No se encontraron coincidencias")
else:
    st.markdown("### Detalles:")

    # Mostrar cada registro como bloque con imagen
    for _, row in list.iterrows():
        st.write(f"**{row['code']}** - {row['description']}")
        if row["image_url"]:
            st.image(row["image_url"], width=150)
        st.write("---")