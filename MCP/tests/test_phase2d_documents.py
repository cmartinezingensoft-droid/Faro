import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock

import faro_mcp


class MinimalDb:
    def __init__(self):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=7, usuario="tester",
        )
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.executed = []
        self.rows = []

    def fetch_one(self, sql, params=()):
        self.rows.append(("one", " ".join(sql.upper().split()), params))
        return None

    def fetch_all(self, sql, params=()):
        self.rows.append(("all", " ".join(sql.upper().split()), params))
        return []

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.upper().split()), params))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class Phase2DTests(unittest.TestCase):
    def test_tools_registered_native_only(self):
        server = faro_mcp.FaroToolRuntime()
        self.assertIn("mostrador_venta_gestion", server.tools)
        self.assertNotIn("mostrador_pedido_cargar", server.tools)
        self.assertIn("venta_documento_crear", server.tools)
        self.assertEqual(len(server.tools), 85)
        self.assertFalse(any(name.startswith("datasnap_") for name in server.tools))

    def test_parse_document_line_matches_14_field_protocol(self):
        db = MinimalDb()
        svc = faro_mcp.FaroPhase1Service(db)
        cbv = {
            "CBV_NUMEMP": 1, "CBV_CENTRO": 7, "CBV_TIPDOC": "A", "CBV_TIPAC": "0",
            "CBV_EJERCI": 2026, "CBV_SERIE": "A", "CBV_NUMDOC": 3, "CBV_CAJA": 1,
            "CBV_USUMOD": "carlos", "CBV_FECHA": date(2026, 9, 14), "CBV_CODMON": "E",
        }
        raw = "A1|Articulo|2|10|5|3|21|0|4|UNI|N|12.10|2026|9"
        line = svc._parse_document_sale_line(cbv, 10, raw)
        self.assertEqual(line["DMV_CODART"], "A1")
        self.assertEqual(line["DMV_CANTID"], Decimal("2"))
        self.assertEqual(line["DMV_DTO1"], Decimal("5"))
        self.assertEqual(line["DMV_DTO2"], Decimal("3"))
        self.assertEqual(line["DMV_PORIVA"], Decimal("21"))
        self.assertEqual(line["DMV_EJEOFE"], 2026)
        self.assertEqual(line["DMV_NUMOFE"], 9)

    def test_grabar_albaran_orchestrates_document_and_commits(self):
        db = MinimalDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._serie_documento = Mock(return_value="A")
        svc._busqueda_clien_pedido = Mock(return_value={
            "codrep": 2, "razsoc": "Cliente", "cif": "B1", "domici": "Calle", "codpos": "46000",
            "poblac": "Valencia", "forpag": 1, "forenv": 0, "dtoesp": Decimal("0"), "regiva": "N",
        })
        svc._busqueda_tipven2 = Mock(return_value=4)
        svc._insert_cabdocv_order = Mock(return_value=55)
        svc._grabar_detmov_g_albaran = Mock(side_effect=lambda line: line)
        svc._record_document_canon = Mock(return_value=1)
        svc._record_document_gifts = Mock(return_value=1)
        svc._finalizar_documento_venta = Mock(return_value={
            "cabecera_borrada": False,
            "totals": {"totals": Decimal("20"), "totald": Decimal("24.2")},
        })
        svc._minimum_delivery_amount = Mock(return_value=None)

        text = "A1|Articulo|2|10|0|0|21|0|4|UNI|N|12.1|0|0#"
        result = svc.save_sales_document("", 7, 10, 0, text, "A", "carlos")
        self.assertEqual(result["documento"], f"A-{date.today().year}-A-55")
        self.assertEqual(result["lineas_principales"], 1)
        self.assertEqual(result["lineas_canon"], 1)
        self.assertEqual(result["lineas_regalo"], 1)
        self.assertEqual(result["datasnap_text"], result["documento"])
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)

    def test_grabar_albaran_uses_explicit_series_when_provided(self):
        db = MinimalDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._serie_documento = Mock(return_value="A")
        svc._busqueda_clien_pedido = Mock(return_value={
            "codrep": 2, "razsoc": "Cliente", "cif": "B1", "domici": "Calle", "codpos": "46000",
            "poblac": "Valencia", "forpag": 1, "forenv": 0, "dtoesp": Decimal("0"), "regiva": "N",
        })
        svc._busqueda_tipven2 = Mock(return_value=4)
        svc._insert_cabdocv_order = Mock(return_value=56)
        svc._grabar_detmov_g_albaran = Mock(side_effect=lambda line: line)
        svc._record_document_canon = Mock(return_value=0)
        svc._record_document_gifts = Mock(return_value=0)
        svc._finalizar_documento_venta = Mock(return_value={
            "cabecera_borrada": False,
            "totals": {"totals": Decimal("20"), "totald": Decimal("24.2")},
        })
        svc._minimum_delivery_amount = Mock(return_value=None)

        text = "A1|Articulo|2|10|0|0|21|0|4|UNI|N|12.1|0|0#"
        result = svc.save_sales_document("", 7, 10, 0, text, "A", "carlos", "Z9")
        self.assertEqual(result["documento"], f"A-{date.today().year}-Z9-56")
        self.assertEqual(result["serie"], "Z9")
        svc._serie_documento.assert_not_called()

    def test_grabar_albaran_calculates_series_from_document_center(self):
        db = MinimalDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._serie_documento = Mock(return_value="AL")
        svc._busqueda_clien_pedido = Mock(return_value={
            "codrep": 2, "razsoc": "Cliente", "cif": "B1", "domici": "Calle", "codpos": "46000",
            "poblac": "Valencia", "forpag": 1, "forenv": 0, "dtoesp": Decimal("0"), "regiva": "N",
        })
        svc._busqueda_tipven2 = Mock(return_value=4)
        svc._insert_cabdocv_order = Mock(return_value=57)
        svc._grabar_detmov_g_albaran = Mock(side_effect=lambda line: line)
        svc._record_document_canon = Mock(return_value=0)
        svc._record_document_gifts = Mock(return_value=0)
        svc._finalizar_documento_venta = Mock(return_value={
            "cabecera_borrada": False,
            "totals": {"totals": Decimal("20"), "totald": Decimal("24.2")},
        })
        svc._minimum_delivery_amount = Mock(return_value=None)

        text = "A1|Articulo|2|10|0|0|21|0|4|UNI|N|12.1|0|0#"
        result = svc.save_sales_document("", 0, 10, 0, text, "A", "carlos", "")
        self.assertEqual(result["serie"], "AL")
        svc._serie_documento.assert_called_once_with("A", 0)

    def test_grabar_albaran_consumes_open_sale_after_header_numbering(self):
        class SaleDb(MinimalDb):
            def fetch_one(self, sql, params=()):
                u = " ".join(sql.upper().split())
                if "SELECT * FROM VENCAJ" in u:
                    return {
                        "CBV_CODREP": 2, "CBV_NOMCLI": "Cliente", "CBV_CIF": "B1", "CBV_DOMCLI": "Calle",
                        "CBV_CODPOS": "46000", "CBV_POBLAC": "Valencia", "CBV_CODPAG": 1,
                        "CBV_FORENV": 0, "CBV_PORDTO": Decimal("0"), "CBV_TIPVEN": 4,
                    }
                return super().fetch_one(sql, params)
        db = SaleDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._serie_documento = Mock(return_value="A")
        svc._probe_vencaj_lock = Mock(return_value=True)
        svc._insert_cabdocv_order = Mock(return_value=77)
        svc._finalizar_documento_venta = Mock(return_value={"cabecera_borrada": True, "totals": None})
        svc._minimum_delivery_amount = Mock(return_value=None)

        result = svc.save_sales_document("2026-9", 7, 10, 0, "", "A", "carlos")
        self.assertTrue(result["venta_eliminada"])
        deletes = [sql for sql, _ in db.executed if sql.startswith("DELETE FROM VENCAJ") or sql.startswith("DELETE FROM VENCUR")]
        self.assertEqual(len(deletes), 2)
        self.assertEqual(db.commits, 1)

    def test_open_sale_from_order_partial_service(self):
        class OrderDb(MinimalDb):
            def __init__(self):
                super().__init__()
                self.calls = 0
            def fetch_one(self, sql, params=()):
                u = " ".join(sql.upper().split())
                if "SELECT * FROM CABDOCV" in u:
                    return {
                        "CBV_NUMEMP": 1, "CBV_CENTRO": 7, "CBV_TIPDOC": "P", "CBV_TIPAC": "0",
                        "CBV_EJERCI": 2026, "CBV_SERIE": "PM", "CBV_NUMDOC": 10, "CBV_CAJA": 1,
                        "CBV_USUMOD": "u", "CBV_FECHA": date(2026, 9, 1), "CBV_FECHAE": date(2026, 9, 1),
                        "CBV_CODCLI": 10, "CBV_SUBCLI": 0, "CBV_CODREP": 2, "CBV_COMREP": Decimal("0"),
                        "CBV_NOMCLI": "Cliente", "CBV_CIF": "B1", "CBV_DOMCLI": "Calle", "CBV_CODPOS": "46000",
                        "CBV_POBLAC": "Valencia", "CBV_CODPAG": 1, "CBV_FORENV": 0, "CBV_PORDTO": Decimal("0"),
                        "CBV_IMPPOR": Decimal("0"), "CBV_BASIMP1": Decimal("20"), "CBV_PORIVA1": Decimal("21"),
                        "CBV_PORREQ1": Decimal("0"), "CBV_BASIMP2": Decimal("0"), "CBV_PORIVA2": Decimal("0"),
                        "CBV_PORREQ2": Decimal("0"), "CBV_BASIMP3": Decimal("0"), "CBV_PORIVA3": Decimal("0"),
                        "CBV_PORREQ3": Decimal("0"), "CBV_BASIMP4": Decimal("0"), "CBV_PORIVA4": Decimal("0"),
                        "CBV_PORREQ4": Decimal("0"), "CBV_TOTALS": Decimal("20"), "CBV_TOTALD": Decimal("24.2"),
                        "CBV_IMPCOB": Decimal("0"), "CBV_CODMON": "E", "CBV_FORCOB": "", "CBV_NUMTAR": 0,
                        "CBV_TIPVEN": 4, "CBV_SITUAC": "P", "CBV_OBSERV": "", "CBV_FECMOD": datetime.now(),
                        "CBV_REFCLI": "", "CBV_RETIRA": "", "CBV_CODTAR": "", "CBV_INDEDI": "N",
                        "CBV_EJERCID": 0, "CBV_TIPDOCD": "", "CBV_SERIED": "", "CBV_NUMDOCD": 0,
                    }
                if "SELECT * FROM DETMOV" in u:
                    return {
                        "DMV_NUMEMP": 1, "DMV_CENTRO": 7, "DMV_TIPDOC": "P", "DMV_TIPAC": "0",
                        "DMV_EJERCI": 2026, "DMV_SERIE": "PM", "DMV_NUMDOC": 10, "DMV_NUMLIN": 10,
                        "DMV_SIGNO": "0", "DMV_CAJA": 1, "DMV_USUAR": "u", "DMV_TIPLIN": "D",
                        "DMV_FECMOV": date(2026, 9, 1), "DMV_CODART": "A1", "DMV_DESCRI": "Articulo",
                        "DMV_CODMON": "E", "DMV_TIPPRE": "4", "DMV_PREVEN": Decimal("10"),
                        "DMV_PORIVA": Decimal("21"), "DMV_PORREQ": Decimal("0"), "DMV_PVP": Decimal("12.1"),
                        "DMV_CANTID": Decimal("5"), "DMV_CANPRE": Decimal("1"), "DMV_UNIMED": "UNI",
                        "DMV_DTO1": Decimal("0"), "DMV_DTO2": Decimal("0"), "DMV_VALLIN": Decimal("60.5"),
                        "DMV_VALLINS": Decimal("50"), "DMV_IMPDTO": Decimal("0"), "DMV_EJEOFE": 0,
                        "DMV_NUMOFE": 0, "DMV_EJERCIO": 0, "DMV_TIPDOCO": "", "DMV_SERIEO": "",
                        "DMV_NUMDOCO": 0, "DMV_NUMLINO": 0, "DMV_PREIVA": "N",
                    }
                return None
        db = OrderDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._cabdocv_to_open_sale = Mock(return_value={
            "CBV_NUMEMP": 1, "CBV_EJERCI": date.today().year, "CBV_NUMDOC": 0, "CBV_CAJA": 1,
            "CBV_USUMOD": "u", "CBV_TIPDOC": "T", "CBV_TIPAC": "0", "CBV_SERIE": "T",
            "CBV_FECHA": date.today(), "CBV_FECHAE": date.today(), "CBV_CODCLI": 10, "CBV_SUBCLI": 0,
            "CBV_CODREP": 2, "CBV_COMREP": Decimal("0"), "CBV_NOMCLI": "Cliente", "CBV_CIF": "B1",
            "CBV_DOMCLI": "Calle", "CBV_CODPOS": "46000", "CBV_POBLAC": "Valencia", "CBV_CODPAG": 1,
            "CBV_FORENV": 0, "CBV_PORDTO": Decimal("0"), "CBV_IMPPOR": Decimal("0"),
            "CBV_BASIMP1": Decimal("0"), "CBV_PORIVA1": Decimal("0"), "CBV_PORREQ1": Decimal("0"),
            "CBV_BASIMP2": Decimal("0"), "CBV_PORIVA2": Decimal("0"), "CBV_PORREQ2": Decimal("0"),
            "CBV_BASIMP3": Decimal("0"), "CBV_PORIVA3": Decimal("0"), "CBV_PORREQ3": Decimal("0"),
            "CBV_BASIMP4": Decimal("0"), "CBV_PORIVA4": Decimal("0"), "CBV_PORREQ4": Decimal("0"),
            "CBV_TOTALS": Decimal("0"), "CBV_TOTALD": Decimal("0"), "CBV_IMPCOB": Decimal("0"),
            "CBV_CODMON": "E", "CBV_FORCOB": "", "CBV_NUMTAR": 0, "CBV_TIPVEN": 4,
            "CBV_SITUAC": "P", "CBV_OBSERV": "", "CBV_FECMOD": datetime.now(), "CBV_REFCLI": "",
            "CBV_RETIRA": "", "CBV_CODTAR": "",
        })
        svc._insert_open_sale_numbered = Mock(side_effect=lambda cbv: cbv.__setitem__("CBV_NUMDOC", 88) or 88)
        svc._insertar_linea_servida = Mock()
        svc._reducir_linea_pedido_pendiente = Mock()
        svc._actualizar_linea_pedido_servida = Mock()
        svc._insert_valued_vencur = Mock(side_effect=lambda line: line)
        svc._value_vencaj_header = Mock(side_effect=lambda cbv: {**cbv, "CBV_TOTALS": Decimal("20"), "CBV_TOTALD": Decimal("24.2")})
        svc._update_vencaj_totals = Mock()
        svc._insert_cabdocv_row = Mock()
        svc._finalizar_documento_venta = Mock(return_value={"cabecera_borrada": False, "totals": {}})

        result = svc.save_open_sale_from_order(7, "2026-PM-10", "T", "10|A1|Articulo|2#")
        self.assertTrue(result["ok"])
        self.assertEqual(result["venta"]["numdoc"], 88)
        self.assertEqual(result["lineas_servidas"][0]["cantidad"], "2")
        svc._insertar_linea_servida.assert_called_once()
        svc._reducir_linea_pedido_pendiente.assert_called_once()
        svc._actualizar_linea_pedido_servida.assert_not_called()
        self.assertEqual(db.commits, 1)

    def test_open_sale_from_order_missing_order_returns_false(self):
        db = MinimalDb()
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.save_open_sale_from_order(7, "2026-PM-999", "T", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["datasnap_text"], "False")
        self.assertEqual(db.commits, 0)


if __name__ == "__main__":
    unittest.main()
