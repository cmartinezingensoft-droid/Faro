# Historial de desarrollo - MCP Faro

> Este documento consolida en un unico fichero los 24 documentos de fase que registraban el desarrollo incremental del servidor MCP de Faro (`FASE1_PYTHON_DIRECTO.md`, `FASE2A..2I_*.md` y `LIMPIEZA_FASE1..14_*.md`), mas el antiguo `MIGRATION_STATUS.md`. Esos ficheros individuales se han eliminado tras esta fusion; su contenido integro se conserva aqui, en orden cronologico, como registro historico de decisiones de diseno, fidelidad con el Delphi/DataSnap original y bugs heredados corregidos conscientemente.
>
> Para el **catalogo de herramientas vigente hoy** (nombres publicos, perfiles, parametros) consulta `README.md` y, para el detalle completo de esquemas, `faro_mcp.tool_definitions()` o la pagina de ayuda en vivo del Probador MCP (`/ayuda`). Este historial documenta el *porque* se llego a ese contrato paso a paso; no lo sustituyas ni lo mantengas sincronizado con cada cambio menor: para eso esta el README.
>
> **Estado vigente (22/09/2026):** servidor **2.15.7**, contrato publico **2.0**, perfiles `core=81`, `admin=89`, `integrations=82`, `all/full=90` y suite **341/341 pruebas** correctas. Las cifras distintas que aparecen dentro de las fases siguientes son historicas y describen el estado exacto de cada fase en su momento.

## Indice

1. [Fase 1 - Python directo](#fase-1---python-directo)
2. [Fase 2A - Motor comercial](#fase-2a---motor-comercial)
3. [Fase 2B - Pedidos](#fase-2b---pedidos)
4. [Fase 2C - Ventas y caja](#fase-2c---ventas-y-caja)
5. [Fase 2D - Documentos de venta](#fase-2d---documentos-de-venta)
6. [Fase 2E - Facturacion](#fase-2e---facturacion)
7. [Fase 2F - Logistica](#fase-2f---logistica)
8. [Fase 2G - Control horario](#fase-2g---control-horario)
9. [Fase 2H - Documentos, ficheros y correo](#fase-2h---documentos-ficheros-y-correo)
10. [Fase 2I - SQL legacy y utilidades](#fase-2i---sql-legacy-y-utilidades)
11. [Limpieza Fase 1 - Catalogo](#limpieza-fase-1---catalogo)
12. [Limpieza Fase 2 - Consolidacion](#limpieza-fase-2---consolidacion)
13. [Limpieza Fase 3 - Normalizacion del API publico](#limpieza-fase-3---normalizacion-del-api-publico)
14. [Limpieza Fase 4 - Perfiles core y full](#limpieza-fase-4---perfiles-core-y-full)
15. [Limpieza Fase 5 - Compactacion de stock/almacen](#limpieza-fase-5---compactacion-de-stockalmacen)
16. [Limpieza Fase 6 - Compactacion de pedidos](#limpieza-fase-6---compactacion-de-pedidos)
17. [Limpieza Fase 7 - Clientes y CRM](#limpieza-fase-7---clientes-y-crm)
18. [Limpieza Fase 8 - Articulos, catalogo y compras](#limpieza-fase-8---articulos-catalogo-y-compras)
19. [Limpieza Fase 9 - Ventas y mostrador](#limpieza-fase-9---ventas-y-mostrador)
20. [Limpieza Fase 10 - Perfiles finales y congelacion del contrato](#limpieza-fase-10---perfiles-finales-y-congelacion-del-contrato)
21. [Limpieza Fase 11 - Refactor interno y eliminacion de aliases](#limpieza-fase-11---refactor-interno-y-eliminacion-de-aliases)
22. [Limpieza Fase 12 - Contrato MCP v2](#limpieza-fase-12---contrato-mcp-v2)
23. [Limpieza Fase 13 - Seguridad, permisos y auditoria](#limpieza-fase-13---seguridad-permisos-y-auditoria)
24. [Limpieza Fase 14 - SDK MCP oficial](#limpieza-fase-14---sdk-mcp-oficial)
25. [Anexo - Estado de migracion DataSnap -> MCP Python](#anexo---estado-de-migracion-datasnap---mcp-python)

---

## 1. Fase 1 - Python directo

> _Fuente original: `FASE1_PYTHON_DIRECTO.md` (fusionado, fichero eliminado)._

> **Actualizacion Fase 2A:** el proyecto ya no contiene ni registra proxies DataSnap. `Precio_Cliente_Articulo`, `Ultimas_Ventas_Cliente` y `TipoVenta_Cliente` se han migrado a Python nativo. Las exclusiones antiguas sobre el motor `PRECIO_VENTA` se referian exclusivamente a `py_grabar_pedido_cliente`; el motor completo ya existe ahora como servicio reutilizable en `py_precio_cliente_articulo`.


Este documento recoge las funciones implementadas directamente en Python sobre ODBC `faro`, sin depender del servidor DataSnap Delphi.

La fase 1 cubre consultas de articulos, stock, familias, marcas, proveedores y ofertas simples. Tambien se ha iniciado el bloque de escrituras sencillas con etiquetas.

### Criterios de implementacion

- Conexion por `FARO_DB_DRIVER=odbc` y `FARO_ODBC_DSN=faro`.
- Filtro por empresa usando `FARO_EMPRESA`, por defecto `1`.
- Salida principal en JSON estructurado.
- Campo adicional `datasnap_text` cuando existe una salida historica equivalente en DataSnap con separadores `|` y `#`.
- Consultas SQL parametrizadas, salvo el campo de ordenacion de busqueda, que se limita a una lista blanca.
- No se aceptan fragmentos SQL libres como `TEXTO_ADICIONAL`; se sustituyen por parametros controlados.

### Funciones MCP directas

| Herramienta MCP | Funcion DataSnap equivalente | Tablas principales | Estado |
| --- | --- | --- | --- |
| `py_find_article` | `Busqueda_Articulo` | `ARTICUL`, `ARTICULC`, `PROVEE` | Implementada y probada |
| `py_search_articles` | `Busqueda_Articulos` | `ARTICUL`, `PROVEE` | Implementada con descripcion, prefijo de codigo y orden controlado |
| `py_article_technical_info` | `Informacion_Tecnica_Articulo` | `ARTCAR` | Implementada |
| `py_article_stock` | `Stock_Articulo` | `ARTICULE` | Implementada y probada |
| `py_article_stocks` | `Stocks_Articulo` | `ARTICULE` | Implementada y probada |
| `py_article_brand` | `Marca_Articulo` | `ARTICULI` | Implementada y probada |
| `py_list_brands` | `Lista_Marcas` | `ARTICULI` | Implementada y probada |
| `py_list_families` | `Lista_Familias` | `FAMILI`, `SUBFAM` | Implementada y probada |
| `py_list_web_families` | `Lista_Familias_Web` | `FAMWEB` | Implementada |
| `py_article_suppliers` | `Proveedores_Articulo` | `ARTICULP`, `PROVEE` | Implementada y probada |
| `py_article_purchase_sheet` | `Ficha_Compra_Articulo` | `ARTICULP` | Implementada y probada |
| `py_offer_pvp` | `PVP_Articulo_Oferta` | `DETOFER`, `OFERTAS` | Implementada y probada sin oferta activa |
| `py_get_labels` | `Etiquetas_Articulo` | `ETIQUE` | Implementada |
| `py_list_labels` | `Lista_Etiquetas` | `ETIQUE` | Implementada |
| `py_grabar_etiquetas` | `Grabar_Etiquetas` | `ETIQUE` | Implementada |
| `py_regularizar_stock` | `Regularizar_Stock` | `CABDOCR`, `DETMOVR`, `ARTICULE`, `STOCKS` | Implementada |
| `py_article_recount` | `Recuento_Articulo` | `RECUENTO` | Implementada |
| `py_list_recounts` | `Recuento_Actual` | `RECUENTO` | Implementada |
| `py_grabar_recuento` | `Grabar_Recuento` | `RECUENTO` | Implementada |
| `py_borrar_recuento` | `Borrar_Recuento` | `RECUENTO` | Implementada |
| `py_borrar_etiquetas` | `Borrar_Etiquetas` | `ETIQUE` | Implementada |
| `py_article_shortage` | `Faltas_Articulo` | `FALTAS` | Implementada |
| `py_list_shortages` | `Lista_Faltas` | `FALTAS`, `ARTICUL`, `PROVEE` | Implementada |
| `py_grabar_faltas` | `Grabar_Faltas` | `FALTAS`, `ARTICUL`, `PARAMETROS` | Implementada |
| `py_borrar_faltas` | `Borrar_Faltas` | `FALTAS` | Implementada |
| `py_grabar_ubicacion` | `Grabar_Ubicacion` | `ARTICULI` | Implementada |
| `py_grabar_ubicacion1` | `Grabar_Ubicacion1` | `ARTICULI` | Implementada |
| `py_grabar_ean` | `Grabar_EAN` | `ARTICULC` | Implementada |
| `py_busqueda_cliente` | `Busqueda_Cliente` | `CLIEN`, `PROVIN` | Implementada |
| `py_consulta_clientes` | `Consulta_Clientes` | `CLIEN` | Implementada con filtros tipados (ver diferencias) |
| `py_grabar_cliente` | `Grabar_Cliente` | `CLIEN` | Implementada (simplificada, ver diferencias) |
| `py_tipos_actividad` | `Tipos_Actividad` | `TIPACT` | Implementada |
| `py_lista_actividades` | `Lista_Actividades` | `ACTIVI`, `TIPACT` | Implementada |
| `py_lista_actividades_representante` | `Lista_Actividades_Representante` | `ACTIVI`, `CLIEN`, `TIPACT` | Implementada |
| `py_grabar_actividad` | `Grabar_Actividad` | `ACTIVI` | Implementada |
| `py_seguridad_usuario` | `Seguridad_Usuario` | `GRUPUSU`, `USUAR` | Implementada |
| `py_conexion_usuario` | `Conexion_Usuario` | `USUAR` | Implementada (usa CRIPT) |
| `py_conexion_cliente` | `Conexion_Cliente` | `CLIENI` | Implementada |
| `py_cript` | `CRIPT` (`LIBTIP_U.pas`) | — | Utilidad, sin tabla propia |
| `py_grabar_pedido_cliente` | `Grabar_Pedido_Cliente` | `CABDOCV`, `DETMOV`, `NUMERA`, `CLIEN`, `ARTICUL`, `CLIART`, `TIPIVA` | Implementada (simplificada, ver diferencias) |

### Diferencias conscientes frente a DataSnap

`py_search_articles` no acepta `TEXTO_ADICIONAL` como fragmento SQL libre. El DataSnap original concatena ese texto dentro de la consulta, pero en MCP se evita para no abrir una via de SQL arbitrario desde la IA. En su lugar se ofrece busqueda por descripcion, prefijo de codigo de articulo, limite de filas y ordenacion controlada.

Las funciones devuelven JSON estructurado ademas del formato compatible `datasnap_text`. Para nuevas automatizaciones debe usarse el JSON. El formato `datasnap_text` se conserva para comparar con clientes FMX existentes.

`py_offer_pvp` usa la fecha actual del equipo para buscar ofertas vigentes, igual que Delphi usa `DATE`.

### Escritura sencilla de etiquetas

`py_grabar_etiquetas` replica la funcion DataSnap `Grabar_Etiquetas`.

Parametros:

| Parametro | Uso |
| --- | --- |
| `codart` | Codigo de articulo que se graba en `ETI_CODART`. |
| `descri` | Descripcion que se graba en `ETI_DESCRI`. |
| `cantid` | Cantidad de etiquetas. Debe ser numerica. |
| `aumentar` | Si es `false`, borra la etiqueta existente del articulo e inserta la nueva. Si es `true`, intenta insertar y, si ya existe, suma la cantidad a `ETI_CANTID`. |
| `modelo` | Modelo de etiqueta `ETI_MODELO`. |
| `imprimir` | Si es `true`, graba `ETI_IMPRIM='S'`; si es `false`, graba `ETI_IMPRIM='N'`. |

La funcion devuelve `before`, `after` y `diff` para auditar el cambio. La operacion se ejecuta dentro de transaccion; ante error se hace rollback.

### Escritura sencilla de stock

`py_regularizar_stock` replica la funcion DataSnap `Regularizar_Stock`.

La cantidad `cantid` representa la existencia final contada, no el incremento. La funcion calcula:

```text
diferencia = cantid - stock_actual
```

Si la diferencia es cero, no graba ningun documento. Si hay diferencia:

- busca o crea una cabecera `CABDOCR` de tipo `R` para el centro indicado y fecha de ayer;
- obtiene la serie desde `PARAMETROS` con codigo `R{centro}`;
- inserta una linea en `DETMOVR` con la diferencia;
- si el articulo es inventariable (`ART_INDINV='S'`), acumula la diferencia en `ARTICULE`;
- ejecuta todo dentro de una transaccion.

Parametros:

| Parametro | Uso |
| --- | --- |
| `codart` | Codigo de articulo. |
| `centro` | Centro cuyas existencias se regularizan. |
| `descri` | Descripcion que se graba en `DMR_DESCRI`. |
| `unimed` | Unidad de medida que se graba en `DMR_UNIMED`. |
| `cantid` | Existencia final contada. |

La respuesta devuelve stock anterior, stock objetivo, diferencia, stock posterior y documento generado (`centro`, `ejerci`, `serie`, `numdoc`, `numlin`).

### Consulta y escritura de recuento

`py_article_recount` replica `Recuento_Articulo` (devuelve el registro `RECUENTO` de un articulo en un centro) y `py_list_recounts` replica `Recuento_Actual` (lista todo `RECUENTO` de un centro).

`py_grabar_recuento` replica la funcion DataSnap `Grabar_Recuento`.

Parametros:

| Parametro | Uso |
| --- | --- |
| `codart` | Codigo de articulo que se graba en `REC_CODART`. |
| `centro` | Centro sobre el que se graba el recuento (`REC_CENTRO`). |
| `descri` | Descripcion que se graba en `REC_DESCRI`. |
| `unimed` | Unidad de medida que se graba en `REC_UNIMED`. |
| `cantid` | Cantidad contada. Debe ser numerica. Se graba en `REC_EXIST` junto con la fecha actual (`REC_FECHA`). |
| `aumentar` | Si es `false`, borra el recuento existente del articulo/centro e inserta la nueva cantidad. Si es `true`, intenta insertar y, si ya existe, suma la cantidad a `REC_EXIST`. |

La funcion comprueba primero que el articulo exista en `ARTICUL` (comprobacion adicional que no hace el Delphi original, pero que evita grabar recuentos huerfanos). Devuelve `before`, `after` y `diff` para auditar el cambio, y se ejecuta dentro de una transaccion con rollback ante cualquier error.

**Correccion consciente de un bug heredado**: el `Grabar_Recuento` de Delphi (`ServerMethodsUnit1.pas`) tiene el mismo patron que `Grabar_Etiquetas` (ver mas arriba) y, por tanto, los mismos dos defectos: (1) confirma la transaccion (`FIN_TRANSACCION(True)`) aunque el `INSERT`/`UPDATE` haya fallado, y (2) en el modo "aumentar", el resultado del `UPDATE` de acumulacion se descarta sin reasignarlo a `R_PARSQL`, por lo que la funcion casi siempre devuelve `False` cuando el recuento ya existia, aunque la cantidad se sume correctamente. `py_grabar_recuento` no reproduce estos defectos: hace rollback explicito ante error y su resultado (`updated: True`) refleja el estado real tras la operacion.

### Consulta y escritura de faltas

`py_article_shortage` replica `Faltas_Articulo`. Al igual que el Delphi original, **no filtra por proveedor**: si un articulo tiene faltas registradas de varios proveedores en el mismo centro, devuelve la primera fila que encuentre la consulta (comportamiento ambiguo heredado, no introducido por el MCP).

`py_list_shortages` replica `Lista_Faltas`: lista `FALTAS` de un centro con la descripcion del articulo (`ARTICUL.ART_DESCRI`) y el nombre corto del proveedor (`PROVEE.PRO_NOMCOR`).

`py_grabar_faltas` replica `Grabar_Faltas`. Parametros:

| Parametro | Uso |
| --- | --- |
| `codart` | Codigo de articulo que se graba en `FAL_CODART`. |
| `centro` | Centro sobre el que se graba la falta (`FAL_CENTRO`). |
| `codpro` | Proveedor (`FAL_PROVEE`). Si es `0`, se resuelve automaticamente: si el articulo no es propio (`ART_INDPROP='N'`) se usa el parametro `COINFE` (por defecto `9999`); si es propio, se usa `ART_CODPRO` del articulo. |
| `cantid` | Cantidad en falta. Debe ser numerica. |
| `aumentar` | Si es `false`, borra la falta existente de ese articulo/proveedor/centro e inserta la nueva cantidad. Si es `true`, intenta insertar y, si ya existe, suma la cantidad a `FAL_CANTID`. |

La clave de identificacion de una falta es `FAL_NUMEMP + FAL_CENTRO + FAL_CODART + FAL_PROVEE` (a diferencia de etiquetas y recuento, que solo usan `CODART`). `py_grabar_faltas` usa esa clave completa tanto para el `DELETE`/`UPDATE` como para el `before`/`after` del resultado, evitando la ambiguedad de `Faltas_Articulo` cuando hay varios proveedores.

**Mismo bug heredado que en etiquetas y recuento**: `Grabar_Faltas` en Delphi tiene identicos defectos (commit incondicional y `CODERR` obsoleto en el camino de acumulacion). `py_grabar_faltas` los corrige desde el principio, igual que las dos funciones anteriores.

### Borrados directos

`py_borrar_recuento`, `py_borrar_etiquetas` y `py_borrar_faltas` replican `Borrar_Recuento`, `Borrar_Etiquetas` y `Borrar_Faltas` respectivamente. A diferencia de las funciones `Grabar_*`, estas tres funciones **ya estaban bien implementadas en Delphi** (asignan correctamente el resultado de `EJECUTA_SQL` y hacen commit o rollback segun `CODERR`), asi que no hay ningun bug que corregir aqui: son un `DELETE` directo dentro de transaccion, con rollback si falla. Las versiones Python devuelven ademas el estado previo (`deleted: true/false` segun si existia el registro) para facilitar la auditoria desde la IA.

### Ubicaciones y EAN

`py_grabar_ubicacion` y `py_grabar_ubicacion1` replican `Grabar_Ubicacion` y `Grabar_Ubicacion1` (`ServerMethodsUnit1.pas:1114-1199`). Ambas graban un valor de texto libre en la tabla generica de informacion adicional `ARTICULI`, usando `ARTI_CODINF='UBICA'` y `ARTI_CODINF='UBIC1'` respectivamente (dos ubicaciones independientes por articulo). Si ya existe una fila con ese `ARTI_CODINF` para el articulo se modifica; si no, se inserta con un numero de linea nuevo (`ARTI_NUMLIN`), calculado como el maximo existente para el articulo (compartido entre todos los tipos de informacion adicional, no solo ubicaciones) mas uno, igual que `NUMERAR_ARTICULI`.

A diferencia de etiquetas/recuento/faltas, `Grabar_Ubicacion` **no tiene ningun bug**: en Delphi ya hace commit o rollback correctamente segun el resultado real de la operacion (`FIN_TRANSACCION(R_PARSQL.CODERR = 0)`), asi que `py_grabar_ubicacion*` simplemente replica la logica sin necesidad de corregir nada.

No existe en Delphi una funcion de consulta dedicada para leer la ubicacion de un articulo (se lee normalmente como parte de otras fichas). El MCP añade `article_info(codart, codinf)` como metodo interno (no expuesto como herramienta por separado) que se usa para el `before`/`after` de estas dos escrituras.

`py_grabar_ean` replica `Grabar_EAN` (`ServerMethodsUnit1.pas:1360-1380`): da de alta un codigo de barras adicional para un articulo en `ARTICULC`, con `ARTC_CANTID=1` fijo. Solo inserta (no hay logica de sustitucion/acumulacion); si el codigo ya existe para otro articulo, la insercion fallara por conflicto y la operacion se deshace. Al igual que `Grabar_Ubicacion`, `Grabar_EAN` en Delphi ya maneja bien el commit/rollback, asi que no hay ningun bug que corregir aqui tampoco.

### Clientes, actividades y seguridad

#### Fuente de verdad usada

Esta fase se ha implementado a partir de `DataModules/CLIEN_UDM.pas` (no `ServicioDatasnap/CLIEN_UDM.pas`, que es una copia obsoleta), `DataModules/ACTIVI_UDM.pas`, `DataModules/GRUPUSU_UDM.pas`, `DataModules/USUAR_UDM.pas`, `DataModules/TIPACT_UDM.pas` y `ServicioDatasnap/ServerMethodsUnit1.pas` (que si es el fichero vigente) y `ServicioDatasnap/LIBTIP_U.pas` (para `CRIPT`).

#### Busqueda y consulta de clientes

`py_busqueda_cliente` replica `Busqueda_Cliente`: consulta directa a `CLIEN` (no pasa por `BUSQUEDA_CLIEN`, asi que no aplica el caso especial "Clientes Caja" ni añade los campos derivados de `CLIENI`). Devuelve `CODCLI|NOMCLI|RAZSOC|DOMICI|CODPOS|POBLAC|PROVINCIA|TELEFO|FAX|EMAIL|CIF`, con la provincia calculada a partir de los 2 primeros digitos del codigo postal contra `PROVIN` (igual que la funcion anidada `BUSQUEDA_PROVIN` del Delphi original). Solo `NOMCLI`, `RAZSOC` y `DOMICI` se limpian de `|`/`#` (`ELIMINAR_CARACTERES`), igual que en Delphi; el resto de campos se devuelven tal cual.

`py_consulta_clientes` replica `Consulta_Clientes`, pero **con filtros tipados** (`codcli`, `subcli`, `nombre_like`, `poblacion_like`, `cif`, `codrep`, `limit`) en lugar del parametro `CADENA_SQL` que el Delphi original concatena directamente a la sentencia SQL. Aceptar un fragmento de SQL arbitrario desde una herramienta MCP (potencialmente redactado por un modelo de lenguaje) es un riesgo de inyeccion SQL inaceptable, asi que esta es una **desviacion deliberada por seguridad**, no un descuido de fidelidad. El limite de filas (`MAXREG` en Delphi) es una variable global cuyo valor en produccion desconocemos; se usa `MAX_ROWS_DEFAULT` (500) como equivalente razonable.

#### Grabar_Cliente

`py_grabar_cliente` replica `Grabar_Cliente`. Es una funcion de **modificacion unicamente**: recibe `TEXTO` con el formato `CODCLI|SUBCLI|NOMCLI|RAZSOC|DOMICI|CODPOS|POBLAC|TELEFO|EMAIL|CIF` (10 campos) y solo puede tocar esos 8 campos de datos de un cliente que ya exista en `CLIEN`. Si el cliente no existe, no graba nada (en Delphi, `BUSQUEDA_CLIEN` devuelve `CLI_CODCLI=-1` y `Grabar_Cliente` sale sin avisar; aqui se refleja con `found: false`).

Caso especial replicado: si `CODCLI=99999` y `SUBCLI=0` ("Clientes Caja"), `BUSQUEDA_CLIEN` en Delphi **no consulta la base de datos** para ese par concreto y devuelve un registro sintetico con `CLI_CODCLI=99999` (no `-1`), por lo que `Grabar_Cliente` no sale por el chequeo de "no encontrado" y continua intentando el `UPDATE`. Si esa fila no existe fisicamente en `CLIEN`, el `UPDATE` no falla, simplemente no afecta ninguna fila. `py_grabar_cliente` reproduce exactamente este comportamiento.

**Simplificaciones deliberadas frente al `GRABAR_CLIEN('M')` completo** (la funcion de bajo nivel que usa `Grabar_Cliente`):

1. `MODIFICAR_CLIEN` en Delphi reescribe unas 40 columnas de `CLIEN` en cada llamada, pero `Grabar_Cliente` solo asigna valores nuevos a 8 de ellas (`NOMCLI`, `RAZSOC`, `DOMICI`, `CODPOS`, `POBLAC`, `TELEFO`, `EMAIL`, `CIF`); las ~32 restantes llegan intactas desde el registro que cargo `BUSQUEDA_CLIEN` y se "regraban" con su propio valor (una operacion sin efecto neto, pero no inocua: si otro proceso modifico alguna de esas columnas entre la lectura y la escritura, ese cambio se pierde). `py_grabar_cliente` hace un `UPDATE` dirigido solo a las 8 columnas reales + `CLI_FECMOD`/`CLI_USUMOD`, con el mismo resultado observable pero sin ese riesgo de condicion de carrera.
2. `GRABAR_CLIEN('M')` recorre ademas una cascada de **27 campos "adicionales"** en la tabla lateral `CLIENI` (`ALB`, `IMPMI`, `SERIE`, `CANPM`, `ACECR`, `ACEOF`, `ACEPR`, `TIVEN`, `TIVFA`, `TIVFC`, `TIVR`, `COBAL`, `PUBLI`, `FEMAI`, `ACDTO`, `WEB`, `DOMIC`, `DOMEN`, `EMAIP`, `IBAN`, `FACMI`, `RUPRE`, `SERIP`, `CAUCI`, `ACTIV`, `PIVA`, `PAIS`), haciendo upsert o borrado de cada uno segun este vacio o no en el registro. Como el formato `TEXTO` de `Grabar_Cliente` **nunca asigna ninguno de estos campos** (solo llegan precargados desde su valor previo, via `BUSQUEDA_CLIEN`), esta cascada es, en la practica, un "reescribir con el mismo valor" que no cambia nada al invocarse desde `Grabar_Cliente`. Se ha decidido **omitirla** en `py_grabar_cliente` en lugar de reproducir 27 upserts sin efecto real; si en una fase futura se implementa una funcion que si permita editar esos campos (por ejemplo, un `Grabar_Cliente_Extendido` o el propio `GRABAR_CLIEN` de bajo nivel como primitiva reutilizable), se añadira entonces.

`CLI_USUMOD` en `GRABAR_CLIEN('M')` se graba como `"{CENTRO} {USUARIO}"` (prefijado de centro), a diferencia de otras tablas ya implementadas (`FALTAS`, `RECUENTO`, `ACTIVI`) que solo graban el usuario. Se ha respetado esa diferencia.

A diferencia de `Grabar_Etiquetas`/`Grabar_Recuento`/`Grabar_Faltas`, `Grabar_Cliente` en Delphi **ya hace commit/rollback correctamente** (`FIN_TRANSACCION(R_PARSQL.CODERR = 0)`), asi que no hay un bug de transaccion que corregir aqui. Si acaso, hay una peculiaridad distinta: `Grabar_Cliente` nunca asigna su `Result` a partir de `R_PARSQL.CODERR`, por lo que el RPC Delphi **siempre devuelve cadena vacia**, exito o fracaso; el llamante no puede saber si realmente se grabo algo. `py_grabar_cliente` corrige esa falta de observabilidad devolviendo `found`/`updated` en el JSON.

#### Actividades comerciales

`py_tipos_actividad` replica `Tipos_Actividad` (catalogo `TIPACT`). `py_lista_actividades` replica `Lista_Actividades` (actividades de un cliente, mas recientes primero, con el tipo resuelto via `TIPO_ACTIVIDAD`). `py_lista_actividades_representante` replica `Lista_Actividades_Representante`, incluyendo el limite de 50 actividades del original. Ninguna de las tres limpia `ACT_OBSERV` de `|`/`#` porque el Delphi original tampoco lo hace (bug heredado de formato, no corregido aqui por no alterar el contenido almacenado).

`py_grabar_actividad` replica `Grabar_Actividad`: busca una actividad existente del cliente **por `CODCLI` + `FECHA` exacta** (sin filtrar por `SUBCLI` ni `CODACT`, igual que el original); si no la encuentra, inserta una nueva numerada con `NUMERAR_ACTIVI` (maximo global de la empresa + 1, con reintento incremental si colisiona, igual que `GRABAR_ACTIVI('G')`); si la encuentra, actualiza representante/tipo/fecha/observacion de esa misma linea.

**Correccion consciente de un bug heredado**: `Grabar_Actividad` hace `FIN_TRANSACCION(TRUE)` incondicional, confirmando la transaccion aunque `GRABAR_ACTIVI` haya fallado (mismo patron que `Grabar_Etiquetas`/`Grabar_Recuento`/`Grabar_Faltas` antes de corregirlos). `py_grabar_actividad` hace rollback si falla cualquier paso.

#### Seguridad y conexion

`py_seguridad_usuario` replica `Seguridad_Usuario`: nivel de permisos (`GRU_NIVEL|GRU_NIVPRI|GRU_AUTVEN|GRU_AUTDTO`) de un usuario en un centro, cruzando `GRUPUSU` y `USUAR` por `USU_IDGRUPO=GRU_IDGRUPO`.

`py_conexion_usuario` replica `Conexion_Usuario`: valida un usuario interno del ERP contra `USUAR`, comparando `USU_PASSWORD` con `CRIPT(1, password, '')`. Usa el centro configurado en el MCP (`FARO_CENTRO`), igual que `R_PARAMETROS.CENTRO` en la sesion Delphi.

`py_conexion_cliente` replica `Conexion_Cliente`: valida un cliente contra la tabla lateral `CLIENI` (`CLII_CODINF='USUAR'` para el login, `CLII_CODINF='PASSW'` para la contraseña). **Nota de seguridad heredada**: esa contraseña se guarda y compara en **texto plano**, sin `CRIPT` ni ningun otro cifrado. Se replica tal cual porque cambiar el esquema de datos no es competencia de esta fase de MCP, pero queda documentado como riesgo conocido del sistema origen.

#### CRIPT (cifrado de `USUAR.USU_PASSWORD`)

`py_cript` expone el cifrado propietario `CRIPT` de `LIBTIP_U.pas`, transcrito integramente: una tabla de 65 entradas (digitos, letras sin la `W` mayuscula, `ñ`, `Ñ` y espacio) con un valor `V1` por entrada; cifrar rellena la entrada a 8 caracteres con espacios por la derecha (si ya tiene 8 o mas, se usan los primeros 8 tal cual) y, para cada una de las 8 posiciones, en un orden fijo `[7,3,8,6,1,4,2,5]` con desplazamientos fijos `[+2,+6,+1,+3,+8,+5,+7,+4]`, emite un bloque de 4 digitos: indice de tabla (2 digitos) + `V1+desplazamiento` (2 digitos). Descifrar solo lee los 2 primeros digitos de cada bloque (el resto no se usa para verificar nada, ademas en Delphi).

**Bug real confirmado y replicado a proposito**: en el Delphi original, `TABLA[33].CH := 'W';` se sobreescribe inmediatamente con `TABLA[33].CH := 'X';`, por lo que ninguna entrada de la tabla queda asociada a `'W'` mayuscula. Cualquier contraseña que contenga una `W` mayuscula dentro de sus primeros 8 caracteres **no se puede cifrar**: `CRIPT` devuelve cadena vacia, y por tanto ese usuario nunca podria iniciar sesion con esa contraseña en el sistema original. `py_cript`/`cript()` reproducen exactamente esta limitacion (necesario para generar hashes compatibles con los ya almacenados en `USUAR`); no se ha "arreglado" porque cambiar la tabla rompería la compatibilidad con las contraseñas ya cifradas en la base de datos. La posicion 36 de la tabla (`V1=43`) tampoco tiene caracter asociado en el original (hueco sin uso, inofensivo).

Verificado con round-trip cifrar/descifrar sobre varias contraseñas de prueba (incluida la reproduccion exacta del fallo con `'W'`).

### Pedidos de cliente

#### Fuente de verdad usada

`py_grabar_pedido_cliente` replica `Grabar_Pedido_Cliente` (`ServicioDatasnap/ServerMethodsUnit1.pas:1501-1668`), apoyandose en `DataModules/CABDOCV_UDM.pas` (`GRABAR_CABDOCV`, `INSERTAR_CABDOCV`, `NUMERAR_CABDOCV`, `GRABAR_NUMERA`, `VALORAR_DETMOV`, `INSERTAR_DETMOV`, `IVA_CABDOCV`, `TOTALES_CABECERA`, `VALORAR_CABDOCV`, `FINALIZAR_CABDOCV`, `BORRAR_CABDOCV`) y en `FuentesDelphi/LIBESP_U.pas` (`PRECIO_VENTA`, solo para las partes de esa funcion que sobreviven — ver mas abajo) y `DataModules/CLIEN_UDM.pas` (`BUSQUEDA_CLIEN`).

**Discrepancia detectada y documentada**: `BUSQUEDA_TIPVEN2` (usada para resolver `CBV_TIPVEN`) no existe en el `DataModules/TIPVEN_UDM.pas` actual (se ha leido integro y solo tiene el CRUD basico), ni en ningun otro sitio de las fuentes vigentes. Solo se ha podido localizar en la copia **obsoleta** `ServicioDatasnap/CABDOCV_UDM.pas`. Al ser trivial (`SELECT FIRST 1 TIV_CODIGO FROM TIPVEN WHERE ... ORDER BY TIV_CODIGO`, o `-1` si no hay ninguno) se ha replicado esa version por ser la unica disponible, pero queda registrado aqui como una discrepancia real frente a la regla general de este proyecto de usar siempre `DataModules/` como fuente de verdad.

#### Que hace

Crea un Pedido (`CBV_TIPDOC='P'`) o, si `urgente='R'`, un Presupuesto (`CBV_TIPDOC='R'`) para un cliente: cabecera en `CABDOCV` (numerada via `NUMERA`, serie fija `'PM'`, centro-caja `1`, ejercicio = año actual), lineas de articulo en `DETMOV` a partir de `TEXTO` (formato `CODART|DESCRI|CANTID|PREVEN|DTO1` por linea, lineas separadas por `#`) y lineas de comentario (`TIPLIN='C'`) a partir de `OBSERVACIONES` (una por cada retorno de carro `\r`, truncada a 100 caracteres). Al terminar, calcula el desglose de IVA y los totales de cabecera (equivalente a `FINALIZAR_CABDOCV`) y, si el pedido se queda sin ninguna linea (`TEXTO` y `OBSERVACIONES` vacios), borra la cabecera que acababa de crear en vez de dejarla vacia — igual que hace el Delphi original.

**Sin efecto en stock**: se ha confirmado leyendo `ACUMULA_DETMOV` que esta funcion hace `GOTO FIN` (no-op) inmediatamente cuando `DMV_SIGNO='0'`, y `DMV_SIGNO` solo llega a `'1'` para `TIPDOC` en `('T','A','C','F')` — nunca para `'P'`/`'R'`. Por eso `Grabar_Pedido_Cliente` (y por tanto `py_grabar_pedido_cliente`) nunca toca `ARTICULE`/existencias.

#### Exclusiones deliberadas frente al Delphi original

1. **Motor de precios `PRECIO_VENTA` completo**: en el Delphi original, cada linea se pasa por esta funcion de ~350 lineas (ofertas activas, precios especiales por cliente/subcliente/grupo, tablas de precio (`CLITAB`), descuentos por familia, tarifas por actividad, articulos-canon), pero justo despues `Grabar_Pedido_Cliente` **sobrescribe incondicionalmente** `DMV_PREVEN` y `DMV_DTO1` con los valores que llegan en `TEXTO`. Todo ese calculo de precio especial es, por tanto, trabajo desechado: no influye en absoluto en el resultado grabado. `py_grabar_pedido_cliente` solo replica lo que si sobrevive: resolucion del articulo (incluido el fallback al codigo propio del cliente via `CLIART`), `DMV_UNIMED`/`DMV_CODMON`/`DMV_PVP`, y el calculo de `DMV_PORIVA`/`DMV_PORREQ` (override `PORIVA_CLIENTE` o `BUSQUEDA_TIPIVA` + recargo de equivalencia si el cliente no es "Caja" y `CLI_REGIVA='R'`). Efecto secundario aceptado: `DMV_NUMOFE`/`DMV_EJEOFE` (anotaciones estadisticas de ofertas) quedan siempre a `0` en vez de heredar una oferta activa, ya que esas son las unicas dos columnas de ese motor que no se sobrescriben despues.
2. **Multiplicador `ART.CANTIDAD`**: `PRECIO_VENTA` hace `DMV_CANTID := ART.CANTIDAD * DMV_CANTID`, pero se ha confirmado leyendo `CARGAR_ARTICUL` integro que el campo `ARTICUL.CANTIDAD` **nunca se asigna** ahi (es un campo de registro sin el prefijo `ART_`, aparentemente pensado como campo transitorio en memoria) — es decir, ese multiplicador opera sobre memoria de pila sin inicializar en el Delphi original. Replicarlo significaria adivinar un valor indefinido, asi que se omite: `DMV_CANTID` se usa tal cual llega del llamante.
3. **Cambio de divisa** (`CAMBIAR_PRECIO`): no implementado. Se asume moneda unica `'E'` en cabecera, articulos y lineas; si un articulo resuelve a otra moneda, o una linea ya grabada tiene una moneda distinta a la de la cabecera al calcular el IVA, se lanza un error explicito en vez de adivinar una tasa de cambio.
4. **Riesgo de cliente** (`ACTUALIZA_RIESGO_CLIENTE`/`RIESGO_ACTUAL`): no implementado. Es un subsistema grande (calculo de exposicion de credito, distinto para clientes "Caja" y de facturacion) solo parcialmente analizado; queda para una posible fase futura dedicada.
5. **Envio de email** (`ENVIAR_CORREO`): no implementado, este MCP no tiene SMTP configurado. El parametro `email` se acepta por fidelidad de firma pero se ignora (el resultado indica `email_omitido: true` si se paso algo).

#### Correcciones deliberadas (bugs heredados, no reproducidos)

- **Cliente inexistente**: `BUSQUEDA_CLIEN` devuelve un registro centinela con `CLI_CODCLI=-1` cuando el cliente no existe (fuera del caso especial "Clientes Caja" `99999/0`), pero `Grabar_Pedido_Cliente` **nunca comprueba** ese centinela: graba felizmente un pedido con `CBV_NOMCLI=''`, `CBV_CIF=''`, etc. para un cliente que no existe. `py_grabar_pedido_cliente` rechaza la operacion con un error en su lugar.
- **Articulo no resoluble**: si `PRECIO_VENTA` no puede resolver `DMV_CODART` (ni directo ni via el codigo propio del cliente en `CLIART`), en Delphi solo marca `CODERR=2` en su propio resultado, pero `Grabar_Pedido_Cliente` **no comprueba ese CODERR** y sigue grabando la linea igualmente, con el codigo original sin validar y `DMV_PORIVA`/`DMV_PORREQ` a `0`. `py_grabar_pedido_cliente` rechaza la linea completa con un error en su lugar.
- **Transaccion incondicional**: igual que en fases anteriores (`Grabar_Etiquetas`, `Grabar_Recuento`, `Grabar_Faltas`, `Grabar_Actividad`), el Delphi original hace `FIN_TRANSACCION(TRUE)` incondicional al final, confirmando la transaccion pase lo que pase. `py_grabar_pedido_cliente` hace rollback si falla cualquier paso.

#### Detalles replicados literalmente (no son descuidos, son fidelidad)

- `CBV_USUMOD`/`DMV_USUAR` se graban siempre como el literal `'admin'` (no el usuario configurado en el MCP): asi lo hace tambien el Delphi original con una asignacion literal en el codigo fuente, probablemente porque este RPC se expone a un canal externo (web/app) sin sesion de usuario interna real.
- Un 5º tipo de IVA distinto entre las lineas de un mismo pedido simplemente no se acumula en el desglose de totales (limite de 4 tramos de `IVA_CABDOCV`, con un comentario `//Fallo de analisis` en el propio Delphi junto a logica relacionada): se replica tal cual.

### Cierre y entrega de pedidos

#### Fuente de verdad usada

`py_cerrar_pedido` replica `Cerrar_Pedido` (`ServicioDatasnap/ServerMethodsUnit1.pas:1673-1737`). `py_grabar_albaran_pedido` replica `Grabar_Albaran_Pedido` (`ServicioDatasnap/ServerMethodsUnit1.pas:1739-1950`), apoyandose en `DataModules/CABDOCV_UDM.pas` (`GRABAR_DETMOV`, `ACUMULA_DETMOV`, `INSERTAR_DETMOV`, `MODIFICAR_DETMOV`, `BORRAR_DETMOV`, `VALORAR_DETMOV`) y `DataModules/ARTICUL_UDM.pas` (`ARTICULB`: composicion de blister).

**Discrepancia detectada y documentada (igual que `BUSQUEDA_TIPVEN2` en la seccion de Pedidos de cliente)**: `BUSQUEDA_CABDOCV`, `SERIE_ALBARAN_CLIENTE`, `FORMA_PAGO_CLIENTE` y `FORMATO_DOCUMENTO_CLIENTE` (junto a sus variantes de factura `FORMATO_FACTURA_CLIENTE`/`FORMATO_FACTURA_CONTADO_CLIENTE`) no existen en ningun `DataModules/*.pas` vigente (comprobado por busqueda exhaustiva, incluido un listado completo de la carpeta remota). Solo se han podido localizar en la copia **obsoleta** `ServicioDatasnap/CABDOCV_UDM.pas:5240-5351`. Se han replicado esas versiones por ser las unicas disponibles; son consultas triviales sobre columnas estandar (`CLIENI` adicional `'SERIE'`/`'TIVEN'`/`'TIVFA'`/`'TIVFC'`, `CLIEN.CLI_FORPAG`) coherentes con el resto de columnas `CLIENI` ya confirmadas en la fase de `Grabar_Cliente`.

#### `py_cerrar_pedido`: que hace

Renombra a `TIPDOC='S'` (historico/cerrado) tanto la cabecera `CABDOCV` como todas las lineas `DETMOV` del documento indicado (tipicamente un Pedido `'P'` o Presupuesto `'R'`); no borra nada.

**Bug del original corregido**: el Delphi original ejecuta, sin comprobar errores entre medias, un `UPDATE` de cabecera a `TIPDOC='S'`, un `UPDATE` de lineas a `TIPDOC='S'`, y luego un `DELETE` de cabecera y otro de lineas **filtrando por el `TIPDOC` original** — y confirma con `FIN_TRANSACCION(TRUE)` incondicional. En el caso normal, el primer `UPDATE` ya ha renombrado la fila, asi que los `DELETE` no encuentran nada (no-op). Pero si ese primer `UPDATE` falla por colision de clave primaria — ya existe una cabecera `'S'` con la misma clave, por ejemplo porque el documento ya se cerro antes — la fila original **nunca se renombra** y los `DELETE` **si la encuentran y la borran**, junto con sus lineas: el documento desaparece silenciosamente, y como el ultimo `DELETE` normalmente tiene exito, el resultado sigue indicando exito. `py_cerrar_pedido` comprueba explicitamente esa colision antes de tocar nada y rechaza la operacion con un error en su lugar; los `DELETE` (no-op confirmado en el caso normal) se omiten; y se hace rollback si cualquier paso falla.

#### `py_grabar_albaran_pedido`: que hace

Convierte total o parcialmente un Pedido (`CBV_TIPDOC='P'`) en un Albaran (`CBV_TIPDOC='A'`): crea una cabecera de Albaran nueva (numerada, serie via `SERIE_ALBARAN_CLIENTE` o `SERIE_DOCUMENTO('A')` si el cliente no tiene serie propia) y, por cada linea indicada en `TEXTO` (formato `NUMLIN|CODART|DESCRI|CANTID` por linea, lineas separadas por `#` — `CODART`/`DESCRI` se aceptan por fidelidad de formato de cable pero **nunca se usan**, igual que en el original), sirve la cantidad pedida:

- Si queda cantidad pendiente en la linea de pedido, esta se **reduce** (revalorizada: `VALLIN`/`VALLINS` recalculados para la cantidad restante) y se inserta ademas una copia "servida" con `TIPDOC='S'` bajo el propio numero del pedido, **sin revalorizar** (replica fiel de `INSERTAR_LINEA_DETMOV`, que llama a `INSERTAR_DETMOV` directo sin pasar por `GRABAR_DETMOV`).
- Si no queda pendiente (servicio total, o sobre-servicio), la linea de pedido se convierte **en su sitio** a `TIPDOC='S'` con la cantidad servida, tambien sin revalorizar (replica de `ACTUALIZAR_LINEA_DETMOV`, un `UPDATE` directo).
- En ambos casos se crea ademas una linea **nueva** en el Albaran, copiando los datos de articulo/precio de la linea de pedido original, con numeracion y "origen" (`DMV_EJERCIO`/`DMV_TIPDOCO`/`DMV_SERIEO`/`DMV_NUMDOCO`/`DMV_NUMLINO`) propios apuntando al pedido. Esta es la **unica** de las tres lineas que dispara `ACUMULA_DETMOV` con efecto real (`DMV_SIGNO='1'` porque su `DMV_TIPDOC='A'`; las otras dos son `'P'`/`'S'`, `SIGNO` siempre `'0'`), incluyendo composicion de blister via `ARTICULB` si el articulo tiene `ART_INDBLI='S'` y el parametro global `BLISTE` esta activo.
- Una linea de pedido con `NUMLIN` inexistente (por ejemplo ya consumida del todo en una entrega anterior) se ignora en silencio, igual que el original.

Al terminar todas las lineas, se replica el cierre final del original (`R_CBV3` + doble `FINALIZAR_CABDOCV`): se crea/actualiza una cabecera `CABDOCV` historica con `CBV_TIPDOC='S'` (mismo numero que el pedido) reflejando el total de lo servido **acumulado entre todas las entregas** (las lineas `'S'` de entregas anteriores siguen bajo la misma clave), y despues se recalculan los totales de la cabecera `'P'` del pedido original si aun quedan lineas pendientes, o se borra si ya no queda ninguna. Se reutiliza el mismo `_finalizar_documento_venta` (renombrado desde `_finalizar_pedido`, generico) que ya usa `py_grabar_pedido_cliente`.

**Validacion de precio activada aqui** (a diferencia de las lineas de pedido, que estan exentas): la linea nueva del Albaran, al tener `DMV_TIPDOC='A'`, **si** pasa por la comprobacion "No tiene precio asignado" de `GRABAR_DETMOV` (rechaza con error salvo que el articulo tenga `ART_TIPPRE='F'` o la linea venga de una oferta activa) — en la practica, casi nunca exenta, porque el pedido de origen nunca registra ofertas (`DMV_NUMOFE` siempre `0`, ver limitacion ya documentada en `py_grabar_pedido_cliente`).

#### Correcciones deliberadas (bugs heredados, no reproducidos)

- **Fuga de recursos si el pedido no existe**: el Delphi original abre la transaccion (`INICIO_TRANSACCION`) antes de comprobar si el pedido existe, y en **todos** sus puntos de salida por error (pedido no encontrado, fallo al grabar la cabecera del Albaran, fallo al grabar cualquier linea) termina la funcion sin llamar a `FIN_TRANSACCION`, dejando la transaccion abierta indefinidamente. `py_grabar_albaran_pedido` comprueba la existencia del pedido antes de escribir nada y envuelve el resto en un `try`/`except` que siempre hace commit o rollback.
- **Colision de la cabecera `'S'` en entregas repetidas, tolerada explicitamente en vez de ignorada a ciegas**: si el pedido ya se entrego parcialmente antes, la insercion de la cabecera `'S'` puede colisionar con la de esa entrega previa. El original ignora ese fallo sin mas (bug de la misma familia que el resto de "transaccion incondicional" de fases anteriores). Aqui se replica esa tolerancia de forma explicita (insercion "mejor esfuerzo"), pero como el recalculo de totales siempre se hace despues sobre **todas** las lineas `'S'` actuales (no depende de si la insercion tuvo exito), no hay perdida de datos: los totales quedan siempre correctos.
- **Colision de clave en `Cerrar_Pedido`**: ver seccion anterior.

#### Detalles replicados literalmente (no son descuidos, son fidelidad)

- `CBV_USUMOD` de la cabecera del Albaran **no se sobrescribe**: hereda el valor de la cabecera del pedido de origen (el Delphi original copia el registro completo del pedido y nunca toca ese campo).
- El `DELETE` de `DETMOV` que el original ejecuta tras `ACTUALIZAR_LINEA_DETMOV` (rama de servicio total) es codigo muerto confirmado (filtra por el `DMV_TIPDOC` antiguo, que el `UPDATE` inmediatamente anterior ya ha cambiado): se omite directamente, no se replica como no-op.
- `CODART`/`DESCRI` en cada linea de `TEXTO` se parsean pero se descartan, igual que el original.

#### Fuera de alcance (documentado, no implementado)

- **Impresion/generacion del Albaran** via `TIdTCPClient` contra `localhost:45000` (proceso externo `ALBLASF.exe`): no hay ese servicio de impresion disponible en este entorno; `py_grabar_albaran_pedido` solo graba los datos y los devuelve en la respuesta.
- Mismas exclusiones ya documentadas para `py_grabar_pedido_cliente`: motor de precios `PRECIO_VENTA` completo, cambio de divisa, riesgo de cliente.

### Consulta y preparacion de pedidos (cierre del grupo de pedidos)

#### Fuente de verdad usada

`py_pedidos_cliente`, `py_cuadro_pedidos`, `py_detalle_pedido` y `py_detalle_pedido_preparacion` replican, respectivamente, `Pedidos_Cliente` (`ServicioDatasnap/ServerMethodsUnit1.pas:2140-2167`), `Cuadro_Pedidos` (`:2651-2837`), `Detalle_Pedido` (`:2843-2910`) y `Detalle_Pedido_Preparacion` (`:2915-3043`). `py_mover_linea_pedido`, `py_grabar_pedido_preparado` y `py_finalizar_pedido` replican `Mover_Linea_Pedido` (`:3048-3079`), `Grabar_Pedido_Preparado` (`:3085-3232`) y `Finalizar_Pedido` (`:3238-3339`), apoyandose en `DataModules/ARTUBI_UDM.pas` (`ACUMULA_ARTUBI`, `GRABAR_ARTUBI`, `NOMBRE_ZONA`, las constantes `ZONA0..ZONA4`/`PREPARACION`/`PREPARADO`) para entender el subsistema de zonas de picking de almacen que usan estas tres ultimas.

Este bloque cierra el grupo conceptual de "pedidos" (creacion, entrega, cierre, consulta y preparacion en almacen). El siguiente bloque pendiente (ventas directas/caja, tickets y facturas) es una funcionalidad distinta.

#### El subsistema de zonas de picking (ARTZON/ARTUBI)

Antes de estas siete funciones, esta fase solo tocaba `ARTICULE`/`STOCKS` (existencias "de verdad"). Este bloque introduce un segundo sistema de cantidades, paralelo y **no relacionado con el stock real**, que usa el almacen para organizar la preparacion fisica de un pedido en cuatro "zonas":

- **Zona 0** (`ZONA0`): centinela especial "sin origen"; nunca es una zona fisica real, se usa como origen cuando se quiere materializar una cantidad en una zona destino sin descontarla de ningun sitio (backorder/forzado).
- **Zona 1** (`ZONA1`, "Dispensing"/almacen): cantidad de un articulo disponible para empezar a prepararse, en la tabla `ARTZON` (saldo por `NUMEMP+CENTRO+ZONA+CODART`).
- **Zona 2** (`ZONA2`): cantidad "en preparacion" (picking en curso).
- **Zona 3** (`ZONA3`): cantidad ya "preparada" para esa linea de pedido en concreto.

Cada movimiento entre zonas se registra en `ARTUBI` (bitacora, con `UBI_DOCUME` como clave de texto `CENTRO-TIPDOC-TIPAC-EJERCI-SERIE-NUMDOC-NUMLIN` que identifica la linea de pedido) y ademas actualiza el saldo acumulado en `ARTZON` para esa zona/articulo (`ACUMULA_ARTUBI`: intenta `INSERT`, si ya existe la fila hace `UPDATE ZON_CANTID = ZON_CANTID + delta`). Estas cantidades **no tienen ninguna relacion con `ARTICULE.ARTE_EXIST`** (el stock real, ya usado en fases anteriores): son un contador de flujo de trabajo de almacen independiente.

#### `py_pedidos_cliente`: que hace

Lista los Pedidos (`CBV_TIPDOC='P'`) de un cliente en un centro, mas recientes primero. Lectura directa, sin transformaciones.

#### `py_cuadro_pedidos`: que hace

Panel de pedidos pendientes de preparar en el almacen de un centro: combina (1) los pedidos que tienen alguna linea de un articulo con existencias > 0 en Zona 1, y (2) los pedidos que ya estan marcados como "en preparacion" (`CBV_INDEDI='L'`), en ambos casos sin duplicar. **Detalle replicado literalmente**: si un pedido aparece por varios articulos distintos (primera pasada), solo se guarda la ubicacion del PRIMER articulo procesado que lo encontro; no se actualiza si aparece de nuevo por otro articulo. No es un descuido de esta implementacion, es como esta escrito el original (usa un `Locate` + salto si ya existe, sin importar cual ubicacion es "la correcta").

#### `py_detalle_pedido` y `py_detalle_pedido_preparacion`: que hacen

`py_detalle_pedido` devuelve las lineas de un pedido con su valoracion (precio, descuentos, IVA, importes) y, para cada articulo, el stock real actual (`UTL_STOCK`, ya implementado como `current_stock_decimal`) y sus ubicaciones fijas (`ARTICULI` con `ARTI_CODINF LIKE 'UBIC%'`). `py_detalle_pedido_preparacion` es la pantalla de detalle para el proceso de picking: por cada linea, cuanta cantidad hay localizada en Zona 1 (almacen), Zona 2 (en preparacion) y Zona 3 (preparada), con sus ubicaciones respectivas, mas el stock global del articulo.

#### `py_mover_linea_pedido`: que hace

Mueve manualmente una cantidad de un articulo de una zona a otra para una linea de pedido dada por el llamante (bitacora `ARTUBI` + saldo `ARTZON`). Si la zona de origen es `0` (`ZONA0`), no se graba salida: la cantidad se materializa en el destino sin descontarse de ningun sitio real.

**Detalle replicado literalmente (no es un descuido)**: `ARTUBI_UDM.pas` tiene una funcion COMPARTIDA `MOVER_LINEA_PEDIDO` que, ademas de mover la cantidad, actualiza `CBV_SITUAC='F'` en la cabecera cuando el destino es Zona 2 -- pero esta funcion compartida la usan internamente `MARCAR_PEDIDO_PREPARADO`/`MARCAR_PEDIDO_EN_PREPARACION` (que no son RPCs expuestos), NO el RPC `Mover_Linea_Pedido`. El RPC expuesto es una reimplementacion manual e independiente en `ServerMethodsUnit1.pas` que **nunca toca `CABDOCV`**. `py_mover_linea_pedido` replica el RPC realmente expuesto, no la funcion compartida.

#### `py_grabar_pedido_preparado`: que hace

Intenta dejar TODAS las lineas de producto de un documento marcadas como "preparadas" (Zona 3) de una vez: por cada linea sin nada aun en Zona 3, usa lo que haya en Zona 2 (preparacion) o, si no hay, en Zona 1 (almacen, hasta el minimo entre disponible y pedido); y si no hay NADA disponible en ninguna de las dos, la mueve igualmente desde Zona 0 ("sin origen"), materializando la cantidad pedida completa. Al final marca la cabecera como `CBV_INDEDI='P'` (preparado).

**Detalle importante replicado literalmente (no es un bug que se corrija, es como funciona el original)**: por ese ultimo caso (Zona 0), esta funcion **siempre** termina marcando cada linea como preparada y la cabecera como preparada, exista o no exista de verdad esa cantidad en el almacen -- es, en efecto, un "forzar preparado" sin verificar stock real. Se replica tal cual porque asi esta expuesto el RPC original, sin añadir una validacion que el Delphi original no tiene.

#### `py_finalizar_pedido`: que hace

Comprueba, linea a linea, si un documento esta completamente preparado (todas las lineas tienen algo en Zona 3) o solo en preparacion (alguna tiene algo en Zona 2), y si alguna de las dos condiciones es cierta, actualiza `CBV_INDEDI`/`CBV_FECMOD` en la cabecera.

**Bug real corregido (fuga de recursos, misma familia que la ya corregida en `Grabar_Albaran_Pedido`)**: el Delphi original hace `INICIO_TRANSACCION` incondicionalmente al principio, pero solo llama a `FIN_TRANSACCION` **dentro** del bloque `IF E_PREPARADO OR E_PREPARACION` -- si el documento no esta ni preparado ni en preparacion (el caso normal de un pedido recien creado que el almacen aun no ha tocado), esa condicion es falsa y la transaccion abierta al principio **nunca se cierra**. `py_finalizar_pedido` hace commit siempre, se actualice o no la cabecera.

**Detalle replicado literalmente (no es un bug que se corrija, es una rareza real documentada)**: la variable `E_PREPARADO` empieza en `True` por defecto y solo pasa a `False` si alguna linea tiene Zona 3 = 0. Un documento SIN lineas de producto (o con todas sus lineas a cantidad 0) nunca entra en el cuerpo del bucle que la cambiaria, asi que se queda en `True` y la cabecera se marca como preparada sin haber comprobado nada en realidad. `py_finalizar_pedido` no corrige esto (no es un bug de transaccion ni de perdida de datos, solo una peculiaridad de negocio), pero queda documentado aqui por si el equipo quiere revisarlo.

#### Fuera de alcance (documentado, no implementado)

`EDITAR_CABDOCV`, `Enviar_Pedido` y `Generar_PDF_Pedido` no se implementan. Las tres delegan en `EDITAR_CABDOCV`, que no toca ningun dato ni calcula nada: solo envia un mensaje Windows `WM_COPYDATA` a un proceso GUI externo (identificado por un manejador de ventana, `MANEJADOR`) pidiendole que imprima/genere el PDF de un documento con una plantilla FastReport (`PedidoW.fr3`) o que lo envie por correo. No existe ese proceso (ni un equivalente) en este entorno, y las tres funciones devuelven siempre cadena vacia incluso en el Delphi original (nunca comprueban si el envio tuvo exito). Implementar un stub que solo devolviera `''` no aportaria nada util; se documenta la exclusion en su lugar, igual que ya se hizo con la impresion del Albaran en la fase anterior.

### Validacion realizada

Pruebas ejecutadas contra ODBC `faro` con el articulo `706550550`:

- `py_find_article`: devuelve descripcion `TESAMOLL UMBRAL 1X38 MAR. 5422`, PVP `3.4500` y proveedor `COINFER`.
- `py_article_stock` centro `1`: devuelve existencias `0`.
- `py_article_stocks`: devuelve centros `0` y `1`.
- `py_article_suppliers`: devuelve proveedor `9960 COINFER`.
- `py_article_purchase_sheet` proveedor `9960`: devuelve referencia `706550550` y precio base `1.3455`.
- `py_list_families`: devuelve 56 familias.
- `py_list_brands`: devuelve 970 marcas.
- `py_offer_pvp`: sin oferta activa para el articulo probado.
- `py_search_articles` con `codart_prefix=706550`: devuelve 43 articulos ordenados por codigo.

### Pendiente de siguientes fases

- **Grupo de pedidos: cerrado.** `Grabar_Pedido_Cliente`, `Cerrar_Pedido`, `Grabar_Albaran_Pedido`, `Pedidos_Cliente`, `Cuadro_Pedidos`, `Detalle_Pedido`, `Detalle_Pedido_Preparacion`, `Mover_Linea_Pedido`, `Grabar_Pedido_Preparado` y `Finalizar_Pedido` estan todos implementados (ver "Pedidos de cliente", "Cierre y entrega de pedidos" y "Consulta y preparacion de pedidos" arriba). `EDITAR_CABDOCV`/`Enviar_Pedido`/`Generar_PDF_Pedido` quedan fuera de alcance, documentado (impresion/email via proceso Windows externo).
- Resto del bloque de ventas en `ServicioDatasnap/ServerMethodsUnit1.pas`, un grupo distinto (venta directa/caja, tickets y facturas), por orden de aparicion: `Grabar_Venta_Abierta_Pedido` (estructuralmente muy similar a `Grabar_Albaran_Pedido`, pero contra `VENCAJ`/`VENCUR` en vez de un nuevo `CABDOCV`), `Grabar_Venta`, `Borrar_Venta`, `TipoVenta_Cliente`, `Grabar_Albaran` (venta directa sin pedido previo), `Grabar_Situacion_Pedido`, `Pedidos_Cliente_Entrada`, `Grabar_Retirado_Referencia`, `BLOQUEO_VENCAJ` y `Grabar_Ticket_Factura` (la mas grande, ~420 lineas). El subsistema de caja/venta abierta (`VENCAJ`/`VENCUR`) esta solo parcialmente explorado y es candidato a su propia sub-fase.
- Riesgo de cliente (`ACTUALIZA_RIESGO_CLIENTE`/`RIESGO_ACTUAL`): subsistema de calculo de exposicion de credito, identificado y deliberadamente excluido de `py_grabar_pedido_cliente`; candidato a fase propia si se necesita en el futuro.
- Ficheros, imagenes, PDF y correo.
- Horas/fichaje de empleados (`Comprobar_Usuario` y tabla `HORAS`): usa tambien `CRIPT` pero es una funcionalidad distinta (control horario), identificada durante la fase de clientes/actividades pero deliberadamente fuera de su alcance.
- Alta de clientes nuevos: `Grabar_Cliente` (y por tanto `py_grabar_cliente`) es solo de modificacion; no existe en el Delphi original una funcion RPC de alta de clientes expuesta en `ServerMethodsUnit1.pas` dentro de este bloque.

---

## 2. Fase 2A - Motor comercial

> _Fuente original: `FASE2A_COMERCIAL.md` (fusionado, fichero eliminado)._

### Objetivo

Eliminar dependencia funcional de DataSnap en el bloque de consulta comercial y preparar la base para migrar ventas, albaranes, caja y facturacion.

Todas las funciones de esta fase acceden directamente a Faro mediante `FaroDb`. No existe fallback ni proxy DataSnap.

### Funciones migradas

#### `py_precio_cliente_articulo`

Equivalente a `TServerMethods1.Precio_Cliente_Articulo` y al motor `PRECIO_VENTA` de `LIBESP_U.pas`.

Implementa:

- validacion de cliente y caso especial `99999/0` (Clientes Caja);
- consulta completa del articulo;
- IVA y recargo de equivalencia;
- precios especiales `CLIART`;
- descripcion especial del articulo por cliente;
- cantidad minima de precio especial;
- articulos canon mediante `ARTICULI/CANON`;
- ofertas activas `DETOFER` + `OFERTAS`;
- rechazo de ofertas segun `CLI_ACEOFE` y tipo de oferta;
- precio PVP de oferta y precio profesional de oferta;
- tabla especifica por cliente `CLITAB`;
- descuentos por familia/subfamilia `CLIFAM`;
- acumulacion de descuentos `CLIENI/ACDTO`;
- herencia de descuentos por grupo `CLIENI/GRUPO`;
- precio por actividad/seccion `CLIACT`;
- variante Salavert (`TIPPRE=2`, actividad cliente/articulo);
- tarifas `T`, `1`, `2`, `3`, `4`, `5`, `8` y `9`;
- `ART_CANPMI` / `CLI_CANPMI`;
- `PREM`;
- descuentos equivalentes para modos `TIPPRE=2/3`;
- redondeo segun `NUMDEC`/`DECLIN`;
- conversion historica `E`/`P` de `CAMBIAR_PRECIO`.

La respuesta incluye JSON estructurado y `datasnap_text` con los 11 campos del RPC original:

`PREVEN#DTO1#DTO2#PORIVA#PORREQ#TIPPRE#UNIMED#PREIVA#PVP#EJEOFE#NUMOFE`

#### `py_ultimas_ventas_cliente`

Equivalente a `Ultimas_Ventas_Cliente`.

- Cruza `DETMOV` con `CABDOCV` por la clave completa del documento.
- Filtra `DMV_SIGNO='1'`.
- Ordena por `DMV_FECMOV DESC`.
- Devuelve un solo registro por articulo: el mas reciente.
- Conserva el limite real del Delphi: hasta **101** articulos distintos (`I > 100`).
- Limpia `|` y `#` de la descripcion como `ELIMINAR_CARACTERES`.

#### `py_tipo_venta_cliente`

Equivalente a `TipoVenta_Cliente`.

Replica:

- documentos distintos de ticket (`T`) exigen cliente distinto de Caja;
- validacion especifica para albaranes (`A`);
- cliente con `CLI_RIESGO=-1` no puede generar albaran;
- `datasnap_text=''` representa operacion permitida.

### Eliminacion de proxies DataSnap

En esta fase se ha eliminado del runtime:

- importacion de `DataSnapToolRegistry`;
- registro automatico de herramientas `datasnap_*`;
- `datasnap_method_catalog`;
- variables `FARO_DATASNAP_*` del ejemplo de configuracion;
- archivo `datasnap_proxy_mcp.py`.

`McpServer()` puede construirse sin tener `ServicioDatasnap/ServerMethodsUnit1.pas` disponible.

### Pruebas

Se incluye `tests/test_phase2_commercial.py` con pruebas de regresion para:

1. servidor sin herramientas proxy DataSnap;
2. precio Caja con PVP IVA incluido;
3. prioridad de precio especial `CLIART`;
4. reglas de `TipoVenta_Cliente`;
5. deduplicacion y formato de `Ultimas_Ventas_Cliente`.

Ejecucion:

```bash
python -m unittest discover -s tests -v
```

### Siguiente fase

Fase 2B, estado y entrada de pedidos:

- `Grabar_Situacion_Pedido`;
- `Pedidos_Cliente_Entrada`;
- `Grabar_Retirado_Referencia`.

---

## 3. Fase 2B - Pedidos

> _Fuente original: `FASE2B_PEDIDOS.md` (fusionado, fichero eliminado)._

### Objetivo

Migrar a Python nativo las tres operaciones complementarias de pedidos que aun dependian de `TServerMethods1`, sin proxies ni llamadas al servidor Delphi.

Funciones migradas:

- `Grabar_Situacion_Pedido` -> `py_grabar_situacion_pedido`;
- `Pedidos_Cliente_Entrada` -> `py_pedidos_cliente_entrada`;
- `Grabar_Retirado_Referencia` -> `py_grabar_retirado_referencia`.

Todas operan directamente sobre Faro mediante `FaroDb` y SQL parametrizado.

### `py_grabar_situacion_pedido`

Replica la actualizacion de `CABDOCV.CBV_INDEDI` para la clave:

`NUMEMP + CENTRO + TIPDOC + TIPAC='0' + EJERCI + SERIE + NUMDOC`.

Se conserva el comportamiento del Delphi:

- `TIPAC` se fuerza a `0`;
- no se modifica `CBV_FECMOD`;
- no se modifica `CBV_USUMOD`;
- en caso correcto `datasnap_text` es cadena vacia, equivalente a `R_PARSQL.MSGERR` sin error.

La version Python mejora la seguridad usando parametros SQL y hace `rollback` si la actualizacion falla.

### `py_pedidos_cliente_entrada`

Replica `Pedidos_Cliente_Entrada`.

Proceso:

1. Lee `DMM_CODART` de `DETMOVM` para el documento de entrada indicado por `CENTRO/EJERCI/SERIE/NUMDOC`.
2. Para cada articulo no vacio localiza lineas `DETMOV` de pedidos (`DMV_TIPDOC='P'`).
3. Deduplica los documentos encontrados.
4. Recarga cada cabecera desde `CABDOCV`.
5. Ordena por ejercicio y numero de documento ascendente.
6. Devuelve JSON estructurado y `datasnap_text` compatible con el RPC historico.

#### Comportamientos heredados mantenidos

Hay dos decisiones aparentemente extrañas en el codigo Delphi que se conservan deliberadamente para evitar diferencias funcionales:

- El `CENTRO` recibido se usa para localizar el documento de entrada en `DETMOVM`, pero la busqueda de pedidos utiliza `R_PARAMETROS.CENTRO`. En Python esto corresponde a `FARO_CENTRO` / `self.settings.centro`.
- La deduplicacion original usa el texto `EJERCI-SERIE-NUMDOC`, no la clave completa con centro/tipo/actividad.

El JSON devuelve explicitamente `centro_pedidos` para que este comportamiento sea visible al consumidor MCP.

La salida estructurada conserva el nombre de cliente sin alterar. El `datasnap_text` tambien mantiene la concatenacion directa del Delphi, incluida su antigua vulnerabilidad a que un `|` o `#` dentro del nombre rompa el formato delimitado; los nuevos consumidores MCP deben usar siempre el JSON estructurado. Para `datasnap_text`, la fecha se representa como `dd/mm/yyyy` y el total con dos decimales y formato regional espanol.

### `py_grabar_retirado_referencia`

Replica `Grabar_Retirado_Referencia`.

El parametro `documento` mantiene el contrato historico:

`CENTRO-TIPDOC-EJERCI-SERIE-NUMDOC`

La funcion actualiza:

- `CABDOCV.CBV_RETIRA`;
- `CABDOCV.CBV_REFCLI`.

La clave siempre utiliza `TIPAC='0'` y la empresa configurada en `FARO_EMPRESA`.

A diferencia del Delphi, el MCP valida el formato de `DOCUMENTO` antes de ejecutar SQL. Un documento mal formado devuelve error en vez de provocar una conversion `StrToInt` no controlada dentro del servidor.

### Pruebas

Se añade `tests/test_phase2b_orders.py`.

Cobertura de regresion de esta fase:

1. registro de las tres herramientas Python y ausencia de proxies;
2. actualizacion de situacion con `TIPAC='0'`;
3. rollback de la situacion ante error SQL;
4. lectura de `DETMOVM`, uso del centro configurado, deduplicacion y orden de pedidos;
5. formato compatible de fecha/importe;
6. parseo y escritura de retirado/referencia;
7. rechazo de claves de documento mal formadas.

Junto con las pruebas de Fase 2A, el paquete ejecuta actualmente **11 pruebas**, todas correctas.

Ejecucion:

```bash
python -m unittest discover -s tests -v
```

### Estado tras Fase 2B

- Funciones DataSnap de referencia: **78**.
- Migradas a Python nativo: **54**.
- Pendientes: **24**.
- Cobertura nativa: **69,2 %**.
- Proxies DataSnap: **0**.
- Herramientas MCP registradas: **59** (54 equivalencias DataSnap + 5 herramientas Python adicionales).

### Siguiente fase

Fase 2C: ventas abiertas y bloqueo de caja:

- `BLOQUEO_VENCAJ`;
- `Grabar_Venta`;
- `Borrar_Venta`.

---

## 4. Fase 2C - Ventas y caja

> _Fuente original: `FASE2C_VENTAS_CAJA.md` (fusionado, fichero eliminado)._

### Objetivo

Migrar a Python nativo las tres funciones publicas DataSnap asociadas a ventas abiertas de caja, eliminando cualquier dependencia de ejecucion del servidor Delphi:

- `BLOQUEO_VENCAJ` -> `py_bloqueo_vencaj`;
- `Grabar_Venta` -> `py_grabar_venta`;
- `Borrar_Venta` -> `py_borrar_venta`.

Las tres operaciones acceden directamente a Faro mediante `FaroDb` y SQL parametrizado.

### `py_bloqueo_vencaj`

Replica el semaforo historico de `BLOQUEO_VENCAJ`:

1. comprueba `SEMAFORO` para `SEM_TABLA='VENCAJ'`;
2. inserta temporalmente el codigo recibido;
3. elimina inmediatamente la fila;
4. devuelve `datasnap_text='True'` si pudo adquirir/liberar el semaforo o `'False'` si ya estaba ocupado.

El codigo conserva el formato utilizado por Delphi:

`NUMEMP\EJERCI\NUMDOC`

La comprobacion previa mediante `SELECT` evita utilizar deliberadamente una violacion de clave unica como flujo de control, sin cambiar el contrato funcional visible.

### `py_grabar_venta`

Migra `Grabar_Venta` sobre las tablas `VENCAJ` y `VENCUR`.

#### Alta

Con `venta=''`:

- crea la cabecera de venta;
- obtiene el siguiente `CBV_NUMDOC` del ejercicio;
- obtiene la serie mediante la misma configuracion usada por `SERIE_DOCUMENTO`;
- carga datos fiscales/comerciales del cliente;
- resuelve `CBV_TIPVEN`;
- graba las lineas recibidas;
- recalcula IVA, bases y totales;
- confirma la transaccion.

#### Modificacion

Con `venta='EJERCI-NUMDOC'`:

- comprueba el semaforo `VENCAJ`;
- recupera la cabecera existente;
- elimina las lineas `VENCUR` actuales;
- vuelve a generar las lineas a partir de `texto`;
- recalcula la cabecera.

Igual que el Delphi, los argumentos `CODCLI`, `SUBCLI`, `TIPDOC` y `USUAR` no sustituyen los datos de cabecera cuando se esta editando una venta ya existente: se conserva la cabecera recuperada de `VENCAJ`.

#### Contrato de `texto`

Cada linea se separa con `#` y contiene 14 campos separados por `|`:

`CODART|DESCRI|CANTID|PREVEN|DTO1|DTO2|PORIVA|PORREQ|TIPPRE|UNIMED|PREIVA|PVP|EJEOFE|NUMOFE`

Se conserva la semantica de `PROCESAR_CADENA`: si aparece una linea vacia, el recorrido termina aunque quede texto posteriormente.

#### Valoracion de lineas

Se ha portado la rama aplicable de `VALORAR_DETMOV`:

- redondeo de cantidad;
- moneda actual historica (`E`);
- precio con/sin IVA (`PREIVA`);
- descuentos `DTO1`/`DTO2`;
- IVA y recargo de equivalencia;
- calculo de `DMV_VALLIN` y `DMV_VALLINS`;
- redondeos `P`, `L` e `I` equivalentes.

#### Canon

`Grabar_Venta` llama internamente a `GRABAR_CANON_VENCUR`, por lo que esta dependencia tambien se ha migrado.

Se soportan:

- canon interno (`PARAMETROS.CANON='I'`);
- linea informativa R.A.E.E. reservada;
- canon definido mediante `ARTICULI.CODINF='CANON'`;
- precio especial de canon via `CLIART`;
- comportamiento especial de articulos en oferta.

Se mantiene que `Grabar_Venta` pasa literalmente el cliente `99999` a `GRABAR_CANON_VENCUR`, tal como hace el fuente Delphi, incluso cuando la venta pertenece a otro cliente.

#### Regalos

Tambien se ha portado `GRABAR_REGALO_VENCUR`:

- reglas `ARTICULI.CODINF='REGAL'`;
- cantidad minima;
- linea descriptiva opcional;
- articulo de regalo;
- `DTO1=100`;
- anulacion de regalos cuando la linea pertenece a una oferta.

#### Bugs historicos preservados por compatibilidad

Se han reproducido deliberadamente dos comportamientos observados en el fuente original:

1. `Grabar_Venta` comprueba `DMV_PREVEN` antes de asignarle el `PREVEN` recibido. Como acaba de inicializarse a cero, toda linea con `CODART=''` se convierte siempre en `TIPLIN='C'`, nunca en `X` aunque tenga precio.
2. En `GRABAR_REGALO_VENCUR`, cuando una regla de regalo contiene descripcion adicional, el registro local pone `DMV_CANTID=0` antes de calcular la cantidad del articulo de regalo; por tanto el regalo termina con cantidad cero. Se conserva para no alterar silenciosamente el comportamiento historico.

Se corrige un caso no util: una cantidad minima de regalo igual o inferior a cero se trata como 1 para evitar division por cero.

#### Mejora transaccional deliberada

El Delphi confirma la cabecera/el borrado de lineas antes de procesar el nuevo detalle. Esto puede dejar una venta parcialmente grabada si posteriormente falla una linea.

La version Python ejecuta **cabecera + lineas + canon/regalos + totales en una unica transaccion**. Si cualquier parte falla se hace `rollback` completo. Esta es una mejora intencionada de integridad y no una copia literal del defecto transaccional del servidor antiguo.

### Valoracion de cabecera

Se ha portado el flujo `IVA_VENCAJ -> TOTALES_CABECERA -> VALORAR_VENCAJ`:

- agrupa `VENCUR` por `(PORIVA, PORREQ)` ignorando comentarios;
- convierte moneda cuando procede;
- respeta `CLI_REGIVA` exento/especial;
- aplica `CBV_PORDTO`;
- calcula cuatro bloques de base/IVA/recargo;
- calcula `CBV_TOTALS` y `CBV_TOTALD`;
- actualiza los totales de `VENCAJ`.

### `py_borrar_venta`

Migra `Borrar_Venta`:

- valida `EJERCI-NUMDOC`;
- comprueba si existe un semaforo `VENCAJ` activo;
- si esta bloqueada devuelve `Venta bloqueada` sin modificar datos;
- si esta libre elimina cabecera y lineas dentro de una transaccion.

Se conserva el orden SQL del Delphi: `DELETE VENCAJ` y despues `DELETE VENCUR`.

### Seguridad y robustez

Frente al servidor antiguo:

- no hay SQL concatenado con parametros del cliente MCP;
- las claves y valores se pasan parametrizados;
- los numeros recibidos se validan explicitamente;
- se hace `rollback` ante excepciones;
- no existe ningun proxy DataSnap.

### Pruebas

Se añade `tests/test_phase2c_sales.py`.

La bateria completa ejecuta **20 pruebas**, todas correctas, incluyendo:

- registro de las tres herramientas MCP;
- ausencia de herramientas `datasnap_*`;
- semaforo disponible/bloqueado;
- alta de venta y calculo de IVA/totales;
- canon externo mediante `ARTICULI`;
- reglas de regalo y cantidad gratuita;
- preservacion del comportamiento historico de linea sin articulo;
- borrado bloqueado;
- borrado efectivo de `VENCAJ`/`VENCUR`;
- `rollback` ante una linea numericamente invalida.

Ejecucion:

```bash
python -m unittest discover -s tests -v
```

### Estado tras Fase 2C

- Funciones DataSnap de referencia: **78**.
- Migradas a Python nativo: **57**.
- Pendientes: **21**.
- Cobertura nativa: **73,1 %**.
- Proxies DataSnap: **0**.
- Herramientas MCP registradas: **62**.

### Siguiente fase

Fase 2D - conversion de ventas/pedidos a documentos:

- `Grabar_Venta_Abierta_Pedido`;
- `Grabar_Albaran`.

---

## 5. Fase 2D - Documentos de venta

> _Fuente original: `FASE2D_DOCUMENTOS.md` (fusionado, fichero eliminado)._

### Objetivo

Portar a Python nativo las dos operaciones publicas DataSnap que conectan pedidos/ventas abiertas con documentos comerciales:

- `Grabar_Venta_Abierta_Pedido` -> `py_grabar_venta_abierta_pedido`
- `Grabar_Albaran` -> `py_grabar_albaran`

No se usa ningun proxy DataSnap. Toda la persistencia se realiza directamente contra Faro mediante la capa de base de datos Python del MCP.

### `py_grabar_venta_abierta_pedido`

Replica el flujo historico de `Grabar_Venta_Abierta_Pedido`:

1. Descompone `CODIGO_PEDIDO` con formato `EJERCICIO-SERIE-NUMERO`.
2. Recupera la cabecera `CABDOCV` del pedido `P` del centro indicado.
3. Transpone la cabecera a una nueva venta abierta `VENCAJ`.
4. Selecciona la serie como en Delphi:
   - `A`: serie de albaran del cliente o serie general de `A`.
   - `F`: serie configurada para `FC`.
   - resto: serie configurada para `T`.
5. Numera la venta abierta de forma segura.
6. Procesa las lineas indicadas por el cliente MCP.
7. Si la cantidad servida es parcial, crea el movimiento historico `S` y reduce la linea pendiente `P`.
8. Si se sirve la cantidad completa, la linea queda servida conforme al comportamiento del servidor original.
9. Genera la linea `VENCUR` enlazada al pedido origen.
10. Valora las lineas y recalcula la cabecera `VENCAJ`.
11. Mantiene/finaliza las cabeceras documentales asociadas.
12. Confirma todo en una unica transaccion.

#### Mejora de seguridad respecto al Delphi

El Delphi podia reutilizar el contenido anterior del registro de detalle si el numero de linea solicitado no existia. Python no replica ese defecto: una linea inexistente se incluye en `lineas_omitidas` y no genera movimientos espurios.

### `py_grabar_albaran`

Replica el flujo de `Grabar_Albaran` sobre `CABDOCV/DETMOV`:

1. Inicializa la cabecera del documento con fecha actual, empresa, centro y serie configurada.
2. Si se pasa `VENTA=EJERCICIO-NUMERO`, valida el semaforo de `VENCAJ`, carga los datos comerciales de la venta abierta y la consume dentro de la misma transaccion.
3. Si no se pasa venta, carga los datos directamente del cliente.
4. Numera e inserta `CABDOCV`.
5. Interpreta el protocolo historico de 14 campos:

   `CODART|DESCRI|CANTID|PREVEN|DTO1|DTO2|PORIVA|PORREQ|TIPPRE|UNIMED|PREIVA|PVP|EJEOFE|NUMOFE`

6. Crea cada linea en `DETMOV` y ejecuta la valoracion equivalente a `VALORAR_DETMOV`.
7. Genera las lineas de canon mediante `DETMOV`.
8. Genera regalos mediante `DETMOV` con descuento del 100 %.
9. Los movimientos de canon/regalo conservan el efecto de stock del DataSnap.
10. Recalcula impuestos, descuentos y totales de `CABDOCV`.
11. Comprueba el importe minimo de albaran (`CLIENI/IMPMI`).
12. Devuelve el identificador `TIPDOC-EJERCI-SERIE-NUMDOC` compatible con DataSnap.

### Atomicidad y concurrencia

Se ha reforzado un punto del original: cuando `Grabar_Albaran` consume una venta abierta, `VENCAJ/VENCUR` no se eliminan hasta que la nueva cabecera `CABDOCV` ha sido numerada e insertada correctamente. Esto evita perder o recuperar inconsistentemente la venta si hay una colision concurrente de numeracion.

Todas las operaciones de cada llamada se confirman con un unico `commit`; cualquier excepcion provoca `rollback`.

### Compatibilidad historica conservada

- La numeracion de lineas mantiene la peculiaridad historica de `NUMERAR_DETMOV` alrededor del valor 9999.
- La regla de regalo conserva el comportamiento del Delphi cuando la configuracion de regalo contiene descripcion adicional: la cantidad del regalo acaba siendo 0.
- La serie se obtiene usando los parametros configurados para empresa/centro, igual que en el servidor original.

### Dependencia interna cerrada en Fase 2E

`Grabar_Albaran` admite genericamente `TIPDOC='F'`. La Fase 2E ha portado y conectado al finalizador comun las dos rutinas que faltaban:

- el equivalente de `LIBFAC_GENERAR_EFECTOS`, con vencimientos `CABDOCVE`;
- `ACTUALIZA_RIESGO_CLIENTE`, apoyada en el calculo nativo de riesgo.

Por tanto, el flujo de factura creado desde `py_grabar_albaran` queda ya completo y comparte motor con `py_grabar_ticket_factura`.

### Pruebas de regresion

Tras la fase:

- **26/26 pruebas correctas**.
- **64 herramientas MCP nativas**.
- **0 proxies `datasnap_*`**.
- **59/78 funciones publicas DataSnap migradas (75,6 %)**.
- **19 funciones publicas pendientes**.

La Fase 2E completa posteriormente `Grabar_Ticket_Factura` y el motor compartido de efectos/riesgo; consultar `FASE2E_FACTURACION.md`.

---

## 6. Fase 2E - Facturacion

> _Fuente original: `FASE2E_FACTURACION.md` (fusionado, fichero eliminado)._

### Objetivo

Eliminar la dependencia de DataSnap para el cierre de tickets/facturas y completar las rutinas internas de facturacion que tambien utiliza `Grabar_Albaran` cuando se crea un documento `TIPDOC='F'`.

### Funcion publica migrada

| DataSnap | MCP Python | Estado |
| --- | --- | --- |
| `Grabar_Ticket_Factura` | `py_grabar_ticket_factura` | Migrada a Python nativo |

No se registra ningun proxy `datasnap_*` y el codigo Delphi no es necesario en tiempo de ejecucion.

### `py_grabar_ticket_factura`

El nuevo flujo reproduce las responsabilidades del metodo Delphi:

1. Inicializa `CABDOCV` con empresa, centro, caja, fecha, ejercicio y usuario.
2. Para facturas (`TIPDOC='F'`) obtiene la serie mediante el selector historico `FC` manteniendo `CBV_TIPDOC='F'`.
3. Puede partir de una venta abierta `VENCAJ`, respetando su semaforo y trasladando los datos comerciales a la nueva cabecera.
4. Si no existe venta abierta, obtiene los datos del cliente directamente.
5. Para factura directa usa el parametro `FPGCON` como forma de pago cuando esta configurado, igual que el servidor original.
6. Numera e inserta `CABDOCV`.
7. Procesa el protocolo historico de lineas de 14 campos y genera `DETMOV`.
8. Ejecuta valoracion, canon y regalos a traves del motor documental comun.
9. Registra los cobros de efectivo, tarjeta y otros en `OPECAJ`.
10. Si el importe entregado supera el total, el cambio reduce exclusivamente el movimiento efectivo; `CBV_COMREP` conserva el importe realmente entregado y `CBV_IMPCOB` el importe aplicado al documento.
11. Finaliza impuestos, descuentos y totales del documento.
12. Genera vencimientos `CABDOCVE` cuando corresponda.
13. Recalcula el riesgo del cliente.
14. Confirma la transaccion y, despues del `commit`, intenta la impresion TCP heredada.
15. Devuelve el identificador `TIPDOC-EJERCI-SERIE-NUMDOC` compatible con DataSnap.

### Rutinas internas portadas

#### `LIBFAC_GENERAR_EFECTOS`

Se ha portado el motor que borra/recrea los vencimientos de una factura:

- Lee `FORPAG` y sus lineas `FORPAGA`.
- Aplica los dias fijos de pago del cliente (`CLI_DIAPAG1..3`).
- Respeta meses sin vencimiento (`CLI_MESNOV1/2`).
- Calcula cada fecha mediante el equivalente Python de `SPFECHAS`.
- Divide `CBV_TOTALD` entre los efectos manteniendo el ajuste de redondeo en el primer efecto.
- Distribuye `CBV_IMPCOB` secuencialmente sobre los vencimientos.
- Marca como cancelados en fecha de factura los efectos cubiertos completamente por el cobro inicial.
- Conserva `TIPGES`, tipo documental y codigo de aceptacion de la forma de pago.

#### `SPFECHAS`

Se ha migrado la logica de fechas de vencimiento:

- Los plazos multiplos de 30 se tratan como meses naturales.
- Se conserva el comportamiento de fin de mes.
- Se aplican dias fijos de pago.
- Se desplazan fechas que caen en meses excluidos.
- Se soportan los modos siguiente, anterior y mas cercano (`MODOVE`).

Se corrige deliberadamente un typo del Delphi que validaba tres veces `DIAFP1`; Python valida cada dia fijo antes de usarlo.

#### Riesgo de cliente

Se han portado `RIESGO_ACTUAL` y `ACTUALIZA_RIESGO_CLIENTE`:

- Parte del riesgo fijo configurado en `CLIEN`.
- Incluye documentos pendientes segun el tipo de cliente.
- Incluye efectos pendientes `CABDOCVE`.
- Incluye facturas aplazadas y, cuando `RIEPED='S'`, pedidos pendientes.
- Respeta agrupaciones de subclientes (`CLI_AGRUPAC`).
- Convierte importes a la moneda del cliente mediante el motor de cambio ya disponible.
- Actualiza `CLI_RIESGOA`, `CLI_FECCOM`, `CLI_FECMOD` y `CLI_USUMOD`.

### Cierre del pendiente de Fase 2D

`_finalizar_documento_venta` es ahora el punto comun para documentos de venta. Por ello `py_grabar_albaran` con `TIPDOC='F'` ya ejecuta tambien:

- generacion/recalculo de `CABDOCVE`;
- distribucion del importe cobrado;
- actualizacion del riesgo del cliente.

No quedan dos motores de facturacion paralelos.

### Impresion

El envio historico al proceso de impresion TCP de Faro se conserva como integracion opcional y de mejor esfuerzo, ejecutada despues de confirmar la operacion de base de datos.

Variables opcionales:

- `FARO_DIR_PROGRAMAS`: directorio de los ejecutables/listados.
- `FARO_PRINT_HOST`: por defecto `localhost`.
- `FARO_PRINT_PORT`: por defecto `45000`.
- `FARO_PRINT_TIMEOUT`: por defecto `0.5` segundos.

Un fallo de consulta/configuracion/impresion no revierte un ticket o factura ya confirmados.

### Diferencias de implementacion deliberadas

- La numeracion de `OPECAJ` busca directamente la siguiente linea libre en vez de provocar una colision para reintentar; el resultado funcional es el mismo y se evita usar excepciones como mecanismo normal de control.
- La validacion de dias fijos de pago corrige el typo indicado de `SPFECHAS`.
- La grabacion del documento, lineas, cobros, efectos y riesgo se ejecuta con una transaccion coherente; cualquier error previo al `commit` provoca `rollback` completo.
- La impresion se aisla de la transaccion para impedir que una averia del proceso local de impresion convierta en error una venta ya persistida.

### Pruebas de regresion

La Fase 2E incorpora pruebas para:

- registro nativo de `py_grabar_ticket_factura` y ausencia de `datasnap_*`;
- reglas de fin de mes de `SPFECHAS`;
- division de vencimientos y distribucion de cobros;
- ejecucion de efectos y riesgo desde el finalizador de facturas;
- sobrepago y cambio en efectivo frente a tarjeta;
- selector de serie `FC` y forma de pago `FPGCON`.

Resultado global tras la fase: **32/32 pruebas correctas**.

### Estado tras la Fase 2E

- **60/78 funciones publicas DataSnap migradas**.
- **76,9 % de cobertura nativa**.
- **18 funciones publicas pendientes**.
- **65 herramientas MCP nativas**.
- **0 proxies DataSnap**.
- **0 dependencias de ejecucion de DataSnap**.

La siguiente fase es **2F - stock y logistica**, con `Trasvase_Centros` y `Stock_Coinfer_Articulo`.

---

## 7. Fase 2F - Logistica

> _Fuente original: `FASE2F_LOGISTICA.md` (fusionado, fichero eliminado)._

### Objetivo

Migrar a Python nativo las dos funciones publicas de DataSnap que quedaban en el bloque de stock/logistica:

- `Trasvase_Centros`
- `Stock_Coinfer_Articulo`

No se utilizan proxies DataSnap ni se requiere el servidor Delphi en ejecucion.

### 1. Trasvase_Centros -> py_trasvase_centros

#### Formato de entrada

Se conserva el protocolo historico de `TEXTO`:

```text
CODART|DESCRI|CANTID|UNIMED#CODART|DESCRI|CANTID|UNIMED#
```

El parser reproduce `PROCESAR_CADENA`: elimina espacios exteriores y deja de procesar cuando encuentra un segmento vacio.

#### Flujo migrado

1. Busca una cabecera `CABDOCR` de tipo `S` del dia para el centro origen y centro destino.
2. Si no existe, crea la salida con serie `SERIE_DOCUMENTO('R')`. Igual que en Delphi, la serie se obtiene con el centro configurado del servidor (`FARO_CENTRO`), no con `CENTROO`.
3. Cada linea se inserta en `DETMOVR` con cantidad negativa en el centro origen.
4. Si el articulo controla inventario (`ART_INDINV='S'`), actualiza `ARTICULE`.
5. `FINALIZAR_CABDOCR` se ha portado para el caso de trasvase:
   - si ya existia una entrada espejo (`CBR_NUMDOCE`), se anula completamente y se desacumula su stock;
   - se crea una nueva cabecera `CABDOCR` de tipo `E` en el centro destino;
   - se regeneran en ella todas las lineas acumuladas de la salida con signo contrario;
   - se actualiza `CBR_NUMDOCE` de la salida con el nuevo numero de entrada.
6. Todo el proceso se confirma en una unica transaccion; ante error se ejecuta rollback.

#### Compatibilidad historica

`FINALIZAR_CABDOCR` del Delphi no copiaba `DMR_UNIMED` a la linea espejo (`R_DMR_SAL`): la entrada generada en el centro destino quedaba siempre sin unidad de medida. Esto se replico igual en la primera version de la migracion, pero se ha corregido deliberadamente (ver `faro_mcp.FaroPhase1Service.transfer_centers`): ahora la entrada espejo copia la `DMR_UNIMED` real de la linea de salida correspondiente. Es una mejora intencional respecto al Delphi original, no una diferencia de comportamiento accidental; los documentos historicos generados antes de la correccion siguen teniendo la unidad de medida vacia en la entrada.

Tambien se mantiene que `TEXTO=''` devuelve exito sin crear movimientos.

Ademas, desde la revision de contrato v2 cada linea de `stock_trasvasar` solo exige `articulo` y `cantidad`; si `descripcion` o `unidad_medida` se dejan vacias, se autocompletan leyendo `ARTICUL` (ver `test_transfer_fills_missing_description_and_unit_from_article`).

### 2. Stock_Coinfer_Articulo -> py_stock_coinfer_articulo

Se conserva el comportamiento de la implementacion Delphi:

1. Solo procesa codigos de articulo de exactamente 9 caracteres.
2. Lee `PARAMETROS.PAR_VALOR` para `PAR_CODIGO='STOCKS'`.
3. Abre `<ruta>/Stocks.txt`.
4. Busca una linea cuyo primer campo separado por `;` coincida con `CODART`.
5. Descarta el segundo campo y devuelve el tercero como stock si es numerico.
6. Ante codigo invalido, parametro ausente, fichero inaccesible, articulo no encontrado o valor no numerico, devuelve `0` como hacia DataSnap.

La codificacion por defecto del fichero es `cp1252`, configurable con:

```text
FARO_STOCKS_ENCODING
```

### Herramientas MCP añadidas

- `py_trasvase_centros`
- `py_stock_coinfer_articulo`

### Pruebas

La fase añade 7 pruebas y la bateria completa queda en **39/39**:

- registro nativo de ambas herramientas;
- creacion de salida y entrada espejo;
- inversion correcta del signo de cantidades;
- regeneracion de una entrada espejo previa;
- compatibilidad del parser `PROCESAR_CADENA`;
- retorno sin escritura para texto vacio;
- lectura y tratamiento de errores de `Stocks.txt`.

### Estado tras la fase

- Funciones publicas DataSnap de referencia: **78**.
- Migradas a Python nativo: **62**.
- Pendientes: **16**.
- Cobertura nativa: **79,5 %**.
- Herramientas MCP registradas: **67**.
- Proxies DataSnap: **0**.

---

## 8. Fase 2G - Control horario

> _Fuente original: `FASE2G_CONTROL_HORARIO.md` (fusionado, fichero eliminado)._

### Objetivo

Migrar la funcion publica DataSnap `Comprobar_Usuario` a Python nativo, sin proxy ni dependencia de ejecucion del servidor Delphi.

### Funcion migrada

| DataSnap | MCP Python | Estado |
| --- | --- | --- |
| `Comprobar_Usuario` | `py_comprobar_usuario` | Migrada a Python nativo |

### Comportamiento portado

`py_comprobar_usuario` reproduce el flujo historico de Faro:

1. Recibe la clave de fichaje en texto original.
2. La transforma con el mismo algoritmo propietario `CRIPT(1, PASSWORD, '')` usado por Delphi.
3. Busca `USUAR.USU_NOMUSU` para la empresa y centro configurados en el MCP.
4. Lee el ultimo registro `HORAS` del usuario ordenado por `HOR_TIME DESC`.
5. Si no existe historial, crea una entrada `I` con tiempo acumulado 0.
6. Si el ultimo registro es `I`, crea una salida `F` y calcula `HOR_TIEMPO` como horas transcurridas.
7. Si el ultimo registro es distinto de `I` (normalmente `F`), crea una nueva entrada `I` con tiempo 0.
8. Inserta el registro en `HORAS` dentro de una transaccion.

`HOR_TIEMPO` se cuantiza a cuatro decimales para reproducir el tipo `CURRENCY` utilizado por `HORAS_UDM.pas`.

### Contrato de respuesta

Ademas del formato estructurado MCP, se conserva `datasnap_text`:

- Usuario no encontrado: `9|Usuario no Encontrado|||`
- Error al insertar: `9|Error al Grabar Registro|||`
- Correcto: `0||USUARIO|TIPO|ULTIMA_HORA`

La respuesta estructurada incluye:

- `ok`
- `usuario`
- `tipo` (`I`/`F`)
- `time`
- `previous_time`
- `worked_hours`
- `message`
- `datasnap_text`

### Diferencia deliberada respecto al Delphi

En el codigo original, cuando el usuario no tiene ningun registro previo, la variable local `ULTIMA_HORA` no se inicializa antes de llamar a `DateTimeToStr(ULTIMA_HORA)`. Ese valor es indeterminado.

En Python se resuelve de forma determinista:

- `previous_time = None`
- el ultimo campo de `datasnap_text` queda vacio.

Tambien se evita dejar una transaccion abierta cuando la clave no corresponde a ningun usuario.

### Pruebas

Se han añadido seis pruebas especificas:

1. Registro MCP nativo y ausencia de proxies DataSnap.
2. Clave inexistente sin escritura.
3. Primer fichaje como entrada `I`.
4. Entrada previa convertida en salida `F` con calculo de horas.
5. Salida previa convertida en nueva entrada `I`.
6. Rollback y mensaje historico ante fallo de insercion.

La bateria completa queda en **45/45 pruebas correctas**.

### Estado tras la fase

- API DataSnap de referencia: **78 funciones**.
- Migradas a Python nativo: **63**.
- Pendientes: **15**.
- Cobertura nativa: **80,8 %**.
- Herramientas MCP registradas: **68**.
- Proxies DataSnap: **0**.
- Dependencia de ejecucion de DataSnap: **0**.

---

## 9. Fase 2H - Documentos, ficheros y correo

> _Fuente original: `FASE2H_DOCUMENTOS_FICHEROS.md` (fusionado, fichero eliminado)._

### Objetivo

Eliminar las ultimas dependencias de DataSnap/FastReport del bloque documental publico y migrar sus nueve RPC a implementaciones Python nativas.

### Funciones migradas

| DataSnap | MCP Python | Implementacion |
| --- | --- | --- |
| `Enviar_Pedido` | `py_enviar_pedido` | Genera PDF nativo y lo envia por SMTP como adjunto |
| `Generar_PDF_Pedido` | `py_generar_pdf_pedido` | PDF desde `CABDOCV`, `DETMOV` y `CLIEN` |
| `Grabar_Fichero` | `py_grabar_fichero` | Escritura de `.TXT` bajo directorio Documentos |
| `GetImagenBannerAsJSON` | `py_get_imagen_banner_as_json` | Imagen `ARTICULI/IMAGE` en Base64 JSON |
| `GetPdfAsJSON` | `py_get_pdf_as_json` | PDF del pedido en Base64 JSON |
| `GetImagenBannerAsString` | `py_get_imagen_banner_as_string` | Base64 de la imagen |
| `ENVIAR_CORREO` | `py_enviar_correo` | `smtplib`/`EmailMessage` |
| `GetFichero` | `py_get_fichero` | Contenido binario en Base64 + metadatos |
| `GetFicheroAsString` | `py_get_fichero_as_string` | Base64 compatible con el retorno historico |

### Sustitucion de EDITAR_CABDOCV

En Delphi, `Enviar_Pedido` y `Generar_PDF_Pedido` no generaban documentos: construian un `TCopyDataMsgRecord` y enviaban `WM_COPYDATA` a un proceso GUI externo identificado por `MANEJADOR`. Ese proceso usaba `PedidoW.fr3`. El MCP no depende de ese proceso.

`py_generar_pdf_pedido` consulta el pedido directamente y crea `P-EJERCI-SERIE-NUMDOC.pdf` en `Documentos/Ventas/Pedidos`. `py_enviar_pedido` genera ese PDF y lo envia como adjunto por SMTP. Por tanto la capacidad queda migrada a Python.

**Diferencia visual conocida:** el PDF Python contiene cabecera, cliente, lineas, importes y observaciones, pero no intenta clonar pixel a pixel la plantilla FastReport `PedidoW.fr3`, que no forma parte del proyecto DataSnap entregado.

### Transporte binario MCP

Los RPC DataSnap que devolvian `TStream`/`TJSONArray` se representan en MCP mediante Base64 y metadatos (`path`, `size`, `mime_type`, `exists`). Esto evita depender de la serializacion privada `TDBXJSONTools.StreamToJSON`.

### Seguridad de ficheros

El DataSnap historico permitia que `GetFichero` recibiera una ruta arbitraria. No se reproduce esa exposicion en MCP: solo se permiten ficheros contenidos en las raices Faro configuradas (`main`, `Documentos`, `Imagenes`, pedidos PDF y, opcionalmente, `FARO_FILE_ROOTS`). Los intentos de `..`/escape son rechazados.

### Configuracion

Variables principales:

- `FARO_MAIN_DIR`
- `FARO_DOCUMENTS_DIR`
- `FARO_IMAGES_DIR`
- `FARO_PEDIDOS_PDF_DIR`
- `FARO_FILE_ROOTS` (opcional, separado por el separador de rutas del sistema)
- `FARO_TEXT_ENCODING` (por defecto `cp1252`)
- `FARO_SMTP_HOST`, `FARO_SMTP_PORT`
- `FARO_SMTP_USER`, `FARO_SMTP_PASSWORD`
- `FARO_SMTP_FROM`, `FARO_SMTP_FROM_NAME`
- `FARO_SMTP_STARTTLS`, `FARO_SMTP_SSL`
- `FARO_SMTP_TIMEOUT`
- `FARO_PEDIDO_EMAIL_BODY`

La generacion de PDF utiliza `reportlab`.

### Pruebas

La fase incorpora siete pruebas nuevas: registro nativo de herramientas, escritura/lectura Base64, proteccion de rutas, imagen normal/reducida, generacion/lectura de PDF, SMTP y envio de pedido con adjunto. La bateria completa queda en **52/52 pruebas correctas**.

---

## 10. Fase 2I - SQL legacy y utilidades

> _Fuente original: `FASE2I_SQL_UTILIDADES.md` (fusionado, fichero eliminado)._

### Objetivo

Cerrar las seis funciones publicas restantes de `TServerMethods1` sin volver a introducir ningun proxy ni dependencia runtime de DataSnap.

### Funciones migradas

| DataSnap | MCP Python | Estado |
| --- | --- | --- |
| `Busqueda_SQL` | `py_busqueda_sql` | Python nativo, SELECT/CTE de una sola sentencia |
| `Abrir_Consulta` | `py_abrir_consulta` | Python nativo, SELECT/CTE con serializacion `|/#` |
| `Ejecutar_SQL` | `py_ejecutar_sql` | Python nativo, escritura legacy protegida por configuracion |
| `InicializaConexion` | `py_inicializa_conexion` | Python nativo, verifica la conexion de la invocacion |
| `EchoString` | `py_echo_string` | Python nativo |
| `ReverseString` | `py_reverse_string` | Python nativo |

### Busqueda_SQL

El Delphi ejecutaba cualquier texto recibido mediante `PREPARAR_SQL` y devolvia `FieldByName(CAMPO).AsString` de la primera fila.

La version Python conserva el resultado y el nombre de campo, pero solo acepta un `SELECT`/CTE de lectura y una unica sentencia. Se rechazan comentarios, encadenamiento con `;` y palabras de escritura/DDL.

### Abrir_Consulta

Se conserva el formato historico de DataSnap:

- `|` separa campos.
- `#` separa registros.
- `ELIMINAR_CARACTERES` se reproduce eliminando `|` y `#` de cada valor.

Ademas de `datasnap_text`, el MCP devuelve `columns`, `items` y `count` como JSON estructurado.

Para impedir que una consulta accidentalmente enorme agote memoria, se limita la materializacion mediante `FARO_SQL_MAX_ROWS` (500 por defecto, maximo 5000).

### Ejecutar_SQL

Esta RPC historica era especialmente peligrosa porque permitia ejecutar SQL recibido por red. La migracion es nativa, pero **esta deshabilitada por defecto**.

Para habilitar compatibilidad legacy:

```powershell
$env:FARO_ALLOW_LEGACY_SQL_WRITE = "true"
```

Incluso habilitada, solo acepta una sentencia de los tipos:

- `INSERT`
- `UPDATE`
- `DELETE`
- `MERGE`
- `EXECUTE PROCEDURE`

Se rechazan DDL, control de transacciones, comentarios y multiples sentencias. Las nuevas funcionalidades del ERP deben implementarse mediante herramientas MCP tipadas y no mediante esta RPC.

### InicializaConexion

El DataSnap ejecutaba `INICIO_TRANSACCION` y dejaba la transaccion asociada a la sesion del servidor.

Ese comportamiento no debe copiarse literalmente en MCP, porque cada herramienta abre/cierra su propia conexion. `py_inicializa_conexion` comprueba la conectividad con Firebird mediante `RDB$DATABASE` y devuelve el mismo resultado logico verdadero sin dejar una transaccion huerfana.

### EchoString y ReverseString

Son equivalencias directas y no requieren conexion a la base de datos.

### Resultado

Con esta fase quedan migradas **78/78 funciones publicas de DataSnap**. DataSnap deja de ser una dependencia del servidor MCP y permanece unicamente como fuente historica de referencia.

---

## 11. Limpieza Fase 1 - Catalogo

> _Fuente original: `LIMPIEZA_FASE1_CATALOGO.md` (fusionado, fichero eliminado)._

### Objetivo

Reducir la superficie publica del servidor MCP sin perder funcionalidad interna ni romper la migracion DataSnap -> Python.

### Resultado

- Herramientas antes: **83**.
- Herramientas publicas despues: **67**.
- Herramientas internalizadas: **16**.
- Funciones DataSnap migradas a Python: **78/78 (100 %)**.
- Proxies DataSnap: **0**.
- Pruebas: **62/62**.
- Version del servidor: **1.2.0**.

### Herramientas internalizadas

#### Seguridad e infraestructura

- `py_seguridad_usuario`
- `py_conexion_usuario`
- `py_conexion_cliente`
- `py_cript`

Estas operaciones siguen implementadas para uso interno, pero no deben ser decisiones directas del modelo.

#### Mostrador / concurrencia

- `py_bloqueo_vencaj`

El bloqueo es una primitiva tecnica que deben ejecutar internamente las operaciones de venta.

#### Ficheros y comunicaciones genericas

- `py_grabar_fichero`
- `py_get_imagen_banner_as_string`
- `py_enviar_correo`
- `py_get_fichero`
- `py_get_fichero_as_string`

Se mantienen las operaciones de negocio `py_enviar_pedido`, `py_generar_pdf_pedido`, `py_get_imagen_banner_as_json` y `py_get_pdf_as_json`.

#### SQL y utilidades legacy

- `py_busqueda_sql`
- `py_abrir_consulta`
- `py_ejecutar_sql`
- `py_inicializa_conexion`
- `py_echo_string`
- `py_reverse_string`

Las implementaciones SQL continúan protegidas y disponibles internamente para diagnostico/compatibilidad, pero ya no forman parte del API MCP publico.

### Implementacion

`faro_mcp.py` define `INTERNAL_TOOL_NAMES`. El constructor de `McpServer` conserva el mapa completo de handlers y filtra ese conjunto al construir `self.tools`. `tool_definitions()` aplica el mismo filtro.

Por tanto:

1. Las funciones siguen existiendo en Python.
2. No aparecen en `tools/list`.
3. Una llamada directa por MCP devuelve `Herramienta desconocida`.
4. El resto de herramientas puede seguir reutilizando esas primitivas internamente.

### Siguiente fase propuesta

La Fase 2 de limpieza puede fusionar herramientas redundantes de consulta (`get_article`/`py_find_article`, stock, etiquetas, recuentos, faltas, ubicaciones, clientes, actividades, familias y detalle de pedido) y despues renombrar la API publica por dominios, eliminando progresivamente el prefijo `py_`.

---

## 12. Limpieza Fase 2 - Consolidacion

> _Fuente original: `LIMPIEZA_FASE2_CONSOLIDACION.md` (fusionado, fichero eliminado)._

### Objetivo

Reducir herramientas redundantes y presentar al modelo operaciones mas claras por dominio, sin borrar las implementaciones ya migradas y probadas.

### Resultado

- Herramientas publicas antes: **67**.
- Herramientas publicas despues: **55**.
- Reduccion adicional: **12 herramientas**.
- Nombres legacy consolidados/internalizados en esta fase: **23**.
- Nuevas fachadas publicas de dominio: **11**.
- Total de primitivas internas (Fase 1 + Fase 2): **39**.
- Funciones DataSnap migradas: **78/78 (100 %)**.
- Proxies DataSnap: **0**.
- Version del servidor: **1.3.0**.
- Pruebas de regresion: **70/70**.

### Consolidaciones realizadas

| Nueva herramienta publica | Sustituye a | Comportamiento |
| --- | --- | --- |
| `articulo_obtener` | `get_article`, `py_find_article`, `py_article_brand` | Resuelve codigo/EAN y devuelve ficha completa, resumen comercial y marca. |
| `stock_consultar` | `py_article_stock`, `py_article_stocks` | `centro` opcional: uno o todos los centros. |
| `familia_listar` | `py_list_families`, `py_list_web_families` | `tipo=erp/web`; `padre` selecciona nivel. |
| `etiqueta_listar` | `py_get_labels`, `py_list_labels` | `codart` opcional: articulo concreto o listado completo. |
| `recuento_listar` | `py_article_recount`, `py_list_recounts` | `centro` obligatorio; `codart` opcional. |
| `falta_listar` | `py_article_shortage`, `py_list_shortages` | `centro` obligatorio; `codart` opcional. |
| `articulo_ubicacion_guardar` | `py_grabar_ubicacion`, `py_grabar_ubicacion1` | `numero=1/2` selecciona ubicacion principal/secundaria. |
| `cliente_buscar` | `py_busqueda_cliente`, `py_consulta_clientes` | Clave exacta devuelve detalle; filtros devuelven listado. |
| `actividad_listar` | `py_lista_actividades`, `py_lista_actividades_representante` | Exige exactamente `codcli` o `codrep`. |
| `articulo_cambiar_tabla_precio` | `simulate_price_table_change`, `change_article_price_table` | `simular=true` por defecto; solo escribe con `simular=false`. |
| `pedido_detalle` | `py_detalle_pedido`, `py_detalle_pedido_preparacion` | `modo=normal/preparacion`. |

### Politica de compatibilidad

Las 23 herramientas sustituidas siguen implementadas en Python y forman parte de `INTERNAL_TOOL_NAMES`. Esto permite reutilizar codigo ya probado sin mantener dos APIs publicas que hagan practicamente lo mismo.

Como consecuencia:

1. No aparecen en `tools/list`.
2. No pueden invocarse con `tools/call`.
3. Sus funciones de servicio siguen disponibles para las nuevas fachadas.
4. La migracion DataSnap sigue al 100 %: solo se esta limpiando la superficie MCP.

### Decisiones de diseno

#### Articulos

`articulo_obtener` elimina tres llamadas frecuentes. Un codigo de barras se resuelve primero contra `ARTICULC`; despues se devuelve la fila completa de `ARTICUL`, el resumen comercial historico y la marca.

#### Stock y listas de almacen

Las variantes "un articulo" / "todos" se expresan ahora mediante parametros opcionales. Esto reduce la ambiguedad del selector de herramientas sin eliminar precision.

#### Clientes

`cliente_buscar` selecciona automaticamente la consulta exacta cuando solo recibe `codcli + subcli`. Si recibe filtros de busqueda utiliza el listado seguro y tipado.

#### Tabla de precios

La herramienta consolidada es deliberadamente conservadora: **simula por defecto**. Para escribir en `ARTICUL` debe recibirse `simular=false` de forma explicita.

#### Pedidos

El detalle de negocio y el detalle de picking siguen siendo dos implementaciones internas distintas, pero el modelo ve una unica herramienta con `modo` explicito.

### Continuacion

La normalizacion propuesta en esta fase se ha ejecutado en `LIMPIEZA_FASE3_NORMALIZACION_API.md`. Los 55 nombres publicos ya utilizan nombres de dominio, no existe ningun `py_*` publico y se han mantenido los mismos handlers y schemas.

---

## 13. Limpieza Fase 3 - Normalizacion del API publico

> _Fuente original: `LIMPIEZA_FASE3_NORMALIZACION_API.md` (fusionado, fichero eliminado)._

### Objetivo

Eliminar del catalogo MCP los nombres heredados de la migracion (`py_*` y nombres tecnicos en ingles) y publicar una API estable, predecible y agrupable por dominio de negocio.

La fase no cambia schemas ni logica de negocio. Los handlers Python ya probados siguen siendo los mismos; solo cambia el nombre publico y la descripcion presentada al cliente MCP.

### Resultado

- Herramientas publicas antes: **55**.
- Herramientas publicas despues: **55**.
- Herramientas renombradas: **44**.
- Fachadas de dominio ya normalizadas desde Fase 2 y conservadas: **11**.
- Nombres publicos que empiezan por `py_`: **0**.
- Proxies DataSnap: **0**.
- Funciones DataSnap migradas: **78/78 (100 %)**.
- Primitivas internas existentes: **39**.
- Alias publicos legacy conservados solo en implementacion: **44**.
- Version del servidor: **1.4.0**.
- Pruebas de regresion: **74/74**.

### Inventario publico por dominio

#### Articulos, catalogo y precios (12)

- `articulo_obtener`
- `articulo_buscar`
- `articulo_info_tecnica`
- `marca_listar`
- `familia_listar`
- `articulo_precio_oferta`
- `articulo_precio_cliente`
- `precio_tabla_listar`
- `articulo_cambiar_tabla_precio`
- `articulo_ubicacion_guardar`
- `articulo_ean_grabar`
- `articulo_imagen_obtener`

#### Compras y proveedores (3)

- `articulo_proveedor_listar`
- `articulo_ficha_compra`
- `entrada_pedidos_relacionados`

#### Stock y almacen (12)

- `stock_consultar`
- `stock_regularizar`
- `stock_trasvasar`
- `etiqueta_listar`
- `etiqueta_grabar`
- `etiqueta_borrar`
- `recuento_listar`
- `recuento_grabar`
- `recuento_borrar`
- `falta_listar`
- `falta_grabar`
- `falta_borrar`

#### Clientes y CRM (7)

- `cliente_buscar`
- `cliente_actualizar`
- `cliente_ultimas_ventas`
- `cliente_tipo_venta`
- `actividad_tipo_listar`
- `actividad_listar`
- `actividad_grabar`

#### Pedidos (14)

- `pedido_crear`
- `pedido_cerrar`
- `pedido_albaranar`
- `pedido_listar_cliente`
- `pedido_listar`
- `pedido_detalle`
- `pedido_linea_mover`
- `pedido_marcar_preparado`
- `pedido_finalizar`
- `pedido_situacion_actualizar`
- `pedido_retirada_actualizar`
- `pedido_enviar`
- `pedido_pdf_generar`
- `pedido_pdf_obtener`

#### Ventas y mostrador (5)

- `mostrador_venta_guardar`
- `mostrador_venta_borrar`
- `mostrador_pedido_cargar`
- `mostrador_cobrar`
- `venta_albaran_crear`

#### Control horario (1)

- `control_horario_fichar`

#### Integraciones (1)

- `integracion_coinfer_stock`

Total: **55 herramientas publicas**.

### Renombrados realizados

| Nombre anterior | Nombre publico actual |
| --- | --- |
| `list_price_tables` | `precio_tabla_listar` |
| `py_search_articles` | `articulo_buscar` |
| `py_article_technical_info` | `articulo_info_tecnica` |
| `py_list_brands` | `marca_listar` |
| `py_article_suppliers` | `articulo_proveedor_listar` |
| `py_article_purchase_sheet` | `articulo_ficha_compra` |
| `py_offer_pvp` | `articulo_precio_oferta` |
| `py_grabar_etiquetas` | `etiqueta_grabar` |
| `py_regularizar_stock` | `stock_regularizar` |
| `py_grabar_recuento` | `recuento_grabar` |
| `py_borrar_recuento` | `recuento_borrar` |
| `py_borrar_etiquetas` | `etiqueta_borrar` |
| `py_grabar_faltas` | `falta_grabar` |
| `py_borrar_faltas` | `falta_borrar` |
| `py_grabar_ean` | `articulo_ean_grabar` |
| `py_grabar_cliente` | `cliente_actualizar` |
| `py_tipos_actividad` | `actividad_tipo_listar` |
| `py_grabar_actividad` | `actividad_grabar` |
| `py_grabar_pedido_cliente` | `pedido_crear` |
| `py_cerrar_pedido` | `pedido_cerrar` |
| `py_grabar_albaran_pedido` | `pedido_albaranar` |
| `py_pedidos_cliente` | `pedido_listar_cliente` |
| `py_cuadro_pedidos` | `pedido_listar` |
| `py_mover_linea_pedido` | `pedido_linea_mover` |
| `py_grabar_pedido_preparado` | `pedido_marcar_preparado` |
| `py_finalizar_pedido` | `pedido_finalizar` |
| `py_precio_cliente_articulo` | `articulo_precio_cliente` |
| `py_ultimas_ventas_cliente` | `cliente_ultimas_ventas` |
| `py_tipo_venta_cliente` | `cliente_tipo_venta` |
| `py_grabar_situacion_pedido` | `pedido_situacion_actualizar` |
| `py_pedidos_cliente_entrada` | `entrada_pedidos_relacionados` |
| `py_grabar_retirado_referencia` | `pedido_retirada_actualizar` |
| `py_grabar_venta` | `mostrador_venta_guardar` |
| `py_borrar_venta` | `mostrador_venta_borrar` |
| `py_grabar_venta_abierta_pedido` | `mostrador_pedido_cargar` |
| `py_grabar_albaran` | `venta_albaran_crear` |
| `py_grabar_ticket_factura` | `mostrador_cobrar` |
| `py_trasvase_centros` | `stock_trasvasar` |
| `py_stock_coinfer_articulo` | `integracion_coinfer_stock` |
| `py_comprobar_usuario` | `control_horario_fichar` |
| `py_enviar_pedido` | `pedido_enviar` |
| `py_generar_pdf_pedido` | `pedido_pdf_generar` |
| `py_get_imagen_banner_as_json` | `articulo_imagen_obtener` |
| `py_get_pdf_as_json` | `pedido_pdf_obtener` |

### Compatibilidad interna

`PUBLIC_TOOL_RENAMES` mantiene la relacion entre nombre legacy y nombre canonico. El servidor registra el nombre canonico sobre el mismo handler probado, mientras que `LEGACY_PUBLIC_TOOL_NAMES` impide que el nombre antiguo aparezca o sea invocable por MCP.

Esto permite conservar el codigo de implementacion actual sin mantener dos contratos publicos simultaneos.

### Descripciones

Las descripciones de las 44 herramientas renombradas se han reescrito en terminos de negocio. El cliente MCP ya no ve textos como `Python directo ODBC` o `Replica ... DataSnap` para esas herramientas.

### Pruebas añadidas

`tests/test_cleanup_phase3_public_names.py` verifica:

1. que existen exactamente 55 herramientas publicas;
2. que `tools/list` y el dispatcher contienen exactamente los mismos nombres;
3. que no existe ningun nombre publico `py_*`;
4. que los 44 nombres nuevos estan publicados y sus equivalentes legacy no;
5. que una llamada directa usando un nombre legacy se rechaza;
6. que los dominios principales del ERP siguen representados en el catalogo.

---

## 14. Limpieza Fase 4 - Perfiles core y full

> _Fuente original: `LIMPIEZA_FASE4_PERFILES.md` (fusionado, fichero eliminado)._

### Objetivo

Reducir la superficie que ve la IA en el uso normal sin eliminar ninguna capacidad ya migrada. Las herramientas de uso habitual permanecen en el perfil `core`; las operaciones administrativas, helpers legacy e integraciones específicas se conservan en el perfil `full`.

### Resultado

- Perfil por defecto: `core`.
- Herramientas públicas `core`: **45**.
- Herramientas públicas `full`: **55**.
- Herramientas desplazadas a `full`: **10**.
- Funciones DataSnap migradas a Python: **78/78 (100 %)**.
- Proxies DataSnap: **0**.
- Nombres públicos `py_*`: **0**.
- Versión: **1.5.0**.
- Pruebas: **79/79**.

### Configuración

Por defecto no hay que configurar nada:

```text
FARO_MCP_TOOL_PROFILE=core
```

Para exponer también las herramientas avanzadas:

```text
FARO_MCP_TOOL_PROFILE=full
```

Cualquier valor desconocido se degrada de forma segura a `core`.

### Catálogo `core` por dominio

#### Artículos, catálogo y precios (7)

- `articulo_obtener`
- `articulo_buscar`
- `articulo_info_tecnica`
- `marca_listar`
- `familia_listar`
- `articulo_precio_cliente`
- `articulo_imagen_obtener`

#### Compras y proveedores (2)

- `articulo_proveedor_listar`
- `articulo_ficha_compra`

#### Stock y almacén (12)

- `stock_consultar`
- `stock_regularizar`
- `stock_trasvasar`
- `etiqueta_listar`
- `etiqueta_grabar`
- `etiqueta_borrar`
- `recuento_listar`
- `recuento_grabar`
- `recuento_borrar`
- `falta_listar`
- `falta_grabar`
- `falta_borrar`

#### Clientes y CRM (6)

- `cliente_buscar`
- `cliente_actualizar`
- `cliente_ultimas_ventas`
- `actividad_tipo_listar`
- `actividad_listar`
- `actividad_grabar`

#### Pedidos (12)

- `pedido_crear`
- `pedido_cerrar`
- `pedido_albaranar`
- `pedido_listar_cliente`
- `pedido_listar`
- `pedido_detalle`
- `pedido_linea_mover`
- `pedido_marcar_preparado`
- `pedido_finalizar`
- `pedido_enviar`
- `pedido_pdf_generar`
- `pedido_pdf_obtener`

#### Ventas y mostrador (5)

- `mostrador_venta_guardar`
- `mostrador_venta_borrar`
- `mostrador_pedido_cargar`
- `mostrador_cobrar`
- `venta_albaran_crear`

#### Control horario (1)

- `control_horario_fichar`

Total `core`: **45**.

### Herramientas avanzadas (`full`)

| Herramienta | Motivo para no mostrarla por defecto |
| --- | --- |
| `precio_tabla_listar` | Mantenimiento administrativo de precios. |
| `articulo_cambiar_tabla_precio` | Modifica política de precios del maestro de artículos. |
| `articulo_ubicacion_guardar` | Mantenimiento directo de datos logísticos del artículo. |
| `articulo_ean_grabar` | Mantenimiento directo de identificadores/EAN. |
| `articulo_precio_oferta` | Helper específico; para venta normal se prioriza `articulo_precio_cliente`. |
| `cliente_tipo_venta` | Regla/validación comercial auxiliar que normalmente debe consumir el flujo de venta. |
| `entrada_pedidos_relacionados` | Flujo legacy muy específico de entrada de mercancía. |
| `pedido_situacion_actualizar` | Actualización directa de un campo de estado de bajo nivel. |
| `pedido_retirada_actualizar` | Actualización directa de campos `retirado/referencia` de bajo nivel. |
| `integracion_coinfer_stock` | Integración específica de una instalación/fichero externo. |

Estas herramientas no están eliminadas. El perfil `full` publica exactamente las 55 herramientas canonizadas de la Fase 3.

### Seguridad de exposición

El filtrado se aplica en dos puntos:

1. `tools/list`: una herramienta avanzada no se anuncia en `core`.
2. `tools/call`: aunque un cliente conozca el nombre, el dispatcher no la registra en `core` y la llamada se rechaza como herramienta desconocida.

Esto evita que el perfil sea únicamente cosmético.

### Implementación

- `ADVANCED_PUBLIC_TOOL_NAMES` contiene las 10 herramientas avanzadas.
- `public_tool_profile()` normaliza `FARO_MCP_TOOL_PROFILE`.
- `McpServer` registra solo las herramientas permitidas por el perfil.
- `tool_definitions(profile)` genera el mismo catálogo que el dispatcher.

### Próxima limpieza recomendada

El bloque que todavía concentra más herramientas es `stock/almacén` (12). La siguiente fase puede consolidar las operaciones `listar/grabar/borrar` de etiquetas, recuentos y faltas en tres herramientas orientadas a recursos/acciones, reduciendo otras seis herramientas sin perder capacidad.


> Nota: la recomendacion de compactar stock/almacen fue ejecutada en la Fase 5. El estado actual es `core=39` y `full=49`; este documento conserva las cifras de la Fase 4 como historico.


> Estado posterior: la Fase 6 compacta tambien Pedidos. El estado actual es `core=37`, `full=47`, version `1.7.0`. Las cifras anteriores se conservan en este documento como historico de su fase.

---

## 15. Limpieza Fase 5 - Compactacion de stock/almacen

> _Fuente original: `LIMPIEZA_FASE5_ALMACEN.md` (fusionado, fichero eliminado)._

### Objetivo

Reducir decisiones redundantes para la IA en el dominio de almacén. Hasta la Fase 4, etiquetas, recuentos y faltas exponían tres herramientas independientes por recurso (`listar`, `grabar` y `borrar`). Esta fase conserva toda la lógica probada, pero publica una única herramienta por recurso con una acción explícita.

### Resultado

- Perfil `core`: **39 herramientas** (antes 45).
- Perfil `full`: **49 herramientas** (antes 55).
- Reducción neta: **6 herramientas** en ambos perfiles.
- Nuevas fachadas: **3**.
- Herramientas públicas sustituidas: **9**.
- Funciones DataSnap migradas: **78/78 (100 %)**.
- Proxies DataSnap: **0**.
- Versión: **1.6.0**.
- Pruebas: **85/85**.

### Nuevas herramientas

#### `etiqueta_gestion`

Acciones:

- `accion=listar`: con `codart` consulta un artículo; sin `codart` lista todas las etiquetas.
- `accion=grabar`: requiere `codart`, `descri`, `cantid`, `aumentar`, `modelo` e `imprimir`.
- `accion=borrar`: requiere `codart`.

Sustituye públicamente a:

- `etiqueta_listar`
- `etiqueta_grabar`
- `etiqueta_borrar`

#### `recuento_gestion`

`centro` es obligatorio para todas las acciones.

- `accion=listar`: con `codart` consulta un artículo; sin `codart` lista el recuento del centro.
- `accion=grabar`: requiere además `codart`, `descri`, `unimed`, `cantid` y `aumentar`.
- `accion=borrar`: requiere además `codart`.

Sustituye públicamente a:

- `recuento_listar`
- `recuento_grabar`
- `recuento_borrar`

#### `falta_gestion`

`centro` es obligatorio para todas las acciones.

- `accion=listar`: con `codart` consulta una falta; sin `codart` lista las faltas del centro.
- `accion=grabar`: requiere `codart`, `cantid` y `aumentar`. `proveedor` es opcional y puede ser `0` para conservar la resolución automática histórica.
- `accion=borrar`: requiere `codart` y `proveedor`.

La API pública usa un solo parámetro `proveedor`; internamente se adapta a los nombres históricos `codpro` (grabar) y `provee` (borrar).

Sustituye públicamente a:

- `falta_listar`
- `falta_grabar`
- `falta_borrar`

### Compatibilidad interna

No se elimina ninguna implementación. Las nueve herramientas anteriores dejan de estar en el catálogo MCP y `tools/call` las rechaza, pero sus handlers/servicios se mantienen para que las tres fachadas nuevas reutilicen la lógica ya validada.

`COMPACTED_STORAGE_TOOL_NAMES` contiene los nueve nombres públicos sustituidos y garantiza que no reaparezcan ni siquiera con `FARO_MCP_TOOL_PROFILE=full`.

### Catálogo `core` tras la Fase 5

#### Artículos, catálogo y precios (7)

- `articulo_obtener`
- `articulo_buscar`
- `articulo_info_tecnica`
- `marca_listar`
- `familia_listar`
- `articulo_precio_cliente`
- `articulo_imagen_obtener`

#### Compras y proveedores (2)

- `articulo_proveedor_listar`
- `articulo_ficha_compra`

#### Stock y almacén (6)

- `stock_consultar`
- `stock_regularizar`
- `stock_trasvasar`
- `etiqueta_gestion`
- `recuento_gestion`
- `falta_gestion`

#### Clientes y CRM (6)

- `cliente_buscar`
- `cliente_actualizar`
- `cliente_ultimas_ventas`
- `actividad_tipo_listar`
- `actividad_listar`
- `actividad_grabar`

#### Pedidos (12)

- `pedido_crear`
- `pedido_cerrar`
- `pedido_albaranar`
- `pedido_listar_cliente`
- `pedido_listar`
- `pedido_detalle`
- `pedido_linea_mover`
- `pedido_marcar_preparado`
- `pedido_finalizar`
- `pedido_enviar`
- `pedido_pdf_generar`
- `pedido_pdf_obtener`

#### Ventas y mostrador (5)

- `mostrador_venta_guardar`
- `mostrador_venta_borrar`
- `mostrador_pedido_cargar`
- `mostrador_cobrar`
- `venta_albaran_crear`

#### Control horario (1)

- `control_horario_fichar`

Total: **39 herramientas**.

### Perfil `full`

El perfil `full` añade las 10 herramientas avanzadas definidas en la Fase 4, por lo que queda en **49 herramientas**. Las nueve herramientas de almacén sustituidas no reaparecen en `full`: la compactación forma parte del contrato API definitivo, no es un filtro por perfil.


> Estado posterior: la Fase 6 compacta tambien Pedidos. El estado actual es `core=37`, `full=47`, version `1.7.0`. Las cifras anteriores se conservan en este documento como historico de su fase.

---

## 16. Limpieza Fase 6 - Compactacion de pedidos

> _Fuente original: `LIMPIEZA_FASE6_PEDIDOS.md` (fusionado, fichero eliminado)._

### Objetivo

Reducir el numero de herramientas del dominio Pedidos sin fusionar acciones transaccionales con efectos distintos. Las operaciones de escritura importantes (`crear`, `cerrar`, `albaranar`, `mover linea`, `marcar preparado` y `finalizar`) permanecen separadas para que el modelo de IA tenga una accion explicita y segura para cada cambio de estado.

### Resultado

- Perfil `core`: **37 herramientas** (antes 39).
- Perfil `full`: **47 herramientas** (antes 49).
- Herramientas de pedidos en `core`: **10** (antes 12).
- Version: **1.7.0**.
- Pruebas: **92/92**.
- DataSnap en runtime: **0 dependencias**.

### Consolidaciones

#### 1. `pedido_listar`

Absorbe las dos consultas publicas anteriores:

- `pedido_listar` (cuadro operativo / `Cuadro_Pedidos`).
- `pedido_listar_cliente` (historico del cliente / `Pedidos_Cliente`).

Contrato actual:

- `centro` es obligatorio.
- Sin `codcli` y `subcli`: devuelve el cuadro operativo del centro.
- Con `codcli` + `subcli`: devuelve los pedidos del cliente.
- Si solo se informa uno de los dos campos de cliente, la llamada se rechaza para evitar consultas ambiguas.

`pedido_listar_cliente` deja de publicarse por MCP.

#### 2. `pedido_pdf_gestion`

Sustituye:

- `pedido_pdf_generar`.
- `pedido_pdf_obtener`.

Acciones:

- `accion=generar`: genera/guarda el PDF y requiere `centro`.
- `accion=obtener`: recupera el PDF historico en Base64 y no requiere `centro`.

Las dos herramientas anteriores dejan de aparecer en `tools/list` y `tools/call` las rechaza.

### Herramientas de Pedidos que permanecen separadas

Se mantienen deliberadamente separadas:

1. `pedido_crear`
2. `pedido_cerrar`
3. `pedido_albaranar`
4. `pedido_listar`
5. `pedido_detalle`
6. `pedido_linea_mover`
7. `pedido_marcar_preparado`
8. `pedido_finalizar`
9. `pedido_pdf_gestion`
10. `pedido_enviar`

No se fusionan `pedido_cerrar`, `pedido_albaranar` o `pedido_finalizar` en una herramienta generica `pedido_accion`, porque son operaciones transaccionales distintas y una accion explicita reduce el riesgo de seleccionar por error un cambio irreversible.

### Correccion detectada durante la limpieza

La fachada `pedido_detalle` asumía que `order_lines()` y `order_preparation_lines()` devolvian un diccionario e intentaba expandir el resultado con `**`. Las implementaciones reales devuelven listas, de modo que la llamada podia fallar fuera de los mocks de prueba.

Ahora ambas variantes devuelven de forma estable:

```json
{
  "modo": "normal",
  "items": []
}
```

o:

```json
{
  "modo": "preparacion",
  "items": []
}
```

Se conserva compatibilidad interna si un adaptador devuelve un diccionario.

### Herramientas retiradas del contrato publico en esta fase

- `pedido_listar_cliente`
- `pedido_pdf_generar`
- `pedido_pdf_obtener`

Las implementaciones Python subyacentes siguen existiendo y son reutilizadas por las fachadas nuevas; no se ha eliminado funcionalidad del ERP.

### Perfil full

El perfil `full` conserva las operaciones avanzadas de pedidos definidas en la Fase 4:

- `pedido_situacion_actualizar`
- `pedido_retirada_actualizar`
- `entrada_pedidos_relacionados` (dominio compras/almacen)

La compactacion de esta fase es estructural: las tres herramientas sustituidas no reaparecen en `full`.

---

## 17. Limpieza Fase 7 - Clientes y CRM

> _Fuente original: `LIMPIEZA_FASE7_CRM.md` (fusionado, fichero eliminado)._

### Objetivo

Reducir el numero de herramientas MCP del dominio Clientes/CRM sin mezclar operaciones de negocio que conviene mantener explicitas.

### Cambios

Las tres herramientas de actividades comerciales:

- `actividad_tipo_listar`
- `actividad_listar`
- `actividad_grabar`

se sustituyen por una unica herramienta publica:

- `actividad_gestion`

La implementacion historica no se elimina. Los handlers anteriores siguen disponibles de forma interna y `actividad_gestion` enruta hacia ellos.

#### Contrato de `actividad_gestion`

- `accion=tipos`: lista los tipos de actividad comercial (`TIPACT`).
- `accion=listar`: exige exactamente uno de `codcli` o `codrep`; consulta las actividades del cliente o del representante.
- `accion=grabar`: exige `codcli`, `subcli`, `fecha`, `codact` y `codrep`; `texto` es opcional. Registra/actualiza la actividad usando la logica Python ya migrada.

### Decisiones de diseno

`cliente_ultimas_ventas` se mantiene separada: es una consulta comercial propia y no una operacion sobre el recurso actividad.

`cliente_buscar` y `cliente_actualizar` tambien permanecen separadas. Unificarlas obligaria a introducir un parametro de accion que mezclaria lectura y escritura del maestro de clientes sin una ganancia real de claridad.

### Superficie publica

- Perfil `core`: **35 herramientas** (antes 37).
- Perfil `full`: **45 herramientas** (antes 47).
- Reduccion: **2 herramientas** en ambos perfiles.
- Version: **1.8.0**.
- Pruebas: **99/99**.

Las herramientas sustituidas quedan en `COMPACTED_CRM_TOOL_NAMES`, no aparecen en `tools/list` y `tools/call` las rechaza.

---

## 18. Limpieza Fase 8 - Articulos, catalogo y compras

> _Fuente original: `LIMPIEZA_FASE8_ARTICULOS.md` (fusionado, fichero eliminado)._

### Objetivo

Reducir la fragmentacion del dominio de articulos sin mezclar operaciones de escritura ni convertir la consulta habitual de un articulo en una llamada pesada.

### Cambios

#### 1. `articulo_obtener` absorbe tecnica e imagen bajo demanda

Las herramientas publicas `articulo_info_tecnica` y `articulo_imagen_obtener` dejan de exponerse por separado.

`articulo_obtener` mantiene una respuesta ligera por defecto. El nuevo parametro `incluir` admite:

- `tecnica`: incorpora la informacion de `ARTCAR`.
- `imagen`: incorpora la imagen Base64.

Cuando se solicita imagen puede indicarse `tamano_imagen`.

Ejemplo conceptual:

```json
{
  "identificador": "ART001",
  "incluir": ["tecnica", "imagen"],
  "tamano_imagen": "P"
}
```

#### 2. Consulta de compra unificada

`articulo_proveedor_listar` y `articulo_ficha_compra` se sustituyen por:

`articulo_compra_consultar`

- Sin `codpro`: lista los proveedores asociados al articulo.
- Con `codpro`: devuelve la ficha de compra `ARTICULP` y el coste calculado para ese proveedor.

#### 3. Catalogos auxiliares unificados

`marca_listar` y `familia_listar` se sustituyen por:

`articulo_catalogo_listar`

El parametro `tipo` admite:

- `marcas`
- `familias`
- `familias_web`

`padre` se utiliza para navegar familias/subfamilias y familias web.

### Herramientas retiradas del catalogo

Las siguientes implementaciones se mantienen internamente, pero ya no aparecen en `tools/list` ni son invocables por `tools/call`:

- `articulo_info_tecnica`
- `articulo_imagen_obtener`
- `articulo_proveedor_listar`
- `articulo_ficha_compra`
- `marca_listar`
- `familia_listar`

### Herramientas nuevas / consolidadas

- `articulo_obtener` (ampliada)
- `articulo_compra_consultar`
- `articulo_catalogo_listar`

### Resultado

- Perfil `core`: 35 -> **31 herramientas**.
- Perfil `full`: 45 -> **41 herramientas**.
- Reduccion neta: **4 herramientas publicas**.
- No se elimina ninguna capacidad Python.
- Las operaciones administrativas de articulo siguen en `full`.
- Version del servidor: **1.9.0**.
- Pruebas: **107/107 correctas**.

---

## 19. Limpieza Fase 9 - Ventas y mostrador

> _Fuente original: `LIMPIEZA_FASE9_VENTAS_MOSTRADOR.md` (fusionado, fichero eliminado)._

### Objetivo

Reducir la fragmentacion del ciclo de venta abierta sin mezclar operaciones con efectos fiscales o contables diferentes.

### Cambios de API

Tres herramientas que operaban sobre la venta abierta de mostrador dejan de publicarse por separado:

- `mostrador_venta_guardar`
- `mostrador_venta_borrar`
- `mostrador_pedido_cargar`

Se sustituyen por:

#### `mostrador_venta_gestion`

Admite `accion`:

- `guardar`: crea o modifica `VENCAJ/VENCUR`. Requiere `codcli`, `subcli`, `texto`, `tipdoc` y `usuario`; `venta` vacia crea una nueva.
- `borrar`: elimina una venta abierta. Requiere `venta` (`EJERCI-NUMDOC`).
- `cargar_pedido`: sirve cantidades de un pedido y crea la venta abierta. Requiere `centro`, `codigo_pedido`, `tipdoc` y `texto`.

Las tres implementaciones anteriores continúan como primitivas internas y la fachada solo enruta a la logica ya probada.

### Operaciones que permanecen separadas

#### `mostrador_cobrar`

No se fusiona con `mostrador_venta_gestion`. Cobrar genera ticket/factura, registra `OPECAJ`, puede generar `CABDOCVE`, actualiza riesgo y puede disparar impresion. Es una frontera transaccional/fiscal suficientemente importante para requerir una herramienta explicita.

#### `venta_documento_crear`

Sustituye el nombre `venta_albaran_crear`. La implementacion historica `Grabar_Albaran` admite distintos `tipdoc` y puede finalizar tambien factura, por lo que el nombre anterior era demasiado restrictivo. Continúa separada del mostrador porque crea directamente `CABDOCV/DETMOV` desde lineas o desde una venta abierta.

### Resultado

Ventas/Mostrador queda con tres herramientas publicas:

1. `mostrador_venta_gestion`
2. `mostrador_cobrar`
3. `venta_documento_crear`

El catalogo queda en:

- `core`: **29 herramientas** (antes 31).
- `full`: **39 herramientas** (antes 41).
- Version: **2.0.0**.
- Pruebas: **114/114**.

### Inventario `core` por dominio

- Articulos/catalogo/precios: 5
- Clientes/CRM: 4
- Stock/almacen: 6
- Pedidos: 10
- Ventas/Mostrador: 3
- Control horario: 1
- Total: **29**

No se elimina ninguna capacidad migrada de DataSnap y no se introduce ninguna dependencia de runtime con Delphi/DataSnap.

---

## 20. Limpieza Fase 10 - Perfiles finales y congelacion del contrato

> _Fuente original: `LIMPIEZA_FASE10_PERFILES_CONTRATO.md` (fusionado, fichero eliminado)._

### Objetivo

Cerrar la fase de reduccion del catalogo definiendo de forma explicita que herramientas puede ver cada tipo de agente y congelar el API publico estable del MCP Faro.

Desde esta fase una herramienta no se publica por el simple hecho de existir en `faro_mcp.py`. El servidor usa allowlists explicitas. Cualquier nueva herramienta debera asignarse conscientemente a uno de los perfiles antes de poder aparecer en `tools/list` o ejecutarse mediante `tools/call`.

### Perfiles

#### `core` - 29 herramientas

Perfil por defecto. Contiene las operaciones habituales de negocio y es el recomendado para asistentes/agentes generales del ERP.

#### `admin` - 38 herramientas

Incluye las 29 de `core` y 9 operaciones administrativas/avanzadas. No incluye integraciones especificas de instalaciones externas.

#### `integrations` - 30 herramientas

Incluye las 29 de `core` y las herramientas de integracion externa. Actualmente incorpora exclusivamente Coinfer.

#### `all` - 39 herramientas

Union de `core + admin + integrations`. Pensado para diagnostico, pruebas o agentes expresamente autorizados para disponer de toda la superficie canonica.

`full` se conserva como alias de compatibilidad y se normaliza internamente a `all`. No debe utilizarse en configuraciones nuevas.

### Contrato congelado `core`

| Dominio | Herramienta | Tipo | Decision |
| --- | --- | --- | --- |
| Articulos | `articulo_buscar` | Lectura | Core |
| Articulos | `articulo_obtener` | Lectura | Core; tecnica/imagen solo bajo demanda |
| Compras | `articulo_compra_consultar` | Lectura | Core; proveedor/ficha compra |
| Catalogo | `articulo_catalogo_listar` | Lectura | Core; marcas/familias |
| Precios | `articulo_precio_cliente` | Lectura/calculo | Core; precio efectivo comercial |
| Clientes | `cliente_buscar` | Lectura | Core |
| Clientes | `cliente_actualizar` | Escritura | Core; mantenimiento operativo habitual |
| Clientes | `cliente_ultimas_ventas` | Lectura | Core |
| CRM | `actividad_gestion` | Mixta | Core; tipos/listado/grabacion |
| Stock | `stock_consultar` | Lectura | Core |
| Stock | `stock_regularizar` | Escritura | Core; operacion habitual de almacen |
| Stock | `stock_trasvasar` | Escritura | Core; movimiento entre centros |
| Almacen | `etiqueta_gestion` | Mixta | Core |
| Almacen | `recuento_gestion` | Mixta | Core |
| Almacen | `falta_gestion` | Mixta | Core |
| Pedidos | `pedido_crear` | Escritura | Core |
| Pedidos | `pedido_cerrar` | Escritura | Core; se mantiene separada por efecto propio |
| Pedidos | `pedido_albaranar` | Escritura | Core; frontera documental explicita |
| Pedidos | `pedido_listar` | Lectura | Core |
| Pedidos | `pedido_detalle` | Lectura | Core |
| Pedidos | `pedido_linea_mover` | Escritura | Core; picking/preparacion |
| Pedidos | `pedido_marcar_preparado` | Escritura | Core |
| Pedidos | `pedido_finalizar` | Escritura | Core; no se fusiona con cerrar/albaranar |
| Pedidos | `pedido_pdf_gestion` | Mixta/fichero | Core; generar/obtener documento |
| Pedidos | `pedido_enviar` | Efecto externo | Core; operacion de negocio explicita |
| Mostrador | `mostrador_venta_gestion` | Escritura | Core; venta abierta guardar/borrar/cargar pedido |
| Mostrador | `mostrador_cobrar` | Escritura critica | Core; caja/fiscal, separada deliberadamente |
| Ventas | `venta_documento_crear` | Escritura critica | Core; documento comercial explicito |
| Control horario | `control_horario_fichar` | Escritura | Core |

No se compactan mas operaciones de pedidos o caja en esta fase. La reduccion adicional haria el contrato mas ambiguo y aumentaria el riesgo de seleccionar una accion con efectos diferentes.

### Herramientas `admin`

Las siguientes 9 se anaden sobre `core`:

| Herramienta | Motivo para no estar en `core` |
| --- | --- |
| `precio_tabla_listar` | Mantenimiento/configuracion de precios |
| `articulo_cambiar_tabla_precio` | Modifica politica de precios del articulo |
| `articulo_ubicacion_guardar` | Mantenimiento de maestro/almacen |
| `articulo_ean_grabar` | Mantenimiento de codigos EAN |
| `articulo_precio_oferta` | Helper comercial especifico; el precio efectivo esta en core |
| `cliente_tipo_venta` | Regla interna/comercial avanzada |
| `entrada_pedidos_relacionados` | Consulta operativa especializada de entradas |
| `pedido_situacion_actualizar` | Actualizacion de estado de bajo nivel |
| `pedido_retirada_actualizar` | Actualizacion especializada de retirada/referencia |

### Herramientas `integrations`

Actualmente solo anade:

- `integracion_coinfer_stock`: lectura de la fuente externa `Stocks.txt` configurada para Coinfer.

La separacion evita que una instalacion que no usa Coinfer anuncie al modelo una herramienta irrelevante.

### Implementacion

Se incorporan las constantes:

- `CORE_PUBLIC_TOOL_NAMES`
- `ADMIN_PUBLIC_TOOL_NAMES`
- `INTEGRATION_PUBLIC_TOOL_NAMES`
- `ALL_PUBLIC_TOOL_NAMES`

`public_tool_names_for_profile()` devuelve la allowlist exacta para el perfil activo.

Tanto el dispatcher (`McpServer.tools`) como `tool_definitions()` se construyen contra esa misma allowlist. Si falta un handler o un schema perteneciente al contrato, el servidor falla de forma explicita con `Contrato MCP incompleto`, evitando publicar un API parcialmente roto.

### Compatibilidad

- `FARO_MCP_TOOL_PROFILE=core` -> 29 herramientas.
- `FARO_MCP_TOOL_PROFILE=admin` -> 38 herramientas.
- `FARO_MCP_TOOL_PROFILE=integrations` -> 30 herramientas.
- `FARO_MCP_TOOL_PROFILE=all` -> 39 herramientas.
- `FARO_MCP_TOOL_PROFILE=full` -> alias compatible de `all`.
- Un valor desconocido -> `core`.

### Resultado

- Version MCP: **2.1.0**.
- Contrato `core`: **29 herramientas congeladas**.
- Perfil `admin`: **38 herramientas**.
- Perfil `integrations`: **30 herramientas**.
- Perfil `all`: **39 herramientas**.
- DataSnap: **78/78 migradas**.
- Proxies DataSnap: **0**.
- Pruebas: **122/122**.

---

## 21. Limpieza Fase 11 - Refactor interno y eliminacion de aliases

> _Fuente original: `LIMPIEZA_FASE11_INTERNO.md` (fusionado, fichero eliminado)._

### Objetivo

Mantener **sin cambios** el contrato MCP congelado en la Fase 10 y limpiar la implementacion interna que aun arrastraba nombres de migracion, aliases y wrappers ya innecesarios.

### Resultado

- Version del servidor: **2.2.0**.
- Perfil `core`: **29 herramientas**.
- Perfil `admin`: **38 herramientas**.
- Perfil `integrations`: **30 herramientas**.
- Perfil `all`: **39 herramientas**.
- `full` continua como alias de compatibilidad de `all`.
- **127/127 pruebas** correctas.
- Los 39 schemas de `all` son identicos a los publicados en la Fase 10.

### Cambios internos

#### 1. Registro directo de herramientas canonicas

Se elimina la construccion historica `nombre antiguo -> alias canonico`. `McpServer` registra directamente las herramientas definitivas:

```text
articulo_buscar -> tool_articulo_buscar
pedido_crear -> tool_pedido_crear
mostrador_cobrar -> tool_mostrador_cobrar
...
```

Cada herramienta publica tiene ahora un handler cuyo nombre coincide con el contrato MCP: `tool_<nombre_publico>`.

#### 2. Eliminacion de infraestructura de aliases

Se eliminan del runtime:

- `PUBLIC_TOOL_RENAMES`;
- `PUBLIC_TOOL_DESCRIPTIONS` usado para renombrado dinamico;
- `LEGACY_PUBLIC_TOOL_NAMES`;
- `INTERNAL_TOOL_NAMES` como filtro de publicacion;
- los conjuntos `COMPACTED_*_TOOL_NAMES` usados para ocultar versiones sustituidas.

La seguridad de exposicion depende unicamente de las allowlists de Fase 10.

#### 3. Schemas canonicos directos

`tool_definitions()` deja de generar schemas a partir de nombres anteriores. Los **39 schemas canonicos** estan definidos directamente en `PUBLIC_TOOL_DEFINITIONS` y se filtran por perfil.

La Fase 11 incluye una prueba SHA-256 sobre el catalogo `all` para detectar cambios accidentales respecto a la Fase 10.

#### 4. Reduccion de wrappers

`McpServer` pasa de:

- **107 metodos** totales / **103 wrappers de herramienta** en Fase 10

a:

- **58 metodos** totales / **54 handlers/helpers de herramienta** en Fase 11.

Se eliminan **49 wrappers muertos** que solo existian para compatibilidad con etapas anteriores.

El fichero `faro_mcp.py` baja aproximadamente de **10.183 a 8.684 lineas**.

#### 5. Nombres internos limpios

No quedan metodos `tool_py_*` en el runtime. Las operaciones internas reutilizadas por fachadas usan nombres privados orientados al negocio, por ejemplo:

- `_tool_etiqueta_grabar`;
- `_tool_recuento_borrar`;
- `_tool_actividad_grabar`;
- `_tool_mostrador_venta_guardar`.

Las utilidades SQL no expuestas se renombran como operaciones internas (`internal_*`) y la opcion de escritura pasa a `FARO_ALLOW_INTERNAL_SQL_WRITE`.

#### 6. Compatibilidad de respuestas

Se mantienen algunos campos `datasnap_text` / `datasnap_value` en resultados internos o historicos porque forman parte del comportamiento observable que ya estaba probado. En esta fase no se cambia el formato de respuesta; esa normalizacion corresponde a una fase posterior.

### Contrato MCP

La superficie publica **no cambia** respecto a Fase 10. Esto se comprueba mediante:

- conteos exactos por perfil;
- igualdad de nombres handler/schema;
- hash del conjunto completo de schemas;
- rechazo de nombres no canonicos;
- bateria completa de regresion.

### Siguiente fase sugerida

Fase 12: normalizacion de parametros, respuestas y errores. Esa fase si debe tratarse como una evolucion del contrato y versionarse cuidadosamente.

---

## 22. Limpieza Fase 12 - Contrato MCP v2

> _Fuente original: `LIMPIEZA_FASE12_CONTRATO_V2.md` (fusionado, fichero eliminado)._

### Objetivo

Normalizar el borde MCP sin modificar la logica transaccional ya migrada y probada. La Fase 12 mantiene exactamente los mismos nombres de herramientas y perfiles de Fase 10/11, pero cambia de forma controlada el **contrato de argumentos y resultados** para que sea mas legible, tipado y seguro para un agente.

### Versiones

- Servidor: **2.3.0**.
- Contrato publico: **2.0**.
- `core`: **29 herramientas**.
- `admin`: **38 herramientas**.
- `integrations`: **30 herramientas**.
- `all`: **39 herramientas**.
- `full`: alias de compatibilidad de `all`.
- Pruebas: **141/141**.

### 1. Parametros publicos orientados al dominio

Las abreviaturas procedentes de la base de datos dejan de exponerse en los schemas MCP. Ejemplos:

| Anterior | Contrato v2 |
| --- | --- |
| `codart` | `articulo` |
| `codcli` | `cliente` |
| `subcli` | `subcliente` |
| `codrep` | `representante` |
| `codpro` | `proveedor` |
| `codact` | `tipo_actividad` |
| `tipdoc` | `tipo_documento` |
| `ejerci` | `ejercicio` |
| `numdoc` | `numero` |
| `cantid` | `cantidad` |
| `descri` | `descripcion` |
| `unimed` | `unidad_medida` |
| `centroo` | `centro_origen` |
| `centrod` | `centro_destino` |
| `ubi_origen` | `ubicacion_origen` |
| `ubi_destino` | `ubicacion_destino` |
| `situac` | `situacion` |
| `password` | `contrasena` |
| `limit` | `limite` |
| `order_by` | `ordenar_por` |
| `codart_prefix` | `prefijo_articulo` |
| `new_table` | `tabla_nueva` |

La traduccion se realiza exclusivamente en el borde mediante `translate_public_arguments()`. Los servicios internos mantienen sus firmas actuales y, por tanto, no se reescribe la logica de negocio probada.

Todos los `inputSchema` publicos usan `additionalProperties=false`. Una clave no anunciada se rechaza tambien en runtime aunque el cliente MCP no valide JSON Schema.

### 2. Fin de los protocolos `|/#` en el contrato publico

El modelo ya no tiene que construir cadenas con separadores historicos. Las siguientes herramientas aceptan estructuras JSON y el servidor las serializa internamente al formato que entiende el motor migrado:

#### `cliente_actualizar`

Recibe `datos` como objeto con `cliente`, `subcliente`, `nombre`, `razon_social`, `domicilio`, `codigo_postal`, `poblacion`, `telefono`, `email` y `cif`.

#### `pedido_crear`

Recibe `lineas` como array de objetos con:

- `articulo`;
- `descripcion` opcional;
- `cantidad`;
- `precio`;
- `descuento` opcional.

`comentarios` es ahora un array de strings y `crear_presupuesto` un booleano. El valor tecnico historico `urgente='R'` deja de formar parte del API publico.

#### `pedido_albaranar`

Recibe `lineas` como objetos `{linea, cantidad}`. Los campos historicos de articulo/descripcion que el servidor Delphi recibia pero no utilizaba ya no se exponen.

#### `stock_trasvasar`

Recibe `lineas` como objetos `{articulo, descripcion, cantidad, unidad_medida}`.

#### Ventas / mostrador

`mostrador_cobrar`, `venta_documento_crear` y `mostrador_venta_gestion(accion=guardar)` reciben lineas estructuradas con precio, descuentos, IVA, recargo, unidad, PVP y oferta. `mostrador_venta_gestion(accion=cargar_pedido)` usa `{linea, cantidad}`.

### 3. Orden de articulos sin nombres fisicos de BD

`articulo_buscar.ordenar_por` deja de admitir columnas como `ART_DESCRI` y publica valores funcionales:

- `codigo`;
- `descripcion`;
- `unidad_medida`;
- `coste`;
- `precio4`;
- `pvp`;
- `proveedor`;
- `nombre_proveedor`.

La capa de borde traduce estos valores a la columna permitida correspondiente.

### 4. Respuesta uniforme

Toda llamada MCP valida devuelve ahora un sobre comun.

Exito:

```json
{
  "ok": true,
  "data": {},
  "warnings": [],
  "meta": {
    "tool": "stock_consultar",
    "profile": "core",
    "contract_version": "2.0"
  }
}
```

Error de negocio/validacion:

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "..."
  },
  "warnings": [],
  "meta": {
    "tool": "stock_consultar",
    "profile": "core",
    "contract_version": "2.0"
  }
}
```

Los resultados historicos con `ok=false` se convierten a `BUSINESS_ERROR`. Las excepciones se clasifican en `INVALID_ARGUMENT`, `NOT_FOUND`, `RESOURCE_LOCKED`, `FARO_ERROR` o `INTERNAL_ERROR`.

En `tools/call`, los errores de ejecucion de herramienta se devuelven con `result.isError=true`, reservando el error JSON-RPC exterior para errores de protocolo o nombres de herramientas no disponibles en el perfil.

### 5. Eliminacion de artefactos DataSnap del borde

`datasnap_text` y `datasnap_value` pueden seguir existiendo dentro de algunas funciones internas para comprobar fidelidad historica y mantener las pruebas de migracion, pero se eliminan recursivamente de cualquier respuesta publicada por MCP.

La API publica ya no depende de esos campos.

### 6. Compatibilidad

- Los **nombres de las herramientas no cambian** respecto a Fase 10/11.
- Los perfiles y sus conteos tampoco cambian.
- El contrato de argumentos si evoluciona y por eso se versiona como **2.0**.
- Los handlers internos siguen aceptando las firmas historicas; la traduccion solo ocurre cuando la llamada entra por MCP.
- Las pruebas de migracion directa de los servicios conservan los resultados historicos para verificar equivalencia funcional.

### Resultado

La Fase 12 separa definitivamente dos niveles:

1. **Contrato MCP limpio**: nombres de negocio, JSON estructurado, errores y respuestas uniformes.
2. **Motor Faro interno**: puede conservar formatos heredados donde ya estan probados, sin exponerlos al agente.

La siguiente fase recomendada es Fase 13: permisos por herramienta/accion, confirmacion de operaciones criticas y auditoria de escrituras.

---

## 23. Limpieza Fase 13 - Seguridad, permisos y auditoria

> _Fuente original: `LIMPIEZA_FASE13_SEGURIDAD_AUDITORIA.md` (fusionado, fichero eliminado)._

### Objetivo

La Fase 13 endurece el borde MCP sin modificar el contrato publico de herramientas de la Fase 12. Los nombres, perfiles y schemas permanecen congelados (`core=29`, `admin=38`, `integrations=30`, `all=39`), mientras que `tools/call` incorpora autorizacion por nivel de riesgo y auditoria obligatoria de mutaciones.

Version del servidor: **2.4.0**. Contrato publico: **2.0**.

### Niveles de acceso

`FARO_MCP_ACCESS_LEVEL` admite:

- `read`: solo operaciones de lectura. Es el valor por defecto.
- `write`: lectura + escrituras ordinarias.
- `critical`: lectura + escritura + operaciones criticas.

Se aceptan `readonly` como alias de `read`, `rw` como alias de `write` y `admin`/`full` como alias de `critical`. Un valor desconocido cae en `read`.

El perfil funcional (`FARO_MCP_TOOL_PROFILE`) y el permiso de ejecucion son conceptos independientes: el perfil decide que herramientas se publican; el nivel de acceso decide si una invocacion concreta puede ejecutarse.

### Clasificacion maxima de las 39 herramientas

La clasificacion indicada es el riesgo maximo de cada herramienta. Las fachadas con varias acciones pueden rebajar el riesgo efectivo cuando la accion es de solo lectura.

#### Lectura (15)

| Herramienta | Riesgo maximo |
| --- | --- |
| `articulo_buscar` | read |
| `articulo_catalogo_listar` | read |
| `articulo_compra_consultar` | read |
| `articulo_obtener` | read |
| `articulo_precio_cliente` | read |
| `articulo_precio_oferta` | read |
| `cliente_buscar` | read |
| `cliente_tipo_venta` | read |
| `cliente_ultimas_ventas` | read |
| `entrada_pedidos_relacionados` | read |
| `integracion_coinfer_stock` | read |
| `pedido_detalle` | read |
| `pedido_listar` | read |
| `precio_tabla_listar` | read |
| `stock_consultar` | read |

#### Escritura (14)

| Herramienta | Riesgo maximo |
| --- | --- |
| `actividad_gestion` | write |
| `articulo_ean_grabar` | write |
| `articulo_ubicacion_guardar` | write |
| `cliente_actualizar` | write |
| `control_horario_fichar` | write |
| `etiqueta_gestion` | write |
| `falta_gestion` | write |
| `pedido_crear` | write |
| `pedido_linea_mover` | write |
| `pedido_marcar_preparado` | write |
| `pedido_pdf_gestion` | write |
| `pedido_retirada_actualizar` | write |
| `pedido_situacion_actualizar` | write |
| `recuento_gestion` | write |

#### Criticas (10)

| Herramienta | Riesgo maximo |
| --- | --- |
| `articulo_cambiar_tabla_precio` | critical |
| `mostrador_cobrar` | critical |
| `mostrador_venta_gestion` | critical |
| `pedido_albaranar` | critical |
| `pedido_cerrar` | critical |
| `pedido_enviar` | critical |
| `pedido_finalizar` | critical |
| `stock_regularizar` | critical |
| `stock_trasvasar` | critical |
| `venta_documento_crear` | critical |

### Herramientas de riesgo dinamico

- `actividad_gestion`: `tipos/listar` = `read`; `grabar` = `write`.
- `etiqueta_gestion`, `recuento_gestion`, `falta_gestion`: `listar` = `read`; `grabar/borrar` = `write`.
- `pedido_pdf_gestion`: `obtener` = `read`; `generar` = `write`.
- `articulo_cambiar_tabla_precio`: `simular=true` (valor por defecto) = `read`; `simular=false` = `critical`.
- `mostrador_venta_gestion`: `guardar/cargar_pedido` = `write`; `borrar` = `critical`. Una accion desconocida se trata como critica (fail closed).

### Auditoria

Todas las invocaciones con riesgo efectivo `write` o `critical` se auditan. Las lecturas pueden incluirse con `FARO_MCP_AUDIT_READS=true`.

Variables:

```text
FARO_MCP_ACTOR
FARO_MCP_CLIENT_ID
FARO_MCP_AUDIT_LOG
FARO_MCP_AUDIT_READS=false
FARO_MCP_AUDIT_REQUIRED=true
```

Si no se indica `FARO_MCP_AUDIT_LOG`, se usa `<FARO_MAIN_DIR>/logs/faro_mcp_audit.jsonl`. `actor` usa `FARO_MCP_ACTOR` y, si falta, `FARO_USUARIO`.

Para una mutacion autorizada se registra un evento `started` **antes** de ejecutar la herramienta. Si el log obligatorio no puede escribirse, se devuelve `AUDIT_ERROR` y la operacion no se ejecuta. Tras la llamada se intenta registrar `success`, `business_error` o `error`. El evento inicial evita perder la trazabilidad de una mutacion aunque falle el cierre del log.

Los intentos denegados generan `status=denied` cuando el sink de auditoria esta disponible.

Cada registro JSONL incluye al menos:

- fecha/hora con zona;
- `event_id` y `request_id`;
- actor y `client_id`;
- empresa y centro;
- herramienta, riesgo efectivo y nivel concedido;
- estado;
- argumentos sanitizados en eventos de inicio/denegacion;
- codigo/mensaje de error cuando corresponde;
- duracion para el cierre.

No se copian resultados completos al log. Contraseñas, tokens, secretos y autorizaciones se sustituyen por `***REDACTED***`; listas y textos se limitan para evitar logs descontrolados.

### Codigos de error nuevos

- `FORBIDDEN`: el nivel de acceso no alcanza el riesgo efectivo solicitado.
- `AUDIT_ERROR`: una mutacion autorizada no puede comenzar porque el sink obligatorio de auditoria no es escribible.

### Limitacion de identidad

`FARO_MCP_ACTOR` identifica al actor de despliegue, pero esta fase **no introduce autenticacion de red ni identidad criptograficamente verificada del cliente**. Mientras el transporte sea stdio/manual, el proceso que arranca el servidor controla estas variables. La autenticacion de transporte/SDK pertenece a la siguiente fase de infraestructura.

### Compatibilidad

- Los 39 schemas publicos son identicos a Fase 12 (mismo snapshot SHA-256).
- No cambian los perfiles ni los nombres de herramientas.
- Los handlers internos siguen disponibles para pruebas y composicion, pero los permisos se aplican en el borde `tools/call`.
- El acceso por defecto cambia deliberadamente a **solo lectura**. Para operar el ERP hay que configurar `write` o `critical` de forma explicita.

### Pruebas

La bateria completa pasa **154/154** pruebas. Se anaden verificaciones de clasificacion completa, riesgo dinamico, acceso seguro por defecto, bloqueo `read -> write`, bloqueo `write -> critical`, auditoria de inicio/resultado, redaccion de secretos, fail-closed del log y auditoria opcional de lecturas.

---

## 24. Limpieza Fase 14 - SDK MCP oficial

> _Fuente original: `LIMPIEZA_FASE14_SDK_OFICIAL.md` (fusionado, fichero eliminado)._

### Objetivo

Sustituir la implementacion manual del protocolo MCP por el SDK Python oficial, manteniendo sin cambios la logica Faro, los perfiles, los permisos, la auditoria y el contrato publico v2.

### Resultado

- Servidor Faro: **2.5.0**.
- Contrato publico: **2.0** (sin cambios).
- Perfiles: `core=29`, `admin=38`, `integrations=30`, `all=39`; `full` sigue siendo alias de `all`.
- SDK objetivo: `mcp>=2.2.0,<3.0.0` (rama estable v2).
- Pruebas: **162/162**.
- DataSnap runtime: **0**.
- Protocolo MCP manual en produccion: **0**.

### Arquitectura nueva

`faro_mcp.py` queda como motor de negocio y runtime de herramientas. `FaroToolRuntime.invoke_tool()` concentra validacion del contrato, traduccion de argumentos, autorizacion `read/write/critical`, auditoria y normalizacion de resultados.

`mcp_sdk_server.py` es el unico adaptador de protocolo. Usa la API low-level del SDK oficial (`Server`, `Tool`, `ListToolsResult`, `CallToolResult`, `TextContent`, `stdio_server`). Se elige la API low-level deliberadamente para conservar literalmente los JSON Schemas congelados en Fase 12; no se regeneran mediante Pydantic ni decoradores.

`server.py` se reduce al entrypoint del adaptador SDK.

### Eliminado

Se eliminan de produccion:

- `McpServer.handle()` como dispatcher JSON-RPC manual.
- `read_message()`.
- `write_message()`.
- framing manual `Content-Length`.
- respuestas manuales a `initialize`.
- dispatch manual de `tools/list` y `tools/call`.
- bucle propio sobre `stdin/stdout`.

El SDK pasa a gestionar versionado de protocolo, lifecycle, framing, stdio y mensajes MCP.

### Transportes

#### stdio (por defecto)

```powershell
$env:FARO_MCP_TRANSPORT = "stdio"
python server.py
```

Es el modo recomendado para un host MCP local.

#### Streamable HTTP (opt-in)

```powershell
$env:FARO_MCP_TRANSPORT = "streamable-http"
$env:FARO_MCP_HTTP_HOST = "127.0.0.1"
$env:FARO_MCP_HTTP_PORT = "8000"
$env:FARO_MCP_HTTP_PATH = "/mcp"
python server.py
```

Por defecto se enlaza solo a `127.0.0.1`, usa modo stateless y respuesta JSON. No debe exponerse a Internet sin una capa de autenticacion/autorizacion HTTP de produccion. El control `FARO_MCP_ACCESS_LEVEL` sigue protegiendo acciones ERP, pero no sustituye la autenticacion de red.

### Seguridad

La Fase 14 no modifica la politica Fase 13. El SDK entrega la llamada a `FaroToolRuntime`, que sigue aplicando:

1. allowlist del perfil funcional;
2. validacion JSON Schema runtime;
3. riesgo efectivo de la accion;
4. permiso `read/write/critical`;
5. auditoria fail-closed antes de mutaciones;
6. traduccion del contrato publico a la implementacion interna;
7. normalizacion uniforme del resultado.

El `request_id` proporcionado por el contexto del SDK se utiliza como identificador de auditoria cuando esta disponible.

### Compatibilidad

Los 39 schemas publicos no cambian. Tampoco cambian nombres, argumentos, perfiles ni el contrato de respuestas `ok/data/warnings/meta` y `ok/error/warnings/meta`.

Las pruebas historicas que antes llamaban directamente al dispatcher JSON-RPC usan ahora un adaptador exclusivamente de test (`tests/_runtime_compat.py`). Este fichero no se importa ni se utiliza en produccion.

### Dependencias

`requirements.txt` incorpora:

- `mcp>=2.2.0,<3.0.0`
- `uvicorn>=0.35.0,<1.0.0` para el transporte Streamable HTTP opcional.

### Validacion

Se conservan las 154 pruebas previas y se incorporan 8 pruebas especificas de Fase 14:

- ausencia del protocolo manual en `faro_mcp.py`;
- dependencia SDK v2 fijada;
- construccion del servidor SDK con version 2.5.0;
- conservacion exacta del catalogo `core`;
- delegacion `tools/call -> FaroToolRuntime.invoke_tool`;
- conservacion de `isError` en errores de herramienta;
- Streamable HTTP local y explicito por defecto;
- entrypoint `server.py` basado en el adaptador SDK.

El entorno de construccion de esta sesion no permite descargar paquetes de PyPI, por lo que el paquete `mcp` real no pudo instalarse aqui. La integracion se ha escrito contra la API oficial v2 documentada y se ha validado con dobles estrictos de esas clases. En el entorno de despliegue debe ejecutarse `pip install -r requirements.txt` y realizarse la prueba de humo con el SDK real / MCP Inspector.

---

## 25. Anexo - Estado de migracion DataSnap -> MCP Python

> _Fuente original: `MIGRATION_STATUS.md` (fusionado, fichero eliminado)._

### Fase 14 - SDK MCP oficial

La capa de protocolo manual se sustituye por el SDK MCP Python oficial v2. `FaroToolRuntime` mantiene la logica de negocio, perfiles, validacion, permisos y auditoria; `mcp_sdk_server.py` se limita a adaptar `tools/list` y `tools/call` a los tipos oficiales del SDK.

Se eliminan de produccion `McpServer.handle`, `read_message`, `write_message`, framing `Content-Length`, handshake manual y bucle JSON-RPC propio. `stdio` sigue siendo el transporte por defecto y se anade Streamable HTTP como opcion explicita en localhost.

El contrato publico permanece **2.0** y los perfiles siguen exactamente en `core=29`, `admin=38`, `integrations=30`, `all=39`. Version del servidor: **2.5.0**. Pruebas: **162/162**.

### Limpieza Fase 13 - seguridad y auditoria

El contrato publico v2 permanece estable (`core=29`, `admin=38`, `integrations=30`, `all=39`), pero `tools/call` incorpora permisos `read/write/critical`. El valor por defecto es `read`. Las fachadas mixtas calculan riesgo por accion y las operaciones de impacto alto requieren `critical`.

Toda mutacion se audita en JSONL con evento previo `started` y cierre `success/business_error/error`; si la auditoria obligatoria no puede registrar el inicio, la mutacion se bloquea con `AUDIT_ERROR`. Los secretos se redactan y los intentos sin permiso devuelven `FORBIDDEN`.

Version del servidor: **2.4.0**. Contrato publico: **2.0**. Pruebas: **154/154**. Los 39 schemas publicos conservan exactamente el snapshot de Fase 12.


### Limpieza Fase 12 - contrato MCP v2

La superficie de herramientas permanece congelada (`core=29`, `admin=38`, `integrations=30`, `all=39`), pero el contrato de argumentos/resultados evoluciona a la version **2.0**. Los schemas publicos usan nombres de dominio completos, `additionalProperties=false` y estructuras JSON para lineas de clientes/pedidos/trasvases/ventas en lugar de cadenas `|/#`.

`tools/call` devuelve un sobre uniforme `ok/data/warnings/meta` o `ok/error/warnings/meta`, con `isError=true` para errores de ejecucion de herramienta. `datasnap_text`/`datasnap_value` siguen disponibles solo en capas internas de compatibilidad y se eliminan de las respuestas MCP.

Version del servidor: **2.3.0**. Pruebas: **141/141**.


### Limpieza Fase 11 - refactor interno

El contrato publico de Fase 10 permanece congelado: `core=29`, `admin=38`, `integrations=30`, `all=39`. La implementacion ya no utiliza tablas de renombrado ni aliases de handlers; cada herramienta publica apunta directamente a `tool_<nombre_canonico>` y cada schema se declara directamente con su nombre final.

Se eliminaron **49 wrappers muertos**, no queda ningun metodo `tool_py_*` en runtime y las utilidades SQL no publicas usan nomenclatura `internal_*`. La Fase 11 cerro en **2.2.0** con **127/127** pruebas; Fase 12 evoluciona intencionadamente el schema publico.

Los campos `datasnap_text`/`datasnap_value` se conservan solo dentro del motor para pruebas de fidelidad, pero Fase 12 los retira de las respuestas MCP publicas.


### Limpieza Fase 10 - perfiles finales y contrato congelado

El API MCP deja de depender de filtros negativos y se define mediante allowlists explicitas. `core` conserva exactamente **29 herramientas**; `admin` expone **38**, `integrations` **30** y `all` **39**. `full` se mantiene solo como alias de compatibilidad hacia `all`. Cualquier herramienta nueva debe asignarse expresamente a un perfil y tener handler + schema antes de poder publicarse. Contrato de nombres/perfiles congelado originalmente en **2.1.0**; el contrato de argumentos/resultados evoluciona en Fase 12 a la version publica **2.0** y servidor **2.3.0**.

### Limpieza Fase 9 - compactacion de Ventas/Mostrador

`mostrador_venta_guardar`, `mostrador_venta_borrar` y `mostrador_pedido_cargar` se consolidan en `mostrador_venta_gestion(accion=guardar|borrar|cargar_pedido)`. `mostrador_cobrar` permanece separada por su impacto fiscal y de caja. `venta_albaran_crear` se renombra a `venta_documento_crear` para reflejar que el tipo documental depende de `tipdoc`. El perfil `core` baja de **31 a 29 herramientas** y `full` de **41 a 39**.

### Limpieza Fase 8 - compactacion de Articulos/Catalogo/Compras

`articulo_obtener` absorbe informacion tecnica e imagen de forma opcional (`incluir=tecnica|imagen`). `articulo_proveedor_listar` + `articulo_ficha_compra` se consolidan en `articulo_compra_consultar`, y `marca_listar` + `familia_listar` en `articulo_catalogo_listar`. El perfil `core` baja de **35 a 31 herramientas** y `full` de **45 a 41**, sin eliminar implementaciones internas.

### Limpieza Fase 7 - compactacion de Clientes/CRM

`actividad_tipo_listar`, `actividad_listar` y `actividad_grabar` se consolidan en `actividad_gestion` (`accion=tipos|listar|grabar`). `cliente_ultimas_ventas`, `cliente_buscar` y `cliente_actualizar` permanecen separadas por representar operaciones de negocio distintas. El perfil `core` baja de **37 a 35 herramientas** y `full` de **47 a 45**.

### Limpieza Fase 6 - compactacion de pedidos

`pedido_listar_cliente` se integra en `pedido_listar`, que admite opcionalmente `codcli` + `subcli`. `pedido_pdf_generar` y `pedido_pdf_obtener` se consolidan en `pedido_pdf_gestion` (`accion=generar|obtener`). Las escrituras de pedido con significado distinto permanecen separadas. El perfil `core` baja de **39 a 37 herramientas** y `full` de **49 a 47**. Tambien se corrige la fachada `pedido_detalle` para manejar correctamente las listas devueltas por la implementacion real.

### Limpieza Fase 5 - compactacion de stock/almacen

Las nueve herramientas publicas de etiquetas, recuentos y faltas (`listar/grabar/borrar`) se consolidan en `etiqueta_gestion`, `recuento_gestion` y `falta_gestion`. El perfil `core` baja de **45 a 39 herramientas** y el perfil `full` de **55 a 49**, sin eliminar las implementaciones internas.

### Limpieza Fase 4 - perfiles core/full

El catalogo por defecto se reduce de **55 a 45 herramientas** mediante `FARO_MCP_TOOL_PROFILE=core`. Las 10 operaciones retiradas del catalogo normal no se borran: permanecen implementadas y se exponen al usar `FARO_MCP_TOOL_PROFILE=full`. La finalidad es separar operaciones habituales de negocio de mantenimiento administrativo, helpers legacy e integraciones especificas.


### Resumen final

- API publica DataSnap de referencia: **78 funciones**.
- Funciones publicas migradas a Python nativo: **78**.
- Funciones publicas pendientes: **0**.
- Cobertura nativa actual: **100 %** (78/78).
- Herramientas MCP publicas por defecto (`core`): **36**.
- Perfil `admin`: **44 herramientas**.
- Perfil `integrations`: **37 herramientas**.
- Perfil `all`: **45 herramientas** (`full` es alias de compatibilidad).
- Proxies DataSnap: **0**.
- Dependencia de ejecucion de DataSnap: **0**.

La migracion conserva las 78 equivalencias funcionales en Python. Tras la Fase 11 ya no existen aliases de implementacion ni wrappers `tool_py_*`; el contrato publico se registra directamente mediante nombres canonicos y perfiles explicitos.


### Limpieza posterior a la migracion - Fase 3

Se han normalizado los **55 nombres publicos** por dominio. Las 44 herramientas que conservaban nombres de migracion (`py_*` o `list_price_tables`) publican ahora nombres de negocio estables, manteniendo exactamente los mismos handlers y schemas.

Ejemplos: `py_search_articles` -> `articulo_buscar`, `py_grabar_cliente` -> `cliente_actualizar`, `py_grabar_pedido_cliente` -> `pedido_crear`, `py_grabar_venta` -> `mostrador_venta_guardar`, `py_grabar_ticket_factura` -> `mostrador_cobrar` y `py_comprobar_usuario` -> `control_horario_fichar`.

Los nombres historicos dejaron de formar parte del runtime en Fase 11. Desde Fase 10 el contrato se define por allowlists: `core` (29), `admin` (38), `integrations` (30) y `all` (39). `full` queda como alias de compatibilidad de `all`. Version actual tras Fase 14: **2.5.0**.

### Limpieza posterior a la migracion - Fase 2

Se han consolidado **23 herramientas legacy** en **11 fachadas publicas de dominio**, reduciendo el catalogo de 67 a **55 herramientas** sin eliminar implementaciones internas.

Nuevas fachadas: `articulo_obtener`, `stock_consultar`, `familia_listar`, `etiqueta_listar`, `recuento_listar`, `falta_listar`, `articulo_ubicacion_guardar`, `cliente_buscar`, `actividad_listar`, `articulo_cambiar_tabla_precio` y `pedido_detalle`.

El cambio de tabla de precios queda en modo simulacion por defecto y requiere `simular=false` para modificar datos.

### Limpieza posterior a la migracion - Fase 1

Se han retirado del catalogo MCP 16 herramientas tecnicas o redundantes, manteniendo su implementacion Python interna. `tools/list` y `tools/call` ya no las exponen. La migracion DataSnap sigue estando al 100 %.

Herramientas internalizadas: `py_seguridad_usuario`, `py_conexion_usuario`, `py_conexion_cliente`, `py_cript`, `py_bloqueo_vencaj`, `py_grabar_fichero`, `py_get_imagen_banner_as_string`, `py_enviar_correo`, `py_get_fichero`, `py_get_fichero_as_string`, `py_busqueda_sql`, `py_abrir_consulta`, `py_ejecutar_sql`, `py_inicializa_conexion`, `py_echo_string` y `py_reverse_string`.

### Ultima fase de migracion completada - Fase 2I

| DataSnap | MCP Python | Estado |
| --- | --- | --- |
| `Busqueda_SQL` | `py_busqueda_sql` | Migrada; lectura SQL protegida |
| `Abrir_Consulta` | `py_abrir_consulta` | Migrada; lectura SQL protegida + formato `|/#` |
| `Ejecutar_SQL` | `py_ejecutar_sql` | Migrada; deshabilitada por defecto y protegida por flag |
| `InicializaConexion` | `py_inicializa_conexion` | Migrada al ciclo de conexion MCP |
| `EchoString` | `py_echo_string` | Migrada |
| `ReverseString` | `py_reverse_string` | Migrada |

#### Politica de SQL legacy

`Busqueda_SQL` y `Abrir_Consulta` aceptan un unico `SELECT`/CTE de lectura y rechazan sentencias encadenadas, comentarios y operaciones de escritura/DDL.

`Ejecutar_SQL` existe para cerrar la compatibilidad funcional, pero queda deshabilitada de fabrica. Requiere `FARO_ALLOW_INTERNAL_SQL_WRITE=true` y, aun asi, se limita a DML/`EXECUTE PROCEDURE`; no permite DDL ni control transaccional.

### Fases completadas

- Fase 1: primera migracion Python directa.
- 2A: motor comercial (`Precio_Cliente_Articulo`, `Ultimas_Ventas_Cliente`, `TipoVenta_Cliente`).
- 2B: operaciones complementarias de pedidos.
- 2C: ventas abiertas/caja (`BLOQUEO_VENCAJ`, `Grabar_Venta`, `Borrar_Venta`).
- 2D: conversion de pedidos y documentos (`Grabar_Venta_Abierta_Pedido`, `Grabar_Albaran`).
- 2E: ticket/factura, efectos, caja y riesgo (`Grabar_Ticket_Factura`).
- 2F: stock/logistica (`Trasvase_Centros`, `Stock_Coinfer_Articulo`).
- 2G: control horario (`Comprobar_Usuario`).
- 2H: documentos, ficheros, PDF e email.
- 2I: SQL legacy y utilidades finales.

### Pruebas

Tras la Fase 14 pasan **162 pruebas de regresion**. Se incluyen las pruebas de las fases anteriores y nuevas comprobaciones de:

- contrato exacto de **29 herramientas** en `core`, **38** en `admin`, **30** en `integrations` y **39** en `all`;
- compatibilidad de `full` como alias de `all` y fallback seguro de perfiles desconocidos a `core`;
- rechazo cruzado de herramientas `admin`/`integrations` cuando el perfil no las habilita;
- ausencia total de wrappers `tool_py_*` en el runtime y registro directo de nombres canonicos;
- snapshot/hash del contrato publico v2 de Fase 12 y mantenimiento exacto de los nombres/perfiles de Fase 10;
- filtrado efectivo de las 10 herramientas avanzadas en `core` tanto en `tools/list` como en `tools/call`;
- compactacion y enrutamiento `listar/grabar/borrar` de etiquetas, recuentos y faltas;
- compactacion de pedidos (`pedido_listar` y `pedido_pdf_gestion`) y rechazo de los nombres sustituidos;
- compactacion CRM mediante `actividad_gestion` y rechazo de `actividad_tipo_listar`, `actividad_listar` y `actividad_grabar`;
- compactacion de ventas/mostrador mediante `mostrador_venta_gestion`, manteniendo `mostrador_cobrar` separada y renombrando `venta_documento_crear`;
- compactacion de articulos: ficha tecnica/imagen opcionales en `articulo_obtener`, compras en `articulo_compra_consultar` y catalogos en `articulo_catalogo_listar`;
- correccion de `pedido_detalle` con resultados reales en forma de lista;
- enrutamiento de las nuevas fachadas consolidadas de stock, ubicaciones, clientes, precios y pedidos;
- ausencia de `datasnap_*`;
- compatibilidad `Busqueda_SQL` / `Abrir_Consulta`;
- formato historico `|/#`;
- rechazo de SQL de lectura peligroso;
- bloqueo por defecto de `Ejecutar_SQL`;
- commit de DML cuando se habilita explicitamente;
- `InicializaConexion`, `EchoString` y `ReverseString`.

### Estado final

La migracion de la **API publica DataSnap esta completada al 100 %**. Las mejoras posteriores ya no son fases de migracion sino de endurecimiento, compatibilidad MCP, observabilidad, pruebas contra una BD Faro real y refactor de mantenimiento.



## Estabilizacion posterior - Fase 4: acceso critical por defecto (16/09/2026)

Por decision de operacion del servidor, el nivel de acceso MCP por defecto cambia de `read` a **`critical`**. Esto afecta al runtime cuando `FARO_MCP_ACCESS_LEVEL` no esta definida o esta vacia, y tambien a `.mcp.json` y `config.example.json`.

Se mantiene un comportamiento fail-closed para configuraciones erroneas: un valor desconocido de `FARO_MCP_ACCESS_LEVEL` no concede permisos `critical`, sino que cae a `read`. Los niveles explicitos `read` y `write` siguen disponibles para ejecuciones restringidas y para la bateria segura de pruebas contra base de datos.


## Estabilizacion posterior - Fase 5: cobertura directa de herramientas publicas (16/09/2026)

Se amplia la bateria de regresion sobre cinco herramientas que estaban cubiertas de forma indirecta o parcial: `cliente_tipo_venta`, `precio_tabla_listar`, `pedido_linea_mover`, `pedido_marcar_preparado` y `pedido_finalizar`.

Las nuevas pruebas verifican de forma explicita el schema publico, nombres de dominio y traduccion a parametros internos, clasificacion de riesgo, rechazo de parametros legacy/incompletos, enrutamiento a los servicios Python, cierre de la conexion y recorrido completo por `FaroToolRuntime.invoke_tool` con validacion y auditoria. No se modifica logica de negocio ni SQL en esta fase.

Resultado de regresion: **250/250 pruebas** correctas, mas **122 subtests parametrizados**.


## Fase 6 - Limpieza de distribucion (2026-09-16)

- Eliminados del paquete distribuible `.venv`, `__pycache__`, `.pytest_cache`, bytecode Python y `test-runs` generados.
- Anhadido `.gitignore` para evitar que esos artefactos vuelvan a incorporarse al proyecto.
- Anhadido `requirements-dev.txt` para separar la instalacion de pruebas (`pytest`) de las dependencias de runtime.
- Anhadido `scripts/build_distribution.py`, generador reproducible del ZIP que excluye automaticamente entornos, caches, resultados y salidas de build.
- README actualizado con el procedimiento para crear `.venv`, instalar runtime/desarrollo y generar la distribucion.
- Sin cambios en contrato MCP, SQL ni logica de negocio.


## Fase 7 - Tarifas de proveedor (16/09/2026)

Se incorpora `tarifa_proveedor_actualizar`, migrada a Python nativo tomando `IMPTAR_U.pas` y `ARTICUL_UDM.pas` como referencia funcional. La herramienta queda en el perfil `core` y se clasifica como `critical` porque puede modificar costes y precios de venta en lote.

Comportamiento implementado:

- valida la existencia del proveedor en `PROVEE`;
- resuelve el articulo por `ART_CODART`, `ARTICULC.ARTC_CODIGO` o `ARTICULP.ARTP_REFPRO`;
- busca la ficha actual por empresa + articulo + proveedor;
- si existe, guarda el precio anterior en `ARTP_CANPRE`, actualiza `ARTP_PREBAS`, permite cambiar `ARTP_REFPRO` y conserva conversiones/descuentos/campos no informados;
- si no existe, inserta `ARTICULP` con los valores por defecto equivalentes al importador Delphi (`CANCON=1`, `CANVEN=1`, `UNIPAQ=1`, descuentos=0, moneda del articulo, `CANPRE=1`);
- admite los seis descuentos de proveedor, conversion compra/venta, unidades por paquete, unidad de medida, descripcion, `ARTP_AMPUNIV` y `ARTP_AJUSTE`;
- calcula el coste neto con `PREBAS * (1-dto1/100) * ... * (1-dto6/100)`;
- con `actualizar_precio_venta=true`, actualiza el coste de `ARTICUL` y reutiliza `CALCULAR_PRECIO_ARTICUL` ya migrado (`calculate_article_price`) para recalcular precios de venta/PVP;
- la llamada MCP es atomica: se hace `commit` solo al completar todas las lineas y `rollback` del lote ante cualquier error;
- maximo de 500 lineas por invocacion para evitar lotes MCP descontrolados.

El contrato publica 46 herramientas: `core=37`, `admin=45`, `integrations=38`, `all/full=46`. La version del servidor pasa a **2.7.0** y el contrato publico continua en **2.0**. El snapshot SHA-256 del catalogo `all` pasa a `8be2b36ce0b6af2a57ebcdf61e3b36cd5c5f88a943c40d37c57f2244a4bc2494`.

Pruebas especificas nuevas: contrato y validacion, nivel `critical`, alta con valores por defecto, modificacion preservando campos no informados, `ARTP_CANPRE` como precio anterior, cambio de referencia, resolucion por EAN/referencia, recalculo opcional de `ARTICUL`, rollback atomico y cierre de conexion en la fachada MCP.

Resultado de regresion: **259/259 pruebas** correctas, mas **125 subtests parametrizados**.


## Fase 8 - Probador web para tarifas de proveedor (16/09/2026)

Se actualiza `scripts/mcp_tester_web.py` para que `tarifa_proveedor_actualizar` tenga una interfaz especifica, manteniendo como backend la misma llamada a `FaroToolRuntime.invoke_tool` del resto del probador.

Mejoras incorporadas:

- editor visual de multiples lineas en vez del textarea JSON generico;
- alta/eliminacion de lineas desde la propia pagina;
- campos visibles para articulo, codigo de barras, referencia de proveedor, descripcion, unidad, precio base y los seis descuentos;
- bloque avanzado por linea para conversion compra/venta, unidades por paquete, ampliacion de unidad de venta y ajuste;
- serializacion automatica del editor al array `lineas` exacto del contrato MCP;
- datos de prueba obtenidos mediante `articulo_compra_consultar`, sin escritura previa: la BD solo se modifica al confirmar y pulsar `Ejecutar`;
- aviso explicito de que la herramienta modifica `ARTICULP` y, con `actualizar_precio_venta=true`, tambien `ARTICUL`;
- categoria visual propia `Critica` para herramientas cuyo contrato se identifica como `CRITICA`;
- resultado de tarifas presentado por defecto en grid, con columnas por linea y resumen de lineas, altas, modificaciones y PVP actualizados;
- se conserva la vista JSON y el override JSON manual para diagnostico avanzado.

No cambia el contrato MCP ni la logica SQL de `tarifa_proveedor_actualizar`; esta fase afecta al probador web y a sus pruebas de regresion.

Resultado de regresion tras la Fase 8: **264/264 pruebas** correctas, mas **125 subtests parametrizados**.


## Fase 9 - Opciones de Proceso de tarifas de proveedor (16/09/2026)

Un usuario reporto, viendo el probador web, que al formulario de `tarifa_proveedor_actualizar` le faltaban todas las casillas "Opciones Proceso" que existen en la pantalla Delphi original (`FuentesDelphi/IMPTAR_U.pas` / `.dfm`). Se confirmo leyendo el codigo linea a linea (ver `revision-tarifa-proveedor-actualizar.md` en el proyecto de Claude) que el hueco era real: el esquema solo declaraba `proveedor`, `lineas` y `actualizar_precio_venta`, y ninguna prueba, el README ni este historial documentaban las 11 casillas de esa pantalla.

De las 11, cinco tenian logica clara y accionable sin ampliar el alcance de la herramienta (que solo opera sobre articulos ya existentes) y se han incorporado:

- `actualizar_solo_si_sube_precio` (replica `B_MAS`): con `actualizar_precio_venta=true`, si el coste neto nuevo es menor que el anterior, no se toca `ARTICUL` (la tarifa de compra en `ARTICULP` si se actualiza).
- `actualizar_solo_proveedor_principal` (replica `B_PRINCIPAL`): solo recalcula el precio de venta si el proveedor de la linea coincide con `ART_CODPRO`.
- `actualizar_solo_si_propio` (replica `B_PROPIO`): solo recalcula el precio de venta si `ART_INDPROP<>'N'`.
- `generar_etiquetas` + `etiqueta_modelo` (replica `B_ETIQUETAS`): si el PVP de una linea cambia de verdad, inserta una fila en `ETIQUE` (`ETI_CANTID=1`, `ETI_IMPRIM='S'`), con la descripcion corta de `ARTICULI/ARTI_CODINF='DESCO'` cuando existe (igual que `GRABAR_ETIQUE` de `ETIQUE_UDM.pas`). El modelo se pide explicito porque `MODELO_ETIQUETA_ARTICUL` (la funcion Delphi que resolveria un modelo por defecto) no se ha podido localizar en las fuentes disponibles; por defecto es `0`, el mismo valor de respaldo que usa el propio Delphi cuando esa resolucion no encuentra nada.
- Cuando una linea informa `descripcion` y `actualizar_precio_venta=true`, ahora tambien se sobrescribe `ARTICUL.ART_DESCRI` (antes solo se tocaba `ARTICULP.ARTP_DESCRI`), replicando la mitad de `B_DESCRI` que faltaba.

Las otras seis casillas quedan documentadas como no aplicables o fuera de alcance, no como un olvido:

- `B_ALTA` ("Dar de alta") y `B_REFPRO` ("Codigo de Articulo = Referencia Proveedor"): confirmado leyendo `IMPTAR_U.pas` que solo controlan la creacion de un articulo **completamente nuevo** en `ARTICUL`. Esta herramienta nunca ha creado articulos nuevos (si no encuentra el articulo, da error), solo tarifas de articulos existentes; insertar una tarifa nueva para un articulo ya existente no depende de `B_ALTA` ni siquiera en el propio Delphi. **`B_ALTA` se implemento despues, en la Fase 10; `B_REFPRO` (autogeneracion de codigo) se implemento en la Fase 11.**
- `B_DTO` ("Asumir Dto del Articulo"): no es un hueco, es una diferencia de diseno. `update_supplier_tariff` ya logra el mismo resultado por linea (si la linea trae `descuentoN` se usa ese valor, si no se conserva el que ya hubiera), mas flexible que el interruptor global de Delphi.
- `B_RECALCULO` ("Recalculo codigo de barras"): esta herramienta no escribe codigos de barras (esa escritura vive en `articulo_ean_grabar`), asi que no aplica.
- `B_CABECERA` ("La primera fila del Fichero indica las cabeceras"): es sobre parsear un Excel/CSV subido; el MCP recibe `lineas` ya como JSON estructurado.

La version del servidor pasa a **2.8.0**; el contrato publico continua en **2.0** y los perfiles no cambian de tamanho (`core=37`, `admin=45`, `integrations=38`, `all/full=46`) porque son parametros nuevos de una herramienta existente, no herramientas nuevas. El snapshot SHA-256 del catalogo `all` pasa a `19c52985072ebd680845447c33c101034dea5aed30e9f435e4ef1459f6ae5ff3`.

Pruebas especificas nuevas: omision del recalculo de venta por cada una de las tres condiciones "solo si..." (y su contraparte que permite el recalculo), sobrescritura de `ART_DESCRI` con y sin `descripcion` informada, insercion de etiqueta cuando el PVP cambia y su omision cuando no cambia, reenvio de los cinco parametros nuevos desde la fachada MCP, y que `update_supplier_tariff` solo cuenta como "actualizado" o "etiqueta generada" los casos que realmente se ejecutan (no los omitidos por una condicion).

Resultado de regresion tras la Fase 9: **276/276 pruebas** correctas, mas **125 subtests parametrizados**.

## Fase 10 - Alta de articulos nuevos en tarifa_proveedor_actualizar (16/09/2026)

El usuario pidio explicitamente implementar lo que la Fase 9 habia dejado documentado como fuera de alcance: "revisa la funcion de tarifas para que si el articulo no existe cree tanto la ficha del articulo (ARTICUL) como de compra (ARTICULP) al igual que lo hace delphi cuando marcamos la opcion de dar de alta". Se leyo la rama `ELSE IF B_ALTA.Checked` de `IMPTAR_U.pas` (lineas 1999-2069) junto con sus "Valores por defecto" (lineas 1668-1717) y `INSERTAR_ARTICUL`/`MODIFICAR_ARTICUL` de `ARTICUL_UDM.pas` (lineas 1303-1412) para obtener la lista definitiva y ordenada de las 47 columnas que Delphi inserta en `ARTICUL`.

Se añadio el parametro `dar_de_alta` (bool, por defecto `false`, a nivel de lote — como el propio checkbox `B_ALTA`, no por linea). Con `dar_de_alta=false` (comportamiento previo, sin cambios) una linea sin articulo existente sigue lanzando error y revirtiendo el lote completo. Con `dar_de_alta=true`, esa linea crea `ARTICUL` + `ARTICULP` en el mismo lote (metodo nuevo `_create_article_for_tariff_alta`), reutilizando despues el mismo camino ya existente de "alta de tarifa sobre articulo existente" para insertar `ARTICULP`.

Para poder dar de alta hace falta informacion que Delphi obtiene de una fila de fichero ya parseada o de controles de pantalla (seccion, tipo de IVA, tipo de precio, unidad de medida) que esta API no puede inventar; por eso la linea debe informar explicitamente `articulo`, `descripcion`, `seccion`, `tipo_iva`, `tipo_precio` y `unidad_medida` cuando el articulo no existe, y `update_supplier_tariff` lanza un error listando los campos que falten. Campos opcionales nuevos, con los mismos valores por defecto que usa `IMPTAR_U.pas` cuando se dejan en blanco: `familia`/`subfamilia` (0), `tabla_precios` (0, usa la tabla de precios del sistema), `canon` (fuerza `tipo_precio='C'`, replicando el forzado literal de Delphi), `tarifa`, `pvp` (PVP directo) y `cantidad_pedido_minimo`, mas `norma` (texto). Si la linea trae `codigo_barras`, tambien se inserta en `ARTICULC` al dar de alta, igual que Delphi con el codigo usado para localizar el articulo.

Fidelidad verificada explicitamente, no asumida:

- El coste (`ART_PREBAS`) se calcula con la misma formula que `_supplier_net_cost` (precio base × los seis descuentos de proveedor), igual que `CARGAR_VALORES` en `IMPTAR_U.pas`.
- La conversion compra/venta (`ART_CANPRE`) replica la rama de alta literalmente, que es **distinta** de la rama de modificacion ya implementada en la Fase 9: la rama de alta compara `ARTP_CANCON`/`ARTP_CANVEN` con `> 1` y sin normalizar ceros a uno antes, mientras que la rama de modificacion usa `<> 1` con normalizacion previa. Se replico cada rama con su propio matiz en vez de reutilizar una sola formula para ambas.
- Fechas: `IMPTAR_U.pas` usa `FORMATEAR_FECHA(0)` para "sin fecha", que resuelve a `NULL` SQL (visto en `LIBTIP_U.pas`); `ART_FEBAJA`/`ART_FECMOV` se insertan como `NULL`, no como una fecha centinela.
- Una linea recien dada de alta **nunca** pasa por el bloque de `actualizar_precio_venta`: en `IMPTAR_U.pas` ese bloque (`MODIFICAR_PVENTA`) solo existe dentro de `IF NOT ALTA THEN`, nunca en la rama de alta. Se replico esa exclusividad explicitamente (si `dar_de_alta` crea el articulo en una linea, se omite la llamada a `_update_sale_price_from_supplier_tariff` para esa linea aunque `actualizar_precio_venta=true`).

Deliberadamente fuera de alcance en esta Fase, documentado como tal (no un olvido): `B_REFPRO` y la autogeneracion de codigo de articulo a partir de seccion+proveedor+contador (`IMPTAR_U.pas:1727-1742`) — esta API exige `articulo` explicito porque no existe aqui un "lote con seccion ya seleccionada en pantalla" que replicar de forma fiable. **Se implemento despues, en la Fase 11.** Tambien fuera de alcance (y sigue estandolo): `STOMIN`/`STOMAX`/`STOCK` inicial, caracteristicas tecnicas, marca/familia-no-catalogada/subfamilia-no-catalogada, blister y el limite `NUEVES` de articulos propios por seccion/proveedor — todos ellos dependen de columnas del fichero de importacion que no tienen equivalente en el esquema `lineas` de esta herramienta.

El resultado de `update_supplier_tariff` añade el contador `articulos_creados` y el flag `dar_de_alta` (eco del parametro); cada linea del array `resultados` añade `articulo_creado` (bool) y usa `accion="alta_articulo"` para distinguir una alta de articulo completo de un alta de tarifa sobre un articulo ya existente (`accion="alta"`).

La version del servidor pasa a **2.9.0**; el contrato publico continua en **2.0** y los perfiles no cambian de tamaño. El snapshot SHA-256 del catalogo `all` pasa a `acd6e07c4756722ac1547e322ac61607928388a019cdcdb9fca10530ec2a012e` (motivo 9 documentado en `test_cleanup_phase11_internal_refactor.py`).

Pruebas especificas nuevas (`SupplierTariffAltaTests` en `test_phase7_supplier_tariffs.py`): sin `dar_de_alta` sigue lanzando error y revirtiendo el lote; con `dar_de_alta=true` inserta `ARTICUL` y `ARTICULP` con los campos correctos; falta de campos obligatorios lanza un error que los nombra todos; `canon` fuerza `tipo_precio='C'`; `codigo_barras` inserta en `ARTICULC`; el calculo de PVP via tabla de precios + IVA es correcto; `actualizar_precio_venta=true` no genera ningun `UPDATE ARTICUL` adicional para la linea recien creada; una linea sin ningun identificador sigue siendo un error incluso con `dar_de_alta=true`.

Resultado de regresion tras la Fase 10: **284/284 pruebas** correctas, mas **125 subtests parametrizados**.

## Fase 11 - Autogeneracion de codigo de articulo en altas (17/09/2026)

La Fase 10 dejo documentado como deliberadamente fuera de alcance que `dar_de_alta` exigiera siempre un `articulo` explicito, porque `IMPTAR_U.pas` autogenera el codigo a partir de seccion+proveedor+contador (`B_REFPRO` sin marcar) o de la referencia de proveedor (`B_REFPRO` marcada), y esa Fase considero que replicarlo sin un "lote con seccion en pantalla" no era fiable. El usuario pidio explicitamente revisar de nuevo el proceso de alta e implementar ambas vias, indicando ademas que el numero de digitos del codigo (seccion + proveedor a 4 digitos + un numerador) debe ser configurable.

Se releyo `IMPTAR_U.pas:1727-1742` (la resolucion del codigo dentro del bucle de importacion) junto con `INICIALIZAR_VARIABLES` (`IMPTAR_U.pas:1570-1583`, que construye `CEROS`/`NUEVES` a partir de `B_DIGITOS.VALUE - 5`) y la inicializacion de `CONTADOR := NUMINICIAL.AsInteger` (linea 1629), y se confirmaron los controles de pantalla correspondientes en `IMPTAR_U.dfm`: `B_DIGITOS` (`TRxSpinEdit`, `MinValue=8`, `MaxValue=15`, por defecto `9`) y `NumInicial` (`TRxSpinEdit`, hint "Numerador inicial para el codigo").

Se añadieron tres parametros nuevos a `tarifa_proveedor_actualizar`, con efecto solo cuando `dar_de_alta=true` y una linea no informa `articulo`:

- `usar_referencia_proveedor_como_codigo` (bool, por defecto `false`): usa `referencia_proveedor` de la linea tal cual como `ART_CODART`, replicando `B_REFPRO` marcada. Si esta activo y la linea no trae `referencia_proveedor`, es error explicito.
- `digitos_codigo_articulo` (entero, por defecto `9`, entre `8` y `15`): numero total de digitos del codigo autogenerado (seccion + proveedor a 4 digitos + un contador que ocupa el resto), replicando `B_DIGITOS`. Fuera de rango lanza error antes de abrir la transaccion del lote.
- `numerador_inicial` (entero, por defecto `0`): valor inicial del contador, replicando `NumInicial`.

El metodo nuevo `_generar_codigo_articulo` concatena `seccion` (tal cual la informa la linea) + `proveedor` formateado a un minimo de 4 digitos + el contador formateado al ancho `digitos_codigo_articulo - 5`, exactamente como `FORMATFLOAT('0000', CODPRO) + FORMATFLOAT(CEROS, CONTADOR)`. Si el codigo generado ya existe (comprobado en `ARTICUL` con el mismo patron de consulta que el resto del fichero, mas un set en memoria para evitar colisiones dentro del propio lote antes de que la insercion sea visible), incrementa el contador y reintenta, replicando el bucle `WHILE EXISTE DO`; si esta libre, el contador **no** se incrementa tras el exito -igual que en Delphi, donde solo se detecta y avanza en la siguiente llamada si ese codigo ya quedo ocupado-. El estado del contador (`_init_codigo_articulo_gen_state`) se crea una sola vez por llamada a `update_supplier_tariff` y se comparte para todas las lineas del lote sin reiniciarse entre ellas, igual que `CONTADOR` en Delphi (inicializado una unica vez en `INICIALIZAR_VARIABLES`, antes del bucle de filas).

Un `articulo` explicito en la linea sigue teniendo prioridad absoluta sobre ambas vias, igual que en `IMPTAR_U.pas` (`IF T_ARTICUL.FieldByName('ART_CODART').AsString <> '' THEN ...`).

Cambio relacionado: `_supplier_tariff_article` exigia hasta ahora que toda linea informara al menos un identificador (`articulo`/`codigo_barras`/`referencia_proveedor`), incluso con `dar_de_alta=true`. Esa exigencia ya no es correcta: una linea sin ningun identificador es exactamente el caso normal de "codigo autogenerado". Se relajo para que, con `required=False` (es decir, `dar_de_alta=true`), la ausencia total de identificadores tambien delegue en `_create_article_for_tariff_alta` en lugar de lanzar error alli mismo; si a esa linea tambien le faltan `descripcion`/`seccion`/etc., el error se sigue lanzando, solo que con el mensaje mas especifico de campos faltantes.

La version del servidor pasa a **2.10.0**; el contrato publico continua en **2.0** y los perfiles no cambian de tamaño. El snapshot SHA-256 del catalogo `all` pasa a `d846b49f8150c015060bd56013ee17023967491bddcedc73886e0555d42c79b8` (motivo 10 documentado en `test_cleanup_phase11_internal_refactor.py`).

Pruebas especificas nuevas (`SupplierTariffAltaCodeGenerationTests` en `test_phase7_supplier_tariffs.py`): codigo autogenerado con seccion+proveedor+contador por defecto; el contador salta codigos ya existentes; `digitos_codigo_articulo`/`numerador_inicial` cambian el codigo generado; el contador se comparte y avanza entre lineas del mismo lote; `usar_referencia_proveedor_como_codigo` usa la referencia de proveedor; ese mismo parametro exige `referencia_proveedor` si falta; `articulo` explicito sigue ganando aunque los otros modos esten activos; `digitos_codigo_articulo` fuera de rango lanza error; la fachada MCP reenvia los tres parametros nuevos.

Resultado de regresion tras la Fase 11: **293/293 pruebas** correctas, mas **125 subtests parametrizados**.

## Fase 12 - Consulta de proveedores (17/09/2026)

Se publica `proveedor_buscar` como herramienta de lectura en el perfil `core`.
La implementacion ya existia parcialmente como fachada interna, pero no formaba
parte del catalogo publico ni de la clasificacion de seguridad. La herramienta
consulta el maestro `PROVEE` y permite filtrar por:

- codigo de proveedor (`proveedor`);
- nombre comercial (`PRO_NOMCOR`);
- nombre fiscal (`PRO_NOMFIS`);
- nombre abreviado (`PRO_NOMABR`);
- CIF (`PRO_CIF`);
- fecha de alta exacta o rango (`PRO_FEALTA`).

Si se indica solo `proveedor`, devuelve `modo=detalle`; con cualquier filtro de
busqueda devuelve `modo=listado`. La ficha incluye campos funcionales y tambien
el registro `PROVEE` normalizado para conservar todos los datos originales del
proveedor.

La version del servidor pasa a **2.11.0**; el contrato publico sigue en **2.0**.
Los perfiles quedan en `core=38`, `admin=46`, `integrations=39`, `all/full=47`.
El snapshot SHA-256 del catalogo `all` pasa a
`3d1485622591d0cb83a674fd90786730183915a97b5a68a7079771ebc2190c77`
(motivo 11 documentado en `test_cleanup_phase11_internal_refactor.py`).

Resultado de regresion tras la Fase 12: **295/295 pruebas** correctas, mas
**126 subtests parametrizados**.

## Fase 13 - Dashboard, compras, rentabilidad y Cartera (22/09/2026)

Se amplio el catalogo `core` con herramientas de lectura orientadas al dashboard
ERP: resumen ejecutivo, series, alertas, acciones recomendadas, compras
pendientes, articulos pendientes de recibir, propuestas de orden de compra por
pedidos de cliente y por stock minimo/maximo, y el bloque especifico de Cartera.

En ventas/rentabilidad se ajusto el calculo para respetar articulos no
inventariables (`ART_INDINV='N'`) como conceptos sin coste de inventario, y se
porto la regla de articulos fantasma (`DMV_TIPLIN='X'`) indicada por el ERP:
se ignoran las lineas tecnicas de factura de tickets/cobro/IVA y, para el resto,
se calcula el coste desde `DMV_CANPRE * DMV_CANTID` o desde el parametro
`RENTAF` cuando no hay cantidad/precio de coste directo.

Para compras se añadieron:

- `compras_articulos_pendientes_recibir`, lectura agregada por articulo desde
  pedidos de compra pendientes.
- `orden_compra_propuesta_stock_minimo`, propuesta de cantidades sin crear
  `CABORC`, basada en stock minimo/maximo, proveedor, unidades de paquete y
  criterios de `GENPEDM`.
- `orden_compra_propuesta_pedidos_cliente`, propuesta de cantidades desde
  pedidos de cliente, basada en `GENPEDC` y stock disponible.

Para Cartera se añadieron herramientas estrictamente de solo lectura, sin
creacion/cancelacion de remesas ni cobros:

- `cartera_efectos_detalle`
- `cartera_efectos_pendientes_resumen`
- `cartera_efectos_por_cliente`
- `cartera_pendiente_remesar`
- `cartera_remesas_resumen`
- `cartera_riesgo_cliente`
- `cartera_riesgo_clientes_resumen`

La logica de efectos replica los criterios visibles en `ANAEFE_U/ANAEFE_UR` y
`REMESA_UDM`: un efecto pendiente es `CBVE_FECCAN IS NULL`; el pendiente
monetario se calcula como `CBVE_IMPORT + CBVE_IMPGAS - CBVE_IMPCOB`; y un
efecto se considera remesado cuando `CBVE_EJEREM` o `CBVE_CODREM` son distintos
de cero.

La logica de riesgo de credito diferencia expresamente entre riesgo comercial de
dashboard (`negocio_clientes_riesgo`, basado en evolucion de ventas/margen) y
riesgo operativo de Cartera (`cartera_riesgo_*`, basado en el port de
`RIESGO_ACTUAL`). Este ultimo parte de `CLIEN.CLI_RIESGO`, respeta
`CLI_AGRUPAC`, descuenta albaranes pendientes, efectos vivos de factura,
facturas contado pendientes y pedidos cuando `RIEPED='S'`, y devuelve desglose
por componente para que el dashboard pueda explicar el saldo.

La version del servidor queda en **2.15.7**; el contrato publico sigue en
**2.0**. Los perfiles quedan en `core=81`, `admin=89`, `integrations=82`,
`all/full=90`. El snapshot SHA-256 del catalogo `all` queda en
`8df4f3bcf5770a69e66eb8ca8b81d69ded22f235d1c65e664fb1fe3e52234752`.

Resultado de regresion tras la Fase 13: **341/341 pruebas** correctas.
