import unittest
from decimal import Decimal

import faro_mcp


class FakeDb:
    def __init__(self, mode="cash"):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=1, usuario="test",
        )
        self.mode = mode
        self.closed = False

    def fetch_one(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM PARAMETROS" in u:
            return None
        if "FROM ARTICUL WHERE" in u:
            return {
                "ART_NUMEMP": 1, "ART_CODART": "A1", "ART_DESCRI": "Articulo",
                "ART_SECCIO": "01", "ART_TIPPRE": "V", "ART_TIPIVA": 1,
                "ART_CODMON": "E", "ART_UNIMED": "UNI", "ART_PVP": Decimal("121"),
                "ART_PREVEN1": Decimal("70"), "ART_PREVEN2": Decimal("80"),
                "ART_PREVEN3": Decimal("94"), "ART_PREVEN4": Decimal("100"),
                "ART_PRETAR": Decimal("0"), "ART_CANPMI": Decimal("0"),
                "ART_CANPRE": Decimal("1"), "ART_PREBAS": Decimal("50"),
                "ART_PRECOS": Decimal("55"), "ART_TABPREC": 0, "ART_CODFAM": 0,
                "ART_SUBFAM": 0, "ART_CODPRO": 1,
            }
        if "FROM TIPIVA" in u:
            return {"TIV_PORIVA": Decimal("21"), "TIV_PORREQ": Decimal("5.2")}
        if "FROM CLIEN WHERE" in u:
            if self.mode == "risk":
                return {"CLI_RIESGO": Decimal("-1")}
            if self.mode == "special":
                return {
                    "CLI_CODCLI": 10, "CLI_SUBCLI": 0, "CLI_TIPPRE": "4",
                    "CLI_PORAUM": Decimal("0"), "CLI_REGIVA": "N",
                }
            return None
        if "FROM CLIENI" in u:
            return None
        if "FROM CLIART" in u:
            if self.mode == "special":
                return {
                    "CLIA_CODART": "A1", "CLIA_CODCLI": 10,
                    "CLIA_PRECIO": Decimal("80"), "CLIA_CANPRE": Decimal("1"),
                    "CLIA_CODMON": "E", "CLIA_DESCUE": Decimal("5"), "CLIA_DESCRI": "",
                }
            return None
        if "FROM DETOFER" in u:
            return None
        if "FROM CLITAB" in u or "FROM CLIFAM" in u or "FROM CLIACT" in u:
            return None
        if "FROM ARTICULI" in u:
            return None
        return None

    def fetch_all(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM DETMOV INNER JOIN CABDOCV" in u:
            return [
                {"DMV_CODART": "A", "DMV_DESCRI": "Uno|x", "DMV_UNIMED": "U", "DMV_PREVEN": 1, "DMV_PVP": 2, "DMV_FECMOV": "2026-09-14"},
                {"DMV_CODART": "A", "DMV_DESCRI": "Antiguo", "DMV_UNIMED": "U", "DMV_PREVEN": 9, "DMV_PVP": 9, "DMV_FECMOV": "2026-09-13"},
                {"DMV_CODART": "B", "DMV_DESCRI": "Dos#x", "DMV_UNIMED": "KG", "DMV_PREVEN": 3, "DMV_PVP": 4, "DMV_FECMOV": "2026-09-12"},
            ]
        if "FROM ARTICULI" in u:
            return []
        return []

    def execute(self, sql, params=()):
        raise AssertionError("No debe escribir en Fase 2A")

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class Phase2CommercialTests(unittest.TestCase):
    def test_server_has_no_datasnap_proxies(self):
        server = faro_mcp.FaroToolRuntime()
        self.assertFalse(any(name.startswith("datasnap_") for name in server.tools))
        definitions = faro_mcp.tool_definitions()
        self.assertFalse(any(item["name"].startswith("datasnap_") for item in definitions))

    def test_cash_customer_price_uses_pvp_with_vat(self):
        svc = faro_mcp.FaroPhase1Service(FakeDb("cash"))
        result = svc.customer_article_price("A1", "2", 99999, 0)
        self.assertTrue(result["found"])
        self.assertEqual(result["preven"], "100")
        self.assertEqual(result["pvp"], "121")
        self.assertEqual(result["poriva"], "21")
        self.assertEqual(result["tippre"], "4")
        self.assertEqual(result["preiva"], "S")

    def test_special_customer_price_has_priority(self):
        svc = faro_mcp.FaroPhase1Service(FakeDb("special"))
        result = svc.customer_article_price("A1", "2", 10, 0)
        self.assertEqual(result["preven"], "80")
        self.assertEqual(result["dto1"], "5")
        self.assertEqual(result["tippre"], "0")
        self.assertEqual(result["preiva"], "N")

    def test_tipo_venta_cliente_rules(self):
        svc = faro_mcp.FaroPhase1Service(FakeDb("cash"))
        blocked = svc.customer_sale_type("A", 99999, 0)
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["message"], "Debe especificar el cliente")

        svc = faro_mcp.FaroPhase1Service(FakeDb("risk"))
        blocked = svc.customer_sale_type("A", 10, 0)
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["message"], "No se pueden hacer albaranes a los clientes sin Riesgo")

    def test_last_customer_sales_keeps_latest_unique_article(self):
        svc = faro_mcp.FaroPhase1Service(FakeDb())
        result = svc.last_customer_sales(10, 0)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["items"][0]["codart"], "A")
        self.assertEqual(result["items"][0]["preven"], 1)
        self.assertEqual(result["items"][0]["descri"], "Unox")
        self.assertEqual(result["items"][1]["descri"], "Dosx")
        self.assertEqual(result["datasnap_text"], "A|Unox|U|1|2#B|Dosx|KG|3|4#")


if __name__ == "__main__":
    unittest.main()
