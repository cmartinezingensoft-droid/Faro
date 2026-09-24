import os
import os
import unittest
from unittest.mock import patch
from datetime import date
from decimal import Decimal

import faro_mcp


class FakeDbPhase2B:
    def __init__(self, fail_execute=False):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=7, usuario="test",
        )
        self.fail_execute = fail_execute
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def fetch_all(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "FROM DETMOVM" in u:
            self.last_detmovm_params = params
            return [
                {"DMM_CODART": "A1"},
                {"DMM_CODART": ""},
                {"DMM_CODART": "A2"},
            ]
        if "FROM DETMOV WHERE" in u and "DMV_TIPDOC='P'" in u:
            self.last_detmov_params = params
            codart = params[-1]
            if codart == "A1":
                return [
                    {"DMV_CENTRO": 7, "DMV_TIPDOC": "P", "DMV_TIPAC": "0", "DMV_EJERCI": 2026, "DMV_SERIE": "A", "DMV_NUMDOC": 20},
                    {"DMV_CENTRO": 7, "DMV_TIPDOC": "P", "DMV_TIPAC": "0", "DMV_EJERCI": 2025, "DMV_SERIE": "B", "DMV_NUMDOC": 99},
                ]
            if codart == "A2":
                return [
                    # Duplicado del pedido 2026-A-20: debe salir una sola vez.
                    {"DMV_CENTRO": 7, "DMV_TIPDOC": "P", "DMV_TIPAC": "0", "DMV_EJERCI": 2026, "DMV_SERIE": "A", "DMV_NUMDOC": 20},
                    {"DMV_CENTRO": 7, "DMV_TIPDOC": "P", "DMV_TIPAC": "0", "DMV_EJERCI": 2026, "DMV_SERIE": "C", "DMV_NUMDOC": 5},
                ]
        return []

    def fetch_one(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "SELECT * FROM CABDOCV" in u:
            # La busqueda debe usar el centro configurado (7), no el centro de entrada (2).
            self.asserted_center = params[1]
            _, centro, tipdoc, tipac, ejerci, serie, numdoc = params
            key = (ejerci, serie, numdoc)
            rows = {
                (2025, "B", 99): {
                    "CBV_EJERCI": 2025, "CBV_SERIE": "B", "CBV_NUMDOC": 99,
                    "CBV_CODCLI": 10, "CBV_SUBCLI": 0, "CBV_NOMCLI": "Cliente#Uno",
                    "CBV_FECHA": date(2025, 12, 1), "CBV_TOTALD": Decimal("1234.5"), "CBV_INDEDI": "L",
                },
                (2026, "C", 5): {
                    "CBV_EJERCI": 2026, "CBV_SERIE": "C", "CBV_NUMDOC": 5,
                    "CBV_CODCLI": 11, "CBV_SUBCLI": 0, "CBV_NOMCLI": "Cliente Dos",
                    "CBV_FECHA": date(2026, 1, 2), "CBV_TOTALD": Decimal("10"), "CBV_INDEDI": "",
                },
                (2026, "A", 20): {
                    "CBV_EJERCI": 2026, "CBV_SERIE": "A", "CBV_NUMDOC": 20,
                    "CBV_CODCLI": 12, "CBV_SUBCLI": 1, "CBV_NOMCLI": "Cliente|Tres",
                    "CBV_FECHA": date(2026, 2, 3), "CBV_TOTALD": Decimal("20.2"), "CBV_INDEDI": "P",
                },
            }
            return rows.get(key)
        return None

    def execute(self, sql, params=()):
        if self.fail_execute:
            raise RuntimeError("fallo simulado")
        self.executed.append((" ".join(sql.split()), params))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class FakeDbCloseOrder:
    def __init__(self, existing_tipdoc="P", collision=False, fail_execute=False):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=7, usuario="test",
        )
        self.existing_tipdoc = existing_tipdoc
        self.collision = collision
        self.fail_execute = fail_execute
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def fetch_one(self, sql, params=()):
        u = " ".join(sql.upper().split())
        if "CBV_TIPDOC='S'" in u:
            return {"CBV_NUMDOC": params[-1]} if self.collision else None
        if "FROM CABDOCV" in u:
            tipdoc = params[2]
            return {"CBV_NUMDOC": params[-1]} if tipdoc == self.existing_tipdoc else None
        return None

    def execute(self, sql, params=()):
        if self.fail_execute:
            raise RuntimeError("fallo simulado")
        self.executed.append((" ".join(sql.split()), params))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class Phase2BOrderTests(unittest.TestCase):
    def test_tools_are_registered_natively(self):
        with patch.dict(os.environ, {"FARO_MCP_TOOL_PROFILE": "full"}):
            server = faro_mcp.FaroToolRuntime()
            definitions = {item["name"] for item in faro_mcp.tool_definitions()}
        for name in (
            "pedido_situacion_actualizar",
            "entrada_pedidos_relacionados",
            "pedido_retirada_actualizar",
        ):
            self.assertIn(name, server.tools)
        self.assertTrue({
            "pedido_situacion_actualizar",
            "entrada_pedidos_relacionados",
            "pedido_retirada_actualizar",
        }.issubset(definitions))
        self.assertFalse(any(name.startswith("datasnap_") for name in server.tools))

    def test_grabar_situacion_pedido_updates_only_tipac_zero(self):
        db = FakeDbPhase2B()
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.save_order_status("P", 2, "P", 2026, "A", 15)
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        self.assertEqual(result["situacion"], "P")
        sql, params = db.executed[0]
        self.assertIn("CBV_TIPAC='0'", sql)
        self.assertEqual(params, ("P", 1, 2, "P", 2026, "A", 15))
        self.assertEqual(result["datasnap_text"], "")

    def test_grabar_situacion_rolls_back_on_error(self):
        db = FakeDbPhase2B(fail_execute=True)
        svc = faro_mcp.FaroPhase1Service(db)
        with self.assertRaises(RuntimeError):
            svc.save_order_status("P", 2, "P", 2026, "A", 15)
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)

    def test_pedidos_cliente_entrada_matches_delphi_center_and_dedup(self):
        db = FakeDbPhase2B()
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.incoming_order_customer_orders(2, 2026, "E", 77)

        self.assertEqual(db.last_detmovm_params, (1, 2, 2026, "E", 77))
        self.assertEqual(db.last_detmov_params[1], 7)  # FARO_CENTRO / R_PARAMETROS.CENTRO
        self.assertEqual(db.asserted_center, 7)
        self.assertEqual(result["count"], 3)
        self.assertEqual(
            [(x["ejerci"], x["numdoc"]) for x in result["items"]],
            [(2025, 99), (2026, 5), (2026, 20)],
        )
        self.assertEqual(result["items"][0]["nomcli"], "Cliente#Uno")
        self.assertEqual(result["items"][2]["nomcli"], "Cliente|Tres")
        self.assertIn("01/12/2025|1.234,50|L#", result["datasnap_text"])

    def test_grabar_retirado_referencia_parses_document_and_updates(self):
        db = FakeDbPhase2B()
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.save_order_withdrawal_reference("2-P-2026-A-123", "S", "REF-CLIENTE")
        self.assertEqual(db.commits, 1)
        sql, params = db.executed[0]
        self.assertIn("CBV_RETIRA=?", sql)
        self.assertIn("CBV_REFCLI=?", sql)
        self.assertIn("CBV_TIPAC='0'", sql)
        self.assertEqual(params, ("S", "REF-CLIENTE", 1, 2, "P", 2026, "A", 123))
        self.assertEqual(result["datasnap_text"], "")

    def test_grabar_retirado_referencia_rejects_bad_document(self):
        db = FakeDbPhase2B()
        svc = faro_mcp.FaroPhase1Service(db)
        with self.assertRaises(faro_mcp.FaroError):
            svc.save_order_withdrawal_reference("P-2026-1", "S", "REF")
        self.assertEqual(db.executed, [])

    def test_cerrar_pedido_closes_order_to_historic_type(self):
        db = FakeDbCloseOrder(existing_tipdoc="P")
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.close_client_order("carlos", 0, "P", 2026, "PM", 12)

        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        self.assertEqual(result["documento"], "pedido")
        self.assertEqual(result["tipo_origen"], "P")
        self.assertEqual(result["tipo_destino"], "S")
        self.assertEqual(len(db.executed), 2)
        self.assertIn("UPDATE CABDOCV SET CBV_TIPDOC='S'", db.executed[0][0])
        self.assertIn("UPDATE DETMOV SET DMV_TIPDOC='S'", db.executed[1][0])
        self.assertEqual(db.executed[0][1][3], 1)
        self.assertEqual(db.executed[0][1][5], "P")
        self.assertEqual(db.executed[1][1], (1, 0, "P", "0", 2026, "PM", 12))

    def test_cerrar_pedido_closes_budget_to_historic_type(self):
        db = FakeDbCloseOrder(existing_tipdoc="R")
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.close_client_order("carlos", 0, "r", 2026, "PM", 12)

        self.assertEqual(db.commits, 1)
        self.assertEqual(result["documento"], "presupuesto")
        self.assertEqual(result["tipo_origen"], "R")
        self.assertEqual(db.executed[0][1][5], "R")
        self.assertEqual(db.executed[1][1], (1, 0, "R", "0", 2026, "PM", 12))

    def test_cerrar_pedido_rejects_other_document_types(self):
        db = FakeDbCloseOrder(existing_tipdoc="A")
        svc = faro_mcp.FaroPhase1Service(db)
        with self.assertRaises(faro_mcp.FaroError):
            svc.close_client_order("carlos", 0, "A", 2026, "PM", 12)
        self.assertEqual(db.executed, [])
        self.assertEqual(db.commits, 0)


if __name__ == "__main__":
    unittest.main()
