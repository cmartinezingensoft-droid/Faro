"""Compatibilidad de pruebas históricas tras migrar el transporte al SDK oficial.

Este módulo existe solo en tests. Producción ya no contiene parser/dispatcher JSON-RPC manual.
"""
from __future__ import annotations

import json
from typing import Any

import faro_mcp


def legacy_handle_for_test(runtime: faro_mcp.FaroToolRuntime, message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": faro_mcp.tool_definitions(runtime.tool_profile)}}
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": (message.get("params") or {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "faro-mcp", "version": faro_mcp.SERVER_VERSION},
            },
        }
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name", ""))
        if name not in runtime.tools:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32000, "message": f"Herramienta desconocida: {name}"}}
        result, is_error = runtime.invoke_tool(
            name,
            params.get("arguments") or {},
            request_id=str(msg_id) if msg_id is not None else None,
        )
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                "isError": is_error,
            },
        }
    if method == "notifications/initialized":
        return None
    raise AssertionError(f"Metodo legacy de prueba no soportado: {method}")
