import os
import unittest
from unittest.mock import patch

import faro_mcp
from tests._runtime_compat import legacy_handle_for_test


class CleanupPhase10ProfilesTests(unittest.TestCase):
    def _surface(self, profile):
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": profile}):
            server = faro_mcp.FaroToolRuntime()
            definitions = {item["name"] for item in faro_mcp.tool_definitions()}
        return server, definitions

    def test_core_contract_includes_supplier_tariff(self):
        server, definitions = self._surface("core")
        self.assertEqual(set(server.tools), set(faro_mcp.CORE_PUBLIC_TOOL_NAMES))
        self.assertEqual(definitions, set(faro_mcp.CORE_PUBLIC_TOOL_NAMES))
        self.assertEqual(len(server.tools), 81)

    def test_admin_is_core_plus_nine_admin_tools(self):
        server, definitions = self._surface("admin")
        expected = set(faro_mcp.CORE_PUBLIC_TOOL_NAMES | faro_mcp.ADMIN_PUBLIC_TOOL_NAMES)
        self.assertEqual(set(server.tools), expected)
        self.assertEqual(definitions, expected)
        self.assertEqual(len(server.tools), 90)
        self.assertTrue(faro_mcp.INTEGRATION_PUBLIC_TOOL_NAMES.isdisjoint(server.tools))

    def test_integrations_is_core_plus_integration_tools(self):
        server, definitions = self._surface("integrations")
        expected = set(faro_mcp.CORE_PUBLIC_TOOL_NAMES | faro_mcp.INTEGRATION_PUBLIC_TOOL_NAMES)
        self.assertEqual(set(server.tools), expected)
        self.assertEqual(definitions, expected)
        self.assertEqual(len(server.tools), 82)
        self.assertTrue(faro_mcp.ADMIN_PUBLIC_TOOL_NAMES.isdisjoint(server.tools))

    def test_all_exposes_complete_canonical_contract(self):
        server, definitions = self._surface("all")
        self.assertEqual(set(server.tools), set(faro_mcp.ALL_PUBLIC_TOOL_NAMES))
        self.assertEqual(definitions, set(faro_mcp.ALL_PUBLIC_TOOL_NAMES))
        self.assertEqual(len(server.tools), 91)

    def test_full_is_backwards_compatible_alias_for_all(self):
        server, definitions = self._surface("full")
        self.assertEqual(server.tool_profile, "all")
        self.assertEqual(set(server.tools), set(faro_mcp.ALL_PUBLIC_TOOL_NAMES))
        self.assertEqual(definitions, set(faro_mcp.ALL_PUBLIC_TOOL_NAMES))

    def test_profiles_reject_tools_from_other_profiles(self):
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "core"}):
            server = faro_mcp.FaroToolRuntime()
            blocked = faro_mcp.ADMIN_PUBLIC_TOOL_NAMES | faro_mcp.INTEGRATION_PUBLIC_TOOL_NAMES
            for name in blocked:
                response = legacy_handle_for_test(server, {
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": name, "arguments": {}},
                })
                self.assertIn("Herramienta desconocida", response["error"]["message"])

        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "admin"}):
            server = faro_mcp.FaroToolRuntime()
            for name in faro_mcp.INTEGRATION_PUBLIC_TOOL_NAMES:
                response = legacy_handle_for_test(server, {
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": name, "arguments": {}},
                })
                self.assertIn("Herramienta desconocida", response["error"]["message"])

    def test_unknown_profile_falls_back_to_core(self):
        server, definitions = self._surface("unknown-profile")
        self.assertEqual(server.tool_profile, "core")
        self.assertEqual(set(server.tools), set(faro_mcp.CORE_PUBLIC_TOOL_NAMES))
        self.assertEqual(definitions, set(faro_mcp.CORE_PUBLIC_TOOL_NAMES))

    def test_server_version_tracks_current_release(self):
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "core"}):
            server = faro_mcp.FaroToolRuntime()
            response = legacy_handle_for_test(server, {
                "jsonrpc": "2.0", "id": 99, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            })
        self.assertEqual(response["result"]["serverInfo"]["version"], faro_mcp.SERVER_VERSION)


if __name__ == "__main__":
    unittest.main()
