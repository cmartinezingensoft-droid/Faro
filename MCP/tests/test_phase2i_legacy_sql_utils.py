import unittest

import faro_mcp


class InternalSqlDb:
    def __init__(self, allow_write=False):
        self.settings = faro_mcp.Settings(
            db_driver="odbc", db_path="", odbc_dsn="faro", db_user="u", db_password="p",
            empresa=1, centro=1, usuario="test", allow_internal_sql_write=allow_write, sql_max_rows=2,
        )
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.queries = []

    def query_rows(self, sql, params=(), limit=500):
        self.queries.append((sql, params, limit))
        return ["CODIGO", "DESCRI"], [
            {"CODIGO": 1, "DESCRI": "Uno|#"},
            {"CODIGO": 2, "DESCRI": "Dos"},
        ][:limit]

    def fetch_one(self, sql, params=()):
        if "RDB$DATABASE" in sql.upper():
            return {"OK": 1}
        return None

    def fetch_all(self, sql, params=()):
        return []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class Phase2IInternalSqlUtilsTests(unittest.TestCase):
    def test_internal_sql_helpers_are_not_mcp_tools(self):
        server = faro_mcp.FaroToolRuntime()
        self.assertEqual(len(server.tools), 85)
        self.assertFalse(any("sql" in name for name in server.tools))
        defs = {x["name"] for x in faro_mcp.tool_definitions()}
        self.assertEqual(defs, set(server.tools))

    def test_busqueda_sql_returns_requested_field_as_string(self):
        svc = faro_mcp.FaroPhase1Service(InternalSqlDb())
        result = svc.internal_search_sql("SELECT CODIGO, DESCRI FROM TEST", "codigo")
        self.assertEqual(result["campo"], "CODIGO")
        self.assertEqual(result["datasnap_text"], "1")

    def test_abrir_consulta_keeps_historical_delimiters_and_cleans_values(self):
        db = InternalSqlDb()
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.internal_open_query("SELECT CODIGO, DESCRI FROM TEST;")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["columns"], ["CODIGO", "DESCRI"])
        self.assertEqual(result["datasnap_text"], "1|Uno|#2|Dos|#")
        self.assertEqual(db.queries[-1][2], 2)

    def test_read_sql_rejects_write_multi_statement_and_comments(self):
        svc = faro_mcp.FaroPhase1Service(InternalSqlDb())
        bad = [
            "UPDATE ARTICUL SET ART_DESCRI='X'",
            "SELECT * FROM ARTICUL; DELETE FROM ARTICUL",
            "SELECT * FROM ARTICUL -- comentario",
            "SELECT * FROM ARTICUL /* comentario */",
        ]
        for sql in bad:
            with self.subTest(sql=sql), self.assertRaises(faro_mcp.FaroError):
                svc.internal_open_query(sql)

    def test_ejecutar_sql_is_disabled_by_default(self):
        db = InternalSqlDb(allow_write=False)
        svc = faro_mcp.FaroPhase1Service(db)
        with self.assertRaises(faro_mcp.FaroError):
            svc.internal_execute_sql("UPDATE ARTICUL SET ART_DESCRI='X' WHERE ART_CODART='1'")
        self.assertEqual(db.executed, [])
        self.assertEqual(db.commits, 0)

    def test_ejecutar_sql_executes_dml_only_when_explicitly_enabled(self):
        db = InternalSqlDb(allow_write=True)
        svc = faro_mcp.FaroPhase1Service(db)
        result = svc.internal_execute_sql("UPDATE ARTICUL SET ART_DESCRI='X' WHERE ART_CODART='1';")
        self.assertTrue(result["ok"])
        self.assertEqual(result["datasnap_text"], "")
        self.assertEqual(len(db.executed), 1)
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        with self.assertRaises(faro_mcp.FaroError):
            svc.internal_execute_sql("DROP TABLE ARTICUL")

    def test_initializa_conexion_checks_database(self):
        svc = faro_mcp.FaroPhase1Service(InternalSqlDb())
        result = svc.initialize_connection()
        self.assertTrue(result["initialized"])
        self.assertTrue(result["datasnap_value"])

    def test_echo_and_reverse_match_delphi_helpers(self):
        self.assertEqual(faro_mcp.FaroPhase1Service.echo_string("abc")["datasnap_text"], "abc")
        self.assertEqual(faro_mcp.FaroPhase1Service.reverse_string("abcñ")["datasnap_text"], "ñcba")


if __name__ == "__main__":
    unittest.main()
