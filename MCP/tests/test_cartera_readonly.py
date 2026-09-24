import unittest
from decimal import Decimal

import faro_mcp


class FakeCarteraDb:
    def __init__(self):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=1, usuario="test",
        )

    def fetch_one(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM PARAMETROS" in u:
            return None
        if "FROM CLIEN" in u:
            return {
                "CLI_CODCLI": 10,
                "CLI_SUBCLI": 0,
                "CLI_NOMCLI": "Cliente 10",
                "CLI_RAZSOC": "Cliente SA",
                "CLI_AGRUPAC": "N",
                "CLI_RIESGO": Decimal("1000"),
                "CLI_RIESGOA": Decimal("650"),
                "CLI_CODMON": "E",
            }
        return None

    def fetch_all(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM CABDOCVE" in u and "GROUP BY CBVE_CODMON" not in u:
            return [
                {
                    "CBVE_NUMEMP": 1, "CBVE_CENTRO": 1, "CBVE_TIPDOC": "F", "CBVE_TIPAC": "",
                    "CBVE_EJERCI": 2026, "CBVE_SERIE": "A", "CBVE_NUMDOC": 100, "CBVE_NUMORD": 1,
                    "CBVE_TIPGES": "", "CBVE_TIPOEF": "R", "CBVE_CODACEP": "", "CBVE_FECHA": "2026-09-01",
                    "CBVE_FECVTO": "2026-09-10", "CBVE_IMPORT": Decimal("250"), "CBVE_CODMON": "E",
                    "CBVE_CODCLI": 10, "CBVE_SUBCLI": 0, "CBVE_FECCAN": None,
                    "CBVE_IMPCOB": Decimal("50"), "CBVE_IMPGAS": Decimal("5"), "CBVE_FECIMP": None,
                    "CBVE_INDEDI": "N", "CBVE_OBSERV": "Obs", "CBVE_EJEREM": 0, "CBVE_CODREM": 0,
                },
                {
                    "CBVE_NUMEMP": 1, "CBVE_CENTRO": 1, "CBVE_TIPDOC": "F", "CBVE_TIPAC": "",
                    "CBVE_EJERCI": 2026, "CBVE_SERIE": "A", "CBVE_NUMDOC": 101, "CBVE_NUMORD": 1,
                    "CBVE_TIPGES": "", "CBVE_TIPOEF": "T", "CBVE_CODACEP": "", "CBVE_FECHA": "2026-09-02",
                    "CBVE_FECVTO": "2026-10-10", "CBVE_IMPORT": Decimal("100"), "CBVE_CODMON": "E",
                    "CBVE_CODCLI": 10, "CBVE_SUBCLI": 0, "CBVE_FECCAN": "2026-09-15",
                    "CBVE_IMPCOB": Decimal("100"), "CBVE_IMPGAS": Decimal("0"), "CBVE_FECIMP": None,
                    "CBVE_INDEDI": "N", "CBVE_OBSERV": "", "CBVE_EJEREM": 2026, "CBVE_CODREM": 7,
                },
            ]
        if "FROM CABDOCVE" in u and "GROUP BY CBVE_CODMON" in u:
            return [{"CBVE_IMPORT": Decimal("300"), "CBVE_IMPCOB": Decimal("50"), "CBVE_CODMON": "E"}]
        if "FROM CABDOCV" in u:
            return []
        if "FROM REMESA R" in u:
            return [
                {
                    "REM_EJERCI": 2026, "REM_CODIGO": 7, "REM_TIPO": "R", "REM_FECHA": "2026-09-12",
                    "REM_FECCON": None, "REM_FECENV": None, "REM_TOTAL": Decimal("100"), "REM_CODMON": "E",
                    "REM_CODBAN": 1, "REM_CODSUC": 2, "REM_DIGITO": 3, "REM_NUMCUE": "123",
                    "REM_CUECON": "572", "REM_SITUAC": "P", "EFECTOS": 1, "PENDIENTE_EFECTOS": Decimal("0"),
                }
            ]
        if "FROM CLIEN" in u:
            return [{"CLI_CODCLI": 10, "CLI_SUBCLI": 0}]
        return []

    def execute(self, sql, params=()):
        raise AssertionError("Las funciones de Cartera son solo lectura")

    def close(self):
        pass


class CarteraReadOnlyTests(unittest.TestCase):
    def test_cartera_effect_details_calculates_pending_amounts(self):
        svc = faro_mcp.FaroPhase1Service(FakeCarteraDb())
        result = svc.cartera_effect_details({"fecha_referencia": "2026-09-22"})
        self.assertEqual(result["totales"]["efectos"], 2)
        self.assertEqual(result["totales"]["pendiente"], "205")
        self.assertEqual(result["efectos"][0]["situacion"], "vencido")
        self.assertFalse(result["efectos"][0]["remesado"])

    def test_cartera_by_customer_groups_pending_and_remitted(self):
        svc = faro_mcp.FaroPhase1Service(FakeCarteraDb())
        result = svc.cartera_effects_by_customer({"fecha_referencia": "2026-09-22"})
        self.assertEqual(result["clientes"][0]["cliente"]["codigo"], 10)
        self.assertEqual(result["clientes"][0]["pendiente"], "205")
        self.assertEqual(result["clientes"][0]["no_remesado"], "205")

    def test_cartera_risk_breakdown_uses_riesgo_actual_rules(self):
        svc = faro_mcp.FaroPhase1Service(FakeCarteraDb())
        result = svc.cartera_customer_credit_risk({"cliente": 10, "subcliente": 0})
        self.assertEqual(result["riesgo_concedido"], "1000")
        self.assertEqual(result["riesgo_consumido"], "250")
        self.assertEqual(result["riesgo_actual"], "750")

    def test_cartera_remittance_summary_is_read_only(self):
        svc = faro_mcp.FaroPhase1Service(FakeCarteraDb())
        result = svc.cartera_remittance_summary({})
        self.assertEqual(result["totales"]["remesas"], 1)
        self.assertEqual(result["remesas"][0]["codigo"], 7)


if __name__ == "__main__":
    unittest.main()
