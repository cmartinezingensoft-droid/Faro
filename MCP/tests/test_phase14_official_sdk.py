import asyncio
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import faro_mcp


class _Tool:
    def __init__(self, *, name, description="", input_schema=None, **kwargs):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.kwargs = kwargs


class _TextContent:
    def __init__(self, *, type, text):
        self.type = type
        self.text = text


class _ListToolsResult:
    def __init__(self, *, tools):
        self.tools = tools


class _CallToolResult:
    def __init__(self, *, content, is_error=False, **kwargs):
        self.content = content
        self.is_error = is_error
        self.kwargs = kwargs


class _CallToolRequestParams:
    def __init__(self, name, arguments=None):
        self.name = name
        self.arguments = arguments


class _PaginatedRequestParams:
    pass


class _ServerRequestContext:
    pass


class _Server:
    def __init__(self, name, **kwargs):
        self.name = name
        self.kwargs = kwargs
        self.run_calls = []
        self.http_calls = []

    def create_initialization_options(self):
        return {"sdk": True}

    async def run(self, read, write, options):
        self.run_calls.append((read, write, options))

    def streamable_http_app(self, **kwargs):
        self.http_calls.append(kwargs)
        return {"asgi": True, "kwargs": kwargs}


def _load_sdk_module():
    mcp = types.ModuleType("mcp")
    mcp_server = types.ModuleType("mcp.server")
    mcp_stdio = types.ModuleType("mcp.server.stdio")
    mcp_types = types.ModuleType("mcp.types")

    mcp_server.Server = _Server
    mcp_server.ServerRequestContext = _ServerRequestContext

    class _UnusedStdio:
        def __aenter__(self):
            raise AssertionError("No debe usarse en estas pruebas")

    mcp_stdio.stdio_server = lambda: _UnusedStdio()

    mcp_types.CallToolRequestParams = _CallToolRequestParams
    mcp_types.CallToolResult = _CallToolResult
    mcp_types.ListToolsResult = _ListToolsResult
    mcp_types.PaginatedRequestParams = _PaginatedRequestParams
    mcp_types.TextContent = _TextContent
    mcp_types.Tool = _Tool

    modules = {
        "mcp": mcp,
        "mcp.server": mcp_server,
        "mcp.server.stdio": mcp_stdio,
        "mcp.types": mcp_types,
    }
    with patch.dict(sys.modules, modules):
        sys.modules.pop("mcp_sdk_server", None)
        module = importlib.import_module("mcp_sdk_server")
    return module


class Phase14OfficialSdkTests(unittest.TestCase):
    def test_manual_protocol_transport_is_removed_from_runtime(self):
        source = Path(faro_mcp.__file__).read_text(encoding="utf-8")
        self.assertNotIn("def read_message(", source)
        self.assertNotIn("def write_message(", source)
        self.assertNotIn("def handle(self, message", source)
        self.assertNotIn("Content-Length:", source)
        self.assertNotIn('method == "initialize"', source)
        self.assertNotIn('method == "tools/list"', source)
        self.assertNotIn('method == "tools/call"', source)

    def test_sdk_dependency_is_pinned_to_v2_line(self):
        requirements = (Path(__file__).parents[1] / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("mcp>=2.2.0,<3.0.0", requirements)

    def test_sdk_server_preserves_profile_catalog_and_version(self):
        sdk = _load_sdk_module()
        with patch.dict("os.environ", {"FARO_MCP_TOOL_PROFILE": "core"}):
            runtime = faro_mcp.FaroToolRuntime()
        server = sdk.build_server(runtime)
        self.assertEqual(server.name, "faro-mcp")
        self.assertEqual(server.kwargs["version"], "2.15.8")
        self.assertTrue(callable(server.kwargs["on_list_tools"]))
        self.assertTrue(callable(server.kwargs["on_call_tool"]))

        result = asyncio.run(server.kwargs["on_list_tools"](SimpleNamespace(), None))
        self.assertEqual(len(result.tools), 87)
        self.assertEqual(
            {tool.name for tool in result.tools},
            {item["name"] for item in faro_mcp.tool_definitions("core")},
        )
        by_name = {tool.name: tool for tool in result.tools}
        self.assertEqual(
            by_name["stock_consultar"].input_schema,
            next(x for x in faro_mcp.tool_definitions("core") if x["name"] == "stock_consultar")["inputSchema"],
        )

    def test_sdk_call_tool_delegates_to_business_runtime(self):
        sdk = _load_sdk_module()
        runtime = Mock()
        runtime.tool_profile = "core"
        runtime.invoke_tool.return_value = (
            {"ok": True, "data": {"existencias": 7}, "warnings": [], "meta": {"tool": "stock_consultar"}},
            False,
        )
        adapter = sdk.FaroSdkAdapter(runtime)
        params = _CallToolRequestParams("stock_consultar", {"articulo": "A1"})
        result = asyncio.run(adapter.call_tool(SimpleNamespace(request_id="req-14"), params))
        runtime.invoke_tool.assert_called_once_with(
            "stock_consultar", {"articulo": "A1"}, request_id="req-14"
        )
        self.assertFalse(result.is_error)
        payload = json.loads(result.content[0].text)
        self.assertEqual(payload["data"]["existencias"], 7)

    def test_sdk_call_tool_preserves_tool_errors_as_is_error(self):
        sdk = _load_sdk_module()
        runtime = Mock()
        runtime.tool_profile = "core"
        runtime.invoke_tool.return_value = (
            {"ok": False, "error": {"code": "FORBIDDEN", "message": "denegado"}, "warnings": [], "meta": {}},
            True,
        )
        adapter = sdk.FaroSdkAdapter(runtime)
        result = asyncio.run(
            adapter.call_tool(SimpleNamespace(request_id=22), _CallToolRequestParams("pedido_cerrar", {}))
        )
        self.assertTrue(result.is_error)
        self.assertEqual(json.loads(result.content[0].text)["error"]["code"], "FORBIDDEN")

    def test_streamable_http_is_explicit_and_localhost_by_default(self):
        sdk = _load_sdk_module()
        fake_server = _Server("faro-mcp")
        with patch.dict("os.environ", {}, clear=False):
            import os
            for key in (
                "FARO_MCP_HTTP_HOST", "FARO_MCP_HTTP_PATH",
                "FARO_MCP_HTTP_STATELESS", "FARO_MCP_HTTP_JSON_RESPONSE",
            ):
                os.environ.pop(key, None)
            app = sdk.build_streamable_http_app(fake_server)
        self.assertTrue(app["asgi"])
        args = fake_server.http_calls[-1]
        self.assertEqual(args["host"], "127.0.0.1")
        self.assertEqual(args["streamable_http_path"], "/mcp")
        self.assertTrue(args["stateless_http"])
        self.assertTrue(args["json_response"])

    def test_server_entrypoint_uses_sdk_adapter(self):
        source = (Path(__file__).parents[1] / "server.py").read_text(encoding="utf-8")
        self.assertIn("from mcp_sdk_server import main", source)
        self.assertNotIn("from faro_mcp import main", source)

    def test_runtime_version_and_contract_stay_separate(self):
        self.assertEqual(faro_mcp.SERVER_VERSION, "2.15.8")
        self.assertEqual(faro_mcp.PUBLIC_CONTRACT_VERSION, "2.0")
        self.assertEqual(len(faro_mcp.tool_definitions("core")), 87)
        self.assertEqual(len(faro_mcp.tool_definitions("admin")), 96)
        self.assertEqual(len(faro_mcp.tool_definitions("integrations")), 88)
        self.assertEqual(len(faro_mcp.tool_definitions("all")), 97)


if __name__ == "__main__":
    unittest.main()
