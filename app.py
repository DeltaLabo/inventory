import streamlit as st
import pandas as pd

# Set the title and favicon that appear in the Browser's tab bar.
st.set_page_config(
    page_title='Detalles de cursos - CLIE - EIEM - TEC',
)


'''
# Delta LAB
#### Inventario
Escuela de Ingeniería Electromecánica - Tecnológico de Costa Rica
'''

detail = pd.read_csv("details.csv").fillna("")
types = detail["type"].unique()
locati = pd.read_csv("locations.csv").fillna("")

type = st.selectbox(
    'Type',
    types
)

subtypes = detail[detail["type"]==type]["subtype"].unique()

subtype = st.selectbox(
    'Subtype',
    subtypes
)

list = detail[(detail["type"]==type) & (detail["subtype"]==subtype)]

list = list.merge(locati, on='code', how='left')

list.drop(columns=["info","type","subtype"],inplace=True)

st.markdown("### Detalles:")

st.dataframe(list,hide_index=True)  



# codArea = areas[areas["nombre"]==nomArea]["codArea"].item()
# cursos = cursosraw[(cursosraw["area"]==codArea)\
#                    & (cursosraw["semestre"]<=10)\
#                    & (cursosraw["nombre"]!="Electiva I")\
#                    & (cursosraw["nombre"]!="Electiva II") ].copy()
# #saberes = saberes[saberes["codArea"]==codArea].copy()  esto causaba errores con metrología

# nomCurso = st.selectbox(
#     "Curso",
#     cursos[cursos["area"]==codArea]["nombre"])

# st.markdown("### Detalles:")

# codCurso = cursos[cursos["nombre"]==nomCurso]["codigo"].item()

# idCurso = cursos[cursos["nombre"]==nomCurso]["id"].item()

# semes = cursos[cursos["nombre"]==nomCurso]["semestre"].item()

# cred = cursos[cursos["nombre"]==nomCurso]["creditos"].item()

# hteor = cursos[cursos["nombre"]==nomCurso]["horasTeoria"].item()

# hprac = cursos[cursos["nombre"]==nomCurso]["horasPractica"].item()

# st.markdown(
# f'''
# * ID: {idCurso}
# * Código: {codCurso}
# * Semestre: {semes}
# * Creditos: {cred}
# * Horas clase: {hteor + hprac}<br>
# &nbsp;&nbsp;&nbsp;&nbsp; teoría: {hteor}<br>
# &nbsp;&nbsp;&nbsp;&nbsp; práctica: {hprac}
# * Horas extraclase: {(cred * 3)-(hteor + hprac)}
# ''', unsafe_allow_html=True)

# st.markdown("*Requisitos:*")

# cursos["requisitos"] = cursos["requisitos"].str.split(';', expand=False) #convertir los valores separados por ; en una lista por fila

# req = cursos[cursos["nombre"]==nomCurso]["requisitos"].item()

# if req != [""]:
#     for reqi in req:
#         codReq = cursosraw[cursosraw["id"]==reqi]["codigo"].item()
#         curReq = cursosraw[cursosraw["id"]==reqi]["nombre"].item()
#         st.markdown(f"* {codReq} - {curReq}") 
# else:
#     st.markdown("* No")

# st.markdown("*Correquisitos:*")

# cursos["correquisitos"] = cursos["correquisitos"].str.split(';', expand=False) #convertir los valores separados por ; en una lista por fila

# cor = cursos[cursos["nombre"]==nomCurso]["correquisitos"].item()

# if cor != [""]:
#     for cori in cor:
#         codCor = cursosraw[cursosraw["id"]==cori]["codigo"].item()
#         curCor = cursosraw[cursosraw["id"]==cori]["nombre"].item()
#         st.markdown(f"* {codCor} - {curCor}") 
# else:
#     st.markdown("* No")

# st.markdown("*Es requisito:*")

# cursos["esrequisito"] = cursos["esrequisito"].str.split(';', expand=False) #convertir los valores separados por ; en una lista por fila

# esreq = cursos[cursos["nombre"]==nomCurso]["esrequisito"].item()

# if esreq != [""]:
#     for esreqi in esreq:
#         codesReq = cursosraw[cursosraw["id"]==esreqi]["codigo"].item()
#         curesReq = cursosraw[cursosraw["id"]==esreqi]["nombre"].item()
#         st.markdown(f"* {codesReq} - {curesReq}") 
# else:
#     st.markdown("* No")


# cursos_rasgos["codSaber"] = cursos_rasgos["codSaber"].str.split(';', expand=False) #convertir los valores separados por ; en una lista por fila

# codSaber = cursos_rasgos[cursos_rasgos["id"]==idCurso]["codSaber"].item()

# rasgos["codSaber"] = rasgos["codSaber"].str.split(';', expand=False) #convertir los valores separados por ; en una lista por fila

# rasgos = rasgos.explode("codSaber") #expadir la lista

# codRasgos = rasgos[rasgos["codSaber"].isin(codSaber)]["rasgo"].unique()

# cursos_rasgos = cursos_rasgos.explode("codSaber") #expadir la lista despues de tener codSaber

# st.markdown("### Saberes:")

# print(saberes)

# for codSaberi in codSaber:
#     print(saberes[saberes["codSaber"]==codSaberi]["nombre"])
#     saber = saberes[saberes["codSaber"]==codSaberi]["nombre"].item()
#     st.markdown(f"* **{saber}**")
#     compar = cursos_rasgos[(cursos_rasgos["codSaber"]==codSaberi)\
#                         & (cursos_rasgos["id"]!=idCurso)\
#                         ]['id'].tolist()
#     if compar != []:
#             st.markdown("*Compartido con:*")
#     for compari in compar:        
#         if compari in cursos["id"].tolist():
#             codCompar = cursos[cursos["id"]==compari]["codigo"].item()
#             nomCompar = cursos[cursos["id"]==compari]["nombre"].item()
#             st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{codCompar} - {nomCompar}")
    
# st.markdown("### Rasgos:")

# for rasgo in codRasgos:
#     st.markdown(f"* {rasgo}")


# st.markdown("### Ruta de requisitos:")

# cursosraw["requisitos"] = cursosraw["requisitos"].str.split(';', expand=False) #convertir los valores separados por ; en una lista por fila
# cursosraw["correquisitos"] = cursosraw["correquisitos"].str.split(';', expand=False) #convertir los valores separados por ; en una lista por fila

# rutaReq = set()

# def recurReq(req,cor):
#     if (cor != [""]) & (req != [""]):
#         req.extend(cor)
#     elif req == [""]:
#         req = cor
#     if req != [""]:
#         for reqi in req:
#             seme = cursosraw[cursosraw["id"]==reqi]["semestre"].item()
#             fila = cursosraw[cursosraw["id"]==reqi]["fila"].item()
#             order = int(str(seme) + str(fila))
#             codReq = cursosraw[cursosraw["id"]==reqi]["codigo"].item()
#             curReq = cursosraw[cursosraw["id"]==reqi]["nombre"].item()
#             rutaReq.add((order, codReq, curReq))
#             reqreq = cursosraw[cursosraw["id"]==reqi]["requisitos"].item()
#             corcor = cursosraw[cursosraw["id"]==reqi]["correquisitos"].item()
#             recurReq(reqreq,corcor)

# recurReq(req,cor)

# # Convert the set to a list and sort it by "nombre"
# rutaReq = sorted(list(rutaReq), key=lambda x: x[0])

# for req in rutaReq:
#     st.markdown(f"* {req[1]} - {req[2]}")

# st.markdown("### Ruta de cursos para los que es requisito:")

# cursosraw["esrequisito"] = cursosraw["esrequisito"].str.split(';', expand=False) #convertir los valores separados por ; en una lista por fila

# rutaEsReq = set()

# def recurEsReq(esreq):
#     if esreq != [""]:
#         for esreqi in esreq:
#             seme = cursosraw[cursosraw["id"]==esreqi]["semestre"].item()
#             fila = cursosraw[cursosraw["id"]==esreqi]["fila"].item()
#             order = int(str(seme) + str(fila))
#             codesReq = cursosraw[cursosraw["id"]==esreqi]["codigo"].item()
#             curesReq = cursosraw[cursosraw["id"]==esreqi]["nombre"].item()
#             rutaEsReq.add((order, codesReq, curesReq))
#             esreqesreq = cursosraw[cursosraw["id"]==esreqi]["esrequisito"].item()
#             recurEsReq(esreqesreq)

# recurEsReq(esreq)

# # Convert the set to a list and sort it by "nombre"
# rutaEsReq = sorted(list(rutaEsReq), key=lambda x: x[0])

# for esreq in rutaEsReq:
#     st.markdown(f"* {esreq[1]} - {esreq[2]}")