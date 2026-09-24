import unittest
from unittest.mock import Mock, patch

import faro_mcp


class CleanupPhase2ConsolidationTests(unittest.TestCase):
    def test_catalog_keeps_merged_names_across_core_and_full_profiles(self):
        server = faro_mcp.FaroToolRuntime()
        definitions = {item["name"] for item in faro_mcp.tool_definitions()}
        core_merged = {
            "articulo_obtener", "stock_consultar", "articulo_catalogo_listar", "etiqueta_gestion",
            "recuento_gestion", "falta_gestion", "cliente_buscar", "actividad_grabar",
            "actividad_listar", "actividad_tipo_listar",
            "pedido_detalle", "articulo_cambiar_tabla_precio", "articulo_familia_guardar",
        }
        self.assertEqual(len(server.tools), 87)
        self.assertEqual(len(definitions), 87)
        self.assertTrue(core_merged.issubset(server.tools))
        self.assertTrue(core_merged.issubset(definitions))
        self.assertNotIn("articulo_ubicacion_guardar", server.tools)

    def test_alias_infrastructure_was_removed(self):
        self.assertFalse(hasattr(faro_mcp, "PUBLIC_TOOL_RENAMES"))
        self.assertFalse(hasattr(faro_mcp, "LEGACY_PUBLIC_TOOL_NAMES"))
        self.assertFalse(any(name.startswith("tool_py_") for name in dir(faro_mcp.FaroToolRuntime)))

    def _fake_phase_service(self):
        svc = Mock()
        svc.db = Mock()
        svc.settings = Mock(empresa=1)
        return svc

    def test_stock_consultar_routes_single_or_all_centres(self):
        server = faro_mcp.FaroToolRuntime()
        svc = self._fake_phase_service()
        svc.article_stock.return_value = {"codart": "A", "centro": 2, "existencias": "7", "datasnap_text": "7"}
        svc.article_stocks.return_value = {"codart": "A", "items": [{"centro": 1, "existencias": "3"}], "datasnap_text": "1|3#"}
        with patch.object(server, "phase1_service", return_value=svc):
            one = server.tool_stock_consultar({"codart": "A", "centro": 2})
            all_ = server.tool_stock_consultar({"codart": "A"})
        self.assertEqual(one["scope"], "centro")
        self.assertEqual(all_["scope"], "todos")
        svc.article_stock.assert_called_once_with("A", 2)
        svc.article_stocks.assert_called_once_with("A")

    def test_location_routes_principal_and_secondary(self):
        server = faro_mcp.FaroToolRuntime()
        svc = self._fake_phase_service()
        svc.save_location.return_value = {"ok": True, "slot": 1}
        svc.save_location_secondary.return_value = {"ok": True, "slot": 2}
        with patch.object(server, "phase1_service", return_value=svc):
            a = server.tool_articulo_ubicacion_guardar({"codart": "A", "ubicacion": "P1", "numero": 1})
            b = server.tool_articulo_ubicacion_guardar({"codart": "A", "ubicacion": "P2", "numero": 2})
        self.assertEqual(a["slot"], 1)
        self.assertEqual(b["slot"], 2)

    def test_actividad_listar_requires_at_least_one_filter(self):
        # actividad_listar (contrato v2) admite combinar cliente, tipo_actividad,
        # representante y fecha con AND, a diferencia del extinto
        # actividad_gestion(accion=listar) que exigia exactamente uno de
        # cliente/representante. Se sigue exigiendo al menos un filtro para no
        # volcar toda la tabla ACTIVI sin acotar.
        class _EmptyActivityDb:
            settings = type("S", (), {"empresa": 1})()

            def fetch_all(self, sql, params=()):
                return []

            def fetch_one(self, sql, params=()):
                return None

            def close(self):
                pass

        server = faro_mcp.FaroToolRuntime()
        svc = faro_mcp.FaroPhase1Service(_EmptyActivityDb())
        with patch.object(server, "phase1_service", return_value=svc):
            with self.assertRaises(faro_mcp.FaroError):
                server.tool_actividad_listar({})

    def test_price_table_defaults_to_simulation(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        svc.simulate_price_table_change.return_value = {"changed": True}
        svc.change_article_price_table.return_value = {"changed": True}
        with patch.object(server, "service", return_value=svc):
            simulated = server.tool_articulo_cambiar_tabla_precio({"codart": "A", "new_table": 3})
            changed = server.tool_articulo_cambiar_tabla_precio({"codart": "A", "new_table": 3, "simular": False})
        self.assertTrue(simulated["simulado"])
        self.assertFalse(changed["simulado"])
        svc.simulate_price_table_change.assert_called_once_with("A", 3)
        svc.change_article_price_table.assert_called_once()

    def test_article_family_save_delegates_to_service(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        svc.change_article_family.return_value = {"updated": True}
        with patch.object(server, "service", return_value=svc):
            result = server.tool_articulo_familia_guardar({"codart": "A", "codfam": 4, "subfam": 2, "ssubfam": 9})
        self.assertTrue(result["updated"])
        svc.change_article_family.assert_called_once_with("A", 4, 2, 9, None)
        svc.db.close.assert_called_once()

    def test_article_family_service_updates_article_family_fields(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.db = Mock()
        svc.settings = Mock(empresa=1, usuario="tester")
        svc._article_additional_info = Mock(return_value=None)
        svc._table_from_article_family = Mock(return_value=0)
        svc.get_article = Mock(side_effect=[
            {"ART_CODART": "A", "ART_DESCRI": "Articulo", "ART_CODFAM": 1, "ART_SUBFAM": 0},
            {"ART_CODART": "A", "ART_DESCRI": "Articulo", "ART_CODFAM": 4, "ART_SUBFAM": 2},
        ])

        result = svc.change_article_family("A", 4, 2)

        sql, params = svc.db.execute.call_args.args
        self.assertIn("UPDATE ARTICUL SET ART_CODFAM=?", sql)
        self.assertEqual(params[0], 4)
        self.assertEqual(params[1], 2)
        self.assertEqual(params[-2:], (1, "A"))
        svc.db.commit.assert_called_once()
        svc.db.rollback.assert_not_called()
        self.assertTrue(result["updated"])
        self.assertEqual(result["diff"]["ART_CODFAM"], {"before": 1, "after": 4})

    def test_article_family_prefers_ssubfam_table_over_subfam_table(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc._ssubfamily_price_table = Mock(return_value=8)
        svc._subfamily_price_table = Mock(return_value=5)
        self.assertEqual(svc._table_from_article_family(4, 2, 9), 8)
        svc._subfamily_price_table.assert_not_called()

    def test_article_family_uses_subfam_table_when_ssubfam_has_no_table(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc._ssubfamily_price_table = Mock(return_value=0)
        svc._subfamily_price_table = Mock(return_value=5)
        self.assertEqual(svc._table_from_article_family(4, 2, 9), 5)
        svc._subfamily_price_table.assert_called_once_with(4, 2)

    def test_article_family_service_applies_inferred_price_table(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.db = Mock()
        svc.settings = Mock(empresa=1, usuario="tester")
        current = {
            "ART_CODART": "A", "ART_DESCRI": "Articulo", "ART_CODFAM": 1, "ART_SUBFAM": 0,
            "ART_PRECOS": 10, "ART_TABPREC": 0, "ART_PREVEN1": 11, "ART_PREVEN2": 12,
            "ART_PREVEN3": 13, "ART_PREVEN4": 14, "ART_PVP": 16,
        }
        after = {
            **current, "ART_CODFAM": 4, "ART_SUBFAM": 2, "ART_TABPREC": 5,
            "ART_PREVEN1": 21, "ART_PREVEN2": 22, "ART_PREVEN3": 23,
            "ART_PREVEN4": 24, "ART_PVP": 29,
        }
        recalculated = dict(after)
        svc.get_article = Mock(side_effect=[current, after])
        svc._article_additional_info = Mock(return_value=None)
        svc._table_from_article_family = Mock(return_value=5)
        svc.get_price_table = Mock(return_value={"TPR_CODTAB": 5})
        svc.calculate_article_price = Mock(return_value=recalculated)

        result = svc.change_article_family("A", 4, 2, None, "")

        sql, params = svc.db.execute.call_args.args
        self.assertIn("ART_TABPREC=?", sql)
        self.assertIn("ART_PVP=?", sql)
        self.assertEqual(params[2], 10)
        self.assertEqual(params[3], 5)
        self.assertEqual(result["tabla_aplicada"], 5)
        self.assertEqual(result["tabla_origen"], "inferida")
        self.assertEqual(result["diff"]["ART_TABPREC"], {"before": 0, "after": 5})

    def test_article_family_service_saves_ssubfam_as_additional_info(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.db = Mock()
        svc.settings = Mock(empresa=1, usuario="tester")
        svc._table_from_article_family = Mock(return_value=0)
        svc.get_article = Mock(side_effect=[
            {"ART_CODART": "A", "ART_DESCRI": "Articulo", "ART_CODFAM": 4, "ART_SUBFAM": 2},
            {"ART_CODART": "A", "ART_DESCRI": "Articulo", "ART_CODFAM": 4, "ART_SUBFAM": 2},
        ])
        svc._article_additional_info = Mock(side_effect=[
            {"ARTI_DESCRI": "7"},
            {"ARTI_DESCRI": "9"},
        ])
        svc._save_article_additional_info = Mock()
        svc._delete_article_additional_info = Mock()

        result = svc.change_article_family("A", 4, 2, 9)

        svc._save_article_additional_info.assert_called_once_with("A", "SSUBF", "9")
        svc._delete_article_additional_info.assert_not_called()
        self.assertEqual(result["diff"]["SSUBF"], {"before": "7", "after": "9"})

    def test_article_family_service_deletes_ssubfam_when_zero(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.db = Mock()
        svc.settings = Mock(empresa=1, usuario="tester")
        svc._table_from_article_family = Mock(return_value=0)
        svc.get_article = Mock(side_effect=[
            {"ART_CODART": "A", "ART_DESCRI": "Articulo", "ART_CODFAM": 4, "ART_SUBFAM": 2},
            {"ART_CODART": "A", "ART_DESCRI": "Articulo", "ART_CODFAM": 4, "ART_SUBFAM": 2},
        ])
        svc._article_additional_info = Mock(side_effect=[
            {"ARTI_DESCRI": "9"},
            None,
        ])
        svc._save_article_additional_info = Mock()
        svc._delete_article_additional_info = Mock()

        result = svc.change_article_family("A", 4, 2, 0)

        svc._delete_article_additional_info.assert_called_once_with("A", "SSUBF")
        svc._save_article_additional_info.assert_not_called()
        self.assertEqual(result["diff"]["SSUBF"], {"before": "9", "after": ""})

    def test_article_famncc_table_save_delegates_to_service(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        svc.change_article_famncc_table.return_value = {"updated": True}
        with patch.object(server, "service", return_value=svc):
            result = server.tool_articulo_familiancc_tabla_guardar({
                "codart": "A", "famncc": "0102", "new_table": 0,
            })
        self.assertTrue(result["updated"])
        svc.change_article_famncc_table.assert_called_once_with("A", "0102", 0)
        svc.db.close.assert_called_once()

    def test_article_famncc_table_service_applies_inferred_price_table(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.db = Mock()
        svc.settings = Mock(empresa=1, usuario="tester")
        current = {
            "ART_CODART": "A", "ART_DESCRI": "Articulo",
            "ART_PRECOS": 10, "ART_TABPREC": 0, "ART_PREVEN1": 11, "ART_PREVEN2": 12,
            "ART_PREVEN3": 13, "ART_PREVEN4": 14, "ART_PVP": 16,
        }
        after = {
            **current, "ART_TABPREC": 6, "ART_PREVEN1": 21, "ART_PREVEN2": 22,
            "ART_PREVEN3": 23, "ART_PREVEN4": 24, "ART_PVP": 29,
        }
        svc.get_article = Mock(side_effect=[current, after])
        svc._article_additional_info = Mock(side_effect=[
            {"ARTI_DESCRI": "0001"},
            {"ARTI_DESCRI": "0102"},
        ])
        svc._famncc_price_table = Mock(return_value=6)
        svc.get_price_table = Mock(return_value={"TPR_CODTAB": 6})
        svc.calculate_article_price = Mock(return_value=dict(after))
        svc._save_article_additional_info = Mock()
        svc._delete_article_additional_info = Mock()

        result = svc.change_article_famncc_table("A", "0102", "")

        svc._save_article_additional_info.assert_called_once_with("A", "FAMNC", "0102")
        sql, params = svc.db.execute.call_args.args
        self.assertIn("ART_TABPREC=?", sql)
        self.assertEqual(params[1], 6)
        self.assertEqual(result["tabla_aplicada"], 6)
        self.assertEqual(result["tabla_origen"], "inferida")
        self.assertEqual(result["diff"]["FAMNC"], {"before": "0001", "after": "0102"})

    def test_article_famncc_table_service_deletes_famncc_when_empty(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.db = Mock()
        svc.settings = Mock(empresa=1, usuario="tester")
        current = {
            "ART_CODART": "A", "ART_DESCRI": "Articulo",
            "ART_PRECOS": 10, "ART_TABPREC": 0, "ART_PREVEN1": 11, "ART_PREVEN2": 12,
            "ART_PREVEN3": 13, "ART_PREVEN4": 14, "ART_PVP": 16,
        }
        svc.get_article = Mock(side_effect=[current, current])
        svc._article_additional_info = Mock(side_effect=[
            {"ARTI_DESCRI": "0001"},
            None,
        ])
        svc._save_article_additional_info = Mock()
        svc._delete_article_additional_info = Mock()

        result = svc.change_article_famncc_table("A", "", None)

        svc._delete_article_additional_info.assert_called_once_with("A", "FAMNC")
        svc._save_article_additional_info.assert_not_called()
        self.assertEqual(result["diff"]["FAMNC"], {"before": "0001", "after": ""})

    def test_pedido_detalle_routes_mode(self):
        server = faro_mcp.FaroToolRuntime()
        svc = self._fake_phase_service()
        svc.order_lines.return_value = {"items": [1]}
        svc.order_preparation_lines.return_value = {"items": [2]}
        base = {"centro": 1, "ejerci": 2026, "serie": "A", "numdoc": 10}
        with patch.object(server, "phase1_service", return_value=svc):
            normal = server.tool_pedido_detalle(base)
            prep = server.tool_pedido_detalle({**base, "modo": "preparacion"})
        self.assertEqual(normal["modo"], "normal")
        self.assertEqual(prep["modo"], "preparacion")

    def test_cliente_buscar_uses_detail_only_for_exact_key(self):
        server = faro_mcp.FaroToolRuntime()
        svc = self._fake_phase_service()
        svc.search_client.return_value = {"found": True, "codcli": 1}
        svc.list_clients.return_value = {"count": 1, "items": [{"codcli": 1}]}
        with patch.object(server, "phase1_service", return_value=svc):
            detail = server.tool_cliente_buscar({"codcli": 1, "subcli": 0})
            listing = server.tool_cliente_buscar({"nombre_like": "ACME"})
        self.assertEqual(detail["modo"], "detalle")
        self.assertEqual(listing["modo"], "listado")
        svc.search_client.assert_called_once_with(1, 0)
        svc.list_clients.assert_called_once()

    def test_proveedor_buscar_uses_detail_only_for_exact_key(self):
        server = faro_mcp.FaroToolRuntime()
        svc = self._fake_phase_service()
        svc.search_provider.return_value = {"found": True, "codigo": 9}
        svc.list_providers.return_value = {"count": 1, "items": [{"codigo": 9}]}
        with patch.object(server, "phase1_service", return_value=svc):
            detail = server.tool_proveedor_buscar({"codpro": 9})
            listing = server.tool_proveedor_buscar({
                "nombre_comercial_like": "COINFER",
                "fecha_alta_desde": "2026-01-01",
                "fecha_alta_hasta": "2026-12-31",
                "limit": 25,
            })
        self.assertEqual(detail["modo"], "detalle")
        self.assertEqual(listing["modo"], "listado")
        svc.search_provider.assert_called_once_with(9)
        svc.list_providers.assert_called_once_with(
            None, "COINFER", "", "", "", "", "2026-01-01", "2026-12-31", 25
        )


if __name__ == "__main__":
    unittest.main()
