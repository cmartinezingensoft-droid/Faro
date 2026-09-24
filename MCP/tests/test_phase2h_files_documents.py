import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import faro_mcp


class DocumentsDb:
    def __init__(self, root: str):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=7, usuario="test", main_dir=root,
            documents_dir=str(Path(root) / "Documentos"), images_dir=str(Path(root) / "Imagenes"),
            smtp_host="smtp.example.test", smtp_port=25, smtp_user="user", smtp_password="secret",
            smtp_from="erp@example.test", smtp_from_name="Faro ERP",
        )
        self.commits = 0
        self.rollbacks = 0

    def fetch_one(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM ARTICULI" in u:
            return {"ARTI_DESCRI": "articulos/A1.jpg"}
        if "FROM CABDOCV" in u:
            return {
                "CBV_NUMEMP": 1, "CBV_CENTRO": 7, "CBV_TIPDOC": "P", "CBV_TIPAC": "0",
                "CBV_EJERCI": 2026, "CBV_SERIE": "A", "CBV_NUMDOC": 42,
                "CBV_FECHA": "2026-09-14", "CBV_CODCLI": 100, "CBV_SUBCLI": 0,
                "CBV_TOTALS": 121, "CBV_TOTALD": 121, "CBV_OBSERV": "Entregar por la mañana",
            }
        if "FROM CLIEN" in u:
            return {
                "CLI_RAZSOC": "Cliente Prueba", "CLI_NIF": "B12345678", "CLI_DOMICI": "Calle Mayor 1",
                "CLI_CODPOS": "46001", "CLI_POBLAC": "Valencia",
            }
        return None

    def fetch_all(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM DETMOV" in u:
            return [
                {
                    "DMV_NUMLIN": 10, "DMV_TIPLIN": "D", "DMV_CODART": "A1", "DMV_DESCRI": "Articulo uno",
                    "DMV_CANTID": 2, "DMV_PREVEN": 50, "DMV_DTO1": 0, "DMV_DTO2": 0,
                    "DMV_VALLIN": 100, "DMV_VALLINS": 100,
                },
                {
                    "DMV_NUMLIN": 20, "DMV_TIPLIN": "C", "DMV_CODART": "", "DMV_DESCRI": "Comentario",
                    "DMV_CANTID": 0, "DMV_PREVEN": 0, "DMV_DTO1": 0, "DMV_DTO2": 0,
                    "DMV_VALLIN": 0, "DMV_VALLINS": 0,
                },
            ]
        return []

    def execute(self, sql, params=()):
        raise AssertionError("Fase 2H no debe escribir en BD")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class FakeSmtp:
    instances = []

    def __init__(self, host, port, timeout=None, **kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.logged = None
        self.message = None
        self.started_tls = False
        self.closed = False
        FakeSmtp.instances.append(self)

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        self.logged = (user, password)

    def send_message(self, message):
        self.message = message

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True


class Phase2HFilesDocumentsTests(unittest.TestCase):
    def setUp(self):
        FakeSmtp.instances.clear()

    def test_tools_registered_native_only(self):
        server = faro_mcp.FaroToolRuntime()
        public = {
            "pedido_enviar", "pedido_pdf_gestion", "articulo_obtener",
        }
        internal = {
            "fichero_grabar", "imagen_obtener_como_texto",
            "correo_enviar", "fichero_obtener", "fichero_obtener_como_texto",
        }
        self.assertTrue(public.issubset(server.tools))
        self.assertTrue(internal.isdisjoint(server.tools))
        self.assertEqual(len(server.tools), 87)
        self.assertFalse(any(name.startswith("datasnap_") for name in server.tools))
        defs = {x["name"] for x in faro_mcp.tool_definitions()}
        self.assertEqual(len(defs), 87)
        self.assertTrue(public.issubset(defs))
        self.assertTrue(internal.isdisjoint(defs))

    def test_grabar_and_get_fichero_base64(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc = faro_mcp.FaroPhase1Service(DocumentsDb(tmp))
            saved = svc.save_text_file("prueba", "hola")
            path = Path(saved["path"])
            self.assertTrue(path.exists())
            self.assertTrue(path.name.endswith(".TXT"))
            got = svc.get_file_as_string("prueba.TXT")
            decoded = base64.b64decode(got["datasnap_text"]).decode("cp1252")
            self.assertEqual(decoded, "hola" + __import__("os").linesep)

    def test_file_reader_rejects_escape_outside_faro_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc = faro_mcp.FaroPhase1Service(DocumentsDb(tmp))
            with self.assertRaises(faro_mcp.FaroError):
                svc.get_file("../fuera.txt")

    def test_article_image_original_and_resized(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = DocumentsDb(tmp)
            root = Path(db.settings.images_dir)
            (root / "articulos").mkdir(parents=True)
            (root / "resized").mkdir(parents=True)
            (root / "articulos" / "A1.jpg").write_bytes(b"ORIGINAL")
            (root / "resized" / "A1.jpg").write_bytes(b"SMALL")
            svc = faro_mcp.FaroPhase1Service(db)
            original = svc.article_image_as_string("A1", "G")
            small = svc.article_image_as_json("A1", "P")
            self.assertEqual(base64.b64decode(original["content_base64"]), b"ORIGINAL")
            self.assertEqual(base64.b64decode(small["content_base64"]), b"SMALL")
            self.assertEqual(small["transport"], "base64")

    def test_generate_order_pdf_and_read_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc = faro_mcp.FaroPhase1Service(DocumentsDb(tmp))
            result = svc.generate_order_pdf(7, 2026, "A", 42)
            pdf = Path(result["path"])
            self.assertTrue(pdf.exists())
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
            self.assertEqual(pdf.name, "P-2026-A-42.pdf")
            transmitted = svc.order_pdf_as_json(2026, "A", 42)
            self.assertTrue(transmitted["exists"])
            self.assertTrue(base64.b64decode(transmitted["content_base64"]).startswith(b"%PDF"))

    def test_enviar_correo_uses_smtp_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc = faro_mcp.FaroPhase1Service(DocumentsDb(tmp))
            with patch.object(faro_mcp.smtplib, "SMTP", FakeSmtp):
                result = svc.send_email("destino@example.test", "Tema", "Texto")
            self.assertTrue(result["ok"])
            self.assertEqual(result["datasnap_text"], "Enviado correo a destino@example.test con exito")
            smtp = FakeSmtp.instances[-1]
            self.assertEqual(smtp.logged, ("user", "secret"))
            self.assertEqual(smtp.message["To"], "destino@example.test")
            self.assertEqual(smtp.message["Subject"], "Tema")

    def test_enviar_pedido_generates_and_attaches_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc = faro_mcp.FaroPhase1Service(DocumentsDb(tmp))
            with patch.object(faro_mcp.smtplib, "SMTP", FakeSmtp):
                result = svc.send_order(7, 2026, "A", 42, "cliente@example.test")
            self.assertTrue(result["ok"])
            self.assertEqual(result["datasnap_text"], "")
            self.assertTrue(Path(result["pdf"]).exists())
            smtp = FakeSmtp.instances[-1]
            attachments = list(smtp.message.iter_attachments())
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0].get_filename(), "P-2026-A-42.pdf")


if __name__ == "__main__":
    unittest.main()
