# MCP Faro ERP

Servidor MCP en Python para operar directamente sobre la base de datos Faro/ERP.

## Arquitectura

El servidor **no usa proxies DataSnap** ni necesita que el servidor Delphi este en ejecucion. `ServicioDatasnap` se utiliza exclusivamente como fuente de verdad historica para migrar la logica heredada a Python; la migracion esta completa (ver [Historial de desarrollo](#historial-de-desarrollo)).

La conexion se realiza directamente mediante ODBC/Firebird y las herramientas MCP ejecutan implementaciones Python nativas.

`faro_mcp.py` concentra todo el motor de negocio (validacion, permisos, auditoria, normalizacion del contrato publico) en un unico fichero; `mcp_sdk_server.py` es la capa de transporte, construida sobre el SDK oficial MCP Python (`mcp>=2.2,<3`) para `stdio`, `tools/list`, `tools/call`, lifecycle y Streamable HTTP. `server.py` es el punto de entrada (`from mcp_sdk_server import main`).

## Configuracion

Por defecto se usa el DSN ODBC `faro`:

```powershell
$env:FARO_DB_DRIVER = "odbc"
$env:FARO_ODBC_DSN = "faro"
$env:FARO_DB_USER = "SYSDBA"
$env:FARO_DB_PASSWORD = "masterkey"
$env:FARO_EMPRESA = "1"
$env:FARO_CENTRO = "0"
$env:FARO_USUARIO = "codex"
$env:FARO_MCP_TOOL_PROFILE = "core"  # core (87), admin (96), integrations (88) o all (97)
$env:FARO_MCP_ACCESS_LEVEL = "critical" # critical por defecto; read y write siguen disponibles
```

Dependencias:

- `pyodbc` para ODBC.
- `firebird-driver` o `fdb` si se conecta directamente a Firebird.
- `reportlab` para generar PDF de pedidos en Python.
- `mcp>=2.2,<3` para el protocolo MCP oficial.
- `uvicorn` para el transporte Streamable HTTP opcional.

### Instalacion del entorno

La distribucion no incluye `.venv`: el entorno se crea localmente a partir de los ficheros de dependencias. En Windows/PowerShell:

```powershell
cd C:\IA\Faro\MCP
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Para desarrollar o ejecutar la suite de pruebas, instalar las dependencias de desarrollo (incluyen las de runtime):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`.venv`, caches Python, `test-runs` y salidas de `dist` no forman parte del paquete distribuible. Para crear un ZIP limpio de forma reproducible:

```powershell
.\.venv\Scripts\python.exe scripts\build_distribution.py
```

## Ejecutar

### stdio (recomendado para uso local)

```powershell
$env:FARO_MCP_TRANSPORT = "stdio"
python C:\IA\Faro\MCP\server.py
```

### Streamable HTTP (opcional)

```powershell
$env:FARO_MCP_TRANSPORT = "streamable-http"
$env:FARO_MCP_HTTP_HOST = "127.0.0.1"
$env:FARO_MCP_HTTP_PORT = "8000"
$env:FARO_MCP_HTTP_PATH = "/mcp"
python C:\IA\Faro\MCP\server.py
```

No exponga Streamable HTTP fuera de localhost sin una capa de autenticacion/autorizacion HTTP de produccion.

## Probador MCP Faro (interfaz web)

`scripts\mcp_tester_web.py` levanta un servidor de desarrollo local (`ThreadingHTTPServer`) con una interfaz web para invocar cualquier herramienta publica, agrupada por dominio, con formularios generados a partir del propio schema.

```powershell
cd C:\IA\Faro\MCP
.\.venv\Scripts\python.exe scripts\mcp_tester_web.py
```

La cabecera de la interfaz incluye un enlace **Ayuda**, que abre `/ayuda`: una pagina generada en el momento a partir de `faro_mcp.tool_definitions()` con el catalogo completo de herramientas (descripcion, parametros, tipo y perfil) siempre sincronizada con el servidor en ejecucion.

Para `tarifa_proveedor_actualizar` el probador no usa el textarea JSON generico: muestra un **editor especifico de tarifas** con lineas anadibles/eliminables, articulo/EAN/referencia de proveedor, precio base, seis descuentos y campos avanzados de conversion/unidades. El boton **Cargar datos de prueba** consulta una ficha real de compra para rellenar el formulario, pero no escribe nada hasta pulsar **Ejecutar**. El resultado se abre por defecto como grid por linea con un resumen de altas, modificaciones y PVP recalculados. Las herramientas `critical` se identifican visualmente como una categoria propia.

## Replicar empresa

`scripts\replicar_empresa.py` copia desde la empresa 1 las tablas auxiliares y de configuracion conocidas hacia una empresa nueva. Por defecto trabaja en modo simulacion, muestra el plan y no escribe nada.

```powershell
cd C:\IA\Faro\MCP
$env:FARO_DB_DRIVER = "odbc"
$env:FARO_ODBC_DSN = "faro"
$env:FARO_DB_USER = "SYSDBA"
$env:FARO_DB_PASSWORD = "masterkey"
.\.venv\Scripts\python.exe scripts\replicar_empresa.py --target-empresa 2 --plan-csv output\replicar_empresa_plan_2.csv
```

Cuando el plan sea correcto, ejecute con `--execute` y los datos propios de la empresa destino:

```powershell
.\.venv\Scripts\python.exe scripts\replicar_empresa.py `
  --target-empresa 2 `
  --nombre-comercial "NUEVA EMPRESA" `
  --nombre-fiscal "NUEVA EMPRESA S.L." `
  --cif "B00000000" `
  --domicilio1 "Calle Ejemplo, 1" `
  --codigo-postal "46000" `
  --poblacion "Valencia" `
  --email "administracion@example.com" `
  --execute
```

La utilidad bloquea la ejecucion si alguna tabla seleccionada ya tiene datos de la empresa destino. Al informar `--nombre-comercial` o `--nombre-fiscal`, tambien renombra `CENTROS.CEN_NOMCEN` con el nuevo nombre de empresa. Use `--include TABLA1,TABLA2` para copiar solo tablas concretas, `--exclude TABLA` para omitir alguna tabla auxiliar del plan, y `--all-company-tables` solo para auditorias o casos muy controlados, porque incluye tambien tablas maestras y movimientos.

La misma operacion esta publicada en MCP como `empresa_replicar` dentro del perfil `admin` y con riesgo `critical`. Pide `empresa_destino`, `nombre` y `direccion`, replica siempre desde la empresa 1 y actualiza nombre/direccion en `EMPRES` y `CENTROS`.

## Pruebas de funciones MCP

El script `scripts\run_mcp_function_tests.py` arranca `server.py` mediante el
cliente oficial MCP por `stdio`, valida perfiles, ejecuta una bateria segura de
lecturas reales y comprueba bloqueos esperados de escritura con
`FARO_MCP_ACCESS_LEVEL=read`. Guarda evidencias en `test-runs\` como JSON y
CSV.

```powershell
cd C:\IA\Faro\MCP
.\.venv\Scripts\python.exe scripts\run_mcp_function_tests.py
```

Parametros utiles:

```powershell
.\.venv\Scripts\python.exe scripts\run_mcp_function_tests.py `
  --dsn Faro `
  --empresa 1 `
  --centro 0 `
  --sample-articulo 814943103 `
  --sample-cliente 100 `
  --sample-subcliente 0
```

Para incluir simulaciones seguras de herramientas clasificadas como escritura:

```powershell
.\.venv\Scripts\python.exe scripts\run_mcp_function_tests.py --include-write-dry-run
```

### Suite de pruebas unitarias

La logica de `faro_mcp.py` (schemas, permisos, routing, casos de negocio) tiene su propia bateria de pruebas unitarias en `tests\`, sin necesidad de una base de datos real:

```powershell
cd C:\IA\Faro\MCP
.\.venv\Scripts\python.exe -m pytest tests\ -q
```

Estado actual: **356/356 pruebas** correctas, mas **371 subtests parametrizados**.

## Catalogo de herramientas

Version del servidor: **2.15.8**. Contrato publico: **2.0**. Migracion DataSnap -> Python nativo: **100 %** (0 proxies DataSnap).

Herramientas publicas por perfil (`FARO_MCP_TOOL_PROFILE`):

| Perfil | Herramientas | Descripcion |
| --- | --- | --- |
| `core` (por defecto) | 87 | Operacion habitual. |
| `admin` | 96 | `core` + mantenimientos/operaciones avanzadas. |
| `integrations` | 88 | `core` + integracion Coinfer. |
| `all` | 97 | Union completa. |
| `full` | 97 | Alias de compatibilidad de `all`. |

Cada herramienta tiene ademas un **nivel de riesgo** (`lectura`, `escritura` o `critica`) independiente del perfil, controlado por `FARO_MCP_ACCESS_LEVEL` (ver [Seguridad y auditoria](#seguridad-y-auditoria)). El borde del contrato v2 valida estrictamente los tipos JSON Schema usados por el catalogo, incluidos tipos alternativos como `number|string`, limites `minItems`/`maxItems`, `enum`, campos obligatorios y `additionalProperties=false`. El listado completo, siempre actualizado, esta disponible en vivo en `/ayuda` desde el Probador MCP o programaticamente via `faro_mcp.tool_definitions()`. Resumen por dominio (perfil `all`):

### ACTIVIDAD

- `actividad_grabar` [escritura] (core): registra o actualiza una actividad comercial de un cliente en una fecha.
- `actividad_listar` [lectura] (core): lista actividades filtrando por cliente, tipo de actividad, representante y/o un rango de fechas (`fecha_desde`/`fecha_hasta`); filtros combinables, se exige al menos uno.
- `actividad_tipo_listar` [lectura] (core): lista los tipos de actividad comercial disponibles.

### ARTICULO

- `articulo_buscar` [lectura] (core)
- `articulo_cambiar_tabla_precio` [critica] (core) — segura por defecto: simula salvo `simular=false`.
- `articulo_catalogo_listar` [lectura] (core) — marcas, familias o familias web segun `tipo`.
- `articulo_compra_consultar` [lectura] (core) — proveedores de un articulo, o ficha de compra si se indica `proveedor`.
- `articulo_ean_grabar` [escritura] (admin)
- `articulo_familia_guardar` [escritura] (core)
- `articulo_familiancc_tabla_guardar` [escritura] (core)
- `articulo_obtener` [lectura] (core) — ficha basica; `incluir` opcional añade info tecnica o imagen.
- `articulo_precio_cliente` [lectura] (core)
- `articulo_precio_oferta` [lectura] (admin)
- `articulo_ubicacion_guardar` [escritura] (admin)
- `tarifa_proveedor_actualizar` [critica] (core) - alta/actualiza `ARTICULP` por proveedor en lote y, si `actualizar_precio_venta=true`, recalcula el coste y precios de `ARTICUL` siguiendo la logica de `IMPTAR_U.pas`. Permite resolver el articulo por codigo, EAN o referencia de proveedor.

#### Actualizacion de tarifas de proveedor

`tarifa_proveedor_actualizar` recibe un proveedor y entre 1 y 500 lineas. Cada linea requiere `precio_base` y al menos uno de estos identificadores: `articulo`, `codigo_barras` o `referencia_proveedor`. Los descuentos pueden enviarse como `descuento1`..`descuento6` o mediante el array `descuentos`. En modificaciones, los campos no informados se conservan; en altas se aplican los valores por defecto de `IMPTAR_U.pas`. La llamada es atomica: ante un error se revierte el lote completo.

Ademas de `actualizar_precio_venta`, la herramienta replica cinco de las "Opciones Proceso" de la pantalla `IMPTAR_U.pas` que faltaban en el contrato publico (ver `revision-tarifa-proveedor-actualizar.md`):

- `actualizar_solo_si_sube_precio` (bool, por defecto `false`): con `actualizar_precio_venta=true`, omite el recalculo de venta de una linea si el coste neto nuevo es menor que el anterior (replica `B_MAS`). La tarifa de compra en `ARTICULP` se actualiza igualmente.
- `actualizar_solo_proveedor_principal` (bool, por defecto `false`): solo recalcula el precio de venta si el proveedor de la linea coincide con el proveedor principal del articulo (`ART_CODPRO`), replicando `B_PRINCIPAL`.
- `actualizar_solo_si_propio` (bool, por defecto `false`): solo recalcula el precio de venta si el articulo no esta marcado como no-propio (`ART_INDPROP<>'N'`), replicando `B_PROPIO`.
- `generar_etiquetas` (bool, por defecto `false`): si una linea cambia realmente el PVP, inserta una etiqueta en `ETIQUE`, replicando `B_ETIQUETAS`.
- `etiqueta_modelo` (entero, por defecto `0`): modelo de `MODETI` a usar con `generar_etiquetas`. `IMPTAR_U.pas` resuelve un modelo por defecto via `MODELO_ETIQUETA_ARTICUL`, funcion que no se ha podido localizar en las fuentes Delphi disponibles; por eso aqui se pide explicito (0 es el mismo valor de respaldo que usa el propio Delphi cuando esa resolucion automatica no encuentra nada).

Ademas, cuando `actualizar_precio_venta=true` y una linea informa `descripcion`, la herramienta ahora tambien sobrescribe `ARTICUL.ART_DESCRI` (la descripcion maestra del articulo), no solo `ARTICULP.ARTP_DESCRI` (la de la linea de tarifa) — replicando la mitad de `B_DESCRI` que antes faltaba.

**Dar de alta articulos nuevos (`dar_de_alta`).** Por defecto (`dar_de_alta=false`), una linea cuyo articulo no existe sigue lanzando error y revirtiendo el lote completo, igual que siempre. Con `dar_de_alta=true`, esa misma linea crea `ARTICUL` + `ARTICULP` en el mismo lote, replicando la rama `ELSE IF B_ALTA.Checked` de `IMPTAR_U.pas`. En ese caso la linea debe informar tambien `descripcion`, `seccion`, `tipo_iva`, `tipo_precio` y `unidad_medida`; `articulo` (el codigo) es opcional — ver "Codigo de articulo en altas" mas abajo. Campos opcionales solo para altas: `familia`, `subfamilia`, `tabla_precios`, `canon` (fuerza `tipo_precio='C'`, igual que Delphi), `tarifa`, `pvp` (PVP directo), `cantidad_pedido_minimo` y `norma`. Si la linea trae `codigo_barras`, tambien se inserta en `ARTICULC` al dar de alta. Una linea recien creada nunca pasa por el bloque de `actualizar_precio_venta` (en `IMPTAR_U.pas` ese bloque solo existe dentro de la rama "articulo ya existente"); sus precios de venta salen ya calculados desde el alta. El resultado añade el contador `articulos_creados` y cada linea trae `articulo_creado` (bool).

**Codigo de articulo en altas.** Cuando `dar_de_alta=true` y una linea no informa `articulo`, el codigo se resuelve en el mismo orden que `IMPTAR_U.pas:1727-1742`:

1. Si la linea informa `referencia_proveedor` y el lote tiene `usar_referencia_proveedor_como_codigo=true`, se usa esa referencia tal cual como `ART_CODART` (replica la casilla `B_REFPRO` "Codigo de Articulo = Referencia Proveedor" marcada). Si esta activo y la linea no trae `referencia_proveedor`, es error.
2. Si no, se autogenera: `seccion` (tal cual la informa la linea, normalmente 1 digito) + el `proveedor` del lote a un minimo de 4 digitos + un contador que ocupa el resto (replica `B_REFPRO` sin marcar). `digitos_codigo_articulo` (entero, por defecto `9`, entre `8` y `15`) fija el numero total de digitos del codigo, igual que `B_DIGITOS` en la pantalla. `numerador_inicial` (entero, por defecto `0`) fija el valor inicial del contador, igual que `NumInicial`. El contador se incrementa automaticamente cuando el codigo generado ya existe y se comparte para todas las lineas del lote sin reiniciarse entre ellas (igual que `CONTADOR` en Delphi, que solo se inicializa una vez por ejecucion).

Un `articulo` explicito en la linea siempre tiene prioridad sobre ambas vias, igual que en `IMPTAR_U.pas`.

Fuera de alcance del contrato actual: `B_RECALCULO` (esta herramienta no escribe codigos de barras salvo el que ya se use para localizar/dar de alta el articulo; el resto vive en `articulo_ean_grabar`) y `B_CABECERA` (es sobre parsear un fichero Excel/CSV subido; el MCP recibe `lineas` ya como JSON estructurado).

Con `actualizar_precio_venta=false` (por defecto) solo se modifica `ARTICULP`. Con `true`, se calcula el coste neto aplicando los seis descuentos del proveedor y se recalculan `ART_PREBAS`, `ART_PRECOS`, precios de venta y PVP en `ARTICUL` — para lineas sobre articulos ya existentes; ver el parrafo anterior para altas.

### CLIENTE

- `cliente_actualizar` [escritura] (core)
- `cliente_buscar` [lectura] (core)
- `cliente_tipo_venta` [lectura] (admin)
- `cliente_ultimas_ventas` [lectura] (core)

### COMERCIAL / AGENTES

Herramientas de solo lectura orientadas a analizar el rendimiento de representantes comerciales. Cruzan ventas de `CABDOCV`/`DETMOV`, rentabilidad por linea, actividades de `ACTIVI`, tipos de actividad de `TIPACT`, clientes de `CLIEN` y agentes de `REPRESE`.

- `comercial_agente_actividades` [lectura] (core) — resume actividades de un representante por periodo, agrupadas por tipo y cliente, con ultimas actividades.
- `comercial_agente_analisis` [lectura] (core) — vision 360 de un agente: ventas, margen, rentabilidad, actividades, clientes top y productos top.
- `comercial_agente_clientes` [lectura] (core) — ranking de clientes vendidos por agente con venta neta, coste, margen, rentabilidad y actividades asociadas.
- `comercial_agente_productos` [lectura] (core) — ranking de productos vendidos por agente con unidades, venta neta, coste, margen y rentabilidad.
- `comercial_agente_visitas_ventas_clientes` [lectura] (core) — cruza clientes vendidos y clientes visitados para calcular venta por visita, margen por visita, ultima visita, dias desde la ultima visita y clasificacion comercial.
- `comercial_agente_visitas_ventas_oportunidades` [lectura] (core) — clasifica oportunidades y riesgos comerciales: clientes sobrevisitados, alto valor poco visitado, venta sin visita, visitas sin venta y clientes equilibrados.

La comparativa visitas/ventas usa por defecto las actividades comerciales del periodo como contacto/visita. Si se quiere restringir solo a tipos cuyo texto contenga `VISIT`, puede usarse `solo_visitas=true`; tambien se pueden filtrar codigos concretos con `tipos_actividad`. Los umbrales `visitas_alta_desde` y `visitas_baja_hasta` permiten adaptar la clasificacion a la cadencia comercial de la empresa.

### CARTERA

Herramientas de solo lectura para analizar efectos, remesas y riesgo de credito. Se apoyan en `CABDOCVE`, `REMESA` y `CLIEN`, tomando como referencia Delphi `ANAEFE_U/ANAEFE_UR`, `REMESA_UDM`, `MNTREM_U` y `RIESGO_U`. En efectos, el pendiente se calcula como `importe + gastos - cobrado` cuando `CBVE_FECCAN IS NULL`; un efecto se considera remesado cuando `CBVE_EJEREM` o `CBVE_CODREM` son distintos de cero.

- `cartera_efectos_detalle` [lectura] (core) — lista efectos de `CABDOCVE` con documento, cliente, tipo de efecto, vencimiento, importes, cobrado, pendiente, estado y remesa.
- `cartera_efectos_pendientes_resumen` [lectura] (core) — resume efectos pendientes/vencidos por tipo de efecto, situacion y estado de remesa.
- `cartera_efectos_por_cliente` [lectura] (core) — agrupa la deuda viva por cliente/subcliente, separando vencido, remesado, no remesado y proximo vencimiento.
- `cartera_pendiente_remesar` [lectura] (core) — devuelve efectos pendientes sin remesa asignada, candidatos a preparar remesa.
- `cartera_remesas_resumen` [lectura] (core) — resume `REMESA` y sus efectos vinculados en `CABDOCVE`, con banco, situacion, total y pendiente.
- `cartera_riesgo_cliente` [lectura] (core) — calcula el riesgo actual de credito de un cliente replicando la regla `RIESGO_ACTUAL`: parte de `CLI_RIESGO` y descuenta albaranes pendientes, efectos vivos, facturas contado pendientes y pedidos si el parametro `RIEPED` esta activo.
- `cartera_riesgo_clientes_resumen` [lectura] (core) — calcula el riesgo de credito para un rango de clientes, con opcion `solo_excedidos`.

Estas funciones son distintas de `negocio_clientes_riesgo`: `negocio_clientes_riesgo` analiza deterioro comercial entre periodos; `cartera_riesgo_*` calcula riesgo de credito operativo contra el limite concedido del cliente.

### COMPRA / DASHBOARD

- `compras_articulos_pendientes_recibir` [lectura] (core) — agrupa por articulo las cantidades pendientes de recibir desde pedidos de compra `CABORC`/`DETORC`.
- `compras_documentos_pendientes_resumen` [lectura] (core) — resume documentos de proveedor pendientes desde `CABDOCM`.
- `compras_pedidos_pendientes_resumen` [lectura] (core) — resume ordenes de compra pendientes desde `CABORC`/`DETORC`.
- `compras_resumen` [lectura] (core) — resume compras del periodo usando movimientos de almacen.
- `clientes_acciones_recomendadas` [lectura] (core) — recomienda acciones comerciales sobre clientes que caen, desaparecen o deterioran margen.
- `clientes_resumen` [lectura] (core) — resume clientes en riesgo comercial, bajadas de venta y concentracion.
- `dashboard_acciones_recomendadas` [lectura] (core) — consolida acciones priorizadas de ventas, clientes, stock, pendientes y tesoreria.
- `dashboard_alertas` [lectura] (core) — consolida alertas de rentabilidad, clientes y stock.
- `dashboard_filtros` [lectura] (core) — devuelve catalogos para poblar filtros del dashboard.
- `dashboard_resumen` [lectura] (core) — resume ventas, rentabilidad, clientes, stock e insights accionables.
- `dashboard_series_temporales` [lectura] (core) — devuelve series agregadas para graficas del dashboard.
- `documentos_pendientes_resumen` [lectura] (core) — resume albaranes, facturas y creditos pendientes.
- `pedidos_acciones_recomendadas` [lectura] (core) — recomienda acciones sobre pedidos, presupuestos y documentos pendientes.
- `pedidos_resumen` [lectura] (core) — resume pedidos y presupuestos de venta.
- `proveedores_resumen` [lectura] (core) — resume ventas y compras agrupadas por proveedor.
- `stock_acciones_recomendadas` [lectura] (core) — recomienda acciones sobre stock parado, sobrestock y compras sin salida.
- `stock_resumen` [lectura] (core) — resume stock, valor inmovilizado y alertas de rotacion.
- `tesoreria_acciones_recomendadas` [lectura] (core) — recomienda acciones sobre cierres de caja y operaciones revisables desde `OPECAJ`.
- `tesoreria_resumen` [lectura] (core) — resume operaciones de caja/tesoreria desde `OPECAJ`.
- `ventas_acciones_recomendadas` [lectura] (core) — recomienda acciones sobre lineas y articulos con margen negativo.
- `ventas_resumen` [lectura] (core) — resume ventas y documentos apoyandose en rentabilidad y ANADOC.

### ENTRADA

- `entrada_almacen_crear` [critica] (core) — crea una entrada de almacen desde cabecera y lineas estructuradas, con actualizacion de existencias.
- `entrada_pedidos_relacionados` [lectura] (admin)

### ETIQUETA / RECUENTO / FALTA

- `etiqueta_gestion` [escritura] (core) — `accion=listar|grabar|borrar`.
- `recuento_gestion` [escritura] (core) — `accion=listar|grabar|borrar`.
- `falta_gestion` [escritura] (core) — `accion=listar|grabar|borrar`.

### INTEGRACION

- `integracion_coinfer_stock` [lectura] (integrations)

### MOSTRADOR

- `mostrador_cobrar` [critica] (core)
- `mostrador_venta_gestion` [critica] (core) — `accion=guardar|borrar|cargar_pedido`.

### OFERTA

- `oferta_crear` [escritura] (core) — crea una oferta con cabecera y lineas de articulos.

### ORDEN DE COMPRA

- `orden_compra_cerrar` [critica] (core) — cierra manualmente una orden de compra (`CABORC`) y todas sus lineas.
- `orden_compra_propuesta_pedidos_cliente` [lectura] (core) — propone cantidades a pedir desde pedidos de cliente, replicando criterios de `GENPEDC` y stock disponible, sin crear `CABORC`.
- `orden_compra_propuesta_stock_minimo` [lectura] (core) — propone cantidades a pedir desde stock minimo/maximo, replicando criterios de `GENPEDM`, proveedor, unidades por paquete y stock disponible, sin crear `CABORC`.

### PEDIDO

- `pedido_albaranar` [critica] (core)
- `pedido_cerrar` [critica] (core)
- `pedido_crear` [escritura] (core)
- `pedido_detalle` [lectura] (core)
- `pedido_enviar` [critica] (core)
- `pedido_finalizar` [critica] (core)
- `pedido_linea_mover` [escritura] (core)
- `pedido_listar` [lectura] (core)
- `pedido_marcar_preparado` [escritura] (core)
- `pedido_pdf_gestion` [escritura] (core) — `accion=generar|obtener`.
- `pedido_retirada_actualizar` [escritura] (admin)
- `pedido_situacion_actualizar` [escritura] (admin)

### PRECIO

- `precio_tabla_listar` [lectura] (admin)

### PROVEEDOR

- `proveedor_buscar` [lectura] (core) — busca proveedores por `proveedor`, nombre comercial, nombre fiscal, nombre abreviado, CIF o fecha de alta (`fecha_alta`, `fecha_alta_desde`, `fecha_alta_hasta`) y devuelve la ficha completa del maestro `PROVEE`.

### STOCK

- `stock_consultar` [lectura] (core)
- `stock_regularizar` [critica] (core)
- `stock_trasvasar` [critica] (core)

### VENTA

- `venta_documento_crear` [critica] (core)
- `venta_documentos_detalle` [lectura] (core) — lista cabeceras de venta tipo ANADOC por periodo con totales, cliente, documento, forma de pago/cobro y categoria (`factura`, `factura_contado`, `factura_tickets`, `credito`, `albaran_pendiente`, etc.).
- `venta_documentos_resumen` [lectura] (core) — resume documentos por `cliente`, `ejercicio`, `tipo_documento`, `categoria`, `centro`, `mes`, `trimestre`, `dia_semana`, `hora`, `zona_cliente`, `representante`, `forma_pago`, `situacion`, `moneda`, `poblacion` o `tarifa`.
- `venta_documentos_abc` [lectura] (core) — genera un ABC sobre el resumen documental, por defecto por cliente y ordenado por total.
- `negocio_clientes_riesgo` [lectura] (core) — detecta clientes que bajan, desaparecen, empeoran margen, tienen rentabilidad negativa o concentran demasiada venta.
- `negocio_cuadro_mando` [lectura] (core) — devuelve una vision ejecutiva combinando ventas/margen, alertas de rentabilidad, clientes en riesgo y stock/rotacion.
- `negocio_diagnostico_cambios` [lectura] (core) — explica por que cambian ventas o margen entre periodos, con foco opcional por familia, articulo, cliente u otra dimension, desglosando articulos, clientes, unidades, precio medio, coste medio y lineas negativas.
- `negocio_stock_rotacion` [lectura] (core) — analiza stock actual, valor inmovilizado, ventas, compras y rotacion para detectar stock sin ventas, sobrestock, baja rotacion y compras sin salida.
- `negocio_stock_tendencias` [lectura] (core) — compara periodos de stock/ventas/compras y detecta articulos donde sube el stock mientras bajan ventas o margen.
- `negocio_tendencias` [lectura] (core) — compara ventas y rentabilidad entre periodos por `familia`, `subfamilia`, `articulo`, `cliente` u otra dimension, detectando subidas, bajadas, apariciones, desapariciones y deterioros de margen.
- `venta_alertas_rentabilidad` [lectura] (core) — detecta alertas estilo ANAVEN: lineas negativas, articulos con alguna linea negativa, articulos negativos agregados y grupos bajo umbral.
- `venta_rentabilidad_lineas` [lectura] (core) — analiza lineas de venta por rango de fechas, tipos de documento, articulo, proveedor, cliente, representante, centro u oferta; devuelve venta neta, coste, margen y rentabilidad por linea usando la misma regla de coste configurada en Faro.
- `venta_rentabilidad_resumen` [lectura] (core) — agrega esas lineas por `articulo`, `seccion`, `familia`, `subfamilia`, `proveedor`, `cliente`, `representante`, `centro`, `mes`, `dia_semana`, `tipo_documento` o `marca`, ordenando por venta, coste, margen, rentabilidad, unidades o lineas.

Las funciones documentales usan `politica="ventas_reales"` por defecto: cuentan facturas y creditos, suman solo albaranes pendientes no enlazados a factura, y excluyen tickets, pedidos, presupuestos y pedidos servidos para evitar duplicar o anticipar ventas. En `agrupar_por="cliente"` agrupan por codigo principal de cliente; solo el cliente `99999` conserva separado cada subcliente contado (`99999/subcliente`). Tambien admiten filtros `zona_desde`/`zona_hasta` sobre `CLIEN.CLI_ZONA`. Si se necesita auditoria documental pura, puede usarse `politica="documentos"` con `tipos_documento` explicitos.

Las funciones de rentabilidad usan `moneda="E"` por defecto y aceptan `tipos_documento` como lista de codigos (`T`, `F`, `A`, `C`, `P`, `R`, `S`). Cuando se agrupa por `familia` o `subfamilia`, `tipo_familia="ncc"` usa la familia NCC de informacion adicional (`FAMNC`/`FAMNCC`) por defecto; tambien admite `propia` (`ART_CODFAM`/`ART_SUBFAM`) y `cooperativa` (`ART_AGRUP1/2/3`). El probador web genera automaticamente sus formularios desde el contrato y las muestra en el grupo **Ventas / rentabilidad**.

## Contrato publico (v2)

El borde MCP no expone abreviaturas de base de datos (`codart`, `codcli`, `ejerci`, `numdoc`, etc.): usa nombres de dominio (`articulo`, `cliente`, `ejercicio`, `numero`, `cantidad`, `unidad_medida`...) traducidos internamente por `translate_public_arguments()`. Los antiguos protocolos de texto separados por `|`/`#` (clientes, pedidos, trasvases, ventas) tampoco forman parte del contrato publico: se usan objetos/arrays JSON estructurados. Toda respuesta de `tools/call` usa el sobre uniforme `ok/data/warnings/meta` o `ok/error/warnings/meta`.

## Seguridad y auditoria

`FARO_MCP_ACCESS_LEVEL` admite `read`, `write` y `critical` (**por defecto**), de forma independiente al perfil funcional (`FARO_MCP_TOOL_PROFILE`): el perfil decide que herramientas existen, el nivel de acceso decide cuales pueden ejecutarse. Las lecturas siguen disponibles con `read`; las escrituras ordinarias exigen `write`; cobros, documentos fiscales, entradas de almacen, cierres/albaranados/finalizaciones, stock manual/trasvases, borrado de venta y cambios reales de precios exigen `critical`.
Si la variable no esta definida (o esta vacia), el runtime usa `critical`. Si contiene un valor desconocido, cae deliberadamente a `read` para no elevar permisos por un error de configuracion.

Todas las mutaciones se auditan en JSONL. Antes de ejecutar una escritura se registra un evento `started`; si `FARO_MCP_AUDIT_REQUIRED=true` y el log no es escribible, la operacion se bloquea con `AUDIT_ERROR`. Los secretos se redactan y no se guardan resultados completos.

Configuracion recomendada:

```powershell
$env:FARO_MCP_ACCESS_LEVEL = "critical"  # valor por defecto; read | write | critical
$env:FARO_MCP_ACTOR = "chatgpt-produccion"
$env:FARO_MCP_CLIENT_ID = "erp-mcp"
$env:FARO_MCP_AUDIT_LOG = "C:\FaroERP\logs\faro_mcp_audit.jsonl"
$env:FARO_MCP_AUDIT_REQUIRED = "true"
$env:FARO_MCP_AUDIT_READS = "false"
```

## SQL legacy interno

Las implementaciones de busqueda/apertura de consulta SQL se conservan internamente por compatibilidad, pero ya no se exportan como herramientas MCP. Solo permiten una sentencia `SELECT`/CTE de lectura. `FARO_SQL_MAX_ROWS` limita las filas devueltas (500 por defecto, maximo 5000).

La ejecucion SQL interna de escritura tambien es interna y permanece deshabilitada por defecto. Solo se habilita de forma explicita:

```powershell
$env:FARO_ALLOW_INTERNAL_SQL_WRITE = "true"
```

Incluso habilitada, solo permite DML/`EXECUTE PROCEDURE`; DDL, control transaccional, comentarios y multiples sentencias se rechazan. Para funcionalidad nueva se deben preferir siempre herramientas MCP tipadas.

## Documentacion adicional

- **Manual de usuario**: `Manual_usuario_MCP_Faro.docx` / `.pdf` — guia orientada a usuario final del Probador MCP y del catalogo de herramientas.
- **Ayuda en vivo**: `/ayuda` en el Probador MCP, o `faro_mcp.tool_definitions()` en Python — catalogo completo siempre sincronizado con el codigo.

## Historial de desarrollo

`HISTORIAL_FASES.md` consolida en un unico documento el registro cronologico completo de las fases de migracion, limpieza y ampliacion del dashboard, incluyendo cada decision de fidelidad frente al Delphi/DataSnap original, bugs heredados corregidos conscientemente y desviaciones deliberadas por seguridad. Consulta ese fichero para el "por que" de cada decision; este README solo documenta el estado vigente.
