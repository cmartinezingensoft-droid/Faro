import os
import unittest
from unittest.mock import Mock, patch

import faro_mcp
from tests._runtime_compat import legacy_handle_for_test


class CleanupPhase7CrmTests(unittest.TestCase):
    def _server_and_service(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        return server, svc

    def test_catalog_splits_crm_in_core_and_full(self):
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "core"}):
            core = faro_mcp.FaroToolRuntime()
            core_defs = {item["name"] for item in faro_mcp.tool_definitions()}
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "full"}):
            full = faro_mcp.FaroToolRuntime()
            full_defs = {item["name"] for item in faro_mcp.tool_definitions()}
        self.assertEqual(len(core.tools), 81)
        self.assertEqual(len(core_defs), 81)
        self.assertEqual(len(full.tools), 91)
        self.assertEqual(len(full_defs), 91)
        split_names = {"actividad_grabar", "actividad_listar", "actividad_tipo_listar"}
        self.assertTrue(split_names.issubset(core.tools))
        self.assertTrue(split_names.issubset(full.tools))
        self.assertNotIn("actividad_gestion", core.tools)
        self.assertNotIn("actividad_gestion", full.tools)

    def test_actividad_tipo_listar_routes_to_activity_types(self):
        server, svc = self._server_and_service()
        svc.activity_types.return_value = {"items": [{"codigo": 1}]}
        with patch.object(server, "phase1_service", return_value=svc):
            result = server.tool_actividad_tipo_listar({})
        self.assertEqual(result["items"], [{"codigo": 1}])
        svc.activity_types.assert_called_once_with()

    def test_actividad_listar_routes_combined_filters(self):
        server, svc = self._server_and_service()
        svc.list_activities.return_value = {"items": [{"id": 1}]}
        with patch.object(server, "phase1_service", return_value=svc):
            result = server.tool_actividad_listar({
                "codcli": 10, "codact": 2,
                "fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-14",
            })
        self.assertEqual(result["items"], [{"id": 1}])
        svc.list_activities.assert_called_once_with(
            10, 2, None, "2026-09-01", "2026-09-14", faro_mcp.MAX_ROWS_DEFAULT
        )

    def test_actividad_listar_requires_at_least_one_filter_at_service_level(self):
        # La validacion de "al menos un filtro" vive en FaroPhase1Service.list_activities,
        # no en el wrapper del tool; se prueba con la instancia real del servicio en
        # test_cleanup_phase2_consolidation.py. Aqui solo se comprueba que el wrapper
        # delega sin interceptar el error.
        server, svc = self._server_and_service()
        svc.list_activities.side_effect = faro_mcp.FaroError(
            "Indica al menos un filtro: cliente, tipo_actividad, representante o fecha"
        )
        with patch.object(server, "phase1_service", return_value=svc):
            with self.assertRaises(faro_mcp.FaroError):
                server.tool_actividad_listar({})

    def test_actividad_grabar_routes_write(self):
        server, svc = self._server_and_service()
        svc.save_activity.return_value = {"ok": True}
        args = {
            "codcli": 10, "subcli": 0,
            "fecha": "2026-09-14", "codact": 2, "codrep": 4,
            "texto": "Visita",
        }
        with patch.object(server, "phase1_service", return_value=svc):
            result = server.tool_actividad_grabar(args)
        self.assertTrue(result["ok"])
        svc.save_activity.assert_called_once_with(10, 0, "2026-09-14", 2, 4, "Visita")

    def test_actividad_grabar_validates_required_fields(self):
        server = faro_mcp.FaroToolRuntime()
        for args in (
            {},
            {"codcli": 1},
            {"codcli": 1, "subcli": 0, "fecha": "2026-09-14", "codact": 2},
        ):
            with self.subTest(args=args):
                with self.assertRaises(faro_mcp.FaroError):
                    server.tool_actividad_grabar(args)

    def test_old_actividad_gestion_tool_is_not_callable(self):
        server = faro_mcp.FaroToolRuntime()
        response = legacy_handle_for_test(server, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "actividad_gestion", "arguments": {}},
        })
        self.assertIn("error", response)
        self.assertIn("Herramienta desconocida", response["error"]["message"])

    def test_cliente_ultimas_ventas_remains_public(self):
        server = faro_mcp.FaroToolRuntime()
        self.assertIn("cliente_ultimas_ventas", server.tools)


if __name__ == "__main__":
    unittest.main()
