"""Adaptador oficial MCP SDK v2 para Faro.

La logica ERP, validacion, permisos, auditoria y contrato permanecen en
``faro_mcp.FaroToolRuntime``. Este modulo se limita a traducir entre los
tipos del SDK oficial y esa frontera de negocio.
"""
from __future__ import annotations

import json
import os
from typing import Any

import anyio
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from faro_mcp import FaroToolRuntime, SERVER_VERSION, tool_definitions

SERVER_NAME = "faro-mcp"
SERVER_TITLE = "Faro ERP MCP"
SERVER_DESCRIPTION = "Servidor MCP nativo para Faro ERP sobre Firebird."


class FaroSdkAdapter:
    """Une el SDK MCP oficial con el runtime de negocio de Faro."""

    def __init__(self, runtime: FaroToolRuntime | None = None):
        self.runtime = runtime or FaroToolRuntime()

    async def list_tools(
        self,
        ctx: ServerRequestContext,
        params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        del ctx, params
        tools = [
            Tool(
                name=definition["name"],
                description=definition.get("description", ""),
                input_schema=definition["inputSchema"],
            )
            for definition in tool_definitions(self.runtime.tool_profile)
        ]
        return ListToolsResult(tools=tools)

    async def call_tool(
        self,
        ctx: ServerRequestContext,
        params: CallToolRequestParams,
    ) -> CallToolResult:
        request_id = getattr(ctx, "request_id", None)
        result, is_error = self.runtime.invoke_tool(
            params.name,
            params.arguments or {},
            request_id=str(request_id) if request_id is not None else None,
        )
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False, indent=2),
                )
            ],
            is_error=is_error,
        )


def build_server(runtime: FaroToolRuntime | None = None) -> Server:
    """Construye el servidor low-level oficial conservando los schemas v2."""
    adapter = FaroSdkAdapter(runtime)
    server = Server(
        SERVER_NAME,
        version=SERVER_VERSION,
        title=SERVER_TITLE,
        description=SERVER_DESCRIPTION,
        on_list_tools=adapter.list_tools,
        on_call_tool=adapter.call_tool,
    )
    return server


async def run_stdio_async(server: Server | None = None) -> None:
    """Ejecuta Faro por stdio usando el framing y lifecycle del SDK."""
    sdk_server = server or build_server()
    async with stdio_server() as (read_stream, write_stream):
        await sdk_server.run(
            read_stream,
            write_stream,
            sdk_server.create_initialization_options(),
        )


def build_streamable_http_app(server: Server | None = None):
    """Devuelve una app ASGI Streamable HTTP oficial.

    El bind por defecto es localhost. La autenticacion HTTP no se habilita
    automaticamente: no exponga este endpoint a Internet sin una politica de
    autenticacion/autorizacion de despliegue.
    """
    sdk_server = server or build_server()
    host = os.getenv("FARO_MCP_HTTP_HOST", "127.0.0.1")
    path = os.getenv("FARO_MCP_HTTP_PATH", "/mcp")
    stateless = os.getenv("FARO_MCP_HTTP_STATELESS", "true").lower() in {"1", "true", "yes", "si"}
    json_response = os.getenv("FARO_MCP_HTTP_JSON_RESPONSE", "true").lower() in {"1", "true", "yes", "si"}
    return sdk_server.streamable_http_app(
        streamable_http_path=path,
        stateless_http=stateless,
        json_response=json_response,
        host=host,
    )


def run_streamable_http(server: Server | None = None) -> None:
    """Sirve Streamable HTTP con uvicorn, solo cuando se solicita expresamente."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - depende del entorno de despliegue
        raise RuntimeError("Instala 'uvicorn' para usar FARO_MCP_TRANSPORT=streamable-http") from exc

    host = os.getenv("FARO_MCP_HTTP_HOST", "127.0.0.1")
    port = int(os.getenv("FARO_MCP_HTTP_PORT", "8000"))
    app = build_streamable_http_app(server)
    uvicorn.run(app, host=host, port=port, log_level=os.getenv("FARO_MCP_HTTP_LOG_LEVEL", "info"))


def main() -> None:
    transport = os.getenv("FARO_MCP_TRANSPORT", "stdio").strip().lower()
    server = build_server()
    if transport == "stdio":
        anyio.run(run_stdio_async, server)
        return
    if transport in {"streamable-http", "http"}:
        run_streamable_http(server)
        return
    raise RuntimeError(
        "FARO_MCP_TRANSPORT no valido. Usa 'stdio' o 'streamable-http'."
    )


if __name__ == "__main__":
    main()
