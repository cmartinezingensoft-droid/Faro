import os
import unittest
from unittest.mock import Mock, patch

import faro_mcp
from tests._runtime_compat import legacy_handle_for_test


class CleanupPhase5StorageManagementTests(unittest.TestCase):
    def _server_and_service(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        return server, svc

    def test_catalog_is_compacted_in_core_and_full(self):
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
        expected = {"etiqueta_gestion", "recuento_gestion", "falta_gestion"}
        self.assertTrue(expected.issubset(core.tools))
        self.assertTrue(expected.issubset(full.tools))
        self.assertTrue({"etiqueta_listar", "etiqueta_grabar", "etiqueta_borrar", "recuento_listar", "recuento_grabar", "recuento_borrar", "falta_listar", "falta_grabar", "falta_borrar"}.isdisjoint(full.tools))

    def test_etiqueta_gestion_routes_all_actions(self):
        server, svc = self._server_and_service()
        svc.get_labels.return_value = {"cantidad": "2"}
        svc.list_labels.return_value = {"items": []}
        svc.save_labels.return_value = {"ok": True, "accion": "grabar"}
        svc.delete_labels.return_value = {"ok": True, "accion": "borrar"}
        with patch.object(server, "phase1_service", return_value=svc):
            one = server.tool_etiqueta_gestion({"accion": "listar", "codart": "A"})
            all_ = server.tool_etiqueta_gestion({"accion": "listar"})
            saved = server.tool_etiqueta_gestion({
                "accion": "grabar", "codart": "A", "descri": "Articulo", "cantid": "3",
                "aumentar": True, "modelo": 1, "imprimir": False,
            })
            deleted = server.tool_etiqueta_gestion({"accion": "borrar", "codart": "A"})
        self.assertEqual(one["cantidad"], "2")
        self.assertEqual(all_["items"], [])
        self.assertEqual(saved["accion"], "grabar")
        self.assertEqual(deleted["accion"], "borrar")
        svc.get_labels.assert_called_once_with("A")
        svc.list_labels.assert_called_once_with()
        svc.save_labels.assert_called_once_with("A", "Articulo", "3", True, 1, False)
        svc.delete_labels.assert_called_once_with("A")

    def test_etiqueta_gestion_grabar_allows_missing_description(self):
        server, svc = self._server_and_service()
        svc.save_labels.return_value = {"ok": True}
        with patch.object(server, "phase1_service", return_value=svc):
            server.tool_etiqueta_gestion({
                "accion": "grabar", "codart": "A", "cantid": "3",
                "aumentar": False, "modelo": 0, "imprimir": False,
            })
        svc.save_labels.assert_called_once_with("A", "", "3", False, 0, False)

    def test_recuento_gestion_routes_all_actions(self):
        server, svc = self._server_and_service()
        svc.article_recount.return_value = {"cantidad": "4"}
        svc.save_recount.return_value = {"ok": True}
        svc.delete_recount.return_value = {"ok": True}
        with patch.object(server, "phase1_service", return_value=svc):
            server.tool_recuento_gestion({"accion": "listar", "centro": 1, "codart": "A"})
            server.tool_recuento_gestion({
                "accion": "grabar", "centro": 1, "codart": "A", "descri": "Articulo",
                "unimed": "UD", "cantid": "5", "aumentar": False,
            })
            server.tool_recuento_gestion({"accion": "borrar", "centro": 1, "codart": "A"})
        svc.article_recount.assert_called_once_with("A", 1)
        svc.save_recount.assert_called_once_with("A", 1, "Articulo", "UD", "5", False)
        svc.delete_recount.assert_called_once_with("A", 1)

    def test_recuento_gestion_grabar_allows_missing_description_and_unit(self):
        # descripcion/unidad_medida son opcionales desde que save_recount las
        # autocompleta leyendo ARTICUL (igual que ya hacia stock_regularizar).
        server, svc = self._server_and_service()
        svc.save_recount.return_value = {"ok": True}
        with patch.object(server, "phase1_service", return_value=svc):
            server.tool_recuento_gestion({
                "accion": "grabar", "centro": 1, "codart": "A", "cantid": "5", "aumentar": False,
            })
        svc.save_recount.assert_called_once_with("A", 1, "", "", "5", False)

    def test_falta_gestion_unifies_provider_argument(self):
        server, svc = self._server_and_service()
        svc.save_shortage.return_value = {"ok": True}
        svc.delete_shortage.return_value = {"ok": True}
        with patch.object(server, "phase1_service", return_value=svc):
            server.tool_falta_gestion({
                "accion": "grabar", "centro": 1, "codart": "A", "proveedor": 0,
                "cantid": "6", "aumentar": True,
            })
            server.tool_falta_gestion({
                "accion": "borrar", "centro": 1, "codart": "A", "proveedor": 12,
            })
        svc.save_shortage.assert_called_once_with("A", 1, 0, "6", True)
        svc.delete_shortage.assert_called_once_with("A", 1, 12)

    def test_falta_gestion_routes_listar_action(self):
        # A diferencia de etiqueta_gestion y recuento_gestion (ver
        # test_etiqueta_gestion_routes_all_actions / test_recuento_gestion_routes_all_actions),
        # la accion "listar" de falta_gestion -que ademas es la accion por
        # defecto- no tenia ninguna prueba, ni con codart (ficha de una
        # falta) ni sin el (listado del centro).
        server, svc = self._server_and_service()
        svc.article_shortage.return_value = {"codart": "A", "cantid": "2"}
        svc.list_shortages.return_value = {"items": []}
        with patch.object(server, "phase1_service", return_value=svc):
            one = server.tool_falta_gestion({"accion": "listar", "centro": 1, "codart": "A"})
            all_ = server.tool_falta_gestion({"centro": 1})
        self.assertEqual(one["cantid"], "2")
        self.assertEqual(all_["items"], [])
        svc.article_shortage.assert_called_once_with("A", 1)
        svc.list_shortages.assert_called_once_with(1)

    def test_management_validates_action_specific_fields(self):
        server = faro_mcp.FaroToolRuntime()
        with self.assertRaises(faro_mcp.FaroError):
            # cantid/aumentar/modelo/imprimir siguen siendo obligatorios; descri se autocompleta.
            server.tool_etiqueta_gestion({"accion": "grabar", "codart": "A"})
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_recuento_gestion({"accion": "borrar", "centro": 1})
        with self.assertRaises(faro_mcp.FaroError):
            # cantid/aumentar siguen siendo obligatorios; solo descri/unimed son opcionales.
            server.tool_recuento_gestion({"accion": "grabar", "centro": 1, "codart": "A"})
        with self.assertRaises(faro_mcp.FaroError):
            server.tool_falta_gestion({"accion": "borrar", "centro": 1, "codart": "A"})

    def test_old_storage_tools_are_not_callable(self):
        server = faro_mcp.FaroToolRuntime()
        for name in {"etiqueta_listar", "etiqueta_grabar", "etiqueta_borrar", "recuento_listar", "recuento_grabar", "recuento_borrar", "falta_listar", "falta_grabar", "falta_borrar"}:
            with self.subTest(name=name):
                response = legacy_handle_for_test(server, {
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": name, "arguments": {}},
                })
                self.assertIn("error", response)
                self.assertIn("Herramienta desconocida", response["error"]["message"])


if __name__ == "__main__":
    unittest.main()
