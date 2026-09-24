import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import faro_mcp


class Phase5PublicToolCoverageTests(unittest.TestCase):
    """Cobertura directa del borde MCP para herramientas antes solo cubiertas indirectamente."""

    def _definition(self, name: str) -> dict:
        return next(item for item in faro_mcp.tool_definitions("all") if item["name"] == name)

    def _server_and_service(self):
        with patch.dict(
            os.environ,
            {
                "FARO_MCP_TOOL_PROFILE": "all",
                "FARO_MCP_ACCESS_LEVEL": "critical",
                "FARO_MCP_AUDIT_REQUIRED": "false",
                "FARO_MCP_AUDIT_LOG": "",
            },
            clear=False,
        ):
            server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        return server, svc

    def test_target_tools_have_explicit_public_contracts(self):
        expected_required = {
            "cliente_tipo_venta": ["tipo_documento", "cliente", "subcliente"],
            "precio_tabla_listar": [],
            "pedido_linea_mover": [
                "centro", "articulo", "cantidad", "linea", "zona_origen", "zona_destino"
            ],
            "pedido_marcar_preparado": [
                "centro", "tipo_documento", "ejercicio", "serie", "numero"
            ],
            "pedido_finalizar": [
                "centro", "tipo_documento", "ejercicio", "serie", "numero"
            ],
        }
        for tool_name, required in expected_required.items():
            with self.subTest(tool=tool_name):
                schema = self._definition(tool_name)["inputSchema"]
                self.assertFalse(schema.get("additionalProperties", True))
                self.assertEqual(schema.get("required", []), required)

    def test_all_public_tools_accept_empresa_with_default_one(self):
        for definition in faro_mcp.tool_definitions("all"):
            with self.subTest(tool=definition["name"]):
                schema = definition["inputSchema"]
                self.assertIn("empresa", schema.get("properties", {}))
                self.assertEqual(schema["properties"]["empresa"].get("type"), "integer")
                self.assertEqual(schema["properties"]["empresa"].get("default"), 1)
                self.assertNotIn("empresa", schema.get("required", []))

    def test_center_scoped_tools_accept_optional_centro_with_default_zero(self):
        for tool_name in faro_mcp.CENTER_SCOPED_TOOL_NAMES:
            with self.subTest(tool=tool_name):
                schema = self._definition(tool_name)["inputSchema"]
                self.assertIn("centro", schema.get("properties", {}))
                self.assertEqual(schema["properties"]["centro"].get("type"), ["integer", "string"])
                self.assertEqual(schema["properties"]["centro"].get("default"), 0)
                self.assertNotIn("centro", schema.get("required", []))

    def test_center_scoped_translation_defaults_to_center_zero_and_blank_means_all(self):
        self.assertEqual(
            faro_mcp.translate_public_arguments("stock_consultar", {"articulo": "A1"}),
            {"codart": "A1", "centro": 0},
        )
        self.assertEqual(
            faro_mcp.translate_public_arguments("stock_consultar", {"articulo": "A1", "centro": ""}),
            {"codart": "A1", "centro": ""},
        )
        self.assertEqual(
            faro_mcp.translate_public_arguments(
                "venta_rentabilidad_lineas",
                {"fecha_desde": "2026-01-01", "fecha_hasta": "2026-01-31"},
            )["centro"],
            0,
        )

    def test_target_tools_keep_expected_security_risk(self):
        expected = {
            "cliente_tipo_venta": "read",
            "precio_tabla_listar": "read",
            "pedido_linea_mover": "write",
            "pedido_marcar_preparado": "write",
            "pedido_finalizar": "critical",
        }
        for tool_name, risk in expected.items():
            with self.subTest(tool=tool_name):
                self.assertEqual(faro_mcp.effective_tool_risk(tool_name, {}), risk)

    def test_public_argument_translation_for_target_tools(self):
        cases = {
            "cliente_tipo_venta": (
                {"tipo_documento": "A", "cliente": 10, "subcliente": 0},
                {"tipdoc": "A", "codcli": 10, "subcli": 0},
            ),
            "precio_tabla_listar": ({}, {}),
            "pedido_marcar_preparado": (
                {"centro": 1, "tipo_documento": "P", "ejercicio": 2026, "serie": "PM", "numero": 25},
                {"centro": 1, "tipdoc": "P", "ejerci": 2026, "serie": "PM", "numdoc": 25},
            ),
            "pedido_finalizar": (
                {"centro": 1, "tipo_documento": "P", "ejercicio": 2026, "serie": "PM", "numero": 25},
                {"centro": 1, "tipdoc": "P", "ejerci": 2026, "serie": "PM", "numdoc": 25},
            ),
            "pedido_linea_mover": (
                {
                    "centro": 1,
                    "articulo": "A1",
                    "descripcion": "Articulo 1",
                    "cantidad": "2.5",
                    "linea": "1-P-0-2026-PM-25-1",
                    "zona_origen": 1,
                    "zona_destino": 2,
                    "ubicacion_origen": "A-01",
                    "ubicacion_destino": "B-02",
                },
                {
                    "centro": 1,
                    "codart": "A1",
                    "descri": "Articulo 1",
                    "cantid": "2.5",
                    "linea": "1-P-0-2026-PM-25-1",
                    "zona_origen": 1,
                    "zona_destino": 2,
                    "ubi_origen": "A-01",
                    "ubi_destino": "B-02",
                },
            ),
        }
        for tool_name, (public_args, internal_args) in cases.items():
            with self.subTest(tool=tool_name):
                self.assertEqual(
                    faro_mcp.translate_public_arguments(tool_name, public_args),
                    internal_args,
                )

    def test_public_validation_rejects_legacy_or_incomplete_arguments(self):
        invalid_cases = {
            "cliente_tipo_venta": {"tipdoc": "A", "codcli": 10, "subcli": 0},
            "precio_tabla_listar": {"empresa": "1"},
            "pedido_linea_mover": {
                "centro": 1,
                "articulo": "A1",
                "cantidad": "1",
                "linea": "L1",
                "zona_origen": 1,
                # zona_destino omitida
            },
            "pedido_marcar_preparado": {
                "centro": 1, "tipo_documento": "P", "ejercicio": 2026, "serie": "PM"
            },
            "pedido_finalizar": {
                "centro": 1, "tipo_documento": "P", "ejercicio": 2026, "serie": "PM"
            },
        }
        for tool_name, args in invalid_cases.items():
            with self.subTest(tool=tool_name):
                with self.assertRaises(faro_mcp.FaroError):
                    faro_mcp.translate_public_arguments(tool_name, args)

    def test_cliente_tipo_venta_handler_calls_service_and_closes_db(self):
        server, svc = self._server_and_service()
        svc.customer_sale_type.return_value = {"allowed": True, "message": ""}
        with patch.object(server, "phase1_service", return_value=svc):
            result = server.tool_cliente_tipo_venta({"tipdoc": "A", "codcli": 10, "subcli": 0})
        self.assertEqual(result, {"allowed": True, "message": ""})
        svc.customer_sale_type.assert_called_once_with("A", 10, 0)
        svc.db.close.assert_called_once_with()

    def test_precio_tabla_listar_handler_calls_service_and_closes_db(self):
        server, svc = self._server_and_service()
        svc.list_price_tables.return_value = [{"TPR_CODTAB": 1}, {"TPR_CODTAB": 2}]
        with patch.object(server, "service", return_value=svc):
            result = server.tool_precio_tabla_listar({})
        self.assertEqual(result, [{"TPR_CODTAB": 1}, {"TPR_CODTAB": 2}])
        svc.list_price_tables.assert_called_once_with()
        svc.db.close.assert_called_once_with()

    def test_stock_consultar_center_zero_filters_and_blank_lists_all_centers(self):
        server, svc = self._server_and_service()
        svc.article_stock.return_value = {"centro": 0, "existencias": 5, "datasnap_text": "5"}
        svc.article_stocks.return_value = {"items": [{"centro": 1, "existencias": 2}]}
        with patch.object(server, "phase1_service", return_value=svc):
            center_zero = server.tool_stock_consultar({"codart": "A1", "centro": 0})
            all_centers = server.tool_stock_consultar({"codart": "A1", "centro": ""})
        self.assertEqual(center_zero["scope"], "centro")
        self.assertEqual(all_centers["scope"], "todos")
        svc.article_stock.assert_called_once_with("A1", 0)
        svc.article_stocks.assert_called_once_with("A1")
        self.assertEqual(svc.db.close.call_count, 2)

    def test_pedido_linea_mover_handler_calls_service_and_closes_db(self):
        server, svc = self._server_and_service()
        svc.move_order_line_zone.return_value = {"movido": True}
        args = {
            "centro": 1,
            "codart": "A1",
            "descri": "Articulo",
            "cantid": "2",
            "linea": "1-P-0-2026-PM-25-1",
            "zona_origen": 1,
            "zona_destino": 2,
            "ubi_origen": "A-01",
            "ubi_destino": "B-02",
        }
        with patch.object(server, "phase1_service", return_value=svc):
            result = server.tool_pedido_linea_mover(args)
        self.assertEqual(result, {"movido": True})
        svc.move_order_line_zone.assert_called_once_with(
            1, "A1", "Articulo", "2", "1-P-0-2026-PM-25-1", 1, 2, "A-01", "B-02"
        )
        svc.db.close.assert_called_once_with()

    def test_pedido_marcar_preparado_and_finalizar_handlers_call_service(self):
        server, svc = self._server_and_service()
        svc.save_order_prepared.return_value = {"cabecera_marcada_preparado": True}
        svc.check_order_preparation_status.return_value = {"indedi": "P"}
        args = {"centro": 1, "tipdoc": "P", "ejerci": 2026, "serie": "PM", "numdoc": 25}
        with patch.object(server, "phase1_service", return_value=svc):
            prepared = server.tool_pedido_marcar_preparado(args)
            finalized = server.tool_pedido_finalizar(args)
        self.assertEqual(prepared, {"cabecera_marcada_preparado": True})
        self.assertEqual(finalized, {"indedi": "P"})
        svc.save_order_prepared.assert_called_once_with(1, "P", 2026, "PM", 25)
        svc.check_order_preparation_status.assert_called_once_with(1, "P", 2026, "PM", 25)
        self.assertEqual(svc.db.close.call_count, 2)

    def test_invoke_tool_exercises_public_boundary_for_all_target_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "FARO_MCP_TOOL_PROFILE": "all",
                    "FARO_MCP_ACCESS_LEVEL": "critical",
                    "FARO_MCP_AUDIT_REQUIRED": "true",
                    "FARO_MCP_AUDIT_LOG": os.path.join(tmp, "audit.jsonl"),
                },
                clear=False,
            ):
                server = faro_mcp.FaroToolRuntime()

            cases = {
                "cliente_tipo_venta": (
                    {"tipo_documento": "A", "cliente": 10, "subcliente": 0},
                    {"tipdoc": "A", "codcli": 10, "subcli": 0},
                ),
                "precio_tabla_listar": ({}, {}),
                "pedido_linea_mover": (
                    {
                        "centro": 1,
                        "articulo": "A1",
                        "cantidad": "1",
                        "linea": "1-P-0-2026-PM-25-1",
                        "zona_origen": 1,
                        "zona_destino": 2,
                    },
                    {
                        "centro": 1,
                        "codart": "A1",
                        "cantid": "1",
                        "linea": "1-P-0-2026-PM-25-1",
                        "zona_origen": 1,
                        "zona_destino": 2,
                    },
                ),
                "pedido_marcar_preparado": (
                    {"centro": 1, "tipo_documento": "P", "ejercicio": 2026, "serie": "PM", "numero": 25},
                    {"centro": 1, "tipdoc": "P", "ejerci": 2026, "serie": "PM", "numdoc": 25},
                ),
                "pedido_finalizar": (
                    {"centro": 1, "tipo_documento": "P", "ejercicio": 2026, "serie": "PM", "numero": 25},
                    {"centro": 1, "tipdoc": "P", "ejerci": 2026, "serie": "PM", "numdoc": 25},
                ),
            }

            for tool_name, (public_args, internal_args) in cases.items():
                with self.subTest(tool=tool_name):
                    handler = Mock(return_value={"tool": tool_name})
                    server.tools[tool_name] = handler
                    result, is_error = server.invoke_tool(tool_name, public_args, request_id=f"phase5-{tool_name}")
                    self.assertFalse(is_error)
                    self.assertTrue(result["ok"])
                    self.assertEqual(result["data"], {"tool": tool_name})
                    handler.assert_called_once_with(internal_args)

    def test_invoke_tool_uses_empresa_argument_without_passing_it_to_handler(self):
        with patch.dict(
            os.environ,
            {
                "FARO_MCP_TOOL_PROFILE": "all",
                "FARO_MCP_ACCESS_LEVEL": "critical",
                "FARO_MCP_AUDIT_REQUIRED": "false",
                "FARO_MCP_AUDIT_LOG": "",
                "FARO_EMPRESA": "9",
            },
            clear=False,
        ):
            server = faro_mcp.FaroToolRuntime()

        handler = Mock(side_effect=lambda args: {"empresa": server._settings_for_call().empresa, "args": args})
        server.tools["precio_tabla_listar"] = handler

        result, is_error = server.invoke_tool("precio_tabla_listar", {"empresa": 2}, request_id="phase5-empresa")

        self.assertFalse(is_error)
        self.assertEqual(result["data"], {"empresa": 2, "args": {}})
        handler.assert_called_once_with({})

    def test_invoke_tool_defaults_empresa_to_one(self):
        with patch.dict(
            os.environ,
            {
                "FARO_MCP_TOOL_PROFILE": "all",
                "FARO_MCP_ACCESS_LEVEL": "critical",
                "FARO_MCP_AUDIT_REQUIRED": "false",
                "FARO_MCP_AUDIT_LOG": "",
                "FARO_EMPRESA": "9",
            },
            clear=False,
        ):
            server = faro_mcp.FaroToolRuntime()

        server.tools["precio_tabla_listar"] = lambda args: {"empresa": server._settings_for_call().empresa}

        result, is_error = server.invoke_tool("precio_tabla_listar", {}, request_id="phase5-empresa-default")

        self.assertFalse(is_error)
        self.assertEqual(result["data"], {"empresa": 1})

    def test_invoke_tool_reports_validation_errors_before_handler(self):
        with patch.dict(
            os.environ,
            {
                "FARO_MCP_TOOL_PROFILE": "all",
                "FARO_MCP_ACCESS_LEVEL": "critical",
                "FARO_MCP_AUDIT_REQUIRED": "false",
                "FARO_MCP_AUDIT_LOG": "",
            },
            clear=False,
        ):
            server = faro_mcp.FaroToolRuntime()
        handler = Mock(return_value={"unexpected": True})
        server.tools["cliente_tipo_venta"] = handler
        result, is_error = server.invoke_tool(
            "cliente_tipo_venta",
            {"tipo_documento": "A", "cliente": 10},
            request_id="phase5-invalid",
        )
        self.assertTrue(is_error)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        handler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
