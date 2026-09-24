import os
import unittest
from unittest.mock import Mock, patch

import faro_mcp
from tests._runtime_compat import legacy_handle_for_test


class CleanupPhase9SalesCounterTests(unittest.TestCase):
    def test_catalog_counts_and_sales_surface(self):
        core = faro_mcp.FaroToolRuntime()
        core_defs = {item["name"] for item in faro_mcp.tool_definitions()}
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "full"}):
            full = faro_mcp.FaroToolRuntime()
            full_defs = {item["name"] for item in faro_mcp.tool_definitions()}

        self.assertEqual(len(core.tools), 87)
        self.assertEqual(len(core_defs), 87)
        self.assertEqual(len(full.tools), 97)
        self.assertEqual(len(full_defs), 97)
        for server in (core, full):
            self.assertIn("mostrador_venta_gestion", server.tools)
            self.assertIn("mostrador_cobrar", server.tools)
            self.assertIn("venta_documento_crear", server.tools)
            self.assertTrue({"mostrador_venta_guardar", "mostrador_venta_borrar", "mostrador_pedido_cargar", "venta_albaran_crear"}.isdisjoint(server.tools))
            self.assertNotIn("venta_albaran_crear", server.tools)

    def test_guardar_routes_to_internal_handler(self):
        server = faro_mcp.FaroToolRuntime()
        server._tool_mostrador_venta_guardar = Mock(return_value={"ok": "guardar"})
        result = server.tool_mostrador_venta_gestion({
            "accion": "guardar", "venta": "", "codcli": 10, "subcli": 0,
            "texto": "A1|Articulo|1|10|0|0|21|0|4|UNI|N|12.1|0|0#",
            "tipdoc": "T", "usuario": "carlos",
        })
        self.assertEqual(result, {"ok": "guardar"})
        server._tool_mostrador_venta_guardar.assert_called_once()

    def test_borrar_routes_minimal_payload(self):
        server = faro_mcp.FaroToolRuntime()
        server._tool_mostrador_venta_borrar = Mock(return_value={"ok": "borrar"})
        result = server.tool_mostrador_venta_gestion({"accion": "borrar", "venta": "2026-15"})
        self.assertEqual(result, {"ok": "borrar"})
        server._tool_mostrador_venta_borrar.assert_called_once_with({"venta": "2026-15"})

    def test_cargar_pedido_routes_to_internal_handler(self):
        server = faro_mcp.FaroToolRuntime()
        server._tool_mostrador_pedido_cargar = Mock(return_value={"ok": "pedido"})
        result = server.tool_mostrador_venta_gestion({
            "accion": "cargar_pedido", "centro": 1, "codigo_pedido": "2026-A-10",
            "tipdoc": "T", "texto": "1|A1|Articulo|2#",
        })
        self.assertEqual(result, {"ok": "pedido"})
        server._tool_mostrador_pedido_cargar.assert_called_once()

    def test_action_validation(self):
        server = faro_mcp.FaroToolRuntime()
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_mostrador_venta_gestion({"accion": "borrar"})
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_mostrador_venta_gestion({"accion": "guardar", "codcli": 1})
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_mostrador_venta_gestion({"accion": "cargar_pedido", "centro": 1})
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_mostrador_venta_gestion({"accion": "desconocida"})

    def test_compacted_names_are_not_callable(self):
        server = faro_mcp.FaroToolRuntime()
        for name in {"mostrador_venta_guardar", "mostrador_venta_borrar", "mostrador_pedido_cargar", "venta_albaran_crear"}:
            response = legacy_handle_for_test(server, {
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            })
            self.assertIn("error", response)
            self.assertIn("Herramienta desconocida", response["error"]["message"])

    def test_sales_tool_schema_exposes_explicit_actions(self):
        definitions = {item["name"]: item for item in faro_mcp.tool_definitions()}
        schema = definitions["mostrador_venta_gestion"]["inputSchema"]
        self.assertEqual(schema["properties"]["accion"]["enum"], ["guardar", "borrar", "cargar_pedido"])
        self.assertIn("accion", schema["required"])
        self.assertIn("venta_documento_crear", definitions)
        self.assertNotIn("venta_albaran_crear", definitions)


if __name__ == "__main__":
    unittest.main()
