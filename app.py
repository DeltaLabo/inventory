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
search_term = st.text_input("Buscar por descripción")

# Filtrar por término de búsqueda si se ingresó algo
if search_term:
    list = list[list["description"].str.contains(search_term, case=False, na=False)]

# Mostrar resultados
st.markdown("### Detalles:")
st.dataframe(list, hide_index=True)
