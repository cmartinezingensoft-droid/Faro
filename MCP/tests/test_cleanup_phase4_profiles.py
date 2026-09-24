import os
import unittest
from unittest.mock import patch

import faro_mcp
from tests._runtime_compat import legacy_handle_for_test


class CleanupPhase4ProfilesTests(unittest.TestCase):
    def test_core_is_default_and_has_45_tools(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FARO_MCP_TOOL_PROFILE", None)
            server = faro_mcp.FaroToolRuntime()
            definitions = {item["name"] for item in faro_mcp.tool_definitions()}
        self.assertEqual(server.tool_profile, "core")
        self.assertEqual(len(server.tools), 81)
        self.assertEqual(len(definitions), 81)
        self.assertEqual(set(server.tools), definitions)
        self.assertTrue((faro_mcp.ADMIN_PUBLIC_TOOL_NAMES | faro_mcp.INTEGRATION_PUBLIC_TOOL_NAMES).isdisjoint(server.tools))

    def test_full_restores_all_55_canonical_tools(self):
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "full"}):
            server = faro_mcp.FaroToolRuntime()
            definitions = {item["name"] for item in faro_mcp.tool_definitions()}
        self.assertEqual(server.tool_profile, "all")
        self.assertEqual(len(server.tools), 91)
        self.assertEqual(len(definitions), 91)
        self.assertTrue((faro_mcp.ADMIN_PUBLIC_TOOL_NAMES | faro_mcp.INTEGRATION_PUBLIC_TOOL_NAMES).issubset(server.tools))

    def test_advanced_tools_are_not_callable_in_core(self):
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "core"}):
            server = faro_mcp.FaroToolRuntime()
            for name in (faro_mcp.ADMIN_PUBLIC_TOOL_NAMES | faro_mcp.INTEGRATION_PUBLIC_TOOL_NAMES):
                with self.subTest(name=name):
                    response = legacy_handle_for_test(server, {
                        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": {}},
                    })
                    self.assertIn("error", response)
                    self.assertIn("Herramienta desconocida", response["error"]["message"])

    def test_tools_list_uses_same_profile_as_dispatcher(self):
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "core"}):
            server = faro_mcp.FaroToolRuntime()
            response = legacy_handle_for_test(server, {"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
        listed = {item["name"] for item in response["result"]["tools"]}
        self.assertEqual(listed, set(server.tools))

    def test_invalid_profile_falls_back_to_core(self):
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "inventado"}):
            server = faro_mcp.FaroToolRuntime()
        self.assertEqual(server.tool_profile, "core")
        self.assertEqual(len(server.tools), 81)


if __name__ == "__main__":
    unittest.main()
