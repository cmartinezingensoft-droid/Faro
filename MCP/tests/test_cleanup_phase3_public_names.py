import os
import unittest
from unittest.mock import patch

import faro_mcp
from tests._runtime_compat import legacy_handle_for_test


class CleanupPhase3PublicNamesTests(unittest.TestCase):
    def test_public_catalog_uses_only_canonical_names(self):
        server = faro_mcp.FaroToolRuntime()
        definitions = {item["name"] for item in faro_mcp.tool_definitions()}
        self.assertEqual(len(server.tools), 87)
        self.assertEqual(len(definitions), 87)
        self.assertEqual(set(server.tools), definitions)
        self.assertEqual(set(server.tools), set(faro_mcp.CORE_PUBLIC_TOOL_NAMES))
        self.assertNotIn("list_price_tables", server.tools)

    def test_all_profile_contains_only_frozen_canonical_names(self):
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "all"}):
            server = faro_mcp.FaroToolRuntime()
        self.assertEqual(set(server.tools), set(faro_mcp.ALL_PUBLIC_TOOL_NAMES))
        self.assertEqual(set(server.tools), set(faro_mcp.ALL_PUBLIC_TOOL_NAMES))
        self.assertFalse(hasattr(faro_mcp, "PUBLIC_TOOL_RENAMES"))

    def test_unknown_noncanonical_name_is_not_callable(self):
        server = faro_mcp.FaroToolRuntime()
        response = legacy_handle_for_test(server, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "articulo_buscar_legacy", "arguments": {}},
        })
        self.assertIn("Herramienta desconocida", response["error"]["message"])

    def test_expected_business_domains_are_visible(self):
        names = set(faro_mcp.FaroToolRuntime().tools)
        expected = {
            "articulo_buscar", "articulo_obtener", "articulo_precio_cliente",
            "cliente_buscar", "cliente_actualizar", "actividad_grabar",
            "pedido_crear", "pedido_listar", "pedido_detalle", "pedido_albaranar",
            "stock_consultar", "stock_regularizar", "stock_trasvasar",
            "mostrador_venta_gestion", "mostrador_cobrar", "venta_documento_crear",
            "pedido_pdf_gestion", "articulo_compra_consultar", "articulo_catalogo_listar",
        }
        self.assertTrue(expected.issubset(names))
        self.assertNotIn("control_horario_fichar", names)


if __name__ == "__main__":
    unittest.main()
