import os
import unittest
from unittest.mock import Mock, patch

import faro_mcp
from tests._runtime_compat import legacy_handle_for_test


class CleanupPhase8ArticlesTests(unittest.TestCase):
    def _server_and_service(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        svc.settings = Mock(empresa=1)
        return server, svc

    def test_catalog_compacts_articles_in_core_and_full(self):
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
        for name in ("articulo_obtener", "articulo_compra_consultar", "articulo_catalogo_listar"):
            self.assertIn(name, core.tools)
            self.assertIn(name, full.tools)
        self.assertTrue({"articulo_info_tecnica", "articulo_imagen_obtener", "articulo_proveedor_listar", "articulo_ficha_compra", "marca_listar", "familia_listar"}.isdisjoint(full.tools))

    def test_articulo_obtener_is_light_by_default(self):
        server, svc = self._server_and_service()
        svc.find_article.return_value = {"codart": "A1", "descri": "Articulo"}
        svc.db.fetch_one.return_value = {"ART_CODART": "A1", "ART_DESCRI": "Articulo"}
        svc.article_brand.return_value = {"marca": "MARCA"}
        with patch.object(server, "phase1_service", return_value=svc):
            result = server.tool_articulo_obtener({"identificador": "A1"})
        self.assertTrue(result["found"])
        self.assertEqual(result["codart"], "A1")
        self.assertNotIn("tecnica", result)
        self.assertNotIn("imagen", result)
        svc.article_technical_info.assert_not_called()
        svc.article_image_as_json.assert_not_called()

    def test_articulo_obtener_can_include_technical_info_and_image(self):
        server, svc = self._server_and_service()
        svc.find_article.return_value = {"codart": "A1", "descri": "Articulo"}
        svc.db.fetch_one.return_value = {"ART_CODART": "A1"}
        svc.article_brand.return_value = {"marca": "MARCA"}
        svc.article_technical_info.return_value = {"codart": "A1", "text": "Ficha tecnica"}
        svc.article_image_as_json.return_value = {"articulo": "A1", "content_base64": "AAAA"}
        with patch.object(server, "phase1_service", return_value=svc):
            result = server.tool_articulo_obtener({
                "identificador": "A1",
                "incluir": ["tecnica", "imagen"],
                "tamano_imagen": "P",
            })
        self.assertEqual(result["tecnica"]["text"], "Ficha tecnica")
        self.assertEqual(result["imagen"]["content_base64"], "AAAA")
        svc.article_technical_info.assert_called_once_with("A1")
        svc.article_image_as_json.assert_called_once_with("A1", "P")

    def test_articulo_obtener_validates_include(self):
        server = faro_mcp.FaroToolRuntime()
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_articulo_obtener({"identificador": "A1", "incluir": "imagen"})
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_articulo_obtener({"identificador": "A1", "incluir": ["desconocido"]})

    def test_articulo_compra_consultar_routes_supplier_list_and_sheet(self):
        server, svc = self._server_and_service()
        svc.article_suppliers.return_value = {"codart": "A1", "items": [{"codpro": 10}]}
        svc.article_purchase_sheet.return_value = {"codart": "A1", "codpro": 10, "found": True, "precos": "5"}
        with patch.object(server, "phase1_service", return_value=svc):
            providers = server.tool_articulo_compra_consultar({"codart": "A1"})
            sheet = server.tool_articulo_compra_consultar({"codart": "A1", "codpro": 10})
        self.assertEqual(providers["modo"], "proveedores")
        self.assertEqual(sheet["modo"], "ficha")
        svc.article_suppliers.assert_called_once_with("A1")
        svc.article_purchase_sheet.assert_called_once_with("A1", 10)

    def test_articulo_catalogo_listar_routes_all_catalogs(self):
        server, svc = self._server_and_service()
        svc.list_brands.return_value = {"items": ["M1"]}
        svc.list_families.return_value = {"items": [{"codigo": 1}]}
        svc.list_web_families.return_value = {"items": [{"codigo": "W"}]}
        with patch.object(server, "phase1_service", return_value=svc):
            marcas = server.tool_articulo_catalogo_listar({"tipo": "marcas"})
            familias = server.tool_articulo_catalogo_listar({"tipo": "familias", "padre": "1"})
            web = server.tool_articulo_catalogo_listar({"tipo": "familias_web", "padre": "R"})
        self.assertEqual(marcas["tipo"], "marcas")
        self.assertEqual(familias["tipo"], "familias")
        self.assertEqual(web["tipo"], "familias_web")
        svc.list_brands.assert_called_once_with()
        svc.list_families.assert_called_once_with("1")
        svc.list_web_families.assert_called_once_with("R")

    def test_articulo_catalogo_listar_validates_type_and_parent(self):
        server = faro_mcp.FaroToolRuntime()
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_articulo_catalogo_listar({"tipo": "otro"})
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_articulo_catalogo_listar({"tipo": "marcas", "padre": "X"})

    def test_old_article_tools_are_not_callable(self):
        server = faro_mcp.FaroToolRuntime()
        for name in {"articulo_info_tecnica", "articulo_imagen_obtener", "articulo_proveedor_listar", "articulo_ficha_compra", "marca_listar", "familia_listar"}:
            with self.subTest(name=name):
                response = legacy_handle_for_test(server, {
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": name, "arguments": {}},
                })
                self.assertIn("error", response)
                self.assertIn("Herramienta desconocida", response["error"]["message"])


if __name__ == "__main__":
    unittest.main()
