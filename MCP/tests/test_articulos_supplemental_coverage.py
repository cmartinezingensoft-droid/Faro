"""Cobertura complementaria para funciones de articulos sin pruebas previas.

Al revisar funcion por funcion el grupo de articulos/almacen (15 herramientas
publicas: articulo_buscar, articulo_obtener, articulo_catalogo_listar,
articulo_compra_consultar, articulo_precio_oferta, articulo_precio_cliente,
articulo_cambiar_tabla_precio, articulo_ean_grabar, articulo_ubicacion_guardar,
stock_consultar, stock_regularizar, stock_trasvasar, etiqueta_gestion,
recuento_gestion, falta_gestion) se detecto que dos no tenian ninguna prueba,
ni de fachada (tool_*) ni de logica de negocio (FaroPhase1Service):

- ``articulo_precio_oferta`` (delega en ``offer_pvp``)
- ``articulo_ean_grabar`` (delega en ``save_ean``)

Tampoco existia ninguna prueba de la capa de traduccion de argumentos
publicos->internos (``translate_public_arguments``, contrato v2) para estas
dos herramientas, pese a que si esta probada para otras (ver
``test_cleanup_phase12_contract_v2.py``).

Este fichero cierra ese hueco con pruebas unitarias (mocks, sin BD real),
seguidas del mismo estilo que ``test_cleanup_phase8_articles.py`` y
``test_cleanup_phase12_contract_v2.py``.
"""
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

import faro_mcp


class ArticleSearchWithStockTests(unittest.TestCase):
    def test_search_articles_filters_stock_and_purchase_date_by_current_center(self):
        class _Db:
            settings = type("S", (), {"empresa": 1, "centro": 7})()

            def __init__(self):
                self.sql = ""
                self.params = ()

            def fetch_all(self, sql, params=()):
                self.sql = sql
                self.params = params
                return [
                    {
                        "ART_NUMEMP": 1,
                        "ART_CODART": "TAL-1",
                        "ART_DESCRI": "Taladro percutor",
                        "ART_UNIMED": "UD",
                        "ART_PRECOS": Decimal("10.5"),
                        "ART_PREVEN1": Decimal("12"),
                        "ART_PREVEN2": Decimal("13"),
                        "ART_PREVEN3": Decimal("14"),
                        "ART_PREVEN4": Decimal("15"),
                        "ART_PVP": Decimal("18.15"),
                        "ART_CODFAM": 4,
                        "ART_SUBFAM": 2,
                        "ART_TIPIVA": 21,
                        "ART_TABPREC": 1,
                        "ART_CODPRO": 99,
                        "PRO_NOMCOR": "PROVEEDOR",
                        "ARTE_CENTRO": 7,
                        "ARTE_EXIST": Decimal("3"),
                        "ARTE_MINIMO": Decimal("1"),
                        "ARTE_MAXIMO": Decimal("9"),
                        "ARTE_FECCOM": date(2025, 12, 31),
                        "ARTE_FECVEN": None,
                        "ARTE_FECMOV": date(2026, 1, 2),
                    }
                ]

        db = _Db()
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.search_articles(
            texto="TALADROS",
            with_stock=True,
            purchase_before="2026-01-01",
            sale_before="2026-01-01",
            order_by="ARTE_EXIST",
        )

        sql = " ".join(db.sql.split())
        self.assertIn("SELECT FIRST", sql)
        self.assertIn("JOIN ARTICULE E ON", sql)
        self.assertIn("E.ARTE_CENTRO = ?", sql)
        self.assertIn("E.ARTE_EXIST > 0", sql)
        self.assertIn("E.ARTE_FECCOM < ?", sql)
        self.assertIn("E.ARTE_FECVEN < ?", sql)
        self.assertIn("ORDER BY E.ARTE_EXIST", sql)
        self.assertIn("OR E.ARTE_FECVEN IS NULL", sql)
        self.assertEqual(db.params, (7, 1, "%TALADROS%", "%TALADRO%", date(2026, 1, 1), date(2026, 1, 1)))
        self.assertEqual(result["items"][0]["existencias"], "3")
        self.assertEqual(result["items"][0]["familia"], 4)
        self.assertIn("ART_PREVEN1", result["items"][0]["articulo"])


class OfferCreateTests(unittest.TestCase):
    def test_create_offer_inserts_header_and_article_lines(self):
        class _Db:
            settings = type("S", (), {"empresa": 1, "centro": 0, "usuario": "tester"})()

            def __init__(self):
                self.executed = []
                self.committed = False
                self.rolled_back = False

            def fetch_one(self, sql, params=()):
                if "MAX(OFE_NUMOFE)" in sql:
                    return {"NUMOFE": 40}
                if "FROM ARTICUL" in sql:
                    return {
                        "ART_CODART": params[1],
                        "ART_PREBAS": Decimal("12.3400"),
                        "ART_CODMON": "E",
                        "ART_CANPRE": Decimal("1"),
                    }
                return None

            def execute(self, sql, params=()):
                self.executed.append((" ".join(sql.split()), params))

            def commit(self):
                self.committed = True

            def rollback(self):
                self.rolled_back = True

        db = _Db()
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.create_offer(
            tipo_oferta="T",
            nombre="Oferta test",
            fecha_inicio="2027-03-01",
            fecha_fin="2027-03-31",
            articulos=[{"articulo": "A1", "precio_oferta": "9.99", "descuentos": [10, 5]}],
            proveedor=0,
        )

        self.assertEqual(result["ejercicio"], 2027)
        self.assertEqual(result["numero"], 41)
        self.assertEqual(result["lineas"], 1)
        self.assertTrue(db.committed)
        self.assertFalse(db.rolled_back)
        self.assertIn("INSERT INTO OFERTAS", db.executed[0][0])
        self.assertIn("INSERT INTO DETOFER", db.executed[1][0])
        self.assertEqual(db.executed[0][1][1:5], (2027, 41, 0, "Oferta test"))
        self.assertEqual(db.executed[1][1][1:4], (2027, 41, "A1"))
        self.assertEqual(db.executed[1][1][7], Decimal("12.3400"))
        self.assertEqual(db.executed[1][1][9], Decimal("9.99"))
        self.assertEqual(db.executed[1][1][12], Decimal("10"))
        self.assertEqual(db.executed[1][1][13], Decimal("5"))


class ArticuloPrecioOfertaTests(unittest.TestCase):
    def _server_and_service(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        svc.settings = Mock(empresa=1)
        return server, svc

    def test_facade_delegates_to_offer_pvp_with_codart(self):
        server, svc = self._server_and_service()
        svc.offer_pvp.return_value = {"codart": "A1", "pvp": "9.95", "offer": {"DOF_NUMOFE": 3}}
        with patch.object(server, "phase1_service", return_value=svc):
            result = server.tool_articulo_precio_oferta({"codart": "A1"})
        self.assertEqual(result["pvp"], "9.95")
        svc.offer_pvp.assert_called_once_with("A1")
        svc.db.close.assert_called_once()

    def test_facade_closes_connection_even_if_offer_pvp_raises(self):
        server, svc = self._server_and_service()
        svc.offer_pvp.side_effect = faro_mcp.FaroError("boom")
        with patch.object(server, "phase1_service", return_value=svc):
            with self.assertRaises(faro_mcp.FaroError):
                server.tool_articulo_precio_oferta({"codart": "A1"})
        svc.db.close.assert_called_once()

    def test_offer_pvp_returns_zero_when_no_active_offer(self):
        svc = faro_mcp.FaroPhase1Service.__new__(faro_mcp.FaroPhase1Service)
        svc.db = Mock()
        svc.settings = Mock(empresa=1)
        svc.db.fetch_all.return_value = []
        result = svc.offer_pvp("A1")
        self.assertEqual(result, {"codart": "A1", "pvp": "0", "offer": None})

    def test_offer_pvp_applies_dto1_and_dto2_discounts(self):
        svc = faro_mcp.FaroPhase1Service.__new__(faro_mcp.FaroPhase1Service)
        svc.db = Mock()
        svc.settings = Mock(empresa=1)
        svc.db.fetch_all.return_value = [
            {
                "DOF_PVP": Decimal("10"),
                "DOF_DTO1": Decimal("10"),
                "DOF_DTO2": Decimal("0"),
                "DOF_EJERCI": 2026,
                "DOF_NUMOFE": 5,
            }
        ]
        svc.db.fetch_one.return_value = {"OFE_TIPOFE": "N"}
        result = svc.offer_pvp("A1")
        self.assertEqual(Decimal(str(result["pvp"])), Decimal("9.00"))

    def test_offer_pvp_ignores_offer_marked_sin_precios(self):
        svc = faro_mcp.FaroPhase1Service.__new__(faro_mcp.FaroPhase1Service)
        svc.db = Mock()
        svc.settings = Mock(empresa=1)
        svc.db.fetch_all.return_value = [
            {
                "DOF_PVP": Decimal("10"),
                "DOF_DTO1": Decimal("0"),
                "DOF_DTO2": Decimal("0"),
                "DOF_EJERCI": 2026,
                "DOF_NUMOFE": 5,
            }
        ]
        svc.db.fetch_one.return_value = {"OFE_TIPOFE": "S"}
        result = svc.offer_pvp("A1")
        self.assertEqual(result["pvp"], "0")
        self.assertEqual(result["ignored_reason"], "Oferta sin precios")


class ArticuloPrecioCosteTests(unittest.TestCase):
    def _server_and_service(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        svc.settings = Mock(empresa=1)
        return server, svc

    def test_facade_delegates_to_article_cost_price_with_date_and_currency(self):
        server, svc = self._server_and_service()
        svc.article_cost_price.return_value = {
            "codart": "A1",
            "fecha": "2026-09-21",
            "moneda": "E",
            "precio_coste": "12.5",
        }
        with patch.object(server, "service", return_value=svc):
            result = server.tool_articulo_precio_coste(
                {"codart": "A1", "fecha": "2026-09-21", "moneda": "E"}
            )
        self.assertEqual(result["precio_coste"], "12.5")
        svc.article_cost_price.assert_called_once_with("A1", date(2026, 9, 21), "E")
        svc.db.close.assert_called_once()

    def test_facade_uses_euro_when_currency_is_omitted(self):
        server, svc = self._server_and_service()
        svc.article_cost_price.return_value = {
            "codart": "A1",
            "fecha": "2026-09-21",
            "moneda": "E",
            "precio_coste": "12.5",
        }
        with patch.object(server, "service", return_value=svc):
            server.tool_articulo_precio_coste({"codart": "A1", "fecha": "2026-09-21"})
        svc.article_cost_price.assert_called_once_with("A1", date(2026, 9, 21), "E")

    def test_article_cost_price_uses_base_price_when_rentab_is_pbase(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.settings = Mock(empresa=1)
        svc.article_no_contable_flag = Mock(return_value="")
        svc.parameter = Mock(return_value="PBASE")
        svc.article_file_cost = Mock()
        svc.article_base_price = Mock(return_value=Decimal("7.25"))
        svc.average_cost = Mock()
        svc.last_purchase_cost = Mock()

        result = svc.article_cost_price("A1", date(2026, 9, 21), "E")

        self.assertEqual(result["fuente"], "precio_base")
        self.assertEqual(result["precio_coste"], "7.25")
        svc.article_base_price.assert_called_once_with("A1", "E")
        svc.article_file_cost.assert_not_called()
        svc.average_cost.assert_not_called()
        svc.last_purchase_cost.assert_not_called()

    def test_article_cost_price_uses_file_cost_when_rentab_is_pcoste(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.settings = Mock(empresa=1)
        svc.article_no_contable_flag = Mock(return_value="")
        svc.parameter = Mock(return_value="PCOSTE")
        svc.article_file_cost = Mock(return_value=Decimal("6.80"))
        svc.article_base_price = Mock()
        svc.average_cost = Mock()
        svc.last_purchase_cost = Mock()

        result = svc.article_cost_price("A1", date(2026, 9, 21), "E")

        self.assertEqual(result["fuente"], "precio_coste_ficha")
        self.assertEqual(result["precio_coste"], "6.80")
        svc.article_file_cost.assert_called_once_with("A1", "E")
        svc.article_base_price.assert_not_called()
        svc.average_cost.assert_not_called()
        svc.last_purchase_cost.assert_not_called()

    def test_article_cost_price_uses_average_cost_when_rentab_is_pmedio(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.settings = Mock(empresa=1)
        svc.article_no_contable_flag = Mock(return_value="")
        svc.parameter = Mock(return_value="PMEDIO")
        svc.article_file_cost = Mock()
        svc.article_base_price = Mock()
        svc.average_cost = Mock(return_value=Decimal("8.50"))
        svc.last_purchase_cost = Mock()

        result = svc.article_cost_price("A1", date(2026, 9, 21), "E")

        self.assertEqual(result["fuente"], "coste_medio")
        self.assertEqual(result["precio_coste"], "8.50")
        svc.average_cost.assert_called_once_with("A1", date(2026, 9, 21), "E")
        svc.last_purchase_cost.assert_not_called()

    def test_article_cost_price_uses_last_cost_for_unknown_rentab_mode(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.settings = Mock(empresa=1)
        svc.article_no_contable_flag = Mock(return_value="")
        svc.parameter = Mock(return_value="PULTIM")
        svc.article_file_cost = Mock()
        svc.article_base_price = Mock()
        svc.average_cost = Mock()
        svc.last_purchase_cost = Mock(return_value=Decimal("9.75"))

        result = svc.article_cost_price("A1", date(2026, 9, 21), "E")

        self.assertEqual(result["fuente"], "coste_ultimo")
        self.assertEqual(result["precio_coste"], "9.75")
        svc.last_purchase_cost.assert_called_once_with("A1", date(2026, 9, 21), "E")

    def test_article_cost_price_forces_zero_when_article_is_no_contable_n(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.settings = Mock(empresa=1)
        svc.article_no_contable_flag = Mock(return_value="N")
        svc.parameter = Mock(return_value="PMEDIO")
        svc.average_cost = Mock()

        result = svc.article_cost_price("A1", date(2026, 9, 21), "E")

        self.assertTrue(result["forzado_a_cero"])
        self.assertEqual(result["fuente"], "no_contable")
        self.assertEqual(result["precio_coste"], "0")
        svc.average_cost.assert_not_called()

    def test_last_purchase_cost_falls_back_to_file_cost_when_no_movement(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.settings = Mock(empresa=1)
        svc.db = Mock()
        svc.db.fetch_one.side_effect = [None]
        svc.article_file_cost = Mock(return_value=Decimal("6.40"))
        svc.parameter = Mock(return_value="")

        result = svc.last_purchase_cost("A1", date(2026, 9, 21), "E")

        self.assertEqual(result, Decimal("6.40"))
        svc.article_file_cost.assert_called_once_with("A1", "E")

    def test_average_cost_falls_back_to_last_purchase_cost_when_no_average(self):
        svc = faro_mcp.FaroArticleService.__new__(faro_mcp.FaroArticleService)
        svc.settings = Mock(empresa=1)
        svc.db = Mock()
        svc.db.fetch_one.return_value = None
        svc.last_purchase_cost = Mock(return_value=Decimal("11.00"))

        result = svc.average_cost("A1", date(2026, 9, 21), "E")

        self.assertEqual(result, Decimal("11.00"))
        svc.last_purchase_cost.assert_called_once_with("A1", date(2026, 9, 21), "E")


class ArticuloEanGrabarTests(unittest.TestCase):
    def _server_and_service(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        svc.settings = Mock(empresa=1)
        return server, svc

    def test_facade_delegates_to_save_ean_with_codart_and_ean(self):
        server, svc = self._server_and_service()
        svc.save_ean.return_value = {"codart": "A1", "ean": "8412345678901", "updated": True}
        with patch.object(server, "phase1_service", return_value=svc):
            result = server.tool_articulo_ean_grabar({"codart": "A1", "ean": "8412345678901"})
        self.assertTrue(result["updated"])
        svc.save_ean.assert_called_once_with("A1", "8412345678901")
        svc.db.close.assert_called_once()

    def test_save_ean_rejects_non_numeric_ean_without_touching_db(self):
        svc = faro_mcp.FaroPhase1Service.__new__(faro_mcp.FaroPhase1Service)
        svc.db = Mock()
        svc.settings = Mock(empresa=1)
        with self.assertRaises(faro_mcp.FaroError):
            svc.save_ean("A1", "NO-ES-UN-EAN")
        svc.db.execute.assert_not_called()
        svc.db.commit.assert_not_called()

    def test_save_ean_inserts_and_commits_on_success(self):
        svc = faro_mcp.FaroPhase1Service.__new__(faro_mcp.FaroPhase1Service)
        svc.db = Mock()
        svc.settings = Mock(empresa=1)
        result = svc.save_ean("A1", "8412345678901")
        svc.db.execute.assert_called_once_with(
            "INSERT INTO ARTICULC (ARTC_NUMEMP, ARTC_CODART, ARTC_CODIGO, ARTC_CANTID) VALUES (?, ?, ?, ?)",
            (1, "A1", "8412345678901", 1),
        )
        svc.db.commit.assert_called_once()
        svc.db.rollback.assert_not_called()
        self.assertEqual(result, {"codart": "A1", "ean": "8412345678901", "updated": True})

    def test_save_ean_rolls_back_on_insert_failure(self):
        svc = faro_mcp.FaroPhase1Service.__new__(faro_mcp.FaroPhase1Service)
        svc.db = Mock()
        svc.settings = Mock(empresa=1)
        svc.db.execute.side_effect = RuntimeError("duplicate key")
        with self.assertRaises(RuntimeError):
            svc.save_ean("A1", "8412345678901")
        svc.db.rollback.assert_called_once()
        svc.db.commit.assert_not_called()


class RegularizeStockDb:
    """Fake DB para probar la logica real de regularize_stock (stock_regularizar).

    Esta funcion es de riesgo ``critical`` (ver test_cleanup_phase13_security_audit.py)
    y, pese a eso, no tenia ninguna prueba de logica de negocio -solo el
    routing de fachada con mocks en test_cleanup_phase2_consolidation.py-. Este
    fake reproduce las tablas relevantes (ARTICUL, ARTICULE, CABDOCR, DETMOVR,
    PARAMETROS) al estilo de OrchestrationDb en test_phase2f_logistics.py.
    """

    def __init__(self, indinv="S", current_exist=Decimal("5"), param_serie="R", settings_centro=1):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=settings_centro, usuario="test",
        )
        self.indinv = indinv
        self.current_exist = current_exist
        self.param_serie = param_serie
        self.queried_parameter_codes: list[str] = []
        self.executed: list[tuple[str, tuple]] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_on: set[str] = set()

    def fetch_one(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM ARTICUL WHERE" in u:
            return {"ART_CODART": params[1], "ART_DESCRI": "Articulo", "ART_UNIMED": "UD", "ART_INDINV": self.indinv}
        if "FROM ARTICULE WHERE" in u:
            return {"ARTE_EXIST": self.current_exist}
        if "FROM CABDOCR" in u and "MAX(CBR_NUMDOC)" in u:
            return None
        if "FROM CABDOCR" in u and "CBR_FECHA=?" in u:
            return None
        if "FROM PARAMETROS" in u:
            self.queried_parameter_codes.append(params[1])
            return {"PAR_VALOR": self.param_serie} if self.param_serie else None
        if "FROM DETMOVR" in u:
            return None
        return None

    def execute(self, sql, params=()):
        key = " ".join(sql.split())
        for marker in self.fail_on:
            if marker in key:
                raise RuntimeError(f"fallo simulado: {marker}")
        self.executed.append((key, params))
        if key.startswith("INSERT INTO ARTICULE"):
            # Simula violacion de PK: ya existe fila ARTICULE para ese articulo/centro
            # (current_exist ya la reflejaba), forzando la rama UPDATE de accumulate_stock.
            raise RuntimeError("duplicate key ARTICULE")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class StockRegularizarTests(unittest.TestCase):
    def test_no_change_returns_early_without_any_write(self):
        db = RegularizeStockDb(current_exist=Decimal("5"))
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.regularize_stock("A1", 1, "Articulo", "UD", "5")
        self.assertFalse(result["updated"])
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.executed, [])

    def test_accumulates_when_article_controls_inventory(self):
        db = RegularizeStockDb(indinv="S", current_exist=Decimal("5"))
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.regularize_stock("A1", 1, "Articulo", "UD", "8")
        self.assertTrue(result["updated"])
        self.assertTrue(result["stock_accumulated"])
        self.assertEqual(result["difference"], "3")
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        statements = [k for k, _ in db.executed]
        self.assertTrue(any(s.startswith("UPDATE ARTICULE") for s in statements))
        self.assertTrue(any(s.startswith("INSERT INTO DETMOVR") for s in statements))

    def test_missing_description_and_unit_are_loaded_from_article(self):
        db = RegularizeStockDb(indinv="S", current_exist=Decimal("5"))
        svc = faro_mcp.FaroPhase1Service(db)
        svc.regularize_stock("A1", 1, "", "", "8")

        detmovr = next(params for sql, params in db.executed if sql.startswith("INSERT INTO DETMOVR"))
        self.assertEqual(detmovr[8], "Articulo")
        self.assertEqual(detmovr[9], "UD")

    def test_skips_accumulation_when_article_does_not_control_inventory(self):
        db = RegularizeStockDb(indinv="N", current_exist=Decimal("5"))
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.regularize_stock("A1", 1, "Articulo", "UD", "8")
        self.assertTrue(result["updated"])
        self.assertFalse(result["stock_accumulated"])
        statements = [k for k, _ in db.executed]
        self.assertFalse(any(s.startswith("UPDATE ARTICULE") for s in statements))
        self.assertTrue(any(s.startswith("INSERT INTO DETMOVR") for s in statements))

    def test_raises_for_unknown_article_without_touching_cabdocr(self):
        db = RegularizeStockDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc.db.fetch_one = lambda sql, params=(): None if "FROM ARTICUL WHERE" in sql.upper() else db.__class__.fetch_one(db, sql, params)
        with self.assertRaises(faro_mcp.FaroError):
            svc.regularize_stock("NOEXISTE", 1, "Articulo", "UD", "8")
        self.assertEqual(db.executed, [])
        self.assertEqual(db.commits, 0)

    def test_rolls_back_when_detmovr_insert_fails(self):
        db = RegularizeStockDb(indinv="S", current_exist=Decimal("5"))
        db.fail_on.add("INSERT INTO DETMOVR")
        svc = faro_mcp.FaroPhase1Service(db)
        with self.assertRaises(RuntimeError):
            svc.regularize_stock("A1", 1, "Articulo", "UD", "8")
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)

    def test_missing_serie_parameter_raises_before_any_write(self):
        db = RegularizeStockDb(param_serie="")
        svc = faro_mcp.FaroPhase1Service(db)
        with self.assertRaises(faro_mcp.FaroError):
            svc.regularize_stock("A1", 1, "Articulo", "UD", "8")
        self.assertEqual(db.executed, [])

    def test_known_quirk_serie_lookup_uses_target_centro_not_session_centro(self):
        # Documentado como pendiente en el proyecto (revision-consulta-etiquetas-stock.md,
        # recomendacion #2) desde la Fase 1: SERIE_DOCUMENTO en el Delphi original resuelve
        # la serie con el centro de la SESION conectada (R_PARAMETROS.CENTRO), no con el
        # centro que se esta regularizando. Python replica esa misma discrepancia: aqui la
        # sesion esta en centro=9 pero se regulariza el centro=1, y la busqueda de parametro
        # se hace por "R1" (el centro objetivo), no por "R9" (el centro de sesion). No se
        # corrige en esta prueba a proposito: solo se fija el comportamiento actual para que
        # cualquier cambio futuro (arreglarlo) sea una decision explicita, no un efecto
        # colateral no detectado.
        db = RegularizeStockDb(indinv="S", current_exist=Decimal("5"), settings_centro=9)
        svc = faro_mcp.FaroPhase1Service(db)
        svc.regularize_stock("A1", 1, "Articulo", "UD", "8")
        self.assertIn("R1", db.queried_parameter_codes)
        self.assertNotIn("R9", db.queried_parameter_codes)


class RecuentoArticleDb:
    """Fake DB para probar que save_recount (recuento_gestion) autocompleta
    descripcion/unidad_medida desde ARTICUL cuando se dejan vacias, igual que
    ya hace regularize_stock (ver RegularizeStockDb mas arriba)."""

    def __init__(self, existing_recount=None, article=None):
        self.settings = faro_mcp.Settings("odbc", "", "faro", "u", "p", 1, 1, "test")
        self.recuento_row = existing_recount
        self.article = article if article is not None else {"ART_DESCRI": "Cafetera induccion", "ART_UNIMED": "UNI"}
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def fetch_one(self, sql, params=()):
        u = sql.upper()
        if "FROM ARTICUL" in u:
            return self.article
        if "FROM RECUENTO" in u:
            return dict(self.recuento_row) if self.recuento_row else None
        return None

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), params))
        upper = sql.strip().upper()
        if upper.startswith("INSERT INTO RECUENTO"):
            self.recuento_row = {
                "REC_CODART": params[2], "REC_DESCRI": params[3],
                "REC_EXIST": params[4], "REC_FECHA": params[5], "REC_UNIMED": params[6],
            }
        elif upper.startswith("DELETE FROM RECUENTO"):
            self.recuento_row = None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


_DEFAULT_LABEL_ARTICLE = object()


class LabelsArticleDb:
    def __init__(self, article=_DEFAULT_LABEL_ARTICLE):
        self.settings = faro_mcp.Settings("odbc", "", "faro", "u", "p", 1, 1, "test")
        self.label_row = None
        self.article = {"ART_DESCRI": "Cafetera induccion"} if article is _DEFAULT_LABEL_ARTICLE else article
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def fetch_one(self, sql, params=()):
        u = sql.upper()
        if "FROM ARTICUL" in u:
            return self.article
        if "FROM ETIQUE" in u:
            return dict(self.label_row) if self.label_row else None
        return None

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), params))
        upper = sql.strip().upper()
        if upper.startswith("INSERT INTO ETIQUE"):
            self.label_row = {
                "ETI_CODART": params[1], "ETI_DESCRI": params[2], "ETI_CANTID": params[3],
                "ETI_IMPRIM": params[4], "ETI_MODELO": params[5], "ETI_DESCRI2": params[6],
            }
        elif upper.startswith("DELETE FROM ETIQUE"):
            self.label_row = None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class SaveLabelsTests(unittest.TestCase):
    def test_missing_description_is_loaded_from_article(self):
        db = LabelsArticleDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc.save_labels("A1", "", "3", False, 0, False)
        insert = next(params for sql, params in db.executed if sql.startswith("INSERT INTO ETIQUE"))
        self.assertEqual(insert[2], "Cafetera induccion")

    def test_keeps_explicit_description(self):
        db = LabelsArticleDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc.save_labels("A1", "Manual", "3", False, 0, False)
        insert = next(params for sql, params in db.executed if sql.startswith("INSERT INTO ETIQUE"))
        self.assertEqual(insert[2], "Manual")

    def test_raises_for_unknown_article_when_description_is_empty(self):
        db = LabelsArticleDb(article=None)
        svc = faro_mcp.FaroPhase1Service(db)
        with self.assertRaises(faro_mcp.FaroError):
            svc.save_labels("NOEXISTE", "", "3", False, 0, False)
        self.assertEqual(db.executed, [])


class SaveRecountTests(unittest.TestCase):
    def test_missing_description_and_unit_are_loaded_from_article(self):
        db = RecuentoArticleDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc.save_recount("A1", 1, "", "", "5", False)
        insert = next(params for sql, params in db.executed if sql.startswith("INSERT INTO RECUENTO"))
        self.assertEqual(insert[3], "Cafetera induccion")
        self.assertEqual(insert[6], "UNI")

    def test_keeps_explicit_description_and_unit(self):
        db = RecuentoArticleDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc.save_recount("A1", 1, "Manual", "CJ", "5", False)
        insert = next(params for sql, params in db.executed if sql.startswith("INSERT INTO RECUENTO"))
        self.assertEqual(insert[3], "Manual")
        self.assertEqual(insert[6], "CJ")

    def test_raises_for_unknown_article_without_touching_recuento(self):
        db = RecuentoArticleDb()
        db.article = None
        svc = faro_mcp.FaroPhase1Service(db)
        with self.assertRaises(faro_mcp.FaroError):
            svc.save_recount("NOEXISTE", 1, "", "", "5", False)
        self.assertEqual(db.executed, [])


class PublicContractTranslationTests(unittest.TestCase):
    """Cierra el borde publico->interno (contrato v2) para las dos huecas."""

    def test_articulo_precio_oferta_translates_articulo_to_codart(self):
        translated = faro_mcp.translate_public_arguments("articulo_precio_oferta", {"articulo": "A1"})
        self.assertEqual(translated, {"codart": "A1"})

    def test_articulo_precio_oferta_rejects_internal_or_unknown_names(self):
        with self.assertRaises(faro_mcp.FaroError):
            faro_mcp.translate_public_arguments("articulo_precio_oferta", {"codart": "A1"})

    def test_articulo_ean_grabar_translates_articulo_and_keeps_ean(self):
        translated = faro_mcp.translate_public_arguments(
            "articulo_ean_grabar", {"articulo": "A1", "ean": "8412345678901"}
        )
        self.assertEqual(translated, {"codart": "A1", "ean": "8412345678901"})

    def test_articulo_ean_grabar_requires_both_fields(self):
        with self.assertRaises(faro_mcp.FaroError):
            faro_mcp.translate_public_arguments("articulo_ean_grabar", {"articulo": "A1"})


if __name__ == "__main__":
    unittest.main()
