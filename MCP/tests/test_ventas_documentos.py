"""Pruebas de las herramientas tipo ANADOC para analisis documental de ventas."""
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import faro_mcp


class FakeDocumentDb:
    def __init__(self, rows):
        self.settings = type("S", (), {"empresa": 1, "centro": 7})()
        self.rows = rows
        self.last_sql = ""
        self.last_params = ()
        self.closed = False

    def fetch_one(self, sql, params=()):
        if "FROM PARAMETROS" in " ".join(sql.upper().split()):
            return {"PAR_VALOR": "1"} if params[1] == "FPGCON" else None
        return None

    def fetch_all(self, sql, params=()):
        self.last_sql = sql
        self.last_params = params
        return self.rows

    def close(self):
        self.closed = True


def doc_row(**overrides):
    row = {
        "CBV_CENTRO": 7,
        "CBV_TIPDOC": "F",
        "CBV_TIPAC": "0",
        "CBV_EJERCI": 2026,
        "CBV_SERIE": "A",
        "CBV_NUMDOC": 100,
        "CBV_CAJA": 0,
        "CBV_FECHA": date(2026, 1, 5),
        "CBV_FECHAE": None,
        "CBV_CODCLI": 10,
        "CBV_SUBCLI": 0,
        "CBV_NOMCLI": "Cliente",
        "CBV_POBLAC": "Valencia",
        "CBV_CODMON": "E",
        "CBV_CODPAG": 2,
        "CBV_FORCOB": "E",
        "CBV_CODREP": 3,
        "CBV_CODTAR": "T1",
        "CBV_SITUAC": "P",
        "CBV_REFCLI": "REF",
        "CBV_RETIRA": "",
        "CBV_USUMOD": "USR",
        "CBV_OBSERV": "",
        "CBV_CIF": "B1",
        "CBV_EJERCID": 0,
        "CBV_TIPDOCD": "",
        "CBV_SERIED": "",
        "CBV_NUMDOCD": 0,
        "CBV_FECMOD": datetime(2026, 1, 5, 9, 30),
        "CBV_TOTALD": Decimal("121"),
        "CBV_IMPCOB": Decimal("21"),
        "CBV_IMPPOR": Decimal("0"),
        "CBV_PORDTO": Decimal("0"),
        "CBV_BASIMP1": Decimal("100"),
        "CBV_BASIMP2": Decimal("0"),
        "CBV_BASIMP3": Decimal("0"),
        "CBV_BASIMP4": Decimal("0"),
        "CBV_PORIVA1": Decimal("21"),
        "CBV_PORIVA2": Decimal("0"),
        "CBV_PORIVA3": Decimal("0"),
        "CBV_PORIVA4": Decimal("0"),
        "CBV_PORREQ1": Decimal("0"),
        "CBV_PORREQ2": Decimal("0"),
        "CBV_PORREQ3": Decimal("0"),
        "CBV_PORREQ4": Decimal("0"),
        "CLI_NOMCLI": "Cli",
        "CLI_TIPFAC": "M",
        "CLI_ZONA": 4,
        "ZON_DESCRI": "Levante",
    }
    row.update(overrides)
    return row


class SalesDocumentServiceTests(unittest.TestCase):
    def test_sales_document_details_uses_real_sales_policy_and_signed_credit(self):
        db = FakeDocumentDb([
            doc_row(CBV_TIPDOC="F", CBV_TOTALD=Decimal("121"), CBV_IMPCOB=Decimal("21")),
            doc_row(CBV_TIPDOC="C", CBV_TOTALD=Decimal("12.10"), CBV_BASIMP1=Decimal("10"), CBV_IMPCOB=Decimal("0")),
        ])
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.sales_document_details(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            tipos_documento=["F", "A", "T", "P"],
            moneda="E",
        )

        self.assertIn("NOT EXISTS", db.last_sql)
        self.assertIn("D.DMV_TIPDOCO='A'", db.last_sql)
        self.assertIn("T se omite", " ".join(result["avisos"]))
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["items"][0]["categoria"], "factura")
        self.assertEqual(result["items"][1]["categoria"], "credito")
        self.assertEqual(Decimal(result["items"][1]["total"]), Decimal("-12.10"))
        self.assertEqual(Decimal(result["totales"]["total"]), Decimal("108.90"))

    def test_sales_document_summary_groups_by_customer(self):
        rows = [
            doc_row(CBV_CODCLI=10, CBV_NOMCLI="Cliente A", CBV_TOTALD=Decimal("100"), CBV_BASIMP1=Decimal("100")),
            doc_row(CBV_CODCLI=10, CBV_SUBCLI=1, CBV_NOMCLI="Cliente A", CBV_TOTALD=Decimal("50"), CBV_BASIMP1=Decimal("50")),
            doc_row(CBV_CODCLI=99999, CBV_SUBCLI=1, CBV_NOMCLI="Contado 1", CBV_TOTALD=Decimal("30"), CBV_BASIMP1=Decimal("30")),
            doc_row(CBV_CODCLI=99999, CBV_SUBCLI=2, CBV_NOMCLI="Contado 2", CBV_TOTALD=Decimal("20"), CBV_BASIMP1=Decimal("20")),
        ]
        svc = faro_mcp.FaroPhase1Service(FakeDocumentDb(rows))

        result = svc.sales_document_summary({
            "fecha_desde": "2026-01-01",
            "fecha_hasta": "2026-01-31",
            "agrupar_por": "cliente",
        })

        self.assertEqual(result["count"], 3)
        self.assertEqual(result["items"][0]["codigo"], "10")
        self.assertEqual(Decimal(result["items"][0]["total"]), Decimal("150"))
        self.assertEqual([item["codigo"] for item in result["items"][1:]], ["99999/1", "99999/2"])

    def test_sales_document_summary_groups_by_weekday_hour_and_customer_zone(self):
        rows = [
            doc_row(CBV_CODCLI=10, CBV_TOTALD=Decimal("100"), CLI_ZONA=4, ZON_DESCRI="Levante"),
            doc_row(CBV_CODCLI=20, CBV_TOTALD=Decimal("50"), CLI_ZONA=5, ZON_DESCRI="Norte", CBV_FECMOD=datetime(2026, 1, 5, 10, 15)),
        ]
        svc = faro_mcp.FaroPhase1Service(FakeDocumentDb(rows))

        by_zone = svc.sales_document_summary({
            "fecha_desde": "2026-01-01",
            "fecha_hasta": "2026-01-31",
            "agrupar_por": "zona_cliente",
            "zona_desde": 4,
            "zona_hasta": 5,
        })
        zone_sql = svc.db.last_sql
        by_hour = svc.sales_document_summary({
            "fecha_desde": "2026-01-01",
            "fecha_hasta": "2026-01-31",
            "agrupar_por": "hora",
        })
        by_weekday = svc.sales_document_summary({
            "fecha_desde": "2026-01-01",
            "fecha_hasta": "2026-01-31",
            "agrupar_por": "dia_semana",
        })

        self.assertEqual([item["codigo"] for item in by_zone["items"]], ["4", "5"])
        self.assertIn("L.CLI_ZONA>=?", zone_sql)
        self.assertEqual([item["nombre"] for item in by_hour["items"]], ["09:00", "10:00"])
        self.assertEqual(by_weekday["items"][0]["codigo"], "lunes")

    def test_sales_document_abc_classifies_cumulative_sales(self):
        rows = [
            doc_row(CBV_CODCLI=10, CBV_NOMCLI="Cliente A", CBV_TOTALD=Decimal("80"), CBV_BASIMP1=Decimal("80")),
            doc_row(CBV_CODCLI=20, CBV_NOMCLI="Cliente B", CBV_TOTALD=Decimal("15"), CBV_BASIMP1=Decimal("15")),
            doc_row(CBV_CODCLI=30, CBV_NOMCLI="Cliente C", CBV_TOTALD=Decimal("5"), CBV_BASIMP1=Decimal("5")),
        ]
        svc = faro_mcp.FaroPhase1Service(FakeDocumentDb(rows))

        result = svc.sales_document_abc({
            "fecha_desde": "2026-01-01",
            "fecha_hasta": "2026-01-31",
            "agrupar_por": "cliente",
        })

        self.assertEqual([item["abc"] for item in result["items"]], ["A", "B", "C"])
        self.assertEqual(result["items"][0]["porcentaje_acumulado"], "80")


class SalesDocumentRuntimeTests(unittest.TestCase):
    def test_runtime_exposes_document_sales_tools_as_read_only_core_tools(self):
        for name in ("venta_documentos_detalle", "venta_documentos_resumen", "venta_documentos_abc"):
            with self.subTest(name=name):
                self.assertIn(name, faro_mcp.CORE_PUBLIC_TOOL_NAMES)
                self.assertIn(name, faro_mcp.READ_ONLY_TOOL_NAMES)

    def test_runtime_delegates_document_summary_and_closes_service(self):
        runtime = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.sales_document_summary.return_value = {"count": 0, "items": []}
        svc.db.close = Mock()

        with patch.object(runtime, "phase1_service", return_value=svc):
            result = runtime.tool_venta_documentos_resumen({"fecha_desde": "2026-01-01", "fecha_hasta": "2026-01-31"})

        self.assertEqual(result, {"count": 0, "items": []})
        svc.sales_document_summary.assert_called_once_with({"fecha_desde": "2026-01-01", "fecha_hasta": "2026-01-31"})
        svc.db.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
