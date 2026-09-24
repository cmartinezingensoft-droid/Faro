import os
import unittest
from unittest.mock import Mock, patch

import faro_mcp
from tests._runtime_compat import legacy_handle_for_test


class CleanupPhase6OrdersTests(unittest.TestCase):
    def _server_and_service(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        return server, svc

    def test_catalog_compacts_orders_in_core_and_full(self):
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "core"}):
            core = faro_mcp.FaroToolRuntime()
            core_defs = {item["name"] for item in faro_mcp.tool_definitions()}
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "full"}):
            full = faro_mcp.FaroToolRuntime()
            full_defs = {item["name"] for item in faro_mcp.tool_definitions()}
        self.assertEqual(len(core.tools), 85)
        self.assertEqual(len(core_defs), 85)
        self.assertEqual(len(full.tools), 95)
        self.assertEqual(len(full_defs), 95)
        self.assertIn("pedido_listar", core.tools)
        self.assertIn("pedido_pdf_gestion", core.tools)
        self.assertTrue({"pedido_listar_cliente", "pedido_pdf_generar", "pedido_pdf_obtener"}.isdisjoint(full.tools))

    def test_pedido_listar_routes_operational_and_client_modes(self):
        server, svc = self._server_and_service()
        svc.order_board.return_value = [{"numdoc": 1}]
        svc.list_client_orders.return_value = [{"numdoc": 2}]
        with patch.object(server, "phase1_service", return_value=svc):
            operational = server.tool_pedido_listar({"centro": 1})
            client = server.tool_pedido_listar({"centro": 1, "codcli": 10, "subcli": 0})
        self.assertEqual(operational, [{"numdoc": 1}])
        self.assertEqual(client, [{"numdoc": 2}])
        svc.order_board.assert_called_once_with(1)
        svc.list_client_orders.assert_called_once_with(1, 10, 0)

    def test_pedido_listar_requires_complete_client_key(self):
        server = faro_mcp.FaroToolRuntime()
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_pedido_listar({"centro": 1, "codcli": 10})
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_pedido_listar({"centro": 1, "subcli": 0})

    def test_pedido_pdf_gestion_routes_generate_and_get(self):
        server, svc = self._server_and_service()
        svc.generate_order_pdf.return_value = {"ok": True, "path": "pedido.pdf"}
        svc.order_pdf_as_json.return_value = {"ok": True, "base64": "AAAA"}
        base = {"ejerci": 2026, "serie": "A", "numdoc": 12}
        with patch.object(server, "phase1_service", return_value=svc):
            generated = server.tool_pedido_pdf_gestion({**base, "accion": "generar", "centro": 1})
            obtained = server.tool_pedido_pdf_gestion({**base, "accion": "obtener"})
        self.assertEqual(generated["path"], "pedido.pdf")
        self.assertEqual(obtained["base64"], "AAAA")
        svc.generate_order_pdf.assert_called_once_with(1, 2026, "A", 12)
        svc.order_pdf_as_json.assert_called_once_with(2026, "A", 12)

    def test_pedido_pdf_gestion_validates_action_and_center(self):
        server = faro_mcp.FaroToolRuntime()
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_pedido_pdf_gestion({"accion": "otra", "ejerci": 2026, "serie": "A", "numdoc": 1})
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_pedido_pdf_gestion({"accion": "generar", "ejerci": 2026, "serie": "A", "numdoc": 1})

    def test_pedido_detalle_wraps_real_list_results(self):
        server, svc = self._server_and_service()
        svc.order_lines.return_value = [{"numlin": 1}]
        svc.order_preparation_lines.return_value = [{"numlin": 2}]
        base = {"centro": 1, "ejerci": 2026, "serie": "A", "numdoc": 10}
        with patch.object(server, "phase1_service", return_value=svc):
            normal = server.tool_pedido_detalle(base)
            prep = server.tool_pedido_detalle({**base, "modo": "preparacion"})
        self.assertEqual(normal, {"modo": "normal", "items": [{"numlin": 1}]})
        self.assertEqual(prep, {"modo": "preparacion", "items": [{"numlin": 2}]})

    def test_old_order_tools_are_not_callable(self):
        server = faro_mcp.FaroToolRuntime()
        for name in {"pedido_listar_cliente", "pedido_pdf_generar", "pedido_pdf_obtener"}:
            with self.subTest(name=name):
                response = legacy_handle_for_test(server, {
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": name, "arguments": {}},
                })
                self.assertIn("error", response)
                self.assertIn("Herramienta desconocida", response["error"]["message"])


if __name__ == "__main__":
    unittest.main()
