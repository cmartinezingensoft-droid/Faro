import os
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

import faro_mcp


ARTICLE = {
    "ART_NUMEMP": 1,
    "ART_CODART": "A1",
    "ART_DESCRI": "Articulo uno",
    "ART_UNIMED": "UD",
    "ART_CODMON": "E",
    "ART_PREBAS": Decimal("7.00"),
    "ART_PRECOS": Decimal("7.00"),
    "ART_CANPRE": Decimal("1"),
    "ART_DTOAUM1": Decimal("0"),
    "ART_DTOAUM2": Decimal("0"),
    "ART_DTOAUM3": Decimal("0"),
    "ART_DTOAUM4": Decimal("0"),
    "ART_DTOAUM5": Decimal("0"),
    "ART_DTOAUM6": Decimal("0"),
    "ART_DTOAUM7": Decimal("0"),
    "ART_IMPFIJ": Decimal("0"),
    "ART_TIPPRE": "V",
    "ART_TABPREC": 1,
    "ART_TIPIVA": 1,
    "ART_PREVEN1": Decimal("10"),
    "ART_PREVEN2": Decimal("10"),
    "ART_PREVEN3": Decimal("10"),
    "ART_PREVEN4": Decimal("10"),
    "ART_PVP": Decimal("12.10"),
    "ART_CODPRO": 9,
}

ARTP = {
    "ARTP_NUMEMP": 1,
    "ARTP_CODART": "A1",
    "ARTP_CODPRO": 9,
    "ARTP_REFPRO": "OLDREF",
    "ARTP_DESCRI": "Descripcion vieja",
    "ARTP_UNIMED": "UD",
    "ARTP_CANCON": Decimal("1"),
    "ARTP_CANVEN": Decimal("1"),
    "ARTP_UNIPAQ": Decimal("1"),
    "ARTP_PREBAS": Decimal("10.00"),
    "ARTP_DTOAUM1": Decimal("5"),
    "ARTP_DTOAUM2": Decimal("2"),
    "ARTP_DTOAUM3": Decimal("0"),
    "ARTP_DTOAUM4": Decimal("0"),
    "ARTP_DTOAUM5": Decimal("0"),
    "ARTP_DTOAUM6": Decimal("0"),
    "ARTP_CODMON": "E",
    "ARTP_CANPRE": Decimal("1"),
    "ARTP_UBICA": "",
    "ARTP_AMPUNIV": "",
    "ARTP_AJUSTE": "",
}


class FakeTariffDb:
    settings = type("S", (), {"empresa": 1, "centro": 0, "usuario": "tester"})()

    def __init__(self, current=None, existing_codes=()):
        self.current = dict(current) if current else None
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self.article = dict(ARTICLE)
        # Codigos adicionales (aparte de "A1") que EXISTE_ARTICUL debe ver
        # como ya ocupados; usado para forzar colisiones en la generacion
        # automatica de ART_CODART.
        self.existing_codes = set(existing_codes)

    def fetch_one(self, sql, params=()):
        flat = " ".join(sql.split())
        if "FROM PROVEE" in flat:
            return {"PRO_CODPRO": 9, "PRO_NOMCOR": "Proveedor 9"} if int(params[-1]) == 9 else None
        if "FROM PARAMETROS" in flat:
            return None
        if "FROM ARTICULC" in flat:
            return {"ARTC_CODART": "A1"} if params[-1] == "8410000000001" else None
        if "SELECT FIRST 1 ARTP_CODART FROM ARTICULP" in flat:
            if params[-1] in {"OLDREF", "R9"}:
                return {"ARTP_CODART": "A1"}
            return None
        if "SELECT * FROM ARTICUL WHERE" in flat:
            if params[-1] == "A1":
                return dict(self.article)
            if params[-1] in self.existing_codes:
                return {"ART_CODART": params[-1]}
            return None
        if "SELECT FIRST 1 * FROM ARTICULP" in flat:
            return dict(self.current) if self.current else None
        if "FROM TABPREC" in flat:
            return {
                "TPR_NUMEMP": 1, "TPR_CODTAB": 1,
                "TPR_PORAUM1": Decimal("0"), "TPR_PORAUM2": Decimal("0"),
                "TPR_PORAUM3": Decimal("0"), "TPR_PORAUM4": Decimal("0"),
                "TPR_AJUSTEE": Decimal("0"), "TPR_AJUSTEP": Decimal("0"),
            } if params[-1] == 1 else None
        if "FROM TIPIVA" in flat:
            return {"TIV_NUMEMP": 1, "TIV_TIPIVA": 1, "TIV_PORIVA": Decimal("21")} if params[-1] == 1 else None
        return None

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), params))

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class SupplierTariffContractTests(unittest.TestCase):
    def test_tool_is_public_core_and_critical(self):
        self.assertIn("tarifa_proveedor_actualizar", faro_mcp.CORE_PUBLIC_TOOL_NAMES)
        self.assertIn("tarifa_proveedor_actualizar", faro_mcp.CRITICAL_TOOL_NAMES)
        definition = next(x for x in faro_mcp.tool_definitions("core") if x["name"] == "tarifa_proveedor_actualizar")
        self.assertEqual(definition["inputSchema"]["required"], ["proveedor", "lineas"])
        line = definition["inputSchema"]["properties"]["lineas"]
        self.assertEqual(line["minItems"], 1)
        self.assertEqual(line["maxItems"], 500)
        self.assertEqual(line["items"]["required"], ["precio_base"])

    def test_contract_rejects_unknown_line_fields_and_more_than_six_discounts(self):
        with self.assertRaises(faro_mcp.FaroError):
            faro_mcp.translate_public_arguments(
                "tarifa_proveedor_actualizar",
                {"proveedor": 9, "lineas": [{"articulo": "A1", "precio_base": 10, "campo_raro": 1}]},
            )
        with self.assertRaises(faro_mcp.FaroError):
            faro_mcp.translate_public_arguments(
                "tarifa_proveedor_actualizar",
                {"proveedor": 9, "lineas": [{"articulo": "A1", "precio_base": 10, "descuentos": [1,2,3,4,5,6,7]}]},
            )

    def test_access_level_requires_critical(self):
        with patch.dict(os.environ, {"FARO_MCP_ACCESS_LEVEL": "write"}):
            server = faro_mcp.FaroToolRuntime()
            result, is_error = server.invoke_tool(
                "tarifa_proveedor_actualizar", {"proveedor": 9, "lineas": [{"articulo": "A1", "precio_base": 10}]}
            )
        self.assertTrue(is_error)
        self.assertEqual(result["error"]["code"], "FORBIDDEN")


class SupplierTariffServiceTests(unittest.TestCase):
    def test_updates_existing_supplier_row_and_preserves_uninformed_fields(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        result = svc.update_supplier_tariff(
            9,
            [{
                "articulo": "A1",
                "referencia_proveedor": "NEWREF",
                "precio_base": "12.50",
                "descuento1": "10",
                "unidades_paquete": 6,
            }],
        )
        self.assertEqual(result["modificaciones"], 1)
        self.assertEqual(result["altas"], 0)
        self.assertTrue(db.committed)
        self.assertFalse(db.rolled_back)
        sql, params = db.executed[0]
        self.assertTrue(sql.startswith("UPDATE ARTICULP SET"))
        self.assertIn("ARTP_REFPRO=?", sql)
        self.assertEqual(params[0], "NEWREF")
        self.assertEqual(params[6], Decimal("12.50"))
        self.assertEqual(params[7], Decimal("10"))
        self.assertEqual(params[8], Decimal("2"))  # descuento2 preservado
        self.assertEqual(params[14], Decimal("10.00"))  # ARTP_CANPRE = precio anterior
        self.assertEqual(params[-1], "OLDREF")  # WHERE usa la referencia antigua
        self.assertEqual(result["resultados"][0]["coste_neto"], "11.03")

    def test_inserts_supplier_row_with_delphi_defaults(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        result = svc.update_supplier_tariff(9, [{"articulo": "A1", "precio_base": 20, "descuentos": [10, 5]}])
        self.assertEqual(result["altas"], 1)
        sql, params = db.executed[0]
        self.assertTrue(sql.startswith("INSERT INTO ARTICULP"))
        self.assertEqual(params[0:6], (1, "A1", 9, "A1", "Articulo uno", "UD"))
        self.assertEqual(params[6:10], (Decimal("1"), Decimal("1"), Decimal("1"), Decimal("20")))
        self.assertEqual(params[10:12], (Decimal("10"), Decimal("5")))
        self.assertEqual(params[16], "E")
        self.assertEqual(params[17], Decimal("1"))

    def test_can_resolve_article_by_barcode_or_supplier_reference(self):
        for line, expected in [
            ({"codigo_barras": "8410000000001", "precio_base": 10}, "codigo_barras"),
            ({"referencia_proveedor": "R9", "precio_base": 10}, "referencia_proveedor"),
        ]:
            with self.subTest(line=line):
                db = FakeTariffDb(ARTP)
                svc = faro_mcp.FaroArticleService(db)
                result = svc.update_supplier_tariff(9, [line])
                self.assertEqual(result["resultados"][0]["articulo"], "A1")
                self.assertEqual(result["resultados"][0]["resuelto_por"], expected)

    def test_sale_price_update_uses_supplier_net_cost_and_updates_articul(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        recalculated = dict(ARTICLE)
        recalculated.update({
            "ART_PREBAS": Decimal("9.00"), "ART_PRECOS": Decimal("9.00"), "ART_CANPRE": Decimal("1"),
            "ART_PREVEN1": Decimal("11"), "ART_PREVEN2": Decimal("11"), "ART_PREVEN3": Decimal("11"),
            "ART_PREVEN4": Decimal("11"), "ART_PVP": Decimal("13.31"),
        })
        with patch.object(svc, "calculate_article_price", return_value=recalculated) as calc:
            result = svc.update_supplier_tariff(
                9, [{"articulo": "A1", "precio_base": 10, "descuentos": [10]}], True
            )
        self.assertEqual(result["precios_venta_actualizados"], 1)
        self.assertEqual(calc.call_args.args[0]["ART_PREBAS"], Decimal("8.82"))
        self.assertTrue(any(sql.startswith("UPDATE ARTICUL SET") for sql, _ in db.executed))
        self.assertEqual(result["resultados"][0]["precio_venta"]["pvp_modificado"], True)

    def test_invalid_line_rolls_back_entire_batch(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        with self.assertRaises(faro_mcp.FaroError):
            svc.update_supplier_tariff(9, [{"articulo": "NO-EXISTE", "precio_base": 10}])
        self.assertFalse(db.committed)
        self.assertTrue(db.rolled_back)


class SupplierTariffFacadeTests(unittest.TestCase):
    def test_facade_delegates_and_closes_connection(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        svc.update_supplier_tariff.return_value = {"altas": 1}
        with patch.object(server, "service", return_value=svc):
            result = server.tool_tarifa_proveedor_actualizar({
                "proveedor": 9,
                "lineas": [{"articulo": "A1", "precio_base": 10}],
                "actualizar_precio_venta": True,
            })
        self.assertEqual(result, {"altas": 1})
        svc.update_supplier_tariff.assert_called_once_with(
            9, [{"articulo": "A1", "precio_base": 10}], True,
            solo_si_sube_precio=False,
            solo_proveedor_principal=False,
            solo_si_propio=False,
            generar_etiquetas=False,
            etiqueta_modelo=0,
            dar_de_alta=False,
            usar_referencia_proveedor_como_codigo=False,
            digitos_codigo_articulo=9,
            numerador_inicial=0,
        )
        svc.db.close.assert_called_once()

    def test_facade_forwards_new_process_options(self):
        server = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.db = Mock()
        svc.update_supplier_tariff.return_value = {"altas": 1}
        with patch.object(server, "service", return_value=svc):
            server.tool_tarifa_proveedor_actualizar({
                "proveedor": 9,
                "lineas": [{"articulo": "A1", "precio_base": 10}],
                "actualizar_precio_venta": True,
                "actualizar_solo_si_sube_precio": True,
                "actualizar_solo_proveedor_principal": True,
                "actualizar_solo_si_propio": True,
                "generar_etiquetas": True,
                "etiqueta_modelo": 7,
                "dar_de_alta": True,
                "usar_referencia_proveedor_como_codigo": True,
                "digitos_codigo_articulo": 10,
                "numerador_inicial": 5,
            })
        svc.update_supplier_tariff.assert_called_once_with(
            9, [{"articulo": "A1", "precio_base": 10}], True,
            solo_si_sube_precio=True,
            solo_proveedor_principal=True,
            solo_si_propio=True,
            generar_etiquetas=True,
            etiqueta_modelo=7,
            dar_de_alta=True,
            usar_referencia_proveedor_como_codigo=True,
            digitos_codigo_articulo=10,
            numerador_inicial=5,
        )


class SupplierTariffProcessOptionsTests(unittest.TestCase):
    """Replican las casillas "Opciones Proceso" de IMPTAR_U.pas que faltaban
    en update_supplier_tariff (B_MAS, B_PRINCIPAL, B_PROPIO, B_DESCRI sobre
    ARTICUL, B_ETIQUETAS). Ver revision-tarifa-proveedor-actualizar.md."""

    def test_solo_si_sube_precio_skips_when_new_cost_is_lower(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        artp = dict(ARTP)
        artp["ARTP_PREBAS"] = Decimal("5.00")
        artp["ARTP_DTOAUM1"] = Decimal("0")
        artp["ARTP_DTOAUM2"] = Decimal("0")
        # ARTICLE["ART_PREBAS"] = 7.00; coste neto nuevo (5.00, sin descuentos) < 7.00 -> se omite.
        result = svc._update_sale_price_from_supplier_tariff(
            dict(ARTICLE), artp, 9, solo_si_sube_precio=True,
        )
        self.assertFalse(result["actualizado"])
        self.assertEqual(result["omitido_por"], "precio_no_sube")
        self.assertFalse(any(sql.startswith("UPDATE ARTICUL SET") for sql, _ in db.executed))

    def test_solo_si_sube_precio_allows_update_when_new_cost_is_higher(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        recalculated = dict(ARTICLE)
        recalculated["ART_PVP"] = Decimal("15.00")
        with patch.object(svc, "calculate_article_price", return_value=recalculated):
            result = svc._update_sale_price_from_supplier_tariff(
                dict(ARTICLE), dict(ARTP), 9, solo_si_sube_precio=True,
            )
        self.assertTrue(result["actualizado"])
        self.assertTrue(any(sql.startswith("UPDATE ARTICUL SET") for sql, _ in db.executed))

    def test_solo_proveedor_principal_skips_when_line_supplier_is_not_principal(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        article = dict(ARTICLE)
        article["ART_CODPRO"] = 5
        result = svc._update_sale_price_from_supplier_tariff(
            article, dict(ARTP), 9, solo_proveedor_principal=True,
        )
        self.assertFalse(result["actualizado"])
        self.assertEqual(result["omitido_por"], "proveedor_no_principal")
        self.assertFalse(any(sql.startswith("UPDATE ARTICUL SET") for sql, _ in db.executed))

    def test_solo_proveedor_principal_allows_update_when_line_supplier_matches(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        recalculated = dict(ARTICLE)
        recalculated["ART_PVP"] = Decimal("15.00")
        with patch.object(svc, "calculate_article_price", return_value=recalculated):
            result = svc._update_sale_price_from_supplier_tariff(
                dict(ARTICLE), dict(ARTP), 9, solo_proveedor_principal=True,
            )
        self.assertTrue(result["actualizado"])

    def test_solo_si_propio_skips_when_article_marked_not_own(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        article = dict(ARTICLE)
        article["ART_INDPROP"] = "N"
        result = svc._update_sale_price_from_supplier_tariff(
            article, dict(ARTP), 9, solo_si_propio=True,
        )
        self.assertFalse(result["actualizado"])
        self.assertEqual(result["omitido_por"], "articulo_no_propio")

    def test_solo_si_propio_allows_update_when_flag_is_not_n(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        article = dict(ARTICLE)
        article["ART_INDPROP"] = "S"
        recalculated = dict(ARTICLE)
        recalculated["ART_PVP"] = Decimal("15.00")
        with patch.object(svc, "calculate_article_price", return_value=recalculated):
            result = svc._update_sale_price_from_supplier_tariff(
                article, dict(ARTP), 9, solo_si_propio=True,
            )
        self.assertTrue(result["actualizado"])

    def test_descripcion_articulo_overwrites_articul_descri(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        recalculated = dict(ARTICLE)
        recalculated["ART_PVP"] = Decimal("20.00")
        with patch.object(svc, "calculate_article_price", return_value=recalculated):
            result = svc._update_sale_price_from_supplier_tariff(
                dict(ARTICLE), dict(ARTP), 9, descripcion_articulo="Nueva descripcion",
            )
        self.assertEqual(result["descripcion_actualizada"], "Nueva descripcion")
        sql, params = next(
            (sql, params) for sql, params in db.executed if sql.startswith("UPDATE ARTICUL SET")
        )
        self.assertIn("ART_DESCRI=?", sql)
        self.assertIn("Nueva descripcion", params)

    def test_without_descripcion_articulo_articul_descri_is_untouched(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        recalculated = dict(ARTICLE)
        recalculated["ART_PVP"] = Decimal("20.00")
        with patch.object(svc, "calculate_article_price", return_value=recalculated):
            svc._update_sale_price_from_supplier_tariff(dict(ARTICLE), dict(ARTP), 9)
        sql, _ = next(
            (sql, params) for sql, params in db.executed if sql.startswith("UPDATE ARTICUL SET")
        )
        self.assertNotIn("ART_DESCRI=?", sql)

    def test_generar_etiquetas_inserts_label_when_pvp_changes(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        recalculated = dict(ARTICLE)
        recalculated["ART_PVP"] = Decimal("20.00")  # distinto del ART_PVP actual (12.10)
        with patch.object(svc, "calculate_article_price", return_value=recalculated):
            result = svc._update_sale_price_from_supplier_tariff(
                dict(ARTICLE), dict(ARTP), 9, generar_etiquetas=True, etiqueta_modelo=3,
            )
        self.assertTrue(result["etiqueta_generada"])
        label_sql, label_params = next(
            (sql, params) for sql, params in db.executed if sql.startswith("INSERT INTO ETIQUE")
        )
        self.assertEqual(label_params[0], 1)
        self.assertEqual(label_params[1], "A1")
        self.assertEqual(label_params[3], Decimal("1"))
        self.assertEqual(label_params[4], "S")
        self.assertEqual(label_params[5], 3)

    def test_generar_etiquetas_skips_label_when_pvp_unchanged(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        recalculated = dict(ARTICLE)  # ART_PVP identico -> sin cambio de precio
        with patch.object(svc, "calculate_article_price", return_value=recalculated):
            result = svc._update_sale_price_from_supplier_tariff(
                dict(ARTICLE), dict(ARTP), 9, generar_etiquetas=True,
            )
        self.assertFalse(result["etiqueta_generada"])
        self.assertFalse(any(sql.startswith("INSERT INTO ETIQUE") for sql, _ in db.executed))

    def test_update_supplier_tariff_counts_only_actual_sale_updates_and_labels(self):
        db = FakeTariffDb(ARTP)
        svc = faro_mcp.FaroArticleService(db)
        db.article["ART_CODPRO"] = 5  # no coincide con el proveedor de la linea (9)
        recalculated = dict(ARTICLE)
        recalculated["ART_PVP"] = Decimal("20.00")
        with patch.object(svc, "calculate_article_price", return_value=recalculated):
            result = svc.update_supplier_tariff(
                9, [{"articulo": "A1", "precio_base": 10}], True,
                solo_proveedor_principal=True,
            )
        self.assertEqual(result["precios_venta_actualizados"], 0)
        self.assertEqual(result["etiquetas_generadas"], 0)
        self.assertEqual(result["resultados"][0]["precio_venta"]["omitido_por"], "proveedor_no_principal")


class SupplierTariffAltaTests(unittest.TestCase):
    """Replica la rama "ELSE IF B_ALTA.Checked" de IMPTAR_U.pas: cuando
    dar_de_alta=true y la linea no resuelve a un articulo existente, se crea
    ARTICUL + ARTICULP en el mismo lote en vez de fallar. Ver
    revision-tarifa-proveedor-actualizar.md."""

    NEW_LINE = {
        "articulo": "NEW1",
        "descripcion": "Articulo nuevo de prueba",
        "seccion": "01",
        "tipo_iva": 1,
        "tipo_precio": "V",
        "unidad_medida": "UD",
        "precio_base": "10.00",
    }

    def test_without_dar_de_alta_still_raises_and_rolls_back(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        with self.assertRaises(faro_mcp.FaroError):
            svc.update_supplier_tariff(9, [dict(self.NEW_LINE)])
        self.assertFalse(db.committed)
        self.assertTrue(db.rolled_back)

    def test_dar_de_alta_creates_articul_and_articulp(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        result = svc.update_supplier_tariff(9, [dict(self.NEW_LINE)], dar_de_alta=True)
        self.assertEqual(result["articulos_creados"], 1)
        self.assertEqual(result["altas"], 1)
        self.assertTrue(db.committed)
        self.assertFalse(db.rolled_back)

        articul_sql, articul_params = next(
            (sql, params) for sql, params in db.executed if sql.startswith("INSERT INTO ARTICUL ")
        )
        fields = [f.strip() for f in articul_sql.split("(", 1)[1].split(")", 1)[0].split(",")]
        row = dict(zip(fields, articul_params))
        self.assertEqual(row["ART_CODART"], "NEW1")
        self.assertEqual(row["ART_DESCRI"], "Articulo nuevo de prueba")
        self.assertEqual(row["ART_SECCIO"], "01")
        self.assertEqual(row["ART_TIPIVA"], 1)
        self.assertEqual(row["ART_TIPPRE"], "V")
        self.assertEqual(row["ART_UNIMED"], "UD")
        self.assertEqual(row["ART_INDPROP"], "S")
        self.assertEqual(row["ART_CODPRO"], 9)
        self.assertEqual(row["ART_PREBAS"], Decimal("10.00"))
        self.assertIsNone(row["ART_FEBAJA"])
        self.assertIsNone(row["ART_FECMOV"])

        self.assertTrue(any(sql.startswith("INSERT INTO ARTICULP") for sql, _ in db.executed))
        self.assertEqual(result["resultados"][0]["accion"], "alta_articulo")
        self.assertTrue(result["resultados"][0]["articulo_creado"])

    def test_dar_de_alta_requires_new_article_fields(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        incomplete = {"articulo": "NEW1", "precio_base": "10.00"}
        with self.assertRaises(faro_mcp.FaroError) as ctx:
            svc.update_supplier_tariff(9, [incomplete], dar_de_alta=True)
        message = str(ctx.exception)
        for field in ("descripcion", "seccion", "tipo_iva", "tipo_precio", "unidad_medida"):
            self.assertIn(field, message)
        self.assertFalse(db.committed)
        self.assertTrue(db.rolled_back)

    def test_dar_de_alta_ignores_actualizar_precio_venta_for_new_article(self):
        # IMPTAR_U.pas: MODIFICAR_PVENTA solo existe en la rama "IF NOT ALTA";
        # una linea de alta nunca pasa por ese bloque.
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        result = svc.update_supplier_tariff(
            9, [dict(self.NEW_LINE)], True, dar_de_alta=True,
        )
        self.assertIsNone(result["resultados"][0]["precio_venta"])
        self.assertEqual(result["precios_venta_actualizados"], 0)
        self.assertFalse(any(sql.startswith("UPDATE ARTICUL SET") for sql, _ in db.executed))

    def test_dar_de_alta_canon_forces_tipo_precio_c(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        line = dict(self.NEW_LINE)
        line["canon"] = "5.00"
        svc.update_supplier_tariff(9, [line], dar_de_alta=True)
        articul_sql, articul_params = next(
            (sql, params) for sql, params in db.executed if sql.startswith("INSERT INTO ARTICUL ")
        )
        fields = [f.strip() for f in articul_sql.split("(", 1)[1].split(")", 1)[0].split(",")]
        row = dict(zip(fields, articul_params))
        self.assertEqual(row["ART_TIPPRE"], "C")
        self.assertEqual(row["ART_IMPFIJ"], Decimal("5.00"))

    def test_dar_de_alta_inserts_barcode_when_provided(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        line = dict(self.NEW_LINE)
        line["codigo_barras"] = "8412345678901"
        svc.update_supplier_tariff(9, [line], dar_de_alta=True)
        barcode_sql, barcode_params = next(
            (sql, params) for sql, params in db.executed if sql.startswith("INSERT INTO ARTICULC")
        )
        self.assertEqual(barcode_params, (1, "NEW1", "8412345678901", Decimal("1")))

    def test_dar_de_alta_computes_sale_prices_with_price_table(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        line = dict(self.NEW_LINE)
        line["tabla_precios"] = 1
        result = svc.update_supplier_tariff(9, [line], dar_de_alta=True)
        articul_sql, articul_params = next(
            (sql, params) for sql, params in db.executed if sql.startswith("INSERT INTO ARTICUL ")
        )
        fields = [f.strip() for f in articul_sql.split("(", 1)[1].split(")", 1)[0].split(",")]
        row = dict(zip(fields, articul_params))
        # Coste 10.00 sin descuentos, tabla sin recargos -> PVP = coste * 1.21 (IVA 21%).
        self.assertEqual(Decimal(str(row["ART_PVP"])), Decimal("12.10"))
        self.assertEqual(Decimal(result["resultados"][0]["precio_base"]), Decimal("10.00"))

    def test_dar_de_alta_still_raises_for_line_with_no_identifiers_at_all(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        with self.assertRaises(faro_mcp.FaroError):
            svc.update_supplier_tariff(9, [{"precio_base": "10.00"}], dar_de_alta=True)


class SupplierTariffAltaCodeGenerationTests(unittest.TestCase):
    """Replica la generacion automatica de ART_CODART de IMPTAR_U.pas
    (IMPTAR_U.pas:1727-1742, B_DIGITOS/NumInicial/B_REFPRO) cuando
    dar_de_alta=true y la linea no informa 'articulo'. Ver
    revision-tarifa-proveedor-actualizar.md."""

    NO_CODE_LINE = {
        "descripcion": "Articulo nuevo sin codigo",
        "seccion": "1",
        "tipo_iva": 1,
        "tipo_precio": "V",
        "unidad_medida": "UD",
        "precio_base": "10.00",
    }

    def test_generates_code_from_seccion_provider_and_counter_defaults(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        result = svc.update_supplier_tariff(9, [dict(self.NO_CODE_LINE)], dar_de_alta=True)
        # seccion "1" + proveedor "0009" (4 digitos) + contador "0000"
        # (ancho = digitos_codigo_articulo(9) - 5, numerador_inicial=0 por defecto).
        self.assertEqual(result["resultados"][0]["articulo"], "100090000")
        self.assertTrue(result["resultados"][0]["articulo_creado"])

    def test_generated_code_skips_codes_that_already_exist(self):
        db = FakeTariffDb(None, existing_codes={"100090000", "100090001"})
        svc = faro_mcp.FaroArticleService(db)
        result = svc.update_supplier_tariff(9, [dict(self.NO_CODE_LINE)], dar_de_alta=True)
        self.assertEqual(result["resultados"][0]["articulo"], "100090002")

    def test_digitos_codigo_articulo_and_numerador_inicial_change_the_generated_code(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        result = svc.update_supplier_tariff(
            9, [dict(self.NO_CODE_LINE)], dar_de_alta=True,
            digitos_codigo_articulo=8, numerador_inicial=7,
        )
        # ancho contador = 8 - 5 = 3 -> "007"
        self.assertEqual(result["resultados"][0]["articulo"], "10009007")

    def test_counter_is_shared_and_advances_across_lines_of_the_same_batch(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        line2 = dict(self.NO_CODE_LINE)
        line2["descripcion"] = "Segundo articulo nuevo"
        result = svc.update_supplier_tariff(
            9, [dict(self.NO_CODE_LINE), line2], dar_de_alta=True,
        )
        codes = [r["articulo"] for r in result["resultados"]]
        self.assertEqual(codes, ["100090000", "100090001"])

    def test_usar_referencia_proveedor_como_codigo_uses_the_supplier_reference(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        line = dict(self.NO_CODE_LINE)
        line["referencia_proveedor"] = "REF-123"
        result = svc.update_supplier_tariff(
            9, [line], dar_de_alta=True, usar_referencia_proveedor_como_codigo=True,
        )
        self.assertEqual(result["resultados"][0]["articulo"], "REF-123")

    def test_usar_referencia_proveedor_como_codigo_requires_the_reference(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        with self.assertRaises(faro_mcp.FaroError):
            svc.update_supplier_tariff(
                9, [dict(self.NO_CODE_LINE)], dar_de_alta=True,
                usar_referencia_proveedor_como_codigo=True,
            )
        self.assertFalse(db.committed)
        self.assertTrue(db.rolled_back)

    def test_explicit_articulo_still_wins_over_autogeneration(self):
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        line = dict(self.NO_CODE_LINE)
        line["articulo"] = "EXPLICIT1"
        line["referencia_proveedor"] = "REF-999"
        result = svc.update_supplier_tariff(
            9, [line], dar_de_alta=True, usar_referencia_proveedor_como_codigo=True,
        )
        self.assertEqual(result["resultados"][0]["articulo"], "EXPLICIT1")

    def test_digitos_codigo_articulo_out_of_range_raises(self):
        # La validacion de digitos_codigo_articulo ocurre antes de abrir la
        # transaccion del lote (nada que insertar todavia), asi que no hay
        # commit ni rollback: simplemente no se ejecuta ninguna sentencia.
        db = FakeTariffDb(None)
        svc = faro_mcp.FaroArticleService(db)
        with self.assertRaises(faro_mcp.FaroError):
            svc.update_supplier_tariff(
                9, [dict(self.NO_CODE_LINE)], dar_de_alta=True, digitos_codigo_articulo=7,
            )
        self.assertFalse(db.committed)
        self.assertFalse(any(sql.startswith("INSERT") for sql, _ in db.executed))

    def test_facade_passes_new_alta_code_options_through_to_the_service(self):
        result = faro_mcp.translate_public_arguments(
            "tarifa_proveedor_actualizar",
            {
                "proveedor": 9,
                "lineas": [dict(self.NO_CODE_LINE)],
                "dar_de_alta": True,
                "usar_referencia_proveedor_como_codigo": True,
                "digitos_codigo_articulo": 10,
                "numerador_inicial": 3,
            },
        )
        self.assertTrue(result["usar_referencia_proveedor_como_codigo"])
        self.assertEqual(result["digitos_codigo_articulo"], 10)
        self.assertEqual(result["numerador_inicial"], 3)


if __name__ == "__main__":
    unittest.main()
