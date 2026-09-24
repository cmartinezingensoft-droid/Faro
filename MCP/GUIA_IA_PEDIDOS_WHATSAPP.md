# Guia IA para generar pedidos desde WhatsApp

## Objetivo

Convertir un texto libre recibido por WhatsApp en un borrador de pedido de cliente, usando siempre Faro/MCP como fuente de verdad para clientes, articulos, precios, historico y creacion del documento.

Ejemplo de entrada:

```text
Soy Edifesa, quiero 1 rollo de alambre y 2 botes de pintura para exterior
```

Resultado esperado:

```json
{
  "cliente": {
    "cliente": 100,
    "subcliente": 0,
    "nombre": "EDIFESA S.L.",
    "confianza": 0.97
  },
  "lineas": [
    {
      "cantidad": 1,
      "texto_original": "1 rollo de alambre",
      "articulo": "814943103",
      "descripcion": "ALAMBRE GALVANIZADO ROLLO 100M",
      "confianza": 0.91
    },
    {
      "cantidad": 2,
      "texto_original": "2 botes de pintura para exterior",
      "articulo": "123456789",
      "descripcion": "PINTURA FACHADA BLANCA 15L",
      "confianza": 0.86
    }
  ],
  "accion_recomendada": "crear_borrador"
}
```

La IA no debe inventar codigos de articulo ni confirmar pedidos finales por si sola. Su funcion principal es entender el lenguaje humano, estructurar la intencion y ayudar a ordenar candidatos.

## Principios de diseno

- La IA extrae estructura, Faro decide con datos.
- Fuse.js puede usarse como buscador difuso textual, pero no sustituye al historico comercial.
- El historico de ventas del cliente debe prevalecer cuando existan varios articulos parecidos.
- Toda coincidencia debe tener explicacion: texto, sinonimo, historico, unidad, stock, precio o compra reciente.
- Si la confianza no es alta, se crea un borrador revisable o se pide confirmacion.
- Las correcciones humanas se guardan para mejorar siguientes resoluciones.

## Flujo general

1. Recibir el WhatsApp con metadatos: texto, telefono, fecha, adjuntos si existen.
2. Normalizar el texto: minusculas, espacios, acentos, abreviaturas comunes.
3. Extraer estructura con IA: cliente mencionado, lineas, cantidades, unidades, atributos y observaciones.
4. Resolver cliente con `cliente_buscar` y, si existe, por telefono/origen.
5. Consultar historico con `cliente_ultimas_ventas`.
6. Buscar candidatos de articulo con `articulo_buscar`.
7. Reforzar la busqueda con Fuse.js sobre catalogo/index local de articulos y sinonimos.
8. Reordenar candidatos con scoring ponderado: texto + historico + sinonimos + unidad + stock + recencia.
9. Calcular confianza por linea y confianza global.
10. Crear borrador o pedido con `pedido_crear` solo cuando proceda.
11. Guardar decision/correccion para aprendizaje futuro.

## Extraccion inicial con IA

La IA debe devolver solo JSON estructurado. No debe llamar articulo a lo que todavia es texto del cliente.

Formato recomendado:

```json
{
  "cliente_mencionado": "Edifesa",
  "observaciones": "",
  "lineas_texto": [
    {
      "cantidad": 1,
      "unidad_texto": "rollo",
      "producto_texto": "alambre",
      "atributos": [],
      "texto_original": "1 rollo de alambre"
    },
    {
      "cantidad": 2,
      "unidad_texto": "botes",
      "producto_texto": "pintura",
      "atributos": ["exterior"],
      "texto_original": "2 botes de pintura para exterior"
    }
  ],
  "requiere_revision": false,
  "motivos_revision": []
}
```

Reglas de extraccion:

- Interpretar cantidades numericas y escritas: `dos`, `media docena`, `un par`.
- Mantener la unidad textual original: `rollo`, `bote`, `caja`, `saco`, `lata`, `cubo`.
- Separar producto de atributos: color, medida, litros, kilos, marca, uso interior/exterior.
- Extraer frases como `lo de siempre`, `como la otra vez`, `igual que el ultimo pedido` como indicadores de historico.
- No completar marcas, formatos ni medidas que no aparezcan salvo que el historico lo resuelva con confianza alta.

Prompt base recomendado:

```text
Extrae de este WhatsApp un posible pedido comercial.
Devuelve solo JSON valido.
No inventes codigos de articulo.
No elijas articulos definitivos.
Separa cliente, lineas, cantidades, unidades, producto, atributos y observaciones.
Marca requiere_revision=true si falta cantidad, cliente o producto, o si el texto contiene ambiguedad fuerte.
```

## Resolucion del cliente

Usar `cliente_buscar` con varias estrategias:

- Nombre literal mencionado.
- Nombre normalizado sin forma juridica: `S.L.`, `SA`, `S.L.U.`.
- Telefono de WhatsApp si se dispone de relacion cliente-telefono.
- CIF/NIF si aparece en el texto.
- Alias o nombre comercial.
- Historico reciente del telefono/contacto si existe.

Scoring sugerido para cliente:

| Factor | Peso |
| --- | ---: |
| Coincidencia por telefono | 0.40 |
| Coincidencia exacta nombre/CIF | 0.30 |
| Coincidencia difusa nombre | 0.15 |
| Cliente activo y con ventas recientes | 0.10 |
| Comercial/zona/origen coherente | 0.05 |

Umbrales:

- `>= 0.90`: cliente resuelto.
- `0.70 - 0.89`: cliente probable, pedir confirmacion visual.
- `< 0.70`: no crear pedido automaticamente.

## Indice Fuse.js de articulos

Fuse.js debe trabajar sobre un indice preparado, no directamente sobre campos pobres.

Objeto recomendado por articulo:

```json
{
  "articulo": "814943103",
  "descripcion": "ALAMBRE GALVANIZADO ROLLO 100M",
  "familia": "FERRETERIA",
  "subfamilia": "ALAMBRES",
  "marca": "",
  "unidad_medida": "ROLLO",
  "codigo_barras": ["843..."],
  "sinonimos": ["hilo galvanizado", "bobina alambre", "rollo alambre"],
  "busqueda": "alambre galvanizado rollo 100m hilo bobina ferreteria",
  "activo": true
}
```

Configuracion inicial:

```ts
import Fuse from "fuse.js";

const fuse = new Fuse(articulos, {
  keys: [
    { name: "descripcion", weight: 0.45 },
    { name: "busqueda", weight: 0.25 },
    { name: "sinonimos", weight: 0.20 },
    { name: "familia", weight: 0.05 },
    { name: "codigo_barras", weight: 0.05 }
  ],
  includeScore: true,
  ignoreLocation: true,
  threshold: 0.35,
  minMatchCharLength: 2
});
```

Notas:

- En Fuse.js, score menor significa mejor coincidencia.
- Convertir el score textual a puntuacion positiva con `scoreTexto = 1 - scoreFuse`.
- Para catalogos grandes, Fuse debe estar en backend o en un servicio local, no en una pantalla React cargando todo sin control.
- La tabla `SINONIMO` puede alimentar el campo `sinonimos` si la relacion funcional esta validada.

## Sinonimos y normalizacion

Mantener un diccionario de sinonimos de negocio:

```json
{
  "alambre": ["hilo", "cable", "bobina", "rollo alambre"],
  "pintura exterior": ["pintura fachada", "revestimiento exterior", "pintura intemperie"],
  "bote": ["lata", "envase", "cubo", "bidon"],
  "rollo": ["bobina", "carrete"]
}
```

Normalizaciones utiles:

- Quitar acentos para busqueda, pero conservar texto original.
- Unificar plurales simples: `botes` -> `bote`, `rollos` -> `rollo`.
- Detectar unidades: `kg`, `kilos`, `l`, `litros`, `m`, `metros`, `mm`.
- Expandir abreviaturas frecuentes de clientes y vendedores.
- Separar medidas del texto: `15L`, `15 l`, `15 litros`.

## Historico de ventas del cliente

`cliente_ultimas_ventas` debe usarse para construir un perfil temporal del cliente.

Estructura logica recomendada:

```json
{
  "articulo": "123456789",
  "descripcion": "PINTURA FACHADA BLANCA 15L",
  "veces_comprado": 8,
  "fecha_ultima_compra": "2026-08-31",
  "cantidad_media": 2,
  "unidad_habitual": "BOTE",
  "familia": "PINTURAS"
}
```

Score de historico sugerido:

```text
scoreHistorico =
  frecuencia_normalizada * 0.45
+ recencia_normalizada * 0.30
+ coincidencia_familia * 0.15
+ coincidencia_unidad * 0.10
```

Casos especiales:

- Si el texto contiene `lo de siempre`, aumentar mucho el peso del historico.
- Si el texto contiene `como la otra vez`, priorizar la ultima compra compatible.
- Si el cliente nunca compro articulos similares, usar ranking global/familia, pero bajar confianza.
- Si el articulo habitual esta inactivo o sin stock, mostrar alternativa y motivo.

## Scoring final de articulos

Para cada linea de WhatsApp, combinar candidatos de:

- `articulo_buscar`.
- Fuse.js sobre indice de articulos/sinonimos.
- Historico del cliente.
- Articulos equivalentes o alternativos si existen.

Formula inicial:

```text
scoreFinal =
  scoreTexto * 0.35
+ scoreHistoricoCliente * 0.30
+ scoreSinonimosFamilia * 0.15
+ scoreUnidadFormato * 0.10
+ scoreStockActivo * 0.05
+ scoreRecenciaGlobal * 0.05
```

Ajustes:

- Si el texto contiene `lo de siempre` o `como la otra vez`:

```text
scoreFinal =
  scoreTexto * 0.20
+ scoreHistoricoCliente * 0.55
+ scoreSinonimosFamilia * 0.10
+ scoreUnidadFormato * 0.10
+ scoreStockActivo * 0.05
```

- Si aparece EAN/codigo exacto, priorizar coincidencia exacta salvo articulo inactivo.
- Si aparece marca o medida, penalizar candidatos que no la cumplan.
- Si varios candidatos quedan muy cerca, no decidir automaticamente.

## Umbrales de decision

Por linea:

| Confianza | Accion |
| --- | --- |
| `>= 0.88` | Aceptar candidato para borrador |
| `0.70 - 0.87` | Mostrar candidato principal y alternativas |
| `< 0.70` | Requiere revision manual |

Global:

| Caso | Accion |
| --- | --- |
| Cliente resuelto y todas las lineas `>= 0.88` | Crear borrador con `pedido_crear` |
| Cliente resuelto y alguna linea dudosa | Crear prepedido visual/no definitivo |
| Cliente dudoso | No crear pedido; pedir seleccion de cliente |
| Articulo dudoso y texto ambiguo | Pedir aclaracion o revision |

Regla de proximidad:

- Si el primer candidato supera al segundo por menos de `0.08`, marcar la linea como dudosa aunque el score sea alto.

## Creacion del pedido

Crear pedido solo tras resolver cliente y lineas. Al inicio se recomienda crear pedidos como borradores o presupuestos si el contrato lo permite.

Usar `pedido_crear` con:

- Cliente y subcliente resueltos.
- Lineas con articulo real, cantidad y precio calculado por Faro.
- Comentarios con referencia al origen WhatsApp.
- Observaciones extraidas: entrega, obra, urgencia.

Comentario recomendado:

```text
Pedido generado desde WhatsApp. Texto original: "Soy Edifesa, quiero 1 rollo de alambre y 2 botes de pintura para exterior"
```

No enviar, cerrar, albaranar ni finalizar automaticamente desde este flujo inicial.

## Aprendizaje por correccion

Cada validacion humana debe generar un registro de aprendizaje.

Datos minimos:

```json
{
  "texto_whatsapp": "2 botes de pintura para exterior",
  "cliente": 100,
  "subcliente": 0,
  "producto_texto": "pintura para exterior",
  "unidad_texto": "botes",
  "articulo_sugerido": "111",
  "articulo_confirmado": "123456789",
  "usuario": "operador",
  "fecha": "2026-09-18",
  "motivo": "correccion_manual"
}
```

Usos posteriores:

- Aumentar peso historico cliente-texto.
- Crear sinonimo si se repite en varios clientes.
- Crear alias especifico del cliente si solo aplica a uno.
- Ajustar penalizaciones por unidad/formato.

## Errores frecuentes a controlar

- Cliente no identificado: texto empieza por `soy Pepe`, pero Pepe puede ser contacto, no razon social.
- Producto sin cantidad: `mandame pintura exterior`.
- Cantidad sin articulo: `ponme dos mas`.
- Unidad ambigua: `bote grande`, `rollo pequeno`, `caja`.
- Marca omitida: el cliente compra siempre una marca, pero no la menciona.
- Medida omitida: `pintura exterior` puede ser 4L, 15L o 20L.
- Articulo inactivo o sin stock.
- Varios articulos equivalentes con score parecido.
- Mensaje con varias intenciones: pedido + consulta + reclamacion.

## Funciones MCP actuales a utilizar

- `cliente_buscar`: resolucion del cliente.
- `cliente_ultimas_ventas`: historico de compra y preferencia del cliente.
- `articulo_buscar`: candidatos iniciales por texto/codigo.
- `articulo_obtener`: validacion de ficha del articulo elegido.
- `articulo_precio_cliente`: precio comercial real para el cliente.
- `stock_consultar`: desempate por disponibilidad si aplica.
- `pedido_crear`: creacion final del borrador/pedido.
- `pedido_detalle`: verificacion posterior si se crea documento.

## Funciones MCP nuevas recomendadas

Estas funciones no son imprescindibles para una primera prueba, pero harian el sistema mucho mas robusto.

### `whatsapp_pedido_preparar`

Lectura/orquestacion. No crea pedido. Recibe texto y telefono, devuelve cliente probable, lineas interpretadas, candidatos y scoring.

Entrada:

```json
{
  "texto": "Soy Edifesa, quiero 1 rollo de alambre y 2 botes de pintura para exterior",
  "telefono": "+34...",
  "max_candidatos": 5
}
```

Salida:

```json
{
  "cliente": {},
  "lineas": [],
  "confianza_global": 0.86,
  "requiere_revision": true,
  "motivos_revision": []
}
```

### `articulo_resolver_texto_cliente`

Lectura. Resuelve una linea de texto contra articulos reales, mezclando `articulo_buscar`, sinonimos, Fuse e historico del cliente.

Entrada:

```json
{
  "cliente": 100,
  "subcliente": 0,
  "texto": "botes de pintura para exterior",
  "cantidad": 2,
  "unidad_texto": "botes",
  "max_candidatos": 5
}
```

Salida:

```json
{
  "candidatos": [
    {
      "articulo": "123456789",
      "descripcion": "PINTURA FACHADA BLANCA 15L",
      "score_final": 0.91,
      "score_texto": 0.78,
      "score_historico": 0.96,
      "motivos": ["comprado 8 veces por el cliente", "coincide con pintura exterior"]
    }
  ]
}
```

### `cliente_resolver_identidad`

Lectura. Resolver cliente por texto, telefono, alias, CIF y actividad reciente. Evita que cada cliente de IA implemente sus propias reglas.

### `aprendizaje_pedido_whatsapp_grabar`

Escritura controlada. Guarda correcciones de usuario para mejorar sinonimos, alias cliente-texto y ranking futuro.

### `articulo_indice_busqueda_exportar`

Lectura. Exporta un indice optimizado para Fuse.js o para un motor futuro como Typesense/Meilisearch.

Debe incluir:

- Codigo de articulo.
- Descripcion.
- Familia/subfamilia.
- Unidad.
- Sinonimos.
- EAN/codigos de barras.
- Activo/inactivo.
- Campos de busqueda precompuestos.

## Primera version recomendada

Implementar en este orden:

1. Extraccion IA a JSON.
2. Resolucion de cliente con `cliente_buscar`.
3. Busqueda de articulos con `articulo_buscar`.
4. Reordenacion por `cliente_ultimas_ventas`.
5. Indice Fuse local con descripcion, familia, unidad y sinonimos.
6. Pantalla de revision con candidato principal y alternativas.
7. Creacion con `pedido_crear` solo tras confirmacion.
8. Registro de correcciones.

No empezar creando pedidos definitivos automaticamente. Primero medir aciertos, revisar correcciones y ajustar pesos.

## Criterio de exito

La primera version sera aceptable si:

- Identifica correctamente el cliente en mas del 90% de mensajes con nombre claro.
- Propone el articulo correcto en primera posicion en mas del 80% de lineas habituales.
- Detecta como dudosas las lineas ambiguas en lugar de equivocarse con confianza.
- Permite corregir rapido y guarda la correccion.
- Nunca inventa articulos ni crea documentos finales sin una confianza suficiente o validacion humana.
