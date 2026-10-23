# Inventario Delta LAB

Inventario con consulta pública, ingresos pendientes de aprobación y retiros
inmediatos. La interfaz está en español y GitHub guarda los datos.

Aplicación publicada: https://deltalab-inventory.streamlit.app/

## Ejecutar

Desde este repositorio:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

`app.py` es la única aplicación. En Streamlit Cloud, seleccionar `app.py` como
archivo principal. Los CSV se resuelven desde la ubicación del código.

## Uso

- **Consultar:** búsqueda y filtros sin contraseña. También permite descargar los
  resultados y consultar imágenes opcionales.
- **Ingresar:** requiere la contraseña de ingresos. Elegir un producto nuevo o
  más unidades de un producto existente; indicar cantidad, caja, compartimento y
  responsable. Un producto nuevo recibe un ID automático permanente. La app crea
  una pull request; las existencias se incorporan al aprobarla y **fusionarla**.
- **Retirar:** requiere la contraseña compartida de retiros. Elegir el producto y
  su ubicación, indicar cantidad y responsable. El saldo y el movimiento se guardan
  inmediatamente en un único commit de GitHub, sin esperar aprobación.

Los campos «Proyecto o nota» son opcionales. Los nombres o iniciales y las notas
quedan en el repositorio público: usar únicamente la información necesaria.

No se permiten retiros de productos con códigos ambiguos, ubicaciones duplicadas,
saldos inválidos o cantidades insuficientes. Primero hay que conciliar esos datos.
El resto del inventario sigue disponible.

## Habilitar los formularios en Streamlit

Crear un token de GitHub de acceso detallado limitado a `DeltaLabo/inventory`, con
permisos **Contents: Read and write** y **Pull requests: Read and write**. La cuenta
propietaria del token debe tener acceso al repositorio y permiso para crear ramas,
pull requests y actualizar la rama principal. Respetar las reglas de la organización;
si `main` exige pull requests para todo cambio, los retiros directos no funcionarán
con esas reglas y habrá que ajustar el despliegue o el flujo.

En los ajustes de la app de Streamlit, sección **Secrets**, agregar:

```toml
GITHUB_TOKEN = "TOKEN_PRIVADO_DE_GITHUB"
INVENTORY_REPOSITORY = "DeltaLabo/inventory"
INVENTORY_BRANCH = "main"
INVENTORY_ADD_PASSWORD = "CONTRASEÑA_PARA_INGRESOS"
INVENTORY_WITHDRAW_PASSWORD = "CONTRASEÑA_COMPARTIDA_PARA_RETIROS"
```

Elegir contraseñas diferentes. La contraseña de retiros puede compartirse con las
personas que usan el laboratorio. El token y la contraseña de ingresos se entregan
solo a quienes corresponda; nunca poner el token en el formulario.

Para uso local, copiar `.streamlit/secrets.example.toml` a
`.streamlit/secrets.toml` y completar los valores. Este último está excluido de Git.
También se admiten variables de entorno con los mismos nombres, con prioridad.
No usar literalmente los ejemplos ni reutilizar la contraseña publicada antigua.

Sin token, la consulta usa los CSV locales y los formularios están deshabilitados.
Con token, consulta la rama configurada de GitHub y mantiene una caché de 15 segundos.
«Actualizar existencias» actualiza la consulta; un retiro exitoso invalida la caché.
Si GitHub no responde, la consulta usa la copia local con aviso y deshabilita cambios.

Si falla la conexión al guardar, reintentar el mismo formulario con los mismos datos:
la solicitud conserva un identificador y recupera un cambio ya guardado sin duplicarlo.
Tras un éxito, usar «Registrar otro ingreso/retiro» para una operación diferente.
Recargar el navegador o abrir otra sesión inicia solicitudes nuevas: comprobar los
registros antes de repetir una operación cuyo resultado no se conoce.

## Aprobar ingresos

La app entrega un enlace a la pull request. Revisar descripción, clasificación,
responsable, ubicación y cantidades; aprobar y fusionar para aceptar el ingreso.
Si el producto ya existe, solicitar más unidades del existente para reutilizar su ID.
Los IDs nuevos son aleatorios (`I` + UUID) y no dependen del nombre del producto.
Los códigos anteriores se conservan sin migrarlos.

Las propuestas guardan el catálogo/stock calculado en su rama y un comprobante en
`requests/<id>.json`. Nunca cambian `main` antes de fusionarse. Si hubo otros cambios
en la misma fila de stock, GitHub puede señalar un conflicto: revisar los saldos
actuales y sumar el ingreso sobre ellos, sin reemplazarlos por una versión vieja.
Una solicitud cerrada sin fusionar no agrega existencias.

## Actualizar datos

- `details.csv`: fichas de productos. Conservar los códigos como texto, incluidos
  sus ceros y puntos. Cada producto debe tener un código único.
- `locations.csv`: una fila por código, ubicación y compartimento. `units` es la
  cantidad registrada y `available` la disponible; ambas son enteros no negativos,
  con disponible menor o igual a la cantidad registrada.
- `to_buy.csv`: lista de compras independiente.
- `smd.csv` y `not_found.csv`: listas auxiliares pendientes de conciliación;
  no se importan automáticamente ni cambian existencias.
- `usage_log.csv`: registro histórico conservado como referencia. No se usa para
  recalcular existencias porque no explica todos los saldos actuales.
- `movements.csv`: se crea en GitHub con el primer retiro. Incluye identificador,
  fecha UTC, producto, caja, compartimento, cantidad, responsable, proyecto y saldo
  posterior. Se guarda junto con el cambio de stock en el mismo commit.
- `requests/`: comprobantes de ingresos propuestos, incorporados al fusionar cada PR.

Editar los CSV y ejecutar la validación:

```powershell
python inventory.py
```

La validación muestra problemas y termina con código 1 si hay datos pendientes.
La aplicación también los muestra en «Datos por revisar». Los productos sin
ubicación muestran cantidades vacías (desconocidas), no cero. Las ubicaciones sin
ficha siguen visibles en «Sin clasificar». Los códigos duplicados se presentan
como ambiguos, conservando sus descripciones sin multiplicar las filas de stock.
Confirmar físicamente las diferencias antes de renombrar códigos o asignar saldos.

La app no escribe CSVs en el disco temporal de Streamlit. Los cambios se guardan
por la API de GitHub. Los retiros revisan el saldo más reciente, afectan una sola
ubicación y reintentan ante cambios simultáneos, sin forzar el historial de Git.
Los ingresos usan una rama independiente por solicitud y requieren tu revisión.

## Imágenes

Se buscan por código en `DeltaLabo/inventory_pictures`, carpeta
`inventory_images_ready`, extensiones PNG y JPG. Son opcionales y se muestran
solo al activar «Mostrar imágenes», hasta 12 productos por página. Las consultas
tienen un tiempo máximo y se guardan en caché durante una hora.

## Comprobaciones

```powershell
python -m unittest discover -s tests -v
```

Las versiones antiguas de la aplicación están en el historial de Git.

Las pruebas usan un GitHub simulado; no publican registros ni modifican el inventario
real. Cubren contraseñas, formularios, aprobación, reintentos y retiros simultáneos.

Referencias de configuración: [Secrets de Streamlit](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management),
[árboles y commits de GitHub](https://docs.github.com/en/rest/git/trees),
[actualización de ramas](https://docs.github.com/en/rest/git/refs).
