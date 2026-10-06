import os
import tempfile
import os
import unittest
import base64
from unittest.mock import patch
from datetime import date
from decimal import Decimal
from pathlib import Path

import faro_mcp


def document_insert_value(db, column):
    for sql, params in db.executed:
        if sql.startswith("INSERT INTO DOCUMENTO"):
            columns = [item.strip() for item in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
            return params[columns.index(column)]
    raise AssertionError("No se encontro INSERT INTO DOCUMENTO")


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
        self.company = {
            "EMP_NOMEMP": "METALFIX",
            "EMP_NOMFIS": "METALFIX SUMINISTROS INDUSTRIALES SL",
            "EMP_CIF": "B98261795",
        }

    def fetch_one(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM EMPRES" in u:
            return dict(self.company)
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
        if "SELECT * FROM CABDOCM" in u:
            return {
                "CBM_NUMEMP": 1, "CBM_CENTRO": 7, "CBM_EJERCI": 2026,
                "CBM_SERIE": "EN", "CBM_NUMDOC": 101, "CBM_FECHA": date(2026, 9, 15),
                "CBM_CODPRO": 44, "CBM_NOMPRO": "Proveedor 44", "CBM_DOMICI": "Calle",
                "CBM_CODPOS": 46000, "CBM_POBLAC": "Valencia", "CBM_CIF": "B44",
                "CBM_CODPAG": 3, "CBM_ALBPRO": "ALB-77", "CBM_FACPRO": "FAC-77",
                "CBM_PORDTO": Decimal("0"), "CBM_IMPPOR": Decimal("2"),
                "CBM_TOTALS": Decimal("30"), "CBM_TOTALD": Decimal("38.30"),
                "CBM_SITUAC": "F",
            }
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
        self.assertIn("entrada_almacen_pdf_previsualizar", core.tools)
        self.assertIn("entrada_almacen_desde_pdf", core.tools)
        self.assertIn("entrada_almacen_imagen_previsualizar", core.tools)
        self.assertIn("entrada_almacen_desde_imagen", core.tools)
        self.assertIn("entrada_almacen_pendientes_integrar", core.tools)
        self.assertIn("orden_compra_cerrar", core.tools)
        self.assertNotIn("integracion_coinfer_stock", core.tools)
        self.assertEqual(len(core.tools), 92)
        self.assertFalse(any(name.startswith("datasnap_") for name in core.tools))
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "full"}):
            full = faro_mcp.FaroToolRuntime()
            defs = {x["name"] for x in faro_mcp.tool_definitions()}
        self.assertIn("stock_trasvasar", defs)
        self.assertIn("entrada_almacen_crear", defs)
        self.assertIn("entrada_almacen_pdf_previsualizar", defs)
        self.assertIn("entrada_almacen_desde_pdf", defs)
        self.assertIn("entrada_almacen_imagen_previsualizar", defs)
        self.assertIn("entrada_almacen_desde_imagen", defs)
        self.assertIn("entrada_almacen_pendientes_integrar", defs)
        self.assertIn("orden_compra_cerrar", defs)
        self.assertIn("integracion_coinfer_stock", full.tools)
        self.assertIn("integracion_coinfer_stock", defs)

    def test_create_purchase_entry_from_pdf_copies_to_documents_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "pendiente.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n% prueba\n")
            db = PurchaseEntryDb()
            db.settings.main_dir = tmp
            db.settings.documents_dir = "Documentos"
            svc = faro_mcp.FaroPhase1Service(db)
            svc.purchase_entry_pdf_proposal = lambda args: {
                "pdf": {"source": str(pdf_path)},
                "cabecera": {"proveedor": 44, "fecha": "2026-09-15"},
                "lineas": [{"articulo": "A1", "cantidad": "1", "precio": "8", "resuelto": True}],
                "advertencias": [],
                "validacion_fuentes": {},
            }
            svc.create_purchase_entry = lambda header, lines: {
                "documento": {"centro": 7, "ejercicio": 2026, "serie": "EA", "numero": 1526},
                "proveedor": 44,
                "totales": {"base": Decimal("8"), "total": Decimal("9.68")},
            }
            svc._save_purchase_entry_pdf_document = lambda args, result: {"ruta": str(Path(tmp) / "GestionDC" / "Compras" / "doc.pdf")}

            result = svc.create_purchase_entry_from_pdf({"ruta_pdf": str(pdf_path)})

            copied = Path(result["documentos_entradas"]["ruta"])
            self.assertEqual(copied.parent, Path(tmp) / "Documentos" / "Entradas")
            self.assertEqual(copied.name, "2026-EA-1526.pendiente.pdf")
            self.assertTrue(copied.exists())
            self.assertEqual(copied.read_bytes(), pdf_path.read_bytes())

    def test_integrate_pending_purchase_entry_pdfs_processes_and_copies_processed(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp) / "GestionDC" / "Pendientes"
            pending.mkdir(parents=True)
            pdf_path = pending / "ALB_TEST.pdf"
            pdf_bytes = b"%PDF-1.4\n% prueba\n"
            pdf_path.write_bytes(pdf_bytes)
            db = PurchaseEntryDb()
            db.settings.main_dir = tmp
            svc = faro_mcp.FaroPhase1Service(db)
            svc.purchase_entry_pdf_proposal = lambda args: {
                "cabecera": {"proveedor": 44, "albaran": "ALB-1", "factura": ""},
                "lineas": [{"articulo": "A1", "cantidad": "1", "precio": "8", "resuelto": True}],
            }
            svc._purchase_entry_existing_for_pdf_header = lambda header: None
            svc.create_purchase_entry_from_pdf = lambda args: {
                "documento": {"centro": 7, "ejercicio": 2026, "serie": "EN", "numero": 101},
                "gestion_documental": {"ruta": str(Path(tmp) / "GestionDC" / "Compras" / "doc.pdf")},
                "documentos_entradas": {"ruta": str(Path(tmp) / "Documentos" / "Entradas" / "doc.pdf")},
                "lineas_pdf_detectadas": 1,
            }

            result = svc.integrate_pending_purchase_entry_pdfs({})

            self.assertEqual(result["procesados_ok"], 1)
            self.assertEqual(result["errores"], 0)
            log_path = Path(result["log"])
            self.assertEqual(log_path.parent, Path(tmp) / "GestionDC" / "Logs")
            self.assertTrue(log_path.exists())
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("Inicio integracion", log_text)
            self.assertIn("Documento procesado entrada", log_text)
            self.assertIn("Fin integracion total=1 procesados_ok=1 documentados=0 omitidos=0 errores=0", log_text)
            processed = Path(result["documentos"][0]["procesados"]["ruta"])
            self.assertEqual(processed.parent, Path(tmp) / "GestionDC" / "Procesados")
            self.assertTrue(processed.exists())
            self.assertEqual(processed.read_bytes(), pdf_bytes)
            self.assertFalse(pdf_path.exists())
            self.assertTrue(result["documentos"][0]["pendiente_borrado"]["borrado"])

    def test_integrate_pending_purchase_entry_pdfs_skips_existing_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp) / "GestionDC" / "Pendientes"
            pending.mkdir(parents=True)
            duplicate = pending / "ALB_DUP.pdf"
            duplicate.write_bytes(b"%PDF-1.4\n% prueba\n")
            db = PurchaseEntryDb()
            db.settings.main_dir = tmp
            svc = faro_mcp.FaroPhase1Service(db)
            svc.purchase_entry_pdf_proposal = lambda args: {
                "cabecera": {"proveedor": 44, "albaran": "ALB-1", "factura": ""},
                "lineas": [],
            }
            svc._purchase_entry_existing_for_pdf_header = lambda header: {
                "CBM_CENTRO": 7, "CBM_EJERCI": 2026, "CBM_SERIE": "EN", "CBM_NUMDOC": 101,
            }
            svc.create_purchase_entry_from_pdf = lambda args: self.fail("No debe grabar duplicados")

            result = svc.integrate_pending_purchase_entry_pdfs({})

            self.assertEqual(result["procesados_ok"], 0)
            self.assertEqual(result["omitidos"], 1)
            self.assertEqual(result["documentos"][0]["estado"], "omitido")
            log_text = Path(result["log"]).read_text(encoding="utf-8")
            self.assertIn("Documento omitido ya dado de alta", log_text)
            self.assertIn("Fin integracion total=1 procesados_ok=0 documentados=0 omitidos=1 errores=0", log_text)
            self.assertFalse((Path(tmp) / "GestionDC" / "Procesados").exists())
            self.assertTrue(duplicate.exists())

    def test_integrate_pending_purchase_entry_pdfs_document_management_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp) / "GestionDC" / "Pendientes"
            pending.mkdir(parents=True)
            pdf_path = pending / "FAC_TEST.pdf"
            pdf_bytes = b"%PDF-1.4\n% prueba\n"
            pdf_path.write_bytes(pdf_bytes)
            db = PurchaseEntryDb()
            db.settings.main_dir = tmp
            svc = faro_mcp.FaroPhase1Service(db)
            svc.purchase_entry_pdf_proposal = lambda args: {
                "_texto_extraido_documento": (
                    "FACTURA DE PROVEEDOR Proveedor 44 CIF B44 FAC-1 REF-A1 Articulo uno "
                    "Base imponible 8 IVA 21 Total documento 9.68"
                ),
                "cabecera": {
                    "proveedor": 44,
                    "cif": "B44",
                    "factura": "FAC-1",
                    "albaran": "",
                    "fecha": "2026-09-15",
                    "fecha_factura": "2026-09-15",
                },
                "lineas": [{"articulo": "A1", "cantidad": "1", "precio": "8", "resuelto": True}],
            }
            svc.create_purchase_entry_from_pdf = lambda args: self.fail("No debe crear entrada de almacen")

            result = svc.integrate_pending_purchase_entry_pdfs({"solo_gestion_documental": True})

            self.assertEqual(result["procesados_ok"], 0)
            self.assertEqual(result["documentados"], 1)
            self.assertEqual(result["errores"], 0)
            document_path = Path(result["documentos"][0]["gestion_documental"]["ruta"])
            self.assertTrue(document_path.exists())
            self.assertEqual(document_path.read_bytes(), pdf_bytes)
            processed = Path(result["documentos"][0]["procesados"]["ruta"])
            self.assertEqual(processed.parent, Path(tmp) / "GestionDC" / "Procesados")
            self.assertTrue(processed.exists())
            self.assertEqual(processed.read_bytes(), pdf_bytes)
            self.assertFalse(pdf_path.exists())
            self.assertTrue(result["documentos"][0]["pendiente_borrado"]["borrado"])
            sql_text = "\n".join(sql for sql, _ in db.executed)
            self.assertIn("INSERT INTO DOCUMENTO", sql_text)
            self.assertNotIn("INSERT INTO CABDOCM", sql_text)
            keywords = document_insert_value(db, "DOC_KEYWORDS")
            self.assertIn("FACTURA DE PROVEEDOR", keywords)
            self.assertIn("REF-A1 Articulo uno", keywords)
            self.assertIn("Total documento 9.68", keywords)
            log_text = Path(result["log"]).read_text(encoding="utf-8")
            self.assertIn("Modo=SOLO_GESTION_DOCUMENTAL", log_text)
            self.assertIn("Documento guardado solo gestion documental", log_text)

    def test_document_management_only_updates_keywords_for_existing_document(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        proposal = {
            "_texto_extraido_documento": (
                "FACTURA DE PROVEEDOR CELESA CIF A48230650 "
                "1-25 BROCAS ANTISLIP INOX BC95B TOTAL FACTURA 2241.43"
            ),
            "cabecera": {
                "proveedor": 10012,
                "factura": "FAC-IMG-CELESA-260001",
                "fecha_factura": "2026-10-05",
            },
        }
        svc._document_management_existing_for_header = lambda header: {
            "DOC_ID": "60EA0A72-EC65-47C8-9D93-C582940856AD",
            "DOC_FICHERO": "Compras\\Facturas.Proveedor\\2026\\10\\doc.png",
        }

        result = svc._save_purchase_document_only(
            {"content_base64_imagen": "iVBORw0KGgo=", "nombre_fichero": "factura.png"},
            proposal,
        )

        self.assertTrue(result["existente"])
        self.assertTrue(result["palabras_clave"]["actualizado"])
        update_sql, update_params = next(item for item in db.executed if item[0].startswith("UPDATE DOCUMENTO SET DOC_KEYWORDS=?"))
        self.assertIn("FACTURA DE PROVEEDOR CELESA", update_params[0])
        self.assertIn("BROCAS ANTISLIP", update_params[0])
        self.assertIn("TOTAL FACTURA 2241.43", update_params[0])
        self.assertLessEqual(len(update_params[0]), 1024)

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

    def test_purchase_entry_pdf_preview_resolves_supplier_reference(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nAlbarán Nº ALB-77\n15/09/2026\nREF-A1 Articulo uno 3 10 21",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"proveedor": 44, "centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "FAC-77")
        self.assertEqual(result["cabecera"]["albaran"], "ALB-77")
        self.assertEqual(result["cabecera"]["fecha"], "2026-09-15")
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-15")
        self.assertEqual(result["lineas"][0]["referencia_proveedor"], "REF-A1")
        self.assertEqual(result["lineas"][0]["articulo"], "A1")
        self.assertTrue(result["lineas"][0]["resuelto"])
        self.assertIn("CABDOCM_UDM.pas", result["validacion_fuentes"]["cabecera_y_totales"])

    def test_purchase_entry_pdf_resolves_supplier_name_ignoring_metalfix_customer(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "ALONSO SALINAS,S.L.\n"
            "N.I.F. B44\n"
            "FACTURA 135-202601578\n"
            "Cliente 1826\n"
            "METALFIX SUMINISTROS INDUSTRIALES SL\n"
            "30/09/2026\n"
            "REF-A1 Articulo uno 3 10 21",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["proveedor"], 44)
        self.assertEqual(result["cabecera"]["nombre_proveedor"], "ALONSO SALINAS,S.L.")
        self.assertEqual(result["cabecera"]["cif"], "B44")
        self.assertEqual(result["lineas"][0]["articulo"], "A1")

    def test_purchase_entry_pdf_ignores_legacy_provider_faro_text_and_uses_cif(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            # Texto antiguo de PDFs de prueba: no debe usarse para resolver proveedor.
            "Proveedor Faro: 99999\n"
            "ALONSO SALINAS,S.L.\n"
            "N.I.F. B44\n"
            "METALFIX SUMINISTROS INDUSTRIALES SL\n"
            "Factura Nº FAC-77\n"
            "15/09/2026\n"
            "REF-A1 Articulo uno 3 10 21",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["proveedor"], 44)
        self.assertTrue(any("PRO_CIF=?" in sql for sql, _ in db.provider_queries))

    def test_purchase_entry_pdf_extracts_invoice_number_with_numero_marker(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "RALIZA S.L.\n"
            "METALFIX Suministros Industriales, S.L.U.\n"
            "C.I.F. B-98261795\n"
            "FACTURA Nº 36/26\n"
            "Paiporta a 30 de septiembre de 2026\n"
            "Factura de almacenamiento, preparacion de pedidos y recepcion de material.\n"
            "BASE IMPONIBLE 1370,00\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        svc._resolve_purchase_provider_by_name = lambda name: {
            "codpro": 77,
            "nompro": "RALIZA S.L.",
            "cif": "B98261795",
        }

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "36/26")
        self.assertEqual(result["cabecera"]["albaran"], "")
        self.assertEqual(result["cabecera"]["proveedor"], 77)
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-30")

    def test_purchase_entry_pdf_extracts_alonso_invoice_before_page_counter(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "ALONSO SALINAS,S.L.\n"
            "N.I.F. B97045959\n"
            "alonsosalinas.com ALONSO SALINAS,S.L.\n"
            "FACTURA\n"
            "UnidadesDescripcion Precio\n"
            "Articulo\n"
            "1826\n"
            "FACTURA\n"
            "Fecha 30/09/2026\n"
            "Cliente\n"
            "NIF.B98261795\n"
            "%IVA\n"
            "135-202601578\n"
            "TRANSFERENCIA BANCARIA 60 DIAS\n"
            "METALFIX SUMINISTROS INDUSTRIALES SL\n"
            "Albaran 135-202.604.484 de Fecha 17/09/2026\n"
            "IMPORTE FACTURA Eu 301,83\n"
            "Pagina 1/1",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "135-202601578")
        self.assertEqual(result["cabecera"]["albaran"], "135-202.604.484")
        self.assertEqual(result["cabecera"]["nombre_proveedor"], "ALONSO SALINAS,S.L.")
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-30")

    def test_purchase_entry_pdf_extracts_invoice_before_period_value(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "AIGUES DE L'HORTA S.A.\n"
            "N.I.F.:A96523329\n"
            "DATOS DE FACTURACION\n"
            "Num. factura 95452026A100031511\n"
            "Periodo 2026/03\n"
            "Fecha emision 21-09-2026\n"
            "METALFIX SUMINISTROS INDUSTRIALES, S.L.\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "95452026A100031511")
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-21")

    def test_purchase_entry_pdf_extracts_invoice_number_from_ocr_raliza_scan(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "RALIZA S.L. A lvnacenamwntcy METALFIX Suministros Industriales, S L U "
            "Av. Ovidi Montllor, 29 bajo 46960 Aldaya (Valencia) C.I.F.: B-98261795 "
            "FACTURA No Paiporta a 30 de septiembre de 2026 36/26 "
            "Factura de almacenamiento, preparacion de pedidos y recepcion de material",
            {"origen": "factura.pdf", "bytes": 1234, "extraccion": "ocr_pdf"},
        )
        svc._resolve_purchase_provider_by_name = lambda name: {
            "codpro": 77,
            "nompro": "RALIZA S.L.",
            "cif": "B96967906",
        }

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "36/26")
        self.assertEqual(result["cabecera"]["proveedor"], 77)
        self.assertEqual(result["cabecera"]["cif"], "B96967906")
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-30")

    def test_purchase_entry_pdf_uses_empres_to_ignore_customer_identity(self):
        db = PurchaseEntryDb()
        db.company = {
            "EMP_NOMEMP": "CLIENTE PROPIO",
            "EMP_NOMFIS": "CLIENTE PROPIO INDUSTRIAL SL",
            "EMP_CIF": "B11111111",
        }
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "PROVEEDOR REAL S.L.\n"
            "CLIENTE PROPIO INDUSTRIAL SL\n"
            "C.I.F.: B11111111\n"
            "Factura Nº 25/77\n"
            "30/09/2026\n"
            "REF-A1 Articulo uno 3 10 21",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        svc._resolve_purchase_provider_by_name = lambda name: {
            "codpro": 77,
            "nompro": "PROVEEDOR REAL S.L.",
            "cif": "B22222222",
        }

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["nombre_proveedor"], "PROVEEDOR REAL S.L.")
        self.assertEqual(result["cabecera"]["proveedor"], 77)
        self.assertEqual(result["cabecera"]["cif"], "B22222222")

    def test_purchase_entry_pdf_extracts_invoice_number_from_redur_table_header(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "LOZANO TRANSPORTES, S.A.U.\n"
            "METALFIX SUMINISTROS INDUST. S.L.U.\n"
            "CIF: A50113380\n"
            "FECHA FACTURA Nº FACTURA FORMA PAGO VENCIMIENTO\n"
            "15/09/2026 VAL/26J/000344 RECIBO DOMICILIADO 15/10/2026\n"
            "FECHA EXPEDICION S/REFERENCIA CONCEPTO KG VALOR UN. IMPORTE\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        svc._resolve_purchase_provider_by_name = lambda name: {
            "codpro": 50228,
            "nompro": "LOZANO TRANSPORTES S.A.U",
            "cif": "A50113380",
        }

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "VAL/26J/000344")
        self.assertEqual(result["cabecera"]["proveedor"], 50228)
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-15")

    def test_purchase_entry_pdf_extracts_invoice_number_from_redur_codigo_cliente_table(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "LOZANO TRANSPORTES, S.A.U.\n"
            "CODIGO CLIENTE FACTURA NUMERO FECHA FORMA DE PAGO FFECHA VTO.\n"
            "METALFIX VAL/26A/003227 30/09/2026 RECIBO DOMICILIADO 30/10/2026\n"
            "FECHA CONCEPTO VALOR\n"
            "30/09/2026 SERVICIOS REALIZADOS DEL 0108 AL 3009 GRUPO 1 126,26\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        svc._resolve_purchase_provider_by_name = lambda name: {
            "codpro": 50228,
            "nompro": "LOZANO TRANSPORTES S.A.U",
            "cif": "A50113380",
        }

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "VAL/26A/003227")
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-30")

    def test_purchase_entry_pdf_extracts_invoice_from_client_invoice_date_nif_row(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "loginsert\n"
            "METALFIX SUMINISTROS INDUSTRIALES, S.L.U.\n"
            "Cliente: Factura: Fecha: N.I.F.: 7681 26/4685 30/09/2026 B98261795\n"
            "CONCEPTO SERVICIOS PAQUETERIA SEPTIEMBRE 2026\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        svc._resolve_purchase_provider_by_name = lambda name: {
            "codpro": 88,
            "nompro": "LOGINSER",
            "cif": "B00000000",
        }

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "26/4685")
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-30")

    def test_purchase_entry_pdf_extracts_invoice_after_fecha_label(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "illusion Studio S.L.\n"
            "METALFIX SUMINISTROS INDUSTRIALES S.L.U.\n"
            "Factura Fecha: 05/09/2026 F26652 DESCRIPCION CANTIDAD PRECIO TOTAL\n"
            "SEO mensual 10,00 40,00 400,00\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        svc._resolve_purchase_provider_by_name = lambda name: {
            "codpro": 99,
            "nompro": "ILLUSION STUDIO S.L.",
            "cif": "B98740913",
        }

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "F26652")
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-05")

    def test_purchase_entry_pdf_extracts_invoice_from_fecha_factura_header_row(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "illusion Studio S.L.\n"
            "B98740913\n"
            "Cliente\n"
            "METALFIX SUMINISTROS INDUSTRIALES SLU\n"
            "Factura\n"
            "Fecha: Factura:\n"
            "05/09/2026 F26652\n"
            "DESCRIPCION CANTIDAD PRECIO TOTAL\n"
            "SEO mensual 10.00 40,00 400,00\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        svc._resolve_purchase_provider_by_name = lambda name: {
            "codpro": 99,
            "nompro": "ILLUSION STUDIO S.L.",
            "cif": "B98740913",
        }

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "F26652")
        self.assertEqual(result["cabecera"]["albaran"], "")
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-05")

    def test_purchase_entry_pdf_keeps_invoice_suffix_after_spaced_slash(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "SERVICIOS INTEGRALES ALBORACHE, S.L.U.\n"
            "Factura Nº SL2026 / 1369\n"
            "Fecha: 30-09-2026\n"
            "METALFIX SUMINISTROS INDUSTRIALES S.L.U.\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        svc._resolve_purchase_provider_by_name = lambda name: {
            "codpro": 91,
            "nompro": "SERVICIOS INTEGRALES ALBORACHE",
            "cif": "B98597156",
        }

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "SL2026/1369")
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-30")

    def test_purchase_entry_pdf_uses_explicit_num_factura_over_title(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "FACTURA POR CUOTA - CONTRATO DE ARRENDAMIENTO OPERATIVO\n"
            "30/09/2026 0744 B0S020\n"
            "BANCO SANTANDER, S.A. CIF A-39000013\n"
            "NUM. CONTRATO : B0S020\n"
            "NUM. FACTURA : 28653694 (DUPLICADO)\n"
            "METALFIX SUMINISTROS INDUSTRIAL\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "28653694")
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-30")

    def test_purchase_entry_pdf_uses_num_factura_over_billing_period(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "FACTURA DE ELECTRICIDAD\n"
            "IBERDROLA CLIENTES, S.A.U. CIF A-95758389\n"
            "PERIODO DE FACTURACION: 31/07/2026 - 31/08/2026 Nº FACTURA: 21260903010147586\n"
            "RESUMEN DE FACTURA\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "21260903010147586")
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-07-31")

    def test_purchase_entry_from_pdf_reuses_validated_entry_creation(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        extracted_text = (
            "CIF: B44\nFactura Nº FAC-77\nAlbarán Nº ALB-77\n15/09/2026\n"
            "REF-A1 Articulo uno 3 10 21\nBase imponible 30\nIVA 21 6.30\nTOTAL FACTURA 36.30"
        )
        with tempfile.TemporaryDirectory() as tmp:
            svc.settings.main_dir = tmp
            pdf = Path(tmp) / "factura.pdf"
            pdf.write_bytes(b"%PDF-1.4\n% test\n")
            svc._purchase_entry_pdf_text = lambda args: (
                extracted_text,
                {"origen": str(pdf), "bytes": pdf.stat().st_size},
            )

            result = svc.create_purchase_entry_from_pdf({"proveedor": 44, "centro": 7, "ruta_pdf": str(pdf)})

            document = result["gestion_documental"]
            document_path = Path(document["ruta"])
            self.assertTrue(document_path.exists())
            self.assertEqual(document_path.read_bytes(), pdf.read_bytes())

        self.assertTrue(result["ok"])
        self.assertEqual(result["documento"], {"centro": 7, "ejercicio": 2026, "serie": "EN", "numero": 101})
        self.assertEqual(result["lineas_pdf_detectadas"], 1)
        self.assertEqual(result["articulos"][0]["articulo"], "A1")
        self.assertEqual(db.commits, 2)
        self.assertEqual(document["subtipo"], "Facturas.Proveedor")
        self.assertIn("Compras\\Facturas.Proveedor\\2026\\9\\", document["fichero"])
        sql_text = "\n".join(sql for sql, _ in db.executed)
        self.assertIn("INSERT INTO DOCUMENTO", sql_text)
        keywords = document_insert_value(db, "DOC_KEYWORDS")
        self.assertIn("Factura Nº FAC-77", keywords)
        self.assertIn("REF-A1 Articulo uno", keywords)
        self.assertIn("TOTAL FACTURA 36.30", keywords)
        self.assertLessEqual(len(keywords), 1024)
        cabdocm_insert = next(params for sql, params in db.executed if sql.startswith("INSERT INTO CABDOCM"))
        self.assertEqual(cabdocm_insert[16], date(2026, 9, 15))

    def test_purchase_entry_from_pdf_writes_base64_pdf_to_document_management(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nAlbarán Nº ALB-77\n15/09/2026\nREF-A1 Articulo uno 3 10 21",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        with tempfile.TemporaryDirectory() as tmp:
            svc.settings.main_dir = tmp
            encoded = "JVBERi0xLjQKJSB0ZXN0Cg=="

            result = svc.create_purchase_entry_from_pdf({
                "proveedor": 44,
                "centro": 7,
                "content_base64": encoded,
                "nombre_fichero": "factura.pdf",
            })

            self.assertTrue(Path(result["gestion_documental"]["ruta"]).exists())
            self.assertEqual(Path(result["gestion_documental"]["ruta"]).read_bytes(), b"%PDF-1.4\n% test\n")

    def test_purchase_entry_from_image_uses_extracted_text_and_preserves_extension(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lGg7qwAAAABJRU5ErkJggg=="
        )
        with tempfile.TemporaryDirectory() as tmp:
            svc.settings.main_dir = tmp
            image = Path(tmp) / "albaran.png"
            image.write_bytes(png_bytes)
            svc._cabdocm_for_document = lambda documento: {
                "CBM_FECHA": date(2026, 9, 15),
                "CBM_CODPRO": 44,
                "CBM_ALBPRO": "ALB-77",
                "CBM_FACPRO": "",
            }

            result = svc.create_purchase_entry_from_pdf({
                "proveedor": 44,
                "centro": 7,
                "ruta_imagen": str(image),
                "texto_extraido": "CIF: B44\nAlbaran No: ALB-77\n15/09/2026\nREF-A1 Articulo uno 3 10 21",
            })

            gd_path = Path(result["gestion_documental"]["ruta"])
            entries_path = Path(result["documentos_entradas"]["ruta"])
            self.assertEqual(result["gestion_documental"]["subtipo"], "Albaranes.Proveedor")
            self.assertIn("Compras\\Albaranes.Proveedor\\2026\\9\\", result["gestion_documental"]["fichero"])
            self.assertEqual(gd_path.suffix, ".png")
            self.assertEqual(entries_path.suffix, ".png")
            self.assertEqual(gd_path.read_bytes(), png_bytes)
            self.assertEqual(entries_path.read_bytes(), png_bytes)

    def test_purchase_entry_ocr_command_handles_empty_streams_in_error(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        with patch.dict(os.environ, {"FARO_OCR_COMMAND": "cmd /c exit 7"}):
            with self.assertRaisesRegex(faro_mcp.FaroError, "FARO_OCR_COMMAND fallo: 7"):
                svc._extract_purchase_entry_image_text(b"not-image", "scan.png")

    def test_purchase_entry_from_pdf_requires_review_for_unresolved_lines(self):
        db = PurchaseEntryDb(supplier_article=False)
        svc = faro_mcp.FaroPhase1Service(db)
        svc._internal_article_for_entry = lambda codart: None
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\n15/09/2026\nREF-NO Existe 3 10 21",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        with self.assertRaises(faro_mcp.FaroError):
            svc.create_purchase_entry_from_pdf({"proveedor": 44, "centro": 7})
        self.assertEqual(db.commits, 0)

    def test_purchase_entry_from_pdf_stops_with_missing_provider_before_articles(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B999\nFactura Nº FAC-77\n15/09/2026\nREF-A1 Articulo uno 3 10 21",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        with self.assertRaisesRegex(faro_mcp.FaroError, "Proveedor no encontrado"):
            svc.create_purchase_entry_from_pdf({"centro": 7})
        self.assertEqual(db.commits, 0)
        self.assertFalse(any(sql.startswith("INSERT INTO CABDOCM") for sql, _ in db.executed))

    def test_purchase_entry_from_pdf_can_continue_with_ghost_line_when_article_missing(self):
        db = PurchaseEntryDb(supplier_article=False)
        svc = faro_mcp.FaroPhase1Service(db)
        svc._internal_article_for_entry = lambda codart: None
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\n15/09/2026\nREF-NO Articulo fantasma 3 10 21",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        with tempfile.TemporaryDirectory() as tmp:
            svc.settings.main_dir = tmp
            encoded = "JVBERi0xLjQKJSB0ZXN0Cg=="

            result = svc.create_purchase_entry_from_pdf({
                "proveedor": 44,
                "centro": 7,
                "content_base64": encoded,
                "nombre_fichero": "factura.pdf",
                "politica_articulo_no_encontrado": "fantasma",
            })

        self.assertTrue(result["ok"])
        self.assertEqual(result["articulos"][0]["tipo_linea"], "X")
        self.assertEqual(result["incidencias_articulos"][0]["referencia"], "REF-NO")
        self.assertTrue(result["incidencias_articulos"][0]["linea_fantasma"])

    def test_purchase_entry_from_pdf_can_update_supplier_purchase_price(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\n15/09/2026\nREF-A1 Articulo uno 3 10 21",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        with tempfile.TemporaryDirectory() as tmp:
            svc.settings.main_dir = tmp
            encoded = "JVBERi0xLjQKJSB0ZXN0Cg=="

            result = svc.create_purchase_entry_from_pdf({
                "proveedor": 44,
                "centro": 7,
                "content_base64": encoded,
                "nombre_fichero": "factura.pdf",
                "politica_precio_compra": "actualizar",
            })

        self.assertEqual(result["cambios_precio_compra"][0]["articulo"], "A1")
        self.assertEqual(result["cambios_precio_compra"][0]["precio_anterior"], "8")
        self.assertEqual(result["cambios_precio_compra"][0]["precio_nuevo"], "10")
        self.assertTrue(result["cambios_precio_compra"][0]["actualizado"])
        self.assertTrue(any(sql.startswith("UPDATE ARTICULP SET ARTP_PREBAS=?") for sql, _ in db.executed))

    def test_purchase_entry_from_pdf_updates_supplier_purchase_price_only_if_rises(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\n15/09/2026\nREF-A1 Articulo uno 3 7 21",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        with tempfile.TemporaryDirectory() as tmp:
            svc.settings.main_dir = tmp
            encoded = "JVBERi0xLjQKJSB0ZXN0Cg=="

            result = svc.create_purchase_entry_from_pdf({
                "proveedor": 44,
                "centro": 7,
                "content_base64": encoded,
                "nombre_fichero": "factura.pdf",
                "politica_precio_compra": "actualizar_si_sube",
            })

        self.assertFalse(result["cambios_precio_compra"][0]["actualizado"])
        self.assertEqual(result["cambios_precio_compra"][0]["motivo"], "precio_no_sube")
        self.assertFalse(any(sql.startswith("UPDATE ARTICULP SET ARTP_PREBAS=?") for sql, _ in db.executed))

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
