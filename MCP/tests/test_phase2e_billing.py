import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock

import faro_mcp


class BillingDb:
    def __init__(self):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=7, usuario="tester",
        )
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.effect_rows = []

    def fetch_one(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM PARAMETROS" in u:
            values = {"MODOVE": "1", "TIPGES": "C", "FPGCON": "5", "NUMDEC": "2", "DECLIN": "2"}
            value = values.get(params[1])
            return {"PAR_VALOR": value} if value is not None else None
        if "SELECT FIRST 1 CBVE_NUMDOC" in u:
            return None
        if "CLI_DIAPAG1" in u:
            return {
                "CLI_CODCLI": 10, "CLI_SUBCLI": 0, "CLI_DIAPAG1": 0, "CLI_DIAPAG2": 0,
                "CLI_DIAPAG3": 0, "CLI_MESNOV1": 0, "CLI_MESNOV2": 0,
            }
        if "FROM FORPAG" in u and "FORPAGA" not in u:
            return {"FPG_CODIGO": 5, "FPG_TIPDOC": "R", "FPG_CODACEP": "N"}
        if "MAX(OPC_NUMLIN)" in u:
            return {"OPC_NUMLIN": 3}
        if "SELECT FIRST 1 OPC_NUMLIN" in u:
            return None
        return None

    def fetch_all(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM FORPAGA" in u:
            return [{"FPGA_APLAZ": 0}, {"FPGA_APLAZ": 30}]
        return []

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.upper().split()), params))
        if sql.upper().startswith("INSERT INTO CABDOCVE"):
            self.effect_rows.append(params)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class Phase2EBillingTests(unittest.TestCase):
    def test_ticket_tool_registered_natively(self):
        server = faro_mcp.FaroToolRuntime()
        self.assertIn("mostrador_cobrar", server.tools)
        self.assertEqual(len(server.tools), 85)
        self.assertFalse(any(name.startswith("datasnap_") for name in server.tools))

    def test_spfechas_month_end_rule(self):
        svc = faro_mcp.FaroPhase1Service(BillingDb())
        dates = svc._spfechas(date(2026, 1, 31), [30, 60], [0, 0, 0], [0, 0], 1)
        self.assertEqual(dates[0], date(2026, 2, 28))
        self.assertEqual(dates[1], date(2026, 3, 31))

    def test_generate_invoice_effects_distributes_payment(self):
        db = BillingDb()
        svc = faro_mcp.FaroPhase1Service(db)
        cbv = {
            "CBV_NUMEMP": 1, "CBV_CENTRO": 7, "CBV_TIPDOC": "F", "CBV_TIPAC": "0",
            "CBV_EJERCI": 2026, "CBV_SERIE": "F", "CBV_NUMDOC": 12,
            "CBV_FECHA": date(2026, 9, 14), "CBV_TOTALD": Decimal("100"), "CBV_IMPCOB": Decimal("30"),
            "CBV_CODMON": "E", "CBV_CODCLI": 10, "CBV_SUBCLI": 0, "CBV_CODPAG": 5,
        }
        count = svc._generate_invoice_effects(cbv)
        self.assertEqual(count, 2)
        self.assertEqual(len(db.effect_rows), 2)
        # CBVE_IMPORT indice 13; CBVE_FECCAN indice 17; CBVE_IMPCOB indice 18.
        self.assertEqual(db.effect_rows[0][13], Decimal("50"))
        self.assertEqual(db.effect_rows[0][18], Decimal("30"))
        self.assertIsNone(db.effect_rows[0][17])
        self.assertEqual(db.effect_rows[1][13], Decimal("50"))
        self.assertEqual(db.effect_rows[1][18], Decimal("0"))

    def test_finalizer_generates_effects_and_risk_for_invoice(self):
        class FinalDb(BillingDb):
            def fetch_one(self, sql, params=()):
                if "COUNT(*) AS N FROM DETMOV" in " ".join(sql.upper().split()):
                    return {"N": 1}
                return super().fetch_one(sql, params)
        svc = faro_mcp.FaroPhase1Service(FinalDb())
        cbv = {
            "CBV_NUMEMP": 1, "CBV_CENTRO": 7, "CBV_TIPDOC": "F", "CBV_TIPAC": "0", "CBV_EJERCI": 2026,
            "CBV_SERIE": "F", "CBV_NUMDOC": 1, "CBV_CODCLI": 10, "CBV_SUBCLI": 0, "CBV_CODPAG": 5,
            "CBV_SITUAC": "P", "CBV_PORDTO": Decimal("0"), "CBV_USUMOD": "u", "CBV_FECHA": date.today(),
            "CBV_FECMOD": datetime.now(), "CBV_CODMON": "E", "CBV_IMPCOB": Decimal("0"), "CBV_COMREP": Decimal("0"),
            "CBV_FORCOB": "", "CBV_OBSERV": "",
        }
        svc._busqueda_clien_pedido = Mock(return_value={"regiva": "N"})
        svc._iva_cabdocv_pedido = Mock(return_value=[])
        totals = {**cbv,
            "CBV_BASIMP1": Decimal("100"), "CBV_PORIVA1": Decimal("21"), "CBV_PORREQ1": Decimal("0"),
            "CBV_BASIMP2": Decimal("0"), "CBV_PORIVA2": Decimal("0"), "CBV_PORREQ2": Decimal("0"),
            "CBV_BASIMP3": Decimal("0"), "CBV_PORIVA3": Decimal("0"), "CBV_PORREQ3": Decimal("0"),
            "CBV_BASIMP4": Decimal("0"), "CBV_PORIVA4": Decimal("0"), "CBV_PORREQ4": Decimal("0"),
            "CBV_TOTALS": Decimal("100"), "CBV_TOTALD": Decimal("121"),
        }
        svc._totales_cabecera_pedido = Mock(return_value=totals)
        svc._generate_invoice_effects = Mock(return_value=2)
        svc._modificar_cabdocv_totales = Mock()
        svc._update_cabdocv_runtime_fields = Mock()
        svc._actualiza_riesgo_cliente = Mock(return_value={"valor": Decimal("500"), "moneda": "E", "warning": ""})
        result = svc._finalizar_documento_venta(cbv)
        self.assertEqual(result["efectos"], 2)
        self.assertEqual(result["riesgo"]["valor"], Decimal("500"))
        svc._generate_invoice_effects.assert_called_once()
        svc._actualiza_riesgo_cliente.assert_called_once()

    def test_ticket_overpayment_only_reduces_cash_movement(self):
        db = BillingDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._serie_ticket = Mock(return_value="T")
        svc._busqueda_clien_pedido = Mock(return_value={
            "codrep": 2, "razsoc": "Cliente", "cif": "B", "domici": "C", "codpos": "46000", "poblac": "V",
            "forpag": 1, "forenv": 0, "dtoesp": Decimal("0"), "regiva": "N",
        })
        svc._busqueda_tipven2 = Mock(return_value=4)
        captured = {}
        def insert_header(cbv):
            captured["cbv"] = cbv
            cbv["CBV_NUMDOC"] = 94
            return 94
        svc._insert_cabdocv_order = Mock(side_effect=insert_header)
        payments = []
        svc._insert_opecaj = Mock(side_effect=lambda opc: payments.append(dict(opc)) or len(payments))
        svc._grabar_detmov_g_albaran = Mock(side_effect=lambda line: line)
        svc._record_document_canon = Mock(return_value=0)
        svc._record_document_gifts = Mock(return_value=0)
        svc._finalizar_documento_venta = Mock(return_value={"totals": {"totals": Decimal("100"), "totald": Decimal("100")}, "efectos": 0, "riesgo": None})
        svc._print_ticket_best_effort = Mock(return_value={"intentada": False, "enviada": False})
        result = svc.save_ticket_invoice(1, "80", "30", "", "", "100", "", 7, 10, 0, "", "T", "u")
        self.assertEqual(result["documento"], f"T-{date.today().year}-T-94")
        self.assertEqual(payments[0]["OPC_IMPORT"], Decimal("70"))
        self.assertEqual(payments[1]["OPC_IMPORT"], Decimal("30"))
        self.assertEqual(captured["cbv"]["CBV_IMPCOB"], Decimal("100"))
        self.assertEqual(captured["cbv"]["CBV_COMREP"], Decimal("110"))
        self.assertEqual(db.commits, 1)

    def test_invoice_uses_fc_series_and_cash_payment_form_parameter(self):
        db = BillingDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._serie_documento = Mock(return_value="FC26")
        svc._busqueda_clien_pedido = Mock(return_value={
            "codrep": 2, "razsoc": "Cliente", "cif": "B", "domici": "C", "codpos": "46000", "poblac": "V",
            "forpag": 9, "forenv": 0, "dtoesp": Decimal("0"), "regiva": "N",
        })
        svc._busqueda_tipven2 = Mock(return_value=7)
        captured = {}
        svc._insert_cabdocv_order = Mock(side_effect=lambda cbv: captured.setdefault("cbv", dict(cbv)) or 11)
        # side_effect anterior devuelve dict; usar funcion explicita
        def number(cbv):
            captured["cbv"] = dict(cbv)
            cbv["CBV_NUMDOC"] = 11
            return 11
        svc._insert_cabdocv_order = Mock(side_effect=number)
        svc._finalizar_documento_venta = Mock(return_value={"totals": {}, "efectos": 1, "riesgo": None})
        svc._print_ticket_best_effort = Mock(return_value={"intentada": False, "enviada": False})
        result = svc.save_ticket_invoice(1, "", "", "", "", "0", "", 7, 10, 0, "", "F", "u")
        # centro=7 (el de este documento) debe llegar a la busqueda de serie;
        # antes se ignoraba y se usaba el centro global del runtime, lo que
        # daba una serie equivocada o vacia en instalaciones con mas de un
        # centro o cuando el centro de la llamada no coincidia con el global.
        svc._serie_documento.assert_called_once_with("FC", 7)
        self.assertEqual(captured["cbv"]["CBV_CODPAG"], 5)
        self.assertEqual(result["tipdoc"], "F")

    def _mock_ticket_dependencies(self, svc, numdoc, captured):
        svc._busqueda_clien_pedido = Mock(return_value={
            "codrep": 2, "razsoc": "Cliente", "cif": "B", "domici": "C", "codpos": "46000", "poblac": "V",
            "forpag": 1, "forenv": 0, "dtoesp": Decimal("0"), "regiva": "N",
        })
        svc._busqueda_tipven2 = Mock(return_value=4)

        def insert_header(cbv):
            captured["cbv"] = dict(cbv)
            cbv["CBV_NUMDOC"] = numdoc
            return numdoc

        svc._insert_cabdocv_order = Mock(side_effect=insert_header)
        svc._finalizar_documento_venta = Mock(return_value={"totals": {}, "efectos": 0, "riesgo": None})
        svc._print_ticket_best_effort = Mock(return_value={"intentada": False, "enviada": False})

    def test_ticket_series_uses_documents_own_centro_not_global_default(self):
        # BillingDb fija settings.centro=7; esta venta se cobra para el
        # centro 3, que es el que debe usarse para buscar la serie (antes se
        # ignoraba el centro de la llamada y siempre se usaba el 7 global).
        db = BillingDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._serie_ticket = Mock(return_value="T3")
        captured = {}
        self._mock_ticket_dependencies(svc, 55, captured)
        svc.save_ticket_invoice(1, "50", "", "", "", "50", "", 3, 10, 0, "", "T", "u")
        svc._serie_ticket.assert_called_once_with(3)
        self.assertEqual(captured["cbv"]["CBV_SERIE"], "T3")

    def test_ticket_honors_explicit_serie_override(self):
        db = BillingDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._serie_ticket = Mock(return_value="NO_DEBERIA_USARSE")
        svc._serie_documento = Mock(return_value="NO_DEBERIA_USARSE")
        captured = {}
        self._mock_ticket_dependencies(svc, 56, captured)
        svc.save_ticket_invoice(1, "50", "", "", "", "50", "", 7, 10, 0, "", "T", "u", serie="ZZ")
        svc._serie_ticket.assert_not_called()
        svc._serie_documento.assert_not_called()
        self.assertEqual(captured["cbv"]["CBV_SERIE"], "ZZ")

    def test_ticket_from_open_sale_copies_vencur_when_lines_are_empty(self):
        class OpenSaleDb(BillingDb):
            def fetch_one(self, sql, params=()):
                u = " ".join(sql.upper().split())
                if "SELECT * FROM VENCAJ" in u:
                    return {
                        "CBV_CODREP": 2, "CBV_NOMCLI": "Cliente", "CBV_CIF": "B",
                        "CBV_DOMCLI": "Calle", "CBV_CODPOS": "46000", "CBV_POBLAC": "Valencia",
                        "CBV_CODPAG": 1, "CBV_FORENV": 0, "CBV_PORDTO": Decimal("0"), "CBV_TIPVEN": 4,
                    }
                return super().fetch_one(sql, params)

            def fetch_all(self, sql, params=()):
                u = " ".join(sql.upper().split())
                if "FROM VENCUR" in u:
                    return [{
                        "DMV_NUMEMP": 1, "DMV_EJERCI": 2026, "DMV_NUMDOC": 113, "DMV_NUMLIN": 10,
                        "DMV_CAJA": 1, "DMV_USUAR": "web", "DMV_TIPLIN": "D",
                        "DMV_FECMOV": date(2026, 9, 15), "DMV_CODART": "A1", "DMV_DESCRI": "Articulo",
                        "DMV_CODMON": "E", "DMV_TIPPRE": "4", "DMV_PREVEN": Decimal("94.78"),
                        "DMV_PORIVA": Decimal("21"), "DMV_PORREQ": Decimal("0"), "DMV_PVP": Decimal("114.68"),
                        "DMV_CANTID": Decimal("1"), "DMV_CANPRE": Decimal("1"), "DMV_UNIMED": "UNI",
                        "DMV_DTO1": Decimal("0"), "DMV_DTO2": Decimal("0"), "DMV_VALLIN": Decimal("114.68"),
                        "DMV_VALLINS": Decimal("94.78"), "DMV_IMPDTO": Decimal("0"), "DMV_EJEOFE": 0,
                        "DMV_NUMOFE": 0, "DMV_EJERCIO": 0, "DMV_TIPDOCO": "", "DMV_SERIEO": "",
                        "DMV_NUMDOCO": 0, "DMV_NUMLINO": 0, "DMV_PREIVA": "N",
                    }]
                return super().fetch_all(sql, params)

        db = OpenSaleDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._serie_ticket = Mock(return_value="TT")
        svc._probe_vencaj_lock = Mock(return_value=True)
        svc._insert_cabdocv_order = Mock(return_value=222)
        inserted_lines = []
        svc._grabar_detmov_g_albaran = Mock(side_effect=lambda line: inserted_lines.append(dict(line)) or line)
        svc._insert_opecaj = Mock(return_value=1)
        svc._finalizar_documento_venta = Mock(return_value={
            "totals": {"totals": Decimal("94.78"), "totald": Decimal("114.68")},
            "efectos": 0,
            "riesgo": None,
        })
        svc._print_ticket_best_effort = Mock(return_value={"intentada": False, "enviada": False})

        result = svc.save_ticket_invoice(1, "114.68", "", "", "", "114.68", "2026-113", 0, 100, 0, "[]", "T", "probador-web")

        self.assertEqual(result["lineas_principales"], 1)
        self.assertEqual(inserted_lines[0]["DMV_CENTRO"], 0)
        self.assertEqual(inserted_lines[0]["DMV_TIPDOC"], "T")
        self.assertEqual(inserted_lines[0]["DMV_SERIE"], "TT")
        self.assertEqual(inserted_lines[0]["DMV_NUMDOC"], 222)
        self.assertEqual(inserted_lines[0]["DMV_CODART"], "A1")
        deletes = [sql for sql, _ in db.executed if sql.startswith("DELETE FROM VENCAJ") or sql.startswith("DELETE FROM VENCUR")]
        self.assertEqual(len(deletes), 2)

    def test_serie_ticket_prefers_configured_tt_parameter_over_fallback(self):
        # GRABAR_TICKET (Delphi) busca la serie del ticket en PARAMETROS con
        # la clave 'TT'+centro, no 'T'+centro como el resto de documentos.
        db = BillingDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc.parameter = Mock(return_value="Z9")
        self.assertEqual(svc._serie_ticket(3), "Z9")
        svc.parameter.assert_called_once_with("TT3", "")

    def test_serie_ticket_falls_back_to_serie_ticket_formula_when_unconfigured(self):
        # BillingDb.fetch_one solo conoce MODOVE/TIPGES/FPGCON/NUMDEC/DECLIN
        # como PAR_CODIGO, asi que "TT7" no existe -> debe caer al algoritmo
        # SERIE_TICKET en vez de devolver una serie vacia.
        db = BillingDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._serie_ticket_fallback = Mock(return_value="XY")
        self.assertEqual(svc._serie_ticket(7), "XY")
        svc._serie_ticket_fallback.assert_called_once_with()

    def test_serie_ticket_fallback_encodes_month_and_day(self):
        # Replica TABLA[1..9]='1'..'9', TABLA[10..31]='A'..'V' del Delphi
        # (SERIE_TICKET = TABLA[MES] + TABLA[DIA]).
        db = BillingDb()
        svc = faro_mcp.FaroPhase1Service(db)
        self.assertEqual(svc._serie_ticket_fallback(date(2026, 1, 1)), "11")
        self.assertEqual(svc._serie_ticket_fallback(date(2026, 9, 15)), "9F")
        self.assertEqual(svc._serie_ticket_fallback(date(2026, 10, 10)), "AA")
        self.assertEqual(svc._serie_ticket_fallback(date(2026, 12, 31)), "CV")


if __name__ == "__main__":
    unittest.main()
