import json
import os
import unittest
from unittest.mock import Mock, patch

import faro_mcp
from tests._runtime_compat import legacy_handle_for_test


class CleanupPhase12ContractV2Tests(unittest.TestCase):
    def _definition(self, name, profile="all"):
        return next(item for item in faro_mcp.tool_definitions(profile) if item["name"] == name)

    def test_profiles_and_tool_names_are_unchanged(self):
        expected = {"core": 87, "admin": 96, "integrations": 88, "all": 97, "full": 97}
        for profile, count in expected.items():
            with self.subTest(profile=profile):
                self.assertEqual(len(faro_mcp.tool_definitions(profile)), count)

    def test_public_schemas_use_domain_names_and_reject_extra_properties(self):
        defs = faro_mcp.tool_definitions("all")
        for definition in defs:
            self.assertFalse(definition["inputSchema"].get("additionalProperties", True), definition["name"])
        stock = self._definition("stock_regularizar")["inputSchema"]["properties"]
        self.assertIn("articulo", stock)
        self.assertIn("cantidad", stock)
        self.assertIn("unidad_medida", stock)
        self.assertNotIn("codart", stock)
        self.assertNotIn("cantid", stock)
        self.assertNotIn("unimed", stock)

    def test_stock_regularizar_defaults_center_and_requires_article_and_quantity(self):
        schema = self._definition("stock_regularizar")["inputSchema"]
        self.assertEqual(schema["required"], ["articulo", "cantidad"])
        translated = faro_mcp.translate_public_arguments(
            "stock_regularizar", {"articulo": "A1", "cantidad": 5}
        )
        self.assertEqual(translated, {"codart": "A1", "centro": 0, "cantid": 5})

    def test_company_replicate_is_admin_critical_and_uses_domain_names(self):
        admin_names = {item["name"] for item in faro_mcp.tool_definitions("admin")}
        core_names = {item["name"] for item in faro_mcp.tool_definitions("core")}
        self.assertIn("empresa_replicar", admin_names)
        self.assertNotIn("empresa_replicar", core_names)
        schema = self._definition("empresa_replicar", "admin")["inputSchema"]
        self.assertEqual(schema["required"], ["empresa_destino", "nombre", "direccion"])
        self.assertIn("empresa_destino", schema["properties"])
        self.assertIn("nombre", schema["properties"])
        self.assertIn("direccion", schema["properties"])
        self.assertEqual(faro_mcp.effective_tool_risk("empresa_replicar", {}), "critical")

    def test_company_replicate_handler_calls_phase1_service(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.replicate_company_from_template.return_value = {"ok": True}
        with patch.object(server, "phase1_service", return_value=svc):
            result = server.tool_empresa_replicar({
                "empresa_destino": 4,
                "nombre": "Empresa 4",
                "direccion": "Calle 4",
            })
        self.assertEqual(result, {"ok": True})
        svc.replicate_company_from_template.assert_called_once_with(4, "Empresa 4", "Calle 4")
        svc.db.close.assert_called_once()

    def test_article_search_hides_database_order_columns(self):
        schema = self._definition("articulo_buscar")["inputSchema"]
        self.assertIn("ordenar_por", schema["properties"])
        self.assertEqual(schema["properties"]["ordenar_por"]["default"], "descripcion")
        self.assertNotIn("ART_DESCRI", schema["properties"]["ordenar_por"]["enum"])
        translated = faro_mcp.translate_public_arguments(
            "articulo_buscar", {"texto": "motor", "ordenar_por": "descripcion", "limite": 10}
        )
        self.assertEqual(translated["order_by"], "ART_DESCRI")
        self.assertEqual(translated["limit"], 10)

    def test_article_search_exposes_stock_and_article_dates_filters(self):
        schema = self._definition("articulo_buscar")["inputSchema"]
        props = schema["properties"]
        for name in ("centro", "con_stock", "fecha_compra_antes", "fecha_venta_antes", "fecha_movimiento_antes"):
            self.assertIn(name, props)
        self.assertIn("existencias", props["ordenar_por"]["enum"])
        self.assertIn("fecha_compra", props["ordenar_por"]["enum"])

        translated = faro_mcp.translate_public_arguments(
            "articulo_buscar",
            {
                "texto": "TALADROS",
                "centro": 2,
                "con_stock": True,
                "fecha_compra_antes": "2026-01-01",
                "ordenar_por": "existencias",
            },
        )
        self.assertEqual(translated["with_stock"], True)
        self.assertEqual(translated["purchase_before"], "2026-01-01")
        self.assertEqual(translated["order_by"], "ARTE_EXIST")

    def test_article_cost_price_uses_domain_names(self):
        schema = self._definition("articulo_precio_coste")["inputSchema"]
        self.assertEqual(schema["required"], ["articulo", "fecha"])
        self.assertIn("articulo", schema["properties"])
        self.assertIn("fecha", schema["properties"])
        self.assertIn("moneda", schema["properties"])
        self.assertNotIn("codart", schema["properties"])
        translated = faro_mcp.translate_public_arguments(
            "articulo_precio_coste", {"articulo": "A1", "fecha": "2026-09-21", "moneda": "E"}
        )
        self.assertEqual(translated, {"codart": "A1", "fecha": "2026-09-21", "moneda": "E"})
        translated_without_currency = faro_mcp.translate_public_arguments(
            "articulo_precio_coste", {"articulo": "A1", "fecha": "2026-09-21"}
        )
        self.assertEqual(translated_without_currency, {"codart": "A1", "fecha": "2026-09-21"})

    def test_provider_search_exposes_supplier_filters(self):
        schema = self._definition("proveedor_buscar", "core")["inputSchema"]
        props = schema["properties"]
        for name in (
            "proveedor", "nombre_comercial", "nombre_fiscal", "nombre_abreviado", "cif",
            "fecha_alta", "fecha_alta_desde", "fecha_alta_hasta", "limite",
        ):
            self.assertIn(name, props)
        self.assertNotIn("codpro", props)
        self.assertNotIn("nombre_comercial_like", props)

        translated = faro_mcp.translate_public_arguments(
            "proveedor_buscar",
            {
                "nombre_comercial": "FERRETERIA",
                "nombre_fiscal": "SUMINISTROS",
                "nombre_abreviado": "SUM",
                "cif": "B12345678",
                "fecha_alta_desde": "2026-01-01",
                "fecha_alta_hasta": "2026-12-31",
                "limite": 25,
            },
        )
        self.assertEqual(translated["nombre_comercial_like"], "FERRETERIA")
        self.assertEqual(translated["nombre_fiscal_like"], "SUMINISTROS")
        self.assertEqual(translated["nombre_abreviado_like"], "SUM")
        self.assertEqual(translated["fecha_alta_desde"], "2026-01-01")
        self.assertEqual(translated["fecha_alta_hasta"], "2026-12-31")
        self.assertEqual(translated["limit"], 25)

    def test_article_family_save_uses_domain_names(self):
        schema = self._definition("articulo_familia_guardar")["inputSchema"]
        self.assertEqual(schema["required"], ["articulo", "familia", "subfamilia"])
        self.assertIn("familia", schema["properties"])
        self.assertIn("subfamilia", schema["properties"])
        self.assertIn("ssubfamilia", schema["properties"])
        self.assertIn("tabla_nueva", schema["properties"])
        translated = faro_mcp.translate_public_arguments(
            "articulo_familia_guardar", {
                "articulo": "A1", "familia": 4, "subfamilia": 2, "ssubfamilia": 9, "tabla_nueva": 0,
            }
        )
        self.assertEqual(translated, {"codart": "A1", "codfam": 4, "subfam": 2, "ssubfam": 9, "new_table": 0})

    def test_offer_create_uses_structured_article_lines(self):
        schema = self._definition("oferta_crear")["inputSchema"]
        self.assertEqual(
            schema["required"],
            ["tipo_oferta", "nombre", "fecha_inicio", "fecha_fin", "articulos"],
        )
        self.assertEqual(schema["properties"]["tipo_oferta"]["enum"], ["R", "P", "T", "S", "W"])
        line_schema = schema["properties"]["articulos"]["items"]
        self.assertIn("precio_oferta", line_schema["properties"])
        self.assertIn("descuentos", line_schema["properties"])

        args = {
            "tipo_oferta": "T",
            "nombre": "Oferta primavera",
            "fecha_inicio": "2027-03-01",
            "fecha_fin": "2027-03-31",
            "articulos": [{"articulo": "A1", "precio_oferta": "9.99", "descuentos": [10, 5]}],
        }
        translated = faro_mcp.translate_public_arguments("oferta_crear", args)
        self.assertEqual(translated, args)

    def test_article_famncc_table_save_uses_domain_names(self):
        schema = self._definition("articulo_familiancc_tabla_guardar")["inputSchema"]
        self.assertEqual(schema["required"], ["articulo", "familia_ncc"])
        self.assertIn("familia_ncc", schema["properties"])
        self.assertIn("tabla_nueva", schema["properties"])
        translated = faro_mcp.translate_public_arguments(
            "articulo_familiancc_tabla_guardar", {
                "articulo": "A1", "familia_ncc": "0102", "tabla_nueva": 0,
            }
        )
        self.assertEqual(translated, {"codart": "A1", "famncc": "0102", "new_table": 0})

    def test_client_update_is_structured(self):
        schema = self._definition("cliente_actualizar")["inputSchema"]
        self.assertEqual(schema["properties"]["datos"]["type"], "object")
        translated = faro_mcp.translate_public_arguments("cliente_actualizar", {"datos": {
            "cliente": 10, "subcliente": 0, "nombre": "Carlos", "razon_social": "Empresa SL",
            "domicilio": "Calle 1", "codigo_postal": "46000", "poblacion": "Valencia",
            "telefono": "960000000", "email": "x@example.test", "cif": "B12345678",
        }})
        self.assertEqual(
            translated["texto"],
            "10|0|Carlos|Empresa SL|Calle 1|46000|Valencia|960000000|x@example.test|B12345678",
        )

    def test_order_create_accepts_structured_lines_comments_and_budget_flag(self):
        translated = faro_mcp.translate_public_arguments("pedido_crear", {
            "centro": 1, "cliente": 10, "subcliente": 0,
            "lineas": [{"articulo": "A1", "descripcion": "Articulo", "cantidad": 2, "precio": 5.5, "descuento": 10}],
            "comentarios": ["Urgente", "Entregar por la tarde"], "crear_presupuesto": True,
        })
        self.assertEqual(translated["codcli"], 10)
        self.assertEqual(translated["texto"], "A1|Articulo|2|5.5|10#")
        self.assertEqual(translated["observaciones"], "Urgente\rEntregar por la tarde\r")
        self.assertEqual(translated["urgente"], "R")

    def test_delivery_and_transfer_lines_are_structured(self):
        delivery = faro_mcp.translate_public_arguments("pedido_albaranar", {
            "centro": 1, "codigo_pedido": "2026-PM-3", "lineas": [{"linea": 10, "cantidad": 2}],
        })
        self.assertEqual(delivery["texto"], "10|||2#")
        transfer = faro_mcp.translate_public_arguments("stock_trasvasar", {
            "centro_origen": 1, "centro_destino": 2,
            "lineas": [{"articulo": "A1", "cantidad": 3}],
        })
        self.assertEqual(transfer["centroo"], 1)
        self.assertEqual(transfer["centrod"], 2)
        self.assertEqual(transfer["texto"], "A1||3|#")

    def test_order_close_accepts_orders_and_budgets_only(self):
        schema = self._definition("pedido_cerrar")["inputSchema"]
        self.assertEqual(schema["properties"]["tipo_documento"]["enum"], ["P", "R"])

        translated = faro_mcp.translate_public_arguments("pedido_cerrar", {
            "centro": 0, "tipo_documento": "R", "ejercicio": 2026, "serie": "PM", "numero": 12,
            "usuario": "carlos",
        })
        self.assertEqual(translated, {
            "centro": 0, "tipdoc": "R", "ejerci": 2026, "serie": "PM", "numdoc": 12,
            "usuario": "carlos",
        })

        with self.assertRaises(faro_mcp.FaroError):
            faro_mcp.translate_public_arguments("pedido_cerrar", {
                "centro": 0, "tipo_documento": "A", "ejercicio": 2026, "serie": "PM", "numero": 12,
            })

    def test_purchase_order_close_uses_document_domain_names(self):
        schema = self._definition("orden_compra_cerrar")["inputSchema"]
        self.assertEqual(schema["required"], ["ejercicio", "serie", "numero"])

        translated = faro_mcp.translate_public_arguments("orden_compra_cerrar", {
            "ejercicio": 2026, "serie": "OC", "numero": 12, "usuario": "carlos",
        })
        self.assertEqual(translated, {
            "centro": 0, "ejerci": 2026, "serie": "OC", "numdoc": 12, "usuario": "carlos",
        })

    def test_sale_lines_are_structured(self):
        translated = faro_mcp.translate_public_arguments("mostrador_cobrar", {
            "caja": 1, "centro": 1, "cliente": 10, "subcliente": 0,
            "lineas": [{"articulo": "A1", "descripcion": "Articulo", "cantidad": 1, "precio": 10,
                        "iva": 21, "precio_iva_incluido": False, "pvp": 12.1}],
            "tipo_documento": "T", "total": 12.1, "usuario": "carlos",
        })
        self.assertEqual(translated["codcli"], 10)
        self.assertEqual(translated["tipdoc"], "T")
        self.assertEqual(translated["texto"], "A1|Articulo|1|10|0|0|21|0|||N|12.1|0|0#")

    def test_sales_document_accepts_optional_series_and_typed_document_enum(self):
        translated = faro_mcp.translate_public_arguments("venta_documento_crear", {
            "centro": 0, "cliente": 10, "subcliente": 0, "serie": "Z9",
            "lineas": [{"articulo": "A1", "descripcion": "Articulo", "cantidad": 1, "precio": 10}],
            "tipo_documento": "A", "usuario": "carlos",
        })
        self.assertEqual(translated["serie"], "Z9")
        self.assertEqual(translated["tipdoc"], "A")

        with self.assertRaises(faro_mcp.FaroError):
            faro_mcp.translate_public_arguments("venta_documento_crear", {
                "centro": 0, "cliente": 10, "subcliente": 0, "lineas": [],
                "tipo_documento": "X", "usuario": "carlos",
            })

    def test_unknown_public_parameter_is_rejected(self):
        with self.assertRaises(faro_mcp.FaroError):
            faro_mcp.translate_public_arguments("stock_consultar", {"articulo": "A1", "codart": "A1"})

    def test_public_result_envelope_removes_datasnap_fields_recursively(self):
        result = faro_mcp.normalize_public_result("stock_consultar", "core", {
            "ok": True, "codart": "A1", "datasnap_text": "A1|2",
            "nested": {"value": 2, "datasnap_value": True},
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"codart": "A1", "nested": {"value": 2}})
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["meta"]["contract_version"], "2.0")

    def test_business_false_result_uses_uniform_error_envelope(self):
        result = faro_mcp.normalize_public_result("pedido_enviar", "core", {
            "ok": False, "message": "Pedido no encontrado", "pedido": "2026-A-1", "datasnap_text": "False",
        })
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "BUSINESS_ERROR")
        self.assertEqual(result["error"]["message"], "Pedido no encontrado")
        self.assertEqual(result["error"]["details"], {"pedido": "2026-A-1"})

    def test_tools_call_returns_uniform_success_envelope(self):
        server = faro_mcp.FaroToolRuntime()
        server.tools["stock_consultar"] = Mock(return_value={"codart": "A1", "datasnap_text": "7", "existencias": "7"})
        response = legacy_handle_for_test(server, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "stock_consultar", "arguments": {"articulo": "A1"}},
        })
        self.assertFalse(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"], {"codart": "A1", "existencias": "7"})
        server.tools["stock_consultar"].assert_called_once_with({"codart": "A1", "centro": 0})

    def test_tools_call_returns_uniform_validation_error(self):
        server = faro_mcp.FaroToolRuntime()
        response = legacy_handle_for_test(server, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "stock_consultar", "arguments": {"codart": "A1"}},
        })
        self.assertTrue(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENT")
        self.assertIn("Parametros no permitidos", payload["error"]["message"])

    def test_tool_exception_is_not_promoted_to_jsonrpc_protocol_error(self):
        server = faro_mcp.FaroToolRuntime()
        server.tools["stock_consultar"] = Mock(side_effect=faro_mcp.FaroError("Articulo no encontrado"))
        response = legacy_handle_for_test(server, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "stock_consultar", "arguments": {"articulo": "NO"}},
        })
        self.assertNotIn("error", response)
        self.assertTrue(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")

    def test_server_version_and_contract_version(self):
        self.assertEqual(faro_mcp.SERVER_VERSION, "2.15.8")
        self.assertEqual(faro_mcp.PUBLIC_CONTRACT_VERSION, "2.0")


if __name__ == "__main__":
    unittest.main()
