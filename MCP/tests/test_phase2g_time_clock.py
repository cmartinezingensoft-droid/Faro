import unittest
from datetime import datetime as RealDateTime
from decimal import Decimal
from unittest.mock import patch

import faro_mcp


class FixedDateTime(RealDateTime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 14, 16, 30, 0)


class TimeClockDb:
    def __init__(self, *, user="ANA", previous=None, fail_insert=False):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=7, usuario="test",
        )
        self.user = user
        self.previous = previous
        self.fail_insert = fail_insert
        self.executed = []
        self.user_query_params = None
        self.commits = 0
        self.rollbacks = 0

    def fetch_one(self, sql, params=()):
        upper = " ".join(sql.upper().split())
        if "FROM USUAR" in upper:
            self.user_query_params = params
            return {"USU_NOMUSU": self.user} if self.user is not None else None
        if "FROM HORAS" in upper:
            return self.previous
        return None

    def execute(self, sql, params=()):
        if self.fail_insert:
            raise RuntimeError("db error")
        self.executed.append((" ".join(sql.split()), params))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class Phase2GTimeClockTests(unittest.TestCase):
    def test_tool_is_temporarily_not_public(self):
        server = faro_mcp.FaroToolRuntime()
        self.assertNotIn("control_horario_fichar", server.tools)
        self.assertEqual(len(server.tools), 87)
        self.assertFalse(any(name.startswith("datasnap_") for name in server.tools))
        defs = {item["name"] for item in faro_mcp.tool_definitions()}
        self.assertNotIn("control_horario_fichar", defs)
        self.assertEqual(len(defs), 87)

    def test_unknown_password_returns_datasnap_error_without_insert(self):
        db = TimeClockDb(user=None)
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.check_time_clock_user("clave")
        self.assertFalse(result["ok"])
        self.assertEqual(result["datasnap_text"], "9|Usuario no Encontrado|||")
        self.assertEqual(db.executed, [])
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 0)
        self.assertEqual(db.user_query_params[2], faro_mcp.cript(1, "clave", ""))

    def test_first_punch_creates_entry(self):
        db = TimeClockDb(previous=None)
        svc = faro_mcp.FaroPhase1Service(db)
        with patch.object(faro_mcp, "datetime", FixedDateTime):
            result = svc.check_time_clock_user("clave")
        self.assertTrue(result["ok"])
        self.assertEqual(result["tipo"], "I")
        self.assertEqual(result["worked_hours"], "0")
        self.assertIsNone(result["previous_time"])
        self.assertEqual(result["datasnap_text"], "0||ANA|I|")
        self.assertEqual(db.commits, 1)
        params = db.executed[0][1]
        self.assertEqual(params[0:3], (1, 7, "ANA"))
        self.assertEqual(params[4], "I")
        self.assertEqual(params[5], Decimal("0"))

    def test_previous_entry_creates_exit_and_calculates_hours(self):
        previous_time = FixedDateTime(2026, 9, 14, 8, 15, 0)
        db = TimeClockDb(previous={"HOR_TIME": previous_time, "HOR_TIPO": "I"})
        svc = faro_mcp.FaroPhase1Service(db)
        with patch.object(faro_mcp, "datetime", FixedDateTime):
            result = svc.check_time_clock_user("clave")
        self.assertEqual(result["tipo"], "F")
        self.assertEqual(result["worked_hours"], "8.2500")
        self.assertEqual(result["previous_time"], "2026-09-14T08:15:00")
        self.assertEqual(result["datasnap_text"], "0||ANA|F|14/09/2026 08:15:00")
        self.assertEqual(db.executed[0][1][5], Decimal("8.2500"))

    def test_previous_exit_creates_new_entry_with_zero_time(self):
        previous_time = FixedDateTime(2026, 9, 14, 13, 0, 0)
        db = TimeClockDb(previous={"HOR_TIME": previous_time, "HOR_TIPO": "F"})
        svc = faro_mcp.FaroPhase1Service(db)
        with patch.object(faro_mcp, "datetime", FixedDateTime):
            result = svc.check_time_clock_user("clave")
        self.assertEqual(result["tipo"], "I")
        self.assertEqual(result["worked_hours"], "0")
        self.assertEqual(result["datasnap_text"], "0||ANA|I|14/09/2026 13:00:00")

    def test_insert_failure_rolls_back_and_returns_historical_error(self):
        db = TimeClockDb(previous=None, fail_insert=True)
        svc = faro_mcp.FaroPhase1Service(db)
        with patch.object(faro_mcp, "datetime", FixedDateTime):
            result = svc.check_time_clock_user("clave")
        self.assertFalse(result["ok"])
        self.assertEqual(result["datasnap_text"], "9|Error al Grabar Registro|||")
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
