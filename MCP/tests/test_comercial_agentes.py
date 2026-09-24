import faro_mcp


def test_comercial_agent_tools_are_public_readonly_core():
    names = {
        "comercial_agente_actividades",
        "comercial_agente_analisis",
        "comercial_agente_clientes",
        "comercial_agente_productos",
        "comercial_agente_visitas_ventas_clientes",
        "comercial_agente_visitas_ventas_oportunidades",
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


def test_comercial_visit_sales_tools_expose_comparison_controls():
    definitions = {item["name"]: item for item in faro_mcp.tool_definitions("core")}

    clients_schema = definitions["comercial_agente_visitas_ventas_clientes"]["inputSchema"]["properties"]
    assert "solo_visitas" in clients_schema
    assert "tipos_actividad" in clients_schema
    assert "visitas_alta_desde" in clients_schema
    assert "visitas_baja_hasta" in clients_schema
    assert "venta_por_visita" in clients_schema["ordenar_por"]["enum"]
    assert "dias_desde_ultima_visita" in clients_schema["ordenar_por"]["enum"]

    opportunities_schema = definitions["comercial_agente_visitas_ventas_oportunidades"]["inputSchema"]["properties"]
    assert "limite_por_categoria" in opportunities_schema
    assert "limite_base" in opportunities_schema
