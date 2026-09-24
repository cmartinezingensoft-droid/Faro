import os
import tempfile
import os
import unittest
from unittest.mock import patch
from datetime import date
from decimal import Decimal
from pathlib import Path

import faro_mcp


class OrchestrationDb:
    def __init__(self, existing=False):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=7, usuario="test",
        )
        self.existing = existing
        self.output_lines = []
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def fetch_one(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM ARTICUL WHERE" in u:
            return {"ART_DESCRI": f"Articulo {params[1]}", "ART_UNIMED": "UD"}
        if "FROM CABDOCR" in u and "CBR_TIPO=?" in u:
            if not self.existing:
                return None
            return {
                "CBR_NUMEMP": 1, "CBR_CENTRO": 2, "CBR_EJERCI": date.today().year,
                "CBR_SERIE": "TR", "CBR_NUMDOC": 10, "CBR_FECHA": date.today(),
                "CBR_TIPO": "S", "CBR_CENREL": 3, "CBR_OBSERV": "Trasvase Centro 3",
                "CBR_NUMDOCE": 77,
            }
        if "FROM CABDOCR" in u and "CBR_NUMDOC=?" in u:
            return {
                "CBR_NUMEMP": 1, "CBR_CENTRO": 3, "CBR_EJERCI": date.today().year,
                "CBR_SERIE": "TR", "CBR_NUMDOC": 77, "CBR_TIPO": "E",
            }
        return None

    def fetch_all(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM DETMOVR" in u:
            return list(self.output_lines)
        return []

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), params))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class PurchaseEntryDb:
    def __init__(self, supplier_article=True):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=7, usuario="test",
        )
        self.supplier_article = supplier_article
        self.executed = []
        self.provider_queries = []
        self.detmovm_lines = []
        self.commits = 0
        self.rollbacks = 0

    def fetch_one(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM PARAMETROS" in u:
            code = params[1]
            if code == "E":
                return {"PAR_VALOR": "EN"}
            if code in {"NUMDEC", "DECLIN"}:
                return {"PAR_VALOR": "2"}
            return None
        if "FROM PROVEE" in u:
            self.provider_queries.append((u, params))
            if "PRO_CODPRO=?" in u and int(params[1]) != 44:
                return None
            if "PRO_CIF=?" in u and str(params[1]) != "B44":
                return None
            return {
                "PRO_CODPRO": 44, "PRO_NOMCOR": "Proveedor 44", "PRO_DOMICI": "Calle",
                "PRO_CODPOS": 46000, "PRO_POBLAC": "Valencia", "PRO_CIF": "B44",
                "PRO_CODPAG": 3,
            }
        if "MAX(CBM_NUMDOC)" in u:
            return {"NUMDOC": 100}
        if "MAX(DMM_NUMLIN)" in u:
            return {"NUMLIN": len(self.detmovm_lines) * 10} if self.detmovm_lines else {"NUMLIN": None}
        if "FROM ARTICULP" in u and self.supplier_article:
            return {
                "ARTP_CODART": "A1", "ARTP_REFPRO": "REF-A1", "ARTP_UNIMED": "UD",
                "ARTP_PREBAS": Decimal("8"), "ARTP_DTOAUM1": Decimal("5"),
                "ARTP_DTOAUM2": Decimal("0"), "ARTP_DTOAUM3": Decimal("0"),
                "ARTP_DTOAUM4": Decimal("0"), "ARTP_DTOAUM5": Decimal("0"),
                "ARTP_DTOAUM6": Decimal("0"),
            }
        if "SELECT ART_CODART, ART_DESCRI, ART_UNIMED FROM ARTICUL" in u:
            return {"ART_CODART": params[1], "ART_DESCRI": f"Articulo {params[1]}", "ART_UNIMED": "UD"}
        if "FROM DETORC,CABORC" in u:
            return {"DOC_EJERCI": 2026, "DOC_SERIE": "OC", "DOC_NUMDOC": 9, "DOC_NUMLIN": 20}
        if "SELECT ART_INDINV FROM ARTICUL" in u:
            return {"ART_INDINV": "S"}
        return None

    def fetch_all(self, sql, params=()):
        return []

    def execute(self, sql, params=()):
        normalized_sql = " ".join(sql.split())
        self.executed.append((normalized_sql, params))
        if normalized_sql.startswith("INSERT INTO DETMOVM"):
            self.detmovm_lines.append(params)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class PurchaseOrderCloseDb:
    def __init__(self, exists=True, fail_execute=False):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=7, usuario="test",
        )
        self.exists = exists
        self.fail_execute = fail_execute
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def fetch_one(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM CABORC" in u and self.exists:
            return {
                "COC_NUMEMP": 1, "COC_CENTRO": params[1], "COC_EJERCI": params[2],
                "COC_SERIE": params[3], "COC_NUMDOC": params[4], "COC_SITUAC": "P",
                "COC_IMPPEN": Decimal("25.00"),
            }
        return None

    def fetch_all(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM DETORC" in u:
            return [
                {"DOC_NUMLIN": 10, "DOC_SITUAC": "A", "DOC_CIEMAN": "N", "DOC_CANPEN": Decimal("2"), "DOC_VALPEN": Decimal("10")},
                {"DOC_NUMLIN": 20, "DOC_SITUAC": "A", "DOC_CIEMAN": "N", "DOC_CANPEN": Decimal("3"), "DOC_VALPEN": Decimal("15")},
            ]
        return []

    def execute(self, sql, params=()):
        if self.fail_execute:
            raise RuntimeError("fallo simulado")
        self.executed.append((" ".join(sql.split()), params))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class Phase2FLogisticsTests(unittest.TestCase):
    def _service(self, existing=False):
        db = OrchestrationDb(existing=existing)
        svc = faro_mcp.FaroPhase1Service(db)
        svc.parameter = lambda code, default="": "TR" if code == "R7" else default
        headers = []
        destination_lines = []
        deleted = []

        def insert_header(centro, ejerci, serie, fecha, tipo, cenrel, observ, numdoce=0):
            numdoc = 10 if tipo == "S" else 88
            header = {
                "CBR_NUMEMP": 1, "CBR_CENTRO": centro, "CBR_EJERCI": ejerci,
                "CBR_SERIE": serie, "CBR_NUMDOC": numdoc, "CBR_FECHA": fecha,
                "CBR_TIPO": tipo, "CBR_CENREL": cenrel, "CBR_OBSERV": observ,
                "CBR_NUMDOCE": numdoce,
            }
            headers.append(header)
            return header

        def insert_line(**kwargs):
            row = {
                "DMR_CENTRO": kwargs["centro"], "DMR_CODART": kwargs["codart"],
                "DMR_DESCRI": kwargs["descri"], "DMR_UNIMED": kwargs["unimed"],
                "DMR_CANTID": kwargs["cantidad"], "DMR_EJERCIO": kwargs.get("ejercio", 0),
                "DMR_SERIEO": kwargs.get("serieo", ""), "DMR_NUMDOCO": kwargs.get("numdoco", 0),
                "DMR_NUMLINO": kwargs.get("numlino", 0), "DMR_NUMLIN": len(db.output_lines) + 1,
            }
            if kwargs["centro"] == 2:
                db.output_lines.append(row)
            else:
                destination_lines.append(row)
            return row["DMR_NUMLIN"]

        svc._insert_cabdocr_header = insert_header
        svc._insert_detmovr_with_stock = insert_line
        svc._delete_cabdocr_document = lambda header: deleted.append(header)
        return svc, db, headers, destination_lines, deleted

    def test_tools_registered_native_only(self):
        core = faro_mcp.FaroToolRuntime()
        self.assertIn("stock_trasvasar", core.tools)
        self.assertIn("entrada_almacen_crear", core.tools)
        self.assertIn("orden_compra_cerrar", core.tools)
        self.assertNotIn("integracion_coinfer_stock", core.tools)
        self.assertEqual(len(core.tools), 87)
        self.assertFalse(any(name.startswith("datasnap_") for name in core.tools))
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "full"}):
            full = faro_mcp.FaroToolRuntime()
            defs = {x["name"] for x in faro_mcp.tool_definitions()}
        self.assertIn("stock_trasvasar", defs)
        self.assertIn("entrada_almacen_crear", defs)
        self.assertIn("orden_compra_cerrar", defs)
        self.assertIn("integracion_coinfer_stock", full.tools)
        self.assertIn("integracion_coinfer_stock", defs)

    def test_close_purchase_order_marks_lines_and_header_closed(self):
        db = PurchaseOrderCloseDb()
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.close_purchase_order("carlos", 0, 2026, "OC", 12)

        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        self.assertTrue(result["cerrada"])
        self.assertEqual(result["lineas_cerradas"], 2)
        self.assertEqual(result["situacion_anterior"], "P")
        self.assertEqual(result["situacion"], "C")
        self.assertEqual(len(db.executed), 3)
        self.assertTrue(all(item[0].startswith("UPDATE DETORC SET DOC_CIEMAN='S'") for item in db.executed[:2]))
        self.assertIn("UPDATE CABORC SET COC_SITUAC='C'", db.executed[2][0])
        self.assertEqual(db.executed[0][1][-1], 10)
        self.assertEqual(db.executed[1][1][-1], 20)
        self.assertEqual(db.executed[2][1][1], "carlos")

    def test_close_purchase_order_rejects_missing_header(self):
        db = PurchaseOrderCloseDb(exists=False)
        svc = faro_mcp.FaroPhase1Service(db)
        with self.assertRaises(faro_mcp.FaroError):
            svc.close_purchase_order("carlos", 0, 2026, "OC", 12)
        self.assertEqual(db.executed, [])
        self.assertEqual(db.commits, 0)

    def test_close_purchase_order_rolls_back_on_update_error(self):
        db = PurchaseOrderCloseDb(fail_execute=True)
        svc = faro_mcp.FaroPhase1Service(db)
        with self.assertRaises(RuntimeError):
            svc.close_purchase_order("carlos", 0, 2026, "OC", 12)
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)

    def test_transfer_creates_output_and_mirrored_input_with_opposite_sign(self):
        svc, db, headers, destination_lines, deleted = self._service(existing=False)
        result = svc.transfer_centers(2, 3, "A1|Articulo 1|2.5|UD#A2|Articulo 2|1|KG#")
        self.assertTrue(result["ok"])
        self.assertEqual(result["lines_added"], 2)
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        self.assertEqual(len(headers), 2)
        self.assertEqual(headers[0]["CBR_TIPO"], "S")
        self.assertEqual(headers[1]["CBR_TIPO"], "E")
        self.assertEqual([x["DMR_CANTID"] for x in db.output_lines], [Decimal("-2.5"), Decimal("-1")])
        self.assertEqual([x["DMR_CANTID"] for x in destination_lines], [Decimal("2.5"), Decimal("1")])
        # Correccion deliberada respecto al Delphi original: la entrada
        # espejo SI copia la unidad de medida real de la linea de salida.
        self.assertEqual([x["DMR_UNIMED"] for x in destination_lines], ["UD", "KG"])
        self.assertEqual(deleted, [])

    def test_transfer_fills_missing_description_and_unit_from_article(self):
        svc, db, headers, destination_lines, deleted = self._service(existing=False)
        result = svc.transfer_centers(2, 3, "A1||2.5|#")
        self.assertTrue(result["ok"])
        self.assertEqual(result["lines_added"], 1)
        self.assertEqual(db.output_lines[0]["DMR_DESCRI"], "Articulo A1")
        self.assertEqual(db.output_lines[0]["DMR_UNIMED"], "UD")

    def test_transfer_regenerates_previous_input_counterpart(self):
        svc, db, headers, destination_lines, deleted = self._service(existing=True)
        db.output_lines.append({
            "DMR_CODART": "OLD", "DMR_DESCRI": "Anterior", "DMR_UNIMED": "UD",
            "DMR_CANTID": Decimal("-4"), "DMR_EJERCIO": 0, "DMR_SERIEO": "",
            "DMR_NUMDOCO": 0, "DMR_NUMLINO": 0, "DMR_NUMLIN": 1,
        })
        result = svc.transfer_centers(2, 3, "NEW|Nueva|2|UD#")
        self.assertEqual(len(deleted), 1)
        self.assertEqual(deleted[0]["CBR_NUMDOC"], 77)
        self.assertEqual(len(headers), 1)  # solo se crea la nueva entrada espejo
        self.assertEqual(headers[0]["CBR_TIPO"], "E")
        self.assertEqual([x["DMR_CODART"] for x in destination_lines], ["OLD", "NEW"])
        self.assertEqual([x["DMR_CANTID"] for x in destination_lines], [Decimal("4"), Decimal("2")])
        self.assertEqual([x["DMR_UNIMED"] for x in destination_lines], ["UD", "UD"])
        self.assertTrue(result["input_document"]["regenerated"])

    def test_transfer_empty_text_matches_delphi_success_without_writes(self):
        svc, db, headers, destination_lines, deleted = self._service(existing=False)
        result = svc.transfer_centers(2, 3, "")
        self.assertTrue(result["ok"])
        self.assertFalse(result["updated"])
        self.assertEqual(db.commits, 0)
        self.assertEqual(headers, [])

    def test_purchase_entry_creates_cabdocm_detmovm_and_accumulates_stock(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.create_purchase_entry(
            {
                "centro": 7, "proveedor": 44, "fecha": "2026-09-15",
                "albaran": "ALB-1", "factura": "FAC-1", "portes": "2",
            },
            [{"articulo": "REF-A1", "descripcion": "Articulo uno", "cantidad": "3", "precio": "10", "iva": "21"}],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["documento"], {"centro": 7, "ejercicio": 2026, "serie": "EN", "numero": 101})
        self.assertEqual(result["lineas"], 1)
        self.assertEqual(result["articulos"][0]["articulo"], "A1")
        self.assertEqual(result["articulos"][0]["pedido"]["numero"], 9)
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        sql_text = "\n".join(sql for sql, _ in db.executed)
        self.assertIn("INSERT INTO CABDOCM", sql_text)
        self.assertIn("INSERT INTO DETMOVM", sql_text)
        self.assertIn("INSERT INTO ARTICULE", sql_text)
        self.assertIn("UPDATE CABDOCM SET", sql_text)

    def test_purchase_entry_uses_cif_when_provider_code_is_zero(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.create_purchase_entry(
            {"centro": 7, "proveedor": 0, "cif": "B44", "fecha": "2026-09-15"},
            [{"articulo": "REF-A1", "cantidad": "1"}],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["proveedor"], 44)
        self.assertTrue(any("PRO_CIF=?" in sql for sql, _ in db.provider_queries))

    def test_purchase_entry_internal_article_without_supplier_reference_still_updates_stock(self):
        db = PurchaseEntryDb(supplier_article=False)
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.create_purchase_entry(
            {"centro": 7, "proveedor": 44, "fecha": "2026-09-15"},
            [{"articulo": "814943103", "cantidad": "1", "precio": "1"}],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["articulos"][0]["articulo"], "814943103")
        self.assertEqual(result["articulos"][0]["tipo_linea"], "D")
        sql_text = "\n".join(sql for sql, _ in db.executed)
        self.assertIn("INSERT INTO ARTICULE", sql_text)

    def test_purchase_entry_public_contract_uses_structured_header_and_lines(self):
        translated = faro_mcp.translate_public_arguments("entrada_almacen_crear", {
            "cabecera": {"centro": 7, "proveedor": 44, "cif": ""},
            "lineas": [{"referencia_proveedor": "REF-A1", "cantidad": "2"}],
        })
        self.assertEqual(translated["cabecera"]["proveedor"], 44)
        self.assertEqual(translated["cabecera"]["cif"], "")
        self.assertEqual(translated["lineas"][0]["referencia_proveedor"], "REF-A1")

    def test_purchase_entry_public_contract_rejects_provider_name_lookup(self):
        with self.assertRaises(faro_mcp.FaroError):
            faro_mcp.translate_public_arguments("entrada_almacen_crear", {
                "cabecera": {"centro": 7, "proveedor": 0, "nombre_proveedor": "Proveedor 44"},
                "lineas": [{"referencia_proveedor": "REF-A1", "cantidad": "2"}],
            })

    def test_transfer_parser_stops_on_empty_datasnap_segment(self):
        svc, db, headers, destination_lines, deleted = self._service(existing=False)
        result = svc.transfer_centers(2, 3, " A1|Articulo|1|UD ##A2|Ignorada|5|UD#")
        self.assertEqual(result["lines_added"], 1)
        self.assertEqual([x["DMR_CODART"] for x in db.output_lines], ["A1"])

    def test_coinfer_stock_reads_third_semicolon_field(self):
        class CoinferDb:
            def __init__(self, path):
                self.settings = faro_mcp.Settings("odbc", "", "faro", "u", "p", 1, 7, "test")
                self.path = path
            def fetch_one(self, sql, params=()):
                if "FROM PARAMETROS" in sql.upper():
                    return {"PAR_VALOR": self.path}
                return None

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "Stocks.txt").write_text("000000001;IGNORAR;12,75;OTRO\n000000002;X;4\n", encoding="cp1252")
            svc = faro_mcp.FaroPhase1Service(CoinferDb(tmp))
            result = svc.coinfer_stock("000000001")
            self.assertTrue(result["found"])
            self.assertEqual(result["stock"], "12,75")
            self.assertEqual(result["datasnap_text"], "12,75")

    def test_coinfer_stock_returns_zero_for_invalid_code_or_missing_file(self):
        class CoinferDb:
            def __init__(self, path):
                self.settings = faro_mcp.Settings("odbc", "", "faro", "u", "p", 1, 7, "test")
                self.path = path
            def fetch_one(self, sql, params=()):
                return {"PAR_VALOR": self.path} if "FROM PARAMETROS" in sql.upper() else None

        svc = faro_mcp.FaroPhase1Service(CoinferDb("/path/that/does/not/exist"))
        self.assertEqual(svc.coinfer_stock("SHORT")["stock"], "0")
        missing = svc.coinfer_stock("000000001")
        self.assertFalse(missing["found"])
        self.assertEqual(missing["stock"], "0")


if __name__ == "__main__":
    unittest.main()
