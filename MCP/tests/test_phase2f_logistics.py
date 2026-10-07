import os
import tempfile
import re
import weakref
import sys
import unittest
import base64
import hashlib
import json
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
        temporary = tempfile.mkdtemp(prefix="faro-test-")
        import shutil
        weakref.finalize(self, shutil.rmtree, temporary, True)
        self.settings.main_dir = temporary
        self.supplier_article = supplier_article
        self.executed = []
        self.provider_queries = []
        self.fetch_all_calls = []
        self.detmovm_lines = []
        self.commits = 0
        self.rollbacks = 0
        self.importation_row = None
        self.existing_entry_document = None
        self.company = {
            "EMP_NOMEMP": "METALFIX",
            "EMP_NOMFIS": "METALFIX SUMINISTROS INDUSTRIALES SL",
            "EMP_CIF": "B98261795",
        }

    def fetch_one(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM GDC_IMPORTACION" in u:
            if "COUNT(*)" in u:
                return {"TOTAL": int(self.importation_row is not None)}
            if self.importation_row and "GDI_HASH=?" in u and params[-1] != self.importation_row.get("GDI_HASH"):
                return None
            return dict(self.importation_row) if self.importation_row else None
        if "FROM DOCUMENTO" in u and "DOC_IDKRONOS" in u:
            return dict(self.existing_entry_document) if self.existing_entry_document else None
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
        self.fetch_all_calls.append((sql, params))
        u = " ".join(sql.upper().split())
        if "FROM PROVEE" in u:
            row = self.fetch_one(sql, params)
            return [row] if row else []
        if "FROM GDC_IMPORTACION" in u and self.importation_row:
            return [dict(self.importation_row)]
        return []

    def execute(self, sql, params=()):
        normalized_sql = " ".join(sql.split())
        self.executed.append((normalized_sql, params))
        if normalized_sql.startswith("INSERT INTO GDC_IMPORTACION ("):
            columns = normalized_sql.split("(", 1)[1].split(")", 1)[0].split(",")
            self.importation_row = dict(zip((column.strip() for column in columns), params))
        if normalized_sql.startswith("UPDATE GDC_IMPORTACION SET") and self.importation_row:
            assignments = normalized_sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
            values = iter(params)
            for column, expression in re.findall(r"(GDI_\w+)\s*=\s*(\?|'[^']*')", assignments):
                self.importation_row[column] = next(values) if expression == "?" else expression.strip("'")
        if normalized_sql.startswith("DELETE FROM GDC_IMPORTACION") and self.importation_row:
            self.importation_row = None
        if normalized_sql.startswith("INSERT INTO DETMOVM"):
            self.detmovm_lines.append(params)

    def execute_affected(self, sql, params=()):
        row = self.importation_row
        if not row:
            return 0
        before, where = sql.upper().split(" WHERE ", 1)
        values = iter(params[before.count("?"):])
        for column in re.findall(r"(GDI_\w+)\s*=\s*\?", where):
            if row.get(column) != next(values):
                return 0
        for column, value in re.findall(r"(GDI_\w+)\s*=\s*'([^']*)'", where):
            if row.get(column) != value:
                return 0
        if "GDI_ESTADO IN ('PROPUESTA', 'REVISADA')" in where and row.get("GDI_ESTADO") not in {"PROPUESTA", "REVISADA"}:
            return 0
        self.execute(sql, params)
        return 1

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
    def _pdf_base64(self, pages):
        from io import BytesIO
        from reportlab.pdfgen import canvas

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer)
        for text in pages:
            if text:
                pdf.drawString(40, 780, text)
            pdf.showPage()
        pdf.save()
        return base64.b64encode(buffer.getvalue()).decode("ascii")

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
        self.assertIn("entrada_almacen_propuesta_confirmar", core.tools)
        self.assertIn("entrada_almacen_propuesta_borrar", core.tools)
        self.assertIn("entrada_almacen_propuesta_guardar", core.tools)
        self.assertIn("entrada_almacen_propuesta_reintentar_documento", core.tools)
        self.assertIn("entrada_almacen_propuestas_listar", core.tools)
        self.assertIn("orden_compra_cerrar", core.tools)
        self.assertNotIn("integracion_coinfer_stock", core.tools)
        self.assertEqual(len(core.tools), 99)
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
        self.assertIn("entrada_almacen_propuesta_confirmar", defs)
        self.assertIn("entrada_almacen_propuesta_borrar", defs)
        self.assertIn("entrada_almacen_propuesta_guardar", defs)
        self.assertIn("entrada_almacen_propuesta_reintentar_documento", defs)
        self.assertIn("entrada_almacen_propuestas_listar", defs)
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
                "hash_sha256": hashlib.sha256(Path(args["ruta_pdf"]).read_bytes()).hexdigest(),
                "pdf": {"origen": args["ruta_pdf"]},
                "totales": {"source_gross": "9.68"},
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
            svc._save_purchase_entry_pdf_document = lambda args, result, **kwargs: {"ruta": str(Path(tmp) / "GestionDC" / "Compras" / "doc.pdf")}

            result = svc.create_purchase_entry_from_pdf({"ruta_pdf": str(pdf_path)})

            copied = Path(result["documentos_entradas"]["ruta"])
            self.assertEqual(copied.parent, Path(tmp) / "Documentos" / "Entradas")
            self.assertEqual(copied.name, "2026-EN-101.pendiente.pdf")
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
                "hash_sha256": hashlib.sha256(Path(args["ruta_pdf"]).read_bytes()).hexdigest(),
                "pdf": {"origen": args["ruta_pdf"]},
                "totales": {"source_gross": "9.68"},
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

    def test_integrate_pending_purchase_entry_keeps_success_when_pending_delete_fails(self):
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
                "hash_sha256": hashlib.sha256(Path(args["ruta_pdf"]).read_bytes()).hexdigest(),
                "pdf": {"origen": args["ruta_pdf"]},
                "totales": {"source_gross": "9.68"},
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
            svc._delete_pending_document = lambda path: (_ for _ in ()).throw(PermissionError("[WinError 32] archivo en uso"))

            result = svc.integrate_pending_purchase_entry_pdfs({})

            self.assertEqual(result["procesados_ok"], 1)
            self.assertEqual(result["errores"], 0)
            document = result["documentos"][0]
            self.assertEqual(document["estado"], "procesado")
            self.assertEqual(document["entrada"], {"centro": 7, "ejercicio": 2026, "serie": "EN", "numero": 101})
            self.assertFalse(document["pendiente_borrado"]["borrado"])
            self.assertIn("WinError 32", document["pendiente_borrado"]["error"])
            self.assertTrue(pdf_path.exists())
            self.assertIn("Documento pendiente no borrado", Path(result["log"]).read_text(encoding="utf-8"))

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
                "hash_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                "pdf": {"origen": str(pdf_path)},
                "_texto_extraido_documento": (
                    "FACTURA DE PROVEEDOR Proveedor 44 CIF B44 FAC-1 REF-A1 Articulo uno "
                    "Base imponible 8 IVA 21 Total documento 9.68"
                ),
                "cabecera": {
                    "solo_gestion_documental": True,
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
            "CIF: B44\nFactura Nº FAC-77\nAlbarán Nº ALB-77\n15/09/2026\nREF-A1 Articulo uno 3 10 21\nTOTAL FACTURA 36.30",
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

    def test_purchase_entry_pdf_preview_extracts_standard_table_with_percent_columns(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura: ST-2026-1007-002\nAlbaran: ALB-ST-26042\n"
            "Ref. proveedor Articulo Descripcion Cant. Precio Dto. Base IVA Importe\n"
            "0-90-948 0-90-948 LLAVE AJUSTABLE STANLEY 5 9,31 0% 46,55 21% 56,33\n"
            "BIMATERIAL 200MM\n"
            "1-17-754 1-17-754 CORTAVARILLAS MANGO TUBULAR 1 79,00 36% 50,56 21% 61,18\n"
            "900MM / 36\"\n"
            "Base imponible 97,11\nIVA 21% 20,40\nTOTAL FACTURA 117,51",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"proveedor": 44, "centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "ST-2026-1007-002")
        self.assertEqual([line["referencia_proveedor"] for line in result["lineas"]], ["0-90-948", "1-17-754"])
        self.assertEqual(result["lineas"][0]["descripcion"], "LLAVE AJUSTABLE STANLEY BIMATERIAL 200MM")
        self.assertEqual(result["lineas"][1]["descripcion"], "CORTAVARILLAS MANGO TUBULAR 900MM / 36\"")
        self.assertEqual(result["lineas"][0]["importe_origen"], "46.55")
        self.assertEqual(result["lineas"][1]["descuento1"], "36")
        self.assertTrue(result["validacion"]["total_reconciled"])
        self.assertFalse(result["validacion"]["no_lines_detected"])

    def test_purchase_entry_pdf_preview_resolves_internal_article_code_without_supplier_reference(self):
        db = PurchaseEntryDb(supplier_article=False)
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\n15/09/2026\n814943103 Articulo interno 3 10 21",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"proveedor": 44, "centro": 7})

        self.assertEqual(result["lineas"][0]["referencia_proveedor"], "814943103")
        self.assertEqual(result["lineas"][0]["articulo"], "814943103")
        self.assertTrue(result["lineas"][0]["resuelto"])
        self.assertNotIn("unresolved_article", result["advertencias"])

    def test_purchase_entry_pdf_preview_resolves_ean_without_supplier_reference(self):
        db = PurchaseEntryDb(supplier_article=False)
        svc = faro_mcp.FaroPhase1Service(db)
        svc.barcode_article = lambda text: "A1" if text == "8412345678901" else None
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\n15/09/2026\n8412345678901 Articulo por ean 3 10 21",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"proveedor": 44, "centro": 7})

        self.assertEqual(result["lineas"][0]["referencia_proveedor"], "8412345678901")
        self.assertEqual(result["lineas"][0]["articulo"], "A1")
        self.assertTrue(result["lineas"][0]["resuelto"])
        self.assertNotIn("unresolved_article", result["advertencias"])

    def test_purchase_entry_pdf_preview_ignores_payment_footer_in_layout_text(self):
        db = PurchaseEntryDb(supplier_article=False)
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "ARTICULO DESCRIPCION CANTIDAD PRECIO %DTO. IMPORTE\n"
            "1282D55 CERRADURA EMBUT.N 2000 55X30 TESA 1 37,5000 37,50\n"
            "Forma Pago: PAGARE 180 DIAS F/FTRA. CCC ES98 0049 1861 11 2010070072",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"proveedor": 44, "centro": 7})

        self.assertEqual(len(result["lineas"]), 1)
        self.assertEqual(result["lineas"][0]["referencia_proveedor"], "1282D55")
        self.assertEqual(result["lineas"][0]["articulo"], "1282D55")
        self.assertEqual(result["lineas"][0]["cantidad"], "1")
        self.assertEqual(result["lineas"][0]["precio"], "37.5000")
        self.assertNotIn("unresolved_article", result["advertencias"])

    def test_purchase_entry_pdf_preview_extracts_faren_columnar_ocr_rows(self):
        db = PurchaseEntryDb(supplier_article=False)
        original_fetch = db.fetch_one
        def faren_provider(sql, params=()):
            row = original_fetch(sql, params)
            if row and "FROM PROVEE" in sql.upper():
                row["PRO_CIF"] = "A25142488"
            return row
        db.fetch_one = faren_provider
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "BANCO CODIGO IGE500SP 977003 TARIC COD. NOMBRE DEL ARTICULO UDAD "
            "3403198000 3208201090 3402901000 CANTIDAD 6 30 36 BULTOS 5 "
            "PRECIO UDAD 11, 65 2,25 2,85 GF503 GRASA COJINETES RAL 3000 ROJO VIVO WELD "
            "AUTORIZACION 6721478 A25142488 40% PESO TOTAL 28 IMPORTE 41,9 67,5 102,6 "
            "TOTAL FACTURA EUR 256,57",
            {"origen": "faren.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"proveedor": 44, "centro": 7})

        self.assertEqual(len(result["lineas"]), 3)
        self.assertEqual([line["referencia_proveedor"] for line in result["lineas"]], ["1GE500SP", "3208201090", "977003"])
        self.assertEqual([line["descripcion"] for line in result["lineas"]], ["GF503 GRASA COJINETES", "RAL 3000 ROJO VIVO", "WELD"])
        self.assertEqual([line["cantidad"] for line in result["lineas"]], ["6", "30", "36"])
        self.assertEqual(result["lineas"][0]["descuento1"], "40")
        self.assertFalse(result["validacion"]["no_lines_detected"])
        self.assertEqual(result["totales"]["computed_gross"], "256.57")
        self.assertTrue(result["totales"]["reconciled"])

    def test_purchase_entry_pdf_preview_ignores_iban_and_preserves_layout_order(self):
        db = PurchaseEntryDb(supplier_article=False)
        svc = faro_mcp.FaroPhase1Service(db)
        svc._internal_article_for_entry = lambda codart: None if codart == "62794" else {
            "ART_CODART": codart,
            "ART_DESCRI": f"Articulo {codart}",
            "ART_UNIMED": "UD",
        }
        svc._purchase_entry_pdf_text = lambda args: (
            "FACTURA\n"
            "TRANSFERENCIA BANCARIA 60 DIAS\n"
            "ES42 2100 4337 8302 0008 5262\n"
            "Art�culo Descripci�n Unidades Precio Dto %IVA Importe\n"
            "37741 ARCHIVADOR JASPEADO FOLIO SIN RADO LIDERPA 10,00 2,01 21,00 20,10\n"
            "Sociedad DSG26401516 C.250 SOBRES ADHES. PACKING-LIST 240x140 (ext.) 3,00 19,18 21,00 57,54\n"
            "62794 BOLIGRAFO BIC CRISTAL FUN TURQUESA PUNTA 1 20,00 0,39 21,00 7,80\n"
            "1�, 33669 PIZ.BLANCA LAC. MAG MARCO ALUM 150X100 CM Q- 1,00 145,01 21,00 145,01\n"
            "Base Imponible 249,45\n"
            "IVA 21,00% 249,45 52,38\n"
            "IMPORTE FACTURA Eu 301,83",
            {"origen": "alonso.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"proveedor": 44, "centro": 7})

        refs = [line["referencia_proveedor"] for line in result["lineas"]]
        self.assertNotIn("ES42", refs)
        self.assertEqual(refs, ["37741", "DSG26401516", "62794", "33669"])
        self.assertEqual(result["lineas"][0]["cantidad"], "10.00")
        self.assertEqual(result["lineas"][1]["precio"], "19.18")
        self.assertEqual(result["lineas"][3]["importe_origen"], "145.01")
        self.assertEqual(result["validacion"]["unresolved_lines"], 1)
        # The fixture's four lines sum to 230.45, not the printed base 249.45.
        # A printed total must never hide a missing or misread line.
        self.assertEqual(result["lineas"][2]["cantidad"], "20.00")
        self.assertEqual(result["lineas"][2]["precio"], "0.39")
        self.assertFalse(result["totales"]["reconciled"])
        self.assertEqual(result["totales"]["computed_gross"], "278.84")

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
            "REF-A1 Articulo uno 3 10 21\nTOTAL FACTURA 36.30",
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
            "REF-A1 Articulo uno 3 10 21\nTOTAL FACTURA 36.30",
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
            "REF-A1 Articulo uno 3 10 21\nTOTAL FACTURA 36.30",
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

    def test_purchase_entry_pdf_uses_second_tax_id_when_first_is_own_company(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "METALFIX SUMINISTROS INDUSTRIALES SL CIF B98261795\n"
            "Proveedor sin sufijo comercial\n"
            "CIF: B44\n"
            "Factura Nº FAC-77\n"
            "Fecha factura: 15/09/2026\n"
            "REF-A1 Articulo uno 3 10 21\nTOTAL FACTURA 36.30",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["proveedor"], 44)
        self.assertEqual(result["cabecera"]["cif"], "B44")
        self.assertTrue(any("PRO_CIF=?" in sql and params[1] == "B44" for sql, params in db.provider_queries))

    def test_purchase_entry_pdf_prefers_lucemar_supplier_block_over_customer_header(self):
        db = PurchaseEntryDb()
        original_fetch_one = db.fetch_one

        def fetch_one(sql, params=()):
            u = " ".join(sql.upper().split())
            if "FROM PROVEE" in u and "PRO_CIF=?" in u and str(params[1]) == "B98151020":
                return {
                    "PRO_CODPRO": 50233,
                    "PRO_NOMCOR": "SERVICIOS INTEGRALES LUCEMAR",
                    "PRO_CIF": "B98151020",
                    "PRO_DOMICI": "C/ MAESTRO CHAPI, 6",
                    "PRO_CODPOS": 46200,
                    "PRO_POBLAC": "PATERNA",
                    "PRO_CODPAG": 0,
                }
            return original_fetch_one(sql, params)

        db.fetch_one = fetch_one
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "ROVER INFRAESTRUCTURAS S.A.\n"
            "BOTANICO CAVANILLES -28\n"
            "46010 VALENCIA\n"
            "CIF:\n"
            "A281116072026-FA-3\n"
            "Fecha\n"
            "17/01/2026\n"
            "DESCRIPCION CANTIDADARTICULO IMPORTE\n"
            "Factura Cod.Cliente\n"
            "%DTO.PRECIO\n"
            " \n"
            "12345678\n"
            "SERVICIOS INTEGRALES LUCEMAR\n"
            "S.L.C/ MAESTRO CHAPI, 6\n"
            "46200\n"
            "96.312.43.22\n"
            "B98151020\n"
            "administracion@lucemar.com\n"
            "CIF:\n"
            "E-MAIL:\n"
            "PATERNA\n"
            "SERVICIOS INTEGRALES LUCEMAR S.L.\n"
            "TELF:\n"
            "--- Albaran: 2025-AL-9839 de 01/12/2025 ---\n"
            "JUNTA DIL. JD1 ALUM. 15 X 12,5 MM GOMA GRIS 2.268,006500100049 18,9000120\n",
            {"origen": "F-2026-FA-3.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["cif_candidatos"], ["A28111607", "B98151020"])
        self.assertEqual(result["cabecera"]["nombre_proveedor"], "SERVICIOS INTEGRALES LUCEMAR S.L.")
        self.assertEqual(result["cabecera"]["proveedor"], 50233)
        self.assertEqual(result["cabecera"]["cif"], "B98151020")

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

    def test_purchase_entry_pdf_parses_redur_transport_lines_with_glued_amounts(self):
        db = PurchaseEntryDb(supplier_article=False)
        svc = faro_mcp.FaroPhase1Service(db)
        svc._internal_article_for_entry = lambda code: None
        svc._purchase_entry_pdf_text = lambda args: (
            "LOZANO TRANSPORTES, S.A.U.\n"
            "METALFIX SUMINISTROS INDUST. S.L.U.\n"
            "CIF: ESA50113380\n"
            "FECHA FACTURA Nº FACTURA\n"
            "15/09/2026 VAL/26I/000344\n"
            "FECHA EXPEDICION S/REFERENCIA CONCEPTO KG VALOR UN. IMPORTE\n"
            "11/09/2026 962059648 10325 MERCANCIA FUERA DE NORMA 345 61,4661,46\n"
            "13,19 % CARGO COMBUSTIBLE IMP. CARGO 8,11\n"
            "BASE EXENTA BASE IMPONIBLE IVA TOTAL PAGAR EUROS\n"
            "0,00 69,57\n"
            "21%\n"
            "14,61 84,18\n",
            {"origen": "factura.pdf", "bytes": 1234, "page_count": 2},
        )
        svc._resolve_purchase_provider_by_name = lambda name: {
            "codpro": 50228,
            "nompro": "LOZANO TRANSPORTES S.A.U",
            "cif": "A50113380",
        }

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "VAL/26I/000344")
        self.assertEqual(len(result["lineas"]), 2)
        self.assertEqual(result["lineas"][0]["referencia_proveedor"], "10325")
        self.assertEqual(result["lineas"][0]["importe_origen"], "61.46")
        self.assertEqual(result["lineas"][1]["referencia_proveedor"], "CARGO_COMBUSTIBLE")
        self.assertEqual(result["totales"]["computed_gross"], "84.18")
        self.assertIsNone(result["totales"]["reconciled"])
        self.assertFalse(result["validacion"]["can_create_entry"])
        self.assertEqual(result["validacion"]["unresolved_lines"], 2)
        self.assertIn("unresolved_article", result["advertencias"])
        incidents = svc._purchase_entry_pdf_review_incidents(result)
        self.assertEqual(incidents[0]["codigo"], "unresolved_article")
        self.assertIn("Articulos no encontrados", incidents[0]["mensaje"])
        self.assertEqual(incidents[0]["referencias"], ["10325", "CARGO_COMBUSTIBLE"])

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
        self.assertNotIn("fecha_factura", result["cabecera"])
        self.assertIn("fecha_factura_no_detectada", result["advertencias"])

    def test_purchase_entry_pdf_prefers_invoice_date_over_due_date(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "Vencimiento: 30/10/2026\nFecha factura: 30/09/2026\nFactura Nº F-2026-15\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"centro": 7})

        self.assertEqual(result["cabecera"]["factura"], "F-2026-15")
        self.assertEqual(result["cabecera"]["fecha_factura"], "2026-09-30")

    def test_purchase_entry_pdf_parses_discount_tax_and_amount_columns(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\n"
            "REF-A1 Tornillo 10 2,50 10 21 22,50\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"proveedor": 44, "centro": 7})

        self.assertEqual(result["lineas"][0]["cantidad"], "10")
        self.assertEqual(result["lineas"][0]["precio"], "2.50")
        self.assertEqual(result["lineas"][0]["descuento1"], "10")
        self.assertEqual(result["lineas"][0]["iva"], "21")
        self.assertEqual(result["lineas"][0]["importe_origen"], "22.50")

    def test_purchase_entry_pdf_parses_tax_and_amount_without_discount_column(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\n"
            "REF-A1 Tornillo 3 10 21 30\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"proveedor": 44, "centro": 7})

        self.assertEqual(result["lineas"][0]["cantidad"], "3")
        self.assertEqual(result["lineas"][0]["precio"], "10")
        self.assertEqual(Decimal(result["lineas"][0]["descuento1"]), 0)
        self.assertEqual(result["lineas"][0]["iva"], "21")
        self.assertEqual(result["lineas"][0]["importe_origen"], "30")

    def test_purchase_entry_pdf_number_parser_handles_us_and_thousands_formats(self):
        parse = faro_mcp.FaroPhase1Service._parse_pdf_number

        self.assertEqual(parse("1,234.56"), Decimal("1234.56"))
        self.assertEqual(parse("1.234,56"), Decimal("1234.56"))
        self.assertEqual(parse("1.000"), Decimal("1000"))
        self.assertEqual(parse("1,000"), Decimal("1000"))

    def test_purchase_entry_pdf_reconciles_detected_total(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\n"
            "REF-A1 Tornillo 10 2,50 10 21 22,50\n"
            "BASE IMPONIBLE 22,50\nIVA 21 4,73\nTOTAL FACTURA 27,23\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        result = svc.purchase_entry_pdf_proposal({"proveedor": 44, "centro": 7})

        self.assertTrue(result["totales"]["reconciled"])
        self.assertEqual(result["totales"]["source_gross"], "27.23")
        self.assertEqual(result["totales"]["computed_gross"], "27.23")
        self.assertTrue(result["validacion"]["can_create_entry"])

    def test_purchase_entry_from_pdf_blocks_total_mismatch_before_writes(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\n"
            "REF-A1 Articulo uno 1 10 21\n"
            "TOTAL FACTURA 19,36\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        with self.assertRaisesRegex(faro_mcp.FaroError, "no cuadra"):
            svc.create_purchase_entry_from_pdf({"proveedor": 44, "centro": 7})

        self.assertEqual(db.commits, 0)
        self.assertFalse(any(sql.startswith("INSERT INTO CABDOCM") for sql, _ in db.executed))

    def test_purchase_entry_from_pdf_blocks_existing_entry_before_writes(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\n"
            "REF-A1 Articulo uno 1 10 21\nTOTAL FACTURA 12.10\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        svc._purchase_entry_existing_for_pdf_header = lambda header: {
            "CBM_CENTRO": 7,
            "CBM_EJERCI": 2026,
            "CBM_SERIE": "EN",
            "CBM_NUMDOC": 101,
        }

        with self.assertRaisesRegex(faro_mcp.FaroError, "ya dado de alta"):
            svc.create_purchase_entry_from_pdf({"proveedor": 44, "centro": 7})

        self.assertEqual(db.commits, 0)
        self.assertFalse(any(sql.startswith("INSERT INTO CABDOCM") for sql, _ in db.executed))

    def test_integrate_pending_purchase_entry_pdfs_reports_review_state(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        with tempfile.TemporaryDirectory() as tmp:
            svc.settings.main_dir = tmp
            pending = Path(tmp) / "GestionDC" / "Pendientes"
            pending.mkdir(parents=True)
            (pending / "factura.pdf").write_bytes(b"%PDF-1.4\n% test\n")

            result = svc.integrate_pending_purchase_entry_pdfs({
                "texto_extraido": (
                    "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\n"
                    "REF-A1 Articulo uno 1 10 21\nTOTAL FACTURA 19,36\n"
                )
            })

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["procesados_ok"], 0)
        self.assertEqual(result["requiere_revision"], 1)
        self.assertEqual(result["errores"], 0)
        self.assertEqual(result["documentos"][0]["estado"], "requiere_revision")
        self.assertFalse(result["documentos"][0]["validacion"]["total_reconciled"])
        self.assertEqual(result["documentos"][0]["incidencias_revision"][0]["codigo"], "total_mismatch")
        self.assertIn("El total calculado no cuadra", result["documentos"][0]["motivo"])
        self.assertEqual(db.commits, 0)
        self.assertFalse(any(sql.startswith("INSERT INTO CABDOCM") for sql, _ in db.executed))

    def test_integrate_pending_purchase_entry_pdfs_persists_review_proposal(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        with tempfile.TemporaryDirectory() as tmp:
            svc.settings.main_dir = tmp
            pending = Path(tmp) / "GestionDC" / "Pendientes"
            pending.mkdir(parents=True)
            (pending / "factura.pdf").write_bytes(b"%PDF-1.4\n% test\n")

            result = svc.integrate_pending_purchase_entry_pdfs({
                "persistir_propuesta": True,
                "texto_extraido": (
                    "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\n"
                    "REF-A1 Articulo uno 1 10 21\nTOTAL FACTURA 19,36\n"
                ),
            })

        self.assertEqual(result["documentos"][0]["estado"], "requiere_revision")
        self.assertTrue(result["documentos"][0]["importacion"]["persistida"])
        self.assertFalse(any(sql.startswith("INSERT INTO CABDOCM") for sql, _ in db.executed))
        self.assertTrue(any(sql.startswith("INSERT INTO GDC_IMPORTACION") for sql, _ in db.executed))

    def test_integrate_pending_purchase_entry_pdfs_filters_selected_names_without_moving_others(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        with tempfile.TemporaryDirectory() as tmp:
            svc.settings.main_dir = tmp
            pending = Path(tmp) / "GestionDC" / "Pendientes"
            pending.mkdir(parents=True)
            selected = pending / "FAC_SELECTED.pdf"
            unselected = pending / "FAC_OTHER.pdf"
            selected.write_bytes(b"%PDF-1.4\n% selected\n")
            unselected.write_bytes(b"%PDF-1.4\n% other\n")
            seen = []

            def proposal(args):
                seen.append(Path(str(args.get("ruta_pdf"))).name)
                return {
                    "hash_sha256": hashlib.sha256(Path(args["ruta_pdf"]).read_bytes()).hexdigest(),
                    "pdf": {"origen": args["ruta_pdf"]},
                    "totales": {"source_gross": "9.68"},
                    "cabecera": {"proveedor": 44, "albaran": "ALB-1", "factura": ""},
                    "lineas": [{"articulo": "A1", "cantidad": "1", "precio": "8", "resuelto": True}],
                }

            svc.purchase_entry_pdf_proposal = proposal
            svc._purchase_entry_existing_for_pdf_header = lambda header: None
            svc.create_purchase_entry_from_pdf = lambda args: {
                "documento": {"centro": 7, "ejercicio": 2026, "serie": "EN", "numero": 101},
                "gestion_documental": {"ruta": str(Path(tmp) / "GestionDC" / "Compras" / "doc.pdf")},
                "documentos_entradas": {"ruta": str(Path(tmp) / "Documentos" / "Entradas" / "doc.pdf")},
                "lineas_pdf_detectadas": 1,
            }

            result = svc.integrate_pending_purchase_entry_pdfs({"selected_names": ["FAC_SELECTED.pdf"]})

            self.assertEqual(seen, ["FAC_SELECTED.pdf"])
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["procesados_ok"], 1)
            self.assertFalse(selected.exists())
            self.assertTrue(unselected.exists())

    def test_purchase_entry_pdf_adds_ocr_for_mixed_native_and_image_pages(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        encoded = self._pdf_base64(["Factura Nº FAC-77\nFecha factura: 15/09/2026", ""])
        calls = []

        def fake_ocr(data, source):
            calls.append(source)
            return "CIF: B44\nREF-A1 Articulo uno 3 10 21"

        svc._extract_purchase_entry_pdf_ocr_text = fake_ocr

        result = svc.purchase_entry_pdf_proposal({
            "proveedor": 44,
            "centro": 7,
            "content_base64": encoded,
            "nombre_fichero": "mixto.pdf",
        })

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["pdf"]["page_count"], 2)
        self.assertEqual(result["pdf"]["extraccion"], "texto_pdf+ocr_pdf")
        self.assertEqual(result["pdf"]["evidence"]["detail_pages"], [1])
        self.assertGreaterEqual(result["pdf"]["evidence"]["detail_signal_count"], 1)
        self.assertTrue(result["validacion"]["pages_complete"])
        self.assertEqual(result["lineas"][0]["articulo"], "A1")

    def test_purchase_entry_pdf_layout_groups_pymupdf_words_into_rows(self):
        class FakeRect:
            width = 595
            height = 842

        class FakePage:
            rect = FakeRect()

            def get_text(self, mode):
                return [
                    (40, 100, 80, 110, "REF-A1", 0, 0, 0),
                    (100, 101, 160, 111, "Articulo", 0, 0, 1),
                    (170, 101, 190, 111, "1", 0, 0, 2),
                    (220, 101, 250, 111, "10", 0, 0, 3),
                    (280, 101, 300, 111, "21", 0, 0, 4),
                    (40, 140, 80, 150, "TOTAL", 0, 1, 0),
                    (90, 140, 130, 150, "12.10", 0, 1, 1),
                ]

        class FakeDoc:
            def __iter__(self):
                return iter([FakePage()])

            def close(self):
                pass

        class FakePymupdf:
            @staticmethod
            def open(stream, filetype):
                return FakeDoc()

        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        with patch.dict(sys.modules, {"pymupdf": FakePymupdf}):
            layout = svc._extract_purchase_entry_pdf_layout(b"%PDF")

        self.assertEqual(layout["engine"], "pymupdf")
        self.assertEqual(layout["page_count"], 1)
        self.assertEqual(layout["pages"][0]["row_count"], 2)
        self.assertEqual(layout["pages"][0]["rows"][0]["text"], "REF-A1 Articulo 1 10 21")

    def test_purchase_entry_pdf_uses_pymupdf_layout_as_detail_fallback(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        encoded = self._pdf_base64(["Factura Nº FAC-77\nFecha factura: 15/09/2026"])
        svc._extract_purchase_entry_pdf_layout = lambda data: {
            "engine": "pymupdf",
            "page_count": 1,
            "pages": [{
                "page": 1,
                "width": "595",
                "height": "842",
                "word_count": 5,
                "row_count": 1,
                "rows": [{"text": "REF-A1 Articulo uno 1 10 21"}],
            }],
        }

        with patch.dict(os.environ, {"FARO_PDF_NATIVE_TEXT_MIN_CHARS": "0"}):
            result = svc.purchase_entry_pdf_proposal({
                "proveedor": 44,
                "centro": 7,
                "content_base64": encoded,
                "nombre_fichero": "layout.pdf",
            })

        self.assertIn("pymupdf_layout", result["pdf"]["extraccion"])
        self.assertEqual(result["pdf"]["layout"]["engine"], "pymupdf")
        self.assertEqual(result["pdf"]["evidence"]["detail_pages"], [1])
        self.assertEqual(result["lineas"][0]["articulo"], "A1")

    def test_purchase_entry_pdf_requires_review_when_no_lines_are_detected(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.purchase_entry_pdf_proposal({
            "proveedor": 44,
            "centro": 7,
            "texto_extraido": "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\nTOTAL FACTURA 36.30",
            "nombre_fichero": "sin_lineas.pdf",
        })

        self.assertTrue(result["validacion"]["no_lines_detected"])
        self.assertFalse(result["validacion"]["can_create_entry"])
        self.assertIn("no_lines_detected", result["advertencias"])
        self.assertEqual(result["pdf"]["evidence"]["total_pages"], [1])

    def test_purchase_entry_from_pdf_blocks_when_no_lines_are_detected(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\nTOTAL FACTURA 36.30",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        with self.assertRaisesRegex(faro_mcp.FaroError, "No se han detectado lineas"):
            svc.create_purchase_entry_from_pdf({"proveedor": 44, "centro": 7})

        self.assertEqual(db.commits, 0)
        self.assertFalse(any(sql.startswith("INSERT INTO CABDOCM") for sql, _ in db.executed))

    def test_purchase_entry_from_pdf_blocks_when_mixed_ocr_fails(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        encoded = self._pdf_base64(["Factura Nº FAC-77\nFecha factura: 15/09/2026", ""])
        svc._extract_purchase_entry_pdf_ocr_text = lambda data, source: (_ for _ in ()).throw(faro_mcp.FaroError("OCR roto"))

        with self.assertRaisesRegex(faro_mcp.FaroError, "no cubrio todas las paginas"):
            svc.create_purchase_entry_from_pdf({
                "proveedor": 44,
                "centro": 7,
                "content_base64": encoded,
                "nombre_fichero": "mixto.pdf",
            })

        self.assertEqual(db.commits, 0)
        self.assertFalse(any(sql.startswith("INSERT INTO CABDOCM") for sql, _ in db.executed))

    def test_purchase_entry_pdf_marks_page_limit_incomplete(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        encoded = self._pdf_base64(["", "", "", "", "", ""])
        svc._extract_purchase_entry_pdf_ocr_text = (
            lambda data, source: "CIF: B44\nFactura Nº FAC-77\nREF-A1 Articulo uno 1 10 21"
        )

        result = svc.purchase_entry_pdf_proposal({
            "proveedor": 44,
            "centro": 7,
            "content_base64": encoded,
            "nombre_fichero": "seis_paginas.pdf",
        })

        self.assertEqual(result["pdf"]["page_count"], 6)
        self.assertEqual(result["pdf"]["processed_pages"], [1, 2, 3, 4, 5])
        self.assertTrue(result["pdf"]["page_limit_reached"])
        self.assertFalse(result["validacion"]["pages_complete"])
        self.assertFalse(result["validacion"]["can_create_entry"])

    def test_purchase_entry_from_pdf_blocks_when_line_limit_reached(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\n"
            "REF-A1 Articulo uno 1 10 21\n"
            "REF-A2 Articulo dos 2 3 21\n",
            {"origen": "factura.pdf", "bytes": 1234},
        )

        with self.assertRaisesRegex(faro_mcp.FaroError, "limite de lineas"):
            svc.create_purchase_entry_from_pdf({"proveedor": 44, "centro": 7, "limite_lineas": 1})
        self.assertEqual(db.commits, 0)
        self.assertFalse(any(sql.startswith("INSERT INTO CABDOCM") for sql, _ in db.executed))

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

    def test_purchase_entry_from_pdf_uses_manual_article_over_printed_reference(self):
        db = PurchaseEntryDb(supplier_article=False)
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\n"
            "ERRONEA Articulo corregido 2 5 21\nTOTAL FACTURA 12.10",
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
                "lineas": [{
                    "referencia_proveedor": "ERRONEA",
                    "articulo": "A1",
                    "descripcion": "Articulo corregido",
                    "cantidad": "2",
                    "precio": "5",
                    "iva": "21",
                    "resuelto": True,
                    "article_selection": "manual",
                }],
            })

        self.assertTrue(result["ok"])
        self.assertEqual(result["articulos"][0]["articulo"], "A1")
        detmovm_insert = next(params for sql, params in db.executed if sql.startswith("INSERT INTO DETMOVM"))
        self.assertEqual(detmovm_insert[8], "A1")
        self.assertEqual(detmovm_insert[9], "ERRONEA")

    def test_purchase_entry_pdf_proposal_can_be_persisted_with_hash_and_version(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\n"
            "REF-A1 Articulo uno 3 10 21\nTOTAL FACTURA 36.30",
            {"origen": "factura.pdf", "bytes": 1234},
        )
        encoded = "JVBERi0xLjQKJSB0ZXN0Cg=="

        proposal = svc.purchase_entry_pdf_proposal({
            "content_base64": encoded,
            "nombre_fichero": "factura.pdf",
            "persistir_propuesta": True,
        })

        self.assertEqual(proposal["version"], 1)
        self.assertEqual(proposal["hash_sha256"], hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest())
        self.assertTrue(proposal["importacion"]["persistida"])
        insert_sql, insert_params = next(item for item in db.executed if item[0].startswith("INSERT INTO GDC_IMPORTACION"))
        columns = [item.strip() for item in insert_sql.split("(", 1)[1].split(")", 1)[0].split(",")]
        self.assertEqual(insert_params[columns.index("GDI_VERSION")], 1)
        self.assertEqual(insert_params[columns.index("GDI_HASH")], proposal["hash_sha256"])
        self.assertIn('"factura": "FAC-77"', insert_params[columns.index("GDI_PROPUESTA")])
        self.assertFalse(any(sql.startswith("INSERT INTO CABDOCM") for sql, _ in db.executed))

    def test_purchase_entry_importation_confirm_uses_saved_proposal_without_reextracting_pdf(self):
        db = PurchaseEntryDb()
        proposal = {
            "version": 1,
            "hash_sha256": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "cabecera": {
                "centro": 7,
                "proveedor": 44,
                "cif": "B44",
                "factura": "FAC-77",
                "fecha": "2026-09-15",
                "fecha_factura": "2026-09-15",
            },
            "totales": {"source_gross": "36.30"},
            "lineas": [{
                "referencia_proveedor": "REF-A1",
                "descripcion": "Articulo uno",
                "cantidad": "3",
                "precio": "10",
                "iva": "21",
                "resuelto": True,
                "articulo": "A1",
            }],
            "validacion": {"can_create_entry": True},
        }
        db.importation_row = {
            "GDI_ID": "IMP-1",
            "GDI_NUMEMP": 1,
            "GDI_ESTADO": "PROPUESTA",
            "GDI_VERSION": 1,
            "GDI_HASH": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "GDI_PROPUESTA": json.dumps(proposal),
        }
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (_ for _ in ()).throw(AssertionError("no debe reextraer PDF"))

        result = svc.confirm_purchase_entry_importation({
            "content_base64": "JVBERi0xLjQKJSB0ZXN0Cg==", "nombre_fichero": "factura.pdf",
            "propuesta_id": "IMP-1",
            "version": 1,
            "hash_sha256": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
        })

        self.assertTrue(result["ok"])
        self.assertEqual(result["importacion"]["estado"], "CONFIRMADA")
        self.assertEqual(result["documento"], {"centro": 7, "ejercicio": 2026, "serie": "EN", "numero": 101})
        sql_text = "\n".join(sql for sql, _ in db.executed)
        self.assertIn("INSERT INTO CABDOCM", sql_text)
        self.assertIn("INSERT INTO DETMOVM", sql_text)
        self.assertIn("UPDATE GDC_IMPORTACION SET GDI_ESTADO=?", sql_text)
        self.assertEqual(db.commits, 1)

    def test_purchase_entry_importation_confirm_archives_source_when_provided(self):
        db = PurchaseEntryDb()
        proposal = {
            "version": 1,
            "hash_sha256": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "cabecera": {
                "centro": 7,
                "proveedor": 44,
                "cif": "B44",
                "factura": "FAC-77",
                "fecha": "2026-09-15",
                "fecha_factura": "2026-09-15",
            },
            "totales": {"source_gross": "36.30"},
            "lineas": [{
                "referencia_proveedor": "REF-A1",
                "descripcion": "Articulo uno",
                "cantidad": "3",
                "precio": "10",
                "iva": "21",
                "resuelto": True,
                "articulo": "A1",
            }],
            "validacion": {"can_create_entry": True},
        }
        db.importation_row = {
            "GDI_ID": "IMP-1",
            "GDI_NUMEMP": 1,
            "GDI_ESTADO": "PROPUESTA",
            "GDI_VERSION": 1,
            "GDI_HASH": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "GDI_ORIGEN": "factura.pdf",
            "GDI_PROPUESTA": json.dumps(proposal),
        }
        svc = faro_mcp.FaroPhase1Service(db)
        with tempfile.TemporaryDirectory() as tmp:
            svc.settings.main_dir = tmp
            result = svc.confirm_purchase_entry_importation({
                "propuesta_id": "IMP-1",
                "version": 1,
                "hash_sha256": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
                "content_base64": "JVBERi0xLjQKJSB0ZXN0Cg==",
                "nombre_fichero": "factura.pdf",
            })

            self.assertTrue(Path(result["gestion_documental"]["ruta"]).exists())
            self.assertTrue(Path(result["documentos_entradas"]["ruta"]).exists())
        self.assertIn("INSERT INTO DOCUMENTO", "\n".join(sql for sql, _ in db.executed))
        self.assertEqual(db.commits, 1)

    def test_purchase_entry_importation_confirm_allows_ghost_lines_after_user_confirmation(self):
        db = PurchaseEntryDb(supplier_article=False)
        proposal = {
            "version": 1,
            "hash_sha256": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "cabecera": {
                "centro": 7,
                "proveedor": 44,
                "cif": "B44",
                "factura": "FAC-77",
                "fecha": "2026-09-15",
                "fecha_factura": "2026-09-15",
            },
            "totales": {"source_gross": "36.30"},
            "lineas": [{
                "referencia_proveedor": "REF-NO",
                "descripcion": "Articulo fantasma",
                "cantidad": "3",
                "precio": "10",
                "iva": "21",
                "resuelto": False,
            }],
            "validacion": {
                "can_create_entry": False,
                "unresolved_lines": 1,
                "pages_complete": True,
                "total_reconciled": True,
                "no_lines_detected": False,
            },
        }
        db.importation_row = {
            "GDI_ID": "IMP-1",
            "GDI_NUMEMP": 1,
            "GDI_ESTADO": "REVISADA",
            "GDI_VERSION": 1,
            "GDI_HASH": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "GDI_PROPUESTA": json.dumps(proposal),
        }
        svc = faro_mcp.FaroPhase1Service(db)
        svc._internal_article_for_entry = lambda codart: None

        result = svc.confirm_purchase_entry_importation({
            "content_base64": "JVBERi0xLjQKJSB0ZXN0Cg==", "nombre_fichero": "factura.pdf",
            "propuesta_id": "IMP-1",
            "version": 1,
            "hash_sha256": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "cabecera": {"politica_articulo_no_encontrado": "fantasma"},
            "lineas": proposal["lineas"],
        })

        self.assertTrue(result["ok"])
        self.assertEqual(result["articulos"][0]["tipo_linea"], "X")
        self.assertEqual(result["incidencias_articulos"][0]["referencia"], "REF-NO")
        self.assertTrue(result["incidencias_articulos"][0]["linea_fantasma"])
        self.assertEqual(result["importacion"]["estado"], "CONFIRMADA")

    def test_purchase_entry_importation_confirm_rejects_hash_mismatch_before_writes(self):
        db = PurchaseEntryDb()
        db.importation_row = {
            "GDI_ID": "IMP-1",
            "GDI_NUMEMP": 1,
            "GDI_ESTADO": "PROPUESTA",
            "GDI_VERSION": 1,
            "GDI_HASH": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "GDI_PROPUESTA": json.dumps({
                "cabecera": {"centro": 7, "proveedor": 44, "factura": "FAC-77"},
                "lineas": [{"referencia_proveedor": "REF-A1", "cantidad": "1"}],
                "validacion": {"can_create_entry": True},
            }),
        }
        svc = faro_mcp.FaroPhase1Service(db)

        with self.assertRaisesRegex(faro_mcp.FaroError, "hash"):
            svc.confirm_purchase_entry_importation({
                "propuesta_id": "IMP-1",
                "version": 1,
                "hash_sha256": "distinto",
            })

        self.assertFalse(any(sql.startswith("INSERT INTO CABDOCM") for sql, _ in db.executed))
        self.assertEqual(db.commits, 0)

    def test_purchase_entry_importation_revision_increments_version_and_reconciles(self):
        db = PurchaseEntryDb()
        proposal = {
            "version": 1,
            "hash_sha256": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "cabecera": {"centro": 7, "proveedor": 44, "factura": "FAC-77", "fecha": "2026-09-15"},
            "lineas": [{"referencia_proveedor": "REF-A1", "descripcion": "Articulo uno", "cantidad": "1", "precio": "10", "iva": "21"}],
            "totales": {"source_gross": "24.20"},
            "validacion": {"can_create_entry": False, "total_reconciled": False, "pages_complete": True},
            "advertencias": ["total_mismatch"],
        }
        db.importation_row = {
            "GDI_ID": "IMP-1",
            "GDI_NUMEMP": 1,
            "GDI_ESTADO": "PROPUESTA",
            "GDI_VERSION": 1,
            "GDI_HASH": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "GDI_PROPUESTA": json.dumps(proposal),
        }
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.save_purchase_entry_importation_revision({
            "propuesta_id": "IMP-1",
            "version": 1,
            "hash_sha256": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "lineas": [{
                "referencia_proveedor": "REF-A1",
                "descripcion": "Articulo uno",
                "cantidad": "2",
                "precio": "10",
                "iva": "21",
                "articulo": "A1",
                "resuelto": True,
            }],
        })

        self.assertTrue(result["ok"])
        self.assertEqual(result["importacion"]["version"], 2)
        self.assertTrue(result["validacion"]["can_create_entry"])
        self.assertEqual(result["totales"]["computed_gross"], "24.20")
        self.assertEqual(db.importation_row["GDI_VERSION"], 2)
        saved = json.loads(db.importation_row["GDI_PROPUESTA"])
        self.assertEqual(saved["version"], 2)
        self.assertEqual(saved["lineas"][0]["cantidad"], "2")

    def test_purchase_entry_importation_revision_rejects_stale_version(self):
        db = PurchaseEntryDb()
        db.importation_row = {
            "GDI_ID": "IMP-1",
            "GDI_NUMEMP": 1,
            "GDI_ESTADO": "REVISADA",
            "GDI_VERSION": 2,
            "GDI_HASH": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "GDI_PROPUESTA": json.dumps({"cabecera": {}, "lineas": [], "validacion": {}}),
        }
        svc = faro_mcp.FaroPhase1Service(db)

        with self.assertRaisesRegex(faro_mcp.FaroError, "version"):
            svc.save_purchase_entry_importation_revision({
                "propuesta_id": "IMP-1",
                "version": 1,
                "hash_sha256": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
                "cabecera": {"factura": "FAC-NEW"},
            })

        self.assertFalse(any(sql.startswith("UPDATE GDC_IMPORTACION") for sql, _ in db.executed))

    def test_purchase_entry_importation_delete_removes_unconfirmed_revision(self):
        db = PurchaseEntryDb()
        db.importation_row = {
            "GDI_ID": "IMP-1",
            "GDI_NUMEMP": 1,
            "GDI_ESTADO": "REVISADA",
            "GDI_VERSION": 2,
            "GDI_HASH": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "GDI_PROPUESTA": json.dumps({"cabecera": {}, "lineas": []}),
        }
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.delete_purchase_entry_importation_revision({
            "propuesta_id": "IMP-1",
            "version": 2,
            "hash_sha256": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
        })

        self.assertTrue(result["ok"])
        self.assertTrue(result["borrada"])
        self.assertIsNone(db.importation_row)
        self.assertTrue(any(sql.startswith("DELETE FROM GDC_IMPORTACION") for sql, _ in db.executed))
        self.assertEqual(db.commits, 1)

    def test_purchase_entry_importation_delete_rejects_confirmed_revision(self):
        db = PurchaseEntryDb()
        db.importation_row = {
            "GDI_ID": "IMP-1",
            "GDI_NUMEMP": 1,
            "GDI_ESTADO": "CONFIRMADA",
            "GDI_VERSION": 2,
            "GDI_HASH": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "GDI_PROPUESTA": json.dumps({"cabecera": {}, "lineas": []}),
        }
        svc = faro_mcp.FaroPhase1Service(db)

        with self.assertRaisesRegex(faro_mcp.FaroError, "confirmada"):
            svc.delete_purchase_entry_importation_revision({
                "propuesta_id": "IMP-1",
                "version": 2,
                "hash_sha256": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            })

        self.assertFalse(any(sql.startswith("DELETE FROM GDC_IMPORTACION") for sql, _ in db.executed))

    def test_purchase_entry_importations_list_returns_saved_review_payload(self):
        db = PurchaseEntryDb()
        proposal = {
            "cabecera": {"centro": 7, "proveedor": 44, "factura": "FAC-77"},
            "lineas": [{"referencia_proveedor": "REF-A1", "cantidad": "1"}],
            "totales": {"source_gross": "12.10", "computed_gross": "12.10", "reconciled": True},
            "validacion": {"can_create_entry": True},
            "advertencias": [],
            "pdf": {"origen": "factura.pdf"},
        }
        db.importation_row = {
            "GDI_ID": "IMP-1",
            "GDI_NUMEMP": 1,
            "GDI_CENTRO": 7,
            "GDI_ESTADO": "REVISADA",
            "GDI_VERSION": 2,
            "GDI_HASH": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "GDI_ORIGEN": "factura.pdf",
            "GDI_PROPUESTA": json.dumps(proposal),
            "GDI_FECMOD": "2026-10-06T10:00:00",
        }
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.list_purchase_entry_importations({"limite": 10})

        self.assertTrue(result["ok"])
        self.assertEqual(result["total"], 1)
        item = result["documentos"][0]
        self.assertEqual(item["pdf"], "factura.pdf")
        self.assertEqual(item["importacion"]["id"], "IMP-1")
        self.assertEqual(item["importacion"]["version"], 2)
        self.assertEqual(item["cabecera"]["factura"], "FAC-77")
        self.assertEqual(item["lineas"][0]["referencia_proveedor"], "REF-A1")

    def test_purchase_entry_importations_list_applies_search_and_pagination(self):
        db = PurchaseEntryDb()
        db.importation_row = {
            "GDI_ID": "IMP-SEARCH",
            "GDI_NUMEMP": 1,
            "GDI_CENTRO": 7,
            "GDI_ESTADO": "PROPUESTA",
            "GDI_VERSION": 1,
            "GDI_HASH": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
            "GDI_ORIGEN": "facturas/fac-buscada.pdf",
            "GDI_PROPUESTA": json.dumps({"cabecera": {"factura": "FAC-BUSCADA"}, "lineas": []}),
            "GDI_FECMOD": "2026-10-06T10:00:00",
        }
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.list_purchase_entry_importations({"limite": 25, "offset": 50, "busqueda": "buscada"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["offset"], 50)
        self.assertEqual(result["limite"], 25)
        self.assertEqual(result["busqueda"], "buscada")
        sql, params = db.fetch_all_calls[-1]
        self.assertIn("SELECT FIRST 25 SKIP 50", " ".join(sql.split()).upper())
        self.assertEqual(params[0], 1)
        self.assertIn("%BUSCADA%", params)

    def test_purchase_entry_importation_documentation_retry_does_not_create_entry_again(self):
        db = PurchaseEntryDb()
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "factura.pdf"
            pdf.write_bytes(b"%PDF-1.4\n% test\n")
            db.importation_row = {
                "GDI_ID": "IMP-1",
                "GDI_NUMEMP": 1,
                "GDI_CENTRO": 7,
                "GDI_ESTADO": "CONFIRMADA",
                "GDI_VERSION": 2,
                "GDI_HASH": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
                "GDI_ORIGEN": str(pdf),
                "GDI_ENT_CENTRO": 7,
                "GDI_ENT_EJERCI": 2026,
                "GDI_ENT_SERIE": "EN",
                "GDI_ENT_NUMDOC": 101,
                "GDI_PROPUESTA": json.dumps({
                    "pdf": {"origen": str(pdf)},
                    "_texto_extraido_documento": "Factura FAC-77",
                    "totales": {"base": "30", "total": "38.30"},
                }),
            }
            svc = faro_mcp.FaroPhase1Service(db)
            svc.settings.main_dir = tmp

            result = svc.retry_purchase_entry_importation_documentation({"propuesta_id": "IMP-1"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["documento"]["numero"], 101)
        self.assertTrue(result["gestion_documental"]["ruta"])
        self.assertFalse(any(sql.startswith("INSERT INTO CABDOCM") for sql, _ in db.executed))
        self.assertFalse(any(sql.startswith("INSERT INTO DETMOVM") for sql, _ in db.executed))
        self.assertTrue(any(sql.startswith("INSERT INTO DOCUMENTO") for sql, _ in db.executed))

    def test_purchase_entry_importation_documentation_retry_reuses_existing_document(self):
        db = PurchaseEntryDb()
        db.existing_entry_document = {
            "DOC_ID": "DOC-1",
            "DOC_FICHERO": "Compras\\Facturas.Proveedor\\2026\\9\\DOC-1.pdf",
            "DOC_TIPO": "Compras",
            "DOC_SUBTIPO": "Facturas.Proveedor",
            "DOC_IDKRONOS": "CABDOCM:7-2026-EN-101",
        }
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "factura.pdf"
            pdf.write_bytes(b"%PDF-1.4\n% test\n")
            db.importation_row = {
                "GDI_ID": "IMP-1",
                "GDI_NUMEMP": 1,
                "GDI_CENTRO": 7,
                "GDI_ESTADO": "CONFIRMADA",
                "GDI_VERSION": 2,
                "GDI_HASH": hashlib.sha256(b"%PDF-1.4\n% test\n").hexdigest(),
                "GDI_ORIGEN": str(pdf),
                "GDI_ENT_CENTRO": 7,
                "GDI_ENT_EJERCI": 2026,
                "GDI_ENT_SERIE": "EN",
                "GDI_ENT_NUMDOC": 101,
                "GDI_PROPUESTA": json.dumps({"pdf": {"origen": str(pdf)}}),
            }
            svc = faro_mcp.FaroPhase1Service(db)
            svc.settings.main_dir = tmp

            result = svc.retry_purchase_entry_importation_documentation({
                "propuesta_id": "IMP-1",
                "copiar_documentos_entradas": False,
            })

        self.assertTrue(result["gestion_documental"]["existente"])
        self.assertEqual(result["gestion_documental"]["id"], "DOC-1")
        self.assertFalse(any(sql.startswith("INSERT INTO DOCUMENTO") for sql, _ in db.executed))

    def test_purchase_entry_from_pdf_writes_base64_pdf_to_document_management(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nAlbarán Nº ALB-77\n15/09/2026\nREF-A1 Articulo uno 3 10 21\nTOTAL FACTURA 36.30",
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
                "texto_extraido": "CIF: B44\nAlbaran No: ALB-77\n15/09/2026\nREF-A1 Articulo uno 3 10 21\nTOTAL FACTURA 36.30",
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
        command = f'"{sys.executable}" -c "import sys; sys.exit(7)"'
        with patch.dict(os.environ, {"FARO_OCR_COMMAND": command}):
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
            "CIF: B999\nFactura Nº FAC-77\n15/09/2026\nREF-A1 Articulo uno 3 10 21\nTOTAL FACTURA 36.30",
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
            "CIF: B44\nFactura Nº FAC-77\n15/09/2026\nREF-NO Articulo fantasma 3 10 21\nTOTAL FACTURA 36.30",
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
            "CIF: B44\nFactura Nº FAC-77\n15/09/2026\nREF-A1 Articulo uno 3 10 21\nTOTAL FACTURA 36.30",
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
            "CIF: B44\nFactura Nº FAC-77\n15/09/2026\nREF-A1 Articulo uno 3 7 21\nTOTAL FACTURA 25.41",
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

    def test_purchase_entry_from_pdf_preserves_explicit_zero_price(self):
        db = PurchaseEntryDb()
        svc = faro_mcp.FaroPhase1Service(db)
        svc._purchase_entry_pdf_text = lambda args: (
            "CIF: B44\nFactura Nº FAC-77\nFecha factura: 15/09/2026\nREF-A1 Articulo gratis 1 0 21\nTOTAL FACTURA 0.00",
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

        self.assertEqual(result["articulos"][0]["precio"], "0")
        self.assertEqual(result["articulos"][0]["valor_linea"], "0")

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
