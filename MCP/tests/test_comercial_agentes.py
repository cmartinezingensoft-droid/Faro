import faro_mcp


def test_comercial_agent_tools_are_public_readonly_core():
    names = {
        "comercial_agente_actividades",
        "comercial_agente_analisis",
        "comercial_agente_clientes",
        "comercial_agente_productos",
    }
    definitions = {item["name"]: item for item in faro_mcp.tool_definitions("core")}

    assert names.issubset(definitions)
    assert names.issubset(faro_mcp.READ_ONLY_TOOL_NAMES)
    assert names.issubset(faro_mcp.CORE_PUBLIC_TOOL_NAMES)

    for name in names:
        schema = definitions[name]["inputSchema"]
        assert {"representante", "fecha_desde", "fecha_hasta"}.issubset(schema["required"])
        assert "centro" in schema["properties"]
        assert faro_mcp.effective_tool_risk(name, {}) == "read"
