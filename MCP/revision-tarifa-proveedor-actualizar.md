# Revision tecnica de tarifa_proveedor_actualizar

Este documento conserva la revision funcional de la herramienta
`tarifa_proveedor_actualizar`, referenciada por el README, para que las
decisiones de contrato no dependan de notas externas.

## Referencias Delphi

- `FuentesDelphi/IMPTAR_U.pas`: pantalla y proceso historico de importacion de
  tarifas de proveedor.
- `FuentesDelphi/IMPTAR_U.dfm`: controles de opciones del proceso.
- `DataModules/ARTICUL_UDM.pas`: alta y modificacion de articulos.

## Opciones Proceso replicadas

La herramienta MCP replica las opciones relevantes de la pantalla Delphi como
parametros JSON estructurados:

- `actualizar_precio_venta`: recalcula coste, precios de venta y PVP en
  `ARTICUL` para articulos existentes.
- `actualizar_solo_si_sube_precio`: replica `B_MAS`; no recalcula venta si el
  coste neto nuevo baja.
- `actualizar_solo_proveedor_principal`: replica `B_PRINCIPAL`; solo recalcula
  si el proveedor del lote coincide con `ART_CODPRO`.
- `actualizar_solo_si_propio`: replica `B_PROPIO`; omite articulos marcados
  como no propios.
- `generar_etiquetas`: replica `B_ETIQUETAS`; genera etiqueta cuando cambia el
  PVP.
- `etiqueta_modelo`: modelo explicito de `MODETI`. El resolutor automatico
  `MODELO_ETIQUETA_ARTICUL` no aparece en las fuentes disponibles, por lo que
  `0` se mantiene como valor de respaldo.
- `dar_de_alta`: replica la rama `B_ALTA`; crea `ARTICUL` y `ARTICULP` en el
  mismo lote si el articulo no existe.
- `usar_referencia_proveedor_como_codigo`: replica `B_REFPRO` marcada; usa la
  referencia del proveedor como codigo de articulo durante altas.
- `digitos_codigo_articulo`: replica `B_DIGITOS`; controla la longitud total
  del codigo autogenerado.
- `numerador_inicial`: replica `NumInicial`; fija el contador inicial para
  codigos autogenerados.

## Alta de articulos

Con `dar_de_alta=true`, si una linea no trae `articulo`, el codigo se resuelve
igual que en `IMPTAR_U.pas:1727-1742`:

1. Si `usar_referencia_proveedor_como_codigo=true`, se exige
   `referencia_proveedor` y se usa tal cual como `ART_CODART`.
2. En caso contrario, se genera como `seccion` + `proveedor` a cuatro digitos +
   contador, respetando `digitos_codigo_articulo` y `numerador_inicial`.

Un `articulo` explicito en la linea siempre tiene prioridad.

Para crear `ARTICUL`, la linea debe informar `descripcion`, `seccion`,
`tipo_iva`, `tipo_precio` y `unidad_medida`, ademas del identificador de
articulo resuelto. Tambien puede informar `familia`, `subfamilia`,
`tabla_precios`, `canon`, `tarifa`, `pvp`, `cantidad_pedido_minimo`, `norma` y
`codigo_barras`.

## Limites deliberados

- `B_RECALCULO` queda fuera de esta herramienta: los codigos de barras
  adicionales se gestionan con `articulo_ean_grabar`.
- `B_CABECERA` pertenece al parseo de ficheros Excel/CSV; el MCP recibe lineas
  JSON ya estructuradas.
- Stock minimo/maximo/inicial, caracteristicas tecnicas, marca/familia no
  catalogada, blister y el limite `NUEVES` no forman parte del contrato actual
  porque dependen de columnas de fichero que no tienen equivalente estable en
  `lineas`.

## Seguridad

`tarifa_proveedor_actualizar` esta clasificada como `critical` porque puede
modificar costes, tarifas de compra, precios de venta, PVP, etiquetas y altas
de articulos en lote. La operacion es atomica: ante error se revierte el lote.
