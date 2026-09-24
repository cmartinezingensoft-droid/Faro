import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import faro_mcp
from tests._runtime_compat import legacy_handle_for_test


class CleanupPhase13SecurityAuditTests(unittest.TestCase):
    def _server(self, tmp, access="read", **extra):
        env = {
            "FARO_MCP_ACCESS_LEVEL": access,
            "FARO_MCP_AUDIT_LOG": str(Path(tmp) / "audit.jsonl"),
            "FARO_MCP_ACTOR": "tester",
            "FARO_MCP_CLIENT_ID": "unit-tests",
            "FARO_MCP_AUDIT_REQUIRED": "true",
        }
        env.update(extra)
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        return faro_mcp.FaroToolRuntime(), Path(env["FARO_MCP_AUDIT_LOG"])

    @staticmethod
    def _payload(response):
        return json.loads(response["result"]["content"][0]["text"])

    def test_security_classification_covers_all_tools_exactly(self):
        union = (
            faro_mcp.READ_ONLY_TOOL_NAMES
            | faro_mcp.WRITE_TOOL_NAMES
            | faro_mcp.CRITICAL_TOOL_NAMES
        )
        self.assertEqual(union, faro_mcp.ALL_PUBLIC_TOOL_NAMES)
        self.assertEqual(len(faro_mcp.READ_ONLY_TOOL_NAMES), 67)
        self.assertEqual(len(faro_mcp.WRITE_TOOL_NAMES), 16)
        self.assertEqual(len(faro_mcp.CRITICAL_TOOL_NAMES), 14)
        self.assertFalse(faro_mcp.READ_ONLY_TOOL_NAMES & faro_mcp.WRITE_TOOL_NAMES)
        self.assertFalse(faro_mcp.READ_ONLY_TOOL_NAMES & faro_mcp.CRITICAL_TOOL_NAMES)
        self.assertFalse(faro_mcp.WRITE_TOOL_NAMES & faro_mcp.CRITICAL_TOOL_NAMES)

    def test_access_level_defaults_to_critical_and_supports_aliases(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FARO_MCP_ACCESS_LEVEL", None)
            self.assertEqual(faro_mcp.public_access_level(), "critical")
        self.assertEqual(faro_mcp.public_access_level(""), "critical")
        self.assertEqual(faro_mcp.public_access_level("rw"), "write")
        self.assertEqual(faro_mcp.public_access_level("admin"), "critical")
        self.assertEqual(faro_mcp.public_access_level("unknown"), "read")

    def test_company_and_center_defaults_are_company_1_center_0(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FARO_EMPRESA", None)
            os.environ.pop("FARO_CENTRO", None)
            self.assertEqual(faro_mcp.Settings.from_env().empresa, 1)
            self.assertEqual(faro_mcp.Settings.from_env().centro, 0)
            self.assertEqual(faro_mcp.SecuritySettings.from_env().empresa, 1)
            self.assertEqual(faro_mcp.SecuritySettings.from_env().centro, 0)

    def test_mixed_tools_compute_effective_risk_by_action(self):
        self.assertEqual(faro_mcp.effective_tool_risk("actividad_listar", {}), "read")
        self.assertEqual(faro_mcp.effective_tool_risk("actividad_tipo_listar", {}), "read")
        self.assertEqual(faro_mcp.effective_tool_risk("actividad_grabar", {}), "write")
        self.assertEqual(faro_mcp.effective_tool_risk("etiqueta_gestion", {"accion": "listar"}), "read")
        self.assertEqual(faro_mcp.effective_tool_risk("etiqueta_gestion", {"accion": "borrar"}), "write")
        self.assertEqual(faro_mcp.effective_tool_risk("pedido_pdf_gestion", {"accion": "obtener"}), "read")
        self.assertEqual(faro_mcp.effective_tool_risk("pedido_pdf_gestion", {"accion": "generar"}), "write")
        self.assertEqual(faro_mcp.effective_tool_risk("articulo_cambiar_tabla_precio", {"simular": True}), "read")
        self.assertEqual(faro_mcp.effective_tool_risk("articulo_cambiar_tabla_precio", {"simular": False}), "critical")
        self.assertEqual(faro_mcp.effective_tool_risk("mostrador_venta_gestion", {"accion": "guardar"}), "write")
        self.assertEqual(faro_mcp.effective_tool_risk("mostrador_venta_gestion", {"accion": "borrar"}), "critical")

    def test_read_access_allows_reads_without_audit_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, audit_path = self._server(tmp, "read")
            server.tools["stock_consultar"] = Mock(return_value={"existencias": 7})
            response = legacy_handle_for_test(server, {
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "stock_consultar", "arguments": {"articulo": "A1"}},
            })
            self.assertFalse(response["result"]["isError"])
            server.tools["stock_consultar"].assert_called_once()
            self.assertFalse(audit_path.exists())

    def test_read_access_denies_write_and_audits_denial_with_secret_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, audit_path = self._server(tmp, "read")
            server.tools["control_horario_fichar"] = Mock(return_value={"tipo": "I"})
            response = legacy_handle_for_test(server, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "control_horario_fichar", "arguments": {"contrasena": "supersecreta"}},
            })
            payload = self._payload(response)
            self.assertTrue(response["result"]["isError"])
            self.assertEqual(payload["error"]["code"], "FORBIDDEN")
            server.tools["control_horario_fichar"].assert_not_called()
            event = json.loads(audit_path.read_text(encoding="utf-8").strip())
            self.assertEqual(event["status"], "denied")
            self.assertEqual(event["actor"], "tester")
            self.assertEqual(event["client_id"], "unit-tests")
            self.assertEqual(event["risk"], "write")
            self.assertEqual(event["arguments"]["contrasena"], "***REDACTED***")

    def test_write_access_executes_write_and_records_started_and_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, audit_path = self._server(tmp, "write")
            server.tools["control_horario_fichar"] = Mock(return_value={"tipo": "I"})
            response = legacy_handle_for_test(server, {
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "control_horario_fichar", "arguments": {"contrasena": "clave"}},
            })
            self.assertFalse(response["result"]["isError"])
            server.tools["control_horario_fichar"].assert_called_once_with({"password": "clave"})
            events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([e["status"] for e in events], ["started", "success"])
            self.assertEqual(events[0]["arguments"]["contrasena"], "***REDACTED***")
            self.assertNotIn("arguments", events[1])

    def test_write_access_denies_critical_and_critical_access_allows_it(self):
        args = {
            "articulo": "A1", "centro": 1, "descripcion": "Articulo",
            "unidad_medida": "UD", "cantidad": "10",
        }
        with tempfile.TemporaryDirectory() as tmp:
            server, _ = self._server(tmp, "write")
            server.tools["stock_regularizar"] = Mock(return_value={"ok": True})
            denied = legacy_handle_for_test(server, {
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": "stock_regularizar", "arguments": args},
            })
            self.assertEqual(self._payload(denied)["error"]["code"], "FORBIDDEN")
            server.tools["stock_regularizar"].assert_not_called()

        with tempfile.TemporaryDirectory() as tmp:
            server, audit_path = self._server(tmp, "critical")
            server.tools["stock_regularizar"] = Mock(return_value={"ok": True, "diferencia": 2})
            allowed = legacy_handle_for_test(server, {
                "jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {"name": "stock_regularizar", "arguments": args},
            })
            self.assertFalse(allowed["result"]["isError"])
            events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(events), 2)
            self.assertEqual(events[1]["result"].get("diferencia"), 2)

    def test_audit_is_fail_closed_before_a_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "not-a-directory"
            blocker.write_text("x", encoding="utf-8")
            bad_path = blocker / "audit.jsonl"
            server, _ = self._server(tmp, "write", FARO_MCP_AUDIT_LOG=str(bad_path))
            server.tools["control_horario_fichar"] = Mock(return_value={"tipo": "I"})
            response = legacy_handle_for_test(server, {
                "jsonrpc": "2.0", "id": 6, "method": "tools/call",
                "params": {"name": "control_horario_fichar", "arguments": {"contrasena": "clave"}},
            })
            payload = self._payload(response)
            self.assertEqual(payload["error"]["code"], "AUDIT_ERROR")
            server.tools["control_horario_fichar"].assert_not_called()

    def test_read_auditing_can_be_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, audit_path = self._server(tmp, "read", FARO_MCP_AUDIT_READS="true")
            server.tools["stock_consultar"] = Mock(return_value={"existencias": 1})
            response = legacy_handle_for_test(server, {
                "jsonrpc": "2.0", "id": 7, "method": "tools/call",
                "params": {"name": "stock_consultar", "arguments": {"articulo": "A1"}},
            })
            self.assertFalse(response["result"]["isError"])
            events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([e["status"] for e in events], ["started", "success"])
            self.assertEqual(events[0]["risk"], "read")


    def test_runtime_schema_rejects_wrong_types_before_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, _ = self._server(tmp, "read")
            server.tools["stock_consultar"] = Mock(return_value={"existencias": 1})
            response = legacy_handle_for_test(server, {
                "jsonrpc": "2.0", "id": 8, "method": "tools/call",
                "params": {"name": "stock_consultar", "arguments": {"articulo": 123}},
            })
            payload = self._payload(response)
            self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENT")
            self.assertIn("debe ser texto", payload["error"]["message"])
            server.tools["stock_consultar"].assert_not_called()

    def test_security_sensitive_boolean_is_fail_closed_and_schema_validated(self):
        self.assertEqual(
            faro_mcp.effective_tool_risk("articulo_cambiar_tabla_precio", {"simular": 0}),
            "critical",
        )
        with self.assertRaises(faro_mcp.FaroError):
            faro_mcp.translate_public_arguments(
                "articulo_cambiar_tabla_precio",
                {"articulo": "A1", "tabla_nueva": 2, "simular": 0},
            )

    def test_public_schema_contract_remains_unchanged(self):
        # Mismo hash que PHASE12_ALL_SCHEMA_SHA256 en
        # test_cleanup_phase11_internal_refactor.py; los motivos de cada
        # cambio intencional del contrato estan documentados alli.
        import hashlib
        payload = json.dumps(
            faro_mcp.tool_definitions("all"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "b258f79f7b0a835463cb9611e889eef3135aea0663d714a17ec20330ea36409d",
        )

    def test_server_version(self):
        self.assertEqual(faro_mcp.SERVER_VERSION, "2.15.8")
        self.assertEqual(faro_mcp.PUBLIC_CONTRACT_VERSION, "2.0")


if __name__ == "__main__":
    unittest.main()
