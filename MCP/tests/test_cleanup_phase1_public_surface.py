import unittest

import faro_mcp
from tests._runtime_compat import legacy_handle_for_test


class CleanupPhase1PublicSurfaceTests(unittest.TestCase):
    def test_technical_primitives_are_not_public_or_callable_through_mcp(self):
        server = faro_mcp.FaroToolRuntime()
        definitions = {item["name"] for item in faro_mcp.tool_definitions()}

        self.assertEqual(len(server.tools), 87)
        self.assertEqual(len(definitions), 87)
        retired = {
            "busqueda_sql", "abrir_consulta", "ejecutar_sql",
            "inicializa_conexion", "echo_string", "reverse_string",
            "bloqueo_vencaj", "enviar_correo", "get_fichero",
        }
        self.assertTrue(retired.isdisjoint(server.tools))
        self.assertTrue(retired.isdisjoint(definitions))
        for name in retired:
            response = legacy_handle_for_test(server, {
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            })
            self.assertIn("Herramienta desconocida", response["error"]["message"])

    def test_business_tools_remain_public(self):
        server = faro_mcp.FaroToolRuntime()
        expected = {
            "articulo_obtener", "articulo_buscar", "cliente_actualizar",
            "pedido_crear", "mostrador_venta_gestion", "venta_documento_crear",
            "mostrador_cobrar", "stock_trasvasar", "pedido_enviar", "pedido_pdf_gestion",
        }
        self.assertTrue(expected.issubset(server.tools))
        self.assertNotIn("control_horario_fichar", server.tools)


if __name__ == "__main__":
    unittest.main()
