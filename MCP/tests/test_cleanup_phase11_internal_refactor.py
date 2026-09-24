import hashlib
import json
import os
import unittest
from unittest.mock import patch

import faro_mcp
from tests._runtime_compat import legacy_handle_for_test


PHASE12_ALL_SCHEMA_SHA256 = "b258f79f7b0a835463cb9611e889eef3135aea0663d714a17ec20330ea36409d"
# Hash actualizado de forma intencional:
# 1) al permitir que stock_trasvasar reciba lineas con solo articulo+cantidad
#    (descripcion/unidad_medida se autocompletan desde ARTICUL si se dejan
#    vacias; ver test_transfer_fills_missing_description_and_unit_from_article
#    en test_phase2f_logistics.py).
# 2) al documentar en el esquema de recuento_gestion que, al grabar,
#    descripcion/unidad_medida tambien son opcionales y se autocompletan
#    desde ARTICUL (ver SaveRecountTests en test_articulos_supplemental_coverage.py).
# 3) al dividir actividad_gestion en tres herramientas independientes
#    (actividad_grabar, actividad_listar, actividad_tipo_listar): ver
#    test_cleanup_phase7_crm.py.
# 4) al cambiar el filtro "fecha" (fecha exacta) de actividad_listar por un
#    rango "fecha_desde"/"fecha_hasta" (ambos opcionales e independientes).
# 5) al ajustar entrada_almacen_crear para resolver proveedor solo por codigo
#    o por CIF cuando proveedor=0, igual que la integracion Delphi.
# 6) al incorporar oferta_crear con lineas de articulos estructuradas.
# 7) al incorporar orden_compra_cerrar al contrato publico v2 usando nombres
#    de dominio (ejercicio/numero) en lugar de los nombres internos legacy.
# 8) al anadir a tarifa_proveedor_actualizar cinco parametros nuevos que
#    replican casillas "Opciones Proceso" de IMPTAR_U.pas que faltaban
#    (actualizar_solo_si_sube_precio/actualizar_solo_proveedor_principal/
#    actualizar_solo_si_propio/generar_etiquetas/etiqueta_modelo); ver
#    revision-tarifa-proveedor-actualizar.md y test_phase7_supplier_tariffs.py.
# 9) al anadir a tarifa_proveedor_actualizar el parametro dar_de_alta y once
#    campos de linea nuevos (seccion/tipo_iva/tipo_precio/familia/subfamilia/
#    tabla_precios/canon/tarifa/pvp/cantidad_pedido_minimo/norma), que
#    replican la rama "ELSE IF B_ALTA.Checked" de IMPTAR_U.pas (crea ARTICUL
#    + ARTICULP cuando el articulo no existe); ver
#    revision-tarifa-proveedor-actualizar.md y SupplierTariffAltaTests en
#    test_phase7_supplier_tariffs.py.
# 10) al anadir a tarifa_proveedor_actualizar tres parametros nuevos
#    (usar_referencia_proveedor_como_codigo/digitos_codigo_articulo/
#    numerador_inicial) y hacer opcional el campo de linea "articulo" para
#    dar_de_alta=true, replicando la autogeneracion de ART_CODART de
#    IMPTAR_U.pas (seccion+proveedor+contador, o B_REFPRO) de
#    IMPTAR_U.pas:1727-1742; ver revision-tarifa-proveedor-actualizar.md y
#    SupplierTariffAltaCodeGenerationTests en test_phase7_supplier_tariffs.py.
# 11) al publicar proveedor_buscar en core como consulta de lectura del
#    maestro PROVEE, con filtros por nombres, CIF y fecha de alta.
# 12) al publicar venta_rentabilidad_lineas y venta_rentabilidad_resumen como
#    consultas de lectura para analizar margen y rentabilidad desde ANAVEN.
# 13) al publicar venta_documentos_detalle, venta_documentos_resumen y
#    venta_documentos_abc para analisis ANADOC con politica antiduplicado.
# 14) al ampliar el analisis ANADOC con dia_semana, hora y zona_cliente,
#    ademas de filtros zona_desde/zona_hasta.
# 15) al publicar venta_alertas_rentabilidad para alertas estilo ANAVEN:
#    lineas negativas, articulos compensados y grupos bajo umbral.
# 16) al publicar negocio_tendencias y permitir tipo_familia=ncc/propia/
#    cooperativa en los analisis de familia de ventas.
# 17) al publicar negocio_diagnostico_cambios para explicar variaciones de
#    venta/margen con desglose por articulos, clientes y lineas negativas.
# 18) al publicar negocio_stock_rotacion y negocio_stock_tendencias para
#    analizar stock inmovilizado, baja rotacion y stock que sube con ventas
#    o margen a la baja.
# 19) al publicar negocio_clientes_riesgo para detectar clientes que bajan,
#    desaparecen o deterioran rentabilidad.
# 20) al publicar negocio_cuadro_mando como resumen ejecutivo de ventas,
#    rentabilidad, clientes en riesgo y stock.
# 21) al publicar las fachadas de dashboard ERP (dashboard_resumen,
#    dashboard_series_temporales, dashboard_alertas, dashboard_filtros,
#    ventas_resumen, compras_resumen, stock_resumen, pedidos_resumen,
#    documentos_pendientes_resumen, clientes_resumen y proveedores_resumen),
#    todas apoyadas en funciones de negocio ya existentes.
# 22) al completar compras/tesoreria del dashboard con
#    compras_pedidos_pendientes_resumen, compras_documentos_pendientes_resumen
#    y tesoreria_resumen, basadas en CABORC/DETORC, CABDOCM y OPECAJ.
# 23) al publicar recomendaciones accionables del dashboard
#    (dashboard_acciones_recomendadas y fachadas por ventas/clientes/stock/
#    pendientes/tesoreria), basadas en las metricas read-only existentes.
# 24) al publicar compras_articulos_pendientes_recibir como agregacion por
#    articulo de los pedidos de compra pendientes CABORC/DETORC.
# 25) al publicar orden_compra_propuesta_stock_minimo y
#    orden_compra_propuesta_pedidos_cliente como propuestas read-only basadas
#    en GENPEDM/GENPEDC, UTL_STOCK_TERMINO y ARTICULP.
# 26) al publicar empresa_replicar en el perfil admin como operacion critica
#    para crear una empresa nueva replicando configuracion/auxiliares desde
#    la empresa 1 y sobrescribiendo nombre/direccion en EMPRES y CENTROS.
# 27) al anadir empresa como parametro opcional comun a todas las herramientas
#    publicas, con default 1, para seleccionar la empresa Faro por invocacion
#    sin depender de FARO_EMPRESA.
# 28) al anadir centro como parametro opcional comun a las herramientas de
#    stock, ventas, compras y almacen, con default 0; la cadena vacia queda
#    reservada para consultar todos los centros.
# Si vuelve a fallar, confirma primero que el cambio de esquema es
# intencional antes de tocar este valor.


class CleanupPhase11InternalRefactorTests(unittest.TestCase):
    def test_public_handlers_use_canonical_method_names(self):
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "all"}):
            server = faro_mcp.FaroToolRuntime()
        self.assertEqual(len(server.tools), 97)
        for name, handler in server.tools.items():
            with self.subTest(name=name):
                self.assertEqual(handler.__name__, f"tool_{name}")

    def test_alias_infrastructure_is_gone(self):
        self.assertFalse(hasattr(faro_mcp, "PUBLIC_TOOL_RENAMES"))
        self.assertFalse(hasattr(faro_mcp, "LEGACY_PUBLIC_TOOL_NAMES"))
        self.assertFalse(hasattr(faro_mcp, "INTERNAL_TOOL_NAMES"))
        self.assertFalse(any(name.startswith("tool_py_") for name in dir(faro_mcp.FaroToolRuntime)))

    def test_public_schema_matches_phase12_contract(self):
        payload = json.dumps(
            faro_mcp.tool_definitions("all"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        self.assertEqual(hashlib.sha256(payload).hexdigest(), PHASE12_ALL_SCHEMA_SHA256)

    def test_profiles_keep_frozen_counts(self):
        expected = {"core": 87, "admin": 96, "integrations": 88, "all": 97, "full": 97}
        for profile, count in expected.items():
            with self.subTest(profile=profile), patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": profile}):
                server = faro_mcp.FaroToolRuntime()
                self.assertEqual(len(server.tools), count)
                self.assertEqual(len(faro_mcp.tool_definitions(profile)), count)

    def test_server_version_tracks_current_release(self):
        server = faro_mcp.FaroToolRuntime()
        response = legacy_handle_for_test(server, {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        })
        self.assertEqual(response["result"]["serverInfo"]["version"], faro_mcp.SERVER_VERSION)


if __name__ == "__main__":
    unittest.main()
