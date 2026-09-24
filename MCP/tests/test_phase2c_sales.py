import unittest
from datetime import date
from decimal import Decimal

import faro_mcp


class FakeDbPhase2C:
    def __init__(self):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=7, usuario="test",
        )
        self.semaforo = set()
        self.vencaj = {}
        self.vencur = []
        self.executed = []
        self.canon_rules = {}
        self.gift_rules = {}
        self.articles = {}
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    @staticmethod
    def _norm(sql):
        return " ".join(sql.upper().split())

    def fetch_one(self, sql, params=()):
        u = self._norm(sql)
        if "FROM PARAMETROS" in u:
            code = params[1]
            values = {"T7": "S", "TT7": "TK", "NUMDEC": "2", "DECLIN": "2"}
            if code in values:
                return {"PAR_VALOR": values[code]}
            return None
        if "FROM CLIEN WHERE" in u:
            codcli = int(params[-2])
            subcli = int(params[-1])
            if (codcli, subcli) == (10, 0):
                return {
                    "CLI_CODREP": 3, "CLI_RAZSOC": "Cliente Diez", "CLI_CIF": "B1",
                    "CLI_DOMICI": "Calle 1", "CLI_CODPOS": "46000", "CLI_POBLAC": "Valencia",
                    "CLI_FORPAG": 1, "CLI_FORENV": 2, "CLI_DTOESP": Decimal("0"), "CLI_REGIVA": "N",
                }
            return None
        if "FROM TIPVEN" in u:
            return {"TIV_CODIGO": 4}
        if "MAX(CBV_NUMDOC)" in u and "FROM VENCAJ" in u:
            ejerci = int(params[1])
            nums = [key[1] for key in self.vencaj if key[0] == ejerci]
            return {"CBV_NUMDOC": max(nums) if nums else None}
        if "FROM SEMAFORO" in u:
            code = params[1]
            return {"SEM_CODIGO": code} if code in self.semaforo else None
        if "SELECT FIRST 1 CBV_NUMDOC FROM VENCAJ" in u:
            _, ejerci, numdoc = params
            row = self.vencaj.get((int(ejerci), int(numdoc)))
            return {"CBV_NUMDOC": numdoc} if row else None
        if "SELECT * FROM VENCAJ" in u:
            _, ejerci, numdoc = params
            return self.vencaj.get((int(ejerci), int(numdoc)))
        if "MAX(DMV_NUMLIN)" in u and "FROM VENCUR" in u:
            _, ejerci, numdoc = params
            nums = [
                int(x["DMV_NUMLIN"]) for x in self.vencur
                if int(x["DMV_EJERCI"]) == int(ejerci)
                and int(x["DMV_NUMDOC"]) == int(numdoc)
                and int(x["DMV_NUMLIN"]) != 999
            ]
            return {"DMV_NUMLIN": max(nums) if nums else None}
        if "FROM ARTICUL" in u:
            codart = str(params[-1]) if params else ""
            return self.articles.get(codart)
        return None

    def fetch_all(self, sql, params=()):
        u = self._norm(sql)
        if "FROM ARTICULI" in u:
            codart = str(params[1])
            codinf = str(params[2])
            if codinf == "CANON":
                return [{"ARTI_DESCRI": value} for value in self.canon_rules.get(codart, [])]
            if codinf == "REGAL":
                return [{"ARTI_DESCRI": value} for value in self.gift_rules.get(codart, [])]
            return []
        if "FROM VENCUR" in u:
            empresa, ejerci, numdoc, _tiplin = params
            return [
                {
                    "DMV_TIPLIN": x["DMV_TIPLIN"], "DMV_PORIVA": x["DMV_PORIVA"],
                    "DMV_PORREQ": x["DMV_PORREQ"], "DMV_VALLINS": x["DMV_VALLINS"],
                    "DMV_CODMON": x["DMV_CODMON"],
                }
                for x in self.vencur
                if int(x["DMV_NUMEMP"]) == int(empresa)
                and int(x["DMV_EJERCI"]) == int(ejerci)
                and int(x["DMV_NUMDOC"]) == int(numdoc)
                and x["DMV_TIPLIN"] != "C"
            ]
        return []

    def execute(self, sql, params=()):
        u = self._norm(sql)
        self.executed.append((u, params))
        if u.startswith("INSERT INTO SEMAFORO"):
            key = params[1]
            if key in self.semaforo:
                raise RuntimeError("duplicate semaphore")
            self.semaforo.add(key)
            return
        if u.startswith("DELETE FROM SEMAFORO"):
            self.semaforo.discard(params[1])
            return
        if u.startswith("INSERT INTO VENCAJ"):
            cols = sql[sql.index("(") + 1:sql.index(")")].replace(" ", "").split(",")
            row = dict(zip(cols, params))
            self.vencaj[(int(row["CBV_EJERCI"]), int(row["CBV_NUMDOC"]))] = row
            return
        if u.startswith("INSERT INTO VENCUR"):
            cols = sql[sql.index("(") + 1:sql.index(")")].replace(" ", "").split(",")
            self.vencur.append(dict(zip(cols, params)))
            return
        if u.startswith("UPDATE VENCAJ SET"):
            key = (int(params[-2]), int(params[-1]))
            row = self.vencaj.get(key)
            if row:
                fields = [
                    "CBV_BASIMP1", "CBV_PORIVA1", "CBV_PORREQ1", "CBV_BASIMP2", "CBV_PORIVA2", "CBV_PORREQ2",
                    "CBV_BASIMP3", "CBV_PORIVA3", "CBV_PORREQ3", "CBV_BASIMP4", "CBV_PORIVA4", "CBV_PORREQ4",
                    "CBV_TOTALS", "CBV_TOTALD",
                ]
                for field, value in zip(fields, params[:14]):
                    row[field] = value
            return
        if u.startswith("DELETE FROM VENCUR"):
            _, ejerci, numdoc = params
            self.vencur = [
                x for x in self.vencur
                if not (int(x["DMV_EJERCI"]) == int(ejerci) and int(x["DMV_NUMDOC"]) == int(numdoc))
            ]
            return
        if u.startswith("DELETE FROM VENCAJ"):
            _, ejerci, numdoc = params
            self.vencaj.pop((int(ejerci), int(numdoc)), None)
            return

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class Phase2CSalesTests(unittest.TestCase):
    def test_tools_are_registered_natively(self):
        server = faro_mcp.FaroToolRuntime()
        self.assertIn("mostrador_venta_gestion", server.tools)
        self.assertNotIn("mostrador_venta_guardar", server.tools)
        self.assertNotIn("mostrador_venta_borrar", server.tools)
        self.assertEqual(len(server.tools), 85)
        self.assertFalse(any(name.startswith("datasnap_") for name in server.tools))

    def test_bloqueo_vencaj_available_and_blocked(self):
        db = FakeDbPhase2C()
        svc = faro_mcp.FaroPhase1Service(db)
        ok = svc.probe_open_sale_lock(r"1\2026\15")
        self.assertTrue(ok["available"])
        self.assertEqual(ok["datasnap_text"], "True")
        self.assertEqual(db.semaforo, set())

        db.semaforo.add(r"1\2026\16")
        blocked = svc.probe_open_sale_lock(r"1\2026\16")
        self.assertFalse(blocked["available"])
        self.assertEqual(blocked["datasnap_text"], "False")

    def test_grabar_venta_new_values_line_and_header(self):
        db = FakeDbPhase2C()
        svc = faro_mcp.FaroPhase1Service(db)
        texto = "A1|Articulo|2|10|0|0|21|0|4|UNI|N|12.1|0|0#"
        result = svc.save_open_sale("", 10, 0, texto, "T", "carlos")

        self.assertTrue(result["created"])
        self.assertEqual(result["lineas_principales"], 1)
        self.assertEqual(Decimal(result["totals"]), Decimal("20"))
        self.assertEqual(Decimal(result["totald"]), Decimal("24.2"))
        self.assertEqual(len(db.vencur), 1)
        self.assertEqual(db.vencaj[(date.today().year, 1)]["CBV_SERIE"], "TK")
        line = db.vencur[0]
        self.assertEqual(line["DMV_TIPLIN"], "D")
        self.assertEqual(Decimal(line["DMV_VALLINS"]), Decimal("20"))
        self.assertEqual(Decimal(line["DMV_VALLIN"]), Decimal("24.2"))
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)

    def test_blank_article_preserves_delphi_comment_bug(self):
        db = FakeDbPhase2C()
        svc = faro_mcp.FaroPhase1Service(db)
        texto = "|Concepto libre|1|25|0|0|21|0||UNI|N|30.25|0|0#"
        result = svc.save_open_sale("", 10, 0, texto, "T", "carlos")
        self.assertEqual(db.vencur[0]["DMV_TIPLIN"], "C")
        self.assertEqual(Decimal(db.vencur[0]["DMV_VALLINS"]), Decimal("0"))
        self.assertEqual(Decimal(result["totald"]), Decimal("0"))

    def test_grabar_venta_ports_external_canon_line(self):
        db = FakeDbPhase2C()
        db.canon_rules["A1"] = ["CAN1"]
        db.articles["CAN1"] = {
            "ART_CODART": "CAN1", "ART_DESCRI": "Canon", "ART_UNIMED": "UNI",
            "ART_CODMON": "E", "ART_PVP": Decimal("2"),
        }
        svc = faro_mcp.FaroPhase1Service(db)
        texto = "A1|Articulo|2|10|0|0|21|0|4|UNI|N|12.1|0|0#"
        result = svc.save_open_sale("", 10, 0, texto, "T", "carlos")
        self.assertEqual(result["lineas_canon"], 1)
        self.assertEqual(len(db.vencur), 2)
        canon = next(x for x in db.vencur if x["DMV_CODART"] == "CAN1")
        self.assertEqual(canon["DMV_TIPLIN"], "D")
        self.assertEqual(Decimal(canon["DMV_VALLINS"]), Decimal("4"))
        self.assertEqual(Decimal(result["totald"]), Decimal("29.04"))

    def test_grabar_venta_ports_gift_rule(self):
        db = FakeDbPhase2C()
        db.gift_rules["A1"] = ["GIFT|2|"]
        db.articles["GIFT"] = {
            "ART_CODART": "GIFT", "ART_DESCRI": "Regalo", "ART_UNIMED": "UNI",
            "ART_PREVEN4": Decimal("5"), "ART_PVP": Decimal("6.05"),
        }
        svc = faro_mcp.FaroPhase1Service(db)
        texto = "A1|Articulo|5|10|0|0|21|0|4|UNI|N|12.1|0|0#"
        result = svc.save_open_sale("", 10, 0, texto, "T", "carlos")
        self.assertEqual(result["lineas_regalo"], 1)
        gift = next(x for x in db.vencur if x["DMV_CODART"] == "GIFT")
        self.assertEqual(Decimal(gift["DMV_CANTID"]), Decimal("2"))
        self.assertEqual(Decimal(gift["DMV_DTO1"]), Decimal("100"))
        self.assertEqual(Decimal(gift["DMV_VALLINS"]), Decimal("0"))

    def test_borrar_venta_respects_semaphore(self):
        db = FakeDbPhase2C()
        year = date.today().year
        db.vencaj[(year, 3)] = {"CBV_EJERCI": year, "CBV_NUMDOC": 3}
        db.semaforo.add(f"1\\{year}\\3")
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.delete_open_sale(f"{year}-3")
        self.assertFalse(result["deleted"])
        self.assertTrue(result["blocked"])
        self.assertIn((year, 3), db.vencaj)

    def test_borrar_venta_deletes_header_and_lines(self):
        db = FakeDbPhase2C()
        year = date.today().year
        db.vencaj[(year, 3)] = {"CBV_EJERCI": year, "CBV_NUMDOC": 3}
        db.vencur.append({"DMV_NUMEMP": 1, "DMV_EJERCI": year, "DMV_NUMDOC": 3, "DMV_NUMLIN": 10})
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.delete_open_sale(f"{year}-3")
        self.assertTrue(result["deleted"])
        self.assertNotIn((year, 3), db.vencaj)
        self.assertEqual(db.vencur, [])
        self.assertEqual(db.commits, 1)

    def test_grabar_venta_rolls_back_on_invalid_numeric_line(self):
        db = FakeDbPhase2C()
        svc = faro_mcp.FaroPhase1Service(db)
        texto = "A1|Articulo|NO_NUMERO|10|0|0|21|0|4|UNI|N|12.1|0|0#"
        with self.assertRaises(faro_mcp.FaroError):
            svc.save_open_sale("", 10, 0, texto, "T", "carlos")
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
