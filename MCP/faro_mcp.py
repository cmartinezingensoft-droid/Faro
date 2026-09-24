from __future__ import annotations

import base64
import calendar
import contextvars
import json
import mimetypes
import os
import re
import smtplib
import socket
import ssl
import sys
import time
import uuid
from email.message import EmailMessage
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Callable


ARTICLE_PRICE_FIELDS = [
    "ART_TABPREC",
    "ART_PRECOS",
    "ART_PREVEN1",
    "ART_PREVEN2",
    "ART_PREVEN3",
    "ART_PREVEN4",
    "ART_PVP",
    "ART_FECVAR",
    "ART_FECMOD",
    "ART_USUMOD",
]

MAX_ROWS_DEFAULT = 500
SERVER_VERSION = "2.15.8"
PUBLIC_CONTRACT_VERSION = "2.0"
DEFAULT_EMPRESA = 1
DEFAULT_CENTRO = 0
_CURRENT_EMPRESA: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "faro_mcp_current_empresa", default=None
)

COMPANY_REPLICATION_SOURCE = 1
COMPANY_REPLICATION_TABLES: tuple[tuple[str, str], ...] = (
    ("AGRUP1", "AG1_NUMEMP"),
    ("AGRUP2", "AG2_NUMEMP"),
    ("AGRUP3", "AG3_NUMEMP"),
    ("BANCOS", "BAN_NUMEMP"),
    ("CAJAS", "CAJ_NUMEMP"),
    ("CENTROS", "CEN_NUMEMP"),
    ("EMPRES", "EMP_NUMEMP"),
    ("FAMILI", "FAM_NUMEMP"),
    ("FAMNCC", "NCC_NUMEMP"),
    ("FORENV", "FEN_NUMEMP"),
    ("FORPAG", "FPG_NUMEMP"),
    ("FORPAGA", "FPGA_NUMEMP"),
    ("GRUPOMENU", "GRM_NUMEMP"),
    ("GRUPUSU", "GRU_NUMEMP"),
    ("GRUPUSU2", "GRU2_NUMEMP"),
    ("MEDIDAS", "MED_NUMEMP"),
    ("NUMERA", "NUM_NUMEMP"),
    ("PARAMETROS", "PAR_NUMEMP"),
    ("SSUBFAM", "SSUB_NUMEMP"),
    ("SUBFAM", "SUB_NUMEMP"),
    ("TABPREC", "TPR_NUMEMP"),
    ("TARJET", "TAR_NUMEMP"),
    ("TIPACT", "TAC_NUMEMP"),
    ("TIPDOC", "TIP_NUMEMP"),
    ("TIPIVA", "TIV_NUMEMP"),
    ("TIPVEN", "TIV_NUMEMP"),
    ("USUAR", "USU_NUMEMP"),
    ("USUAR2", "USU2_NUMEMP"),
    ("ZONAS", "ZON_NUMEMP"),
)

SALE_PROFIT_GROUP_FIELDS = {
    "articulo", "seccion", "familia", "subfamilia", "proveedor", "cliente",
    "representante", "centro", "mes", "dia_semana", "tipo_documento", "marca",
}
SALE_FAMILY_TYPES = {"ncc", "propia", "cooperativa"}

SALE_DOCUMENT_GROUP_FIELDS = {
    "cliente", "ejercicio", "tipo_documento", "categoria", "centro", "mes",
    "trimestre", "representante", "forma_pago", "situacion", "moneda",
    "poblacion", "tarifa", "dia_semana", "hora", "zona_cliente",
}


def clean_text_value(value: Any) -> str:
    return str(value or "").replace("|", "").replace("#", "")


def serialize_text_value(value: Any) -> str:
    return "" if value is None else str(value)


class FaroError(RuntimeError):
    pass


def _is_duplicate_key_error(exc: Exception) -> bool:
    """Distingue una colision real de numeracion (violacion de PRIMARY/UNIQUE KEY,
    p.ej. al reintentar ACT_NUMLIN/CBV_NUMDOC/CBR_NUMDOC) de cualquier otro fallo
    (FK invalida, tipo de dato, columna obligatoria vacia, etc.). Los bucles de
    numeracion con reintento solo deben seguir probando el siguiente numero ante
    una colision real; cualquier otro error debe propagarse de inmediato en vez
    de reintentarse a ciegas hasta 999999 veces (lo que en la practica se percibe
    como que la operacion se queda colgada sin fin).
    """
    sqlcode = getattr(exc, "sqlcode", None)
    if sqlcode == -803:
        return True
    message = str(exc).lower()
    return "unique key constraint" in message or "primary key constraint" in message


def dec(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def my_round(value: Decimal) -> int:
    sign = -1 if value < 0 else 1
    value = abs(value)
    integer = int(value.to_integral_value(rounding=ROUND_DOWN))
    if value - Decimal(integer) >= Decimal("0.5"):
        integer += 1
    return sign * integer


def redondea(value: Decimal, decimals: int) -> Decimal:
    if value == 0:
        return value
    power = Decimal(10) ** decimals
    return Decimal(my_round(value * power)) / power


def row_to_dict(cursor, row) -> dict[str, Any] | None:
    if row is None:
        return None
    names = [col[0].upper() for col in cursor.description]
    return {names[i]: row[i] for i in range(len(names))}


# ---------------------------------------------------------------------------
# CRIPT (LIBTIP_U.pas, lineas 369-657): cifrado propietario usado para
# USUAR.USU_PASSWORD (usuarios internos del ERP). Es una sustitucion/
# permutacion de caracteres, no un algoritmo criptografico estandar.
#
# Tabla original (TABLA[1..65] en Delphi, aqui indice 0..64): caracter + V1.
# Bug heredado y REPLICADO A PROPOSITO por fidelidad: en el Delphi original
# 'TABLA[33].CH := 'W';' se sobreescribe inmediatamente con
# 'TABLA[33].CH := 'X';', de modo que 'W' (mayuscula) nunca queda asociada a
# ninguna entrada de la tabla. Cualquier contrasena que contenga 'W' no se
# puede cifrar en el Delphi original (CRIPT devuelve cadena vacia) y esta
# implementacion Python reproduce exactamente ese comportamiento para no
# generar hashes incompatibles con los ya almacenados en USUAR. La posicion
# 36 (V1=43) tampoco tiene caracter asociado en el original (hueco sin uso).
_CRIPT_TABLE: list[tuple[str | None, int]] = [
    ("0", 79), ("1", 74), ("2", 85), ("3", 15), ("4", 44), ("5", 21), ("6", 76), ("7", 73), ("8", 83), ("9", 18),
    ("A", 77), ("B", 69), ("C", 11), ("D", 84), ("E", 33), ("F", 89), ("G", 27), ("H", 86), ("I", 20), ("J", 81),
    ("K", 78), ("L", 23), ("M", 82), ("N", 31), ("O", 71), ("P", 35), ("Q", 25), ("R", 60), ("S", 58), ("T", 70),
    ("U", 88), ("V", 61), ("X", 48), ("Y", 68), ("Z", 55),
    (None, 43),
    ("a", 53), ("b", 57), ("c", 63), ("d", 50), ("e", 56), ("f", 59), ("g", 46), ("h", 66), ("i", 54), ("j", 41),
    ("k", 10), ("l", 29), ("m", 34), ("n", 39), ("o", 24), ("p", 16), ("q", 22), ("r", 28), ("s", 32), ("t", 19),
    ("u", 12), ("v", 37), ("w", 30), ("x", 17), ("y", 14), ("z", 65),
    ("ñ", 52), ("Ñ", 26), (" ", 36),
]
# Orden de procesado de posiciones (1-based, como en Delphi) y desplazamiento
# sumado a V1 para cada una, en el mismo orden en que aparecen en CRIPT.
_CRIPT_POS_ORDER = [7, 3, 8, 6, 1, 4, 2, 5]
_CRIPT_OFFSETS = [2, 6, 1, 3, 8, 5, 7, 4]


def cript(modo: int, cifrar: str = "", cifrado: str = "") -> str:
    """Replica CRIPT (LIBTIP_U.pas). modo=1 cifra `cifrar`; modo=0 descifra `cifrado`.

    Cifrar: rellena con espacios a la derecha hasta 8 caracteres (si ya tiene
    8 o mas, se usan tal cual los primeros 8; los caracteres 9 en adelante
    nunca influyen en el resultado, igual que en Delphi). Si algun caracter
    de los 8 no aparece en la tabla (p.ej. 'W' mayuscula), devuelve ''.
    Descifrar: solo usa los 2 primeros digitos de cada bloque de 4 (el resto
    es el offset+V1, que Delphi tampoco usa para verificar nada).
    """
    if modo == 1:
        if not cifrar:
            return ""
        if len(cifrar) < 8:
            cifrar = cifrar + " " * (8 - len(cifrar))
        salida = []
        for pos, offset in zip(_CRIPT_POS_ORDER, _CRIPT_OFFSETS):
            ch = cifrar[pos - 1]
            idx = None
            v1 = None
            for i, (table_ch, table_v1) in enumerate(_CRIPT_TABLE, start=1):
                if table_ch == ch:
                    idx, v1 = i, table_v1
                    break
            if idx is None:
                return ""
            salida.append(f"{idx:02d}{v1 + offset:02d}")
        return "".join(salida)

    if not cifrado:
        return ""
    salida = [" "] * 8
    try:
        for block_start, pos in zip(range(0, 32, 4), _CRIPT_POS_ORDER):
            idx = int(cifrado[block_start:block_start + 2])
            table_ch = _CRIPT_TABLE[idx - 1][0]
            salida[pos - 1] = table_ch or " "
    except (ValueError, IndexError) as exc:
        raise FaroError(f"Cadena cifrada no valida para CRIPT: {cifrado}") from exc
    return "".join(salida)


@dataclass
class Settings:
    db_driver: str
    db_path: str
    odbc_dsn: str
    db_user: str
    db_password: str
    empresa: int
    centro: int
    usuario: str
    main_dir: str = r"C:\FaroERP"
    documents_dir: str = ""
    images_dir: str = ""
    smtp_host: str = ""
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_from_name: str = ""
    smtp_starttls: bool = False
    smtp_ssl: bool = False
    allow_internal_sql_write: bool = False
    sql_max_rows: int = MAX_ROWS_DEFAULT

    @classmethod
    def from_env(cls) -> "Settings":
        db_driver = os.getenv("FARO_DB_DRIVER", "odbc").lower()
        db_path = os.getenv("FARO_DB_PATH", "")
        odbc_dsn = os.getenv("FARO_ODBC_DSN", "faro")
        if db_driver in {"firebird", "fdb"} and not db_path:
            raise FaroError("Falta FARO_DB_PATH con la ruta/DSN Firebird de Faro.")
        if db_driver == "odbc" and not odbc_dsn:
            raise FaroError("Falta FARO_ODBC_DSN con el DSN ODBC de Faro.")
        return cls(
            db_driver=db_driver,
            db_path=db_path,
            odbc_dsn=odbc_dsn,
            db_user=os.getenv("FARO_DB_USER", "SYSDBA"),
            db_password=os.getenv("FARO_DB_PASSWORD", "masterkey"),
            empresa=int(os.getenv("FARO_EMPRESA", str(DEFAULT_EMPRESA))),
            centro=int(os.getenv("FARO_CENTRO", "0")),
            usuario=os.getenv("FARO_USUARIO", "codex"),
            main_dir=os.getenv("FARO_MAIN_DIR", r"C:\FaroERP"),
            documents_dir=os.getenv("FARO_DOCUMENTS_DIR", ""),
            images_dir=os.getenv("FARO_IMAGES_DIR", ""),
            smtp_host=os.getenv("FARO_SMTP_HOST", ""),
            smtp_port=int(os.getenv("FARO_SMTP_PORT", "25")),
            smtp_user=os.getenv("FARO_SMTP_USER", ""),
            smtp_password=os.getenv("FARO_SMTP_PASSWORD", ""),
            smtp_from=os.getenv("FARO_SMTP_FROM", ""),
            smtp_from_name=os.getenv("FARO_SMTP_FROM_NAME", ""),
            smtp_starttls=os.getenv("FARO_SMTP_STARTTLS", "false").lower() in {"1", "true", "yes", "si"},
            smtp_ssl=os.getenv("FARO_SMTP_SSL", "false").lower() in {"1", "true", "yes", "si"},
            allow_internal_sql_write=os.getenv(
                "FARO_ALLOW_INTERNAL_SQL_WRITE", "false"
            ).lower() in {"1", "true", "yes", "si"},
            sql_max_rows=max(1, min(int(os.getenv("FARO_SQL_MAX_ROWS", str(MAX_ROWS_DEFAULT))), 5000)),
        )


class FaroDb:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.conn = self._connect()
        self._column_cache: dict[str, set[str]] = {}

    def _connect(self):
        if self.settings.db_driver == "odbc":
            try:
                import pyodbc  # type: ignore
            except ImportError as exc:
                raise FaroError("Instala el paquete 'pyodbc' para usar FARO_DB_DRIVER=odbc.") from exc
            return pyodbc.connect(
                f"DSN={self.settings.odbc_dsn};"
                f"UID={self.settings.db_user};"
                f"PWD={self.settings.db_password}",
                autocommit=False,
            )
        if self.settings.db_driver == "fdb":
            try:
                import fdb  # type: ignore
            except ImportError as exc:
                raise FaroError("Instala el paquete 'fdb' o usa FARO_DB_DRIVER=firebird.") from exc
            return fdb.connect(
                dsn=self.settings.db_path,
                user=self.settings.db_user,
                password=self.settings.db_password,
                charset=os.getenv("FARO_DB_CHARSET", "WIN1252"),
            )
        try:
            from firebird.driver import connect  # type: ignore
        except ImportError as exc:
            raise FaroError("Instala el paquete 'firebird-driver' o usa FARO_DB_DRIVER=fdb.") from exc
        return connect(
            database=self.settings.db_path,
            user=self.settings.db_user,
            password=self.settings.db_password,
            charset=os.getenv("FARO_DB_CHARSET", "WIN1252"),
        )

    def close(self) -> None:
        self.conn.close()

    def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
            return row_to_dict(cur, cur.fetchone())
        finally:
            cur.close()

    def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
            return [row_to_dict(cur, row) for row in cur.fetchall()]
        finally:
            cur.close()

    def table_columns(self, table_name: str) -> set[str]:
        normalized = str(table_name or "").strip().upper()
        if not normalized:
            return set()
        cached = self._column_cache.get(normalized)
        if cached is not None:
            return cached
        cur = self.conn.cursor()
        try:
            try:
                cur.execute(f"SELECT * FROM {normalized} WHERE 1=0")
            except Exception:
                columns = set()
            else:
                columns = {col[0].upper() for col in (cur.description or [])}
        finally:
            cur.close()
        self._column_cache[normalized] = columns
        return columns

    def query_rows(
        self, sql: str, params: tuple[Any, ...] = (), limit: int = MAX_ROWS_DEFAULT
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Ejecuta una consulta de solo lectura y limita lo materializado en memoria."""
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
            columns = [col[0].upper() for col in (cur.description or [])]
            raw_rows = cur.fetchmany(max(1, int(limit)))
            rows = [
                {columns[i]: row[i] for i in range(len(columns))}
                for row in raw_rows
            ]
            return columns, rows
        finally:
            cur.close()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
        finally:
            cur.close()

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()


class FaroArticleService:
    def __init__(self, db: FaroDb):
        self.db = db
        self.settings = db.settings

    def parameter(self, code: str, default: str = "") -> str:
        row = self.db.fetch_one(
            "SELECT PAR_VALOR FROM PARAMETROS WHERE PAR_NUMEMP=? AND PAR_CODIGO=?",
            (self.settings.empresa, code),
        )
        return str(row["PAR_VALOR"]).strip() if row and row.get("PAR_VALOR") is not None else default

    def get_article(self, codart: str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        if not row:
            raise FaroError(f"Articulo no encontrado: {codart}")
        return normalize(row)

    def get_price_table(self, code: int) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM TABPREC WHERE TPR_NUMEMP=? AND TPR_CODTAB=?",
            (self.settings.empresa, code),
        )
        if not row:
            raise FaroError(f"Tabla de precios inexistente: {code}")
        return normalize(row)

    def get_tax(self, code: int) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM TIPIVA WHERE TIV_NUMEMP=? AND TIV_TIPIVA=?",
            (self.settings.empresa, code),
        )
        if not row:
            raise FaroError(f"Tipo de IVA inexistente: {code}")
        return normalize(row)

    def list_price_tables(self) -> list[dict[str, Any]]:
        rows = self.db.fetch_all(
            "SELECT * FROM TABPREC WHERE TPR_NUMEMP=? ORDER BY TPR_CODTAB",
            (self.settings.empresa,),
        )
        return [normalize(row) for row in rows]

    def round_price(self, value: Decimal, currency: str, price_type: str) -> Decimal:
        numdec = int(self.parameter("NUMDEC", "2") or "2")
        declin = int(self.parameter("DECLIN", "2") or "2")
        if value == 0:
            return Decimal("0")
        if price_type == "P":
            return redondea(value, numdec)
        if price_type == "L":
            return redondea(value, declin)
        if currency == "P":
            return redondea(value, 0)
        return redondea(value, 2)

    def adjust_price(self, value: Decimal, adjustment: Decimal, currency: str) -> Decimal:
        if value == 0 or adjustment == 0:
            return value
        if currency == "E":
            canmin = dec(self.parameter("CANMIN", "0"))
            if value <= canmin:
                return value
            canmax_text = self.parameter("CANMAX", "")
            if canmax_text:
                try:
                    canmax = dec(canmax_text)
                    if canmin < value <= canmax:
                        adjustment = Decimal("0.02")
                except Exception:
                    pass
            value = redondea(value, 2) * Decimal(100)
            adjustment = redondea(adjustment, 2) * Decimal(100)
            return self.adjust_price(value, adjustment, "P") / Decimal(100)
        value_i = my_round(value)
        adjustment_i = my_round(adjustment)
        if adjustment_i == 0:
            return Decimal(value_i)
        quotient = value_i // adjustment_i
        if self.parameter("AJUSUP", "") == "S":
            return Decimal((quotient + 1) * adjustment_i)
        rest = value_i % adjustment_i
        if Decimal(rest) < Decimal(adjustment_i) / Decimal(2):
            return Decimal(quotient * adjustment_i)
        return Decimal((quotient + 1) * adjustment_i)

    def provider_conversion_cost(self, art: dict[str, Any]) -> Decimal:
        row = self.db.fetch_one(
            """
            SELECT FIRST 1 ARTP_CANCON, ARTP_CANVEN
            FROM ARTICULP
            WHERE ARTP_NUMEMP=? AND ARTP_CODART=? AND ARTP_CODPRO=?
            ORDER BY ARTP_REFPRO
            """,
            (self.settings.empresa, art["ART_CODART"], art["ART_CODPRO"]),
        )
        if not row:
            raise FaroError("ART_CANPRE es cero y no existe referencia ARTICULP para obtener conversion.")
        cancon = dec(row.get("ARTP_CANCON"))
        canven = dec(row.get("ARTP_CANVEN"))
        if canven == 0:
            raise FaroError("ARTP_CANVEN es cero; no se puede calcular conversion de proveedor.")
        return dec(art["ART_PRECOS"]) * cancon / canven

    def change_price_currency(self, value: Decimal, source: str, target: str, price_type: str) -> Decimal:
        source = str(source or "").strip().upper()[:1]
        target = str(target or "").strip().upper()[:1]
        if source not in {"P", "E"}:
            return Decimal("0")
        if source == target:
            return self.round_price(value, source, price_type)
        if source == "P":
            return redondea(value / Decimal("166.386"), 2)
        if source == "E":
            return redondea(value * Decimal("166.386"), 0)
        return Decimal("-1")

    def _article_file_price(self, codart: str, moneda: str, field_name: str) -> Decimal:
        row = self.db.fetch_one(
            f"SELECT {field_name}, ART_CODMON, ART_CANPRE, ART_CODPRO FROM ARTICUL "
            "WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart.strip()),
        )
        if not row:
            return Decimal("0")

        price = dec(row.get(field_name))
        art_currency = str(row.get("ART_CODMON") or "").strip().upper()[:1]
        target_currency = str(moneda or "E").strip().upper()[:1] or "E"
        if target_currency != art_currency:
            price = self.change_price_currency(price, art_currency, target_currency, "P")

        canpre = dec(row.get("ART_CANPRE"))
        if canpre > 0:
            return price / canpre

        conversion = self.db.fetch_one(
            """
            SELECT ARTP_CANCON, ARTP_CANVEN
            FROM ARTICULP
            WHERE ARTP_NUMEMP=? AND ARTP_CODART=? AND ARTP_CODPRO=?
            """,
            (self.settings.empresa, codart, int(row.get("ART_CODPRO") or 0)),
        )
        cancon = Decimal("1")
        canven = Decimal("1")
        if conversion:
            cancon = dec(conversion.get("ARTP_CANCON"))
            canven = dec(conversion.get("ARTP_CANVEN"))
            if canven == 0:
                canven = Decimal("1")
        return price * cancon / canven

    def article_base_price(self, codart: str, moneda: str = "E") -> Decimal:
        """Replica PRECIO_BASE_ARTICULO: ART_PREBAS ajustado por conversion."""
        return self._article_file_price(codart, moneda, "ART_PREBAS")

    def article_file_cost(self, codart: str, moneda: str = "E") -> Decimal:
        """Replica PCOSTE_ARTICUL: ART_PRECOS ajustado por conversion."""
        return self._article_file_price(codart, moneda, "ART_PRECOS")

    def last_purchase_cost(self, codart: str, fecha: date, moneda: str = "E") -> Decimal:
        row = self.db.fetch_one(
            """
            SELECT FIRST 1 DMM_CODMON, DMM_CANTID, DMM_VALLIN, DMM_IMPDTO
            FROM DETMOVM
            WHERE DMM_NUMEMP=? AND DMM_FECMOV <= ? AND DMM_CODART=?
            ORDER BY DMM_FECMOV DESC
            """,
            (self.settings.empresa, fecha, codart),
        )
        if not row:
            last_price = self.article_file_cost(codart, moneda)
        else:
            quantity = dec(row.get("DMM_CANTID"))
            if quantity == 0:
                quantity = Decimal("1")
            line_value = dec(row.get("DMM_VALLIN")) - dec(row.get("DMM_IMPDTO"))
            movement_currency = str(row.get("DMM_CODMON") or "").strip().upper()[:1]
            target_currency = str(moneda or "E").strip().upper()[:1] or "E"
            if target_currency != movement_currency:
                line_value = self.change_price_currency(line_value, movement_currency, target_currency, "P")
            last_price = line_value / quantity

        if str(self.parameter("INCAU", "")).strip().upper() == "S" and last_price != 0:
            art = self.db.fetch_one(
                "SELECT ART_DTOAUM1, ART_DTOAUM2, ART_DTOAUM3, ART_DTOAUM4, ART_DTOAUM5, ART_DTOAUM6, ART_DTOAUM7, ART_IMPFIJ "
                "FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                (self.settings.empresa, codart),
            )
            if art:
                for key in ("ART_DTOAUM1", "ART_DTOAUM2", "ART_DTOAUM3", "ART_DTOAUM4", "ART_DTOAUM5", "ART_DTOAUM6", "ART_DTOAUM7"):
                    last_price *= Decimal("1") + dec(art.get(key)) / Decimal("100")
                if dec(art.get("ART_IMPFIJ")) != 0:
                    last_price += dec(art.get("ART_IMPFIJ"))
        return last_price

    def average_cost(self, codart: str, fecha: date, moneda: str = "E") -> Decimal:
        row = self.db.fetch_one(
            """
            SELECT FIRST 1 ARTM_COSMED, ARTM_CODMON, ARTM_FECFIN, ARTM_CANPRE
            FROM ARTICULM
            WHERE ARTM_NUMEMP=? AND ARTM_CODART=? AND ARTM_FECFIN <= ?
            ORDER BY ARTM_FECFIN DESC
            """,
            (self.settings.empresa, codart, fecha),
        )
        if not row:
            return self.last_purchase_cost(codart, fecha, moneda)

        price = dec(row.get("ARTM_COSMED"))
        average_currency = str(row.get("ARTM_CODMON") or "").strip().upper()[:1]
        target_currency = str(moneda or "E").strip().upper()[:1] or "E"
        if target_currency != average_currency:
            price = self.change_price_currency(price, average_currency, target_currency, "P")
        return price

    def article_no_contable_flag(self, codart: str) -> str:
        if not str(codart or "").strip():
            return ""
        row = self.db.fetch_one(
            """
            SELECT FIRST 1 ARTI_DESCRI
            FROM ARTICULI
            WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_NUMLIN > 0 AND ARTI_CODINF=?
            """,
            (self.settings.empresa, str(codart).strip(), "NOCON"),
        )
        return str(row.get("ARTI_DESCRI") or "").strip() if row else ""

    def article_cost_price(self, codart: str, fecha: date, moneda: str = "E") -> dict[str, Any]:
        codart = str(codart or "").strip()
        if not codart:
            raise FaroError("codart es obligatorio")
        moneda = str(moneda or "E").strip().upper()[:1] or "E"

        no_contable = self.article_no_contable_flag(codart)
        mode = str(self.parameter("RENTAB", "PBASE") or "PBASE").strip().upper()
        if no_contable == "N":
            price = Decimal("0")
            source = "no_contable"
        elif mode == "PBASE":
            price = self.article_base_price(codart, moneda)
            source = "precio_base"
        elif mode == "PCOSTE":
            price = self.article_file_cost(codart, moneda)
            source = "precio_coste_ficha"
        elif mode == "PMEDIO":
            price = self.average_cost(codart, fecha, moneda)
            source = "coste_medio"
        else:
            price = self.last_purchase_cost(codart, fecha, moneda)
            source = "coste_ultimo"

        return {
            "codart": codart,
            "fecha": fecha.isoformat(),
            "moneda": moneda,
            "modo_rentabilidad": mode,
            "fuente": source,
            "precio_coste": normalize(price),
            "no_contable": no_contable,
            "forzado_a_cero": no_contable == "N",
        }

    def calculate_article_price(self, article: dict[str, Any]) -> dict[str, Any]:
        art = dict(article)
        art["ART_PRECOS"] = (
            dec(art["ART_PREBAS"])
            * (1 + dec(art["ART_DTOAUM1"]) / 100)
            * (1 + dec(art["ART_DTOAUM2"]) / 100)
            * (1 + dec(art["ART_DTOAUM3"]) / 100)
            * (1 + dec(art["ART_DTOAUM4"]) / 100)
            * (1 + dec(art["ART_DTOAUM5"]) / 100)
            * (1 + dec(art["ART_DTOAUM6"]) / 100)
            * (1 + dec(art["ART_DTOAUM7"]) / 100)
        )
        if art["ART_TIPPRE"] != "C":
            art["ART_PRECOS"] += dec(art["ART_IMPFIJ"])
        art["ART_PRECOS"] = redondea(dec(art["ART_PRECOS"]), int(self.parameter("NUMDEC", "2") or "2"))

        if dec(art["ART_CANPRE"]) != 0:
            precos = dec(art["ART_PRECOS"]) / dec(art["ART_CANPRE"])
        else:
            precos = self.provider_conversion_cost(art)

        tippre = str(art["ART_TIPPRE"] or "")
        currency = str(art["ART_CODMON"] or "E")
        if tippre[:1] in ("V", "C"):
            if int(art["ART_TABPREC"] or 0) == 0:
                art["ART_TABPREC"] = int(self.parameter("TABLA", "0") or 0)
            if int(art["ART_TABPREC"] or 0) == 0:
                for key in ("ART_PREVEN1", "ART_PREVEN2", "ART_PREVEN3", "ART_PREVEN4", "ART_PVP"):
                    art[key] = Decimal("0")
            else:
                table = self.get_price_table(int(art["ART_TABPREC"]))
                tax = self.get_tax(int(art["ART_TIPIVA"]))
                if self.parameter("TIPPRE", "") == "2":
                    if dec(table["TPR_PORAUM4"]) != 0:
                        art["ART_PREVEN4"] = precos * (1 + dec(table["TPR_PORAUM4"]) / 100)
                    else:
                        art["ART_PREVEN4"] = dec(art["ART_PREBAS"])
                        if dec(art["ART_CANPRE"]) != 0:
                            art["ART_PREVEN4"] = self.round_price(
                                dec(art["ART_PREBAS"]) / dec(art["ART_CANPRE"]), currency, "P"
                            )
                    if tippre == "C":
                        art["ART_PREVEN4"] = dec(art["ART_PREVEN4"]) + dec(art["ART_IMPFIJ"])
                    art["ART_PVP"] = dec(art["ART_PREVEN4"]) * (1 + dec(tax["TIV_PORIVA"]) / 100)
                    adjustment = dec(table["TPR_AJUSTEP"] if currency == "P" else table["TPR_AJUSTEE"])
                    art["ART_PVP"] = self.adjust_price(dec(art["ART_PVP"]), adjustment, currency)
                    p1 = (dec(table["TPR_PORAUM1"]) / 100) / (1 + dec(table["TPR_PORAUM1"]) / 100)
                    p2 = (dec(table["TPR_PORAUM2"]) / 100) / (1 + dec(table["TPR_PORAUM2"]) / 100)
                    p3 = (dec(table["TPR_PORAUM3"]) / 100) / (1 + dec(table["TPR_PORAUM3"]) / 100)
                    art["ART_PREVEN1"] = dec(art["ART_PREVEN4"]) * (1 - p3)
                    art["ART_PREVEN2"] = dec(art["ART_PREVEN4"]) * (1 - p2)
                    art["ART_PREVEN3"] = dec(art["ART_PREVEN4"]) * (1 - p1)
                else:
                    art["ART_PREVEN1"] = precos * (1 + dec(table["TPR_PORAUM1"]) / 100)
                    art["ART_PREVEN2"] = precos * (1 + dec(table["TPR_PORAUM2"]) / 100)
                    art["ART_PREVEN3"] = precos * (1 + dec(table["TPR_PORAUM3"]) / 100)
                    art["ART_PREVEN4"] = precos * (1 + dec(table["TPR_PORAUM4"]) / 100)
                    if tippre == "C":
                        for key in ("ART_PREVEN1", "ART_PREVEN2", "ART_PREVEN3", "ART_PREVEN4"):
                            art[key] = dec(art[key]) + dec(art["ART_IMPFIJ"])
                    art["ART_PVP"] = dec(art["ART_PREVEN4"]) * (1 + dec(tax["TIV_PORIVA"]) / 100)
                    adjustment = dec(table["TPR_AJUSTEP"] if currency == "P" else table["TPR_AJUSTEE"])
                    art["ART_PVP"] = self.adjust_price(dec(art["ART_PVP"]), adjustment, currency)
                    art["ART_PREVEN4"] = dec(art["ART_PVP"]) / (1 + dec(tax["TIV_PORIVA"]) / 100)
        else:
            tax = self.get_tax(int(art["ART_TIPIVA"]))
            if dec(art["ART_PVP"]) != 0:
                art["ART_PREVEN4"] = dec(art["ART_PVP"]) / (1 + dec(tax["TIV_PORIVA"]) / 100)
            elif dec(art["ART_PREVEN4"]) != 0:
                art["ART_PVP"] = dec(art["ART_PREVEN4"]) * (1 + dec(tax["TIV_PORIVA"]) / 100)
            if int(art["ART_TABPREC"] or 0) != 0:
                table = self.get_price_table(int(art["ART_TABPREC"]))
                art["ART_PREVEN4"] = self.round_price(dec(art["ART_PREVEN4"]), currency, "P")
                art["ART_PREVEN1"] = dec(art["ART_PREVEN4"]) * (
                    (1 + dec(table["TPR_PORAUM1"]) / 100) / (1 + dec(table["TPR_PORAUM4"]) / 100)
                )
                art["ART_PREVEN2"] = dec(art["ART_PREVEN4"]) * (
                    (1 + dec(table["TPR_PORAUM2"]) / 100) / (1 + dec(table["TPR_PORAUM4"]) / 100)
                )
                art["ART_PREVEN3"] = dec(art["ART_PREVEN4"]) * (
                    (1 + dec(table["TPR_PORAUM3"]) / 100) / (1 + dec(table["TPR_PORAUM4"]) / 100)
                )
            else:
                for key in ("ART_PREVEN1", "ART_PREVEN2", "ART_PREVEN3"):
                    if dec(art[key]) == 0:
                        art[key] = dec(art["ART_PREVEN4"])

        for key in ("ART_PREVEN1", "ART_PREVEN2", "ART_PREVEN3", "ART_PREVEN4"):
            art[key] = self.round_price(dec(art[key]), currency, "P")
        art["ART_PVP"] = self.round_price(dec(art["ART_PVP"]), currency, "I")
        if dec(art["ART_PREVEN4"]) > 0 and dec(art["ART_PVP"]) == 0:
            art["ART_PVP"] = Decimal("0.01")
        return normalize(art)

    def simulate_price_table_change(self, codart: str, new_table: int) -> dict[str, Any]:
        current = self.get_article(codart)
        self.get_price_table(new_table)
        proposed = dict(current)
        proposed["ART_TABPREC"] = int(new_table)
        recalculated = self.calculate_article_price(proposed)
        return {
            "article": codart,
            "empresa": self.settings.empresa,
            "current": pick(current, ["ART_CODART", "ART_DESCRI"] + ARTICLE_PRICE_FIELDS),
            "proposed": pick(recalculated, ["ART_CODART", "ART_DESCRI"] + ARTICLE_PRICE_FIELDS),
            "diff": diff(pick(current, ARTICLE_PRICE_FIELDS), pick(recalculated, ARTICLE_PRICE_FIELDS)),
            "blocked_warning": "Articulo blister: escritura bloqueada por defecto."
            if current.get("ART_INDBLI") == "S"
            else None,
        }

    def change_article_price_table(
        self,
        codart: str,
        new_table: int,
        force_blister_current_cost: bool = False,
    ) -> dict[str, Any]:
        current = self.get_article(codart)
        if current.get("ART_INDBLI") == "S" and not force_blister_current_cost:
            raise FaroError(
                "Articulo blister. Delphi puede recalcular coste desde componentes; "
                "repita con force_blister_current_cost=true si desea usar el coste actual."
            )
        simulated = self.simulate_price_table_change(codart, new_table)
        proposed = simulated["proposed"]
        pvp_changed = dec(current["ART_PVP"]) != dec(proposed["ART_PVP"])

        fields = [
            "ART_PRECOS",
            "ART_TABPREC",
            "ART_PREVEN1",
            "ART_PREVEN2",
            "ART_PREVEN3",
            "ART_PREVEN4",
            "ART_PVP",
            "ART_FECMOD",
            "ART_USUMOD",
        ]
        values: list[Any] = [
            proposed["ART_PRECOS"],
            proposed["ART_TABPREC"],
            proposed["ART_PREVEN1"],
            proposed["ART_PREVEN2"],
            proposed["ART_PREVEN3"],
            proposed["ART_PREVEN4"],
            proposed["ART_PVP"],
            datetime.now(),
            self.settings.usuario,
        ]
        set_sql = ", ".join(f"{field}=?" for field in fields)
        if pvp_changed:
            set_sql += ", ART_FECVAR=?"
            values.append(date.today())
        values.extend([self.settings.empresa, codart])
        try:
            self.db.execute(
                f"UPDATE ARTICUL SET {set_sql} WHERE ART_NUMEMP=? AND ART_CODART=?",
                tuple(values),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        after = self.get_article(codart)
        return {
            "article": codart,
            "empresa": self.settings.empresa,
            "updated": True,
            "pvp_changed": pvp_changed,
            "diff": diff(pick(current, ARTICLE_PRICE_FIELDS), pick(after, ARTICLE_PRICE_FIELDS)),
            "after": pick(after, ["ART_CODART", "ART_DESCRI"] + ARTICLE_PRICE_FIELDS),
        }

    def _supplier_tariff_article(
        self, line: dict[str, Any], proveedor: int, required: bool = True
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Resuelve el articulo como IMPTAR_U: codigo, codigo de barras o referencia de proveedor.

        Si ``required`` es False y no se encuentra el articulo por ninguna via
        -incluido el caso de que la linea no informe ningun identificador en
        absoluto-, devuelve ``(None, None)`` en vez de lanzar, para que el
        llamador pueda darlo de alta (ver ``dar_de_alta`` en
        ``update_supplier_tariff``), incluyendo autogenerar el codigo cuando
        la linea no trae ni articulo ni referencia_proveedor (ver
        ``_generar_codigo_articulo``). Con ``required=True`` (comportamiento
        por defecto, ``dar_de_alta=false``) la falta total de identificadores
        sigue siendo siempre un error.
        """
        codart = str(line.get("articulo") or "").strip()
        barcode = str(line.get("codigo_barras") or "").strip()
        refpro = str(line.get("referencia_proveedor") or "").strip()
        resolution = "articulo"

        if codart:
            article = self.db.fetch_one(
                "SELECT * FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                (self.settings.empresa, codart),
            )
            if article:
                return normalize(article), resolution

        if barcode:
            barcode_row = self.db.fetch_one(
                "SELECT ARTC_CODART FROM ARTICULC WHERE ARTC_NUMEMP=? AND ARTC_CODIGO=?",
                (self.settings.empresa, barcode),
            )
            if barcode_row and barcode_row.get("ARTC_CODART"):
                codart = str(barcode_row["ARTC_CODART"]).strip()
                article = self.db.fetch_one(
                    "SELECT * FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                    (self.settings.empresa, codart),
                )
                if article:
                    return normalize(article), "codigo_barras"

        if refpro:
            supplier_row = self.db.fetch_one(
                "SELECT FIRST 1 ARTP_CODART FROM ARTICULP "
                "WHERE ARTP_NUMEMP=? AND ARTP_CODPRO=? AND ARTP_REFPRO=? ORDER BY ARTP_CODART",
                (self.settings.empresa, int(proveedor), refpro),
            )
            if supplier_row and supplier_row.get("ARTP_CODART"):
                codart = str(supplier_row["ARTP_CODART"]).strip()
                article = self.db.fetch_one(
                    "SELECT * FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                    (self.settings.empresa, codart),
                )
                if article:
                    return normalize(article), "referencia_proveedor"

        identifiers = []
        if str(line.get("articulo") or "").strip():
            identifiers.append(f"articulo={line['articulo']}")
        if barcode:
            identifiers.append(f"codigo_barras={barcode}")
        if refpro:
            identifiers.append(f"referencia_proveedor={refpro}")
        if not required:
            # dar_de_alta=true: ni resolver por identificador ni exigir uno.
            # Una linea sin articulo/codigo_barras/referencia_proveedor puede
            # seguir dando de alta el articulo con un codigo autogenerado
            # (ver _create_article_for_tariff_alta); si tampoco hay
            # descripcion/seccion/etc. ese metodo lanzara su propio error.
            return None, None
        if not identifiers:
            raise FaroError(
                "Cada linea de tarifa requiere articulo, codigo_barras o referencia_proveedor."
            )
        raise FaroError("Articulo no encontrado para la tarifa: " + ", ".join(identifiers))

    def _create_article_for_tariff_alta(
        self,
        raw_line: dict[str, Any],
        proveedor: int,
        precio_base: Decimal,
        usar_referencia_proveedor_como_codigo: bool = False,
        codigo_gen_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Replica la rama ``ELSE IF B_ALTA.Checked`` de IMPTAR_U.pas (lineas
        1999-2069): cuando la linea no resuelve a un articulo existente y
        ``dar_de_alta=true``, inserta ARTICUL (via INSERTAR_ARTICUL de
        ARTICUL_UDM.pas) con los mismos valores por defecto que usa esa
        pantalla (IMPTAR_U.pas:1668-1717) mas los campos que la rama de alta
        toma de la fila del fichero (CANON/TARIFA/PVP/ART_CANPMI/CODFAM/
        SUBFAM/NORMA/TABPREC/SECCION). La insercion de ARTICULP la hace el
        llamador (``update_supplier_tariff``) reutilizando el mismo camino ya
        existente para "alta de tarifa sobre articulo existente".

        Resolucion del codigo de articulo, en el mismo orden que
        IMPTAR_U.pas:1727-1742:
        1. Si la linea informa ``articulo`` explicitamente, se usa tal cual
           (``T_ARTICUL.FieldByName('ART_CODART').AsString <> ''``).
        2. Si no, y ``usar_referencia_proveedor_como_codigo`` es true (replica
           B_REFPRO marcada), se usa ``referencia_proveedor`` de la linea.
        3. Si no, se autogenera con ``_generar_codigo_articulo``: seccion +
           proveedor a 4 digitos + un contador de ancho
           ``digitos_codigo_articulo - 5``, incrementando el contador hasta
           encontrar un codigo libre (replica el bucle ``WHILE EXISTE DO``).
           ``codigo_gen_state`` lo prepara y comparte ``update_supplier_tariff``
           para todo el lote, igual que CONTADOR en Delphi no se reinicia
           entre lineas de un mismo proceso de importacion.
        """
        codart = str(raw_line.get("articulo") or "").strip()
        descripcion = str(raw_line.get("descripcion") or "").strip()
        seccion = str(raw_line.get("seccion") or "").strip()
        tipo_iva_raw = raw_line.get("tipo_iva")
        tipo_precio = str(raw_line.get("tipo_precio") or "").strip()
        unidad_medida = str(raw_line.get("unidad_medida") or "").strip()

        missing = [
            name for name, value in (
                ("descripcion", descripcion), ("seccion", seccion),
                ("tipo_precio", tipo_precio), ("unidad_medida", unidad_medida),
            ) if not value
        ]
        if tipo_iva_raw in (None, ""):
            missing.append("tipo_iva")
        if missing:
            raise FaroError(
                "dar_de_alta=true requiere " + ", ".join(missing) + " en la linea del articulo "
                + (codart or "(sin codigo)") +
                " porque todavia no existe (replica la rama B_ALTA de IMPTAR_U.pas)."
            )
        try:
            tipiva_int = int(tipo_iva_raw)
        except (TypeError, ValueError) as exc:
            raise FaroError(f"tipo_iva invalido: {tipo_iva_raw}") from exc

        if not codart:
            refpro_line = str(raw_line.get("referencia_proveedor") or "").strip()
            if usar_referencia_proveedor_como_codigo:
                if not refpro_line:
                    raise FaroError(
                        "usar_referencia_proveedor_como_codigo=true requiere referencia_proveedor "
                        "en la linea del articulo porque todavia no existe (replica B_REFPRO marcada "
                        "de IMPTAR_U.pas)."
                    )
                codart = refpro_line
            else:
                if codigo_gen_state is None:
                    raise FaroError(
                        "No se pudo generar el codigo de articulo: estado de generacion no inicializado."
                    )
                codart = self._generar_codigo_articulo(seccion, proveedor, codigo_gen_state)

        canon_raw = raw_line.get("canon")
        has_canon = canon_raw not in (None, "")
        if has_canon:
            # IMPTAR_U.pas: un CANON valido fuerza ART_TIPPRE='C' aunque se
            # haya pedido otro tipo_precio.
            tipo_precio = "C"

        discounts = [self._supplier_line_discount(raw_line, i, 0) for i in range(1, 7)]
        net_cost = self._supplier_net_cost({
            "ARTP_PREBAS": precio_base,
            "ARTP_CODMON": "E",
            **{f"ARTP_DTOAUM{i}": discounts[i - 1] for i in range(1, 7)},
        })

        # Conversion Compra: IMPTAR_U.pas:2046-2053. A diferencia de la rama
        # de modificacion (que normaliza 0->1 antes de comparar, ver
        # _update_sale_price_from_supplier_tariff), la rama de alta compara
        # los valores de ARTP_CANCON/ARTP_CANVEN tal cual y con '> 1' en vez
        # de '<> 1'; se replica ese matiz literalmente.
        cancon = dec(raw_line.get("cantidad_conversion_compra"), "1")
        canven = dec(raw_line.get("cantidad_conversion_venta"), "1")
        canpre = Decimal("1")
        if cancon > 1 or canven > 1:
            if canven > cancon:
                canpre = canven / cancon
            elif canven < cancon:
                canpre = Decimal("0")

        now = datetime.now()
        today = date.today()
        art: dict[str, Any] = {
            "ART_NUMEMP": self.settings.empresa,
            "ART_CODART": codart,
            "ART_DESCRI": descripcion[:100],
            "ART_SECCIO": seccion,
            "ART_INDPROP": "S",
            "ART_INDBLI": "N",
            "ART_TIPPRE": tipo_precio,
            "ART_INDINV": "S",
            "ART_OBSOL": "N",
            "ART_FEALTA": today,
            "ART_FEBAJA": None,
            "ART_FECMOV": None,
            "ART_FECVAR": today,
            "ART_CODFAM": int(raw_line.get("familia") or 0),
            "ART_SUBFAM": int(raw_line.get("subfamilia") or 0),
            "ART_TIPIVA": tipiva_int,
            "ART_PRETAR": dec(raw_line.get("tarifa"), "0"),
            "ART_FECTAR": None,
            "ART_PREBAS": net_cost,
            "ART_DTOAUM1": Decimal("0"), "ART_DTOAUM2": Decimal("0"), "ART_DTOAUM3": Decimal("0"),
            "ART_DTOAUM4": Decimal("0"), "ART_DTOAUM5": Decimal("0"), "ART_DTOAUM6": Decimal("0"),
            "ART_DTOAUM7": Decimal("0"),
            "ART_IMPFIJ": dec(canon_raw, "0") if has_canon else Decimal("0"),
            "ART_PRECOS": Decimal("0"),
            "ART_TABPREC": int(raw_line.get("tabla_precios") or 0),
            "ART_PREVEN1": Decimal("0"), "ART_PREVEN2": Decimal("0"),
            "ART_PREVEN3": Decimal("0"), "ART_PREVEN4": Decimal("0"),
            "ART_PVP": dec(raw_line.get("pvp"), "0"),
            "ART_CODMON": "E",
            "ART_UNIMED": unidad_medida,
            "ART_CANPRE": canpre,
            "ART_CANPMI": dec(raw_line.get("cantidad_pedido_minimo"), "0"),
            "ART_CODPRO": int(proveedor),
            "ART_OBSINT": "Alta automatica via tarifa_proveedor_actualizar (MCP)",
            "ART_OBSFOR": "",
            "ART_FECMOD": now,
            "ART_USUMOD": f"{self.settings.centro} {self.settings.usuario}",
            "ART_AGRUP1": 0, "ART_AGRUP2": 0, "ART_AGRUP3": 0,
            "ART_NORMA": str(raw_line.get("norma") or ""),
        }

        # calculate_article_price() devuelve el dict pasado por normalize()
        # (Decimal->str, date/datetime->ISO string), que es el formato ya
        # usado en otros UPDATE de este mismo fichero (p.ej.
        # _update_sale_price_from_supplier_tariff). Para el INSERT de un
        # articulo nuevo mantenemos el resto de campos (fechas, texto,
        # ART_PREBAS) con sus tipos Python originales -tal como hace ya el
        # INSERT de ARTICULP mas abajo- y solo tomamos de ahi los campos que
        # esta funcion realmente calcula.
        priced = self.calculate_article_price(art)
        for key in ("ART_PRECOS", "ART_TABPREC", "ART_PREVEN1", "ART_PREVEN2", "ART_PREVEN3", "ART_PREVEN4", "ART_PVP"):
            art[key] = priced.get(key)

        insert_fields = [
            "ART_NUMEMP", "ART_CODART", "ART_DESCRI", "ART_SECCIO", "ART_INDPROP", "ART_INDBLI", "ART_TIPPRE",
            "ART_INDINV", "ART_OBSOL", "ART_FEALTA", "ART_FEBAJA", "ART_FECMOV", "ART_FECVAR", "ART_CODFAM",
            "ART_SUBFAM", "ART_TIPIVA", "ART_PRETAR", "ART_FECTAR", "ART_PREBAS", "ART_DTOAUM1", "ART_DTOAUM2",
            "ART_DTOAUM3", "ART_DTOAUM4", "ART_DTOAUM5", "ART_DTOAUM6", "ART_DTOAUM7", "ART_IMPFIJ", "ART_PRECOS",
            "ART_TABPREC", "ART_PREVEN1", "ART_PREVEN2", "ART_PREVEN3", "ART_PREVEN4", "ART_PVP", "ART_CODMON",
            "ART_UNIMED", "ART_CANPRE", "ART_CANPMI", "ART_CODPRO", "ART_OBSINT", "ART_OBSFOR", "ART_FECMOD",
            "ART_USUMOD", "ART_AGRUP1", "ART_AGRUP2", "ART_AGRUP3", "ART_NORMA",
        ]
        self.db.execute(
            "INSERT INTO ARTICUL (" + ", ".join(insert_fields) + ") VALUES (" +
            ", ".join("?" for _ in insert_fields) + ")",
            tuple(art.get(field) for field in insert_fields),
        )

        barcode = str(raw_line.get("codigo_barras") or "").strip()
        if barcode:
            # IMPTAR_U.pas:2067-2069: inserta el codigo de barras usado para
            # la busqueda (R_ARTC.ARTC_CODIGO) junto con el alta.
            self.db.execute(
                "INSERT INTO ARTICULC (ARTC_NUMEMP, ARTC_CODART, ARTC_CODIGO, ARTC_CANTID) VALUES (?, ?, ?, ?)",
                (self.settings.empresa, codart, barcode, Decimal("1")),
            )

        return art

    def _init_codigo_articulo_gen_state(
        self, digitos_codigo_articulo: int, numerador_inicial: int
    ) -> dict[str, Any]:
        """Prepara el estado compartido para autogenerar ART_CODART durante
        todo un lote de ``update_supplier_tariff`` (replica CEROS/CONTADOR de
        IMPTAR_U.pas, inicializados una sola vez por ejecucion en
        INICIALIZAR_VARIABLES, IMPTAR_U.pas:1570-1583 y 1629).

        ``digitos_codigo_articulo`` es el numero total de digitos de
        ART_CODART (seccion + proveedor a 4 digitos + contador); replica
        B_DIGITOS (TRxSpinEdit, MinValue=8, MaxValue=15, IMPTAR_U.dfm:1879).
        ``numerador_inicial`` es el valor inicial del contador; replica
        NumInicial (IMPTAR_U.dfm:1911, "Numerador inicial para el codigo").
        """
        try:
            digitos = int(digitos_codigo_articulo)
        except (TypeError, ValueError) as exc:
            raise FaroError(f"digitos_codigo_articulo invalido: {digitos_codigo_articulo}") from exc
        if digitos < 8 or digitos > 15:
            raise FaroError(
                "digitos_codigo_articulo debe estar entre 8 y 15 (igual que B_DIGITOS en IMPTAR_U.pas)."
            )
        try:
            contador_inicial = int(numerador_inicial)
        except (TypeError, ValueError) as exc:
            raise FaroError(f"numerador_inicial invalido: {numerador_inicial}") from exc
        if contador_inicial < 0:
            raise FaroError("numerador_inicial no puede ser negativo.")
        return {
            "contador": contador_inicial,
            "ancho_contador": digitos - 5,
            "usados": set(),
        }

    def _generar_codigo_articulo(self, seccion: str, proveedor: int, state: dict[str, Any]) -> str:
        """Replica la generacion automatica de ART_CODART de IMPTAR_U.pas
        (IMPTAR_U.pas:1727-1742): seccion (tal cual la informa la linea,
        normalmente 1 digito) + proveedor formateado a un minimo de 4
        digitos (FORMATFLOAT('0000', CODPRO)) + un contador formateado al
        ancho ``digitos_codigo_articulo - 5`` (FORMATFLOAT(CEROS, CONTADOR)).
        Si el codigo ya existe (en ARTICUL o ya generado antes en este mismo
        lote), incrementa el contador y reintenta -el mismo bucle
        ``WHILE EXISTE DO`` de Delphi-; si esta libre, el contador se deja
        tal cual (no se incrementa en el caso de exito, igual que en Delphi:
        solo vuelve a coincidir con un articulo ya insertado en la siguiente
        llamada, momento en el que se detecta y se incrementa).
        """
        ancho = state["ancho_contador"]
        while True:
            contador = state["contador"]
            codigo = f"{seccion}{int(proveedor):04d}{contador:0{ancho}d}"
            if codigo in state["usados"] or self._articulo_existe(codigo):
                state["contador"] += 1
                continue
            state["usados"].add(codigo)
            return codigo

    def _articulo_existe(self, codart: str) -> bool:
        row = self.db.fetch_one(
            "SELECT * FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        return row is not None

    def _supplier_tariff_current(self, codart: str, proveedor: int) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT FIRST 1 * FROM ARTICULP "
            "WHERE ARTP_NUMEMP=? AND ARTP_CODART=? AND ARTP_CODPRO=? ORDER BY ARTP_REFPRO",
            (self.settings.empresa, codart, int(proveedor)),
        )
        return normalize(row) if row else None

    @staticmethod
    def _supplier_line_discount(line: dict[str, Any], index: int, current: Any = 0) -> Decimal:
        key = f"descuento{index}"
        if key in line:
            return dec(line.get(key))
        compact = line.get("descuentos")
        if isinstance(compact, list) and len(compact) >= index:
            return dec(compact[index - 1])
        return dec(current)

    def _supplier_net_cost(self, artp: dict[str, Any]) -> Decimal:
        value = dec(artp.get("ARTP_PREBAS"))
        for index in range(1, 7):
            value *= Decimal("1") - dec(artp.get(f"ARTP_DTOAUM{index}")) / Decimal("100")
        return self.round_price(value, str(artp.get("ARTP_CODMON") or "E"), "P")

    def _update_sale_price_from_supplier_tariff(
        self,
        article: dict[str, Any],
        artp: dict[str, Any],
        proveedor: int,
        descripcion_articulo: str | None = None,
        solo_si_sube_precio: bool = False,
        solo_proveedor_principal: bool = False,
        solo_si_propio: bool = False,
        generar_etiquetas: bool = False,
        etiqueta_modelo: int = 0,
    ) -> dict[str, Any]:
        """Replica el bloque MODIFICAR_PVENTA de IMPTAR_U.pas, incluidas las
        casillas "Opciones Proceso" que controlan si se propaga o no el nuevo
        coste al precio de venta (B_PRINCIPAL, B_PROPIO, B_MAS), si se
        sobreescribe la descripcion del articulo (mitad de B_DESCRI que toca
        ARTICUL, no solo ARTICULP) y si se genera una etiqueta (B_ETIQUETAS).
        """
        if solo_proveedor_principal and int(article.get("ART_CODPRO") or 0) != int(proveedor):
            return {"actualizado": False, "omitido_por": "proveedor_no_principal"}
        if solo_si_propio and str(article.get("ART_INDPROP") or "") == "N":
            return {"actualizado": False, "omitido_por": "articulo_no_propio"}

        proposed = dict(article)
        proposed["ART_PREBAS"] = self._supplier_net_cost(artp)

        # B_MAS: si el coste nuevo es menor que el anterior, IMPTAR_U.pas no
        # toca en absoluto el precio de venta (la tarifa de compra en
        # ARTICULP ya se ha actualizado fuera de este metodo).
        previous_cost = dec(article.get("ART_PREBAS"))
        if solo_si_sube_precio and previous_cost > proposed["ART_PREBAS"]:
            return {"actualizado": False, "omitido_por": "precio_no_sube"}

        cancon = dec(artp.get("ARTP_CANCON"), "1")
        canven = dec(artp.get("ARTP_CANVEN"), "1")
        if cancon == 0:
            cancon = Decimal("1")
        if canven == 0:
            canven = Decimal("1")
        if cancon != 1 or canven != 1:
            if canven > cancon:
                proposed["ART_CANPRE"] = canven / cancon
            elif canven < cancon:
                proposed["ART_CANPRE"] = Decimal("0")

        nueva_descripcion = None
        if descripcion_articulo:
            nueva_descripcion = str(descripcion_articulo)[:100]
            proposed["ART_DESCRI"] = nueva_descripcion

        recalculated = self.calculate_article_price(proposed)
        pvp_changed = dec(article.get("ART_PVP")) != dec(recalculated.get("ART_PVP"))
        fields = [
            "ART_PREBAS", "ART_PRECOS", "ART_CANPRE", "ART_TABPREC",
            "ART_PREVEN1", "ART_PREVEN2", "ART_PREVEN3", "ART_PREVEN4", "ART_PVP",
            "ART_FECMOD", "ART_USUMOD",
        ]
        values: list[Any] = [
            recalculated.get("ART_PREBAS"), recalculated.get("ART_PRECOS"), recalculated.get("ART_CANPRE"),
            recalculated.get("ART_TABPREC"), recalculated.get("ART_PREVEN1"), recalculated.get("ART_PREVEN2"),
            recalculated.get("ART_PREVEN3"), recalculated.get("ART_PREVEN4"), recalculated.get("ART_PVP"),
            datetime.now(), self.settings.usuario,
        ]
        if pvp_changed:
            fields.append("ART_FECVAR")
            values.append(date.today())
        if nueva_descripcion is not None:
            fields.append("ART_DESCRI")
            values.append(nueva_descripcion)
        self.db.execute(
            f"UPDATE ARTICUL SET {', '.join(field + '=?' for field in fields)} "
            "WHERE ART_NUMEMP=? AND ART_CODART=?",
            tuple(values + [self.settings.empresa, article["ART_CODART"]]),
        )

        etiqueta_generada = False
        if generar_etiquetas and pvp_changed:
            self._queue_price_label(
                str(article["ART_CODART"]),
                nueva_descripcion or str(article.get("ART_DESCRI") or ""),
                etiqueta_modelo,
            )
            etiqueta_generada = True

        return {
            "actualizado": True,
            "pvp_modificado": pvp_changed,
            "descripcion_actualizada": nueva_descripcion,
            "etiqueta_generada": etiqueta_generada,
            "coste_neto": normalize(recalculated.get("ART_PREBAS")),
            "precios": pick(recalculated, ["ART_PRECOS", "ART_PREVEN1", "ART_PREVEN2", "ART_PREVEN3", "ART_PREVEN4", "ART_PVP"]),
        }

    def _queue_price_label(self, codart: str, descripcion: str, modelo: int) -> None:
        """Replica INSERTAR_ETIQUE/GRABAR_ETIQUE('G') de ETIQUE_UDM.pas para
        una etiqueta generada automaticamente tras un cambio de precio.

        Nota de fidelidad: GRABAR_ETIQUE resuelve el modelo por defecto via
        MODELO_ETIQUETA_ARTICUL cuando no se informa uno explicito; esa
        funcion no se ha podido localizar en las fuentes Delphi disponibles
        (no esta en ARTICUL_UDM.pas, ETIQUE_UDM.pas, MODETI_UDM.pas ni
        LIBTIP_U.pas), asi que aqui se exige el modelo como parametro
        (`etiqueta_modelo`, por defecto 0, igual que el valor de respaldo del
        propio Delphi cuando esa resolucion automatica no encuentra nada).
        La descripcion corta (ARTICULI/ARTI_CODINF='DESCO') sí se replica,
        igual que en GRABAR_ETIQUE.
        """
        descri_corta = self._article_additional_info(codart, "DESCO")
        texto = ""
        if descri_corta:
            texto = str(descri_corta.get("ARTI_DESCRI") or "").strip()
        if not texto:
            texto = str(descripcion or "").strip()
        self.db.execute(
            "INSERT INTO ETIQUE (ETI_NUMEMP, ETI_CODART, ETI_DESCRI, ETI_CANTID, ETI_IMPRIM, ETI_MODELO, ETI_DESCRI2) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.settings.empresa, codart, texto[:100], Decimal("1"), "S", int(modelo or 0), ""),
        )

    def update_supplier_tariff(
        self,
        proveedor: int,
        lineas: list[dict[str, Any]],
        actualizar_precio_venta: bool = False,
        solo_si_sube_precio: bool = False,
        solo_proveedor_principal: bool = False,
        solo_si_propio: bool = False,
        generar_etiquetas: bool = False,
        etiqueta_modelo: int = 0,
        dar_de_alta: bool = False,
        usar_referencia_proveedor_como_codigo: bool = False,
        digitos_codigo_articulo: int = 9,
        numerador_inicial: int = 0,
    ) -> dict[str, Any]:
        """Alta/actualiza tarifas de proveedor siguiendo IMPTAR_U.pas.

        Toda la llamada es atomica: si una linea falla se revierte el lote completo.
        Los parametros ``solo_si_sube_precio``/``solo_proveedor_principal``/
        ``solo_si_propio``/``generar_etiquetas``/``etiqueta_modelo`` solo tienen
        efecto cuando ``actualizar_precio_venta`` es true; replican las
        casillas "Opciones Proceso" B_MAS/B_PRINCIPAL/B_PROPIO/B_ETIQUETAS de
        IMPTAR_U.pas (ver revision-tarifa-proveedor-actualizar.md).

        Si ``dar_de_alta`` es true, una linea cuyo articulo no exista se da de
        alta (ARTICUL + ARTICULP) en vez de hacer fallar todo el lote,
        replicando la rama ``ELSE IF B_ALTA.Checked`` de IMPTAR_U.pas (ver
        ``_create_article_for_tariff_alta``). Igual que en Delphi, una linea
        de alta nunca pasa por el bloque MODIFICAR_PVENTA (ese bloque solo
        existe en la rama ``IF NOT ALTA``), asi que ``actualizar_precio_venta``
        y sus opciones no tienen efecto sobre las lineas recien creadas.

        Cuando ``dar_de_alta`` es true y una linea no informa ``articulo``,
        el codigo de articulo se resuelve, en este orden (IMPTAR_U.pas:1727-
        1742): ``referencia_proveedor`` de la linea si
        ``usar_referencia_proveedor_como_codigo`` es true (replica B_REFPRO
        marcada), o si no, se autogenera con seccion + proveedor a 4 digitos +
        un contador (replica B_REFPRO sin marcar). ``digitos_codigo_articulo``
        (por defecto 9, entre 8 y 15) fija el numero total de digitos del
        codigo autogenerado y ``numerador_inicial`` (por defecto 0) el valor
        inicial del contador; ambos replican B_DIGITOS y NumInicial de
        IMPTAR_U.pas. El contador se comparte para todo el lote y no se
        reinicia entre lineas, igual que CONTADOR en Delphi.
        """
        provider = self.db.fetch_one(
            "SELECT PRO_CODPRO, PRO_NOMCOR FROM PROVEE WHERE PRO_NUMEMP=? AND PRO_CODPRO=?",
            (self.settings.empresa, int(proveedor)),
        )
        if not provider:
            raise FaroError(f"Proveedor no encontrado: {proveedor}")
        if not lineas:
            raise FaroError("lineas requiere al menos un elemento")

        codigo_gen_state: dict[str, Any] | None = None
        if dar_de_alta:
            codigo_gen_state = self._init_codigo_articulo_gen_state(
                digitos_codigo_articulo, numerador_inicial
            )

        resultados: list[dict[str, Any]] = []
        altas = 0
        modificaciones = 0
        articulos_creados = 0
        venta_actualizada = 0
        etiquetas_generadas = 0
        try:
            for pos, raw_line in enumerate(lineas, start=1):
                if not isinstance(raw_line, dict):
                    raise FaroError(f"La linea {pos} debe ser un objeto")
                if "precio_base" not in raw_line:
                    raise FaroError(f"La linea {pos} requiere precio_base")
                precio_base = dec(raw_line.get("precio_base"))
                if precio_base < 0:
                    raise FaroError(f"La linea {pos} tiene precio_base negativo")

                article, resolved_by = self._supplier_tariff_article(
                    raw_line, int(proveedor), required=not dar_de_alta
                )
                articulo_creado = False
                if article is None:
                    article = self._create_article_for_tariff_alta(
                        raw_line, int(proveedor), precio_base,
                        usar_referencia_proveedor_como_codigo=usar_referencia_proveedor_como_codigo,
                        codigo_gen_state=codigo_gen_state,
                    )
                    resolved_by = "alta"
                    articulo_creado = True
                    articulos_creados += 1
                codart = str(article["ART_CODART"]).strip()
                current = self._supplier_tariff_current(codart, int(proveedor))
                action = "alta_articulo" if articulo_creado else ("modificacion" if current else "alta")

                if current:
                    target = dict(current)
                    previous_price = dec(current.get("ARTP_PREBAS"))
                    target["ARTP_CANPRE"] = previous_price
                else:
                    target = {
                        "ARTP_NUMEMP": self.settings.empresa,
                        "ARTP_CODART": codart,
                        "ARTP_CODPRO": int(proveedor),
                        "ARTP_REFPRO": codart,
                        "ARTP_DESCRI": str(article.get("ART_DESCRI") or "")[:100],
                        "ARTP_UNIMED": str(article.get("ART_UNIMED") or ""),
                        "ARTP_CANCON": Decimal("1"),
                        "ARTP_CANVEN": Decimal("1"),
                        "ARTP_UNIPAQ": Decimal("1"),
                        "ARTP_PREBAS": Decimal("0"),
                        "ARTP_DTOAUM1": Decimal("0"), "ARTP_DTOAUM2": Decimal("0"),
                        "ARTP_DTOAUM3": Decimal("0"), "ARTP_DTOAUM4": Decimal("0"),
                        "ARTP_DTOAUM5": Decimal("0"), "ARTP_DTOAUM6": Decimal("0"),
                        "ARTP_CODMON": str(article.get("ART_CODMON") or "E"),
                        "ARTP_CANPRE": Decimal("1"),
                        "ARTP_UBICA": "", "ARTP_AMPUNIV": "", "ARTP_AJUSTE": "",
                    }
                    previous_price = None

                refpro = str(raw_line.get("referencia_proveedor") or "").strip()
                if refpro:
                    target["ARTP_REFPRO"] = refpro
                elif not str(target.get("ARTP_REFPRO") or "").strip():
                    target["ARTP_REFPRO"] = codart

                if "descripcion" in raw_line:
                    target["ARTP_DESCRI"] = str(raw_line.get("descripcion") or "")[:100]
                if "unidad_medida" in raw_line:
                    target["ARTP_UNIMED"] = str(raw_line.get("unidad_medida") or "")
                if "cantidad_conversion_compra" in raw_line:
                    target["ARTP_CANCON"] = dec(raw_line.get("cantidad_conversion_compra"))
                if "cantidad_conversion_venta" in raw_line:
                    target["ARTP_CANVEN"] = dec(raw_line.get("cantidad_conversion_venta"))
                if "unidades_paquete" in raw_line:
                    target["ARTP_UNIPAQ"] = dec(raw_line.get("unidades_paquete"))
                if "ampliacion_unidad_venta" in raw_line:
                    target["ARTP_AMPUNIV"] = str(raw_line.get("ampliacion_unidad_venta") or "")
                if "ajuste" in raw_line:
                    target["ARTP_AJUSTE"] = str(raw_line.get("ajuste") or "")

                for index in range(1, 7):
                    target[f"ARTP_DTOAUM{index}"] = self._supplier_line_discount(
                        raw_line, index, target.get(f"ARTP_DTOAUM{index}", 0)
                    )
                target["ARTP_PREBAS"] = self.round_price(
                    precio_base, str(target.get("ARTP_CODMON") or article.get("ART_CODMON") or "E"), "P"
                )

                if current:
                    update_fields = [
                        "ARTP_REFPRO", "ARTP_DESCRI", "ARTP_UNIMED", "ARTP_CANCON", "ARTP_CANVEN",
                        "ARTP_UNIPAQ", "ARTP_PREBAS", "ARTP_DTOAUM1", "ARTP_DTOAUM2", "ARTP_DTOAUM3",
                        "ARTP_DTOAUM4", "ARTP_DTOAUM5", "ARTP_DTOAUM6", "ARTP_CODMON", "ARTP_CANPRE",
                        "ARTP_UBICA", "ARTP_AMPUNIV", "ARTP_AJUSTE",
                    ]
                    self.db.execute(
                        "UPDATE ARTICULP SET " + ", ".join(field + "=?" for field in update_fields) +
                        " WHERE ARTP_NUMEMP=? AND ARTP_CODART=? AND ARTP_CODPRO=? AND ARTP_REFPRO=?",
                        tuple([target.get(field) for field in update_fields] + [
                            self.settings.empresa, codart, int(proveedor), current.get("ARTP_REFPRO")
                        ]),
                    )
                    modificaciones += 1
                else:
                    insert_fields = [
                        "ARTP_NUMEMP", "ARTP_CODART", "ARTP_CODPRO", "ARTP_REFPRO", "ARTP_DESCRI", "ARTP_UNIMED",
                        "ARTP_CANCON", "ARTP_CANVEN", "ARTP_UNIPAQ", "ARTP_PREBAS", "ARTP_DTOAUM1", "ARTP_DTOAUM2",
                        "ARTP_DTOAUM3", "ARTP_DTOAUM4", "ARTP_DTOAUM5", "ARTP_DTOAUM6", "ARTP_CODMON", "ARTP_CANPRE",
                        "ARTP_UBICA", "ARTP_AMPUNIV", "ARTP_AJUSTE",
                    ]
                    self.db.execute(
                        "INSERT INTO ARTICULP (" + ", ".join(insert_fields) + ") VALUES (" +
                        ", ".join("?" for _ in insert_fields) + ")",
                        tuple(target.get(field) for field in insert_fields),
                    )
                    altas += 1

                sale_info: dict[str, Any] | None = None
                if actualizar_precio_venta and not articulo_creado:
                    # IMPTAR_U.pas: MODIFICAR_PVENTA solo existe dentro de la
                    # rama "IF NOT ALTA"; una linea recien dada de alta ya
                    # sale con los precios calculados por
                    # _create_article_for_tariff_alta y no pasa por aqui.
                    sale_info = self._update_sale_price_from_supplier_tariff(
                        article,
                        target,
                        int(proveedor),
                        descripcion_articulo=raw_line.get("descripcion") if "descripcion" in raw_line else None,
                        solo_si_sube_precio=solo_si_sube_precio,
                        solo_proveedor_principal=solo_proveedor_principal,
                        solo_si_propio=solo_si_propio,
                        generar_etiquetas=generar_etiquetas,
                        etiqueta_modelo=etiqueta_modelo,
                    )
                    if sale_info.get("actualizado"):
                        venta_actualizada += 1
                    if sale_info.get("etiqueta_generada"):
                        etiquetas_generadas += 1

                resultados.append({
                    "linea": pos,
                    "articulo": codart,
                    "resuelto_por": resolved_by,
                    "accion": action,
                    "articulo_creado": articulo_creado,
                    "referencia_proveedor": target.get("ARTP_REFPRO"),
                    "precio_anterior": normalize(previous_price),
                    "precio_base": normalize(target.get("ARTP_PREBAS")),
                    "coste_neto": normalize(self._supplier_net_cost(target)),
                    "precio_venta": sale_info,
                })

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "empresa": self.settings.empresa,
            "proveedor": int(proveedor),
            "nombre_proveedor": str(provider.get("PRO_NOMCOR") or "").strip(),
            "lineas": len(resultados),
            "altas": altas,
            "modificaciones": modificaciones,
            "articulos_creados": articulos_creados,
            "precios_venta_actualizados": venta_actualizada,
            "etiquetas_generadas": etiquetas_generadas,
            "actualizar_precio_venta": bool(actualizar_precio_venta),
            "dar_de_alta": bool(dar_de_alta),
            "resultados": resultados,
        }

    def _subfamily_price_table(self, codfam: int, subfam: int) -> int:
        row = self.db.fetch_one(
            """
            SELECT SUB_TABLA
            FROM SUBFAM
            WHERE SUB_NUMEMP=? AND SUB_CODFAM=? AND SUB_CODIGO=?
            """,
            (self.settings.empresa, int(codfam), int(subfam)),
        )
        return int((row or {}).get("SUB_TABLA") or 0)

    def _ssubfamily_price_table(self, codfam: int, subfam: int, ssubfam: int) -> int:
        row = self.db.fetch_one(
            """
            SELECT SSUB_TABLA
            FROM SSUBFAM
            WHERE SSUB_NUMEMP=? AND SSUB_CODFAM=? AND SSUB_CODSUB=? AND SSUB_CODIGO=?
            """,
            (self.settings.empresa, int(codfam), int(subfam), int(ssubfam)),
        )
        return int((row or {}).get("SSUB_TABLA") or 0)

    def _table_from_article_family(self, codfam: int, subfam: int, ssubfam: int | str | None = None) -> int:
        ssubfam_text = str(ssubfam or "").strip()
        if ssubfam_text and int(ssubfam_text) > 0:
            table = self._ssubfamily_price_table(codfam, subfam, int(ssubfam_text))
            if table:
                return table
        if int(subfam or 0) > 0:
            return self._subfamily_price_table(codfam, subfam)
        return 0

    def _famncc_price_table(self, famncc: str) -> int:
        row = self.db.fetch_one(
            """
            SELECT NCC_TABLA
            FROM FAMNCC
            WHERE NCC_NUMEMP=? AND NCC_CODIGO=?
            """,
            (self.settings.empresa, famncc),
        )
        return int((row or {}).get("NCC_TABLA") or 0)

    def _article_additional_info(self, codart: str, code: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            """
            SELECT FIRST 1 *
            FROM ARTICULI
            WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_CODINF=?
            ORDER BY ARTI_NUMLIN
            """,
            (self.settings.empresa, codart, code),
        )

    def _next_article_info_line(self, codart: str) -> int:
        row = self.db.fetch_one(
            "SELECT MAX(ARTI_NUMLIN) AS ARTI_NUMLIN FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=?",
            (self.settings.empresa, codart),
        )
        return int((row or {}).get("ARTI_NUMLIN") or 0) + 1

    def _save_article_additional_info(self, codart: str, code: str, text: str) -> None:
        current = self._article_additional_info(codart, code)
        if current:
            self.db.execute(
                """
                UPDATE ARTICULI
                SET ARTI_CODINF=?, ARTI_DESCRI=?
                WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_NUMLIN=?
                """,
                (code, text, self.settings.empresa, codart, current["ARTI_NUMLIN"]),
            )
            return
        self.db.execute(
            "INSERT INTO ARTICULI (ARTI_NUMEMP, ARTI_CODART, ARTI_NUMLIN, ARTI_CODINF, ARTI_DESCRI) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.settings.empresa, codart, self._next_article_info_line(codart), code, text),
        )

    def _delete_article_additional_info(self, codart: str, code: str) -> None:
        self.db.execute(
            "DELETE FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_CODINF=?",
            (self.settings.empresa, codart, code),
        )

    def change_article_family(
        self,
        codart: str,
        codfam: int,
        subfam: int,
        ssubfam: int | str | None = None,
        new_table: int | str | None = None,
    ) -> dict[str, Any]:
        current = self.get_article(codart)
        current_ssubf = self._article_additional_info(codart, "SSUBF")
        before_ssubf = str((current_ssubf or {}).get("ARTI_DESCRI") or "")
        new_table_text = str(new_table or "").strip()
        target_table = int(new_table_text) if new_table_text else 0
        inferred_table = 0
        if target_table == 0:
            inferred_table = self._table_from_article_family(codfam, subfam, ssubfam)
            target_table = inferred_table

        proposed = dict(current)
        if target_table:
            self.get_price_table(target_table)
            proposed["ART_TABPREC"] = target_table
            proposed = self.calculate_article_price(proposed)

        fields = ["ART_CODFAM", "ART_SUBFAM"]
        values: list[Any] = [int(codfam), int(subfam)]
        if target_table:
            fields.extend([
                "ART_PRECOS",
                "ART_TABPREC",
                "ART_PREVEN1",
                "ART_PREVEN2",
                "ART_PREVEN3",
                "ART_PREVEN4",
                "ART_PVP",
            ])
            values.extend([
                proposed["ART_PRECOS"],
                proposed["ART_TABPREC"],
                proposed["ART_PREVEN1"],
                proposed["ART_PREVEN2"],
                proposed["ART_PREVEN3"],
                proposed["ART_PREVEN4"],
                proposed["ART_PVP"],
            ])
        fields.extend(["ART_FECMOD", "ART_USUMOD"])
        values.extend([datetime.now(), self.settings.usuario])
        set_sql = ", ".join(f"{field}=?" for field in fields)
        try:
            self.db.execute(
                f"UPDATE ARTICUL SET {set_sql} WHERE ART_NUMEMP=? AND ART_CODART=?",
                tuple(values + [self.settings.empresa, codart]),
            )
            if ssubfam is not None:
                ssubfam_text = str(ssubfam or "").strip()
                if ssubfam_text and int(ssubfam_text) > 0:
                    self._save_article_additional_info(codart, "SSUBF", ssubfam_text)
                else:
                    self._delete_article_additional_info(codart, "SSUBF")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        after = self.get_article(codart)
        after_ssubf = self._article_additional_info(codart, "SSUBF")
        after_ssubf_text = str((after_ssubf or {}).get("ARTI_DESCRI") or "")
        family_fields = ["ART_CODFAM", "ART_SUBFAM"]
        family_diff = diff(pick(current, family_fields), pick(after, family_fields))
        if target_table:
            family_diff.update(diff(pick(current, ARTICLE_PRICE_FIELDS), pick(after, ARTICLE_PRICE_FIELDS)))
        if ssubfam is not None and before_ssubf != after_ssubf_text:
            family_diff["SSUBF"] = {"before": before_ssubf, "after": after_ssubf_text}
        return {
            "article": codart,
            "empresa": self.settings.empresa,
            "updated": True,
            "tabla_aplicada": target_table or None,
            "tabla_origen": "inferida" if inferred_table else ("manual" if target_table else None),
            "diff": family_diff,
            "after": {
                **pick(after, ["ART_CODART", "ART_DESCRI"] + family_fields),
                **pick(after, ARTICLE_PRICE_FIELDS),
                "SSUBF": after_ssubf_text,
            },
        }

    def change_article_famncc_table(
        self,
        codart: str,
        famncc: str,
        new_table: int | str | None = None,
    ) -> dict[str, Any]:
        current = self.get_article(codart)
        current_famncc = self._article_additional_info(codart, "FAMNC")
        before_famncc = str((current_famncc or {}).get("ARTI_DESCRI") or "")
        famncc_text = str(famncc or "").strip()

        new_table_text = str(new_table or "").strip()
        target_table = int(new_table_text) if new_table_text else 0
        inferred_table = 0
        if target_table == 0 and famncc_text:
            inferred_table = self._famncc_price_table(famncc_text)
            target_table = inferred_table

        proposed = dict(current)
        if target_table:
            self.get_price_table(target_table)
            proposed["ART_TABPREC"] = target_table
            proposed = self.calculate_article_price(proposed)

        fields: list[str] = []
        values: list[Any] = []
        if target_table:
            fields.extend([
                "ART_PRECOS",
                "ART_TABPREC",
                "ART_PREVEN1",
                "ART_PREVEN2",
                "ART_PREVEN3",
                "ART_PREVEN4",
                "ART_PVP",
            ])
            values.extend([
                proposed["ART_PRECOS"],
                proposed["ART_TABPREC"],
                proposed["ART_PREVEN1"],
                proposed["ART_PREVEN2"],
                proposed["ART_PREVEN3"],
                proposed["ART_PREVEN4"],
                proposed["ART_PVP"],
            ])
        fields.extend(["ART_FECMOD", "ART_USUMOD"])
        values.extend([datetime.now(), self.settings.usuario])
        set_sql = ", ".join(f"{field}=?" for field in fields)

        try:
            if famncc_text:
                self._save_article_additional_info(codart, "FAMNC", famncc_text)
            else:
                self._delete_article_additional_info(codart, "FAMNC")
            self.db.execute(
                f"UPDATE ARTICUL SET {set_sql} WHERE ART_NUMEMP=? AND ART_CODART=?",
                tuple(values + [self.settings.empresa, codart]),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        after = self.get_article(codart)
        after_famncc = self._article_additional_info(codart, "FAMNC")
        after_famncc_text = str((after_famncc or {}).get("ARTI_DESCRI") or "")
        ncc_diff: dict[str, dict[str, Any]] = {}
        if before_famncc != after_famncc_text:
            ncc_diff["FAMNC"] = {"before": before_famncc, "after": after_famncc_text}
        if target_table:
            ncc_diff.update(diff(pick(current, ARTICLE_PRICE_FIELDS), pick(after, ARTICLE_PRICE_FIELDS)))
        return {
            "article": codart,
            "empresa": self.settings.empresa,
            "updated": True,
            "tabla_aplicada": target_table or None,
            "tabla_origen": "inferida" if inferred_table else ("manual" if target_table else None),
            "diff": ncc_diff,
            "after": {
                **pick(after, ["ART_CODART", "ART_DESCRI"] + ARTICLE_PRICE_FIELDS),
                "FAMNC": after_famncc_text,
            },
        }


class FaroPhase1Service:
    def __init__(self, db: FaroDb):
        self.db = db
        self.settings = db.settings

    def provider_name(self, codpro: Any) -> str:
        row = self.db.fetch_one(
            "SELECT PRO_NOMCOR FROM PROVEE WHERE PRO_NUMEMP=? AND PRO_CODPRO=?",
            (self.settings.empresa, int(codpro or 0)),
        )
        return str(row["PRO_NOMCOR"]).strip() if row and row.get("PRO_NOMCOR") is not None else ""

    def barcode_article(self, text: str) -> str | None:
        if not text or len(text) < 12:
            return None
        try:
            Decimal(text)
        except Exception:
            return None
        row = self.db.fetch_one(
            "SELECT ARTC_CODART FROM ARTICULC WHERE ARTC_NUMEMP=? AND ARTC_CODIGO=?",
            (self.settings.empresa, text),
        )
        return str(row["ARTC_CODART"]).strip() if row and row.get("ARTC_CODART") else None

    def find_article(self, texto: str) -> dict[str, Any] | None:
        codart = self.barcode_article(texto) or texto
        row = self.db.fetch_one(
            "SELECT * FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        if not row:
            return None
        row = normalize(row)
        result = {
            "codart": row.get("ART_CODART"),
            "descri": clean_text_value(row.get("ART_DESCRI")),
            "unimed": row.get("ART_UNIMED"),
            "preven1": row.get("ART_PREVEN1"),
            "preven2": row.get("ART_PREVEN2"),
            "preven3": row.get("ART_PREVEN3"),
            "preven4": row.get("ART_PREVEN4"),
            "pvp": row.get("ART_PVP"),
            "codpro": row.get("ART_CODPRO"),
            "propio": row.get("ART_INDPROP"),
            "proveedor": self.provider_name(row.get("ART_CODPRO")),
        }
        result["datasnap_text"] = "|".join(serialize_text_value(result[key]) for key in [
            "codart", "descri", "unimed", "preven1", "preven2", "preven3",
            "preven4", "pvp", "codpro", "propio", "proveedor",
        ])
        return result

    def search_articles(
        self,
        texto: str = "",
        order_by: str = "ART_DESCRI",
        limit: int = MAX_ROWS_DEFAULT,
        codart_prefix: str = "",
        centro: int | str | None = None,
        with_stock: bool = False,
        purchase_before: Any = None,
        sale_before: Any = None,
        movement_before: Any = None,
    ) -> dict[str, Any]:
        allowed_order = {
            "ART_CODART",
            "ART_DESCRI",
            "ART_UNIMED",
            "ART_PRECOS",
            "ART_PREVEN4",
            "ART_PVP",
            "ART_CODPRO",
            "PRO_NOMCOR",
            "ARTE_EXIST",
            "ARTE_FECCOM",
            "ARTE_FECVEN",
            "ARTE_FECMOV",
        }
        order = order_by.upper()
        if order not in allowed_order:
            raise FaroError(f"Orden no permitido: {order_by}")
        centro_int = self.settings.centro if centro is None else int(centro) if not _all_centers(centro) else None
        purchase_limit = self._parse_optional_date(purchase_before)
        sale_limit = self._parse_optional_date(sale_before)
        movement_limit = self._parse_optional_date(movement_before)
        requires_stock_row = bool(with_stock or purchase_limit or sale_limit or movement_limit)
        rows_limit = max(1, min(int(limit), MAX_ROWS_DEFAULT))
        stock_join = "JOIN" if requires_stock_row else "LEFT JOIN"
        sql = (
            f"SELECT FIRST {rows_limit} A.*, P.PRO_NOMCOR, "
            "E.ARTE_CENTRO, E.ARTE_EXIST, E.ARTE_MINIMO, E.ARTE_MAXIMO, "
            "E.ARTE_FECCOM, E.ARTE_FECVEN, E.ARTE_FECMOV "
            "FROM ARTICUL A "
            "JOIN PROVEE P ON A.ART_CODPRO = P.PRO_CODPRO AND A.ART_NUMEMP = P.PRO_NUMEMP "
            f"{stock_join} ARTICULE E ON E.ARTE_NUMEMP = A.ART_NUMEMP "
            "AND E.ARTE_CODART = A.ART_CODART "
            "WHERE A.ART_NUMEMP=?"
        )
        params: list[Any] = [self.settings.empresa]
        if centro_int is not None:
            sql = sql.replace(
                "AND E.ARTE_CODART = A.ART_CODART ",
                "AND E.ARTE_CODART = A.ART_CODART AND E.ARTE_CENTRO = ? ",
            )
            params.insert(0, centro_int)
        if texto:
            search_text = texto.upper().strip()
            search_values = [search_text]
            if len(search_text) > 3 and search_text.endswith("S"):
                search_values.append(search_text[:-1])
            unique_search_values = list(dict.fromkeys(search_values))
            sql += " AND (" + " OR ".join("UPPER(A.ART_DESCRI) LIKE ?" for _ in unique_search_values) + ")"
            params.extend(f"%{value}%" for value in unique_search_values)
        if codart_prefix:
            sql += " AND A.ART_CODART LIKE ?"
            params.append(f"{codart_prefix}%")
        if with_stock:
            sql += " AND E.ARTE_EXIST > 0"
        if purchase_limit:
            sql += " AND E.ARTE_FECCOM < ?"
            params.append(purchase_limit)
        if sale_limit:
            sql += " AND (E.ARTE_FECVEN < ? OR E.ARTE_FECVEN IS NULL)"
            params.append(sale_limit)
        if movement_limit:
            sql += " AND E.ARTE_FECMOV < ?"
            params.append(movement_limit)
        order_sql = f"P.{order}" if order == "PRO_NOMCOR" else f"E.{order}" if order.startswith("ARTE_") else f"A.{order}"
        sql += f" ORDER BY {order_sql}"
        rows = self.db.fetch_all(sql, tuple(params))
        items = []
        parts = []
        for row in rows:
            row = normalize(row)
            articulo = {key: row.get(key) for key in row if key.startswith("ART_")}
            item = {
                "codart": row.get("ART_CODART"),
                "descri": clean_text_value(row.get("ART_DESCRI")),
                "unimed": row.get("ART_UNIMED"),
                "precos": row.get("ART_PRECOS"),
                "preven1": row.get("ART_PREVEN1"),
                "preven2": row.get("ART_PREVEN2"),
                "preven3": row.get("ART_PREVEN3"),
                "preven4": row.get("ART_PREVEN4"),
                "pvp": row.get("ART_PVP"),
                "familia": row.get("ART_CODFAM"),
                "subfamilia": row.get("ART_SUBFAM"),
                "tipo_iva": row.get("ART_TIPIVA"),
                "tabla_precio": row.get("ART_TABPREC"),
                "codpro": row.get("ART_CODPRO"),
                "proveedor": row.get("PRO_NOMCOR"),
                "centro": row.get("ARTE_CENTRO"),
                "existencias": row.get("ARTE_EXIST"),
                "minimo": row.get("ARTE_MINIMO"),
                "maximo": row.get("ARTE_MAXIMO"),
                "fecha_compra": row.get("ARTE_FECCOM"),
                "fecha_venta": row.get("ARTE_FECVEN"),
                "fecha_ultimo_movimiento": row.get("ARTE_FECMOV"),
                "articulo": articulo,
            }
            items.append(item)
            parts.append("|".join(serialize_text_value(item[key]) for key in ["codart", "descri", "unimed", "precos", "preven4", "pvp", "codpro", "proveedor", "centro", "existencias"]))
        return {"count": len(items), "items": items, "datasnap_text": "#".join(parts) + ("#" if parts else "")}

    def article_technical_info(self, codart: str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT ARC_TEXTO1, ARC_TEXTO2, ARC_TEXTO3, ARC_TEXTO4 FROM ARTCAR WHERE ARC_NUMEMP=? AND ARC_CODART=?",
            (self.settings.empresa, codart),
        )
        text = ""
        if row:
            text = "".join(clean_text_value(row.get(key)) for key in ["ARC_TEXTO1", "ARC_TEXTO2", "ARC_TEXTO3", "ARC_TEXTO4"])
        return {"codart": codart, "text": text}

    def article_stock(self, codart: str, centro: int | str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT ARTE_EXIST FROM ARTICULE WHERE ARTE_NUMEMP=? AND ARTE_CENTRO=? AND ARTE_CODART=?",
            (self.settings.empresa, int(centro), codart),
        )
        stock = normalize(row.get("ARTE_EXIST")) if row else ""
        return {"codart": codart, "centro": int(centro), "existencias": stock, "datasnap_text": serialize_text_value(stock)}

    def article_stocks(self, codart: str) -> dict[str, Any]:
        rows = self.db.fetch_all(
            "SELECT * FROM ARTICULE WHERE ARTE_NUMEMP=? AND ARTE_CODART=? ORDER BY ARTE_CENTRO",
            (self.settings.empresa, codart),
        )
        items = []
        parts = []
        for row in rows:
            row = normalize(row)
            item = {
                "centro": row.get("ARTE_CENTRO"),
                "existencias": row.get("ARTE_EXIST"),
                "minimo": row.get("ARTE_MINIMO"),
                "maximo": row.get("ARTE_MAXIMO"),
                "feccom": row.get("ARTE_FECCOM"),
                "fecven": row.get("ARTE_FECVEN"),
            }
            items.append(item)
            parts.append("|".join(serialize_text_value(item[key]) for key in ["centro", "existencias", "minimo", "maximo", "feccom", "fecven"]))
        return {"codart": codart, "items": items, "datasnap_text": "#".join(parts) + ("#" if parts else "")}

    def article_brand(self, codart: str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT ARTI_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_CODINF=?",
            (self.settings.empresa, codart, "MARCA"),
        )
        brand = str(row["ARTI_DESCRI"]).strip() if row and row.get("ARTI_DESCRI") is not None else ""
        return {"codart": codart, "marca": brand, "datasnap_text": brand}

    def list_brands(self) -> dict[str, Any]:
        rows = self.db.fetch_all(
            "SELECT DISTINCT ARTI_DESCRI AS MAR_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODINF=? ORDER BY ARTI_DESCRI",
            (self.settings.empresa, "MARCA"),
        )
        items = [str(row["MAR_DESCRI"]).strip() for row in rows if row.get("MAR_DESCRI") is not None]
        return {"count": len(items), "items": items, "datasnap_text": "#".join(items) + ("#" if items else "")}

    def list_families(self, padre: str = "") -> dict[str, Any]:
        if padre == "":
            rows = self.db.fetch_all(
                "SELECT FAM_CODIGO, FAM_DESCRI FROM FAMILI WHERE FAM_NUMEMP=? ORDER BY FAM_CODIGO",
                (self.settings.empresa,),
            )
            code_key, desc_key = "FAM_CODIGO", "FAM_DESCRI"
        else:
            rows = self.db.fetch_all(
                "SELECT SUB_CODIGO, SUB_DESCRI FROM SUBFAM WHERE SUB_NUMEMP=? AND SUB_CODFAM=? ORDER BY SUB_CODIGO",
                (self.settings.empresa, int(padre)),
            )
            code_key, desc_key = "SUB_CODIGO", "SUB_DESCRI"
        items = [{"codigo": normalize(row.get(code_key)), "descri": clean_text_value(row.get(desc_key))} for row in rows]
        parts = [f"{item['codigo']}|{item['descri']}" for item in items]
        return {"padre": padre, "items": items, "datasnap_text": "#".join(parts) + ("#" if parts else "")}

    def list_web_families(self, padre: str = "") -> dict[str, Any]:
        rows = self.db.fetch_all(
            "SELECT FMW_CODIGO, FMW_DESCRI FROM FAMWEB WHERE FMW_NUMEMP=? AND FMW_PADRE=? ORDER BY FMW_CODIGO",
            (self.settings.empresa, padre),
        )
        items = [{"codigo": normalize(row.get("FMW_CODIGO")), "descri": clean_text_value(row.get("FMW_DESCRI"))} for row in rows]
        parts = [f"{item['codigo']}|{item['descri']}" for item in items]
        return {"padre": padre, "items": items, "datasnap_text": "#".join(parts) + ("#" if parts else "")}

    def article_suppliers(self, codart: str) -> dict[str, Any]:
        rows = self.db.fetch_all(
            "SELECT ARTP_CODPRO FROM ARTICULP WHERE ARTP_NUMEMP=? AND ARTP_CODART=? ORDER BY ARTP_CODPRO",
            (self.settings.empresa, codart),
        )
        items = [{"codpro": normalize(row.get("ARTP_CODPRO")), "nombre": self.provider_name(row.get("ARTP_CODPRO"))} for row in rows]
        parts = [f"{item['codpro']}|{item['nombre']}" for item in items]
        return {"codart": codart, "items": items, "datasnap_text": "#".join(parts) + ("#" if parts else "")}

    def article_purchase_sheet(self, codart: str, codpro: int | str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM ARTICULP WHERE ARTP_NUMEMP=? AND ARTP_CODART=? AND ARTP_CODPRO=?",
            (self.settings.empresa, codart, int(codpro)),
        )
        if not row:
            return {"codart": codart, "codpro": int(codpro), "found": False, "datasnap_text": ""}
        row = normalize(row)
        precos = (
            dec(row.get("ARTP_PREBAS"))
            * (1 - dec(row.get("ARTP_DTOAUM1")) / 100)
            * (1 - dec(row.get("ARTP_DTOAUM2")) / 100)
            * (1 - dec(row.get("ARTP_DTOAUM3")) / 100)
            * (1 - dec(row.get("ARTP_DTOAUM4")) / 100)
            * (1 - dec(row.get("ARTP_DTOAUM5")) / 100)
            * (1 - dec(row.get("ARTP_DTOAUM6")) / 100)
        )
        result = {
            "codart": codart,
            "codpro": int(codpro),
            "found": True,
            "refpro": row.get("ARTP_REFPRO"),
            "descri": clean_text_value(row.get("ARTP_DESCRI")),
            "unimed": row.get("ARTP_UNIMED"),
            "cancon": row.get("ARTP_CANCON"),
            "canven": row.get("ARTP_CANVEN"),
            "unipaq": row.get("ARTP_UNIPAQ"),
            "prebas": row.get("ARTP_PREBAS"),
            "precos": normalize(precos),
            "ampuniv": row.get("ARTP_AMPUNIV"),
            "ajuste": row.get("ARTP_AJUSTE"),
        }
        result["datasnap_text"] = "#".join(serialize_text_value(result[key]) for key in [
            "refpro", "descri", "unimed", "cancon", "canven", "unipaq", "prebas", "precos", "ampuniv", "ajuste",
        ]) + "#"
        return result

    def offer_pvp(self, codart: str) -> dict[str, Any]:
        today = date.today()
        rows = self.db.fetch_all(
            "SELECT * FROM DETOFER WHERE DOF_NUMEMP=? AND DOF_CODART=? AND DOF_FECINI<=? AND DOF_FECFIN>=? ORDER BY DOF_PVP",
            (self.settings.empresa, codart, today, today),
        )
        for row in rows:
            row = normalize(row)
            if dec(row.get("DOF_PVP")) == 0:
                continue
            pvp = dec(row.get("DOF_PVP"))
            if dec(row.get("DOF_DTO1")) != 0:
                pvp = pvp * (1 - dec(row.get("DOF_DTO1")) / 100) * (1 - dec(row.get("DOF_DTO2")) / 100)
            header = self.db.fetch_one(
                "SELECT OFE_TIPOFE FROM OFERTAS WHERE OFE_NUMEMP=? AND OFE_EJERCI=? AND OFE_NUMOFE=?",
                (self.settings.empresa, row.get("DOF_EJERCI"), row.get("DOF_NUMOFE")),
            )
            if header and header.get("OFE_TIPOFE") == "S":
                return {"codart": codart, "pvp": "0", "offer": row, "ignored_reason": "Oferta sin precios"}
            return {"codart": codart, "pvp": normalize(pvp), "offer": row}
        return {"codart": codart, "pvp": "0", "offer": None}

    def next_offer_number(self, ejerci: int) -> int:
        row = self.db.fetch_one(
            "SELECT MAX(OFE_NUMOFE) AS NUMOFE FROM OFERTAS WHERE OFE_NUMEMP=? AND OFE_EJERCI=?",
            (self.settings.empresa, int(ejerci)),
        )
        return int(row.get("NUMOFE") or 0) + 1 if row else 1

    def create_offer(
        self,
        tipo_oferta: str,
        nombre: str,
        fecha_inicio: Any,
        fecha_fin: Any,
        articulos: list[dict[str, Any]],
        proveedor: Any = 0,
        ejercicio: Any = None,
        moneda: str = "E",
        gastos: Any = 0,
        fecha: Any = None,
    ) -> dict[str, Any]:
        fecini = self._parse_optional_date(fecha_inicio)
        fecfin = self._parse_optional_date(fecha_fin)
        if fecini is None or fecfin is None:
            raise FaroError("fecha_inicio y fecha_fin son obligatorias")
        if fecfin < fecini:
            raise FaroError("fecha_fin no puede ser anterior a fecha_inicio")
        if not isinstance(articulos, list) or not articulos:
            raise FaroError("articulos debe contener al menos una linea")

        tipo = str(tipo_oferta or "").strip().upper()[:1]
        if tipo not in {"R", "P", "T", "S", "W"}:
            raise FaroError("tipo_oferta debe ser R, P, T, S o W")
        name = str(nombre or "").strip()
        if not name:
            raise FaroError("nombre es obligatorio")
        if len(name) > 50:
            raise FaroError("nombre no puede superar 50 caracteres")
        offer_year = int(ejercicio) if ejercicio not in (None, "") else fecini.year
        offer_date = self._parse_optional_date(fecha, date.today()) or date.today()
        provider = int(proveedor or 0)
        currency = str(moneda or "E").strip().upper()[:1] or "E"
        now = datetime.now()
        user = str(self.settings.usuario or "")[:15]

        numero = self.next_offer_number(offer_year)
        created_lines: list[dict[str, Any]] = []
        try:
            self.db.execute(
                """
                INSERT INTO OFERTAS (
                    OFE_NUMEMP, OFE_EJERCI, OFE_NUMOFE, OFE_CODPRO, OFE_DESCRI,
                    OFE_FECHA, OFE_FECINI, OFE_FECFIN, OFE_GASTOS, OFE_CODMON,
                    OFE_TIPOFE, OFE_FECMOD, OFE_USUMOD
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.settings.empresa,
                    offer_year,
                    numero,
                    provider,
                    name,
                    offer_date,
                    fecini,
                    fecfin,
                    dec(gastos),
                    currency,
                    tipo,
                    now,
                    user,
                ),
            )
            seen: set[str] = set()
            for index, line in enumerate(articulos, start=1):
                if not isinstance(line, dict):
                    raise FaroError(f"articulos[{index}] debe ser un objeto")
                codart = str(line.get("articulo") or "").strip()
                if not codart:
                    raise FaroError(f"Falta articulo en articulos[{index}]")
                if codart in seen:
                    raise FaroError(f"Articulo duplicado en la oferta: {codart}")
                seen.add(codart)
                article = self.db.fetch_one(
                    """
                    SELECT ART_CODART, ART_PREBAS, ART_CODMON, ART_CANPRE
                    FROM ARTICUL
                    WHERE ART_NUMEMP=? AND ART_CODART=?
                    """,
                    (self.settings.empresa, codart),
                )
                if not article:
                    raise FaroError(f"Articulo no encontrado: {codart}")
                codart = str(article.get("ART_CODART") or codart).strip()
                descuentos = line.get("descuentos", [])
                if descuentos in (None, ""):
                    descuentos = []
                if not isinstance(descuentos, list):
                    raise FaroError(f"descuentos de {codart} debe ser una lista")
                dto1 = line.get("descuento1", descuentos[0] if len(descuentos) > 0 else 0)
                dto2 = line.get("descuento2", descuentos[1] if len(descuentos) > 1 else 0)
                pvp = dec(line.get("precio_oferta"))
                precio = dec(line.get("precio_sin_iva"))
                self.db.execute(
                    """
                    INSERT INTO DETOFER (
                        DOF_NUMEMP, DOF_EJERCI, DOF_NUMOFE, DOF_CODART, DOF_FECINI,
                        DOF_FECFIN, DOF_CODPRO, DOF_PRECOS, DOF_PRECIO, DOF_PVP,
                        DOF_CODMON, DOF_CANPRE, DOF_DTO1, DOF_DTO2
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.settings.empresa,
                        offer_year,
                        numero,
                        codart,
                        fecini,
                        fecfin,
                        provider,
                        dec(article.get("ART_PREBAS")),
                        precio,
                        pvp,
                        str(article.get("ART_CODMON") or currency)[:1],
                        dec(article.get("ART_CANPRE")),
                        dec(dto1),
                        dec(dto2),
                    ),
                )
                created_lines.append(
                    {
                        "articulo": codart,
                        "precio_oferta": normalize(pvp),
                        "precio_sin_iva": normalize(precio),
                        "descuento1": normalize(dec(dto1)),
                        "descuento2": normalize(dec(dto2)),
                    }
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "ok": True,
            "ejercicio": offer_year,
            "numero": numero,
            "tipo_oferta": tipo,
            "nombre": name,
            "fecha_inicio": fecini.isoformat(),
            "fecha_fin": fecfin.isoformat(),
            "proveedor": provider,
            "lineas": len(created_lines),
            "articulos": created_lines,
        }

    def _sale_profit_doc_types(self, value: Any, incluir_pedidos: bool) -> list[str]:
        allowed = {"T", "F", "A", "C", "P", "R", "S"}
        if value in (None, "", []):
            raw_items = ["T", "F", "A", "C"]
            if incluir_pedidos:
                raw_items.extend(["P", "R"])
        elif isinstance(value, str):
            raw_items = [item.strip() for item in value.replace(";", ",").split(",")]
        else:
            raw_items = [str(item).strip() for item in value]

        result: list[str] = []
        for item in raw_items:
            code = item.upper()[:1]
            if not code:
                continue
            if code not in allowed:
                raise FaroError(f"Tipo de documento de venta no soportado: {item}")
            if code not in result:
                result.append(code)
        return result or ["T", "F", "A", "C"]

    @staticmethod
    def _sale_doc_name(code: Any) -> str:
        names = {
            "T": "Ticket",
            "F": "Factura",
            "A": "Albaran",
            "C": "Credito",
            "P": "Pedido",
            "R": "Presupuesto",
            "S": "Servicio",
        }
        key = str(code or "").strip().upper()[:1]
        return names.get(key, key)

    @staticmethod
    def _sale_weekday_name(value: date) -> str:
        names = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
        return names[value.weekday()]

    @staticmethod
    def _sale_payment_name(code: Any) -> str:
        key = str(code or "").strip().upper()
        names = {
            "E": "Efectivo",
            "T": "Tarjeta",
            "R": "Recibo",
            "C": "Credito",
            "D": "Domiciliado",
        }
        return names.get(key, key)

    @staticmethod
    def _is_anaven_ignored_description(value: Any) -> bool:
        text = str(value or "")
        return (
            "Linea Factura de Tickets" in text
            or "Tickets Cobro" in text
            or "IVA:" in text
        )

    def _sale_profit_value(self, row: dict[str, Any], moneda: str) -> dict[str, Any]:
        serie_descuento = str(self.parameter("DESSER", "") or "").strip()
        if serie_descuento and str(row.get("DMV_SERIE") or "").strip() == serie_descuento:
            return {"venta_neta": Decimal("0"), "coste": Decimal("0"), "margen": Decimal("0"), "rentabilidad_pct": Decimal("0")}

        tiplin = str(row.get("DMV_TIPLIN") or "").strip().upper()[:1]
        venta_neta = dec(row.get("DMV_VALLINS")) - dec(row.get("DMV_IMPDTO"))
        row_currency = str(row.get("DMV_CODMON") or moneda or "E").strip().upper()[:1] or "E"
        target_currency = str(moneda or "E").strip().upper()[:1] or "E"
        article_service = FaroArticleService(self.db)
        if row_currency != target_currency:
            venta_neta = article_service.change_price_currency(
                venta_neta,
                row_currency,
                target_currency,
                "I" if tiplin == "X" else "P",
            )

        cantidad = dec(row.get("DMV_CANTID"))
        coste = Decimal("0")
        if tiplin == "D":
            if str(row.get("ART_INDINV") or "").strip().upper() == "N":
                coste = Decimal("0")
            else:
                cost_info = article_service.article_cost_price(
                    str(row.get("DMV_CODART") or "").strip(),
                    self._parse_optional_date(row.get("DMV_FECMOV"), date.today()) or date.today(),
                    target_currency,
                )
                coste = dec(cost_info.get("precio_coste")) * cantidad
        elif tiplin == "X" and not self._is_anaven_ignored_description(row.get("DMV_DESCRI")):
            canpre = dec(row.get("DMV_CANPRE"))
            if canpre not in (Decimal("0"), Decimal("1")):
                coste = canpre * cantidad
            else:
                valor = dec(self.parameter("RENTAF", "25")) / Decimal("100")
                if valor >= Decimal("1"):
                    coste = Decimal("0")
                else:
                    divisor = valor / (Decimal("1") - valor) + Decimal("1")
                    coste = venta_neta / divisor if divisor else Decimal("0")

        margen = venta_neta - coste
        rentabilidad = margen * Decimal("100") / venta_neta if venta_neta > 0 else Decimal("0")
        return {
            "venta_neta": venta_neta,
            "coste": coste,
            "margen": margen,
            "rentabilidad_pct": rentabilidad,
        }

    @staticmethod
    def _sales_profit_totals(items: list[dict[str, Any]]) -> dict[str, Any]:
        lineas = len(items)
        unidades = sum((dec(item.get("cantidad")) for item in items), Decimal("0"))
        venta_neta = sum((dec(item.get("venta_neta")) for item in items), Decimal("0"))
        coste = sum((dec(item.get("coste")) for item in items), Decimal("0"))
        margen = venta_neta - coste
        rentabilidad = margen * Decimal("100") / venta_neta if venta_neta > 0 else Decimal("0")
        return {
            "lineas": lineas,
            "unidades": normalize(unidades),
            "venta_neta": normalize(venta_neta),
            "coste": normalize(coste),
            "margen": normalize(margen),
            "rentabilidad_pct": normalize(rentabilidad),
        }

    def sales_profit_lines(
        self,
        fecha_desde: Any,
        fecha_hasta: Any,
        tipos_documento: Any = None,
        centro: Any = None,
        articulo_desde: str = "",
        articulo_hasta: str = "",
        proveedor_desde: Any = None,
        proveedor_hasta: Any = None,
        cliente_desde: Any = None,
        cliente_hasta: Any = None,
        subcliente_desde: Any = None,
        subcliente_hasta: Any = None,
        representante: Any = None,
        descripcion: str = "",
        solo_en_oferta: bool = False,
        incluir_pedidos: bool = False,
        moneda: str = "E",
        limite: Any = MAX_ROWS_DEFAULT,
    ) -> dict[str, Any]:
        start = self._parse_optional_date(fecha_desde)
        end = self._parse_optional_date(fecha_hasta)
        if not start or not end:
            raise FaroError("fecha_desde y fecha_hasta son obligatorias.")
        if start > end:
            raise FaroError("fecha_desde no puede ser posterior a fecha_hasta.")

        target_currency = str(moneda or "E").strip().upper()[:1] or "E"
        doc_types = self._sale_profit_doc_types(tipos_documento, bool(incluir_pedidos))
        limit = max(1, min(int(limite or MAX_ROWS_DEFAULT), 5000))

        where = [
            "D.DMV_NUMEMP=?",
            "D.DMV_FECMOV BETWEEN ? AND ?",
            "D.DMV_TIPDOC IN (" + ",".join("?" for _ in doc_types) + ")",
            "D.DMV_TIPLIN IN ('D','X')",
        ]
        params: list[Any] = [self.settings.empresa, start, end, *doc_types]
        if not incluir_pedidos:
            where.append("D.DMV_SIGNO='1'")
        if _center_filter_is_set(centro):
            where.append("D.DMV_CENTRO=?")
            params.append(int(centro))
        if articulo_desde:
            where.append("D.DMV_CODART>=?")
            params.append(str(articulo_desde).strip())
        if articulo_hasta:
            where.append("D.DMV_CODART<=?")
            params.append(str(articulo_hasta).strip())
        if proveedor_desde not in (None, "", 0):
            where.append("A.ART_CODPRO>=?")
            params.append(int(proveedor_desde))
        if proveedor_hasta not in (None, "", 0):
            where.append("A.ART_CODPRO<=?")
            params.append(int(proveedor_hasta))
        if cliente_desde not in (None, "", 0):
            where.append("C.CBV_CODCLI>=?")
            params.append(int(cliente_desde))
        if cliente_hasta not in (None, "", 0):
            where.append("C.CBV_CODCLI<=?")
            params.append(int(cliente_hasta))
        if subcliente_desde not in (None, "", 0):
            where.append("C.CBV_SUBCLI>=?")
            params.append(int(subcliente_desde))
        if subcliente_hasta not in (None, "", 0):
            where.append("C.CBV_SUBCLI<=?")
            params.append(int(subcliente_hasta))
        if representante not in (None, "", 0):
            where.append("C.CBV_CODREP=?")
            params.append(int(representante))
        if descripcion:
            where.append("UPPER(D.DMV_DESCRI) LIKE ?")
            params.append(f"%{str(descripcion).upper()}%")
        if solo_en_oferta:
            where.append("D.DMV_EJEOFE>0")

        rows = self.db.fetch_all(
            f"""
            SELECT FIRST {limit}
                D.DMV_CENTRO, D.DMV_EJERCI, D.DMV_SERIE, D.DMV_NUMDOC, D.DMV_TIPDOC,
                D.DMV_TIPLIN, D.DMV_NUMLIN, D.DMV_FECMOV, D.DMV_CODART, D.DMV_DESCRI,
                D.DMV_CANTID, D.DMV_PREVEN, D.DMV_DTO1, D.DMV_DTO2, D.DMV_VALLINS,
                D.DMV_IMPDTO, D.DMV_CODMON, D.DMV_SIGNO, D.DMV_CANPRE, D.DMV_EJEOFE,
                D.DMV_NUMOFE, D.DMV_CAJA, C.CBV_CODCLI, C.CBV_SUBCLI, C.CBV_NOMCLI,
                C.CBV_FORCOB, C.CBV_CODREP, C.CBV_CIF, C.CBV_REFCLI,
                A.ART_SECCIO, A.ART_CODFAM, A.ART_SUBFAM, A.ART_AGRUP1,
                A.ART_AGRUP2, A.ART_AGRUP3, A.ART_CODPRO, A.ART_INDINV,
                P.PRO_NOMCOR, F.FAM_DESCRI, S.SUB_DESCRI,
                CF.FAM_DESCRI AS COOP_FAM_DESCRI, CS.SUB_DESCRI AS COOP_SUB_DESCRI,
                M.ARTI_DESCRI AS MARCA, NCC.ARTI_DESCRI AS FAMILIA_NCC,
                FN1.NCC_DESCRI AS NCC_NIVEL1_DESCRI, FN2.NCC_DESCRI AS NCC_NIVEL2_DESCRI,
                FN3.NCC_DESCRI AS NCC_NIVEL3_DESCRI
            FROM DETMOV D
            LEFT JOIN CABDOCV C ON C.CBV_NUMEMP=D.DMV_NUMEMP
                AND C.CBV_CENTRO=D.DMV_CENTRO AND C.CBV_EJERCI=D.DMV_EJERCI
                AND C.CBV_SERIE=D.DMV_SERIE AND C.CBV_NUMDOC=D.DMV_NUMDOC
                AND C.CBV_TIPDOC=D.DMV_TIPDOC
            LEFT JOIN ARTICUL A ON A.ART_NUMEMP=D.DMV_NUMEMP AND A.ART_CODART=D.DMV_CODART
            LEFT JOIN PROVEE P ON P.PRO_NUMEMP=D.DMV_NUMEMP AND P.PRO_CODPRO=A.ART_CODPRO
            LEFT JOIN FAMILI F ON F.FAM_NUMEMP=D.DMV_NUMEMP AND F.FAM_CODIGO=A.ART_CODFAM
            LEFT JOIN SUBFAM S ON S.SUB_NUMEMP=D.DMV_NUMEMP
                AND S.SUB_CODFAM=A.ART_CODFAM AND S.SUB_CODIGO=A.ART_SUBFAM
            LEFT JOIN FAMILI CF ON CF.FAM_NUMEMP=D.DMV_NUMEMP AND CF.FAM_CODIGO=A.ART_AGRUP1
            LEFT JOIN SUBFAM CS ON CS.SUB_NUMEMP=D.DMV_NUMEMP
                AND CS.SUB_CODFAM=A.ART_AGRUP1 AND CS.SUB_CODIGO=A.ART_AGRUP2
            LEFT JOIN ARTICULI M ON M.ARTI_NUMEMP=D.DMV_NUMEMP
                AND M.ARTI_CODART=D.DMV_CODART AND M.ARTI_CODINF='MARCA'
            LEFT JOIN ARTICULI NCC ON NCC.ARTI_NUMEMP=D.DMV_NUMEMP
                AND NCC.ARTI_CODART=D.DMV_CODART AND NCC.ARTI_CODINF='FAMNC'
            LEFT JOIN FAMNCC FN1 ON FN1.NCC_NUMEMP=D.DMV_NUMEMP
                AND FN1.NCC_CODIGO=SUBSTRING(NCC.ARTI_DESCRI FROM 1 FOR 2)
            LEFT JOIN FAMNCC FN2 ON FN2.NCC_NUMEMP=D.DMV_NUMEMP
                AND FN2.NCC_CODIGO=SUBSTRING(NCC.ARTI_DESCRI FROM 1 FOR 4)
            LEFT JOIN FAMNCC FN3 ON FN3.NCC_NUMEMP=D.DMV_NUMEMP
                AND FN3.NCC_CODIGO=SUBSTRING(NCC.ARTI_DESCRI FROM 1 FOR 6)
            WHERE {" AND ".join(where)}
            ORDER BY D.DMV_FECMOV, D.DMV_CENTRO, D.DMV_TIPDOC, D.DMV_EJERCI,
                D.DMV_SERIE, D.DMV_NUMDOC, D.DMV_NUMLIN
            """,
            tuple(params),
        )

        items: list[dict[str, Any]] = []
        omitted = 0
        for row in rows:
            if self._is_anaven_ignored_description(row.get("DMV_DESCRI")):
                omitted += 1
                continue
            movement_date = self._parse_optional_date(row.get("DMV_FECMOV"), start) or start
            values = self._sale_profit_value(row, target_currency)
            own_family = int(row.get("ART_CODFAM") or 0)
            own_subfamily = int(row.get("ART_SUBFAM") or 0)
            coop_family = clean_text_value(row.get("ART_AGRUP1")) or "0"
            coop_subfamily = clean_text_value(row.get("ART_AGRUP2")) or "0"
            coop_level3 = clean_text_value(row.get("ART_AGRUP3")) or "0"
            ncc_code = clean_text_value(row.get("FAMILIA_NCC"))
            ncc_level1 = ncc_code[:2] if len(ncc_code) >= 2 else ncc_code
            ncc_level2 = ncc_code[:4] if len(ncc_code) >= 4 else ncc_code
            ncc_level3 = ncc_code[:6] if len(ncc_code) >= 6 else ncc_code
            inventory_flag = str(row.get("ART_INDINV") or "S").strip().upper()[:1] or "S"
            item = {
                "documento": {
                    "centro": int(row.get("DMV_CENTRO") or 0),
                    "ejercicio": int(row.get("DMV_EJERCI") or 0),
                    "serie": str(row.get("DMV_SERIE") or "").strip(),
                    "numero": int(row.get("DMV_NUMDOC") or 0),
                    "tipo": str(row.get("DMV_TIPDOC") or "").strip(),
                    "tipo_nombre": self._sale_doc_name(row.get("DMV_TIPDOC")),
                    "linea": int(row.get("DMV_NUMLIN") or 0),
                    "fecha": movement_date.isoformat(),
                },
                "cliente": {
                    "codigo": int(row.get("CBV_CODCLI") or 0),
                    "subcliente": int(row.get("CBV_SUBCLI") or 0),
                    "nombre": clean_text_value(row.get("CBV_NOMCLI")),
                    "cif": clean_text_value(row.get("CBV_CIF")),
                    "referencia": clean_text_value(row.get("CBV_REFCLI")),
                },
                "articulo": {
                    "codigo": str(row.get("DMV_CODART") or "").strip(),
                    "descripcion": clean_text_value(row.get("DMV_DESCRI")),
                    "inventariable": inventory_flag != "N",
                    "indicador_inventario": inventory_flag,
                    "tipo_articulo": "concepto" if inventory_flag == "N" else "articulo",
                    "seccion": clean_text_value(row.get("ART_SECCIO")) or "0",
                    "familia": own_family,
                    "familia_nombre": clean_text_value(row.get("FAM_DESCRI")),
                    "subfamilia": own_subfamily,
                    "subfamilia_nombre": clean_text_value(row.get("SUB_DESCRI")),
                    "familia_propia": {
                        "familia": own_family,
                        "familia_nombre": clean_text_value(row.get("FAM_DESCRI")),
                        "subfamilia": own_subfamily,
                        "subfamilia_nombre": clean_text_value(row.get("SUB_DESCRI")),
                    },
                    "familia_cooperativa": {
                        "familia": coop_family,
                        "familia_nombre": clean_text_value(row.get("COOP_FAM_DESCRI")) or coop_family,
                        "subfamilia": coop_subfamily,
                        "subfamilia_nombre": clean_text_value(row.get("COOP_SUB_DESCRI")) or coop_subfamily,
                        "nivel3": coop_level3,
                        "nivel3_nombre": coop_level3,
                    },
                    "familia_ncc": {
                        "codigo": ncc_code,
                        "familia": ncc_level1,
                        "familia_nombre": clean_text_value(row.get("NCC_NIVEL1_DESCRI")) or ncc_level1,
                        "subfamilia": ncc_level2,
                        "subfamilia_nombre": clean_text_value(row.get("NCC_NIVEL2_DESCRI")) or ncc_level2,
                        "nivel3": ncc_level3,
                        "nivel3_nombre": clean_text_value(row.get("NCC_NIVEL3_DESCRI")) or ncc_level3,
                    },
                    "marca": clean_text_value(row.get("MARCA")),
                },
                "proveedor": {
                    "codigo": int(row.get("ART_CODPRO") or 0),
                    "nombre": clean_text_value(row.get("PRO_NOMCOR")),
                },
                "representante": int(row.get("CBV_CODREP") or 0),
                "forma_cobro": {
                    "codigo": str(row.get("CBV_FORCOB") or "").strip(),
                    "nombre": self._sale_payment_name(row.get("CBV_FORCOB")),
                },
                "cantidad": normalize(dec(row.get("DMV_CANTID"))),
                "precio": normalize(dec(row.get("DMV_PREVEN"))),
                "descuento1": normalize(dec(row.get("DMV_DTO1"))),
                "descuento2": normalize(dec(row.get("DMV_DTO2"))),
                "venta_neta": normalize(values["venta_neta"]),
                "coste": normalize(values["coste"]),
                "margen": normalize(values["margen"]),
                "rentabilidad_pct": normalize(values["rentabilidad_pct"]),
                "moneda": target_currency,
                "oferta": {
                    "ejercicio": int(row.get("DMV_EJEOFE") or 0),
                    "numero": int(row.get("DMV_NUMOFE") or 0),
                },
                "mes": movement_date.strftime("%Y-%m"),
                "dia_semana": self._sale_weekday_name(movement_date),
            }
            items.append(item)

        return {
            "count": len(items),
            "omitidas": omitted,
            "limite": limit,
            "moneda": target_currency,
            "filtros": {
                "fecha_desde": start.isoformat(),
                "fecha_hasta": end.isoformat(),
                "tipos_documento": doc_types,
                "centro": int(centro) if _center_filter_is_set(centro) else None,
                "solo_en_oferta": bool(solo_en_oferta),
                "incluir_pedidos": bool(incluir_pedidos),
            },
            "totales": self._sales_profit_totals(items),
            "items": items,
        }

    @staticmethod
    def _sale_family_type(value: Any = None) -> str:
        family_type = str(value or "ncc").strip().lower()
        if family_type not in SALE_FAMILY_TYPES:
            raise FaroError("tipo_familia debe ser uno de: " + ", ".join(sorted(SALE_FAMILY_TYPES)))
        return family_type

    @staticmethod
    def _sale_family_values(item: dict[str, Any], family_type: str) -> dict[str, Any]:
        article = item["articulo"]
        if family_type == "propia":
            return article.get("familia_propia") or {
                "familia": article.get("familia", 0),
                "familia_nombre": article.get("familia_nombre", ""),
                "subfamilia": article.get("subfamilia", 0),
                "subfamilia_nombre": article.get("subfamilia_nombre", ""),
            }
        if family_type == "cooperativa":
            return article.get("familia_cooperativa") or {}
        return article.get("familia_ncc") or {}

    @classmethod
    def _sale_group_key(
        cls,
        item: dict[str, Any],
        group_by: str,
        family_type: str = "ncc",
    ) -> tuple[str, str]:
        if group_by == "articulo":
            article = item["articulo"]
            return article["codigo"], article["descripcion"]
        if group_by == "seccion":
            value = item["articulo"]["seccion"]
            return str(value), str(value)
        if group_by == "familia":
            family = cls._sale_family_values(item, family_type)
            code = str(family.get("familia") or "0")
            return code, clean_text_value(family.get("familia_nombre")) or code
        if group_by == "subfamilia":
            family = cls._sale_family_values(item, family_type)
            family_code = str(family.get("familia") or "0")
            subfamily_code = str(family.get("subfamilia") or "0")
            code = f"{family_code}/{subfamily_code}"
            return code, clean_text_value(family.get("subfamilia_nombre")) or code
        if group_by == "proveedor":
            provider = item["proveedor"]
            return str(provider["codigo"]), provider["nombre"] or str(provider["codigo"])
        if group_by == "cliente":
            client = item["cliente"]
            return f"{client['codigo']}/{client['subcliente']}", client["nombre"] or str(client["codigo"])
        if group_by == "representante":
            value = item["representante"]
            return str(value), str(value)
        if group_by == "centro":
            value = item["documento"]["centro"]
            return str(value), str(value)
        if group_by == "mes":
            value = item["mes"]
            return value, value
        if group_by == "dia_semana":
            value = item["dia_semana"]
            return value, value
        if group_by == "tipo_documento":
            doc = item["documento"]
            return doc["tipo"], doc["tipo_nombre"]
        if group_by == "marca":
            value = item["articulo"]["marca"]
            return value, value
        raise FaroError(f"Agrupacion no soportada: {group_by}")

    def sales_profit_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        group_by = str(args.get("agrupar_por", "articulo") or "articulo").strip().lower()
        if group_by not in SALE_PROFIT_GROUP_FIELDS:
            raise FaroError(
                "agrupar_por debe ser uno de: " + ", ".join(sorted(SALE_PROFIT_GROUP_FIELDS))
            )
        family_type = self._sale_family_type(args.get("tipo_familia"))
        order_by = str(args.get("ordenar_por", "margen") or "margen").strip().lower()
        if order_by not in {"venta_neta", "coste", "margen", "rentabilidad_pct", "unidades", "lineas"}:
            raise FaroError("ordenar_por no soportado.")
        reverse = str(args.get("sentido", "desc") or "desc").strip().lower() != "asc"

        line_args = dict(args)
        line_args.pop("agrupar_por", None)
        line_args.pop("tipo_familia", None)
        line_args.pop("ordenar_por", None)
        line_args.pop("sentido", None)
        group_limit = line_args.pop("limite_grupos", args.get("limite_grupos", None))
        line_args["limite"] = line_args.get("limite", 5000)
        lines = self.sales_profit_lines(**line_args)

        groups: dict[str, dict[str, Any]] = {}
        for item in lines["items"]:
            code, name = self._sale_group_key(item, group_by, family_type)
            if code not in groups:
                groups[code] = {"codigo": code, "nombre": name, "items": []}
            groups[code]["items"].append(item)

        result_items: list[dict[str, Any]] = []
        for group in groups.values():
            totals = self._sales_profit_totals(group["items"])
            result_items.append({"codigo": group["codigo"], "nombre": group["nombre"], **totals})

        def sort_value(item: dict[str, Any]) -> Decimal:
            if order_by == "lineas":
                return Decimal(item.get("lineas") or 0)
            return dec(item.get(order_by))

        result_items.sort(key=sort_value, reverse=reverse)
        if group_limit not in (None, "", 0):
            result_items = result_items[: max(1, int(group_limit))]

        return {
            "agrupar_por": group_by,
            "tipo_familia": family_type if group_by in {"familia", "subfamilia"} else None,
            "ordenar_por": order_by,
            "sentido": "desc" if reverse else "asc",
            "moneda": lines["moneda"],
            "count": len(result_items),
            "base_lineas": lines["count"],
            "totales": lines["totales"],
            "items": result_items,
        }

    @staticmethod
    def _sales_profit_document_ref(item: dict[str, Any]) -> str:
        doc = item["documento"]
        serie = str(doc.get("serie") or "").strip()
        parts = [
            str(doc.get("tipo") or "").strip(),
            serie,
            str(doc.get("numero") or "").strip(),
            str(doc.get("fecha") or "").strip(),
        ]
        return " ".join(part for part in parts if part)

    def _sales_profit_alert_group(
        self,
        code: str,
        name: str,
        items: list[dict[str, Any]],
        negative_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        negative_items = negative_items if negative_items is not None else [
            item for item in items if dec(item.get("rentabilidad_pct")) < 0
        ]
        totals = self._sales_profit_totals(items)
        worst = min((dec(item.get("rentabilidad_pct")) for item in items), default=Decimal("0"))
        docs: list[str] = []
        for item in negative_items:
            ref = self._sales_profit_document_ref(item)
            if ref and ref not in docs:
                docs.append(ref)
        return {
            "codigo": code,
            "nombre": name,
            **totals,
            "lineas_negativas": len(negative_items),
            "peor_rentabilidad_pct": normalize(worst),
            "documentos_negativos": docs[:10],
        }

    def _sales_profit_group_alerts(
        self,
        items: list[dict[str, Any]],
        group_by: str,
        threshold: Decimal,
        limit: int,
        family_type: str = "ncc",
    ) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for item in items:
            code, name = self._sale_group_key(item, group_by, family_type)
            if code not in groups:
                groups[code] = {"codigo": code, "nombre": name, "items": []}
            groups[code]["items"].append(item)

        alerts: list[dict[str, Any]] = []
        for group in groups.values():
            grouped_items = group["items"]
            totals = self._sales_profit_totals(grouped_items)
            if dec(totals["rentabilidad_pct"]) < threshold:
                alerts.append(self._sales_profit_alert_group(
                    group["codigo"],
                    group["nombre"],
                    grouped_items,
                ))
        alerts.sort(key=lambda item: (dec(item["rentabilidad_pct"]), dec(item["margen"])))
        return alerts[:limit]

    def sales_profit_alerts(self, args: dict[str, Any]) -> dict[str, Any]:
        threshold = dec(args.get("umbral_rentabilidad_baja", "10"))
        if threshold < 0:
            raise FaroError("umbral_rentabilidad_baja no puede ser negativo.")
        alert_limit = max(1, min(int(args.get("limite_alertas", 50) or 50), 500))
        family_type = self._sale_family_type(args.get("tipo_familia"))

        line_args = dict(args)
        line_args.pop("umbral_rentabilidad_baja", None)
        line_args.pop("limite_alertas", None)
        line_args.pop("tipo_familia", None)
        line_args["limite"] = line_args.get("limite", 5000)
        lines = self.sales_profit_lines(**line_args)
        items = list(lines["items"])

        negative_lines = [
            item for item in items
            if dec(item.get("rentabilidad_pct")) < 0 and dec(item.get("venta_neta")) > 0
        ]
        negative_lines.sort(key=lambda item: (dec(item.get("rentabilidad_pct")), dec(item.get("margen"))))

        low_lines = [
            item for item in items
            if Decimal("0") <= dec(item.get("rentabilidad_pct")) < threshold and dec(item.get("venta_neta")) > 0
        ]
        low_lines.sort(key=lambda item: (dec(item.get("rentabilidad_pct")), dec(item.get("margen"))))

        negative_groups: dict[str, dict[str, Any]] = {}
        all_article_groups: dict[str, dict[str, Any]] = {}
        for item in items:
            code, name = self._sale_group_key(item, "articulo")
            if code not in all_article_groups:
                all_article_groups[code] = {"codigo": code, "nombre": name, "items": []}
            all_article_groups[code]["items"].append(item)
            if item in negative_lines:
                if code not in negative_groups:
                    negative_groups[code] = {"codigo": code, "nombre": name, "items": [], "negative_items": []}
                negative_groups[code]["items"].append(item)
                negative_groups[code]["negative_items"].append(item)

        articles_with_negative_lines = [
            self._sales_profit_alert_group(
                group["codigo"],
                group["nombre"],
                group["items"],
                group["negative_items"],
            )
            for group in negative_groups.values()
        ]
        articles_with_negative_lines.sort(
            key=lambda item: (dec(item["peor_rentabilidad_pct"]), dec(item["margen"]))
        )

        aggregated_negative_articles: list[dict[str, Any]] = []
        compensated_articles: list[dict[str, Any]] = []
        for group in all_article_groups.values():
            alert = self._sales_profit_alert_group(group["codigo"], group["nombre"], group["items"])
            if dec(alert["rentabilidad_pct"]) < 0:
                aggregated_negative_articles.append(alert)
            elif group["codigo"] in negative_groups:
                compensated_articles.append(alert)
        aggregated_negative_articles.sort(key=lambda item: (dec(item["rentabilidad_pct"]), dec(item["margen"])))
        compensated_articles.sort(key=lambda item: (dec(item["peor_rentabilidad_pct"]), dec(item["margen"])))

        families_low = self._sales_profit_group_alerts(items, "familia", threshold, alert_limit, family_type)
        clients_low = self._sales_profit_group_alerts(items, "cliente", threshold, alert_limit)

        warnings: list[str] = []
        if compensated_articles:
            warnings.append(
                "Hay articulos con lineas negativas que quedan compensados al agrupar todas sus ventas del periodo."
            )
        if lines["count"] >= int(lines.get("limite", 0) or 0):
            warnings.append("El analisis puede estar limitado por el maximo de lineas solicitado.")

        return {
            "moneda": lines["moneda"],
            "filtros": lines["filtros"],
            "tipo_familia": family_type,
            "umbral_rentabilidad_baja": normalize(threshold),
            "base_lineas": lines["count"],
            "totales": lines["totales"],
            "resumen_alertas": {
                "lineas_negativas": len(negative_lines),
                "lineas_baja_rentabilidad": len(low_lines),
                "articulos_con_lineas_negativas": len(articles_with_negative_lines),
                "articulos_negativos_agregados": len(aggregated_negative_articles),
                "articulos_compensados": len(compensated_articles),
                "familias_bajo_umbral": len(families_low),
                "clientes_bajo_umbral": len(clients_low),
            },
            "lineas_negativas": negative_lines[:alert_limit],
            "lineas_baja_rentabilidad": low_lines[:alert_limit],
            "articulos_con_lineas_negativas": articles_with_negative_lines[:alert_limit],
            "articulos_negativos_agregados": aggregated_negative_articles[:alert_limit],
            "articulos_compensados": compensated_articles[:alert_limit],
            "familias_bajo_umbral": families_low,
            "clientes_bajo_umbral": clients_low,
            "warnings": warnings,
        }

    def _sales_trend_periods(self, args: dict[str, Any]) -> tuple[date, date, date, date]:
        start = self._parse_optional_date(args.get("fecha_desde"))
        end = self._parse_optional_date(args.get("fecha_hasta"))
        if not start or not end:
            raise FaroError("fecha_desde y fecha_hasta son obligatorias.")
        if start > end:
            raise FaroError("fecha_desde no puede ser posterior a fecha_hasta.")

        compare_start = self._parse_optional_date(args.get("comparar_fecha_desde"))
        compare_end = self._parse_optional_date(args.get("comparar_fecha_hasta"))
        if bool(compare_start) != bool(compare_end):
            raise FaroError("comparar_fecha_desde y comparar_fecha_hasta deben indicarse juntas.")
        if compare_start and compare_end:
            if compare_start > compare_end:
                raise FaroError("comparar_fecha_desde no puede ser posterior a comparar_fecha_hasta.")
            return start, end, compare_start, compare_end

        days = (end - start).days + 1
        compare_end = start - timedelta(days=1)
        compare_start = compare_end - timedelta(days=days - 1)
        return start, end, compare_start, compare_end

    @staticmethod
    def _sales_trend_variation(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        venta_current = dec(current.get("venta_neta"))
        venta_previous = dec(previous.get("venta_neta"))
        margen_current = dec(current.get("margen"))
        margen_previous = dec(previous.get("margen"))
        unidades_current = dec(current.get("unidades"))
        unidades_previous = dec(previous.get("unidades"))
        rent_current = dec(current.get("rentabilidad_pct"))
        rent_previous = dec(previous.get("rentabilidad_pct"))

        def pct(delta: Decimal, base: Decimal) -> str | None:
            if base == 0:
                return None
            return normalize((delta / base) * Decimal("100"))

        venta_delta = venta_current - venta_previous
        margen_delta = margen_current - margen_previous
        unidades_delta = unidades_current - unidades_previous
        return {
            "venta_neta_delta": normalize(venta_delta),
            "venta_neta_variacion_pct": pct(venta_delta, venta_previous),
            "margen_delta": normalize(margen_delta),
            "margen_variacion_pct": pct(margen_delta, margen_previous),
            "unidades_delta": normalize(unidades_delta),
            "unidades_variacion_pct": pct(unidades_delta, unidades_previous),
            "rentabilidad_pct_delta": normalize(rent_current - rent_previous),
        }

    def business_trends(self, args: dict[str, Any]) -> dict[str, Any]:
        start, end, compare_start, compare_end = self._sales_trend_periods(args)
        group_by = str(args.get("agrupar_por", "familia") or "familia").strip().lower()
        if group_by not in SALE_PROFIT_GROUP_FIELDS:
            raise FaroError(
                "agrupar_por debe ser uno de: " + ", ".join(sorted(SALE_PROFIT_GROUP_FIELDS))
            )
        family_type = self._sale_family_type(args.get("tipo_familia"))
        threshold = dec(args.get("umbral_variacion_pct", "10"))
        if threshold < 0:
            raise FaroError("umbral_variacion_pct no puede ser negativo.")
        alert_limit = max(1, min(int(args.get("limite_alertas", 20) or 20), 200))

        summary_args = dict(args)
        for key in (
            "comparar_fecha_desde", "comparar_fecha_hasta", "umbral_variacion_pct",
            "limite_alertas", "ordenar_por", "sentido",
        ):
            summary_args.pop(key, None)
        summary_args["agrupar_por"] = group_by
        summary_args["tipo_familia"] = family_type
        summary_args["ordenar_por"] = "venta_neta"
        summary_args["sentido"] = "desc"

        current_args = dict(summary_args)
        current_args["fecha_desde"] = start.isoformat()
        current_args["fecha_hasta"] = end.isoformat()
        previous_args = dict(summary_args)
        previous_args["fecha_desde"] = compare_start.isoformat()
        previous_args["fecha_hasta"] = compare_end.isoformat()

        current = self.sales_profit_summary(current_args)
        previous = self.sales_profit_summary(previous_args)
        current_map = {item["codigo"]: item for item in current["items"]}
        previous_map = {item["codigo"]: item for item in previous["items"]}

        def build_entry(code: str, cur: dict[str, Any] | None, prev: dict[str, Any] | None) -> dict[str, Any]:
            cur_item = cur or {
                "codigo": code, "nombre": (prev or {}).get("nombre", code), "lineas": 0,
                "unidades": "0", "venta_neta": "0", "coste": "0", "margen": "0",
                "rentabilidad_pct": "0",
            }
            prev_item = prev or {
                "codigo": code, "nombre": (cur or {}).get("nombre", code), "lineas": 0,
                "unidades": "0", "venta_neta": "0", "coste": "0", "margen": "0",
                "rentabilidad_pct": "0",
            }
            return {
                "codigo": code,
                "nombre": cur_item.get("nombre") or prev_item.get("nombre") or code,
                "actual": cur_item,
                "comparativo": prev_item,
                "variacion": self._sales_trend_variation(cur_item, prev_item),
            }

        common: list[dict[str, Any]] = []
        appear: list[dict[str, Any]] = []
        disappear: list[dict[str, Any]] = []
        for code in sorted(set(current_map) | set(previous_map)):
            cur = current_map.get(code)
            prev = previous_map.get(code)
            entry = build_entry(code, cur, prev)
            if cur and prev:
                common.append(entry)
            elif cur:
                appear.append(entry)
            else:
                disappear.append(entry)

        rises = [
            item for item in common
            if dec(item["variacion"]["venta_neta_delta"]) > 0
            and item["variacion"]["venta_neta_variacion_pct"] is not None
            and dec(item["variacion"]["venta_neta_variacion_pct"]) >= threshold
        ]
        drops = [
            item for item in common
            if dec(item["variacion"]["venta_neta_delta"]) < 0
            and item["variacion"]["venta_neta_variacion_pct"] is not None
            and abs(dec(item["variacion"]["venta_neta_variacion_pct"])) >= threshold
        ]
        margin_worse = [
            item for item in common
            if dec(item["variacion"]["rentabilidad_pct_delta"]) < 0
        ]

        rises.sort(key=lambda item: dec(item["variacion"]["venta_neta_delta"]), reverse=True)
        drops.sort(key=lambda item: dec(item["variacion"]["venta_neta_delta"]))
        margin_worse.sort(key=lambda item: dec(item["variacion"]["rentabilidad_pct_delta"]))
        appear.sort(key=lambda item: dec(item["actual"]["venta_neta"]), reverse=True)
        disappear.sort(key=lambda item: dec(item["comparativo"]["venta_neta"]), reverse=True)

        total_variation = self._sales_trend_variation(current["totales"], previous["totales"])
        return {
            "agrupar_por": group_by,
            "tipo_familia": family_type if group_by in {"familia", "subfamilia"} else None,
            "periodo_actual": {"fecha_desde": start.isoformat(), "fecha_hasta": end.isoformat()},
            "periodo_comparativo": {
                "fecha_desde": compare_start.isoformat(),
                "fecha_hasta": compare_end.isoformat(),
                "inferido": not (args.get("comparar_fecha_desde") and args.get("comparar_fecha_hasta")),
            },
            "moneda": current["moneda"],
            "umbral_variacion_pct": normalize(threshold),
            "totales_actual": current["totales"],
            "totales_comparativo": previous["totales"],
            "variacion_totales": total_variation,
            "resumen_tendencias": {
                "grupos_actuales": len(current_map),
                "grupos_comparativos": len(previous_map),
                "suben": len(rises),
                "bajan": len(drops),
                "empeoran_rentabilidad": len(margin_worse),
                "aparecen": len(appear),
                "desaparecen": len(disappear),
            },
            "suben": rises[:alert_limit],
            "bajan": drops[:alert_limit],
            "empeoran_rentabilidad": margin_worse[:alert_limit],
            "aparecen": appear[:alert_limit],
            "desaparecen": disappear[:alert_limit],
            "warnings": current.get("warnings", []) + previous.get("warnings", []),
        }

    @staticmethod
    def _sales_empty_totals() -> dict[str, Any]:
        return {
            "lineas": 0,
            "unidades": "0",
            "venta_neta": "0",
            "coste": "0",
            "margen": "0",
            "rentabilidad_pct": "0",
        }

    @staticmethod
    def _sales_average(value: Any, units: Any) -> Decimal:
        quantity = dec(units)
        if quantity == 0:
            return Decimal("0")
        return dec(value) / quantity

    def _sales_diagnostic_variation(self, current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        variation = self._sales_trend_variation(current, previous)
        current_units = dec(current.get("unidades"))
        previous_units = dec(previous.get("unidades"))
        current_price = self._sales_average(current.get("venta_neta"), current.get("unidades"))
        previous_price = self._sales_average(previous.get("venta_neta"), previous.get("unidades"))
        current_cost = self._sales_average(current.get("coste"), current.get("unidades"))
        previous_cost = self._sales_average(previous.get("coste"), previous.get("unidades"))
        current_margin = self._sales_average(current.get("margen"), current.get("unidades"))
        previous_margin = self._sales_average(previous.get("margen"), previous.get("unidades"))
        return {
            **variation,
            "precio_medio_actual": normalize(current_price),
            "precio_medio_comparativo": normalize(previous_price),
            "precio_medio_delta": normalize(current_price - previous_price),
            "coste_medio_actual": normalize(current_cost),
            "coste_medio_comparativo": normalize(previous_cost),
            "coste_medio_delta": normalize(current_cost - previous_cost),
            "margen_unitario_actual": normalize(current_margin),
            "margen_unitario_comparativo": normalize(previous_margin),
            "margen_unitario_delta": normalize(current_margin - previous_margin),
            "impacto_unidades_aprox": normalize((current_units - previous_units) * previous_price),
            "impacto_precio_aprox": normalize((current_price - previous_price) * current_units),
            "impacto_coste_aprox": normalize((previous_cost - current_cost) * current_units),
        }

    @staticmethod
    def _sales_diagnostic_reason(variation: dict[str, Any]) -> str:
        venta_delta = dec(variation.get("venta_neta_delta"))
        margen_delta = dec(variation.get("margen_delta"))
        units_delta = dec(variation.get("unidades_delta"))
        price_delta = dec(variation.get("precio_medio_delta"))
        cost_delta = dec(variation.get("coste_medio_delta"))
        rent_delta = dec(variation.get("rentabilidad_pct_delta"))
        if venta_delta < 0 and units_delta < 0:
            return "menos_unidades"
        if venta_delta < 0 and price_delta < 0:
            return "menor_precio_medio"
        if margen_delta < 0 and cost_delta > 0:
            return "mayor_coste_medio"
        if margen_delta < 0 and rent_delta < 0:
            return "peor_rentabilidad"
        if venta_delta > 0 and margen_delta < 0:
            return "vende_mas_con_menos_margen"
        if venta_delta > 0:
            return "sube_venta"
        if venta_delta < 0:
            return "baja_venta"
        return "estable"

    def _sales_diagnostic_aggregate(
        self,
        items: list[dict[str, Any]],
        group_by: str,
        family_type: str,
    ) -> dict[str, dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for item in items:
            code, name = self._sale_group_key(item, group_by, family_type)
            if code not in groups:
                groups[code] = {"codigo": code, "nombre": name, "items": []}
            groups[code]["items"].append(item)
        return {
            code: {"codigo": group["codigo"], "nombre": group["nombre"], **self._sales_profit_totals(group["items"])}
            for code, group in groups.items()
        }

    def _sales_diagnostic_compare_groups(
        self,
        current: dict[str, dict[str, Any]],
        previous: dict[str, dict[str, Any]],
        limit: int,
        order_key: str,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for code in sorted(set(current) | set(previous)):
            cur = current.get(code) or {"codigo": code, "nombre": previous.get(code, {}).get("nombre", code), **self._sales_empty_totals()}
            prev = previous.get(code) or {"codigo": code, "nombre": current.get(code, {}).get("nombre", code), **self._sales_empty_totals()}
            variation = self._sales_diagnostic_variation(cur, prev)
            result.append({
                "codigo": code,
                "nombre": cur.get("nombre") or prev.get("nombre") or code,
                "actual": cur,
                "comparativo": prev,
                "variacion": variation,
                "motivo_principal": self._sales_diagnostic_reason(variation),
            })
        result.sort(key=lambda item: dec(item["variacion"].get(order_key)), reverse=False)
        return result[:limit]

    def business_change_diagnosis(self, args: dict[str, Any]) -> dict[str, Any]:
        start, end, compare_start, compare_end = self._sales_trend_periods(args)
        group_by = str(args.get("agrupar_por", "familia") or "familia").strip().lower()
        if group_by not in SALE_PROFIT_GROUP_FIELDS:
            raise FaroError(
                "agrupar_por debe ser uno de: " + ", ".join(sorted(SALE_PROFIT_GROUP_FIELDS))
            )
        family_type = self._sale_family_type(args.get("tipo_familia"))
        focus_code = str(args.get("codigo_grupo") or "").strip()
        detail_limit = max(1, min(int(args.get("limite_detalle", 20) or 20), 200))

        line_args = dict(args)
        for key in (
            "agrupar_por", "tipo_familia", "codigo_grupo", "comparar_fecha_desde",
            "comparar_fecha_hasta", "limite_detalle",
        ):
            line_args.pop(key, None)
        line_args["limite"] = line_args.get("limite", 5000)

        current_args = dict(line_args)
        current_args["fecha_desde"] = start.isoformat()
        current_args["fecha_hasta"] = end.isoformat()
        previous_args = dict(line_args)
        previous_args["fecha_desde"] = compare_start.isoformat()
        previous_args["fecha_hasta"] = compare_end.isoformat()

        current_lines = self.sales_profit_lines(**current_args)
        previous_lines = self.sales_profit_lines(**previous_args)

        def filter_focus(lines: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
            if not focus_code:
                return list(lines), "Todos"
            focused: list[dict[str, Any]] = []
            focus_name = focus_code
            for item in lines:
                code, name = self._sale_group_key(item, group_by, family_type)
                if code == focus_code:
                    focused.append(item)
                    focus_name = name or focus_name
            return focused, focus_name

        current_items, current_focus_name = filter_focus(current_lines["items"])
        previous_items, previous_focus_name = filter_focus(previous_lines["items"])
        focus_name = current_focus_name if current_items else previous_focus_name
        current_totals = self._sales_profit_totals(current_items)
        previous_totals = self._sales_profit_totals(previous_items)
        total_variation = self._sales_diagnostic_variation(current_totals, previous_totals)

        articles = self._sales_diagnostic_compare_groups(
            self._sales_diagnostic_aggregate(current_items, "articulo", family_type),
            self._sales_diagnostic_aggregate(previous_items, "articulo", family_type),
            detail_limit,
            "margen_delta",
        )
        clients = self._sales_diagnostic_compare_groups(
            self._sales_diagnostic_aggregate(current_items, "cliente", family_type),
            self._sales_diagnostic_aggregate(previous_items, "cliente", family_type),
            detail_limit,
            "venta_neta_delta",
        )

        negative_current = [
            item for item in current_items
            if dec(item.get("rentabilidad_pct")) < 0 and dec(item.get("venta_neta")) > 0
        ]
        negative_current.sort(key=lambda item: (dec(item.get("rentabilidad_pct")), dec(item.get("margen"))))

        warnings: list[str] = []
        if current_lines["count"] >= int(current_lines.get("limite", 0) or 0):
            warnings.append("El periodo actual puede estar limitado por el maximo de lineas solicitado.")
        if previous_lines["count"] >= int(previous_lines.get("limite", 0) or 0):
            warnings.append("El periodo comparativo puede estar limitado por el maximo de lineas solicitado.")
        if focus_code and not current_items and not previous_items:
            warnings.append("No se encontraron lineas para el codigo_grupo indicado en ninguno de los dos periodos.")

        return {
            "agrupar_por": group_by,
            "tipo_familia": family_type if group_by in {"familia", "subfamilia"} else None,
            "foco": {
                "codigo": focus_code or None,
                "nombre": focus_name,
            },
            "periodo_actual": {"fecha_desde": start.isoformat(), "fecha_hasta": end.isoformat()},
            "periodo_comparativo": {
                "fecha_desde": compare_start.isoformat(),
                "fecha_hasta": compare_end.isoformat(),
                "inferido": not (args.get("comparar_fecha_desde") and args.get("comparar_fecha_hasta")),
            },
            "moneda": current_lines["moneda"],
            "base_lineas_actual": len(current_items),
            "base_lineas_comparativo": len(previous_items),
            "totales_actual": current_totals,
            "totales_comparativo": previous_totals,
            "diagnostico": {
                "variacion": total_variation,
                "motivo_principal": self._sales_diagnostic_reason(total_variation),
                "lineas_negativas_actuales": len(negative_current),
                "articulos_analizados": len(set(item["articulo"]["codigo"] for item in current_items + previous_items)),
                "clientes_analizados": len(set(
                    f"{item['cliente']['codigo']}/{item['cliente']['subcliente']}"
                    for item in current_items + previous_items
                )),
            },
            "articulos_que_explican_cambio": articles,
            "clientes_que_explican_cambio": clients,
            "lineas_negativas_actuales": negative_current[:detail_limit],
            "warnings": warnings,
        }

    def _stock_analysis_period(self, args: dict[str, Any]) -> tuple[date, date]:
        start = self._parse_optional_date(args.get("fecha_desde"))
        end = self._parse_optional_date(args.get("fecha_hasta"))
        if not start or not end:
            raise FaroError("fecha_desde y fecha_hasta son obligatorias.")
        if start > end:
            raise FaroError("fecha_desde no puede ser posterior a fecha_hasta.")
        return start, end

    def _stock_article_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        own_family = int(row.get("ART_CODFAM") or 0)
        own_subfamily = int(row.get("ART_SUBFAM") or 0)
        coop_family = clean_text_value(row.get("ART_AGRUP1")) or "0"
        coop_subfamily = clean_text_value(row.get("ART_AGRUP2")) or "0"
        coop_level3 = clean_text_value(row.get("ART_AGRUP3")) or "0"
        ncc_code = clean_text_value(row.get("FAMILIA_NCC"))
        ncc_level1 = ncc_code[:2] if len(ncc_code) >= 2 else ncc_code
        ncc_level2 = ncc_code[:4] if len(ncc_code) >= 4 else ncc_code
        ncc_level3 = ncc_code[:6] if len(ncc_code) >= 6 else ncc_code
        return {
            "codigo": str(row.get("ART_CODART") or "").strip(),
            "descripcion": clean_text_value(row.get("ART_DESCRI")),
            "seccion": clean_text_value(row.get("ART_SECCIO")) or "0",
            "familia": own_family,
            "familia_nombre": clean_text_value(row.get("FAM_DESCRI")),
            "subfamilia": own_subfamily,
            "subfamilia_nombre": clean_text_value(row.get("SUB_DESCRI")),
            "familia_propia": {
                "familia": own_family,
                "familia_nombre": clean_text_value(row.get("FAM_DESCRI")),
                "subfamilia": own_subfamily,
                "subfamilia_nombre": clean_text_value(row.get("SUB_DESCRI")),
            },
            "familia_cooperativa": {
                "familia": coop_family,
                "familia_nombre": clean_text_value(row.get("COOP_FAM_DESCRI")) or coop_family,
                "subfamilia": coop_subfamily,
                "subfamilia_nombre": clean_text_value(row.get("COOP_SUB_DESCRI")) or coop_subfamily,
                "nivel3": coop_level3,
                "nivel3_nombre": coop_level3,
            },
            "familia_ncc": {
                "codigo": ncc_code,
                "familia": ncc_level1,
                "familia_nombre": clean_text_value(row.get("NCC_NIVEL1_DESCRI")) or ncc_level1,
                "subfamilia": ncc_level2,
                "subfamilia_nombre": clean_text_value(row.get("NCC_NIVEL2_DESCRI")) or ncc_level2,
                "nivel3": ncc_level3,
                "nivel3_nombre": clean_text_value(row.get("NCC_NIVEL3_DESCRI")) or ncc_level3,
            },
            "marca": clean_text_value(row.get("MARCA")),
        }

    def _stock_analysis_rows(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        limit = max(1, min(int(args.get("limite", 5000) or 5000), 10000))
        min_stock = dec(args.get("stock_minimo", "0"))
        centro = args.get("centro")
        proveedor_desde = args.get("proveedor_desde")
        proveedor_hasta = args.get("proveedor_hasta")
        articulo_desde = str(args.get("articulo_desde") or "").strip()
        articulo_hasta = str(args.get("articulo_hasta") or "").strip()
        descripcion = str(args.get("descripcion") or "").strip()
        solo_con_stock = bool(args.get("solo_con_stock", True))

        where = ["A.ART_NUMEMP=?"]
        params: list[Any] = [self.settings.empresa]
        if _center_filter_is_set(centro):
            where.append("E.ARTE_CENTRO=?")
            params.append(int(centro))
        if solo_con_stock:
            where.append("E.ARTE_EXIST>?")
            params.append(min_stock)
        else:
            where.append("E.ARTE_EXIST>=?")
            params.append(min_stock)
        if proveedor_desde not in (None, "", 0):
            where.append("A.ART_CODPRO>=?")
            params.append(int(proveedor_desde))
        if proveedor_hasta not in (None, "", 0):
            where.append("A.ART_CODPRO<=?")
            params.append(int(proveedor_hasta))
        if articulo_desde:
            where.append("A.ART_CODART>=?")
            params.append(articulo_desde)
        if articulo_hasta:
            where.append("A.ART_CODART<=?")
            params.append(articulo_hasta)
        if descripcion:
            where.append("UPPER(A.ART_DESCRI) LIKE ?")
            params.append(f"%{descripcion.upper()}%")

        return self.db.fetch_all(
            f"""
            SELECT FIRST {limit}
                A.ART_CODART, A.ART_DESCRI, A.ART_UNIMED, A.ART_PRECOS, A.ART_CODPRO,
                A.ART_SECCIO, A.ART_CODFAM, A.ART_SUBFAM, A.ART_AGRUP1, A.ART_AGRUP2, A.ART_AGRUP3,
                E.ARTE_CENTRO, E.ARTE_EXIST, E.ARTE_MINIMO, E.ARTE_MAXIMO,
                E.ARTE_FECCOM, E.ARTE_FECVEN, E.ARTE_FECMOV,
                P.PRO_NOMCOR, F.FAM_DESCRI, S.SUB_DESCRI,
                CF.FAM_DESCRI AS COOP_FAM_DESCRI, CS.SUB_DESCRI AS COOP_SUB_DESCRI,
                M.ARTI_DESCRI AS MARCA, NCC.ARTI_DESCRI AS FAMILIA_NCC,
                FN1.NCC_DESCRI AS NCC_NIVEL1_DESCRI, FN2.NCC_DESCRI AS NCC_NIVEL2_DESCRI,
                FN3.NCC_DESCRI AS NCC_NIVEL3_DESCRI
            FROM ARTICUL A
            JOIN ARTICULE E ON E.ARTE_NUMEMP=A.ART_NUMEMP AND E.ARTE_CODART=A.ART_CODART
            LEFT JOIN PROVEE P ON P.PRO_NUMEMP=A.ART_NUMEMP AND P.PRO_CODPRO=A.ART_CODPRO
            LEFT JOIN FAMILI F ON F.FAM_NUMEMP=A.ART_NUMEMP AND F.FAM_CODIGO=A.ART_CODFAM
            LEFT JOIN SUBFAM S ON S.SUB_NUMEMP=A.ART_NUMEMP
                AND S.SUB_CODFAM=A.ART_CODFAM AND S.SUB_CODIGO=A.ART_SUBFAM
            LEFT JOIN FAMILI CF ON CF.FAM_NUMEMP=A.ART_NUMEMP AND CF.FAM_CODIGO=A.ART_AGRUP1
            LEFT JOIN SUBFAM CS ON CS.SUB_NUMEMP=A.ART_NUMEMP
                AND CS.SUB_CODFAM=A.ART_AGRUP1 AND CS.SUB_CODIGO=A.ART_AGRUP2
            LEFT JOIN ARTICULI M ON M.ARTI_NUMEMP=A.ART_NUMEMP
                AND M.ARTI_CODART=A.ART_CODART AND M.ARTI_CODINF='MARCA'
            LEFT JOIN ARTICULI NCC ON NCC.ARTI_NUMEMP=A.ART_NUMEMP
                AND NCC.ARTI_CODART=A.ART_CODART AND NCC.ARTI_CODINF='FAMNC'
            LEFT JOIN FAMNCC FN1 ON FN1.NCC_NUMEMP=A.ART_NUMEMP
                AND FN1.NCC_CODIGO=SUBSTRING(NCC.ARTI_DESCRI FROM 1 FOR 2)
            LEFT JOIN FAMNCC FN2 ON FN2.NCC_NUMEMP=A.ART_NUMEMP
                AND FN2.NCC_CODIGO=SUBSTRING(NCC.ARTI_DESCRI FROM 1 FOR 4)
            LEFT JOIN FAMNCC FN3 ON FN3.NCC_NUMEMP=A.ART_NUMEMP
                AND FN3.NCC_CODIGO=SUBSTRING(NCC.ARTI_DESCRI FROM 1 FOR 6)
            WHERE {" AND ".join(where)}
            ORDER BY E.ARTE_EXIST DESC, A.ART_CODART
            """,
            tuple(params),
        )

    def _stock_purchase_totals(
        self,
        start: date,
        end: date,
        centro: Any = None,
        moneda: str = "E",
    ) -> dict[str, dict[str, Any]]:
        where = [
            "DMM_NUMEMP=?",
            "DMM_FECMOV BETWEEN ? AND ?",
            "DMM_TIPLIN='D'",
            "DMM_CODART<>''",
        ]
        params: list[Any] = [self.settings.empresa, start, end]
        if _center_filter_is_set(centro):
            where.append("DMM_CENTRO=?")
            params.append(int(centro))
        rows = self.db.fetch_all(
            f"""
            SELECT DMM_CODART, SUM(DMM_CANTID) AS UNIDADES,
                SUM(DMM_VALLIN - DMM_IMPDTO) AS IMPORTE
            FROM DETMOVM
            WHERE {" AND ".join(where)}
            GROUP BY DMM_CODART
            """,
            tuple(params),
        )
        return {
            str(row.get("DMM_CODART") or "").strip(): {
                "unidades": normalize(dec(row.get("UNIDADES"))),
                "importe": normalize(dec(row.get("IMPORTE"))),
                "moneda": moneda,
            }
            for row in rows
        }

    def _stock_sales_totals(self, args: dict[str, Any], start: date, end: date) -> dict[str, dict[str, Any]]:
        sales_args = dict(args)
        for key in (
            "tipo_familia", "agrupar_por", "limite_detalle", "stock_minimo", "solo_con_stock",
            "dias_cobertura_alta", "dias_sin_vender_alerta", "comparar_fecha_desde",
            "comparar_fecha_hasta", "limite_alertas",
        ):
            sales_args.pop(key, None)
        sales_args["fecha_desde"] = start.isoformat()
        sales_args["fecha_hasta"] = end.isoformat()
        sales_args["agrupar_por"] = "articulo"
        sales_args["ordenar_por"] = "venta_neta"
        sales_args["sentido"] = "desc"
        sales_args["limite"] = sales_args.get("limite", 5000)
        sales_args["limite_grupos"] = None
        summary = self.sales_profit_summary(sales_args)
        return {item["codigo"]: item for item in summary["items"]}

    @staticmethod
    def _stock_days_between(end: date, value: Any) -> int | None:
        movement_date = FaroPhase1Service._parse_optional_date(value)
        if not movement_date:
            return None
        return max(0, (end - movement_date).days)

    def _stock_rotation_items(self, args: dict[str, Any], start: date, end: date) -> dict[str, Any]:
        family_type = self._sale_family_type(args.get("tipo_familia"))
        detail_limit = max(1, min(int(args.get("limite_detalle", 50) or 50), 500))
        coverage_threshold = dec(args.get("dias_cobertura_alta", "180"))
        no_sale_threshold = int(args.get("dias_sin_vender_alerta", 180) or 180)
        moneda = str(args.get("moneda", "E") or "E").strip().upper()[:1] or "E"
        rows = self._stock_analysis_rows(args)
        sales = self._stock_sales_totals(args, start, end)
        purchases = self._stock_purchase_totals(start, end, args.get("centro"), moneda)
        period_days = Decimal((end - start).days + 1)

        by_article: dict[str, dict[str, Any]] = {}
        for row in rows:
            article = self._stock_article_from_row(row)
            code = article["codigo"]
            stock = dec(row.get("ARTE_EXIST"))
            cost = dec(row.get("ART_PRECOS"))
            bucket = by_article.setdefault(code, {
                "articulo": article,
                "proveedor": {
                    "codigo": int(row.get("ART_CODPRO") or 0),
                    "nombre": clean_text_value(row.get("PRO_NOMCOR")),
                },
                "stock_actual": Decimal("0"),
                "valor_stock": Decimal("0"),
                "centros": [],
                "fecha_ultima_compra": None,
                "fecha_ultima_venta": None,
                "fecha_ultimo_movimiento": None,
            })
            bucket["stock_actual"] += stock
            bucket["valor_stock"] += stock * cost
            bucket["centros"].append({
                "centro": int(row.get("ARTE_CENTRO") or 0),
                "stock": normalize(stock),
                "minimo": normalize(dec(row.get("ARTE_MINIMO"))),
                "maximo": normalize(dec(row.get("ARTE_MAXIMO"))),
            })
            for source_key, target_key in (
                ("ARTE_FECCOM", "fecha_ultima_compra"),
                ("ARTE_FECVEN", "fecha_ultima_venta"),
                ("ARTE_FECMOV", "fecha_ultimo_movimiento"),
            ):
                value = row.get(source_key)
                if value and (bucket[target_key] is None or value > bucket[target_key]):
                    bucket[target_key] = value

        items: list[dict[str, Any]] = []
        for code, bucket in by_article.items():
            sale = sales.get(code, self._sales_empty_totals())
            purchase = purchases.get(code, {"unidades": "0", "importe": "0", "moneda": moneda})
            sold_units = dec(sale.get("unidades"))
            stock = bucket["stock_actual"]
            daily_units = sold_units / period_days if period_days > 0 else Decimal("0")
            coverage_days = stock / daily_units if daily_units > 0 else None
            days_without_sale = self._stock_days_between(end, bucket["fecha_ultima_venta"])
            alerts: list[str] = []
            if stock > 0 and sold_units == 0:
                alerts.append("stock_sin_ventas")
            if coverage_days is None and stock > 0:
                alerts.append("sin_rotacion")
            elif coverage_days is not None and coverage_days >= coverage_threshold:
                alerts.append("sobrestock")
            if days_without_sale is None or days_without_sale >= no_sale_threshold:
                alerts.append("baja_rotacion")
            if dec(purchase.get("unidades")) > 0 and sold_units == 0:
                alerts.append("compra_sin_salida")
            item = {
                "articulo": bucket["articulo"],
                "proveedor": bucket["proveedor"],
                "stock_actual": normalize(stock),
                "valor_stock": normalize(bucket["valor_stock"]),
                "ventas_periodo": sale,
                "compras_periodo": purchase,
                "rotacion_unidades": normalize(sold_units / stock) if stock != 0 else None,
                "dias_cobertura": normalize(coverage_days) if coverage_days is not None else None,
                "fecha_ultima_compra": bucket["fecha_ultima_compra"].isoformat() if bucket["fecha_ultima_compra"] else None,
                "fecha_ultima_venta": bucket["fecha_ultima_venta"].isoformat() if bucket["fecha_ultima_venta"] else None,
                "fecha_ultimo_movimiento": bucket["fecha_ultimo_movimiento"].isoformat() if bucket["fecha_ultimo_movimiento"] else None,
                "dias_sin_vender": days_without_sale,
                "centros": bucket["centros"],
                "alertas": alerts,
            }
            items.append(item)

        items.sort(key=lambda item: dec(item["valor_stock"]), reverse=True)
        totals = {
            "articulos": len(items),
            "stock_actual": normalize(sum((dec(item["stock_actual"]) for item in items), Decimal("0"))),
            "valor_stock": normalize(sum((dec(item["valor_stock"]) for item in items), Decimal("0"))),
            "venta_neta_periodo": normalize(sum((dec(item["ventas_periodo"].get("venta_neta")) for item in items), Decimal("0"))),
            "unidades_vendidas_periodo": normalize(sum((dec(item["ventas_periodo"].get("unidades")) for item in items), Decimal("0"))),
            "unidades_compradas_periodo": normalize(sum((dec(item["compras_periodo"].get("unidades")) for item in items), Decimal("0"))),
        }
        return {
            "items": items,
            "items_limitados": items[:detail_limit],
            "totales": totals,
            "tipo_familia": family_type,
            "periodo_dias": int(period_days),
            "warnings": [
                "La valoracion de stock usa ART_PRECOS; no revaloriza a coste historico por lote."
            ],
        }

    def stock_rotation_analysis(self, args: dict[str, Any]) -> dict[str, Any]:
        start, end = self._stock_analysis_period(args)
        group_by = str(args.get("agrupar_por", "familia") or "familia").strip().lower()
        if group_by not in SALE_PROFIT_GROUP_FIELDS:
            raise FaroError(
                "agrupar_por debe ser uno de: " + ", ".join(sorted(SALE_PROFIT_GROUP_FIELDS))
            )
        data = self._stock_rotation_items(args, start, end)
        family_type = data["tipo_familia"]
        groups: dict[str, dict[str, Any]] = {}
        for item in data["items"]:
            group_item = {"articulo": item["articulo"], "proveedor": item["proveedor"], "cliente": {"codigo": 0, "subcliente": 0, "nombre": ""}, "documento": {"centro": 0, "tipo": ""}, "representante": 0, "mes": "", "dia_semana": ""}
            code, name = self._sale_group_key(group_item, group_by, family_type)
            group = groups.setdefault(code, {
                "codigo": code,
                "nombre": name,
                "articulos": 0,
                "stock_actual": Decimal("0"),
                "valor_stock": Decimal("0"),
                "venta_neta_periodo": Decimal("0"),
                "unidades_vendidas_periodo": Decimal("0"),
                "unidades_compradas_periodo": Decimal("0"),
                "alertas": {},
            })
            group["articulos"] += 1
            group["stock_actual"] += dec(item["stock_actual"])
            group["valor_stock"] += dec(item["valor_stock"])
            group["venta_neta_periodo"] += dec(item["ventas_periodo"].get("venta_neta"))
            group["unidades_vendidas_periodo"] += dec(item["ventas_periodo"].get("unidades"))
            group["unidades_compradas_periodo"] += dec(item["compras_periodo"].get("unidades"))
            for alert in item["alertas"]:
                group["alertas"][alert] = int(group["alertas"].get(alert, 0)) + 1

        group_items = []
        for group in groups.values():
            stock = group["stock_actual"]
            sold = group["unidades_vendidas_periodo"]
            group_items.append({
                "codigo": group["codigo"],
                "nombre": group["nombre"],
                "articulos": group["articulos"],
                "stock_actual": normalize(stock),
                "valor_stock": normalize(group["valor_stock"]),
                "venta_neta_periodo": normalize(group["venta_neta_periodo"]),
                "unidades_vendidas_periodo": normalize(sold),
                "unidades_compradas_periodo": normalize(group["unidades_compradas_periodo"]),
                "rotacion_unidades": normalize(sold / stock) if stock != 0 else None,
                "alertas": group["alertas"],
            })
        group_items.sort(key=lambda item: dec(item["valor_stock"]), reverse=True)
        detail_limit = max(1, min(int(args.get("limite_detalle", 50) or 50), 500))
        return {
            "agrupar_por": group_by,
            "tipo_familia": family_type if group_by in {"familia", "subfamilia"} else None,
            "periodo": {"fecha_desde": start.isoformat(), "fecha_hasta": end.isoformat(), "dias": data["periodo_dias"]},
            "totales": data["totales"],
            "grupos": group_items[:detail_limit],
            "articulos_mayor_stock": data["items_limitados"],
            "stock_sin_ventas": [item for item in data["items"] if "stock_sin_ventas" in item["alertas"]][:detail_limit],
            "sobrestock": [item for item in data["items"] if "sobrestock" in item["alertas"]][:detail_limit],
            "compra_sin_salida": [item for item in data["items"] if "compra_sin_salida" in item["alertas"]][:detail_limit],
            "warnings": data["warnings"],
        }

    def stock_trends_analysis(self, args: dict[str, Any]) -> dict[str, Any]:
        start, end, compare_start, compare_end = self._sales_trend_periods(args)
        current = self._stock_rotation_items(args, start, end)
        previous_args = dict(args)
        previous_args["fecha_desde"] = compare_start.isoformat()
        previous_args["fecha_hasta"] = compare_end.isoformat()
        previous = self._stock_rotation_items(previous_args, compare_start, compare_end)
        current_map = {item["articulo"]["codigo"]: item for item in current["items"]}
        previous_map = {item["articulo"]["codigo"]: item for item in previous["items"]}
        detail_limit = max(1, min(int(args.get("limite_detalle", 50) or 50), 500))

        items: list[dict[str, Any]] = []
        for code in sorted(set(current_map) | set(previous_map)):
            cur = current_map.get(code)
            prev = previous_map.get(code)
            article = (cur or prev or {}).get("articulo", {"codigo": code, "descripcion": code})
            cur_stock = dec((cur or {}).get("stock_actual"))
            prev_stock = dec((prev or {}).get("stock_actual"))
            cur_sales = dec(((cur or {}).get("ventas_periodo") or {}).get("venta_neta"))
            prev_sales = dec(((prev or {}).get("ventas_periodo") or {}).get("venta_neta"))
            cur_margin = dec(((cur or {}).get("ventas_periodo") or {}).get("margen"))
            prev_margin = dec(((prev or {}).get("ventas_periodo") or {}).get("margen"))
            alerts: list[str] = []
            if cur_stock > prev_stock and cur_sales < prev_sales:
                alerts.append("stock_sube_ventas_bajan")
            if cur_stock > prev_stock and cur_margin < prev_margin:
                alerts.append("stock_sube_margen_baja")
            if cur_stock > 0 and cur_sales == 0:
                alerts.append("stock_actual_sin_ventas")
            items.append({
                "articulo": article,
                "stock_actual": normalize(cur_stock),
                "stock_comparativo": normalize(prev_stock),
                "stock_delta": normalize(cur_stock - prev_stock),
                "valor_stock_actual": (cur or {}).get("valor_stock", "0"),
                "valor_stock_comparativo": (prev or {}).get("valor_stock", "0"),
                "valor_stock_delta": normalize(dec((cur or {}).get("valor_stock")) - dec((prev or {}).get("valor_stock"))),
                "venta_neta_actual": normalize(cur_sales),
                "venta_neta_comparativo": normalize(prev_sales),
                "venta_neta_delta": normalize(cur_sales - prev_sales),
                "margen_actual": normalize(cur_margin),
                "margen_comparativo": normalize(prev_margin),
                "margen_delta": normalize(cur_margin - prev_margin),
                "alertas": alerts,
            })
        items.sort(key=lambda item: (len(item["alertas"]), dec(item["valor_stock_delta"])), reverse=True)
        return {
            "periodo_actual": {"fecha_desde": start.isoformat(), "fecha_hasta": end.isoformat()},
            "periodo_comparativo": {
                "fecha_desde": compare_start.isoformat(),
                "fecha_hasta": compare_end.isoformat(),
                "inferido": not (args.get("comparar_fecha_desde") and args.get("comparar_fecha_hasta")),
            },
            "tipo_familia": current["tipo_familia"],
            "totales_actual": current["totales"],
            "totales_comparativo": previous["totales"],
            "resumen": {
                "articulos_actuales": len(current_map),
                "articulos_comparativos": len(previous_map),
                "stock_sube_ventas_bajan": len([item for item in items if "stock_sube_ventas_bajan" in item["alertas"]]),
                "stock_sube_margen_baja": len([item for item in items if "stock_sube_margen_baja" in item["alertas"]]),
                "stock_actual_sin_ventas": len([item for item in items if "stock_actual_sin_ventas" in item["alertas"]]),
            },
            "articulos": items[:detail_limit],
            "stock_sube_ventas_bajan": [item for item in items if "stock_sube_ventas_bajan" in item["alertas"]][:detail_limit],
            "stock_sube_margen_baja": [item for item in items if "stock_sube_margen_baja" in item["alertas"]][:detail_limit],
            "stock_actual_sin_ventas": [item for item in items if "stock_actual_sin_ventas" in item["alertas"]][:detail_limit],
            "warnings": current["warnings"] + [
                "La comparacion de stock usa la foto actual y movimientos del periodo; no sustituye a un historico diario de existencias."
            ],
        }

    @staticmethod
    def _customer_risk_score(current: dict[str, Any], previous: dict[str, Any], variation: dict[str, Any]) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        venta_delta = dec(variation.get("venta_neta_delta"))
        venta_pct = variation.get("venta_neta_variacion_pct")
        rent_delta = dec(variation.get("rentabilidad_pct_delta"))
        current_sales = dec(current.get("venta_neta"))
        previous_sales = dec(previous.get("venta_neta"))
        current_margin = dec(current.get("margen"))
        current_rent = dec(current.get("rentabilidad_pct"))

        if previous_sales > 0 and current_sales == 0:
            score += 45
            reasons.append("cliente_desaparece")
        elif venta_delta < 0:
            score += 20
            reasons.append("baja_ventas")
            if venta_pct is not None and abs(dec(venta_pct)) >= Decimal("30"):
                score += 10
                reasons.append("baja_ventas_fuerte")
        if current_margin < 0 or current_rent < 0:
            score += 25
            reasons.append("rentabilidad_negativa")
        if rent_delta < 0:
            score += 15
            reasons.append("empeora_rentabilidad")
        if current_sales > 0 and current_margin < dec(previous.get("margen")):
            score += 10
            reasons.append("compra_con_menos_margen")
        return min(score, 100), reasons or ["sin_alertas"]

    def customer_risk_analysis(self, args: dict[str, Any]) -> dict[str, Any]:
        start, end, compare_start, compare_end = self._sales_trend_periods(args)
        limit = max(1, min(int(args.get("limite_alertas", 50) or 50), 500))
        min_sales = dec(args.get("venta_minima", "0"))

        summary_args = dict(args)
        for key in (
            "comparar_fecha_desde", "comparar_fecha_hasta", "limite_alertas",
            "venta_minima", "ordenar_por", "sentido", "agrupar_por", "tipo_familia",
        ):
            summary_args.pop(key, None)
        summary_args["agrupar_por"] = "cliente"
        summary_args["ordenar_por"] = "venta_neta"
        summary_args["sentido"] = "desc"
        summary_args["limite"] = summary_args.get("limite", 5000)

        current_args = dict(summary_args)
        current_args["fecha_desde"] = start.isoformat()
        current_args["fecha_hasta"] = end.isoformat()
        previous_args = dict(summary_args)
        previous_args["fecha_desde"] = compare_start.isoformat()
        previous_args["fecha_hasta"] = compare_end.isoformat()

        current = self.sales_profit_summary(current_args)
        previous = self.sales_profit_summary(previous_args)
        current_map = {item["codigo"]: item for item in current["items"]}
        previous_map = {item["codigo"]: item for item in previous["items"]}

        zero = self._sales_empty_totals()
        risks: list[dict[str, Any]] = []
        total_sales = dec(current["totales"].get("venta_neta"))
        for code in sorted(set(current_map) | set(previous_map)):
            cur = current_map.get(code) or {"codigo": code, "nombre": previous_map.get(code, {}).get("nombre", code), **zero}
            prev = previous_map.get(code) or {"codigo": code, "nombre": current_map.get(code, {}).get("nombre", code), **zero}
            if max(dec(cur.get("venta_neta")), dec(prev.get("venta_neta"))) < min_sales:
                continue
            variation = self._sales_trend_variation(cur, prev)
            score, reasons = self._customer_risk_score(cur, prev, variation)
            share = dec(cur.get("venta_neta")) * Decimal("100") / total_sales if total_sales > 0 else Decimal("0")
            risks.append({
                "codigo": code,
                "nombre": cur.get("nombre") or prev.get("nombre") or code,
                "riesgo": score,
                "motivos": reasons,
                "participacion_ventas_pct": normalize(share),
                "actual": cur,
                "comparativo": prev,
                "variacion": variation,
            })

        risks.sort(key=lambda item: (int(item["riesgo"]), dec(item["actual"].get("venta_neta"))), reverse=True)
        sales_drop = [item for item in risks if "baja_ventas" in item["motivos"] or "cliente_desaparece" in item["motivos"]]
        disappeared = [item for item in risks if "cliente_desaparece" in item["motivos"]]
        negative_profit = [item for item in risks if "rentabilidad_negativa" in item["motivos"]]
        worse_profit = [item for item in risks if "empeora_rentabilidad" in item["motivos"]]
        concentration = sorted(
            [item for item in risks if dec(item["actual"].get("venta_neta")) > 0],
            key=lambda item: dec(item["actual"].get("venta_neta")),
            reverse=True,
        )

        cumulative = Decimal("0")
        concentration_items: list[dict[str, Any]] = []
        for item in concentration[:limit]:
            cumulative += dec(item["actual"].get("venta_neta"))
            concentration_items.append({
                **item,
                "participacion_acumulada_pct": normalize(cumulative * Decimal("100") / total_sales) if total_sales > 0 else "0",
            })

        return {
            "periodo_actual": {"fecha_desde": start.isoformat(), "fecha_hasta": end.isoformat()},
            "periodo_comparativo": {
                "fecha_desde": compare_start.isoformat(),
                "fecha_hasta": compare_end.isoformat(),
                "inferido": not (args.get("comparar_fecha_desde") and args.get("comparar_fecha_hasta")),
            },
            "moneda": current["moneda"],
            "venta_minima": normalize(min_sales),
            "totales_actual": current["totales"],
            "totales_comparativo": previous["totales"],
            "variacion_totales": self._sales_trend_variation(current["totales"], previous["totales"]),
            "resumen_clientes": {
                "clientes_analizados": len(risks),
                "clientes_en_riesgo": len([item for item in risks if int(item["riesgo"]) >= 50]),
                "clientes_bajan": len(sales_drop),
                "clientes_desaparecen": len(disappeared),
                "clientes_rentabilidad_negativa": len(negative_profit),
                "clientes_empeoran_rentabilidad": len(worse_profit),
            },
            "clientes_riesgo": risks[:limit],
            "clientes_bajan": sales_drop[:limit],
            "clientes_desaparecen": disappeared[:limit],
            "clientes_rentabilidad_negativa": negative_profit[:limit],
            "clientes_empeoran_rentabilidad": worse_profit[:limit],
            "concentracion_clientes": concentration_items,
            "warnings": current.get("warnings", []) + previous.get("warnings", []),
        }

    def business_dashboard_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        start, end, compare_start, compare_end = self._sales_trend_periods(args)
        family_type = self._sale_family_type(args.get("tipo_familia"))
        detail_limit = max(1, min(int(args.get("limite_alertas", 10) or 10), 100))

        base_args = dict(args)
        base_args["fecha_desde"] = start.isoformat()
        base_args["fecha_hasta"] = end.isoformat()
        base_args["comparar_fecha_desde"] = compare_start.isoformat()
        base_args["comparar_fecha_hasta"] = compare_end.isoformat()
        base_args["tipo_familia"] = family_type
        base_args["limite"] = base_args.get("limite", 3000)
        base_args["limite_alertas"] = detail_limit

        trends_args = dict(base_args)
        trends_args.pop("umbral_rentabilidad_baja", None)
        trends_args.pop("dias_cobertura_alta", None)
        trends_args.pop("dias_sin_vender_alerta", None)
        trends_args.pop("solo_con_stock", None)
        trends_args.pop("stock_minimo", None)
        trends_args.pop("venta_minima", None)
        trends_args.pop("limite_detalle", None)
        trends_args["agrupar_por"] = str(args.get("agrupar_por", "familia") or "familia").strip().lower()
        trends = self.business_trends(trends_args)
        alerts_args = dict(base_args)
        alerts_args.pop("umbral_variacion_pct", None)
        alerts_args.pop("dias_cobertura_alta", None)
        alerts_args.pop("dias_sin_vender_alerta", None)
        alerts_args.pop("solo_con_stock", None)
        alerts_args.pop("stock_minimo", None)
        alerts_args.pop("venta_minima", None)
        alerts_args.pop("limite_detalle", None)
        alerts_args.pop("comparar_fecha_desde", None)
        alerts_args.pop("comparar_fecha_hasta", None)
        alerts = self.sales_profit_alerts(alerts_args)
        customers_args = dict(base_args)
        customers_args.pop("tipo_familia", None)
        customers_args.pop("umbral_variacion_pct", None)
        customers_args.pop("umbral_rentabilidad_baja", None)
        customers_args.pop("dias_cobertura_alta", None)
        customers_args.pop("dias_sin_vender_alerta", None)
        customers_args.pop("solo_con_stock", None)
        customers_args.pop("stock_minimo", None)
        customers_args.pop("limite_detalle", None)
        customers = self.customer_risk_analysis(customers_args)
        stock_args = dict(base_args)
        stock_args["agrupar_por"] = trends_args["agrupar_por"]
        stock_args["limite_detalle"] = detail_limit
        stock_args.pop("umbral_variacion_pct", None)
        stock_args.pop("umbral_rentabilidad_baja", None)
        stock_args.pop("venta_minima", None)
        stock = self.stock_rotation_analysis(stock_args)

        insights: list[dict[str, Any]] = []
        total_var = trends["variacion_totales"]
        if dec(total_var.get("venta_neta_delta")) < 0:
            insights.append({
                "tipo": "ventas_bajan",
                "mensaje": "La venta neta baja frente al periodo comparativo.",
                "impacto": total_var.get("venta_neta_delta"),
            })
        if dec(total_var.get("rentabilidad_pct_delta")) < 0:
            insights.append({
                "tipo": "rentabilidad_baja",
                "mensaje": "La rentabilidad porcentual empeora frente al periodo comparativo.",
                "impacto": total_var.get("rentabilidad_pct_delta"),
            })
        if alerts["resumen_alertas"].get("lineas_negativas", 0):
            insights.append({
                "tipo": "lineas_negativas",
                "mensaje": "Hay lineas de venta con rentabilidad negativa.",
                "impacto": alerts["resumen_alertas"]["lineas_negativas"],
            })
        if customers["resumen_clientes"].get("clientes_en_riesgo", 0):
            insights.append({
                "tipo": "clientes_en_riesgo",
                "mensaje": "Hay clientes con deterioro relevante de venta o margen.",
                "impacto": customers["resumen_clientes"]["clientes_en_riesgo"],
            })
        stock_without_sales = len(stock.get("stock_sin_ventas", []))
        if stock_without_sales:
            insights.append({
                "tipo": "stock_sin_ventas",
                "mensaje": "Hay articulos con stock actual y sin ventas en el periodo.",
                "impacto": stock_without_sales,
            })

        warnings: list[str] = []
        for block in (trends, alerts, customers, stock):
            warnings.extend(block.get("warnings", []))
        warnings = list(dict.fromkeys(warnings))

        return {
            "periodo_actual": {"fecha_desde": start.isoformat(), "fecha_hasta": end.isoformat()},
            "periodo_comparativo": {
                "fecha_desde": compare_start.isoformat(),
                "fecha_hasta": compare_end.isoformat(),
                "inferido": not (args.get("comparar_fecha_desde") and args.get("comparar_fecha_hasta")),
            },
            "tipo_familia": family_type,
            "moneda": trends["moneda"],
            "kpis": {
                "ventas": {
                    "actual": trends["totales_actual"],
                    "comparativo": trends["totales_comparativo"],
                    "variacion": trends["variacion_totales"],
                },
                "rentabilidad": alerts["resumen_alertas"],
                "clientes": customers["resumen_clientes"],
                "stock": stock["totales"],
            },
            "insights": insights[:detail_limit],
            "ventas_bajan": trends["bajan"][:detail_limit],
            "ventas_suben": trends["suben"][:detail_limit],
            "rentabilidad_alertas": {
                "lineas_negativas": alerts["lineas_negativas"][:detail_limit],
                "articulos_negativos_agregados": alerts["articulos_negativos_agregados"][:detail_limit],
                "articulos_compensados": alerts["articulos_compensados"][:detail_limit],
            },
            "clientes_riesgo": customers["clientes_riesgo"][:detail_limit],
            "stock_alertas": {
                "stock_sin_ventas": stock["stock_sin_ventas"][:detail_limit],
                "sobrestock": stock["sobrestock"][:detail_limit],
                "compra_sin_salida": stock["compra_sin_salida"][:detail_limit],
            },
            "warnings": warnings,
        }

    @staticmethod
    def _dashboard_pick_args(args: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
        return {key: value for key, value in args.items() if key in allowed}

    @classmethod
    def _dashboard_sales_args(cls, args: dict[str, Any]) -> dict[str, Any]:
        return cls._dashboard_pick_args(args, {
            "fecha_desde", "fecha_hasta", "tipos_documento", "centro", "articulo_desde",
            "articulo_hasta", "proveedor_desde", "proveedor_hasta", "cliente_desde",
            "cliente_hasta", "subcliente_desde", "subcliente_hasta", "representante",
            "descripcion", "solo_en_oferta", "incluir_pedidos", "moneda", "limite",
            "agrupar_por", "tipo_familia", "ordenar_por", "sentido", "limite_grupos",
        })

    @classmethod
    def _dashboard_trend_args(cls, args: dict[str, Any]) -> dict[str, Any]:
        result = cls._dashboard_sales_args(args)
        for key in ("comparar_fecha_desde", "comparar_fecha_hasta", "umbral_variacion_pct", "limite_alertas"):
            if key in args:
                result[key] = args[key]
        return result

    @classmethod
    def _dashboard_stock_args(cls, args: dict[str, Any]) -> dict[str, Any]:
        result = cls._dashboard_sales_args(args)
        for key in (
            "dias_cobertura_alta", "dias_sin_vender_alerta", "solo_con_stock",
            "stock_minimo", "limite_detalle",
        ):
            if key in args:
                result[key] = args[key]
        return result

    @classmethod
    def _dashboard_customer_args(cls, args: dict[str, Any]) -> dict[str, Any]:
        result = cls._dashboard_trend_args(args)
        for key in ("venta_minima",):
            if key in args:
                result[key] = args[key]
        return result

    @classmethod
    def _dashboard_document_args(cls, args: dict[str, Any]) -> dict[str, Any]:
        return cls._dashboard_pick_args(args, {
            "fecha_desde", "fecha_hasta", "politica", "tipos_documento", "centro",
            "cliente_desde", "cliente_hasta", "subcliente_desde", "subcliente_hasta",
            "representante", "zona_desde", "zona_hasta", "situacion", "serie_desde",
            "serie_hasta", "numero_desde", "numero_hasta", "tipo_acumulado", "tarjeta",
            "moneda", "limite", "agrupar_por", "ordenar_por", "sentido", "limite_grupos",
        })

    def dashboard_time_series(self, args: dict[str, Any]) -> dict[str, Any]:
        series_args = self._dashboard_trend_args(args)
        group_by = str(series_args.get("agrupar_por", "mes") or "mes").strip().lower()
        if group_by not in {"mes", "dia_semana", "centro", "tipo_documento", "familia", "marca", "representante"}:
            raise FaroError("agrupar_por no soportado para series temporales.")
        series_args["agrupar_por"] = group_by
        series_args["ordenar_por"] = str(series_args.get("ordenar_por", "venta_neta") or "venta_neta")
        trends = self.business_trends(series_args)

        documents_args = self._dashboard_document_args(args)
        documents_args["agrupar_por"] = "mes" if group_by in {"mes", "dia_semana"} else group_by
        documents_args["ordenar_por"] = str(documents_args.get("ordenar_por_documentos", "total") or "total")
        documents_args.pop("ordenar_por_documentos", None)
        documents_args.pop("comparar_fecha_desde", None)
        documents_args.pop("comparar_fecha_hasta", None)
        documents = self.sales_document_summary(documents_args)

        return {
            "periodo_actual": trends["periodo_actual"],
            "periodo_comparativo": trends["periodo_comparativo"],
            "agrupar_por": group_by,
            "ventas": {
                "moneda": trends["moneda"],
                "actual": trends["totales_actual"],
                "comparativo": trends["totales_comparativo"],
                "variacion": trends["variacion_totales"],
                "suben": trends["suben"],
                "bajan": trends["bajan"],
                "aparecen": trends["aparecen"],
                "desaparecen": trends["desaparecen"],
            },
            "documentos": {
                "politica": documents["politica"],
                "moneda": documents["moneda"],
                "totales": documents["totales"],
                "items": documents["items"],
            },
            "warnings": list(dict.fromkeys(trends.get("warnings", []) + documents.get("avisos", []))),
        }

    def dashboard_alerts(self, args: dict[str, Any]) -> dict[str, Any]:
        detail_limit = max(1, min(int(args.get("limite_alertas", 20) or 20), 200))
        sales_args = self._dashboard_sales_args(args)
        sales_args["limite_alertas"] = detail_limit
        sales_alerts = self.sales_profit_alerts(sales_args)

        customer_args = self._dashboard_customer_args(args)
        customer_args["limite_alertas"] = detail_limit
        customer_args.pop("umbral_rentabilidad_baja", None)
        customers = self.customer_risk_analysis(customer_args)

        stock_args = self._dashboard_stock_args(args)
        stock_args["limite_detalle"] = detail_limit
        stock_args.pop("umbral_rentabilidad_baja", None)
        stock = self.stock_rotation_analysis(stock_args)

        items: list[dict[str, Any]] = []
        for key, severity in (
            ("lineas_negativas", "alta"),
            ("articulos_negativos_agregados", "alta"),
            ("articulos_compensados", "media"),
        ):
            for item in sales_alerts.get(key, [])[:detail_limit]:
                items.append({"origen": "rentabilidad", "tipo": key, "severidad": severity, "detalle": item})
        for item in customers.get("clientes_riesgo", [])[:detail_limit]:
            items.append({"origen": "clientes", "tipo": "cliente_riesgo", "severidad": "media", "detalle": item})
        for key, severity in (
            ("stock_sin_ventas", "alta"),
            ("sobrestock", "media"),
            ("compra_sin_salida", "media"),
        ):
            for item in stock.get(key, [])[:detail_limit]:
                items.append({"origen": "stock", "tipo": key, "severidad": severity, "detalle": item})

        warnings: list[str] = []
        for block in (sales_alerts, customers, stock):
            warnings.extend(block.get("warnings", []))
        return {
            "periodo": stock["periodo"],
            "resumen": {
                "rentabilidad": sales_alerts["resumen_alertas"],
                "clientes": customers["resumen_clientes"],
                "stock": {
                    "stock_sin_ventas": len(stock.get("stock_sin_ventas", [])),
                    "sobrestock": len(stock.get("sobrestock", [])),
                    "compra_sin_salida": len(stock.get("compra_sin_salida", [])),
                },
                "total_alertas_devuelto": len(items[:detail_limit]),
            },
            "items": items[:detail_limit],
            "warnings": list(dict.fromkeys(warnings)),
        }

    @staticmethod
    def _dashboard_action(
        area: str,
        kind: str,
        severity: str,
        priority: int,
        entity: dict[str, Any],
        evidence: dict[str, Any],
        suggested_action: str,
        sources: list[str],
    ) -> dict[str, Any]:
        return {
            "area": area,
            "tipo": kind,
            "severidad": severity,
            "prioridad": max(0, min(int(priority), 100)),
            "entidad": entity,
            "evidencia": evidence,
            "accion_sugerida": suggested_action,
            "origen": sources,
        }

    @staticmethod
    def _dashboard_action_priority(*values: Any, base: int = 40, factor: Decimal | int = 1) -> int:
        impact = max((abs(dec(value)) for value in values), default=Decimal("0"))
        return max(0, min(int(Decimal(base) + (impact * dec(factor))), 100))

    @staticmethod
    def _dashboard_actions_result(
        area: str,
        period: dict[str, Any] | None,
        actions: list[dict[str, Any]],
        args: dict[str, Any],
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        min_priority = max(0, min(int(args.get("prioridad_minima", 0) or 0), 100))
        limit = max(1, min(int(args.get("limite_acciones", args.get("limite_alertas", 20)) or 20), 200))
        filtered = [item for item in actions if int(item.get("prioridad", 0)) >= min_priority]
        filtered.sort(key=lambda item: (int(item.get("prioridad", 0)), str(item.get("tipo") or "")), reverse=True)
        return {
            "area": area,
            "periodo": period,
            "filtros": {"prioridad_minima": min_priority, "limite_acciones": limit},
            "resumen": {"acciones_detectadas": len(actions), "acciones_devuelve": len(filtered[:limit])},
            "acciones": filtered[:limit],
            "warnings": list(dict.fromkeys(warnings or [])),
        }

    def sales_recommended_actions(self, args: dict[str, Any]) -> dict[str, Any]:
        alerts = self.sales_profit_alerts(self._dashboard_sales_args(args))
        min_amount = dec(args.get("importe_minimo_accion", "0"))
        actions: list[dict[str, Any]] = []
        for item in alerts.get("lineas_negativas", []):
            if abs(dec(item.get("margen"))) < min_amount:
                continue
            article = item.get("articulo") or {}
            actions.append(self._dashboard_action(
                "ventas",
                "linea_margen_negativo",
                "alta",
                self._dashboard_action_priority(item.get("margen"), base=75, factor=Decimal("0.05")),
                {"articulo": article, "documento": item.get("documento"), "cliente": item.get("cliente")},
                {
                    "venta_neta": item.get("venta_neta"),
                    "coste": item.get("coste"),
                    "margen": item.get("margen"),
                    "rentabilidad_pct": item.get("rentabilidad_pct"),
                },
                "Revisar coste, precio o descuentos de esta linea antes de repetir la operacion.",
                ["venta_alertas_rentabilidad"],
            ))
        for item in alerts.get("articulos_negativos_agregados", []):
            if abs(dec(item.get("margen"))) < min_amount:
                continue
            actions.append(self._dashboard_action(
                "ventas",
                "articulo_margen_negativo",
                "alta",
                self._dashboard_action_priority(item.get("margen"), item.get("venta_neta"), base=70, factor=Decimal("0.03")),
                {"articulo": {"codigo": item.get("codigo"), "descripcion": item.get("nombre")}},
                {
                    "venta_neta": item.get("venta_neta"),
                    "margen": item.get("margen"),
                    "rentabilidad_pct": item.get("rentabilidad_pct"),
                    "lineas": item.get("lineas"),
                },
                "Revisar tarifa, coste aplicado y condiciones comerciales del articulo.",
                ["venta_alertas_rentabilidad"],
            ))
        return self._dashboard_actions_result(
            "ventas",
            (alerts.get("filtros") or {}).get("periodo") or None,
            actions,
            args,
            alerts.get("warnings", []),
        )

    def customers_recommended_actions(self, args: dict[str, Any]) -> dict[str, Any]:
        customers = self.customer_risk_analysis(self._dashboard_customer_args(args))
        actions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in customers.get("clientes_riesgo", []):
            code = str(item.get("codigo") or "")
            if code in seen:
                continue
            seen.add(code)
            reasons = item.get("motivos", [])
            if "cliente_desaparece" in reasons:
                kind = "cliente_desaparece"
                severity = "alta"
                suggested = "Contactar al cliente y revisar los articulos o familias que compraba en el periodo comparativo."
            elif "baja_ventas_fuerte" in reasons or "baja_ventas" in reasons:
                kind = "cliente_en_caida"
                severity = "media"
                suggested = "Programar seguimiento comercial y comparar ultimas compras con el periodo anterior."
            elif "rentabilidad_negativa" in reasons:
                kind = "cliente_rentabilidad_negativa"
                severity = "alta"
                suggested = "Revisar condiciones, descuentos y costes asociados al cliente."
            else:
                kind = "cliente_riesgo"
                severity = "media"
                suggested = "Revisar evolucion de venta y margen del cliente."
            actions.append(self._dashboard_action(
                "clientes",
                kind,
                severity,
                int(item.get("riesgo") or 0),
                {"cliente": {"codigo": code, "nombre": item.get("nombre")}},
                {
                    "motivos": reasons,
                    "venta_actual": (item.get("actual") or {}).get("venta_neta"),
                    "venta_comparativa": (item.get("comparativo") or {}).get("venta_neta"),
                    "margen_actual": (item.get("actual") or {}).get("margen"),
                    "variacion": item.get("variacion"),
                    "participacion_ventas_pct": item.get("participacion_ventas_pct"),
                },
                suggested,
                ["clientes_resumen"],
            ))
        return self._dashboard_actions_result(
            "clientes",
            customers.get("periodo_actual"),
            actions,
            args,
            customers.get("warnings", []),
        )

    def stock_recommended_actions(self, args: dict[str, Any]) -> dict[str, Any]:
        stock = self.stock_rotation_analysis(self._dashboard_stock_args(args))
        actions: list[dict[str, Any]] = []
        for key, kind, severity, suggested in (
            ("stock_sin_ventas", "stock_parado", "alta", "Preparar accion de liquidacion, promocion o devolucion si procede."),
            ("sobrestock", "sobrestock", "media", "Revisar reposicion y ajustar minimos/maximos del articulo."),
            ("compra_sin_salida", "compra_sin_salida", "media", "Revisar compra reciente sin salida y validar si responde a pedido pendiente o exceso de stock."),
        ):
            for item in stock.get(key, []):
                actions.append(self._dashboard_action(
                    "stock",
                    kind,
                    severity,
                    self._dashboard_action_priority(item.get("valor_stock"), base=65 if severity == "alta" else 55, factor=Decimal("0.02")),
                    {"articulo": item.get("articulo"), "proveedor": item.get("proveedor")},
                    {
                        "stock_actual": item.get("stock_actual"),
                        "valor_stock": item.get("valor_stock"),
                        "ventas_periodo": item.get("ventas_periodo"),
                        "compras_periodo": item.get("compras_periodo"),
                        "alertas": item.get("alertas"),
                    },
                    suggested,
                    ["stock_resumen"],
                ))
        return self._dashboard_actions_result(
            "stock",
            stock.get("periodo"),
            actions,
            args,
            stock.get("warnings", []),
        )

    def pending_recommended_actions(self, args: dict[str, Any]) -> dict[str, Any]:
        actions: list[dict[str, Any]] = []
        warnings: list[str] = []
        orders = self.pending_orders_dashboard_summary(args)
        warnings.extend(orders.get("warnings", []))
        for item in orders.get("items", []):
            pending = dec(item.get("pendiente") or item.get("total"))
            if pending <= 0:
                continue
            actions.append(self._dashboard_action(
                "pendientes",
                "pedido_o_presupuesto_pendiente",
                "media",
                self._dashboard_action_priority(pending, base=50, factor=Decimal("0.02")),
                {"grupo": {"codigo": item.get("codigo"), "nombre": item.get("nombre")}},
                {
                    "documentos": item.get("documentos"),
                    "total": item.get("total"),
                    "pendiente": item.get("pendiente"),
                    "cobrado": item.get("cobrado"),
                },
                "Revisar pedidos o presupuestos pendientes y priorizar los de mayor importe.",
                ["pedidos_resumen"],
            ))
        documents = self.pending_documents_dashboard_summary(args)
        warnings.extend(documents.get("avisos", documents.get("warnings", [])))
        for item in documents.get("items", []):
            pending = dec(item.get("pendiente") or item.get("total"))
            if pending <= 0:
                continue
            actions.append(self._dashboard_action(
                "pendientes",
                "documento_pendiente",
                "media",
                self._dashboard_action_priority(pending, base=55, factor=Decimal("0.02")),
                {"grupo": {"codigo": item.get("codigo"), "nombre": item.get("nombre")}},
                {
                    "documentos": item.get("documentos"),
                    "total": item.get("total"),
                    "pendiente": item.get("pendiente"),
                    "cobrado": item.get("cobrado"),
                },
                "Revisar albaranes, facturas o creditos pendientes y decidir facturacion/cobro.",
                ["documentos_pendientes_resumen"],
            ))
        return self._dashboard_actions_result(
            "pendientes",
            documents.get("periodo") or orders.get("periodo"),
            actions,
            args,
            warnings,
        )

    def treasury_recommended_actions(self, args: dict[str, Any]) -> dict[str, Any]:
        treasury = self.treasury_dashboard_summary(args)
        actions: list[dict[str, Any]] = []
        totals = treasury.get("totales") or {}
        closing_balance = totals.get("saldo_cierre")
        if closing_balance is not None and dec(closing_balance) != dec(totals.get("saldo")):
            actions.append(self._dashboard_action(
                "tesoreria",
                "cierre_caja_difiere_saldo_movimientos",
                "alta",
                self._dashboard_action_priority(dec(closing_balance) - dec(totals.get("saldo")), base=80, factor=Decimal("0.1")),
                {"caja": {"saldo_cierre": closing_balance}},
                {"saldo_movimientos": totals.get("saldo"), "saldo_cierre": closing_balance, "totales": totals},
                "Revisar el cierre de caja contra entradas y salidas del periodo.",
                ["tesoreria_resumen"],
            ))
        for item in treasury.get("operaciones", []):
            document = item.get("documento") or {}
            if item.get("tipo_operacion") in {"E", "S"} and int(document.get("numero_efecto") or 0) == 0:
                actions.append(self._dashboard_action(
                    "tesoreria",
                    "operacion_caja_sin_efecto",
                    "baja",
                    self._dashboard_action_priority(item.get("importe"), base=35, factor=Decimal("0.03")),
                    {
                        "caja": {"centro": item.get("centro"), "caja": item.get("caja"), "linea": item.get("linea")},
                        "cliente": item.get("cliente"),
                    },
                    {
                        "fecha": item.get("fecha"),
                        "tipo_operacion": item.get("tipo_operacion"),
                        "importe": item.get("importe"),
                        "forma_pago": item.get("forma_pago"),
                        "documento": document,
                    },
                    "Revisar si la operacion apunta a factura directa u otra operacion manual de caja.",
                    ["tesoreria_resumen"],
                ))
        return self._dashboard_actions_result(
            "tesoreria",
            treasury.get("periodo"),
            actions,
            args,
            treasury.get("warnings", []),
        )

    def dashboard_recommended_actions(self, args: dict[str, Any]) -> dict[str, Any]:
        requested = args.get("areas") or ["ventas", "clientes", "stock", "pendientes", "tesoreria"]
        if not isinstance(requested, list):
            raise FaroError("areas debe ser una lista.")
        allowed = {"ventas", "clientes", "stock", "pendientes", "tesoreria"}
        areas = [str(item).strip().lower() for item in requested]
        unknown = set(areas) - allowed
        if unknown:
            raise FaroError("Areas no soportadas: " + ", ".join(sorted(unknown)))
        area_methods = {
            "ventas": self.sales_recommended_actions,
            "clientes": self.customers_recommended_actions,
            "stock": self.stock_recommended_actions,
            "pendientes": self.pending_recommended_actions,
            "tesoreria": self.treasury_recommended_actions,
        }
        actions: list[dict[str, Any]] = []
        warnings: list[str] = []
        area_summaries: dict[str, Any] = {}
        for area in areas:
            result = area_methods[area](args)
            actions.extend(result.get("acciones", []))
            warnings.extend(result.get("warnings", []))
            area_summaries[area] = result.get("resumen", {})
        result = self._dashboard_actions_result(
            "dashboard",
            {"fecha_desde": args.get("fecha_desde"), "fecha_hasta": args.get("fecha_hasta")},
            actions,
            args,
            warnings,
        )
        result["areas"] = area_summaries
        return result

    def dashboard_filters(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = max(1, min(int(args.get("limite", 100) or 100), 500))
        include = args.get("incluir")
        if not include:
            include = ["marcas", "familias", "familias_web", "clientes", "proveedores", "tipos_documento"]
        if not isinstance(include, list):
            raise FaroError("incluir debe ser una lista.")
        requested = {str(item).strip().lower() for item in include}
        allowed = {"marcas", "familias", "familias_web", "clientes", "proveedores", "tipos_documento"}
        unknown = requested - allowed
        if unknown:
            raise FaroError("Filtros no soportados: " + ", ".join(sorted(unknown)))

        result: dict[str, Any] = {}
        if "marcas" in requested:
            result["marcas"] = self.list_brands()
        if "familias" in requested:
            result["familias"] = self.list_families(str(args.get("padre_familia", "")))
        if "familias_web" in requested:
            result["familias_web"] = self.list_web_families(str(args.get("padre_familia_web", "")))
        if "clientes" in requested:
            result["clientes"] = self.list_clients(None, None, "", "", "", None, limit)
        if "proveedores" in requested:
            result["proveedores"] = self.list_providers(None, "", "", "", "", "", "", "", limit)
        if "tipos_documento" in requested:
            result["tipos_documento"] = [
                {"codigo": "T", "nombre": "ticket"},
                {"codigo": "F", "nombre": "factura"},
                {"codigo": "A", "nombre": "albaran"},
                {"codigo": "C", "nombre": "credito"},
                {"codigo": "P", "nombre": "pedido"},
                {"codigo": "R", "nombre": "presupuesto"},
                {"codigo": "S", "nombre": "pedido_servido"},
            ]
        return result

    def sales_dashboard_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        summary_args = self._dashboard_sales_args(args)
        summary_args["agrupar_por"] = str(summary_args.get("agrupar_por", "familia") or "familia")
        summary_args["ordenar_por"] = str(summary_args.get("ordenar_por", "venta_neta") or "venta_neta")
        summary = self.sales_profit_summary(summary_args)

        document_args = self._dashboard_document_args(args)
        document_args["agrupar_por"] = str(document_args.get("agrupar_documentos_por", "cliente") or "cliente")
        document_args["ordenar_por"] = str(document_args.get("ordenar_documentos_por", "total") or "total")
        document_args.pop("agrupar_documentos_por", None)
        document_args.pop("ordenar_documentos_por", None)
        documents = self.sales_document_summary(document_args)

        return {
            "rentabilidad": summary,
            "documentos": documents,
            "warnings": list(dict.fromkeys(summary.get("warnings", []) + documents.get("avisos", []))),
        }

    def purchases_dashboard_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        rotation_args = self._dashboard_stock_args(args)
        rotation_args["agrupar_por"] = str(rotation_args.get("agrupar_por", "proveedor") or "proveedor")
        rotation = self.stock_rotation_analysis(rotation_args)
        groups = []
        for group in rotation.get("grupos", []):
            purchased = dec(group.get("unidades_compradas_periodo"))
            if purchased > 0:
                groups.append(group)
        groups.sort(key=lambda item: dec(item.get("unidades_compradas_periodo")), reverse=True)
        return {
            "periodo": rotation["periodo"],
            "agrupar_por": rotation["agrupar_por"],
            "tipo_familia": rotation.get("tipo_familia"),
            "totales": {
                "unidades_compradas_periodo": rotation["totales"].get("unidades_compradas_periodo", "0"),
                "articulos": rotation["totales"].get("articulos", 0),
            },
            "items": groups,
            "compra_sin_salida": rotation.get("compra_sin_salida", []),
            "warnings": rotation.get("warnings", []),
        }

    def stock_dashboard_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        rotation_args = self._dashboard_stock_args(args)
        rotation_args["agrupar_por"] = str(rotation_args.get("agrupar_por", "familia") or "familia")
        rotation = self.stock_rotation_analysis(rotation_args)
        return {
            "periodo": rotation["periodo"],
            "agrupar_por": rotation["agrupar_por"],
            "tipo_familia": rotation.get("tipo_familia"),
            "totales": rotation["totales"],
            "grupos": rotation["grupos"],
            "articulos_mayor_stock": rotation["articulos_mayor_stock"],
            "alertas": {
                "stock_sin_ventas": rotation["stock_sin_ventas"],
                "sobrestock": rotation["sobrestock"],
                "compra_sin_salida": rotation["compra_sin_salida"],
            },
            "warnings": rotation.get("warnings", []),
        }

    def customers_dashboard_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.customer_risk_analysis(self._dashboard_customer_args(args))

    def providers_dashboard_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        provider_args = self._dashboard_sales_args(args)
        provider_args["agrupar_por"] = "proveedor"
        provider_args["ordenar_por"] = str(provider_args.get("ordenar_por", "venta_neta") or "venta_neta")
        sales = self.sales_profit_summary(provider_args)
        purchases = self.purchases_dashboard_summary(args)
        return {
            "ventas_por_proveedor": sales,
            "compras_por_proveedor": purchases,
            "warnings": list(dict.fromkeys(sales.get("warnings", []) + purchases.get("warnings", []))),
        }

    def pending_orders_dashboard_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        document_args = self._dashboard_document_args(args)
        document_args["politica"] = "documentos"
        document_args["tipos_documento"] = document_args.get("tipos_documento", ["P", "R"])
        document_args["agrupar_por"] = str(document_args.get("agrupar_por", "tipo_documento") or "tipo_documento")
        document_args["ordenar_por"] = str(document_args.get("ordenar_por", "total") or "total")
        return self.sales_document_summary(document_args)

    def pending_documents_dashboard_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        document_args = self._dashboard_document_args(args)
        document_args["politica"] = "documentos"
        document_args["tipos_documento"] = document_args.get("tipos_documento", ["A", "F", "C"])
        document_args["agrupar_por"] = str(document_args.get("agrupar_por", "categoria") or "categoria")
        document_args["ordenar_por"] = str(document_args.get("ordenar_por", "pendiente") or "pendiente")
        document_args["sentido"] = str(document_args.get("sentido", "desc") or "desc")
        return self.sales_document_summary(document_args)

    def purchase_orders_pending_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        start = self._parse_optional_date(args.get("fecha_desde"))
        end = self._parse_optional_date(args.get("fecha_hasta"))
        if not start or not end:
            raise FaroError("fecha_desde y fecha_hasta son obligatorias.")
        if start > end:
            raise FaroError("fecha_desde no puede ser posterior a fecha_hasta.")
        limit = max(1, min(int(args.get("limite", 500) or 500), 5000))
        where = [
            "C.COC_NUMEMP=?",
            "C.COC_FECHA BETWEEN ? AND ?",
            "D.DOC_NUMEMP=C.COC_NUMEMP",
            "D.DOC_CENTRO=C.COC_CENTRO",
            "D.DOC_EJERCI=C.COC_EJERCI",
            "D.DOC_SERIE=C.COC_SERIE",
            "D.DOC_NUMDOC=C.COC_NUMDOC",
        ]
        params: list[Any] = [self.settings.empresa, start, end]
        if _center_filter_is_set(args.get("centro")):
            where.append("C.COC_CENTRO=?")
            params.append(int(args["centro"]))
        if args.get("proveedor_desde") not in (None, "", 0):
            where.append("C.COC_CODPRO>=?")
            params.append(int(args["proveedor_desde"]))
        if args.get("proveedor_hasta") not in (None, "", 0):
            where.append("C.COC_CODPRO<=?")
            params.append(int(args["proveedor_hasta"]))
        situacion = str(args.get("situacion", "P") or "P").strip().upper()
        if situacion:
            where.append("C.COC_SITUAC=?")
            params.append(situacion[:1])
        if bool(args.get("solo_pendiente", True)):
            where.append("D.DOC_SITUAC<>'C'")
            where.append("D.DOC_CANPEN<>0")

        rows = self.db.fetch_all(
            f"""
            SELECT C.COC_CENTRO, C.COC_EJERCI, C.COC_SERIE, C.COC_NUMDOC, C.COC_FECHA,
                   C.COC_CODPRO, C.COC_NOMPRO, C.COC_SITUAC, C.COC_IMPPEN,
                   D.DOC_NUMLIN, D.DOC_CODART, D.DOC_DESCRI, D.DOC_CANPEN, D.DOC_VALPEN,
                   D.DOC_SITUAC
            FROM CABORC C, DETORC D
            WHERE {" AND ".join(where)}
            ORDER BY C.COC_FECHA, C.COC_CENTRO, C.COC_EJERCI, C.COC_SERIE, C.COC_NUMDOC, D.DOC_NUMLIN
            """,
            tuple(params),
        )
        orders: dict[str, dict[str, Any]] = {}
        provider_totals: dict[str, dict[str, Any]] = {}
        total_units = Decimal("0")
        total_value = Decimal("0")
        for row in rows:
            key = "|".join(str(row.get(name) or "") for name in ("COC_CENTRO", "COC_EJERCI", "COC_SERIE", "COC_NUMDOC"))
            order = orders.setdefault(key, {
                "centro": int(row.get("COC_CENTRO") or 0),
                "ejercicio": int(row.get("COC_EJERCI") or 0),
                "serie": str(row.get("COC_SERIE") or "").strip(),
                "numero": int(row.get("COC_NUMDOC") or 0),
                "fecha": normalize(row.get("COC_FECHA")),
                "proveedor": {"codigo": int(row.get("COC_CODPRO") or 0), "nombre": clean_text_value(row.get("COC_NOMPRO"))},
                "situacion": clean_text_value(row.get("COC_SITUAC")),
                "importe_pendiente_cabecera": normalize(dec(row.get("COC_IMPPEN"))),
                "lineas": [],
                "unidades_pendientes": Decimal("0"),
                "valor_pendiente": Decimal("0"),
            })
            line_units = dec(row.get("DOC_CANPEN"))
            line_value = dec(row.get("DOC_VALPEN"))
            total_units += line_units
            total_value += line_value
            order["unidades_pendientes"] += line_units
            order["valor_pendiente"] += line_value
            order["lineas"].append({
                "linea": int(row.get("DOC_NUMLIN") or 0),
                "articulo": str(row.get("DOC_CODART") or "").strip(),
                "descripcion": clean_text_value(row.get("DOC_DESCRI")),
                "cantidad_pendiente": normalize(line_units),
                "valor_pendiente": normalize(line_value),
                "situacion": clean_text_value(row.get("DOC_SITUAC")),
            })
            provider_key = str(row.get("COC_CODPRO") or 0)
            provider = provider_totals.setdefault(provider_key, {
                "codigo": int(row.get("COC_CODPRO") or 0),
                "nombre": clean_text_value(row.get("COC_NOMPRO")),
                "pedidos": set(),
                "lineas": 0,
                "unidades_pendientes": Decimal("0"),
                "valor_pendiente": Decimal("0"),
            })
            provider["pedidos"].add(key)
            provider["lineas"] += 1
            provider["unidades_pendientes"] += line_units
            provider["valor_pendiente"] += line_value

        order_items = []
        for order in orders.values():
            order_items.append({
                **{k: v for k, v in order.items() if k not in {"unidades_pendientes", "valor_pendiente"}},
                "unidades_pendientes": normalize(order["unidades_pendientes"]),
                "valor_pendiente": normalize(order["valor_pendiente"]),
            })
        order_items.sort(key=lambda item: dec(item["valor_pendiente"]), reverse=True)
        provider_items = []
        for provider in provider_totals.values():
            provider_items.append({
                "codigo": provider["codigo"],
                "nombre": provider["nombre"],
                "pedidos": len(provider["pedidos"]),
                "lineas": provider["lineas"],
                "unidades_pendientes": normalize(provider["unidades_pendientes"]),
                "valor_pendiente": normalize(provider["valor_pendiente"]),
            })
        provider_items.sort(key=lambda item: dec(item["valor_pendiente"]), reverse=True)
        return {
            "periodo": {"fecha_desde": start.isoformat(), "fecha_hasta": end.isoformat()},
            "filtros": {"situacion": situacion, "solo_pendiente": bool(args.get("solo_pendiente", True))},
            "totales": {
                "pedidos": len(order_items),
                "lineas": len(rows),
                "unidades_pendientes": normalize(total_units),
                "valor_pendiente": normalize(total_value),
            },
            "proveedores": provider_items[:limit],
            "pedidos": order_items[:limit],
        }

    def purchase_items_pending_receipt_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = max(1, min(int(args.get("limite", 500) or 500), 5000))
        orders = self.purchase_orders_pending_summary({**args, "limite": max(limit, int(args.get("limite_pedidos", 5000) or 5000))})
        articles: dict[str, dict[str, Any]] = {}
        total_units = Decimal("0")
        total_value = Decimal("0")
        for order in orders.get("pedidos", []):
            order_ref = {
                "centro": order.get("centro"),
                "ejercicio": order.get("ejercicio"),
                "serie": order.get("serie"),
                "numero": order.get("numero"),
                "fecha": order.get("fecha"),
                "proveedor": order.get("proveedor"),
            }
            for line in order.get("lineas", []):
                code = str(line.get("articulo") or "").strip()
                if not code:
                    code = "__sin_articulo__"
                quantity = dec(line.get("cantidad_pendiente"))
                value = dec(line.get("valor_pendiente"))
                total_units += quantity
                total_value += value
                article = articles.setdefault(code, {
                    "articulo": None if code == "__sin_articulo__" else code,
                    "descripcion": clean_text_value(line.get("descripcion")),
                    "lineas": 0,
                    "cantidad_pendiente": Decimal("0"),
                    "valor_pendiente": Decimal("0"),
                    "proveedores": {},
                    "pedidos": [],
                    "primera_fecha_pedido": None,
                })
                if not article["descripcion"]:
                    article["descripcion"] = clean_text_value(line.get("descripcion"))
                article["lineas"] += 1
                article["cantidad_pendiente"] += quantity
                article["valor_pendiente"] += value
                if order_ref["fecha"] and (
                    article["primera_fecha_pedido"] is None or str(order_ref["fecha"]) < str(article["primera_fecha_pedido"])
                ):
                    article["primera_fecha_pedido"] = order_ref["fecha"]
                provider = order.get("proveedor") or {}
                provider_key = str(provider.get("codigo") or 0)
                provider_bucket = article["proveedores"].setdefault(provider_key, {
                    "codigo": int(provider.get("codigo") or 0),
                    "nombre": clean_text_value(provider.get("nombre")),
                    "pedidos": set(),
                    "cantidad_pendiente": Decimal("0"),
                    "valor_pendiente": Decimal("0"),
                })
                order_key = "|".join(str(order.get(name) or "") for name in ("centro", "ejercicio", "serie", "numero"))
                provider_bucket["pedidos"].add(order_key)
                provider_bucket["cantidad_pendiente"] += quantity
                provider_bucket["valor_pendiente"] += value
                article["pedidos"].append({
                    **order_ref,
                    "linea": line.get("linea"),
                    "cantidad_pendiente": normalize(quantity),
                    "valor_pendiente": normalize(value),
                    "situacion_linea": line.get("situacion"),
                })

        items = []
        for article in articles.values():
            providers = []
            for provider in article["proveedores"].values():
                providers.append({
                    "codigo": provider["codigo"],
                    "nombre": provider["nombre"],
                    "pedidos": len(provider["pedidos"]),
                    "cantidad_pendiente": normalize(provider["cantidad_pendiente"]),
                    "valor_pendiente": normalize(provider["valor_pendiente"]),
                })
            providers.sort(key=lambda item: dec(item["valor_pendiente"]), reverse=True)
            article_orders = sorted(article["pedidos"], key=lambda item: (str(item.get("fecha") or ""), dec(item.get("valor_pendiente"))), reverse=True)
            items.append({
                "articulo": article["articulo"],
                "descripcion": article["descripcion"],
                "lineas": article["lineas"],
                "cantidad_pendiente": normalize(article["cantidad_pendiente"]),
                "valor_pendiente": normalize(article["valor_pendiente"]),
                "primera_fecha_pedido": article["primera_fecha_pedido"],
                "proveedores": providers,
                "pedidos": article_orders,
            })
        items.sort(key=lambda item: dec(item["valor_pendiente"]), reverse=True)
        return {
            "periodo": orders.get("periodo"),
            "filtros": orders.get("filtros"),
            "totales": {
                "articulos": len(items),
                "lineas": sum(int(item["lineas"]) for item in items),
                "cantidad_pendiente": normalize(total_units),
                "valor_pendiente": normalize(total_value),
            },
            "articulos": items[:limit],
        }

    def _purchase_stock_term(self, codart: str, centro: int, include_customer_orders: bool = True) -> dict[str, Decimal]:
        stock_row = self.db.fetch_one(
            "SELECT ARTE_EXIST, ARTE_MINIMO, ARTE_MAXIMO FROM ARTICULE "
            "WHERE ARTE_NUMEMP=? AND ARTE_CENTRO=? AND ARTE_CODART=?",
            (self.settings.empresa, centro, codart),
        ) or {}
        shortages_row = self.db.fetch_one(
            "SELECT SUM(FAL_CANTID) AS FAL_CANTID FROM FALTAS "
            "WHERE FAL_NUMEMP=? AND FAL_CENTRO=? AND FAL_CODART=?",
            (self.settings.empresa, centro, codart),
        ) or {}
        customer_row: dict[str, Any] = {}
        if include_customer_orders:
            customer_row = self.db.fetch_one(
                "SELECT SUM(DMV_CANTID) AS DMV_CANTID FROM DETMOV "
                "WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPDOC=? AND DMV_CODART=?",
                (self.settings.empresa, centro, "P", codart),
            ) or {}
        supplier_row = self.db.fetch_one(
            "SELECT SUM(DOC_CANPEN) AS DOC_CANPEN FROM DETORC "
            "WHERE DOC_NUMEMP=? AND DOC_CENTRO=? AND DOC_CODART=? AND DOC_SITUAC=?",
            (self.settings.empresa, centro, codart, "A"),
        ) or {}
        exist = dec(stock_row.get("ARTE_EXIST"))
        shortages = dec(shortages_row.get("FAL_CANTID"))
        pending_supplier = dec(supplier_row.get("DOC_CANPEN"))
        pending_customer = dec(customer_row.get("DMV_CANTID"))
        return {
            "existencias": exist,
            "faltas": shortages,
            "pedidos_proveedor": pending_supplier,
            "pedidos_cliente": pending_customer,
            "stock_minimo": dec(stock_row.get("ARTE_MINIMO")),
            "stock_maximo": dec(stock_row.get("ARTE_MAXIMO")),
            "stock_a_termino": exist + pending_supplier + shortages - pending_customer,
        }

    @staticmethod
    def _purchase_round_package(quantity: Decimal, package_units: Decimal) -> Decimal:
        if quantity <= 0 or package_units <= 0:
            return quantity
        return (quantity / package_units).to_integral_value(rounding=ROUND_UP) * package_units

    @staticmethod
    def _purchase_supplier_quantity(quantity: Decimal, row: dict[str, Any], adjust_package: bool = True) -> Decimal:
        result = quantity
        cancon = dec(row.get("ARTP_CANCON"), "1")
        canven = dec(row.get("ARTP_CANVEN"), "1")
        if canven > 0:
            result = result * cancon / canven
        if adjust_package and str(row.get("ARTP_AJUSTE") or "").strip().upper() == "S":
            result = FaroPhase1Service._purchase_round_package(result, dec(row.get("ARTP_UNIPAQ")))
        elif result == 0:
            result = Decimal("1")
        return result

    @staticmethod
    def _purchase_net_cost(row: dict[str, Any]) -> Decimal:
        value = dec(row.get("ARTP_PREBAS"))
        for index in range(1, 7):
            value *= Decimal("1") - dec(row.get(f"ARTP_DTOAUM{index}")) / Decimal("100")
        return value

    def _purchase_article_info(self, codart: str, code: str) -> str:
        if not codart:
            return ""
        row = self.db.fetch_one(
            "SELECT ARTI_DESCRI FROM ARTICULI "
            "WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_NUMLIN > 0 AND ARTI_CODINF=?",
            (self.settings.empresa, codart, code),
        )
        value = str(row.get("ARTI_DESCRI") or "").strip() if row else ""
        if code == "TIPRE":
            return {"N": "Normal", "O": "Oferta", "R": "Ruptura", "F": "Fechas"}.get(value, value)
        return value

    def _purchase_proposal_line(
        self,
        row: dict[str, Any],
        centro: int,
        source: str,
        requested: Decimal,
        term: dict[str, Decimal],
        reasons: list[str],
    ) -> dict[str, Any]:
        supplier_quantity = self._purchase_supplier_quantity(requested, row, True)
        net_cost = self._purchase_net_cost(row)
        value = supplier_quantity * net_cost
        provider_code = int(row.get("ARTP_CODPRO") or row.get("ART_CODPRO") or 0)
        codart = str(row.get("ART_CODART") or row.get("ARTP_CODART") or row.get("DMV_CODART") or "").strip()
        return {
            "origen": source,
            "centro": centro,
            "proveedor": {
                "codigo": provider_code,
                "nombre": clean_text_value(row.get("PRO_NOMCOR")) or self.provider_name(provider_code),
            },
            "articulo": codart,
            "referencia_proveedor": clean_text_value(row.get("ARTP_REFPRO")),
            "descripcion": clean_text_value(row.get("ART_DESCRI")) or clean_text_value(row.get("ARTP_DESCRI")) or clean_text_value(row.get("DMV_DESCRI")),
            "unidad_medida": str(row.get("ART_UNIMED") or row.get("ARTP_UNIMED") or "").strip(),
            "cantidad_sugerida": normalize(requested),
            "cantidad_compra": normalize(supplier_quantity),
            "precio_base": normalize(dec(row.get("ARTP_PREBAS"))),
            "precio_coste_neto": normalize(net_cost),
            "valor_estimado": normalize(value),
            "conversion": {
                "cantidad_compra": normalize(dec(row.get("ARTP_CANCON"), "1")),
                "cantidad_venta": normalize(dec(row.get("ARTP_CANVEN"), "1")),
                "unidades_paquete": normalize(dec(row.get("ARTP_UNIPAQ"))),
                "ajuste_paquete": str(row.get("ARTP_AJUSTE") or "").strip().upper() == "S",
            },
            "stock": {key: normalize(value) for key, value in term.items()},
            "motivos": reasons,
            "tipo_reaprovisionamiento": self._purchase_article_info(codart, "TIPRE"),
            "no_pedible": self._purchase_article_info(codart, "NOPED") == "N",
        }

    def purchase_stock_minimum_proposal(self, args: dict[str, Any]) -> dict[str, Any]:
        centro = int(args.get("centro", self.settings.centro) or self.settings.centro)
        limit = max(1, min(int(args.get("limite", 200) or 200), 1000))
        provider = args.get("proveedor")
        include_without_minimum = bool(args.get("incluir_sin_stock_minimo", False))
        only_positive = bool(args.get("solo_con_cantidad", True))
        use_maximum = bool(args.get("pedir_hasta_maximo", False))
        use_optimum = bool(args.get("pedido_optimo", False))
        use_package_units = bool(args.get("unidades_paquete", True))
        sql = (
            f"SELECT FIRST {limit * 5} A.ART_CODART, A.ART_DESCRI, A.ART_UNIMED, A.ART_CODPRO, "
            "A.ART_INDPROP, A.ART_FEBAJA, A.ART_OBSOL, A.ART_SECCIO, A.ART_CODFAM, A.ART_SUBFAM, "
            "AP.*, P.PRO_NOMCOR FROM ARTICUL A "
            "JOIN ARTICULP AP ON AP.ARTP_NUMEMP=A.ART_NUMEMP AND AP.ARTP_CODART=A.ART_CODART "
            "LEFT JOIN PROVEE P ON P.PRO_NUMEMP=A.ART_NUMEMP AND P.PRO_CODPRO=AP.ARTP_CODPRO "
            "WHERE A.ART_NUMEMP=?"
        )
        params: list[Any] = [self.settings.empresa]
        if provider not in (None, ""):
            sql += " AND AP.ARTP_CODPRO=?"
            params.append(int(provider))
            if bool(args.get("solo_proveedor_principal", False)):
                sql += " AND A.ART_CODPRO=?"
                params.append(int(provider))
        else:
            sql += " AND A.ART_CODPRO=AP.ARTP_CODPRO"
        if args.get("articulo_desde") and args.get("articulo_hasta"):
            sql += " AND A.ART_CODART BETWEEN ? AND ?"
            params.extend([str(args["articulo_desde"]), str(args["articulo_hasta"])])
        elif args.get("articulo"):
            sql += " AND A.ART_CODART=?"
            params.append(str(args["articulo"]))
        if args.get("seccion") not in (None, ""):
            sql += " AND A.ART_SECCIO=?"
            params.append(str(args["seccion"]))
        if args.get("familia") not in (None, ""):
            sql += " AND A.ART_CODFAM=?"
            params.append(int(args["familia"]))
        if args.get("subfamilia") not in (None, ""):
            sql += " AND A.ART_SUBFAM=?"
            params.append(int(args["subfamilia"]))
        if args.get("propio") not in (None, ""):
            sql += " AND A.ART_INDPROP=?"
            params.append(str(args["propio"]).strip().upper()[:1])
        if bool(args.get("solo_activos", True)):
            sql += " AND A.ART_FEBAJA IS NULL"
        if bool(args.get("excluir_obsoletos", False)):
            sql += " AND A.ART_OBSOL=?"
            params.append("N")
        sql += " ORDER BY " + ("A.ART_CODPRO, A.ART_CODART" if provider in (None, "") else "A.ART_CODART")
        items: list[dict[str, Any]] = []
        total_qty = Decimal("0")
        total_purchase_qty = Decimal("0")
        total_value = Decimal("0")
        for raw in self.db.fetch_all(sql, tuple(params)):
            row = normalize(raw)
            codart = str(row.get("ART_CODART") or "").strip()
            term = self._purchase_stock_term(codart, centro, True)
            cancon = dec(row.get("ARTP_CANCON"), "1")
            canven = dec(row.get("ARTP_CANVEN"), "1")
            if cancon != 0 and canven != 0:
                term["pedidos_proveedor"] = term["pedidos_proveedor"] * canven / cancon
            term["stock_a_termino"] = term["existencias"] + term["pedidos_proveedor"] + term["faltas"]
            minimum = term["stock_minimo"]
            maximum = term["stock_maximo"]
            if minimum <= 0 and not include_without_minimum:
                continue
            requested = Decimal("0")
            reasons: list[str] = []
            if minimum > term["stock_a_termino"]:
                requested = minimum - term["stock_a_termino"]
                reasons.append("stock_bajo_minimo")
                if use_maximum and maximum > 0:
                    requested = maximum - term["stock_a_termino"]
                    reasons.append("hasta_stock_maximo")
                if use_optimum and maximum > 0:
                    requested = maximum
                    reasons.append("pedido_optimo")
                if use_package_units:
                    package = dec(row.get("ARTP_UNIPAQ"))
                    if package > 0:
                        package_sales_units = package
                        if cancon != 0 and canven != 0:
                            package_sales_units = package * canven / cancon
                        requested = self._purchase_round_package(requested, package_sales_units)
                        reasons.append("redondeo_paquete")
            if requested <= 0 and only_positive:
                continue
            line = self._purchase_proposal_line(row, centro, "stock_minimo", requested, term, reasons)
            items.append(line)
            total_qty += requested
            total_purchase_qty += dec(line["cantidad_compra"])
            total_value += dec(line["valor_estimado"])
            if len(items) >= limit:
                break
        return {
            "origen": "GENPEDM",
            "centro": centro,
            "filtros": {
                "proveedor": int(provider) if provider not in (None, "") else None,
                "solo_con_cantidad": only_positive,
                "pedir_hasta_maximo": use_maximum,
                "pedido_optimo": use_optimum,
                "unidades_paquete": use_package_units,
            },
            "totales": {
                "lineas": len(items),
                "cantidad_sugerida": normalize(total_qty),
                "cantidad_compra": normalize(total_purchase_qty),
                "valor_estimado": normalize(total_value),
            },
            "lineas": items,
        }

    def purchase_customer_orders_proposal(self, args: dict[str, Any]) -> dict[str, Any]:
        centro = int(args.get("centro", self.settings.centro) or self.settings.centro)
        limit = max(1, min(int(args.get("limite", 200) or 200), 1000))
        provider_filter = args.get("proveedor")
        include_minimum = bool(args.get("incluir_stock_minimo", False))
        package_units = bool(args.get("unidades_paquete", True))
        start = self._parse_optional_date(args.get("fecha_desde"), None)
        end = self._parse_optional_date(args.get("fecha_hasta"), None)
        sql = (
            f"SELECT FIRST {limit * 5} C.CBV_CENTRO, C.CBV_EJERCI, C.CBV_SERIE, C.CBV_NUMDOC, C.CBV_FECHA, "
            "C.CBV_CODCLI, C.CBV_SUBCLI, C.CBV_NOMCLI, D.DMV_NUMLIN, D.DMV_TIPLIN, D.DMV_CODART, "
            "D.DMV_DESCRI, D.DMV_CANTID, A.ART_CODART, A.ART_DESCRI, A.ART_UNIMED, A.ART_CODPRO, A.ART_INDPROP, "
            "AP.*, P.PRO_NOMCOR FROM CABDOCV C "
            "JOIN DETMOV D ON D.DMV_NUMEMP=C.CBV_NUMEMP AND D.DMV_CENTRO=C.CBV_CENTRO "
            "AND D.DMV_TIPDOC=C.CBV_TIPDOC AND D.DMV_TIPAC=C.CBV_TIPAC AND D.DMV_EJERCI=C.CBV_EJERCI "
            "AND D.DMV_SERIE=C.CBV_SERIE AND D.DMV_NUMDOC=C.CBV_NUMDOC "
            "JOIN ARTICUL A ON A.ART_NUMEMP=D.DMV_NUMEMP AND A.ART_CODART=D.DMV_CODART "
            "JOIN ARTICULP AP ON AP.ARTP_NUMEMP=A.ART_NUMEMP AND AP.ARTP_CODART=A.ART_CODART "
            "AND AP.ARTP_CODPRO=A.ART_CODPRO "
            "LEFT JOIN PROVEE P ON P.PRO_NUMEMP=A.ART_NUMEMP AND P.PRO_CODPRO=AP.ARTP_CODPRO "
            "WHERE C.CBV_NUMEMP=? AND C.CBV_CENTRO=? AND C.CBV_TIPDOC=? AND D.DMV_TIPLIN=?"
        )
        params: list[Any] = [self.settings.empresa, centro, "P", "D"]
        if args.get("incluir_todos_documentos"):
            sql = sql.replace("C.CBV_TIPDOC=?", "C.CBV_TIPDOC IN ('F','T','C','A')")
            params.pop(2)
        if start and end:
            sql += " AND C.CBV_FECHA BETWEEN ? AND ? AND D.DMV_FECMOV BETWEEN ? AND ?"
            params.extend([start, end, start, end])
        if args.get("cliente") not in (None, ""):
            sql += " AND C.CBV_CODCLI=?"
            params.append(int(args["cliente"]))
        if args.get("articulo_desde") and args.get("articulo_hasta"):
            sql += " AND D.DMV_CODART BETWEEN ? AND ?"
            params.extend([str(args["articulo_desde"]), str(args["articulo_hasta"])])
        elif args.get("articulo"):
            sql += " AND D.DMV_CODART=?"
            params.append(str(args["articulo"]))
        sql += " ORDER BY AP.ARTP_CODPRO, D.DMV_CODART, C.CBV_FECHA"
        coinfer_provider = int(self.parameter("COINFE", "0") or 0)
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        total_qty = Decimal("0")
        total_purchase_qty = Decimal("0")
        total_value = Decimal("0")
        for raw in self.db.fetch_all(sql, tuple(params)):
            row = normalize(raw)
            codart = str(row.get("DMV_CODART") or row.get("ART_CODART") or "").strip()
            provider_code = int(row.get("ART_CODPRO") or row.get("ARTP_CODPRO") or 0)
            if str(row.get("ART_INDPROP") or "").strip().upper() == "N" and coinfer_provider:
                provider_code = coinfer_provider
                purchase_row = self.db.fetch_one(
                    "SELECT AP.*, P.PRO_NOMCOR FROM ARTICULP AP "
                    "LEFT JOIN PROVEE P ON P.PRO_NUMEMP=AP.ARTP_NUMEMP AND P.PRO_CODPRO=AP.ARTP_CODPRO "
                    "WHERE AP.ARTP_NUMEMP=? AND AP.ARTP_CODART=? AND AP.ARTP_CODPRO=?",
                    (self.settings.empresa, codart, provider_code),
                )
                if purchase_row:
                    row.update(normalize(purchase_row))
            if provider_filter not in (None, "") and int(provider_filter) != provider_code:
                continue
            if codart in seen:
                continue
            seen.add(codart)
            term = self._purchase_stock_term(codart, centro, True)
            cancon = dec(row.get("ARTP_CANCON"), "1")
            canven = dec(row.get("ARTP_CANVEN"), "1")
            if cancon != 0 and canven != 0:
                term["pedidos_proveedor"] = term["pedidos_proveedor"] * canven / cancon
            term["stock_a_termino"] = term["existencias"] + term["pedidos_proveedor"] + term["faltas"] - term["pedidos_cliente"]
            requested = Decimal("0")
            reasons: list[str] = []
            if term["stock_a_termino"] < 0:
                requested = -term["stock_a_termino"]
                reasons.append("pedido_cliente_sin_stock")
            if include_minimum and term["stock_minimo"] > 0 and term["stock_minimo"] > term["stock_a_termino"]:
                requested = -term["stock_a_termino"] + term["stock_minimo"]
                reasons.append("stock_minimo")
            if package_units and requested > 0:
                package = dec(row.get("ARTP_UNIPAQ"))
                if package > 0:
                    requested = self._purchase_round_package(requested, package)
                    reasons.append("redondeo_paquete")
            if requested <= 0:
                continue
            row["ARTP_CODPRO"] = provider_code
            line = self._purchase_proposal_line(row, centro, "pedidos_cliente", requested, term, reasons)
            line["pedido_origen"] = {
                "centro": int(row.get("CBV_CENTRO") or centro),
                "ejercicio": int(row.get("CBV_EJERCI") or 0),
                "serie": str(row.get("CBV_SERIE") or ""),
                "numero": int(row.get("CBV_NUMDOC") or 0),
                "fecha": normalize(row.get("CBV_FECHA")),
                "cliente": {
                    "codigo": int(row.get("CBV_CODCLI") or 0),
                    "subcliente": int(row.get("CBV_SUBCLI") or 0),
                    "nombre": clean_text_value(row.get("CBV_NOMCLI")),
                },
                "linea": int(row.get("DMV_NUMLIN") or 0),
            }
            items.append(line)
            total_qty += requested
            total_purchase_qty += dec(line["cantidad_compra"])
            total_value += dec(line["valor_estimado"])
            if len(items) >= limit:
                break
        return {
            "origen": "GENPEDC",
            "centro": centro,
            "filtros": {
                "proveedor": int(provider_filter) if provider_filter not in (None, "") else None,
                "incluir_stock_minimo": include_minimum,
                "unidades_paquete": package_units,
            },
            "totales": {
                "lineas": len(items),
                "cantidad_sugerida": normalize(total_qty),
                "cantidad_compra": normalize(total_purchase_qty),
                "valor_estimado": normalize(total_value),
            },
            "lineas": items,
        }

    def purchase_documents_pending_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        start = self._parse_optional_date(args.get("fecha_desde"))
        end = self._parse_optional_date(args.get("fecha_hasta"))
        if not start or not end:
            raise FaroError("fecha_desde y fecha_hasta son obligatorias.")
        if start > end:
            raise FaroError("fecha_desde no puede ser posterior a fecha_hasta.")
        limit = max(1, min(int(args.get("limite", 500) or 500), 5000))
        where = ["CBM_NUMEMP=?", "CBM_FECHA BETWEEN ? AND ?"]
        params: list[Any] = [self.settings.empresa, start, end]
        if _center_filter_is_set(args.get("centro")):
            where.append("CBM_CENTRO=?")
            params.append(int(args["centro"]))
        if args.get("proveedor_desde") not in (None, "", 0):
            where.append("CBM_CODPRO>=?")
            params.append(int(args["proveedor_desde"]))
        if args.get("proveedor_hasta") not in (None, "", 0):
            where.append("CBM_CODPRO<=?")
            params.append(int(args["proveedor_hasta"]))
        situacion = str(args.get("situacion", "") or "").strip().upper()
        if situacion:
            where.append("CBM_SITUAC=?")
            params.append(situacion[:1])
        elif bool(args.get("solo_pendiente", True)):
            where.append("CBM_SITUAC<>'C'")
        rows = self.db.fetch_all(
            f"""
            SELECT CBM_CENTRO, CBM_EJERCI, CBM_SERIE, CBM_NUMDOC, CBM_FECHA, CBM_FECREC,
                   CBM_CODPRO, CBM_NOMPRO, CBM_ALBPRO, CBM_FACPRO, CBM_FECFAC,
                   CBM_CODMON, CBM_TOTALD, CBM_TOTALS, CBM_SITUAC
            FROM CABDOCM
            WHERE {" AND ".join(where)}
            ORDER BY CBM_FECHA, CBM_CENTRO, CBM_EJERCI, CBM_SERIE, CBM_NUMDOC
            """,
            tuple(params),
        )
        documents = []
        by_status: dict[str, dict[str, Any]] = {}
        by_provider: dict[str, dict[str, Any]] = {}
        total_document = Decimal("0")
        total_base = Decimal("0")
        for row in rows:
            amount = dec(row.get("CBM_TOTALD"))
            base = dec(row.get("CBM_TOTALS"))
            total_document += amount
            total_base += base
            status = clean_text_value(row.get("CBM_SITUAC")) or "?"
            status_bucket = by_status.setdefault(status, {"situacion": status, "documentos": 0, "total": Decimal("0"), "base": Decimal("0")})
            status_bucket["documentos"] += 1
            status_bucket["total"] += amount
            status_bucket["base"] += base
            provider_key = str(row.get("CBM_CODPRO") or 0)
            provider = by_provider.setdefault(provider_key, {
                "codigo": int(row.get("CBM_CODPRO") or 0),
                "nombre": clean_text_value(row.get("CBM_NOMPRO")),
                "documentos": 0,
                "total": Decimal("0"),
                "base": Decimal("0"),
            })
            provider["documentos"] += 1
            provider["total"] += amount
            provider["base"] += base
            documents.append({
                "centro": int(row.get("CBM_CENTRO") or 0),
                "ejercicio": int(row.get("CBM_EJERCI") or 0),
                "serie": str(row.get("CBM_SERIE") or "").strip(),
                "numero": int(row.get("CBM_NUMDOC") or 0),
                "fecha": normalize(row.get("CBM_FECHA")),
                "fecha_recepcion": normalize(row.get("CBM_FECREC")),
                "proveedor": {"codigo": provider["codigo"], "nombre": provider["nombre"]},
                "albaran_proveedor": clean_text_value(row.get("CBM_ALBPRO")),
                "factura_proveedor": clean_text_value(row.get("CBM_FACPRO")),
                "fecha_factura": normalize(row.get("CBM_FECFAC")),
                "moneda": str(row.get("CBM_CODMON") or "").strip(),
                "base": normalize(base),
                "total": normalize(amount),
                "situacion": status,
            })
        documents.sort(key=lambda item: dec(item["total"]), reverse=True)
        status_items = [
            {"situacion": item["situacion"], "documentos": item["documentos"], "base": normalize(item["base"]), "total": normalize(item["total"])}
            for item in by_status.values()
        ]
        provider_items = [
            {"codigo": item["codigo"], "nombre": item["nombre"], "documentos": item["documentos"], "base": normalize(item["base"]), "total": normalize(item["total"])}
            for item in by_provider.values()
        ]
        provider_items.sort(key=lambda item: dec(item["total"]), reverse=True)
        return {
            "periodo": {"fecha_desde": start.isoformat(), "fecha_hasta": end.isoformat()},
            "filtros": {"situacion": situacion or None, "solo_pendiente": bool(args.get("solo_pendiente", True))},
            "totales": {"documentos": len(documents), "base": normalize(total_base), "total": normalize(total_document)},
            "situaciones": status_items,
            "proveedores": provider_items[:limit],
            "documentos": documents[:limit],
        }

    def treasury_dashboard_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        start = self._parse_optional_date(args.get("fecha_desde"))
        end = self._parse_optional_date(args.get("fecha_hasta"))
        if not start or not end:
            raise FaroError("fecha_desde y fecha_hasta son obligatorias.")
        if start > end:
            raise FaroError("fecha_desde no puede ser posterior a fecha_hasta.")
        limit = max(1, min(int(args.get("limite", 500) or 500), 5000))
        where = ["OPC_NUMEMP=?", "OPC_FECSIT BETWEEN ? AND ?"]
        params: list[Any] = [self.settings.empresa, start, end]
        if args.get("centro") not in (None, "", 0):
            where.append("OPC_CENTRO=?")
            params.append(int(args["centro"]))
        if args.get("caja") not in (None, "", 0):
            where.append("OPC_CAJA=?")
            params.append(int(args["caja"]))
        if str(args.get("tipo_operacion") or "").strip():
            where.append("OPC_TIPOPE=?")
            params.append(str(args["tipo_operacion"]).strip().upper()[:1])
        if str(args.get("forma_pago") or "").strip():
            where.append("OPC_FORPAG=?")
            params.append(str(args["forma_pago"]).strip())
        rows = self.db.fetch_all(
            f"""
            SELECT OPC_CENTRO, OPC_EJERCI, OPC_CAJA, OPC_NUMLIN, OPC_VENDED, OPC_HORA,
                   OPC_TIPOPE, OPC_IMPORT, OPC_CODMON, OPC_FORPAG, OPC_OBSERV,
                   OPC_TIPDOC, OPC_TIPAC, OPC_EJEDOC, OPC_SERIE, OPC_NUMDOC,
                   OPC_NUMORD, OPC_CODCLI, OPC_SUBCLI, OPC_SITUAC, OPC_FECSIT
            FROM OPECAJ
            WHERE {" AND ".join(where)}
            ORDER BY OPC_FECSIT, OPC_CENTRO, OPC_CAJA, OPC_NUMLIN
            """,
            tuple(params),
        )
        by_type: dict[str, dict[str, Any]] = {}
        by_method: dict[str, dict[str, Any]] = {}
        entries = Decimal("0")
        exits = Decimal("0")
        closings = Decimal("0")
        closing_balance: Decimal | None = None
        operations = []
        for row in rows:
            kind = clean_text_value(row.get("OPC_TIPOPE")) or "?"
            amount = dec(row.get("OPC_IMPORT"))
            if kind == "E":
                entries += amount
            elif kind == "S":
                exits += amount
            elif kind == "C":
                closings += amount
                closing_balance = amount
            type_bucket = by_type.setdefault(kind, {"tipo_operacion": kind, "operaciones": 0, "importe": Decimal("0")})
            type_bucket["operaciones"] += 1
            type_bucket["importe"] += amount
            method = clean_text_value(row.get("OPC_FORPAG")) or "?"
            method_bucket = by_method.setdefault(method, {"forma_pago": method, "operaciones": 0, "importe": Decimal("0")})
            method_bucket["operaciones"] += 1
            method_bucket["importe"] += amount
            operations.append({
                "centro": int(row.get("OPC_CENTRO") or 0),
                "ejercicio": int(row.get("OPC_EJERCI") or 0),
                "caja": int(row.get("OPC_CAJA") or 0),
                "linea": int(row.get("OPC_NUMLIN") or 0),
                "fecha": normalize(row.get("OPC_FECSIT")),
                "hora": normalize(row.get("OPC_HORA")),
                "vendedor": clean_text_value(row.get("OPC_VENDED")),
                "tipo_operacion": kind,
                "importe": normalize(amount),
                "moneda": str(row.get("OPC_CODMON") or "").strip(),
                "forma_pago": method,
                "observaciones": clean_text_value(row.get("OPC_OBSERV")),
                "documento": {
                    "tipo": clean_text_value(row.get("OPC_TIPDOC")),
                    "tipo_actividad": clean_text_value(row.get("OPC_TIPAC")),
                    "ejercicio": int(row.get("OPC_EJEDOC") or 0),
                    "serie": str(row.get("OPC_SERIE") or "").strip(),
                    "numero": int(row.get("OPC_NUMDOC") or 0),
                    "numero_efecto": int(row.get("OPC_NUMORD") or 0),
                },
                "cliente": {"codigo": int(row.get("OPC_CODCLI") or 0), "subcliente": int(row.get("OPC_SUBCLI") or 0)},
                "situacion": int(row.get("OPC_SITUAC") or 0),
            })
        operations.sort(key=lambda item: dec(item["importe"]), reverse=True)
        return {
            "periodo": {"fecha_desde": start.isoformat(), "fecha_hasta": end.isoformat()},
            "totales": {
                "operaciones": len(operations),
                "entradas": normalize(entries),
                "salidas": normalize(exits),
                "saldo": normalize(entries - exits),
                "cierres": normalize(closings),
                "saldo_cierre": normalize(closing_balance) if closing_balance is not None else None,
            },
            "por_tipo_operacion": [
                {"tipo_operacion": item["tipo_operacion"], "operaciones": item["operaciones"], "importe": normalize(item["importe"])}
                for item in by_type.values()
            ],
            "por_forma_pago": [
                {"forma_pago": item["forma_pago"], "operaciones": item["operaciones"], "importe": normalize(item["importe"])}
                for item in by_method.values()
            ],
            "operaciones": operations[:limit],
        }

    def _sale_document_doc_types(self, value: Any, policy: str) -> tuple[list[str], list[str]]:
        allowed = {"T", "A", "F", "C", "P", "R", "S"}
        warnings: list[str] = []
        if value in (None, "", []):
            raw_items = ["F", "C", "A"] if policy == "ventas_reales" else ["T", "A", "F", "C", "P", "R", "S"]
        elif isinstance(value, str):
            raw_items = [item.strip() for item in value.replace(";", ",").split(",")]
        else:
            raw_items = [str(item).strip() for item in value]

        result: list[str] = []
        for item in raw_items:
            code = item.upper()[:1]
            if not code:
                continue
            if code not in allowed:
                raise FaroError(f"Tipo de documento de venta no soportado: {item}")
            if policy == "ventas_reales" and code in {"T", "P", "R", "S"}:
                warnings.append(
                    f"{code} se omite en politica ventas_reales para evitar duplicados o documentos no realizados."
                )
                continue
            if code not in result:
                result.append(code)
        if not result:
            raise FaroError("No queda ningun tipo de documento valido para la politica solicitada.")
        return result, warnings

    def _sale_document_category(self, row: dict[str, Any]) -> str:
        tipdoc = str(row.get("CBV_TIPDOC") or "").strip().upper()[:1]
        codpag = int(row.get("CBV_CODPAG") or 0)
        contado = int(self.parameter("FPGCON", "0") or 0)
        if tipdoc == "F" and codpag == -1:
            return "factura_tickets"
        if tipdoc == "F" and codpag in (0, contado):
            return "factura_contado"
        if tipdoc == "F":
            return "factura"
        if tipdoc == "C":
            return "credito"
        if tipdoc == "A":
            return "albaran_pendiente" if str(row.get("CBV_SITUAC") or "").strip().upper() == "P" else "albaran"
        if tipdoc == "T":
            return "ticket"
        if tipdoc == "P":
            return "pedido"
        if tipdoc == "R":
            return "presupuesto"
        if tipdoc == "S":
            return "pedido_servido"
        return tipdoc

    @staticmethod
    def _sale_document_signed_factor(row: dict[str, Any]) -> Decimal:
        return Decimal("-1") if str(row.get("CBV_TIPDOC") or "").strip().upper()[:1] == "C" else Decimal("1")

    @staticmethod
    def _sale_document_base(row: dict[str, Any]) -> Decimal:
        discount_factor = Decimal("1") - dec(row.get("CBV_PORDTO")) / Decimal("100")
        total = Decimal("0")
        for idx in range(1, 5):
            base = dec(row.get(f"CBV_BASIMP{idx}"))
            if idx == 1:
                base += dec(row.get("CBV_IMPPOR"))
            total += base * discount_factor
        return total

    @staticmethod
    def _sale_document_taxes(row: dict[str, Any]) -> tuple[Decimal, Decimal]:
        discount_factor = Decimal("1") - dec(row.get("CBV_PORDTO")) / Decimal("100")
        iva = Decimal("0")
        recargo = Decimal("0")
        for idx in range(1, 5):
            base = dec(row.get(f"CBV_BASIMP{idx}"))
            if idx == 1:
                base += dec(row.get("CBV_IMPPOR"))
            base *= discount_factor
            iva += base * dec(row.get(f"CBV_PORIVA{idx}")) / Decimal("100")
            recargo += base * dec(row.get(f"CBV_PORREQ{idx}")) / Decimal("100")
        return iva, recargo

    @staticmethod
    def _sale_document_totals(items: list[dict[str, Any]]) -> dict[str, Any]:
        documentos = len(items)
        base = sum((dec(item.get("base_imponible")) for item in items), Decimal("0"))
        iva = sum((dec(item.get("iva")) for item in items), Decimal("0"))
        recargo = sum((dec(item.get("recargo")) for item in items), Decimal("0"))
        total = sum((dec(item.get("total")) for item in items), Decimal("0"))
        cobrado = sum((dec(item.get("cobrado")) for item in items), Decimal("0"))
        pendiente = sum((dec(item.get("pendiente")) for item in items), Decimal("0"))
        return {
            "documentos": documentos,
            "base_imponible": normalize(base),
            "iva": normalize(iva),
            "recargo": normalize(recargo),
            "total": normalize(total),
            "cobrado": normalize(cobrado),
            "pendiente": normalize(pendiente),
        }

    def sales_document_details(
        self,
        fecha_desde: Any,
        fecha_hasta: Any,
        politica: str = "ventas_reales",
        tipos_documento: Any = None,
        centro: Any = None,
        cliente_desde: Any = None,
        cliente_hasta: Any = None,
        subcliente_desde: Any = None,
        subcliente_hasta: Any = None,
        representante: Any = None,
        zona_desde: Any = None,
        zona_hasta: Any = None,
        situacion: str = "",
        serie_desde: str = "",
        serie_hasta: str = "",
        numero_desde: Any = None,
        numero_hasta: Any = None,
        tipo_acumulado: str = "0",
        tarjeta: str = "",
        moneda: str = "E",
        limite: Any = MAX_ROWS_DEFAULT,
    ) -> dict[str, Any]:
        start = self._parse_optional_date(fecha_desde)
        end = self._parse_optional_date(fecha_hasta)
        if not start or not end:
            raise FaroError("fecha_desde y fecha_hasta son obligatorias.")
        if start > end:
            raise FaroError("fecha_desde no puede ser posterior a fecha_hasta.")
        policy = str(politica or "ventas_reales").strip().lower()
        if policy not in {"ventas_reales", "documentos"}:
            raise FaroError("politica debe ser ventas_reales o documentos.")
        doc_types, warnings = self._sale_document_doc_types(tipos_documento, policy)
        target_currency = str(moneda or "E").strip().upper()[:1] or "E"
        limit = max(1, min(int(limite or MAX_ROWS_DEFAULT), 10000))

        where = [
            "C.CBV_NUMEMP=?",
            "C.CBV_FECHA BETWEEN ? AND ?",
            "C.CBV_TIPDOC IN (" + ",".join("?" for _ in doc_types) + ")",
            "C.CBV_CODMON=?",
        ]
        params: list[Any] = [self.settings.empresa, start, end, *doc_types, target_currency]
        if policy == "ventas_reales":
            where.append(
                "(C.CBV_TIPDOC IN ('F','C') OR (C.CBV_TIPDOC='A' AND C.CBV_SITUAC='P' "
                "AND NOT EXISTS (SELECT 1 FROM DETMOV D WHERE D.DMV_NUMEMP=C.CBV_NUMEMP "
                "AND D.DMV_TIPDOC='F' AND D.DMV_TIPDOCO='A' "
                "AND D.DMV_EJERCIO=C.CBV_EJERCI AND D.DMV_SERIEO=C.CBV_SERIE "
                "AND D.DMV_NUMDOCO=C.CBV_NUMDOC AND D.DMV_CAJA=C.CBV_CENTRO)))"
            )
        if _center_filter_is_set(centro):
            where.append("C.CBV_CENTRO=?")
            params.append(int(centro))
        if cliente_desde not in (None, "", 0):
            where.append("C.CBV_CODCLI>=?")
            params.append(int(cliente_desde))
        if cliente_hasta not in (None, "", 0):
            where.append("C.CBV_CODCLI<=?")
            params.append(int(cliente_hasta))
        if subcliente_desde not in (None, "", 0):
            where.append("C.CBV_SUBCLI>=?")
            params.append(int(subcliente_desde))
        if subcliente_hasta not in (None, "", 0):
            where.append("C.CBV_SUBCLI<=?")
            params.append(int(subcliente_hasta))
        if representante not in (None, "", 0):
            where.append("C.CBV_CODREP=?")
            params.append(int(representante))
        if zona_desde not in (None, "", 0):
            where.append("L.CLI_ZONA>=?")
            params.append(int(zona_desde))
        if zona_hasta not in (None, "", 0):
            where.append("L.CLI_ZONA<=?")
            params.append(int(zona_hasta))
        if situacion:
            where.append("C.CBV_SITUAC=?")
            params.append(str(situacion).strip().upper()[:1])
        if serie_desde and serie_hasta:
            where.append("C.CBV_SERIE BETWEEN ? AND ?")
            params.extend([str(serie_desde).strip(), str(serie_hasta).strip()])
        if numero_desde not in (None, "", 0) and numero_hasta not in (None, "", 0):
            where.append("C.CBV_NUMDOC BETWEEN ? AND ?")
            params.extend([int(numero_desde), int(numero_hasta)])
        if str(tipo_acumulado or "0") != "9":
            where.append("C.CBV_TIPAC=?")
            params.append(str(tipo_acumulado or "0").strip()[:1])
        if tarjeta:
            where.append("C.CBV_CODTAR=?")
            params.append(str(tarjeta).strip())

        rows = self.db.fetch_all(
            f"""
            SELECT FIRST {limit}
                C.CBV_CENTRO, C.CBV_TIPDOC, C.CBV_TIPAC, C.CBV_EJERCI, C.CBV_SERIE,
                C.CBV_NUMDOC, C.CBV_CAJA, C.CBV_FECHA, C.CBV_FECHAE, C.CBV_CODCLI,
                C.CBV_SUBCLI, C.CBV_NOMCLI, C.CBV_POBLAC, C.CBV_CODMON, C.CBV_CODPAG,
                C.CBV_FORCOB, C.CBV_CODREP, C.CBV_CODTAR, C.CBV_SITUAC,
                C.CBV_REFCLI, C.CBV_RETIRA, C.CBV_USUMOD, C.CBV_OBSERV, C.CBV_CIF,
                C.CBV_EJERCID, C.CBV_TIPDOCD, C.CBV_SERIED, C.CBV_NUMDOCD,
                C.CBV_FECMOD,
                C.CBV_TOTALD, C.CBV_IMPCOB, C.CBV_IMPPOR, C.CBV_PORDTO,
                C.CBV_BASIMP1, C.CBV_BASIMP2, C.CBV_BASIMP3, C.CBV_BASIMP4,
                C.CBV_PORIVA1, C.CBV_PORIVA2, C.CBV_PORIVA3, C.CBV_PORIVA4,
                C.CBV_PORREQ1, C.CBV_PORREQ2, C.CBV_PORREQ3, C.CBV_PORREQ4,
                L.CLI_NOMCLI, L.CLI_TIPFAC, L.CLI_ZONA, Z.ZON_DESCRI
            FROM CABDOCV C
            LEFT JOIN CLIEN L ON L.CLI_NUMEMP=C.CBV_NUMEMP
                AND L.CLI_CODCLI=C.CBV_CODCLI AND L.CLI_SUBCLI=C.CBV_SUBCLI
            LEFT JOIN ZONAS Z ON Z.ZON_NUMEMP=C.CBV_NUMEMP AND Z.ZON_CODIGO=L.CLI_ZONA
            WHERE {" AND ".join(where)}
            ORDER BY C.CBV_FECHA, C.CBV_CENTRO, C.CBV_TIPDOC, C.CBV_EJERCI, C.CBV_SERIE, C.CBV_NUMDOC
            """,
            tuple(params),
        )

        items: list[dict[str, Any]] = []
        for row in rows:
            doc_date = self._parse_optional_date(row.get("CBV_FECHA"), start) or start
            modified = row.get("CBV_FECMOD")
            if isinstance(modified, datetime):
                hour = modified.hour
            elif isinstance(modified, date):
                hour = 0
            else:
                try:
                    hour = datetime.fromisoformat(str(modified)[:19]).hour if modified else 0
                except ValueError:
                    hour = 0
            factor = self._sale_document_signed_factor(row)
            base = self._sale_document_base(row) * factor
            iva, recargo = self._sale_document_taxes(row)
            iva *= factor
            recargo *= factor
            total = dec(row.get("CBV_TOTALD")) * factor
            cobrado = dec(row.get("CBV_IMPCOB")) * factor
            category = self._sale_document_category(row)
            item = {
                "documento": {
                    "centro": int(row.get("CBV_CENTRO") or 0),
                    "tipo": str(row.get("CBV_TIPDOC") or "").strip(),
                    "tipo_nombre": self._sale_doc_name(row.get("CBV_TIPDOC")),
                    "tipo_acumulado": str(row.get("CBV_TIPAC") or "").strip(),
                    "ejercicio": int(row.get("CBV_EJERCI") or 0),
                    "serie": str(row.get("CBV_SERIE") or "").strip(),
                    "numero": int(row.get("CBV_NUMDOC") or 0),
                    "caja": int(row.get("CBV_CAJA") or 0),
                    "fecha": doc_date.isoformat(),
                },
                "origen": {
                    "tipo": str(row.get("CBV_TIPDOCD") or "").strip(),
                    "ejercicio": int(row.get("CBV_EJERCID") or 0),
                    "serie": str(row.get("CBV_SERIED") or "").strip(),
                    "numero": int(row.get("CBV_NUMDOCD") or 0),
                },
                "cliente": {
                    "codigo": int(row.get("CBV_CODCLI") or 0),
                    "subcliente": int(row.get("CBV_SUBCLI") or 0),
                    "nombre": clean_text_value(row.get("CBV_NOMCLI")),
                    "nombre_comercial": clean_text_value(row.get("CLI_NOMCLI")),
                    "cif": clean_text_value(row.get("CBV_CIF")),
                    "poblacion": clean_text_value(row.get("CBV_POBLAC")),
                    "tipo_facturacion": clean_text_value(row.get("CLI_TIPFAC")),
                    "zona": int(row.get("CLI_ZONA") or 0),
                    "zona_nombre": clean_text_value(row.get("ZON_DESCRI")),
                },
                "categoria": category,
                "representante": int(row.get("CBV_CODREP") or 0),
                "situacion": str(row.get("CBV_SITUAC") or "").strip(),
                "tarifa": str(row.get("CBV_CODTAR") or "").strip(),
                "forma_pago": int(row.get("CBV_CODPAG") or 0),
                "forma_cobro": {
                    "codigo": str(row.get("CBV_FORCOB") or "").strip(),
                    "nombre": self._sale_payment_name(row.get("CBV_FORCOB")),
                },
                "base_imponible": normalize(base),
                "iva": normalize(iva),
                "recargo": normalize(recargo),
                "total": normalize(total),
                "cobrado": normalize(cobrado),
                "pendiente": normalize(total - cobrado),
                "moneda": str(row.get("CBV_CODMON") or target_currency).strip(),
                "mes": doc_date.strftime("%Y-%m"),
                "trimestre": (doc_date.month - 1) // 3 + 1,
                "dia_semana": self._sale_weekday_name(doc_date),
                "hora": hour,
                "referencia_cliente": clean_text_value(row.get("CBV_REFCLI")),
                "retira": clean_text_value(row.get("CBV_RETIRA")),
                "usuario_modificacion": clean_text_value(row.get("CBV_USUMOD")),
                "observaciones": clean_text_value(row.get("CBV_OBSERV")),
                "apto_ventas_reales": category in {"factura", "factura_contado", "factura_tickets", "credito", "albaran_pendiente"},
            }
            items.append(item)

        return {
            "count": len(items),
            "limite": limit,
            "politica": policy,
            "moneda": target_currency,
            "avisos": sorted(set(warnings)),
            "filtros": {
                "fecha_desde": start.isoformat(),
                "fecha_hasta": end.isoformat(),
                "tipos_documento": doc_types,
                "centro": int(centro) if _center_filter_is_set(centro) else None,
            },
            "regla_antiduplicado": (
                "ventas_reales cuenta facturas y creditos, y solo albaranes pendientes no enlazados a factura; "
                "excluye tickets, pedidos, presupuestos y pedidos servidos."
            ),
            "totales": self._sale_document_totals(items),
            "items": items,
        }

    @staticmethod
    def _sale_document_customer_group_key(client: dict[str, Any]) -> tuple[str, str]:
        code = int(client.get("codigo") or 0)
        subcode = int(client.get("subcliente") or 0)
        name = str(client.get("nombre") or "").strip()
        if code == 99999:
            return f"{code}/{subcode}", name or f"{code}/{subcode}"
        return str(code), name or str(code)

    @staticmethod
    def _sale_document_group_key(item: dict[str, Any], group_by: str) -> tuple[str, str]:
        if group_by == "cliente":
            return FaroPhase1Service._sale_document_customer_group_key(item["cliente"])
        if group_by == "ejercicio":
            value = item["documento"]["ejercicio"]
            return str(value), str(value)
        if group_by == "tipo_documento":
            doc = item["documento"]
            return doc["tipo"], doc["tipo_nombre"]
        if group_by == "categoria":
            value = item["categoria"]
            return value, value
        if group_by == "centro":
            value = item["documento"]["centro"]
            return str(value), str(value)
        if group_by == "mes":
            value = item["mes"]
            return value, value
        if group_by == "trimestre":
            value = f"{item['documento']['fecha'][:4]}-T{item['trimestre']}"
            return value, value
        if group_by == "dia_semana":
            value = item["dia_semana"]
            return value, value
        if group_by == "hora":
            value = item["hora"]
            return str(value), f"{int(value):02d}:00"
        if group_by == "zona_cliente":
            client = item["cliente"]
            code = str(client["zona"])
            return code, client["zona_nombre"] or code
        if group_by == "representante":
            value = item["representante"]
            return str(value), str(value)
        if group_by == "forma_pago":
            value = item["forma_pago"]
            return str(value), str(value)
        if group_by == "situacion":
            value = item["situacion"]
            return value, value
        if group_by == "moneda":
            value = item["moneda"]
            return value, value
        if group_by == "poblacion":
            value = item["cliente"]["poblacion"]
            return value, value
        if group_by == "tarifa":
            value = item["tarifa"]
            return value, value
        raise FaroError(f"Agrupacion no soportada: {group_by}")

    def sales_document_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        group_by = str(args.get("agrupar_por", "cliente") or "cliente").strip().lower()
        if group_by not in SALE_DOCUMENT_GROUP_FIELDS:
            raise FaroError(
                "agrupar_por debe ser uno de: " + ", ".join(sorted(SALE_DOCUMENT_GROUP_FIELDS))
            )
        order_by = str(args.get("ordenar_por", "total") or "total").strip().lower()
        if order_by not in {"base_imponible", "iva", "recargo", "total", "cobrado", "pendiente", "documentos"}:
            raise FaroError("ordenar_por no soportado.")
        reverse = str(args.get("sentido", "desc") or "desc").strip().lower() != "asc"

        detail_args = dict(args)
        for key in ("agrupar_por", "ordenar_por", "sentido", "limite_grupos"):
            detail_args.pop(key, None)
        group_limit = args.get("limite_grupos")
        detail_args["limite"] = detail_args.get("limite", 10000)
        details = self.sales_document_details(**detail_args)

        groups: dict[str, dict[str, Any]] = {}
        for item in details["items"]:
            code, name = self._sale_document_group_key(item, group_by)
            if code not in groups:
                groups[code] = {"codigo": code, "nombre": name, "items": []}
            groups[code]["items"].append(item)

        result_items: list[dict[str, Any]] = []
        for group in groups.values():
            totals = self._sale_document_totals(group["items"])
            result_items.append({"codigo": group["codigo"], "nombre": group["nombre"], **totals})

        def sort_value(item: dict[str, Any]) -> Decimal:
            if order_by == "documentos":
                return Decimal(item.get("documentos") or 0)
            return dec(item.get(order_by))

        result_items.sort(key=sort_value, reverse=reverse)
        if group_limit not in (None, "", 0):
            result_items = result_items[: max(1, int(group_limit))]

        return {
            "agrupar_por": group_by,
            "ordenar_por": order_by,
            "sentido": "desc" if reverse else "asc",
            "politica": details["politica"],
            "moneda": details["moneda"],
            "avisos": details["avisos"],
            "count": len(result_items),
            "base_documentos": details["count"],
            "totales": details["totales"],
            "items": result_items,
        }

    def sales_document_abc(self, args: dict[str, Any]) -> dict[str, Any]:
        summary_args = dict(args)
        summary_args["agrupar_por"] = summary_args.get("agrupar_por", "cliente")
        summary_args["ordenar_por"] = summary_args.get("ordenar_por", "total")
        summary_args["sentido"] = "desc"
        threshold_a = dec(summary_args.pop("umbral_a", "80"))
        threshold_b = dec(summary_args.pop("umbral_b", "95"))
        summary = self.sales_document_summary(summary_args)
        total = dec(summary["totales"].get("total"))
        cumulative = Decimal("0")
        items: list[dict[str, Any]] = []
        for item in summary["items"]:
            value = dec(item.get("total"))
            cumulative += value
            pct = cumulative * Decimal("100") / total if total > 0 else Decimal("0")
            if pct <= threshold_a:
                klass = "A"
            elif pct <= threshold_b:
                klass = "B"
            else:
                klass = "C"
            items.append({
                **item,
                "abc": klass,
                "porcentaje_acumulado": normalize(pct),
            })
        return {
            **summary,
            "umbral_a": normalize(threshold_a),
            "umbral_b": normalize(threshold_b),
            "items": items,
        }

    def parameter(self, code: str, default: str = "") -> str:
        row = self.db.fetch_one(
            "SELECT PAR_VALOR FROM PARAMETROS WHERE PAR_NUMEMP=? AND PAR_CODIGO=?",
            (self.settings.empresa, code),
        )
        return str(row["PAR_VALOR"]).strip() if row and row.get("PAR_VALOR") is not None else default

    def current_stock_decimal(self, codart: str, centro: int) -> Decimal:
        row = self.db.fetch_one(
            "SELECT ARTE_EXIST FROM ARTICULE WHERE ARTE_NUMEMP=? AND ARTE_CENTRO=? AND ARTE_CODART=?",
            (self.settings.empresa, centro, codart),
        )
        return dec(row.get("ARTE_EXIST")) if row else Decimal("0")

    def next_cab_docr_number(self, centro: int, ejerci: int, serie: str) -> int:
        row = self.db.fetch_one(
            "SELECT MAX(CBR_NUMDOC) AS NUMDOC FROM CABDOCR WHERE CBR_NUMEMP=? AND CBR_CENTRO=? AND CBR_EJERCI=? AND CBR_SERIE=?",
            (self.settings.empresa, centro, ejerci, serie),
        )
        return int(row.get("NUMDOC") or 0) + 1 if row else 1

    def next_cabdocm_number(self, centro: int, ejerci: int, serie: str) -> int:
        row = self.db.fetch_one(
            "SELECT MAX(CBM_NUMDOC) AS NUMDOC FROM CABDOCM WHERE CBM_NUMEMP=? AND CBM_CENTRO=? AND CBM_EJERCI=? AND CBM_SERIE=?",
            (self.settings.empresa, centro, ejerci, serie),
        )
        return int(row.get("NUMDOC") or 0) + 1 if row else 1

    def next_detmovm_line(self, centro: int, ejerci: int, serie: str, numdoc: int) -> int:
        row = self.db.fetch_one(
            "SELECT MAX(DMM_NUMLIN) AS NUMLIN FROM DETMOVM "
            "WHERE DMM_NUMEMP=? AND DMM_CENTRO=? AND DMM_EJERCI=? AND DMM_SERIE=? AND DMM_NUMDOC=?",
            (self.settings.empresa, centro, ejerci, serie, numdoc),
        )
        return int(row.get("NUMLIN") or 0) + 10 if row and row.get("NUMLIN") is not None else 10

    def next_detmovr_line(self, centro: int, ejerci: int, serie: str, numdoc: int) -> int:
        row = self.db.fetch_one(
            "SELECT MAX(DMR_NUMLIN) AS NUMLIN FROM DETMOVR "
            "WHERE DMR_NUMEMP=? AND DMR_CENTRO=? AND DMR_EJERCI=? AND DMR_SERIE=? AND DMR_NUMDOC=?",
            (self.settings.empresa, centro, ejerci, serie, numdoc),
        )
        return int(row.get("NUMLIN") or 0) + 1 if row else 1

    def article_description_and_unit(self, codart: str) -> dict[str, str]:
        row = self.db.fetch_one(
            "SELECT ART_DESCRI, ART_UNIMED FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        if not row:
            raise FaroError(f"Articulo no encontrado: {codart}")
        return {
            "descri": clean_text_value(row.get("ART_DESCRI")),
            "unimed": str(row.get("ART_UNIMED") or "").strip(),
        }

    @staticmethod
    def _parse_optional_date(value: Any, default: date | None = None) -> date | None:
        if value in (None, "", 0):
            return default
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(text[:10], fmt).date()
            except ValueError:
                pass
        raise FaroError(f"Fecha no valida: {value}")

    def _resolve_purchase_provider(self, cabecera: dict[str, Any]) -> dict[str, Any]:
        proveedor = cabecera.get("proveedor", 0)
        if proveedor not in (None, "", 0):
            row = self.db.fetch_one(
                "SELECT * FROM PROVEE WHERE PRO_NUMEMP=? AND PRO_CODPRO=?",
                (self.settings.empresa, int(proveedor)),
            )
        elif str(cabecera.get("cif") or "").strip() and str(cabecera.get("cif") or "").strip() != "-":
            row = self.db.fetch_one(
                "SELECT * FROM PROVEE WHERE PRO_NUMEMP=? AND PRO_CIF=?",
                (self.settings.empresa, str(cabecera.get("cif") or "").strip()),
            )
        else:
            row = None
        if not row:
            raise FaroError("Proveedor no encontrado para la entrada de almacen.")
        row = normalize(row)
        return {
            "codpro": int(row.get("PRO_CODPRO") or 0),
            "nompro": str(row.get("PRO_NOMCOR") or ""),
            "domici": str(row.get("PRO_DOMICI") or ""),
            "codpos": int(row.get("PRO_CODPOS") or 0),
            "poblac": str(row.get("PRO_POBLAC") or ""),
            "cif": str(row.get("PRO_CIF") or ""),
            "codpag": int(row.get("PRO_CODPAG") or 0),
        }

    def _purchase_entry_header(self, cabecera: dict[str, Any], provider: dict[str, Any]) -> dict[str, Any]:
        today = date.today()
        fecha = self._parse_optional_date(cabecera.get("fecha"), today) or today
        fecfac = self._parse_optional_date(cabecera.get("fecha_factura"), None)
        fecrec = self._parse_optional_date(cabecera.get("fecha_recepcion"), fecha) or fecha
        serie = str(cabecera.get("serie") or "").strip() or self.parameter("E", "")
        if not serie:
            raise FaroError("No existe parametro de serie para entradas: E")
        facpro = str(cabecera.get("factura") or "").strip()
        return {
            "CBM_NUMEMP": self.settings.empresa,
            "CBM_CENTRO": int(cabecera.get("centro", self.settings.centro)),
            "CBM_EJERCI": int(cabecera.get("ejercicio") or fecha.year),
            "CBM_SERIE": serie,
            "CBM_NUMDOC": int(cabecera.get("numero") or 0),
            "CBM_FECHA": fecha,
            "CBM_FECREC": fecrec,
            "CBM_CODPRO": provider["codpro"],
            "CBM_NOMPRO": provider["nompro"],
            "CBM_DOMICI": provider["domici"],
            "CBM_CODPOS": provider["codpos"],
            "CBM_POBLAC": provider["poblac"],
            "CBM_CIF": provider["cif"],
            "CBM_CODPAG": provider["codpag"],
            "CBM_ALBPRO": str(cabecera.get("albaran") or "").strip(),
            "CBM_FACPRO": facpro,
            "CBM_FECFAC": fecfac,
            "CBM_CODMON": str(cabecera.get("moneda") or "E").strip() or "E",
            "CBM_PORDTO": dec(cabecera.get("descuento", 0)),
            "CBM_IMPPOR": dec(cabecera.get("portes", 0)),
            "CBM_BASIMP1": dec(cabecera.get("base1", 0)),
            "CBM_PORIVA1": dec(cabecera.get("iva1", 21)),
            "CBM_PORREQ1": dec(cabecera.get("recargo1", 0)),
            "CBM_BASIMP2": dec(cabecera.get("base2", 0)),
            "CBM_PORIVA2": dec(cabecera.get("iva2", 0)),
            "CBM_PORREQ2": dec(cabecera.get("recargo2", 0)),
            "CBM_BASIMP3": dec(cabecera.get("base3", 0)),
            "CBM_PORIVA3": dec(cabecera.get("iva3", 0)),
            "CBM_PORREQ3": dec(cabecera.get("recargo3", 0)),
            "CBM_BASIMP4": dec(cabecera.get("base4", 0)),
            "CBM_PORIVA4": dec(cabecera.get("iva4", 0)),
            "CBM_PORREQ4": dec(cabecera.get("recargo4", 0)),
            "CBM_TOTALD": Decimal("0"),
            "CBM_TOTALS": Decimal("0"),
            "CBM_INDEDI": "N",
            "CBM_SITUAC": "F" if facpro else "P",
            "CBM_OBSERV": str(cabecera.get("observaciones") or ""),
            "CBM_FECMOD": datetime.now(),
            "CBM_USUMOD": self.settings.usuario,
        }

    def _insert_cabdocm_header(self, header: dict[str, Any]) -> dict[str, Any]:
        if int(header.get("CBM_NUMDOC") or 0) == 0:
            header["CBM_NUMDOC"] = self.next_cabdocm_number(
                int(header["CBM_CENTRO"]), int(header["CBM_EJERCI"]), str(header["CBM_SERIE"])
            )
        while True:
            try:
                self.db.execute(
                    "INSERT INTO CABDOCM (CBM_NUMEMP, CBM_CENTRO, CBM_EJERCI, CBM_SERIE, CBM_NUMDOC, "
                    "CBM_FECHA, CBM_FECREC, CBM_CODPRO, CBM_NOMPRO, CBM_DOMICI, CBM_CODPOS, CBM_POBLAC, "
                    "CBM_CIF, CBM_CODPAG, CBM_ALBPRO, CBM_FACPRO, CBM_FECFAC, CBM_CODMON, CBM_PORDTO, "
                    "CBM_IMPPOR, CBM_BASIMP1, CBM_PORIVA1, CBM_PORREQ1, CBM_BASIMP2, CBM_PORIVA2, "
                    "CBM_PORREQ2, CBM_BASIMP3, CBM_PORIVA3, CBM_PORREQ3, CBM_BASIMP4, CBM_PORIVA4, "
                    "CBM_PORREQ4, CBM_TOTALD, CBM_TOTALS, CBM_INDEDI, CBM_SITUAC, CBM_OBSERV, CBM_FECMOD, CBM_USUMOD) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(header[key] for key in [
                        "CBM_NUMEMP", "CBM_CENTRO", "CBM_EJERCI", "CBM_SERIE", "CBM_NUMDOC",
                        "CBM_FECHA", "CBM_FECREC", "CBM_CODPRO", "CBM_NOMPRO", "CBM_DOMICI",
                        "CBM_CODPOS", "CBM_POBLAC", "CBM_CIF", "CBM_CODPAG", "CBM_ALBPRO",
                        "CBM_FACPRO", "CBM_FECFAC", "CBM_CODMON", "CBM_PORDTO", "CBM_IMPPOR",
                        "CBM_BASIMP1", "CBM_PORIVA1", "CBM_PORREQ1", "CBM_BASIMP2", "CBM_PORIVA2",
                        "CBM_PORREQ2", "CBM_BASIMP3", "CBM_PORIVA3", "CBM_PORREQ3", "CBM_BASIMP4",
                        "CBM_PORIVA4", "CBM_PORREQ4", "CBM_TOTALD", "CBM_TOTALS", "CBM_INDEDI",
                        "CBM_SITUAC", "CBM_OBSERV", "CBM_FECMOD", "CBM_USUMOD",
                    ]),
                )
                return header
            except Exception as exc:
                if not _is_duplicate_key_error(exc) or int(header["CBM_NUMDOC"]) >= 999999:
                    raise
                header["CBM_NUMDOC"] = int(header["CBM_NUMDOC"]) + 1

    def _supplier_article_for_entry(self, referencia: str, proveedor: int) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT * FROM ARTICULP WHERE ARTP_NUMEMP=? AND ARTP_REFPRO=? AND ARTP_CODPRO=?",
            (self.settings.empresa, referencia, proveedor),
        )
        return normalize(row) if row else None

    def _internal_article_for_entry(self, codart: str) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT ART_CODART, ART_DESCRI, ART_UNIMED FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        return normalize(row) if row else None

    def _pending_purchase_order_line(self, centro: int, proveedor: int, codart: str) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT DETORC.* FROM DETORC,CABORC WHERE DOC_NUMEMP=COC_NUMEMP AND DOC_EJERCI=COC_EJERCI "
            "AND DOC_SERIE=COC_SERIE AND DOC_NUMDOC=COC_NUMDOC AND COC_SITUAC=? AND COC_CODPRO=? "
            "AND DOC_NUMEMP=? AND DOC_CENTRO=? AND DOC_CODART=? AND DOC_SITUAC=? ORDER BY DOC_FECMOV",
            ("P", proveedor, self.settings.empresa, centro, codart, "A"),
        )
        return normalize(row) if row else None

    def _value_purchase_entry_line(self, line: dict[str, Any]) -> dict[str, Any]:
        value = (
            dec(line["DMM_PREBAS"])
            * (1 - dec(line["DMM_DTOAUM1"]) / 100)
            * (1 - dec(line["DMM_DTOAUM2"]) / 100)
            * (1 - dec(line["DMM_DTOAUM3"]) / 100)
            * (1 - dec(line["DMM_DTOAUM4"]) / 100)
            * (1 - dec(line["DMM_DTOAUM5"]) / 100)
            * (1 - dec(line["DMM_DTOAUM6"]) / 100)
            * dec(line["DMM_CANTIDP"])
        )
        line["DMM_VALLIN"] = FaroArticleService(self.db).round_price(value, str(line.get("DMM_CODMON") or "E"), "L")
        return line

    def _accumulate_detmovm_stock(self, line: dict[str, Any], operation: int = 1) -> None:
        codart = str(line.get("DMM_CODART") or "")
        if not codart:
            return
        article = self.db.fetch_one(
            "SELECT ART_INDINV FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        if article and str(article.get("ART_INDINV") or "").strip().upper() == "N":
            difference = Decimal("0")
        else:
            difference = dec(line.get("DMM_CANTID")) * Decimal(operation)
        now = datetime.now()
        feccom = line.get("DMM_FECMOV") or date.today()
        try:
            self.db.execute(
                "INSERT INTO ARTICULE (ARTE_NUMEMP, ARTE_CODART, ARTE_CENTRO, ARTE_EXIST, ARTE_MINIMO, ARTE_MAXIMO, "
                "ARTE_FECCOM, ARTE_FECVEN, ARTE_FECMOV) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.settings.empresa, codart, int(line["DMM_CENTRO"]), difference, 0, 0, feccom, None, now),
            )
            try:
                self.db.execute(
                    "INSERT INTO STOCKS (STO_NUMEMP, STO_CODART, STO_CENTRO, STO_FECHA, STO_EXIST) VALUES (?, ?, ?, ?, ?)",
                    (self.settings.empresa, codart, self.settings.centro, feccom, 0),
                )
            except Exception:
                pass
        except Exception:
            self.db.execute(
                "UPDATE ARTICULE SET ARTE_EXIST=ARTE_EXIST + ?, ARTE_FECCOM=?, ARTE_FECMOV=? "
                "WHERE ARTE_NUMEMP=? AND ARTE_CODART=? AND ARTE_CENTRO=?",
                (difference, feccom, now, self.settings.empresa, codart, int(line["DMM_CENTRO"])),
            )

    def _purchase_entry_line(self, header: dict[str, Any], raw_line: dict[str, Any], position: int) -> dict[str, Any]:
        referencia = str(raw_line.get("referencia_proveedor") or raw_line.get("articulo") or "").strip()
        if not referencia:
            raise FaroError(f"Falta articulo en lineas[{position}]")
        supplier_article = self._supplier_article_for_entry(referencia, int(header["CBM_CODPRO"]))
        internal_article = None
        if supplier_article:
            codart = str(supplier_article.get("ARTP_CODART") or "").strip()
            tiplin = "D"
            codarp = str(supplier_article.get("ARTP_REFPRO") or referencia).strip()
            unimed = str(raw_line.get("unidad_medida") or supplier_article.get("ARTP_UNIMED") or "").strip()
            fallback_price = dec(supplier_article.get("ARTP_PREBAS"))
            fallback_discounts = [dec(supplier_article.get(f"ARTP_DTOAUM{i}")) for i in range(1, 7)]
        else:
            internal_article = self._internal_article_for_entry(referencia)
            codart = referencia
            tiplin = "D" if internal_article else "X"
            codarp = ""
            unimed = str(
                raw_line.get("unidad_medida")
                or (internal_article or {}).get("ART_UNIMED")
                or "UNID"
            ).strip()
            fallback_price = Decimal("0")
            fallback_discounts = [Decimal("0")] * 6
        price = dec(raw_line.get("precio", fallback_price))
        discounts = [dec(raw_line.get(f"descuento{i}", fallback_discounts[i - 1])) for i in range(1, 7)]
        if price == 0 and supplier_article:
            price = fallback_price
            discounts = fallback_discounts
        quantity = dec(raw_line.get("cantidad", 0))
        order = self._pending_purchase_order_line(int(header["CBM_CENTRO"]), int(header["CBM_CODPRO"]), codart) if tiplin == "D" else None
        line = {
            "DMM_NUMEMP": self.settings.empresa,
            "DMM_CENTRO": int(header["CBM_CENTRO"]),
            "DMM_EJERCI": int(header["CBM_EJERCI"]),
            "DMM_SERIE": str(header["CBM_SERIE"]),
            "DMM_NUMDOC": int(header["CBM_NUMDOC"]),
            "DMM_NUMLIN": int(raw_line.get("linea") or 0),
            "DMM_FECMOV": header["CBM_FECHA"],
            "DMM_TIPLIN": tiplin,
            "DMM_CODART": codart,
            "DMM_CODARP": codarp,
            "DMM_DESCRI": str(raw_line.get("descripcion") or (internal_article or {}).get("ART_DESCRI") or "")[:100],
            "DMM_CANTIDP": quantity,
            "DMM_UNIMED": unimed,
            "DMM_CANTID": quantity,
            "DMM_PREBAS": price,
            "DMM_CODMON": str(raw_line.get("moneda") or header.get("CBM_CODMON") or "E"),
            "DMM_DTOAUM1": discounts[0],
            "DMM_DTOAUM2": discounts[1],
            "DMM_DTOAUM3": discounts[2],
            "DMM_DTOAUM4": discounts[3],
            "DMM_DTOAUM5": discounts[4],
            "DMM_DTOAUM6": discounts[5],
            "DMM_PORIVA": dec(raw_line.get("iva", 21)),
            "DMM_PORREQ": dec(raw_line.get("recargo", 0)),
            "DMM_VALLIN": Decimal("0"),
            "DMM_IMPDTO": Decimal("0"),
            "DMM_OBSERV": "",
            "DMM_EJERCIP": int(order.get("DOC_EJERCI") or 0) if order else 0,
            "DMM_SERIEP": str(order.get("DOC_SERIE") or "") if order else "",
            "DMM_NUMDOCP": int(order.get("DOC_NUMDOC") or 0) if order else 0,
            "DMM_NUMLINP": int(order.get("DOC_NUMLIN") or 0) if order else 0,
            "DMM_EJEOFE": 0,
            "DMM_NUMOFE": 0,
        }
        return self._value_purchase_entry_line(line)

    def _insert_detmovm_with_stock(self, line: dict[str, Any]) -> int:
        if int(line.get("DMM_NUMLIN") or 0) == 0:
            line["DMM_NUMLIN"] = self.next_detmovm_line(
                int(line["DMM_CENTRO"]), int(line["DMM_EJERCI"]), str(line["DMM_SERIE"]), int(line["DMM_NUMDOC"])
            )
        if line.get("DMM_TIPLIN") == "D":
            self._accumulate_detmovm_stock(line, 1)
        self.db.execute(
            "INSERT INTO DETMOVM (DMM_NUMEMP, DMM_CENTRO, DMM_EJERCI, DMM_SERIE, DMM_NUMDOC, DMM_NUMLIN, "
            "DMM_FECMOV, DMM_TIPLIN, DMM_CODART, DMM_CODARP, DMM_DESCRI, DMM_CANTIDP, DMM_UNIMED, DMM_CANTID, "
            "DMM_PREBAS, DMM_CODMON, DMM_DTOAUM1, DMM_DTOAUM2, DMM_DTOAUM3, DMM_DTOAUM4, DMM_DTOAUM5, "
            "DMM_DTOAUM6, DMM_PORIVA, DMM_PORREQ, DMM_VALLIN, DMM_IMPDTO, DMM_OBSERV, DMM_EJERCIP, "
            "DMM_SERIEP, DMM_NUMDOCP, DMM_NUMLINP, DMM_EJEOFE, DMM_NUMOFE) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(line[key] for key in [
                "DMM_NUMEMP", "DMM_CENTRO", "DMM_EJERCI", "DMM_SERIE", "DMM_NUMDOC", "DMM_NUMLIN",
                "DMM_FECMOV", "DMM_TIPLIN", "DMM_CODART", "DMM_CODARP", "DMM_DESCRI", "DMM_CANTIDP",
                "DMM_UNIMED", "DMM_CANTID", "DMM_PREBAS", "DMM_CODMON", "DMM_DTOAUM1", "DMM_DTOAUM2",
                "DMM_DTOAUM3", "DMM_DTOAUM4", "DMM_DTOAUM5", "DMM_DTOAUM6", "DMM_PORIVA", "DMM_PORREQ",
                "DMM_VALLIN", "DMM_IMPDTO", "DMM_OBSERV", "DMM_EJERCIP", "DMM_SERIEP", "DMM_NUMDOCP",
                "DMM_NUMLINP", "DMM_EJEOFE", "DMM_NUMOFE",
            ]),
        )
        if line.get("DMM_CODART"):
            self.db.execute(
                "UPDATE ARTICUL SET ART_OBSOL=? WHERE ART_NUMEMP=? AND ART_CODART=?",
                ("N", self.settings.empresa, str(line["DMM_CODART"])),
            )
        return int(line["DMM_NUMLIN"])

    def _finalize_purchase_entry_header(self, header: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
        buckets: list[dict[str, Decimal]] = []
        for line in lines:
            if line.get("DMM_TIPLIN") == "C":
                continue
            poriva = dec(line.get("DMM_PORIVA"))
            porreq = dec(line.get("DMM_PORREQ"))
            bucket = next((x for x in buckets if x["poriva"] == poriva and x["porreq"] == porreq), None)
            if bucket is None and len(buckets) < 4:
                bucket = {"base": Decimal("0"), "poriva": poriva, "porreq": porreq}
                buckets.append(bucket)
            if bucket is not None:
                bucket["base"] += dec(line.get("DMM_VALLIN"))
        while len(buckets) < 4:
            buckets.append({"base": Decimal("0"), "poriva": Decimal("0"), "porreq": Decimal("0")})
        for index, bucket in enumerate(buckets[:4], start=1):
            header[f"CBM_BASIMP{index}"] = bucket["base"]
            header[f"CBM_PORIVA{index}"] = bucket["poriva"]
            header[f"CBM_PORREQ{index}"] = bucket["porreq"]
        pordto = dec(header.get("CBM_PORDTO"))
        imppor = dec(header.get("CBM_IMPPOR"))
        totals = (
            header["CBM_BASIMP1"] * (1 - pordto / 100) + imppor
            + header["CBM_BASIMP2"] * (1 - pordto / 100)
            + header["CBM_BASIMP3"] * (1 - pordto / 100)
            + header["CBM_BASIMP4"] * (1 - pordto / 100)
        )
        article_service = FaroArticleService(self.db)
        header["CBM_TOTALS"] = article_service.round_price(totals, str(header.get("CBM_CODMON") or "E"), "I")
        iva = (
            (header["CBM_BASIMP1"] * (1 - pordto / 100) + imppor) * header["CBM_PORIVA1"] / 100
            + header["CBM_BASIMP2"] * (1 - pordto / 100) * header["CBM_PORIVA2"] / 100
            + header["CBM_BASIMP3"] * (1 - pordto / 100) * header["CBM_PORIVA3"] / 100
            + header["CBM_BASIMP4"] * (1 - pordto / 100) * header["CBM_PORIVA4"] / 100
        )
        recargo = (
            (header["CBM_BASIMP1"] * (1 - pordto / 100) + imppor) * header["CBM_PORREQ1"] / 100
            + header["CBM_BASIMP2"] * (1 - pordto / 100) * header["CBM_PORREQ2"] / 100
            + header["CBM_BASIMP3"] * (1 - pordto / 100) * header["CBM_PORREQ3"] / 100
            + header["CBM_BASIMP4"] * (1 - pordto / 100) * header["CBM_PORREQ4"] / 100
        )
        header["CBM_TOTALD"] = article_service.round_price(header["CBM_TOTALS"] + iva + recargo, str(header.get("CBM_CODMON") or "E"), "I")
        if header["CBM_BASIMP1"] != 0 and (pordto != 0 or imppor != 0) and header["CBM_TOTALS"] != imppor:
            self.db.execute(
                "UPDATE DETMOVM SET DMM_IMPDTO=(DMM_VALLIN * ?) - (? * DMM_VALLIN / ?) "
                "WHERE DMM_NUMEMP=? AND DMM_CENTRO=? AND DMM_EJERCI=? AND DMM_SERIE=? AND DMM_NUMDOC=?",
                (
                    pordto / 100,
                    imppor,
                    header["CBM_TOTALS"] - imppor,
                    self.settings.empresa,
                    int(header["CBM_CENTRO"]),
                    int(header["CBM_EJERCI"]),
                    str(header["CBM_SERIE"]),
                    int(header["CBM_NUMDOC"]),
                ),
            )
        header["CBM_FECMOD"] = datetime.now()
        header["CBM_USUMOD"] = self.settings.usuario
        self.db.execute(
            "UPDATE CABDOCM SET CBM_FECHA=?, CBM_FECREC=?, CBM_CODPRO=?, CBM_NOMPRO=?, CBM_DOMICI=?, CBM_CODPOS=?, "
            "CBM_POBLAC=?, CBM_CIF=?, CBM_CODPAG=?, CBM_ALBPRO=?, CBM_FACPRO=?, CBM_FECFAC=?, CBM_CODMON=?, "
            "CBM_PORDTO=?, CBM_IMPPOR=?, CBM_BASIMP1=?, CBM_PORIVA1=?, CBM_PORREQ1=?, CBM_BASIMP2=?, "
            "CBM_PORIVA2=?, CBM_PORREQ2=?, CBM_BASIMP3=?, CBM_PORIVA3=?, CBM_PORREQ3=?, CBM_BASIMP4=?, "
            "CBM_PORIVA4=?, CBM_PORREQ4=?, CBM_TOTALD=?, CBM_TOTALS=?, CBM_INDEDI=?, CBM_SITUAC=?, "
            "CBM_OBSERV=?, CBM_FECMOD=?, CBM_USUMOD=? WHERE CBM_NUMEMP=? AND CBM_CENTRO=? AND CBM_EJERCI=? "
            "AND CBM_SERIE=? AND CBM_NUMDOC=?",
            tuple(header[key] for key in [
                "CBM_FECHA", "CBM_FECREC", "CBM_CODPRO", "CBM_NOMPRO", "CBM_DOMICI", "CBM_CODPOS",
                "CBM_POBLAC", "CBM_CIF", "CBM_CODPAG", "CBM_ALBPRO", "CBM_FACPRO", "CBM_FECFAC",
                "CBM_CODMON", "CBM_PORDTO", "CBM_IMPPOR", "CBM_BASIMP1", "CBM_PORIVA1", "CBM_PORREQ1",
                "CBM_BASIMP2", "CBM_PORIVA2", "CBM_PORREQ2", "CBM_BASIMP3", "CBM_PORIVA3", "CBM_PORREQ3",
                "CBM_BASIMP4", "CBM_PORIVA4", "CBM_PORREQ4", "CBM_TOTALD", "CBM_TOTALS", "CBM_INDEDI",
                "CBM_SITUAC", "CBM_OBSERV", "CBM_FECMOD", "CBM_USUMOD",
            ]) + (
                self.settings.empresa,
                int(header["CBM_CENTRO"]),
                int(header["CBM_EJERCI"]),
                str(header["CBM_SERIE"]),
                int(header["CBM_NUMDOC"]),
            ),
        )
        return header

    def create_purchase_entry(self, cabecera: dict[str, Any], lineas: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(cabecera, dict):
            raise FaroError("cabecera debe ser un objeto")
        if not isinstance(lineas, list) or not lineas:
            raise FaroError("lineas debe contener al menos una linea")
        provider = self._resolve_purchase_provider(cabecera)
        header = self._purchase_entry_header(cabecera, provider)
        try:
            header = self._insert_cabdocm_header(header)
            inserted_lines: list[dict[str, Any]] = []
            for index, raw_line in enumerate(lineas, start=1):
                if not isinstance(raw_line, dict):
                    raise FaroError(f"lineas[{index}] debe ser un objeto")
                line = self._purchase_entry_line(header, raw_line, index)
                self._insert_detmovm_with_stock(line)
                inserted_lines.append(line)
            header = self._finalize_purchase_entry_header(header, inserted_lines)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {
            "ok": True,
            "updated": True,
            "documento": {
                "centro": int(header["CBM_CENTRO"]),
                "ejercicio": int(header["CBM_EJERCI"]),
                "serie": str(header["CBM_SERIE"]),
                "numero": int(header["CBM_NUMDOC"]),
            },
            "proveedor": int(header["CBM_CODPRO"]),
            "lineas": len(inserted_lines),
            "totales": {
                "base": normalize(header["CBM_TOTALS"]),
                "total": normalize(header["CBM_TOTALD"]),
            },
            "articulos": [
                {
                    "linea": int(line["DMM_NUMLIN"]),
                    "articulo": str(line["DMM_CODART"]),
                    "tipo_linea": str(line["DMM_TIPLIN"]),
                    "cantidad": normalize(line["DMM_CANTID"]),
                    "pedido": {
                        "ejercicio": int(line["DMM_EJERCIP"]),
                        "serie": str(line["DMM_SERIEP"]),
                        "numero": int(line["DMM_NUMDOCP"]),
                        "linea": int(line["DMM_NUMLINP"]),
                    } if int(line["DMM_EJERCIP"]) else None,
                }
                for line in inserted_lines
            ],
        }

    def get_or_create_regularization_header(self, centro: int) -> dict[str, Any]:
        today = date.today()
        doc_date = today - timedelta(days=1)
        row = self.db.fetch_one(
            "SELECT * FROM CABDOCR WHERE CBR_NUMEMP=? AND CBR_CENTRO=? AND CBR_TIPO=? AND CBR_FECHA=?",
            (self.settings.empresa, centro, "R", doc_date),
        )
        if row:
            header = normalize(row)
            header["created"] = False
            return header
        serie = self.parameter(f"R{centro}")
        if not serie:
            raise FaroError(f"No existe parametro de serie para regularizaciones: R{centro}")
        ejerci = today.year
        numdoc = self.next_cab_docr_number(centro, ejerci, serie)
        now = datetime.now()
        while True:
            try:
                self.db.execute(
                    "INSERT INTO CABDOCR (CBR_NUMEMP, CBR_CENTRO, CBR_EJERCI, CBR_SERIE, CBR_NUMDOC, "
                    "CBR_FECHA, CBR_TIPO, CBR_CENREL, CBR_FECINF, CBR_FECSUP, CBR_OBSERV, CBR_NUMDOCE, CBR_FECMOD, CBR_USUMOD) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self.settings.empresa,
                        centro,
                        ejerci,
                        serie,
                        numdoc,
                        doc_date,
                        "R",
                        0,
                        None,
                        None,
                        "Regularización por recuento",
                        0,
                        now,
                        self.settings.usuario,
                    ),
                )
                break
            except Exception:
                if numdoc >= 999999:
                    raise
                numdoc += 1
        return {
            "CBR_NUMEMP": self.settings.empresa,
            "CBR_CENTRO": centro,
            "CBR_EJERCI": ejerci,
            "CBR_SERIE": serie,
            "CBR_NUMDOC": numdoc,
            "CBR_FECHA": doc_date.isoformat(),
            "CBR_TIPO": "R",
            "created": True,
        }

    def accumulate_stock(self, codart: str, centro: int, difference: Decimal) -> None:
        now = datetime.now()
        try:
            self.db.execute(
                "INSERT INTO ARTICULE (ARTE_NUMEMP, ARTE_CODART, ARTE_CENTRO, ARTE_EXIST, ARTE_MINIMO, ARTE_MAXIMO, "
                "ARTE_FECCOM, ARTE_FECVEN, ARTE_FECMOV) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.settings.empresa, codart, centro, difference, 0, 0, None, None, now),
            )
            try:
                self.db.execute(
                    "INSERT INTO STOCKS (STO_NUMEMP, STO_CODART, STO_CENTRO, STO_FECHA, STO_EXIST) VALUES (?, ?, ?, ?, ?)",
                    (self.settings.empresa, codart, self.settings.centro, date.today(), 0),
                )
            except Exception:
                pass
        except Exception:
            self.db.execute(
                "UPDATE ARTICULE SET ARTE_EXIST=ARTE_EXIST + ?, ARTE_FECMOV=? "
                "WHERE ARTE_NUMEMP=? AND ARTE_CODART=? AND ARTE_CENTRO=?",
                (difference, now, self.settings.empresa, codart, centro),
            )

    def _article_controls_inventory(self, codart: str) -> bool:
        row = self.db.fetch_one(
            "SELECT ART_INDINV FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        if not row:
            raise FaroError(f"Articulo no encontrado: {codart}")
        return str(row.get("ART_INDINV") or "").strip().upper() == "S"

    def _insert_cabdocr_header(
        self,
        centro: int,
        ejerci: int,
        serie: str,
        fecha: date,
        tipo: str,
        cenrel: int,
        observ: str,
        numdoce: int = 0,
    ) -> dict[str, Any]:
        """Inserta una cabecera CABDOCR reproduciendo la numeracion con reintento de Delphi."""
        numdoc = self.next_cab_docr_number(centro, ejerci, serie)
        now = datetime.now()
        while True:
            try:
                self.db.execute(
                    "INSERT INTO CABDOCR (CBR_NUMEMP, CBR_CENTRO, CBR_EJERCI, CBR_SERIE, CBR_NUMDOC, "
                    "CBR_FECHA, CBR_TIPO, CBR_CENREL, CBR_FECINF, CBR_FECSUP, CBR_OBSERV, CBR_NUMDOCE, CBR_FECMOD, CBR_USUMOD) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self.settings.empresa,
                        centro,
                        ejerci,
                        serie,
                        numdoc,
                        fecha,
                        tipo,
                        cenrel,
                        None,
                        None,
                        observ,
                        numdoce,
                        now,
                        self.settings.usuario,
                    ),
                )
                return {
                    "CBR_NUMEMP": self.settings.empresa,
                    "CBR_CENTRO": centro,
                    "CBR_EJERCI": ejerci,
                    "CBR_SERIE": serie,
                    "CBR_NUMDOC": numdoc,
                    "CBR_FECHA": fecha,
                    "CBR_TIPO": tipo,
                    "CBR_CENREL": cenrel,
                    "CBR_FECINF": None,
                    "CBR_FECSUP": None,
                    "CBR_OBSERV": observ,
                    "CBR_NUMDOCE": numdoce,
                    "CBR_FECMOD": now,
                    "CBR_USUMOD": self.settings.usuario,
                }
            except Exception:
                if numdoc >= 999999:
                    raise
                numdoc += 1

    def _insert_detmovr_with_stock(
        self,
        *,
        centro: int,
        ejerci: int,
        serie: str,
        numdoc: int,
        fecmov: date,
        codart: str,
        descri: str,
        unimed: str,
        cantidad: Decimal,
        ejercio: int = 0,
        serieo: str = "",
        numdoco: int = 0,
        numlino: int = 0,
    ) -> int:
        """Equivalente nativo a GRABAR_DETMOVR(...,'G'): acumula stock e inserta la linea."""
        numlin = self.next_detmovr_line(centro, ejerci, serie, numdoc)
        if self._article_controls_inventory(codart):
            self.accumulate_stock(codart, centro, cantidad)
        self.db.execute(
            "INSERT INTO DETMOVR (DMR_NUMEMP, DMR_CENTRO, DMR_EJERCI, DMR_SERIE, DMR_NUMDOC, DMR_NUMLIN, "
            "DMR_FECMOV, DMR_CODART, DMR_DESCRI, DMR_UNIMED, DMR_CANTID, DMR_EJERCIO, DMR_SERIEO, DMR_NUMDOCO, DMR_NUMLINO) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.settings.empresa,
                centro,
                ejerci,
                serie,
                numdoc,
                numlin,
                fecmov,
                codart,
                descri,
                unimed,
                cantidad,
                ejercio,
                serieo,
                numdoco,
                numlino,
            ),
        )
        return numlin

    def _delete_cabdocr_document(self, header: dict[str, Any]) -> None:
        """Equivalente a GRABAR_CABDOCR(...,'A') para el documento de entrada espejo."""
        centro = int(header.get("CBR_CENTRO") or 0)
        ejerci = int(header.get("CBR_EJERCI") or 0)
        serie = str(header.get("CBR_SERIE") or "")
        numdoc = int(header.get("CBR_NUMDOC") or 0)
        rows = self.db.fetch_all(
            "SELECT * FROM DETMOVR WHERE DMR_NUMEMP=? AND DMR_CENTRO=? AND DMR_EJERCI=? AND DMR_SERIE=? AND DMR_NUMDOC=? "
            "ORDER BY DMR_NUMLIN",
            (self.settings.empresa, centro, ejerci, serie, numdoc),
        )
        for row in rows:
            codart = str(row.get("DMR_CODART") or "")
            if codart and self._article_controls_inventory(codart):
                self.accumulate_stock(codart, centro, -dec(row.get("DMR_CANTID")))
            self.db.execute(
                "DELETE FROM DETMOVR WHERE DMR_NUMEMP=? AND DMR_CENTRO=? AND DMR_EJERCI=? AND DMR_SERIE=? AND DMR_NUMDOC=? AND DMR_NUMLIN=?",
                (self.settings.empresa, centro, ejerci, serie, numdoc, int(row.get("DMR_NUMLIN") or 0)),
            )
        self.db.execute(
            "DELETE FROM CABDOCR WHERE CBR_NUMEMP=? AND CBR_CENTRO=? AND CBR_EJERCI=? AND CBR_SERIE=? AND CBR_NUMDOC=?",
            (self.settings.empresa, centro, ejerci, serie, numdoc),
        )

    def transfer_centers(self, centroo: int | str, centrod: int | str, texto: str) -> dict[str, Any]:
        """Replica TRASVASE_CENTROS: salida en origen + entrada espejo regenerada en destino."""
        origin = int(centroo)
        destination = int(centrod)
        if not texto:
            # El Delphi devuelve True inmediatamente sin abrir transaccion.
            return {"ok": True, "updated": False, "reason": "Sin lineas", "origin": origin, "destination": destination}
        # PROCESAR_CADENA de Delphi: cada segmento se TRIMea y el bucle
        # termina en cuanto encuentra un VALOR vacio (por ejemplo ante "##").
        raw_lines: list[str] = []
        remaining = str(texto)
        while True:
            if "#" in remaining:
                raw, remaining = remaining.split("#", 1)
            else:
                raw, remaining = remaining, ""
            raw = raw.strip()
            if not raw:
                break
            raw_lines.append(raw)
            if not remaining:
                break

        parsed: list[dict[str, Any]] = []
        for pos, raw in enumerate(raw_lines, start=1):
            fields = [field.strip() for field in raw.split("|")]
            if len(fields) < 3:
                raise FaroError(f"Linea de trasvase {pos} invalida; se esperan CODART|DESCRI|CANTID|UNIMED")
            fields += [""] * (4 - len(fields))
            codart, descri, cantid_text, unimed = fields[0], fields[1], fields[2], fields[3]
            try:
                amount = dec(cantid_text)
            except Exception as exc:
                raise FaroError(f"Cantidad invalida en linea {pos}: {cantid_text}") from exc
            if not descri or not unimed:
                article = self.article_description_and_unit(codart)
                descri = descri or article["descri"]
                unimed = unimed or article["unimed"]
            parsed.append({"codart": codart, "descri": descri, "cantidad": amount, "unimed": unimed})
        if not parsed:
            return {"ok": True, "updated": False, "reason": "Sin lineas", "origin": origin, "destination": destination}

        today = date.today()
        try:
            out_header = self.db.fetch_one(
                "SELECT * FROM CABDOCR WHERE CBR_NUMEMP=? AND CBR_CENTRO=? AND CBR_TIPO=? AND CBR_FECHA=? AND CBR_CENREL=?",
                (self.settings.empresa, origin, "S", today, destination),
            )
            created_output = False
            if out_header:
                out_header = normalize(out_header)
            else:
                serie = self.parameter(f"R{self.settings.centro}")
                # SERIE_DOCUMENTO('R') usa R_PARAMETROS.CENTRO, no CENTROO.
                if not serie:
                    raise FaroError(f"No existe parametro de serie para regularizaciones: R{self.settings.centro}")
                out_header = self._insert_cabdocr_header(
                    origin, today.year, serie, today, "S", destination, f"Trasvase Centro {destination}", 0
                )
                created_output = True

            ejerci = int(out_header.get("CBR_EJERCI") or today.year)
            serie = str(out_header.get("CBR_SERIE") or "")
            out_numdoc = int(out_header.get("CBR_NUMDOC") or 0)
            for line in parsed:
                self._insert_detmovr_with_stock(
                    centro=origin,
                    ejerci=ejerci,
                    serie=serie,
                    numdoc=out_numdoc,
                    fecmov=today,
                    codart=str(line["codart"]),
                    descri=str(line["descri"]),
                    unimed=str(line["unimed"]),
                    cantidad=-line["cantidad"],
                )

            # FINALIZAR_CABDOCR: si la salida ya tenia entrada espejo, la anula
            # completamente (incluido stock) antes de regenerarla con TODAS las
            # lineas existentes de la salida.
            old_in_numdoc = int(out_header.get("CBR_NUMDOCE") or 0)
            if old_in_numdoc:
                old_in_header = self.db.fetch_one(
                    "SELECT * FROM CABDOCR WHERE CBR_NUMEMP=? AND CBR_CENTRO=? AND CBR_EJERCI=? AND CBR_SERIE=? AND CBR_NUMDOC=?",
                    (self.settings.empresa, destination, ejerci, serie, old_in_numdoc),
                )
                if old_in_header:
                    self._delete_cabdocr_document(normalize(old_in_header))

            in_header = self._insert_cabdocr_header(
                destination,
                ejerci,
                serie,
                today,
                "E",
                origin,
                str(out_header.get("CBR_OBSERV") or f"Trasvase Centro {destination}"),
                out_numdoc,
            )
            in_numdoc = int(in_header["CBR_NUMDOC"])
            output_lines = self.db.fetch_all(
                "SELECT * FROM DETMOVR WHERE DMR_NUMEMP=? AND DMR_CENTRO=? AND DMR_EJERCI=? AND DMR_SERIE=? AND DMR_NUMDOC=? ORDER BY DMR_NUMLIN",
                (self.settings.empresa, origin, ejerci, serie, out_numdoc),
            )
            for row in output_lines:
                # El Delphi historico no copiaba DMR_UNIMED a R_DMR_SAL en
                # FINALIZAR_CABDOCR (la entrada espejo quedaba sin unidad de
                # medida). Aqui se corrige deliberadamente ese defecto y se
                # copia la unidad de medida real de la linea de salida.
                self._insert_detmovr_with_stock(
                    centro=destination,
                    ejerci=ejerci,
                    serie=serie,
                    numdoc=in_numdoc,
                    fecmov=today,
                    codart=str(row.get("DMR_CODART") or ""),
                    descri=str(row.get("DMR_DESCRI") or ""),
                    unimed=str(row.get("DMR_UNIMED") or ""),
                    cantidad=-dec(row.get("DMR_CANTID")),
                    ejercio=int(row.get("DMR_EJERCIO") or 0),
                    serieo=str(row.get("DMR_SERIEO") or ""),
                    numdoco=int(row.get("DMR_NUMDOCO") or 0),
                    numlino=int(row.get("DMR_NUMLINO") or 0),
                )

            self.db.execute(
                "UPDATE CABDOCR SET CBR_NUMDOCE=?, CBR_FECMOD=?, CBR_USUMOD=? "
                "WHERE CBR_NUMEMP=? AND CBR_CENTRO=? AND CBR_EJERCI=? AND CBR_SERIE=? AND CBR_NUMDOC=?",
                (
                    in_numdoc,
                    datetime.now(),
                    self.settings.usuario,
                    self.settings.empresa,
                    origin,
                    ejerci,
                    serie,
                    out_numdoc,
                ),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "ok": True,
            "updated": True,
            "origin": origin,
            "destination": destination,
            "lines_added": len(parsed),
            "output_document": {"centro": origin, "ejerci": ejerci, "serie": serie, "numdoc": out_numdoc, "created": created_output},
            "input_document": {"centro": destination, "ejerci": ejerci, "serie": serie, "numdoc": in_numdoc, "regenerated": bool(old_in_numdoc)},
        }

    def coinfer_stock(self, codart: str) -> dict[str, Any]:
        """Replica Stock_Coinfer_Articulo leyendo <PARAMETROS.STOCKS>/Stocks.txt."""
        codart = str(codart)
        result: dict[str, Any] = {"codart": codart, "stock": "0", "found": False, "datasnap_text": "0"}
        if len(codart) != 9:
            result["reason"] = "CODART debe tener 9 caracteres"
            return result
        ruta = self.parameter("STOCKS", "")
        if not ruta:
            result["reason"] = "Parametro STOCKS no configurado"
            return result

        # En Delphi se concatena literalmente RUTA + '\\Stocks.txt'. En Windows
        # Path/join produce el mismo destino; el reemplazo facilita las pruebas y
        # despliegues Linux con rutas configuradas usando separador Windows.
        clean_path = str(ruta).rstrip("\\/")
        if os.name != "nt":
            clean_path = clean_path.replace("\\", os.sep)
        filename = os.path.join(clean_path, "Stocks.txt")
        result["file"] = filename
        encoding = os.getenv("FARO_STOCKS_ENCODING", "cp1252")
        try:
            with open(filename, "r", encoding=encoding, errors="replace") as fh:
                for raw in fh:
                    fields = [field.strip() for field in raw.rstrip("\r\n").split(";")]
                    if fields and fields[0] == codart:
                        # El Delphi descarta el segundo campo y devuelve el tercero.
                        value = fields[2].strip() if len(fields) >= 3 else ""
                        if value:
                            try:
                                Decimal(value.replace(",", "."))
                            except Exception:
                                result["reason"] = "Stock Coinfer no numerico"
                                return result
                            result.update({"stock": value, "found": True, "datasnap_text": value})
                        return result
        except OSError:
            result["reason"] = "No se pudo abrir Stocks.txt"
            return result
        result["reason"] = "Articulo no encontrado en Stocks.txt"
        return result

    def check_time_clock_user(self, password: str) -> dict[str, Any]:
        """Replica Comprobar_Usuario: valida password y alterna marcajes I/F en HORAS.

        El servidor historico recibia unicamente la clave, la cifraba con CRIPT y buscaba el
        usuario del centro configurado. El nuevo registro siempre invierte el
        ultimo tipo: I -> F (calculando HOR_TIEMPO) y F -> I. Si no hay
        historial, genera una entrada I.

        A diferencia del Delphi original, que deja ULTIMA_HORA sin inicializar
        cuando no existe un marcaje anterior, aqui ``previous_time`` es None y
        el ultimo campo de ``datasnap_text`` queda vacio. Asi se evita exponer
        memoria/valor indeterminado sin cambiar el contrato de campos.
        """
        encrypted = cript(1, str(password), "")
        # Igual que CRIPT en Delphi: una clave con caracteres no soportados
        # produce cadena vacia y, salvo que existiese tal valor en USUAR, no
        # autenticara al usuario.
        user_row = self.db.fetch_one(
            "SELECT USU_NOMUSU FROM USUAR WHERE USU_NUMEMP=? AND USU_CODCEN=? AND USU_PASSWORD=?",
            (self.settings.empresa, self.settings.centro, encrypted),
        )
        if not user_row:
            return {
                "ok": False,
                "usuario": "",
                "tipo": "",
                "previous_time": None,
                "worked_hours": "0",
                "message": "Usuario no Encontrado",
                "datasnap_text": "9|Usuario no Encontrado|||",
            }

        usuario = str(user_row.get("USU_NOMUSU") or "")
        previous = self.db.fetch_one(
            "SELECT * FROM HORAS WHERE HOR_NUMEMP=? AND HOR_CENTRO=? AND HOR_USUAR=? ORDER BY HOR_TIME DESC",
            (self.settings.empresa, self.settings.centro, usuario),
        )
        now = datetime.now()
        previous_time: datetime | None = None
        tipo = "I"
        worked_hours = Decimal("0")

        if previous:
            raw_previous_time = previous.get("HOR_TIME")
            if isinstance(raw_previous_time, datetime):
                previous_time = raw_previous_time
            elif isinstance(raw_previous_time, date):
                previous_time = datetime.combine(raw_previous_time, datetime.min.time())
            elif raw_previous_time is not None:
                # Los drivers Firebird/ODBC normalmente ya devuelven datetime,
                # pero aceptamos ISO como salvaguarda para adaptadores/tests.
                try:
                    previous_time = datetime.fromisoformat(str(raw_previous_time))
                except ValueError as exc:
                    raise FaroError(f"HOR_TIME no es una fecha valida: {raw_previous_time}") from exc

            if str(previous.get("HOR_TIPO") or "") == "I":
                tipo = "F"
                if previous_time is not None:
                    # HOR_TIEMPO es CURRENCY en Delphi (4 decimales) y se
                    # almacena como numero de horas, no como fraccion de dia.
                    seconds = Decimal(str((now - previous_time).total_seconds()))
                    worked_hours = (seconds / Decimal("3600")).quantize(Decimal("0.0001"))
            else:
                tipo = "I"

        try:
            self.db.execute(
                "INSERT INTO HORAS (HOR_NUMEMP,HOR_CENTRO,HOR_USUAR,HOR_TIME,HOR_TIPO,HOR_TIEMPO) "
                "VALUES (?,?,?,?,?,?)",
                (
                    self.settings.empresa,
                    self.settings.centro,
                    usuario,
                    now,
                    tipo,
                    worked_hours,
                ),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            return {
                "ok": False,
                "usuario": usuario,
                "tipo": tipo,
                "previous_time": normalize(previous_time),
                "worked_hours": normalize(worked_hours),
                "message": "Error al Grabar Registro",
                "datasnap_text": "9|Error al Grabar Registro|||",
            }

        # DateTimeToStr depende del locale de Windows. El despliegue historico
        # es ES y usa dd/mm/yyyy hh:mm:ss; el campo queda vacio en el primer
        # marcaje para resolver de forma determinista el ULTIMA_HORA indefinido
        # del codigo Delphi.
        previous_text = previous_time.strftime("%d/%m/%Y %H:%M:%S") if previous_time else ""
        return {
            "ok": True,
            "usuario": usuario,
            "tipo": tipo,
            "time": now.isoformat(),
            "previous_time": normalize(previous_time),
            "worked_hours": normalize(worked_hours),
            "message": "",
            "datasnap_text": f"0||{usuario}|{tipo}|{previous_text}",
        }

    def regularize_stock(
        self, codart: str, centro: int | str, descri: str = "", unimed: str = "", cantid: Any = 0
    ) -> dict[str, Any]:
        centro_int = int(centro)
        try:
            target_stock = dec(cantid)
        except Exception as exc:
            raise FaroError(f"Cantidad de stock no valida: {cantid}") from exc
        article = self.db.fetch_one(
            "SELECT ART_CODART, ART_DESCRI, ART_UNIMED, ART_INDINV FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        if not article:
            raise FaroError(f"Articulo no encontrado: {codart}")
        descri_s = str(descri or "").strip() or clean_text_value(article.get("ART_DESCRI"))
        unimed_s = str(unimed or "").strip() or str(article.get("ART_UNIMED") or "").strip()
        current_stock = self.current_stock_decimal(codart, centro_int)
        difference = target_stock - current_stock
        if difference == 0:
            return {
                "codart": codart,
                "centro": centro_int,
                "updated": False,
                "reason": "La existencia actual ya coincide con la cantidad indicada.",
                "before_stock": normalize(current_stock),
                "after_stock": normalize(current_stock),
                "difference": "0",
            }
        try:
            header = self.get_or_create_regularization_header(centro_int)
            ejerci = int(header["CBR_EJERCI"])
            serie = str(header["CBR_SERIE"])
            numdoc = int(header["CBR_NUMDOC"])
            numlin = self.next_detmovr_line(centro_int, ejerci, serie, numdoc)
            fecmov = date.fromisoformat(str(header["CBR_FECHA"])[:10]) if header.get("CBR_FECHA") else date.today() - timedelta(days=1)
            if str(article.get("ART_INDINV") or "") == "S":
                self.accumulate_stock(codart, centro_int, difference)
                stock_accumulated = True
            else:
                stock_accumulated = False
            self.db.execute(
                "INSERT INTO DETMOVR (DMR_NUMEMP, DMR_CENTRO, DMR_EJERCI, DMR_SERIE, DMR_NUMDOC, DMR_NUMLIN, "
                "DMR_FECMOV, DMR_CODART, DMR_DESCRI, DMR_UNIMED, DMR_CANTID, DMR_EJERCIO, DMR_SERIEO, DMR_NUMDOCO, DMR_NUMLINO) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.settings.empresa,
                    centro_int,
                    ejerci,
                    serie,
                    numdoc,
                    numlin,
                    fecmov,
                    codart,
                    descri_s,
                    unimed_s,
                    difference,
                    0,
                    "",
                    0,
                    0,
                ),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        after_stock = self.current_stock_decimal(codart, centro_int)
        return {
            "codart": codart,
            "centro": centro_int,
            "updated": True,
            "before_stock": normalize(current_stock),
            "target_stock": normalize(target_stock),
            "difference": normalize(difference),
            "after_stock": normalize(after_stock),
            "stock_accumulated": stock_accumulated,
            "document": {
                "centro": centro_int,
                "ejerci": ejerci,
                "serie": serie,
                "numdoc": numdoc,
                "numlin": numlin,
                "fecha": fecmov.isoformat(),
                "header_created": bool(header.get("created")),
            },
        }

    def get_labels(self, codart: str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM ETIQUE WHERE ETI_NUMEMP=? AND ETI_CODART=?",
            (self.settings.empresa, codart),
        )
        if not row:
            return {"codart": codart, "found": False, "datasnap_text": ""}
        row = normalize(row)
        return {
            "codart": codart,
            "found": True,
            "descri": row.get("ETI_DESCRI"),
            "cantid": row.get("ETI_CANTID"),
            "imprimir": row.get("ETI_IMPRIM"),
            "modelo": row.get("ETI_MODELO"),
            "descri2": row.get("ETI_DESCRI2"),
            "datasnap_text": serialize_text_value(row.get("ETI_CANTID")),
        }

    def list_labels(self) -> dict[str, Any]:
        rows = self.db.fetch_all(
            "SELECT * FROM ETIQUE WHERE ETI_NUMEMP=? ORDER BY ETI_CODART",
            (self.settings.empresa,),
        )
        items = []
        parts = []
        for row in rows:
            row = normalize(row)
            item = {
                "codart": row.get("ETI_CODART"),
                "descri": clean_text_value(row.get("ETI_DESCRI")),
                "cantid": row.get("ETI_CANTID"),
                "imprimir": row.get("ETI_IMPRIM"),
                "modelo": row.get("ETI_MODELO"),
            }
            items.append(item)
            parts.append("|".join(serialize_text_value(item[key]) for key in ["codart", "descri", "cantid"]))
        return {"count": len(items), "items": items, "datasnap_text": "#".join(parts) + ("#" if parts else "")}

    def save_labels(
        self,
        codart: str,
        descri: str,
        cantid: Any,
        aumentar: bool,
        modelo: Any,
        imprimir: bool,
    ) -> dict[str, Any]:
        try:
            amount = dec(cantid)
        except Exception as exc:
            raise FaroError(f"Cantidad de etiquetas no valida: {cantid}") from exc
        try:
            model = int(modelo)
        except Exception as exc:
            raise FaroError(f"Modelo de etiqueta no valido: {modelo}") from exc
        descri_s = str(descri or "").strip()
        if not descri_s:
            article = self.db.fetch_one(
                "SELECT ART_DESCRI FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                (self.settings.empresa, codart),
            )
            if not article:
                raise FaroError(f"Articulo no encontrado: {codart}")
            descri_s = clean_text_value(article.get("ART_DESCRI"))

        before = self.get_labels(codart)
        imprim = "S" if imprimir else "N"
        try:
            if not aumentar:
                self.db.execute(
                    "DELETE FROM ETIQUE WHERE ETI_NUMEMP=? AND ETI_CODART=?",
                    (self.settings.empresa, codart),
                )
                self.db.execute(
                    "INSERT INTO ETIQUE (ETI_NUMEMP, ETI_CODART, ETI_DESCRI, ETI_CANTID, ETI_IMPRIM, ETI_MODELO, ETI_DESCRI2) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (self.settings.empresa, codart, descri_s, amount, imprim, model, ""),
                )
            else:
                try:
                    self.db.execute(
                        "INSERT INTO ETIQUE (ETI_NUMEMP, ETI_CODART, ETI_DESCRI, ETI_CANTID, ETI_IMPRIM, ETI_MODELO, ETI_DESCRI2) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (self.settings.empresa, codart, descri_s, amount, imprim, model, ""),
                    )
                except Exception:
                    self.db.rollback()
                    self.db.execute(
                        "UPDATE ETIQUE SET ETI_CANTID=ETI_CANTID + ? WHERE ETI_NUMEMP=? AND ETI_CODART=?",
                        (amount, self.settings.empresa, codart),
                    )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        after = self.get_labels(codart)
        return {
            "codart": codart,
            "updated": True,
            "mode": "aumentar" if aumentar else "sustituir",
            "before": before,
            "after": after,
            "diff": diff(
                {k: before.get(k) for k in ["found", "descri", "cantid", "imprimir", "modelo", "descri2"]},
                {k: after.get(k) for k in ["found", "descri", "cantid", "imprimir", "modelo", "descri2"]},
            ),
        }

    def article_recount(self, codart: str, centro: int | str) -> dict[str, Any]:
        if not _center_filter_is_set(centro):
            rows = self.db.fetch_all(
                "SELECT * FROM RECUENTO WHERE REC_NUMEMP=? AND REC_CODART=? ORDER BY REC_CENTRO",
                (self.settings.empresa, codart),
            )
            items = [
                {
                    "codart": row.get("REC_CODART"),
                    "centro": int(row.get("REC_CENTRO") or 0),
                    "found": True,
                    "descri": clean_text_value(row.get("REC_DESCRI")),
                    "existencias": normalize(row.get("REC_EXIST")),
                    "fecha": normalize(row.get("REC_FECHA")),
                    "unimed": row.get("REC_UNIMED"),
                }
                for row in rows
            ]
            return {"codart": codart, "scope": "todos", "count": len(items), "items": items}
        centro_int = int(centro)
        row = self.db.fetch_one(
            "SELECT * FROM RECUENTO WHERE REC_NUMEMP=? AND REC_CENTRO=? AND REC_CODART=?",
            (self.settings.empresa, centro_int, codart),
        )
        if not row:
            return {"codart": codart, "centro": centro_int, "found": False, "datasnap_text": ""}
        row = normalize(row)
        result = {
            "codart": codart,
            "centro": centro_int,
            "found": True,
            "descri": row.get("REC_DESCRI"),
            "existencias": row.get("REC_EXIST"),
            "fecha": row.get("REC_FECHA"),
            "unimed": row.get("REC_UNIMED"),
        }
        result["datasnap_text"] = "|".join(serialize_text_value(result[key]) for key in ["existencias", "fecha"])
        return result

    def list_recounts(self, centro: int | str) -> dict[str, Any]:
        params: tuple[Any, ...] = (self.settings.empresa,)
        where = "REC_NUMEMP=?"
        if _center_filter_is_set(centro):
            where += " AND REC_CENTRO=?"
            params = (self.settings.empresa, int(centro))
        rows = self.db.fetch_all(
            f"SELECT * FROM RECUENTO WHERE {where} ORDER BY REC_CENTRO, REC_CODART",
            params,
        )
        items = []
        parts = []
        for row in rows:
            row = normalize(row)
            item = {
                "codart": row.get("REC_CODART"),
                "centro": int(row.get("REC_CENTRO") or 0),
                "descri": clean_text_value(row.get("REC_DESCRI")),
                "existencias": row.get("REC_EXIST"),
                "fecha": row.get("REC_FECHA"),
                "unimed": row.get("REC_UNIMED"),
            }
            items.append(item)
            parts.append(
                "|".join(
                    serialize_text_value(item[key]) for key in ["codart", "descri", "existencias", "fecha", "unimed"]
                )
            )
        return {
            "centro": centro_int,
            "count": len(items),
            "items": items,
            "datasnap_text": "#".join(parts) + ("#" if parts else ""),
        }

    def save_recount(
        self,
        codart: str,
        centro: int | str,
        descri: str,
        unimed: str,
        cantid: Any,
        aumentar: bool,
    ) -> dict[str, Any]:
        centro_int = int(centro)
        try:
            amount = dec(cantid)
        except Exception as exc:
            raise FaroError(f"Cantidad de recuento no valida: {cantid}") from exc

        article = self.db.fetch_one(
            "SELECT ART_DESCRI, ART_UNIMED FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        if not article:
            raise FaroError(f"Articulo no encontrado: {codart}")
        # Igual que stock_regularizar: si no se indica descripcion o unidad de
        # medida, se autocompletan desde ARTICUL en vez de grabarlas vacias.
        descri_s = str(descri or "").strip() or clean_text_value(article.get("ART_DESCRI"))
        unimed_s = str(unimed or "").strip() or str(article.get("ART_UNIMED") or "").strip()

        before = self.article_recount(codart, centro_int)
        fecha = date.today()
        try:
            if not aumentar:
                self.db.execute(
                    "DELETE FROM RECUENTO WHERE REC_NUMEMP=? AND REC_CENTRO=? AND REC_CODART=?",
                    (self.settings.empresa, centro_int, codart),
                )
                self.db.execute(
                    "INSERT INTO RECUENTO (REC_NUMEMP, REC_CENTRO, REC_CODART, REC_DESCRI, REC_EXIST, REC_FECHA, REC_UNIMED) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (self.settings.empresa, centro_int, codart, descri_s, amount, fecha, unimed_s),
                )
            else:
                try:
                    self.db.execute(
                        "INSERT INTO RECUENTO (REC_NUMEMP, REC_CENTRO, REC_CODART, REC_DESCRI, REC_EXIST, REC_FECHA, REC_UNIMED) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (self.settings.empresa, centro_int, codart, descri_s, amount, fecha, unimed_s),
                    )
                except Exception:
                    self.db.rollback()
                    self.db.execute(
                        "UPDATE RECUENTO SET REC_EXIST=REC_EXIST + ? "
                        "WHERE REC_NUMEMP=? AND REC_CENTRO=? AND REC_CODART=?",
                        (amount, self.settings.empresa, centro_int, codart),
                    )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        after = self.article_recount(codart, centro_int)
        return {
            "codart": codart,
            "centro": centro_int,
            "updated": True,
            "mode": "aumentar" if aumentar else "sustituir",
            "before": before,
            "after": after,
            "diff": diff(
                {k: before.get(k) for k in ["found", "descri", "existencias", "fecha", "unimed"]},
                {k: after.get(k) for k in ["found", "descri", "existencias", "fecha", "unimed"]},
            ),
        }

    def delete_recount(self, codart: str, centro: int | str) -> dict[str, Any]:
        centro_int = int(centro)
        before = self.article_recount(codart, centro_int)
        try:
            self.db.execute(
                "DELETE FROM RECUENTO WHERE REC_NUMEMP=? AND REC_CENTRO=? AND REC_CODART=?",
                (self.settings.empresa, centro_int, codart),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"codart": codart, "centro": centro_int, "deleted": before.get("found", False)}

    def delete_labels(self, codart: str) -> dict[str, Any]:
        before = self.get_labels(codart)
        try:
            self.db.execute(
                "DELETE FROM ETIQUE WHERE ETI_NUMEMP=? AND ETI_CODART=?",
                (self.settings.empresa, codart),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"codart": codart, "deleted": before.get("found", False)}

    def article_description(self, codart: str) -> str:
        row = self.db.fetch_one(
            "SELECT ART_DESCRI FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        return str(row.get("ART_DESCRI") or "") if row else ""

    def _shortage_row(self, codart: str, centro: int, provee: int) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM FALTAS WHERE FAL_NUMEMP=? AND FAL_CENTRO=? AND FAL_CODART=? AND FAL_PROVEE=?",
            (self.settings.empresa, centro, codart, provee),
        )
        if not row:
            return {"codart": codart, "centro": centro, "provee": provee, "found": False}
        row = normalize(row)
        return {
            "codart": codart,
            "centro": centro,
            "provee": provee,
            "found": True,
            "cantid": row.get("FAL_CANTID"),
            "observ": row.get("FAL_OBSERV"),
            "usumod": row.get("FAL_USUMOD"),
        }

    def article_shortage(self, codart: str, centro: int | str) -> dict[str, Any]:
        # Replica fiel de Faltas_Articulo: no filtra por proveedor, toma la primera
        # fila que encuentre para el articulo/centro (puede haber varios proveedores).
        if not _center_filter_is_set(centro):
            rows = self.db.fetch_all(
                "SELECT * FROM FALTAS WHERE FAL_NUMEMP=? AND FAL_CODART=? ORDER BY FAL_CENTRO, FAL_PROVEE",
                (self.settings.empresa, codart),
            )
            items = [
                {
                    "codart": row.get("FAL_CODART"),
                    "centro": int(row.get("FAL_CENTRO") or 0),
                    "provee": row.get("FAL_PROVEE"),
                    "cantid": normalize(row.get("FAL_CANTID")),
                }
                for row in rows
            ]
            return {"codart": codart, "scope": "todos", "count": len(items), "items": items}
        centro_int = int(centro)
        row = self.db.fetch_one(
            "SELECT * FROM FALTAS WHERE FAL_NUMEMP=? AND FAL_CENTRO=? AND FAL_CODART=?",
            (self.settings.empresa, centro_int, codart),
        )
        if not row:
            return {"codart": codart, "centro": centro_int, "found": False, "datasnap_text": ""}
        row = normalize(row)
        return {
            "codart": codart,
            "centro": centro_int,
            "found": True,
            "provee": row.get("FAL_PROVEE"),
            "cantid": row.get("FAL_CANTID"),
            "datasnap_text": serialize_text_value(row.get("FAL_CANTID")),
        }

    def list_shortages(self, centro: int | str) -> dict[str, Any]:
        params: tuple[Any, ...] = (self.settings.empresa,)
        where = "FAL_NUMEMP=?"
        if _center_filter_is_set(centro):
            where += " AND FAL_CENTRO=?"
            params = (self.settings.empresa, int(centro))
        rows = self.db.fetch_all(
            f"SELECT * FROM FALTAS WHERE {where} ORDER BY FAL_CENTRO, FAL_CODART",
            params,
        )
        items = []
        parts = []
        for row in rows:
            row = normalize(row)
            codart = row.get("FAL_CODART")
            provee = row.get("FAL_PROVEE")
            item = {
                "codart": codart,
                "centro": int(row.get("FAL_CENTRO") or 0),
                "descri": clean_text_value(self.article_description(codart)),
                "provee": provee,
                "proveedor": self.provider_name(provee),
                "cantid": row.get("FAL_CANTID"),
            }
            items.append(item)
            parts.append(
                "|".join(serialize_text_value(item[key]) for key in ["codart", "descri", "provee", "proveedor", "cantid"])
            )
        return {
            "centro": centro_int,
            "count": len(items),
            "items": items,
            "datasnap_text": "#".join(parts) + ("#" if parts else ""),
        }

    def save_shortage(
        self,
        codart: str,
        centro: int | str,
        codpro: Any,
        cantid: Any,
        aumentar: bool,
    ) -> dict[str, Any]:
        centro_int = int(centro)
        try:
            amount = dec(cantid)
        except Exception as exc:
            raise FaroError(f"Cantidad de falta no valida: {cantid}") from exc
        try:
            provee = int(codpro)
        except Exception as exc:
            raise FaroError(f"Proveedor no valido: {codpro}") from exc

        if provee == 0:
            article = self.db.fetch_one(
                "SELECT ART_CODPRO, ART_INDPROP FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                (self.settings.empresa, codart),
            )
            if not article:
                raise FaroError(f"Articulo no encontrado: {codart}")
            if str(article.get("ART_INDPROP") or "") == "N":
                provee = int(self.parameter("COINFE", "9999"))
            else:
                provee = int(article.get("ART_CODPRO") or 0)

        before = self._shortage_row(codart, centro_int, provee)
        now = datetime.now()
        try:
            if not aumentar:
                self.db.execute(
                    "DELETE FROM FALTAS WHERE FAL_NUMEMP=? AND FAL_CENTRO=? AND FAL_CODART=? AND FAL_PROVEE=?",
                    (self.settings.empresa, centro_int, codart, provee),
                )
                self.db.execute(
                    "INSERT INTO FALTAS (FAL_NUMEMP, FAL_CENTRO, FAL_CODART, FAL_PROVEE, FAL_CANTID, "
                    "FAL_OBSERV, FAL_FECMOD, FAL_USUMOD, FAL_OBSERVI) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (self.settings.empresa, centro_int, codart, provee, amount, "", now, self.settings.usuario, ""),
                )
            else:
                try:
                    self.db.execute(
                        "INSERT INTO FALTAS (FAL_NUMEMP, FAL_CENTRO, FAL_CODART, FAL_PROVEE, FAL_CANTID, "
                        "FAL_OBSERV, FAL_FECMOD, FAL_USUMOD, FAL_OBSERVI) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            self.settings.empresa,
                            centro_int,
                            codart,
                            provee,
                            amount,
                            "",
                            now,
                            self.settings.usuario,
                            "",
                        ),
                    )
                except Exception:
                    self.db.rollback()
                    self.db.execute(
                        "UPDATE FALTAS SET FAL_CANTID=FAL_CANTID + ? "
                        "WHERE FAL_NUMEMP=? AND FAL_CENTRO=? AND FAL_CODART=? AND FAL_PROVEE=?",
                        (amount, self.settings.empresa, centro_int, codart, provee),
                    )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        after = self._shortage_row(codart, centro_int, provee)
        return {
            "codart": codart,
            "centro": centro_int,
            "provee": provee,
            "updated": True,
            "mode": "aumentar" if aumentar else "sustituir",
            "before": before,
            "after": after,
            "diff": diff(
                {k: before.get(k) for k in ["found", "cantid", "observ", "usumod"]},
                {k: after.get(k) for k in ["found", "cantid", "observ", "usumod"]},
            ),
        }

    def delete_shortage(self, codart: str, centro: int | str, provee: Any) -> dict[str, Any]:
        centro_int = int(centro)
        try:
            provee_int = int(provee)
        except Exception as exc:
            raise FaroError(f"Proveedor no valido: {provee}") from exc
        before = self._shortage_row(codart, centro_int, provee_int)
        try:
            self.db.execute(
                "DELETE FROM FALTAS WHERE FAL_NUMEMP=? AND FAL_CENTRO=? AND FAL_CODART=? AND FAL_PROVEE=?",
                (self.settings.empresa, centro_int, codart, provee_int),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"codart": codart, "centro": centro_int, "provee": provee_int, "deleted": before.get("found", False)}

    def article_info(self, codart: str, codinf: str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT ARTI_NUMLIN, ARTI_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_CODINF=?",
            (self.settings.empresa, codart, codinf),
        )
        if not row:
            return {"codart": codart, "codinf": codinf, "found": False, "descri": "", "datasnap_text": ""}
        row = normalize(row)
        descri = str(row.get("ARTI_DESCRI") or "")
        return {
            "codart": codart,
            "codinf": codinf,
            "found": True,
            "numlin": row.get("ARTI_NUMLIN"),
            "descri": descri,
            "datasnap_text": descri,
        }

    def _next_articuli_line(self, codart: str) -> int:
        # NUMERAR_ARTICULI: MAX(ARTI_NUMLIN) del articulo, sin filtrar por ARTI_CODINF
        # (la numeracion de linea es compartida entre ubicacion, marca, etc).
        row = self.db.fetch_one(
            "SELECT MAX(ARTI_NUMLIN) AS NUMLIN FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=?",
            (self.settings.empresa, codart),
        )
        return int(row.get("NUMLIN") or 0) + 1 if row else 1

    def save_articuli_info(self, codart: str, codinf: str, valor: str) -> dict[str, Any]:
        before = self.article_info(codart, codinf)
        try:
            if before.get("found"):
                self.db.execute(
                    "UPDATE ARTICULI SET ARTI_CODINF=?, ARTI_DESCRI=? "
                    "WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_NUMLIN=?",
                    (codinf, valor, self.settings.empresa, codart, before["numlin"]),
                )
            else:
                numlin = self._next_articuli_line(codart)
                self.db.execute(
                    "INSERT INTO ARTICULI (ARTI_NUMEMP, ARTI_CODART, ARTI_NUMLIN, ARTI_CODINF, ARTI_DESCRI) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (self.settings.empresa, codart, numlin, codinf, valor),
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        after = self.article_info(codart, codinf)
        return {
            "codart": codart,
            "codinf": codinf,
            "updated": True,
            "before": before,
            "after": after,
            "diff": diff(
                {k: before.get(k) for k in ["found", "descri"]},
                {k: after.get(k) for k in ["found", "descri"]},
            ),
        }

    def save_location(self, codart: str, ubicacion: str) -> dict[str, Any]:
        return self.save_articuli_info(codart, "UBICA", ubicacion)

    def save_location_secondary(self, codart: str, ubicacion: str) -> dict[str, Any]:
        return self.save_articuli_info(codart, "UBIC1", ubicacion)

    def save_ean(self, codart: str, ean: str) -> dict[str, Any]:
        try:
            Decimal(ean)
        except Exception as exc:
            raise FaroError(f"EAN no valido: {ean}") from exc
        try:
            self.db.execute(
                "INSERT INTO ARTICULC (ARTC_NUMEMP, ARTC_CODART, ARTC_CODIGO, ARTC_CANTID) VALUES (?, ?, ?, ?)",
                (self.settings.empresa, codart, ean, 1),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"codart": codart, "ean": ean, "updated": True}

    # ------------------------------------------------------------------
    # Fase 2A - Motor comercial: Precio_Cliente_Articulo,
    # Ultimas_Ventas_Cliente y TipoVenta_Cliente
    # ------------------------------------------------------------------

    def _cliente_info(self, codcli: int, subcli: int, codigo: str, default: str = "") -> str:
        row = self.db.fetch_one(
            "SELECT CLII_DESCRI FROM CLIENI WHERE CLII_NUMEMP=? AND CLII_CODCLI=? AND CLII_SUBCLI=? AND CLII_CODINF=?",
            (self.settings.empresa, codcli, subcli, codigo),
        )
        if not row or row.get("CLII_DESCRI") is None:
            return default
        return str(row["CLII_DESCRI"]).strip()

    def _pricing_client(self, codcli: int, subcli: int) -> dict[str, Any] | None:
        # Precio_Cliente_Articulo evita BUSQUEDA_CLIEN para el cliente caja.
        # PRECIO_VENTA fuerza CLI_TIPPRE='4' y CLI_PORAUM=0 en ese caso.
        if codcli == 99999 and subcli == 0:
            return {
                "CLI_NUMEMP": self.settings.empresa,
                "CLI_CODCLI": 99999,
                "CLI_SUBCLI": 0,
                "CLI_TIPPRE": "4",
                "CLI_PORAUM": Decimal("0"),
                "CLI_REGIVA": "N",
                "CLI_CANPMI": "",
                "CLI_ACEOFE": "",
            }
        row = self.db.fetch_one(
            "SELECT * FROM CLIEN WHERE CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
            (self.settings.empresa, codcli, subcli),
        )
        if not row:
            return None
        cli = normalize(row)
        cli["CLI_CANPMI"] = self._cliente_info(codcli, subcli, "CANPM")
        cli["CLI_ACEOFE"] = self._cliente_info(codcli, subcli, "ACEOF")
        return cli

    def _pricing_article(self, codart: str) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT * FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        return normalize(row) if row else None

    def _pricing_tax(self, tipiva: Any) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT TIV_PORIVA, TIV_PORREQ FROM TIPIVA WHERE TIV_NUMEMP=? AND TIV_TIPIVA=?",
            (self.settings.empresa, int(tipiva or 0)),
        )
        if not row:
            # BUSQUEDA_TIPIVA devuelve un registro inicializado a cero si no
            # encuentra el tipo. Reproducimos ese comportamiento.
            return {"TIV_PORIVA": Decimal("0"), "TIV_PORREQ": Decimal("0")}
        return normalize(row)

    def _client_article_price_row(self, codart: str, codcli: int) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT * FROM CLIART WHERE CLIA_NUMEMP=? AND CLIA_CODART=? AND CLIA_CODCLI=?",
            (self.settings.empresa, codart, codcli),
        )
        return normalize(row) if row else None

    def _active_sale_offer(self, codart: str, fecha: date) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT FIRST 1 * FROM DETOFER WHERE DOF_NUMEMP=? AND DOF_CODART=? "
            "AND DOF_FECINI<=? AND DOF_FECFIN>=? ORDER BY DOF_PVP",
            (self.settings.empresa, codart, fecha, fecha),
        )
        if not row:
            return None
        offer = normalize(row)
        header = self.db.fetch_one(
            "SELECT OFE_TIPOFE FROM OFERTAS WHERE OFE_NUMEMP=? AND OFE_EJERCI=? AND OFE_NUMOFE=?",
            (self.settings.empresa, offer.get("DOF_EJERCI"), offer.get("DOF_NUMOFE")),
        )
        offer["TIPO_OFERTA"] = str(header.get("OFE_TIPOFE") or "") if header else ""
        # ARTICULO_OFERTA anula PVP/PRECIO para ofertas tipo S.
        if offer["TIPO_OFERTA"] == "S":
            offer["DOF_PVP"] = Decimal("0")
            offer["DOF_PRECIO"] = Decimal("0")
        return offer

    def _client_table_price(self, codcli: int, subcli: int, codtab: int) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT * FROM CLITAB WHERE CLIB_NUMEMP=? AND CLIB_CODCLI=? AND CLIB_SUBCLI=? AND CLIB_CODTAB=?",
            (self.settings.empresa, codcli, subcli, codtab),
        )
        return normalize(row) if row else None

    def _family_discount(self, codcli: int, codfam: int, subfam: int) -> Decimal | None:
        # Mismo orden de precedencia que BUSQUEDA_DESCUENTO_FAMILIA:
        # familia+subfamilia -> familia+subfamilia 0 -> familia 0/subfamilia 0.
        candidates = [(codfam, subfam)]
        if subfam != 0:
            candidates.append((codfam, 0))
        if codfam != 0:
            candidates.append((0, 0))
        seen: set[tuple[int, int]] = set()
        for fam, sub in candidates:
            if (fam, sub) in seen:
                continue
            seen.add((fam, sub))
            row = self.db.fetch_one(
                "SELECT CLIF_DTO FROM CLIFAM WHERE CLIF_NUMEMP=? AND CLIF_CODCLI=? AND CLIF_CODFAM=? AND CLIF_SUBFAM=?",
                (self.settings.empresa, codcli, fam, sub),
            )
            if row:
                return dec(row.get("CLIF_DTO"))
        return None

    def _client_activity_price(self, codcli: int, subcli: int, section: str) -> str:
        row = self.db.fetch_one(
            "SELECT CLIC_ACTIVI FROM CLIACT WHERE CLIC_NUMEMP=? AND CLIC_CODCLI=? AND CLIC_SUBCLI=? AND CLIC_SECCIO=?",
            (self.settings.empresa, codcli, subcli, section),
        )
        return str(row.get("CLIC_ACTIVI") or "").strip() if row else ""

    def _salavert_activity_matches(self, codcli: int, subcli: int, codart: str) -> bool:
        actividad = self._cliente_info(codcli, subcli, "ACT")
        if not actividad:
            return False
        rows = self.db.fetch_all(
            "SELECT ARTI_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_CODINF=?",
            (self.settings.empresa, codart, "ACT"),
        )
        return any(str(row.get("ARTI_DESCRI") or "") == actividad for row in rows)

    def _article_is_canon(self, art: dict[str, Any]) -> bool:
        # Solo pueden ser canon los articulos de precio fijo (ART_TIPPRE no V/C).
        tippre_art = str(art.get("ART_TIPPRE") or "")
        if tippre_art[:1] in {"V", "C"}:
            return False
        row = self.db.fetch_one(
            "SELECT FIRST 1 ARTI_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_DESCRI=? AND ARTI_CODINF=?",
            (self.settings.empresa, str(art.get("ART_CODART") or ""), "CANON"),
        )
        return bool(row)

    def _change_price_currency(self, value: Decimal, source: str, target: str, price_type: str) -> Decimal:
        # CAMBIAR_PRECIO solo admite las monedas historicas P (pesetas) y E (euros).
        if source not in {"P", "E"}:
            return Decimal("0")
        article_service = FaroArticleService(self.db)
        if source == target:
            return article_service.round_price(value, source, price_type)
        if source == "P":
            return redondea(value / Decimal("166.386"), 2)
        if source == "E":
            return redondea(value * Decimal("166.386"), 0)
        return Decimal("-1")

    def _equivalent_discount(self, price_type: int, table_code: int, mode: str) -> Decimal:
        if table_code == 0 or mode not in {"2", "3"}:
            return Decimal("0")
        row = self.db.fetch_one(
            "SELECT TPR_PORAUM1, TPR_PORAUM2, TPR_PORAUM3, TPR_PORAUM4 FROM TABPREC "
            "WHERE TPR_NUMEMP=? AND TPR_CODTAB=?",
            (self.settings.empresa, table_code),
        )
        if not row:
            return Decimal("0")
        t = normalize(row)
        if mode == "2":
            key = {1: "TPR_PORAUM3", 2: "TPR_PORAUM2", 3: "TPR_PORAUM1"}.get(price_type)
            if not key:
                return Decimal("0")
            pct = dec(t.get(key)) / Decimal("100")
            return redondea((pct / (Decimal("1") + pct)) * Decimal("100"), 0)
        key = {1: "TPR_PORAUM1", 2: "TPR_PORAUM2", 3: "TPR_PORAUM3"}.get(price_type)
        if not key:
            return Decimal("0")
        ratio = (Decimal("1") + dec(t.get(key)) / 100) / (Decimal("1") + dec(t.get("TPR_PORAUM4")) / 100)
        return redondea((Decimal("1") - ratio) * Decimal("100"), 0)

    def _provider_unit_cost(self, art: dict[str, Any], field: str) -> Decimal:
        canpre = dec(art.get("ART_CANPRE"))
        if canpre > 0:
            return dec(art.get(field)) / canpre
        row = self.db.fetch_one(
            "SELECT FIRST 1 ARTP_CANCON, ARTP_CANVEN FROM ARTICULP "
            "WHERE ARTP_NUMEMP=? AND ARTP_CODART=? AND ARTP_CODPRO=? ORDER BY ARTP_REFPRO",
            (self.settings.empresa, art.get("ART_CODART"), int(art.get("ART_CODPRO") or 0)),
        )
        if not row:
            return Decimal("0")
        canven = dec(row.get("ARTP_CANVEN"))
        if canven == 0:
            return Decimal("0")
        return dec(art.get(field)) * dec(row.get("ARTP_CANCON")) / canven

    def _actualizar_precios_venta(self, dmv: dict[str, Any], art: dict[str, Any], cli: dict[str, Any]) -> dict[str, Any]:
        # Port directo de ACTUALIZAR_PRECIOS (LIBESP_U.pas). Se conserva la
        # semantica de tarifas 1..5/T, precio base 8 y coste 9.
        result = dict(dmv)
        article_service = FaroArticleService(self.db)
        preven = dec(result.get("DMV_PREVEN"))
        pvp = dec(result.get("DMV_PVP"))
        result["DMV_NUMOFE"] = 0
        result["DMV_EJEOFE"] = 0
        cantidad = abs(dec(result.get("DMV_CANTID")))
        tippre_text = str(result.get("DMV_TIPPRE") or "")
        try:
            tipo_precio = 0 if tippre_text == "T" else int(tippre_text or 0)
        except ValueError:
            tipo_precio = 0
        mode = self.parameter("TIPPRE", "")
        salavert = (mode == "2") or (mode == "3" and int(art.get("ART_TABPREC") or 0) != 0)
        if dec(art.get("ART_PREVEN4")) < Decimal("0.01") and tipo_precio == 4:
            result["DMV_TIPPRE"] = "5"
            tipo_precio = 5

        poraum = dec(cli.get("CLI_PORAUM"))
        canpmi_cli = str(cli.get("CLI_CANPMI") or "")
        canpmi_art = dec(art.get("ART_CANPMI"))
        currency = str(result.get("DMV_CODMON") or art.get("ART_CODMON") or "E")
        tabprec = int(art.get("ART_TABPREC") or 0)

        def sale_price(level: int) -> Decimal:
            return dec(art.get(f"ART_PREVEN{level}")) * (Decimal("1") + poraum / 100)

        def set_normal(level: int) -> None:
            nonlocal preven, pvp
            if salavert:
                preven = sale_price(4)
                result["DMV_DTO1"] = self._equivalent_discount(level, tabprec, mode)
            else:
                preven = article_service.round_price(sale_price(level), currency, "P")
            pvp = dec(art.get("ART_PVP")) * (Decimal("1") + poraum / 100)
            result["DMV_PREIVA"] = "N"

        if tipo_precio == 1:
            set_normal(1)
        elif tipo_precio == 2:
            set_normal(1 if canpmi_cli != "S" and canpmi_art > 0 and cantidad >= canpmi_art else 2)
        elif tipo_precio == 3:
            set_normal(2 if canpmi_cli != "S" and canpmi_art > 0 and cantidad >= canpmi_art else 3)
        elif tipo_precio == 4:
            minimum = (
                canpmi_cli != "S" and canpmi_art > 0 and cantidad >= canpmi_art
                and (str(result.get("DMV_TIPDOC") or "") != "T" or self.parameter("PREM", "") == "S")
            )
            if minimum:
                set_normal(3)
            else:
                if salavert:
                    result["DMV_DTO1"] = Decimal("0")
                pvp = dec(art.get("ART_PVP")) * (Decimal("1") + poraum / 100)
                pvp = article_service.round_price(pvp, currency, "I")
                poriva = dec(result.get("DMV_PORIVA"))
                preven = pvp / (Decimal("1") + poriva / 100) if poriva != Decimal("-100") else Decimal("0")
                preven = article_service.round_price(preven, currency, "P")
                result["DMV_PREIVA"] = "S"
        elif tipo_precio == 5:
            if canpmi_cli != "S" and canpmi_art > 0 and cantidad >= canpmi_art:
                set_normal(3)
            else:
                preven = article_service.round_price(sale_price(4), currency, "P")
            pvp = dec(art.get("ART_PVP")) * (Decimal("1") + poraum / 100)
            result["DMV_PREIVA"] = "N"
        elif tipo_precio == 8:
            precos = self._provider_unit_cost(art, "ART_PREBAS") * (Decimal("1") + poraum / 100)
            preven = article_service.round_price(precos, currency, "P")
            pvp = dec(art.get("ART_PVP"))
            result["DMV_PREIVA"] = "N"
        elif tipo_precio == 9:
            precos = self._provider_unit_cost(art, "ART_PRECOS") * (Decimal("1") + poraum / 100)
            preven = article_service.round_price(precos, currency, "P")
            pvp = dec(art.get("ART_PVP"))
            result["DMV_PREIVA"] = "N"
        else:  # tarifa (TIPPRE='T' => 0)
            if int(cli.get("CLI_CODCLI") or 0) != 99999 or int(cli.get("CLI_SUBCLI") or 0) != 0:
                special = self._client_article_price_row(str(art.get("ART_CODART") or ""), int(cli.get("CLI_CODCLI") or 0))
                if special and not (dec(special.get("CLIA_CANPRE")) > 1 and cantidad < dec(special.get("CLIA_CANPRE"))):
                    if dec(special.get("CLIA_PRECIO")) != 0:
                        result["DMV_PREVEN"] = dec(special.get("CLIA_PRECIO"))
                        result["DMV_PVP"] = dec(art.get("ART_PVP"))
                        result["DMV_PREIVA"] = "N"
                        result["DMV_DTO1"] = Decimal("0")
                        result["DMV_DTO2"] = Decimal("0")
                        return result
                    if dec(special.get("CLIA_DESCUE")) != 0:
                        result["DMV_PREVEN"] = dec(art.get("ART_PREVEN4"))
                        result["DMV_PVP"] = dec(art.get("ART_PVP"))
                        result["DMV_DTO1"] = dec(special.get("CLIA_DESCUE"))
                        result["DMV_DTO2"] = Decimal("0")
                        result["DMV_PREIVA"] = "N"
                        return result
            offer = self._active_sale_offer(str(art.get("ART_CODART") or ""), result.get("DMV_FECMOV") or date.today())
            if offer and not (dec(offer.get("DOF_CANPRE")) > 1 and cantidad < dec(offer.get("DOF_CANPRE"))):
                if dec(offer.get("DOF_PVP")) != 0:
                    result["DMV_PVP"] = dec(offer.get("DOF_PVP"))
                    result["DMV_CODMON"] = str(offer.get("DOF_CODMON") or currency)
                    poriva = dec(result.get("DMV_PORIVA"))
                    result["DMV_PREVEN"] = article_service.round_price(
                        result["DMV_PVP"] / (Decimal("1") + poriva / 100), result["DMV_CODMON"], "P"
                    )
                    result["DMV_DTO1"] = Decimal("0")
                    result["DMV_DTO2"] = Decimal("0")
                    result["DMV_PREIVA"] = "S"
                    result["DMV_NUMOFE"] = int(offer.get("DOF_NUMOFE") or 0)
                    result["DMV_EJEOFE"] = int(offer.get("DOF_EJERCI") or 0)
                    return result
                if dec(offer.get("DOF_PRECIO")) != 0 and int(cli.get("CLI_CODCLI") or 0) != 99999:
                    result["DMV_PREVEN"] = dec(offer.get("DOF_PRECIO"))
                    result["DMV_CODMON"] = str(offer.get("DOF_CODMON") or currency)
                    result["DMV_PVP"] = self._change_price_currency(
                        dec(art.get("ART_PVP")), str(art.get("ART_CODMON") or "E"), result["DMV_CODMON"], "I"
                    )
                    result["DMV_DTO1"] = Decimal("0")
                    result["DMV_DTO2"] = Decimal("0")
                    result["DMV_PREIVA"] = "N"
                    result["DMV_NUMOFE"] = int(offer.get("DOF_NUMOFE") or 0)
                    result["DMV_EJEOFE"] = int(offer.get("DOF_EJERCI") or 0)
                    return result
            if dec(art.get("ART_PRETAR")) != 0 and str(result.get("DMV_TIPPRE") or "") == "T":
                preven = dec(art.get("ART_PRETAR"))
                pvp = article_service.round_price(preven * (Decimal("1") + dec(result.get("DMV_PORIVA")) / 100), currency, "I")
            else:
                preven = dec(art.get("ART_PREVEN4"))
                pvp = dec(art.get("ART_PVP"))
            result["DMV_PREIVA"] = "N"

        result["DMV_PREVEN"] = preven
        result["DMV_PVP"] = pvp
        result["DMV_CODMON"] = str(art.get("ART_CODMON") or currency)
        return result

    def customer_article_price(self, codart: str, cantidad: Any, codcli: Any, subcli: Any) -> dict[str, Any]:
        # Port de Precio_Cliente_Articulo + PRECIO_VENTA.
        try:
            qty = dec(str(cantidad).replace(",", "."))
        except Exception:
            qty = Decimal("1")
        codcli_i, subcli_i = int(codcli), int(subcli)
        cli = self._pricing_client(codcli_i, subcli_i)
        if cli is None:
            return {"found": False, "reason": "cliente_no_encontrado", "datasnap_text": ""}
        if codcli_i == 99999 and subcli_i == 0:
            cli["CLI_TIPPRE"] = "4"
            cli["CLI_PORAUM"] = Decimal("0")

        art = self._pricing_article(codart)
        if art is None:
            return {"found": False, "reason": "articulo_no_encontrado", "datasnap_text": ""}
        tax = self._pricing_tax(art.get("ART_TIPIVA"))
        recargo = str(cli.get("CLI_REGIVA") or "") == "R" and not (codcli_i == 99999 and subcli_i == 0)
        dmv: dict[str, Any] = {
            "DMV_CODART": str(art.get("ART_CODART") or codart),
            "DMV_DESCRI": str(art.get("ART_DESCRI") or ""),
            "DMV_CANTID": qty,  # BUSQUEDA_ARTICUL de LIBESP fija ART.CANTIDAD=1
            "DMV_DTO1": Decimal("0"),
            "DMV_DTO2": Decimal("0"),
            "DMV_FECMOV": date.today(),
            "DMV_TIPPRE": "4",
            "DMV_CODMON": str(art.get("ART_CODMON") or "E"),
            "DMV_UNIMED": str(art.get("ART_UNIMED") or ""),
            "DMV_PVP": dec(art.get("ART_PVP")),
            "DMV_CANPRE": Decimal("1"),
            "DMV_PORIVA": dec(tax.get("TIV_PORIVA")),
            "DMV_PORREQ": dec(tax.get("TIV_PORREQ")) if recargo else Decimal("0"),
            "DMV_PREVEN": Decimal("0"),
            "DMV_PREIVA": "",
            "DMV_NUMOFE": 0,
            "DMV_EJEOFE": 0,
            "DMV_TIPDOC": "",  # no inicializado por el RPC; <> 'T' en Delphi
        }

        # 1) Precio especial de cliente.
        if codcli_i != 99999 or subcli_i != 0:
            special = self._client_article_price_row(dmv["DMV_CODART"], codcli_i)
            if special and not (dec(special.get("CLIA_CANPRE")) > 1 and qty < dec(special.get("CLIA_CANPRE"))):
                if str(special.get("CLIA_DESCRI") or "").strip():
                    dmv["DMV_DESCRI"] = str(special.get("CLIA_DESCRI") or "")
                if dec(special.get("CLIA_PRECIO")) != 0:
                    dmv["DMV_PREVEN"] = dec(special.get("CLIA_PRECIO"))
                    dmv["DMV_CODMON"] = str(special.get("CLIA_CODMON") or dmv["DMV_CODMON"])
                    dmv["DMV_PVP"] = self._change_price_currency(dec(art.get("ART_PVP")), str(art.get("ART_CODMON") or "E"), dmv["DMV_CODMON"], "I")
                    dmv["DMV_CANPRE"] = dec(special.get("CLIA_CANPRE"))
                    dmv["DMV_PREIVA"] = "N"
                    dmv["DMV_TIPPRE"] = "0"
                    dmv["DMV_DTO1"] = dec(special.get("CLIA_DESCUE"))
                    return self._customer_price_result(dmv)
                if dec(special.get("CLIA_DESCUE")) != 0:
                    base = dec(art.get("ART_PRETAR")) if dec(art.get("ART_PRETAR")) != 0 else dec(art.get("ART_PREVEN4"))
                    dmv["DMV_PREVEN"] = FaroArticleService(self.db).round_price(base, str(art.get("ART_CODMON") or "E"), "P")
                    dmv["DMV_DTO1"] = dec(special.get("CLIA_DESCUE"))
                    dmv["DMV_CODMON"] = str(art.get("ART_CODMON") or "E")
                    dmv["DMV_PVP"] = self._change_price_currency(dec(art.get("ART_PVP")), str(art.get("ART_CODMON") or "E"), dmv["DMV_CODMON"], "I")
                    dmv["DMV_CANPRE"] = Decimal("1")
                    dmv["DMV_PREIVA"] = "N"
                    dmv["DMV_TIPPRE"] = "0"
                    return self._customer_price_result(dmv)

        # 2) Canon.
        if self._article_is_canon(art):
            dmv["DMV_PREVEN"] = dec(art.get("ART_PVP"))
            dmv["DMV_CODMON"] = str(art.get("ART_CODMON") or "E")
            dmv["DMV_PVP"] = Decimal("0")
            dmv["DMV_CANPRE"] = Decimal("1")
            dmv["DMV_PREIVA"] = "N"
            dmv["DMV_TIPPRE"] = "0"
            return self._customer_price_result(dmv)

        # 3) Oferta activa.
        offer = self._active_sale_offer(dmv["DMV_CODART"], dmv["DMV_FECMOV"])
        if offer:
            eligible = not (dec(offer.get("DOF_CANPRE")) > 1 and qty < dec(offer.get("DOF_CANPRE")))
            eligible = eligible and str(cli.get("CLI_ACEOFE") or "") != "N"
            eligible = eligible and not (str(offer.get("TIPO_OFERTA") or "") == "R" and codcli_i == 99999)
            eligible = eligible and str(offer.get("TIPO_OFERTA") or "") != "P"
            if eligible:
                if dec(offer.get("DOF_PVP")) != 0:
                    dmv["DMV_PVP"] = dec(offer.get("DOF_PVP"))
                    dmv["DMV_CODMON"] = str(offer.get("DOF_CODMON") or dmv["DMV_CODMON"])
                    dmv["DMV_PREVEN"] = FaroArticleService(self.db).round_price(
                        dmv["DMV_PVP"] / (Decimal("1") + dec(dmv["DMV_PORIVA"]) / 100), dmv["DMV_CODMON"], "P"
                    )
                    dmv["DMV_TIPPRE"] = "0"
                    dmv["DMV_PREIVA"] = "S" if codcli_i == 99999 else "N"
                    dmv["DMV_NUMOFE"] = int(offer.get("DOF_NUMOFE") or 0)
                    dmv["DMV_EJEOFE"] = int(offer.get("DOF_EJERCI") or 0)
                    dmv["DMV_DTO1"] = Decimal("0")
                    return self._customer_price_result(dmv)
                if dec(offer.get("DOF_PRECIO")) != 0 and codcli_i != 99999:
                    dmv["DMV_PREVEN"] = dec(offer.get("DOF_PRECIO"))
                    dmv["DMV_CODMON"] = str(offer.get("DOF_CODMON") or dmv["DMV_CODMON"])
                    dmv["DMV_PVP"] = self._change_price_currency(dec(art.get("ART_PVP")), str(art.get("ART_CODMON") or "E"), dmv["DMV_CODMON"], "I")
                    dmv["DMV_TIPPRE"] = "0"
                    dmv["DMV_PREIVA"] = "N"
                    dmv["DMV_NUMOFE"] = int(offer.get("DOF_NUMOFE") or 0)
                    dmv["DMV_EJEOFE"] = int(offer.get("DOF_EJERCI") or 0)
                    dmv["DMV_DTO1"] = Decimal("0")
                    return self._customer_price_result(dmv)
                dmv["DMV_NUMOFE"] = int(offer.get("DOF_NUMOFE") or 0)
                dmv["DMV_EJEOFE"] = int(offer.get("DOF_EJERCI") or 0)

        # 4) Tabla especifica cliente/articulo.
        tabprec = int(art.get("ART_TABPREC") or 0)
        if tabprec > 0 and (codcli_i != 99999 or subcli_i != 0):
            clitab = self._client_table_price(codcli_i, subcli_i, tabprec)
            if clitab:
                dmv["DMV_TIPPRE"] = str(clitab.get("CLIB_TARIFA") or "")
                dmv["DMV_DTO1"] = dec(clitab.get("CLIB_DTO"))
                return self._customer_price_result(self._actualizar_precios_venta(dmv, art, cli))

        # 5) Descuento por familia del cliente.
        if codcli_i != 99999 or subcli_i != 0:
            dto = self._family_discount(codcli_i, int(art.get("ART_CODFAM") or 0), int(art.get("ART_SUBFAM") or 0))
            if dto is not None:
                dmv["DMV_DTO1"] = dto
                if str(cli.get("CLI_TIPPRE") or "") == "T":
                    if dec(art.get("ART_PRETAR")) != 0:
                        dmv["DMV_TIPPRE"] = "T"
                        return self._customer_price_result(self._actualizar_precios_venta(dmv, art, cli))
                    # En Delphi, tarifa T sin ART_PRETAR no entra en la rama
                    # alternativa de acumulacion: se descarta el DTO y continua.
                    dmv["DMV_DTO1"] = Decimal("0")
                else:
                    accumulates = self._cliente_info(codcli_i, subcli_i, "ACDTO") == "S"
                    if accumulates:
                        dmv["DMV_TIPPRE"] = str(cli.get("CLI_TIPPRE") or "")
                        if self.parameter("TIPPRE", "") == "3":
                            dmv["DMV_DTO2"] = dmv["DMV_DTO1"]
                            dmv["DMV_DTO1"] = Decimal("0")
                    else:
                        dmv["DMV_TIPPRE"] = "5"
                        art = dict(art)
                        art["ART_CANPMI"] = Decimal("0")
                    return self._customer_price_result(self._actualizar_precios_venta(dmv, art, cli))
            dmv["DMV_DTO1"] = Decimal("0")

        # 6) Herencia de descuentos por grupo.
        group = self._cliente_info(codcli_i, subcli_i, "GRUPO")
        if group:
            try:
                group_cli = int(group)
            except ValueError:
                group_cli = 0
            if group_cli:
                dto = self._family_discount(group_cli, int(art.get("ART_CODFAM") or 0), int(art.get("ART_SUBFAM") or 0))
                if dto is not None:
                    dmv["DMV_DTO1"] = dto
                    dmv["DMV_TIPPRE"] = "5"
                    art = dict(art)
                    art["ART_CANPMI"] = Decimal("0")
                    return self._customer_price_result(self._actualizar_precios_venta(dmv, art, cli))
                dmv["DMV_DTO1"] = Decimal("0")

        # 7) Actividad por seccion o tarifa de cabecera.
        if codcli_i != 99999 or subcli_i != 0:
            dmv["DMV_TIPPRE"] = self._client_activity_price(codcli_i, subcli_i, str(art.get("ART_SECCIO") or ""))
        if not str(dmv.get("DMV_TIPPRE") or ""):
            dmv["DMV_TIPPRE"] = str(cli.get("CLI_TIPPRE") or "")
        if self.parameter("TIPPRE", "") == "2" and self._salavert_activity_matches(codcli_i, subcli_i, dmv["DMV_CODART"]):
            dmv["DMV_TIPPRE"] = "1"
        return self._customer_price_result(self._actualizar_precios_venta(dmv, art, cli))

    def _customer_price_result(self, dmv: dict[str, Any]) -> dict[str, Any]:
        fields = [
            ("preven", "DMV_PREVEN"), ("dto1", "DMV_DTO1"), ("dto2", "DMV_DTO2"),
            ("poriva", "DMV_PORIVA"), ("porreq", "DMV_PORREQ"), ("tippre", "DMV_TIPPRE"),
            ("unimed", "DMV_UNIMED"), ("preiva", "DMV_PREIVA"), ("pvp", "DMV_PVP"),
            ("ejeofe", "DMV_EJEOFE"), ("numofe", "DMV_NUMOFE"),
        ]
        result = {name: normalize(dmv.get(key)) for name, key in fields}
        result.update({"found": True, "codart": dmv.get("DMV_CODART"), "cantidad": normalize(dmv.get("DMV_CANTID"))})
        result["datasnap_text"] = "#".join(serialize_text_value(dmv.get(key)) for _, key in fields)
        return result

    def last_customer_sales(self, codcli: Any, subcli: Any) -> dict[str, Any]:
        # Port de Ultimas_Ventas_Cliente. El Delphi permite 101 articulos
        # distintos por el `I := I + 1; IF I > 100 THEN Break`.
        codcli_i, subcli_i = int(codcli), int(subcli)
        rows = self.db.fetch_all(
            "SELECT DMV_CODART, DMV_DESCRI, DMV_UNIMED, DMV_PREVEN, DMV_PVP, DMV_FECMOV "
            "FROM DETMOV INNER JOIN CABDOCV ON ("
            "CBV_NUMEMP=DMV_NUMEMP AND CBV_CENTRO=DMV_CENTRO AND CBV_TIPDOC=DMV_TIPDOC "
            "AND CBV_TIPAC=DMV_TIPAC AND CBV_EJERCI=DMV_EJERCI AND CBV_SERIE=DMV_SERIE "
            "AND CBV_NUMDOC=DMV_NUMDOC AND CBV_CODCLI=? AND CBV_SUBCLI=?) "
            "WHERE DMV_NUMEMP=? AND DMV_SIGNO=? ORDER BY DMV_FECMOV DESC",
            (codcli_i, subcli_i, self.settings.empresa, "1"),
        )
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        parts: list[str] = []
        for row in rows:
            codart = str(row.get("DMV_CODART") or "")
            if codart in seen:
                continue
            seen.add(codart)
            item = {
                "codart": codart,
                "descri": clean_text_value(row.get("DMV_DESCRI")),
                "unimed": row.get("DMV_UNIMED"),
                "preven": normalize(row.get("DMV_PREVEN")),
                "pvp": normalize(row.get("DMV_PVP")),
                "fecha": normalize(row.get("DMV_FECMOV")),
            }
            items.append(item)
            parts.append("|".join(serialize_text_value(item[k]) for k in ["codart", "descri", "unimed", "preven", "pvp"]))
            if len(items) > 100:
                break
        return {"codcli": codcli_i, "subcli": subcli_i, "count": len(items), "items": items, "datasnap_text": "#".join(parts) + ("#" if parts else "")}

    def customer_sale_type(self, tipdoc: str, codcli: Any, subcli: Any) -> dict[str, Any]:
        # Port de TipoVenta_Cliente. El resultado Delphi vacio significa OK.
        tipdoc = str(tipdoc or "").upper()
        codcli_i, subcli_i = int(codcli), int(subcli)
        message = ""
        if tipdoc != "T" and codcli_i == 99999 and subcli_i == 0:
            message = "Debe especificar el cliente"
        elif tipdoc == "A":
            if codcli_i == 99999:
                message = "No se pueden hacer albaranes a los clientes caja"
            else:
                row = self.db.fetch_one(
                    "SELECT CLI_RIESGO FROM CLIEN WHERE CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
                    (self.settings.empresa, codcli_i, subcli_i),
                )
                riesgo = dec(row.get("CLI_RIESGO")) if row and row.get("CLI_RIESGO") is not None else Decimal("0")
                if riesgo == Decimal("-1"):
                    message = "No se pueden hacer albaranes a los clientes sin Riesgo"
        return {
            "tipdoc": tipdoc,
            "codcli": codcli_i,
            "subcli": subcli_i,
            "allowed": message == "",
            "message": message,
            "datasnap_text": message,
        }

    # ------------------------------------------------------------------
    # Fase 2B - Estado, entrada y retirada de pedidos
    # (Grabar_Situacion_Pedido, Pedidos_Cliente_Entrada,
    #  Grabar_Retirado_Referencia)
    # ------------------------------------------------------------------

    def save_order_status(
        self, situac: str, centro: Any, tipdoc: str, ejerci: Any, serie: str, numdoc: Any
    ) -> dict[str, Any]:
        """Replica Grabar_Situacion_Pedido con SQL parametrizado.

        El Delphi limita la actualizacion a TIPAC='0' y no modifica FECMOD ni
        USUMOD. Se mantiene esa semantica. El RPC original devuelve MSGERR
        (cadena vacia cuando no hay error); aqui se devuelve ademas una
        respuesta estructurada y ``datasnap_text`` conserva ese contrato.
        """
        centro_i = int(centro)
        ejerci_i = int(ejerci)
        numdoc_i = int(numdoc)
        situac_s = str(situac or "")
        tipdoc_s = str(tipdoc or "").strip()
        serie_s = str(serie or "").strip()
        try:
            self.db.execute(
                "UPDATE CABDOCV SET CBV_INDEDI=? WHERE CBV_NUMEMP=? AND CBV_CENTRO=? "
                "AND CBV_TIPDOC=? AND CBV_TIPAC='0' AND CBV_EJERCI=? AND CBV_SERIE=? AND CBV_NUMDOC=?",
                (situac_s, self.settings.empresa, centro_i, tipdoc_s, ejerci_i, serie_s, numdoc_i),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {
            "centro": centro_i,
            "tipdoc": tipdoc_s,
            "tipac": "0",
            "ejerci": ejerci_i,
            "serie": serie_s,
            "numdoc": numdoc_i,
            "situacion": situac_s,
            "datasnap_text": "",
        }

    @staticmethod
    def _format_order_date(value: Any) -> str:
        """Aproxima DateToStr del servidor Delphi (despliegue espanol)."""
        if value is None:
            return ""
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, date):
            return value.strftime("%d/%m/%Y")
        text = str(value)
        try:
            parsed = date.fromisoformat(text[:10])
            return parsed.strftime("%d/%m/%Y")
        except Exception:
            return text

    @staticmethod
    def _format_order_amount(value: Any) -> str:
        """Aproxima FormatFloat('#,#0.00') con formato regional espanol."""
        try:
            text = f"{dec(value):,.2f}"
            return text.replace(",", "_").replace(".", ",").replace("_", ".")
        except Exception:
            return "0,00"

    def incoming_order_customer_orders(
        self, centro: Any, ejerci: Any, serie: str, numdoc: Any
    ) -> dict[str, Any]:
        """Replica Pedidos_Cliente_Entrada.

        A partir de los articulos presentes en DETMOVM del documento de entrada
        recibido, localiza pedidos de cliente (DETMOV.DMV_TIPDOC='P') que
        contengan cualquiera de esos articulos.

        Rarezas deliberadamente conservadas del Delphi:
        - ``centro`` solo se usa para localizar DETMOVM.
        - La busqueda de pedidos usa ``R_PARAMETROS.CENTRO``; en Python,
          ``self.settings.centro``.
        - La deduplicacion se hace por ``EJERCI-SERIE-NUMDOC`` y no por la
          clave completa del documento.
        - El orden final es ejercicio + numero, ascendente.
        """
        centro_entrada = int(centro)
        ejerci_i = int(ejerci)
        numdoc_i = int(numdoc)
        serie_s = str(serie or "").strip()
        empresa = self.settings.empresa
        centro_pedidos = self.settings.centro

        movimientos = self.db.fetch_all(
            "SELECT DMM_CODART FROM DETMOVM WHERE DMM_NUMEMP=? AND DMM_CENTRO=? "
            "AND DMM_EJERCI=? AND DMM_SERIE=? AND DMM_NUMDOC=?",
            (empresa, centro_entrada, ejerci_i, serie_s, numdoc_i),
        )

        pedidos_unicos: dict[str, dict[str, Any]] = {}
        articulos: list[str] = []
        for mov in movimientos:
            codart = str((mov or {}).get("DMM_CODART") or "").strip()
            if not codart:
                continue
            articulos.append(codart)
            lineas = self.db.fetch_all(
                "SELECT DMV_CENTRO, DMV_TIPDOC, DMV_TIPAC, DMV_EJERCI, DMV_SERIE, DMV_NUMDOC "
                "FROM DETMOV WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPDOC='P' AND DMV_CODART=?",
                (empresa, centro_pedidos, codart),
            )
            for lin in lineas:
                lin = normalize(lin)
                codigo = f"{lin.get('DMV_EJERCI')}-{lin.get('DMV_SERIE')}-{lin.get('DMV_NUMDOC')}"
                if codigo not in pedidos_unicos:
                    pedidos_unicos[codigo] = {
                        "centro": int(lin.get("DMV_CENTRO") or centro_pedidos),
                        "tipdoc": str(lin.get("DMV_TIPDOC") or ""),
                        "tipac": str(lin.get("DMV_TIPAC") or ""),
                        "ejerci": int(lin.get("DMV_EJERCI") or 0),
                        "serie": str(lin.get("DMV_SERIE") or ""),
                        "numdoc": int(lin.get("DMV_NUMDOC") or 0),
                    }

        # TFDMemTable.IndexFieldNames := 'CBV_EJERCI;CBV_NUMDOC'
        claves = sorted(
            pedidos_unicos.values(),
            key=lambda p: (int(p.get("ejerci") or 0), int(p.get("numdoc") or 0)),
        )
        items: list[dict[str, Any]] = []
        partes: list[str] = []
        for pedido in claves:
            # El original vuelve a forzar R_PARAMETROS.CENTRO aqui en vez
            # de utilizar el CBV_CENTRO guardado en T_PEDIDOS.
            cbv = self._busqueda_cabdocv(
                centro_pedidos,
                pedido["tipac"],
                pedido["tipdoc"],
                pedido["ejerci"],
                pedido["serie"],
                pedido["numdoc"],
            )
            if not cbv:
                # BUSQUEDA_CABDOCV devolveria un registro inicializado a
                # cero; en la practica el DETMOV deberia tener cabecera. En
                # MCP es mas seguro no inventar una cabecera inexistente.
                continue
            item = {
                "ejerci": cbv.get("CBV_EJERCI"),
                "serie": str(cbv.get("CBV_SERIE") or ""),
                "numdoc": cbv.get("CBV_NUMDOC"),
                "codcli": cbv.get("CBV_CODCLI"),
                "subcli": cbv.get("CBV_SUBCLI"),
                "nomcli": str(cbv.get("CBV_NOMCLI") or ""),
                "fecha": normalize(cbv.get("CBV_FECHA")),
                "totald": normalize(cbv.get("CBV_TOTALD")),
                "indedi": str(cbv.get("CBV_INDEDI") or ""),
            }
            items.append(item)
            partes.append(
                "|".join(
                    [
                        serialize_text_value(item["ejerci"]),
                        serialize_text_value(item["serie"]),
                        serialize_text_value(item["numdoc"]),
                        serialize_text_value(item["codcli"]),
                        serialize_text_value(item["subcli"]),
                        serialize_text_value(item["nomcli"]),
                        self._format_order_date(cbv.get("CBV_FECHA")),
                        self._format_order_amount(cbv.get("CBV_TOTALD")),
                        serialize_text_value(item["indedi"]),
                    ]
                )
            )

        return {
            "entrada": {
                "centro": centro_entrada,
                "ejerci": ejerci_i,
                "serie": serie_s,
                "numdoc": numdoc_i,
            },
            "centro_pedidos": centro_pedidos,
            "articulos_entrada": articulos,
            "count": len(items),
            "items": items,
            "datasnap_text": "#".join(partes) + ("#" if partes else ""),
        }

    def save_order_withdrawal_reference(
        self, documento: str, retirado: str, referencia: str
    ) -> dict[str, Any]:
        """Replica Grabar_Retirado_Referencia.

        ``DOCUMENTO`` conserva el formato del RPC original:
        ``CENTRO-TIPDOC-EJERCI-SERIE-NUMDOC``. TIPAC se fuerza a ``0``.
        """
        raw = str(documento or "")
        parts = raw.split("-")
        if len(parts) != 5:
            raise FaroError(
                "DOCUMENTO invalido. Se esperaba CENTRO-TIPDOC-EJERCI-SERIE-NUMDOC, "
                f"recibido: {raw!r}"
            )
        centro_s, tipdoc_s, ejerci_s, serie_s, numdoc_s = parts
        try:
            centro_i = int(centro_s)
            ejerci_i = int(ejerci_s)
            numdoc_i = int(numdoc_s)
        except ValueError as exc:
            raise FaroError(f"DOCUMENTO invalido: {raw!r}") from exc

        retirado_s = str(retirado or "")
        referencia_s = str(referencia or "")
        tipdoc_s = tipdoc_s.strip()
        serie_s = serie_s.strip()
        try:
            self.db.execute(
                "UPDATE CABDOCV SET CBV_RETIRA=?, CBV_REFCLI=? WHERE CBV_NUMEMP=? AND CBV_CENTRO=? "
                "AND CBV_TIPDOC=? AND CBV_TIPAC='0' AND CBV_EJERCI=? AND CBV_SERIE=? AND CBV_NUMDOC=?",
                (
                    retirado_s,
                    referencia_s,
                    self.settings.empresa,
                    centro_i,
                    tipdoc_s,
                    ejerci_i,
                    serie_s,
                    numdoc_i,
                ),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {
            "documento": raw,
            "centro": centro_i,
            "tipdoc": tipdoc_s,
            "tipac": "0",
            "ejerci": ejerci_i,
            "serie": serie_s,
            "numdoc": numdoc_i,
            "retirado": retirado_s,
            "referencia": referencia_s,
            "datasnap_text": "",
        }

    # ------------------------------------------------------------------
    # Fase 2C - Ventas abiertas / caja
    # (BLOQUEO_VENCAJ, Grabar_Venta, Borrar_Venta)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_vencaj_key(venta: str) -> tuple[int, int]:
        """Parsea la clave historica ``EJERCI-NUMDOC`` usada por VENCAJ."""
        raw = str(venta or "").strip()
        parts = raw.split("-")
        if len(parts) != 2:
            raise FaroError(f"VENTA invalida. Se esperaba EJERCI-NUMDOC, recibido: {raw!r}")
        try:
            return int(parts[0]), int(parts[1])
        except ValueError as exc:
            raise FaroError(f"VENTA invalida. Se esperaba EJERCI-NUMDOC, recibido: {raw!r}") from exc

    def _vencaj_semaphore_code(self, ejerci: int, numdoc: int) -> str:
        return f"{self.settings.empresa}\\{int(ejerci)}\\{int(numdoc)}"

    def _vencaj_is_locked(self, codigo: str) -> bool:
        row = self.db.fetch_one(
            "SELECT FIRST 1 SEM_CODIGO FROM SEMAFORO WHERE SEM_TABLA=? AND SEM_CODIGO=?",
            ("VENCAJ", codigo),
        )
        return bool(row)

    def _probe_vencaj_lock(self, codigo: str, *, commit: bool) -> bool:
        """Replica el semaforo efimero usado por BLOQUEO_VENCAJ.

        El Delphi intenta insertar ``('VENCAJ', codigo)`` y lo borra de
        inmediato. Si la fila ya existe, la venta se considera bloqueada.
        Aqui hacemos un SELECT previo para evitar usar una excepcion de clave
        duplicada como flujo normal de control, pero mantenemos el mismo
        contrato observable.
        """
        if self._vencaj_is_locked(codigo):
            return False
        try:
            self.db.execute(
                "INSERT INTO SEMAFORO (SEM_TABLA, SEM_CODIGO) VALUES (?, ?)",
                ("VENCAJ", codigo),
            )
            self.db.execute(
                "DELETE FROM SEMAFORO WHERE SEM_TABLA=? AND SEM_CODIGO=?",
                ("VENCAJ", codigo),
            )
            if commit:
                self.db.commit()
            return True
        except Exception:
            if commit:
                self.db.rollback()
                return False
            raise

    def probe_open_sale_lock(self, codigo: str) -> dict[str, Any]:
        """Migra ``BLOQUEO_VENCAJ``.

        Devuelve ``datasnap_text='True'`` cuando el semaforo se puede adquirir
        y liberar, y ``'False'`` si la venta ya esta bloqueada.
        """
        code = str(codigo or "")
        available = self._probe_vencaj_lock(code, commit=True)
        return {
            "codigo": code,
            "available": available,
            "blocked": not available,
            "datasnap_text": "True" if available else "False",
        }

    def _next_vencaj_numero(self, ejerci: int) -> int:
        row = self.db.fetch_one(
            "SELECT MAX(CBV_NUMDOC) AS CBV_NUMDOC FROM VENCAJ WHERE CBV_NUMEMP=? AND CBV_EJERCI=?",
            (self.settings.empresa, int(ejerci)),
        )
        current = row.get("CBV_NUMDOC") if row else None
        numero = int(current) + 1 if current is not None else 1
        if numero > 999999:
            raise FaroError("Error en la numeracion de VENCAJ")
        return numero

    def _insert_vencaj_row(self, cbv: dict[str, Any]) -> None:
        columns = [
            "CBV_NUMEMP", "CBV_EJERCI", "CBV_NUMDOC", "CBV_CAJA", "CBV_USUMOD", "CBV_TIPDOC",
            "CBV_TIPAC", "CBV_SERIE", "CBV_FECHA", "CBV_FECHAE", "CBV_CODCLI", "CBV_SUBCLI",
            "CBV_CODREP", "CBV_COMREP", "CBV_NOMCLI", "CBV_CIF", "CBV_DOMCLI", "CBV_CODPOS",
            "CBV_POBLAC", "CBV_CODPAG", "CBV_FORENV", "CBV_PORDTO", "CBV_IMPPOR", "CBV_BASIMP1",
            "CBV_PORIVA1", "CBV_PORREQ1", "CBV_BASIMP2", "CBV_PORIVA2", "CBV_PORREQ2",
            "CBV_BASIMP3", "CBV_PORIVA3", "CBV_PORREQ3", "CBV_BASIMP4", "CBV_PORIVA4",
            "CBV_PORREQ4", "CBV_TOTALS", "CBV_TOTALD", "CBV_IMPCOB", "CBV_CODMON", "CBV_FORCOB",
            "CBV_NUMTAR", "CBV_TIPVEN", "CBV_SITUAC", "CBV_OBSERV", "CBV_FECMOD", "CBV_REFCLI",
            "CBV_RETIRA", "CBV_CODTAR",
        ]
        placeholders = ",".join(["?"] * len(columns))
        self.db.execute(
            f"INSERT INTO VENCAJ ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(cbv.get(col) for col in columns),
        )

    def _update_vencaj_totals(self, cbv: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE VENCAJ SET CBV_BASIMP1=?, CBV_PORIVA1=?, CBV_PORREQ1=?, "
            "CBV_BASIMP2=?, CBV_PORIVA2=?, CBV_PORREQ2=?, CBV_BASIMP3=?, CBV_PORIVA3=?, "
            "CBV_PORREQ3=?, CBV_BASIMP4=?, CBV_PORIVA4=?, CBV_PORREQ4=?, CBV_TOTALS=?, CBV_TOTALD=? "
            "WHERE CBV_NUMEMP=? AND CBV_EJERCI=? AND CBV_NUMDOC=?",
            (
                cbv["CBV_BASIMP1"], cbv["CBV_PORIVA1"], cbv["CBV_PORREQ1"],
                cbv["CBV_BASIMP2"], cbv["CBV_PORIVA2"], cbv["CBV_PORREQ2"],
                cbv["CBV_BASIMP3"], cbv["CBV_PORIVA3"], cbv["CBV_PORREQ3"],
                cbv["CBV_BASIMP4"], cbv["CBV_PORIVA4"], cbv["CBV_PORREQ4"],
                cbv["CBV_TOTALS"], cbv["CBV_TOTALD"],
                cbv["CBV_NUMEMP"], cbv["CBV_EJERCI"], cbv["CBV_NUMDOC"],
            ),
        )

    def _insert_vencur_row(self, line: dict[str, Any]) -> None:
        columns = [
            "DMV_NUMEMP", "DMV_EJERCI", "DMV_NUMDOC", "DMV_NUMLIN", "DMV_CAJA", "DMV_USUAR",
            "DMV_TIPLIN", "DMV_FECMOV", "DMV_CODART", "DMV_DESCRI", "DMV_CODMON", "DMV_TIPPRE",
            "DMV_PREVEN", "DMV_PORIVA", "DMV_PORREQ", "DMV_PVP", "DMV_CANTID", "DMV_CANPRE",
            "DMV_UNIMED", "DMV_DTO1", "DMV_DTO2", "DMV_VALLIN", "DMV_VALLINS", "DMV_IMPDTO",
            "DMV_EJEOFE", "DMV_NUMOFE", "DMV_EJERCIO", "DMV_TIPDOCO", "DMV_SERIEO", "DMV_NUMDOCO",
            "DMV_NUMLINO", "DMV_PREIVA", "DMV_NSERIE",
        ]
        table_columns = self.db.table_columns("VENCUR") if hasattr(self.db, "table_columns") else set()
        if table_columns:
            columns = [column for column in columns if column in table_columns]
        placeholders = ",".join(["?"] * len(columns))
        self.db.execute(
            f"INSERT INTO VENCUR ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(line.get(col) for col in columns),
        )

    def _next_vencur_line(self, ejerci: int, numdoc: int) -> int:
        row = self.db.fetch_one(
            "SELECT MAX(DMV_NUMLIN) AS DMV_NUMLIN FROM VENCUR WHERE DMV_NUMEMP=? AND DMV_EJERCI=? "
            "AND DMV_NUMDOC=? AND DMV_NUMLIN<>999",
            (self.settings.empresa, int(ejerci), int(numdoc)),
        )
        current = row.get("DMV_NUMLIN") if row else None
        numero = int(current) + 1 if current is not None else 1
        # Replica la condicion literal del Delphi (9999 -> 1000), aunque
        # parece un typo historico y no 999 -> 1000.
        if numero == 9999:
            numero = 1000
        return numero

    def _valorar_vencur_line(self, line: dict[str, Any]) -> dict[str, Any]:
        """Replica VALORAR_DETMOV para una linea VENCUR."""
        line = dict(line)
        if str(line.get("DMV_TIPLIN") or "") == "C":
            return line

        moneda_actual = "E"  # MONEDA_ACTUAL del Delphi devuelve siempre 'E'.
        moneda = str(line.get("DMV_CODMON") or moneda_actual)
        line["DMV_CANTID"] = redondea(dec(line.get("DMV_CANTID")), 2)
        if moneda != moneda_actual:
            line["DMV_PVP"] = self._change_price_currency(dec(line.get("DMV_PVP")), moneda, moneda_actual, "I")
            line["DMV_PREVEN"] = self._change_price_currency(dec(line.get("DMV_PREVEN")), moneda, moneda_actual, "P")
            line["DMV_CODMON"] = moneda_actual
            moneda = moneda_actual

        if str(line.get("DMV_TIPLIN") or "") == "X":
            line["DMV_TIPPRE"] = "0"

        dto1 = dec(line.get("DMV_DTO1"))
        dto2 = dec(line.get("DMV_DTO2"))
        poriva = dec(line.get("DMV_PORIVA"))
        porreq = dec(line.get("DMV_PORREQ"))
        cantidad = dec(line.get("DMV_CANTID"))
        if str(line.get("DMV_PREIVA") or "") == "S" and porreq == 0:
            pvp = self.round_price_order(dec(line.get("DMV_PVP")), moneda, "I")
            line["DMV_PVP"] = pvp
            vallin = cantidad * pvp * (1 - dto1 / 100) * (1 - dto2 / 100)
            vallin = self.round_price_order(vallin, moneda, "L")
            line["DMV_VALLIN"] = vallin
            divisor = Decimal("1") + poriva / 100
            line["DMV_VALLINS"] = vallin / divisor if divisor != 0 else Decimal("0")
        else:
            preven = self.round_price_order(dec(line.get("DMV_PREVEN")), moneda, "P")
            line["DMV_PREVEN"] = preven
            vallins = preven * cantidad * (1 - dto1 / 100) * (1 - dto2 / 100)
            vallins = self.round_price_order(vallins, moneda, "L")
            line["DMV_VALLINS"] = vallins
            vallin = vallins * (1 + poriva / 100 + porreq / 100)
            line["DMV_VALLIN"] = self.round_price_order(vallin, moneda, "L")
        return line

    def _sale_line_base(self, cbv: dict[str, Any], numlin: int) -> dict[str, Any]:
        return {
            "DMV_NUMEMP": cbv["CBV_NUMEMP"], "DMV_EJERCI": cbv["CBV_EJERCI"], "DMV_NUMDOC": cbv["CBV_NUMDOC"],
            "DMV_NUMLIN": int(numlin), "DMV_CAJA": cbv["CBV_CAJA"], "DMV_USUAR": cbv["CBV_USUMOD"],
            "DMV_TIPLIN": "D", "DMV_FECMOV": cbv["CBV_FECHA"], "DMV_CODART": "", "DMV_DESCRI": ".",
            "DMV_CODMON": cbv["CBV_CODMON"], "DMV_TIPPRE": "", "DMV_PREVEN": Decimal("0"),
            "DMV_PORIVA": Decimal("0"), "DMV_PORREQ": Decimal("0"), "DMV_PVP": Decimal("0"),
            "DMV_CANTID": Decimal("0"), "DMV_CANPRE": Decimal("1"), "DMV_UNIMED": "", "DMV_DTO1": Decimal("0"),
            "DMV_DTO2": Decimal("0"), "DMV_VALLIN": Decimal("0"), "DMV_VALLINS": Decimal("0"),
            "DMV_IMPDTO": Decimal("0"), "DMV_EJEOFE": 0, "DMV_NUMOFE": 0, "DMV_EJERCIO": 0,
            "DMV_TIPDOCO": "", "DMV_SERIEO": "", "DMV_NUMDOCO": 0, "DMV_NUMLINO": 0,
            "DMV_PREIVA": "", "DMV_NSERIE": "",
        }

    def _parse_sale_line(self, cbv: dict[str, Any], numlin: int, raw: str) -> dict[str, Any]:
        fields = str(raw or "").split("|")
        if len(fields) < 14:
            fields += [""] * (14 - len(fields))
        codart, descri = fields[0].strip(), fields[1].strip()
        line = self._sale_line_base(cbv, numlin)
        line["DMV_CODART"] = codart
        line["DMV_DESCRI"] = descri
        line["DMV_CANTID"] = self._parse_decimal_pedido(fields[2], "CANTID")
        preven = self._parse_decimal_pedido(fields[3], "PREVEN")
        # Bug historico preservado: el Delphi decide C/X antes de copiar PREVEN
        # al registro y DMV_PREVEN acaba de inicializarse a 0. Por tanto, toda
        # linea sin CODART se clasifica siempre como comentario ('C'), incluso
        # aunque el PREVEN recibido sea distinto de cero.
        if codart == "":
            line["DMV_TIPLIN"] = "C"
        line["DMV_DTO1"] = self._parse_decimal_pedido(fields[4], "DTO1")
        line["DMV_DTO2"] = self._parse_decimal_pedido(fields[5], "DTO2")
        line["DMV_PORIVA"] = self._parse_decimal_pedido(fields[6], "PORIVA")
        line["DMV_PORREQ"] = self._parse_decimal_pedido(fields[7], "PORREQ")
        line["DMV_TIPPRE"] = fields[8].strip()
        line["DMV_UNIMED"] = fields[9].strip()
        line["DMV_PREIVA"] = fields[10].strip()
        line["DMV_PVP"] = self._parse_decimal_pedido(fields[11], "PVP")
        try:
            line["DMV_EJEOFE"] = int((fields[12] or "0").strip())
            line["DMV_NUMOFE"] = int((fields[13] or "0").strip())
        except ValueError as exc:
            raise FaroError(f"Oferta invalida en linea de venta: {raw!r}") from exc
        line["DMV_PREVEN"] = preven
        return self._valorar_vencur_line(line)

    def _insert_valued_vencur(self, line: dict[str, Any]) -> dict[str, Any]:
        valued = self._valorar_vencur_line(line)
        self._insert_vencur_row(valued)
        return valued

    def _insert_canon_comment(self, source: dict[str, Any]) -> None:
        line = dict(source)
        if self.parameter("COOPE", "Valencia") == "Valencia":
            numlin = 999
        else:
            numlin = self._next_vencur_line(source["DMV_EJERCI"], source["DMV_NUMDOC"])
        line.update({
            "DMV_NUMLIN": numlin,
            "DMV_TIPLIN": "C",
            "DMV_CODART": "",
            "DMV_DESCRI": "COSTE R.A.E.E INCLUIDO R.D.208/2005",
            "DMV_CANTID": Decimal("0"),
            "DMV_UNIMED": "",
            "DMV_CODMON": "E",
            "DMV_TIPPRE": "0",
            "DMV_PREVEN": Decimal("0"),
            "DMV_PVP": Decimal("0"),
            "DMV_PREIVA": "N",
            "DMV_DTO1": Decimal("0"),
            "DMV_DTO2": Decimal("0"),
            "DMV_EJEOFE": 0,
            "DMV_NUMOFE": 0,
            "DMV_VALLIN": Decimal("0"),
            "DMV_VALLINS": Decimal("0"),
        })
        self._insert_valued_vencur(line)

    def _record_sale_canon(self, source: dict[str, Any], codcli: int) -> int:
        if str(source.get("DMV_TIPLIN") or "") != "D":
            return 0
        codart = str(source.get("DMV_CODART") or "")
        if int(source.get("DMV_EJEOFE") or 0) != 0:
            row = self.db.fetch_one(
                "SELECT FIRST 1 ARTI_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_CODINF=?",
                (self.settings.empresa, codart, "CANON"),
            )
            if row and str(row.get("ARTI_DESCRI") or ""):
                self._insert_canon_comment(source)
                return 1
            return 0

        if self.parameter("CANON", "") == "I":
            row = self.db.fetch_one(
                "SELECT ART_TIPPRE FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                (self.settings.empresa, codart),
            )
            if row and str(row.get("ART_TIPPRE") or "") == "C":
                self._insert_canon_comment(source)
                return 1
            return 0

        rows = self.db.fetch_all(
            "SELECT ARTI_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_CODINF=?",
            (self.settings.empresa, codart, "CANON"),
        )
        count = 0
        for info in rows:
            canon_code = str(info.get("ARTI_DESCRI") or "").strip()
            if not canon_code:
                continue
            art = self.db.fetch_one(
                "SELECT * FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                (self.settings.empresa, canon_code),
            )
            if not art:
                continue
            art = normalize(art)
            line = dict(source)
            line["DMV_NUMLIN"] = self._next_vencur_line(source["DMV_EJERCI"], source["DMV_NUMDOC"])
            line["DMV_TIPLIN"] = "D"
            line["DMV_CODART"] = str(art.get("ART_CODART") or "")
            line["DMV_DESCRI"] = str(art.get("ART_DESCRI") or "")
            line["DMV_UNIMED"] = str(art.get("ART_UNIMED") or "")
            line["DMV_CODMON"] = str(art.get("ART_CODMON") or "E")
            line["DMV_TIPPRE"] = "0"
            canon_price = dec(art.get("ART_PVP"))
            if codcli != 99999:
                special = self.db.fetch_one(
                    "SELECT CLIA_PRECIO FROM CLIART WHERE CLIA_NUMEMP=? AND CLIA_CODART=? AND CLIA_CODCLI=?",
                    (self.settings.empresa, line["DMV_CODART"], codcli),
                )
                if special and dec(special.get("CLIA_PRECIO")) != 0:
                    canon_price = dec(special.get("CLIA_PRECIO"))
            line["DMV_PREVEN"] = canon_price
            line["DMV_PVP"] = canon_price * (
                Decimal("1") + dec(line.get("DMV_PORIVA")) / 100 + dec(line.get("DMV_PORREQ")) / 100
            )
            line["DMV_PVP"] = self.round_price_order(line["DMV_PVP"], line["DMV_CODMON"], "I")
            line["DMV_PREIVA"] = "N"
            line["DMV_DTO1"] = Decimal("0")
            line["DMV_DTO2"] = Decimal("0")
            line["DMV_EJEOFE"] = 0
            line["DMV_NUMOFE"] = 0
            self._insert_valued_vencur(line)
            count += 1
        return count

    def _record_sale_gifts(self, source: dict[str, Any]) -> int:
        if str(source.get("DMV_TIPLIN") or "") != "D" or int(source.get("DMV_EJEOFE") or 0) != 0:
            return 0
        articulo = str(source.get("DMV_CODART") or "")
        rows = self.db.fetch_all(
            "SELECT ARTI_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_CODINF=?",
            (self.settings.empresa, articulo, "REGAL"),
        )
        inserted = 0
        for info in rows:
            spec = str(info.get("ARTI_DESCRI") or "")
            parts = spec.split("|", 2)
            gift_code = parts[0].strip() if parts else ""
            qty_text = parts[1].strip() if len(parts) > 1 else ""
            description = parts[2] if len(parts) > 2 else ""
            try:
                threshold = Decimal(qty_text.replace(",", ".")) if qty_text else Decimal("1")
            except Exception:
                threshold = Decimal("1")
            if threshold <= 0:
                threshold = Decimal("1")
            original_qty = dec(source.get("DMV_CANTID"))
            if original_qty < threshold:
                continue

            # Se replica literalmente un bug del original: si hay descripcion
            # adicional, R_VCR.DMV_CANTID se pone a 0 antes de calcular la
            # cantidad del regalo, por lo que el regalo termina con cantidad 0.
            working_qty = original_qty
            if description:
                extra = dict(source)
                extra.update({
                    "DMV_NUMLIN": self._next_vencur_line(source["DMV_EJERCI"], source["DMV_NUMDOC"]),
                    "DMV_CODART": "", "DMV_DESCRI": description, "DMV_UNIMED": "", "DMV_TIPLIN": "X",
                    "DMV_CANTID": Decimal("0"), "DMV_CODMON": "E", "DMV_TIPPRE": "", "DMV_PREVEN": Decimal("0"),
                    "DMV_PVP": Decimal("0"), "DMV_PREIVA": "N", "DMV_DTO1": Decimal("0"), "DMV_DTO2": Decimal("0"),
                    "DMV_EJEOFE": 0, "DMV_NUMOFE": 0, "DMV_VALLIN": Decimal("0"), "DMV_VALLINS": Decimal("0"),
                })
                self._insert_valued_vencur(extra)
                inserted += 1
                working_qty = Decimal("0")

            gift = self.db.fetch_one(
                "SELECT ART_CODART, ART_DESCRI, ART_UNIMED, ART_PREVEN4, ART_PVP FROM ARTICUL "
                "WHERE ART_NUMEMP=? AND ART_CODART=?",
                (self.settings.empresa, gift_code),
            )
            if not gift:
                continue
            line = dict(source)
            line.update({
                "DMV_CODART": str(gift.get("ART_CODART") or ""),
                "DMV_DESCRI": str(gift.get("ART_DESCRI") or ""),
                "DMV_UNIMED": str(gift.get("ART_UNIMED") or ""),
                "DMV_PREVEN": dec(gift.get("ART_PREVEN4")),
                "DMV_PVP": dec(gift.get("ART_PVP")),
                "DMV_DTO1": Decimal("100"),
                "DMV_NUMLIN": self._next_vencur_line(source["DMV_EJERCI"], source["DMV_NUMDOC"]),
                "DMV_TIPLIN": "D",
                "DMV_CANTID": Decimal(int(working_qty / threshold)),
                "DMV_CODMON": "E",
                "DMV_TIPPRE": "0",
                "DMV_PREIVA": "N",
                "DMV_DTO2": Decimal("0"),
                "DMV_EJEOFE": 0,
                "DMV_NUMOFE": 0,
            })
            self._insert_valued_vencur(line)
            inserted += 1
        return inserted

    def _vencaj_tax_buckets(self, cbv: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self.db.fetch_all(
            "SELECT DMV_TIPLIN, DMV_PORIVA, DMV_PORREQ, DMV_VALLINS, DMV_CODMON FROM VENCUR "
            "WHERE DMV_NUMEMP=? AND DMV_EJERCI=? AND DMV_NUMDOC=? AND DMV_TIPLIN<>?",
            (cbv["CBV_NUMEMP"], cbv["CBV_EJERCI"], cbv["CBV_NUMDOC"], "C"),
        )
        buckets: list[dict[str, Any]] = []
        for row in rows:
            row = normalize(row)
            poriva = dec(row.get("DMV_PORIVA"))
            porreq = dec(row.get("DMV_PORREQ"))
            amount = dec(row.get("DMV_VALLINS"))
            codmon = str(row.get("DMV_CODMON") or cbv["CBV_CODMON"])
            if codmon != cbv["CBV_CODMON"]:
                amount = self._change_price_currency(amount, codmon, cbv["CBV_CODMON"], "I")
            bucket = next((b for b in buckets if b["poriva"] == poriva and b["porreq"] == porreq), None)
            if bucket is None:
                bucket = {"baseimp": Decimal("0"), "poriva": poriva, "porreq": porreq}
                buckets.append(bucket)
            bucket["baseimp"] += amount
        return buckets

    def _value_vencaj_header(self, cbv: dict[str, Any]) -> dict[str, Any]:
        cbv = dict(cbv)
        # Las cabeceras recuperadas de BD pasan por normalize(), que convierte
        # Decimal a texto para serializacion. Antes de valorar, restauramos los
        # campos monetarios que TOTALES_CABECERA trata aritmeticamente.
        cbv["CBV_PORDTO"] = dec(cbv.get("CBV_PORDTO"))
        cbv["CBV_IMPPOR"] = dec(cbv.get("CBV_IMPPOR"))
        cliente = self._busqueda_clien_pedido(int(cbv["CBV_CODCLI"]), int(cbv["CBV_SUBCLI"]))
        buckets = self._vencaj_tax_buckets(cbv)
        return self._totales_cabecera_pedido(cbv, buckets, cliente)

    def save_open_sale(
        self,
        venta: str,
        codcli: Any,
        subcli: Any,
        texto: str,
        tipdoc: str,
        usuario: str,
    ) -> dict[str, Any]:
        """Migra ``Grabar_Venta`` completamente a SQL Python nativo.

        ``texto`` conserva el protocolo historico: lineas separadas por ``#``
        y 14 campos por linea separados por ``|``::

            CODART|DESCRI|CANTID|PREVEN|DTO1|DTO2|PORIVA|PORREQ|TIPPRE|UNIMED|PREIVA|PVP|EJEOFE|NUMOFE

        A diferencia del Delphi, toda la operacion se confirma en una unica
        transaccion: no se deja una cabecera ya confirmada si falla una linea.
        """
        empresa = self.settings.empresa
        codcli_i, subcli_i = int(codcli), int(subcli)
        tipdoc_s = str(tipdoc or "").strip()
        usuario_s = str(usuario or "")
        now = datetime.now()
        today = now.date()
        cliente = self._busqueda_clien_pedido(codcli_i, subcli_i)
        editing = bool(str(venta or "").strip())

        try:
            if editing:
                ejerci, numdoc = self._parse_vencaj_key(venta)
                codigo = self._vencaj_semaphore_code(ejerci, numdoc)
                if not self._probe_vencaj_lock(codigo, commit=False):
                    raise FaroError("Venta bloqueada")
                row = self.db.fetch_one(
                    "SELECT * FROM VENCAJ WHERE CBV_NUMEMP=? AND CBV_EJERCI=? AND CBV_NUMDOC=?",
                    (empresa, ejerci, numdoc),
                )
                if not row:
                    raise FaroError(f"Venta no encontrada: {venta}")
                cbv = normalize(row)
                self.db.execute(
                    "DELETE FROM VENCUR WHERE DMV_NUMEMP=? AND DMV_EJERCI=? AND DMV_NUMDOC=?",
                    (empresa, ejerci, numdoc),
                )
            else:
                ejerci = today.year
                numdoc = self._next_vencaj_numero(ejerci)
                while numdoc <= 999999:
                    codigo = self._vencaj_semaphore_code(ejerci, numdoc)
                    exists = self.db.fetch_one(
                        "SELECT FIRST 1 CBV_NUMDOC FROM VENCAJ WHERE CBV_NUMEMP=? AND CBV_EJERCI=? AND CBV_NUMDOC=?",
                        (empresa, ejerci, numdoc),
                    )
                    if not exists and self._probe_vencaj_lock(codigo, commit=False):
                        break
                    numdoc += 1
                if numdoc > 999999:
                    raise FaroError("Error en la numeracion de VENCAJ")
                cbv = {
                    "CBV_NUMEMP": empresa, "CBV_EJERCI": ejerci, "CBV_NUMDOC": numdoc, "CBV_CAJA": 1,
                    "CBV_USUMOD": usuario_s, "CBV_TIPDOC": tipdoc_s, "CBV_TIPAC": "0",
                    "CBV_SERIE": self._serie_ticket() if tipdoc_s == "T" else self._serie_documento(tipdoc_s),
                    "CBV_FECHA": today, "CBV_FECHAE": today,
                    "CBV_CODCLI": codcli_i, "CBV_SUBCLI": subcli_i, "CBV_CODREP": cliente["codrep"],
                    "CBV_COMREP": Decimal("0"), "CBV_NOMCLI": cliente["razsoc"], "CBV_CIF": cliente["cif"],
                    "CBV_DOMCLI": cliente["domici"], "CBV_CODPOS": cliente["codpos"], "CBV_POBLAC": cliente["poblac"],
                    "CBV_CODPAG": cliente["forpag"], "CBV_FORENV": cliente["forenv"], "CBV_PORDTO": cliente["dtoesp"],
                    "CBV_IMPPOR": Decimal("0"), "CBV_BASIMP1": Decimal("0"), "CBV_PORIVA1": Decimal("0"),
                    "CBV_PORREQ1": Decimal("0"), "CBV_BASIMP2": Decimal("0"), "CBV_PORIVA2": Decimal("0"),
                    "CBV_PORREQ2": Decimal("0"), "CBV_BASIMP3": Decimal("0"), "CBV_PORIVA3": Decimal("0"),
                    "CBV_PORREQ3": Decimal("0"), "CBV_BASIMP4": Decimal("0"), "CBV_PORIVA4": Decimal("0"),
                    "CBV_PORREQ4": Decimal("0"), "CBV_TOTALS": Decimal("0"), "CBV_TOTALD": Decimal("0"),
                    "CBV_IMPCOB": Decimal("0"), "CBV_CODMON": "E", "CBV_FORCOB": "E", "CBV_NUMTAR": 0,
                    "CBV_TIPVEN": self._busqueda_tipven2(tipdoc_s, "0"), "CBV_SITUAC": "P", "CBV_OBSERV": "",
                    "CBV_FECMOD": now, "CBV_REFCLI": "", "CBV_RETIRA": "", "CBV_CODTAR": "",
                }
                self._insert_vencaj_row(cbv)

            line_count = 0
            canon_count = 0
            gift_count = 0
            rest = str(texto or "")
            numlin = 10
            while rest:
                raw, rest = self._procesar_cadena(rest, "#")
                # El WHILE Delphi se detiene en cuanto VALOR queda vacio,
                # incluso si todavia queda texto despues de otro '#'.
                if raw == "":
                    break
                line = self._parse_sale_line(cbv, numlin, raw)
                self._insert_vencur_row(line)
                line_count += 1
                canon_count += self._record_sale_canon(line, 99999)
                gift_count += self._record_sale_gifts(line)
                numlin += 10

            cbv = self._value_vencaj_header(cbv)
            self._update_vencaj_totals(cbv)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        key = f"{cbv['CBV_EJERCI']}-{cbv['CBV_NUMDOC']}"
        return {
            "venta": key,
            "ejerci": int(cbv["CBV_EJERCI"]),
            "numdoc": int(cbv["CBV_NUMDOC"]),
            "created": not editing,
            "updated": editing,
            "lineas_principales": line_count,
            "lineas_canon": canon_count,
            "lineas_regalo": gift_count,
            "totals": normalize(cbv.get("CBV_TOTALS")),
            "totald": normalize(cbv.get("CBV_TOTALD")),
            "datasnap_text": "",
        }

    def delete_open_sale(self, venta: str) -> dict[str, Any]:
        """Migra ``Borrar_Venta`` con transaccion y SQL parametrizado."""
        ejerci, numdoc = self._parse_vencaj_key(venta)
        codigo = self._vencaj_semaphore_code(ejerci, numdoc)
        if self._vencaj_is_locked(codigo):
            return {
                "venta": str(venta),
                "deleted": False,
                "blocked": True,
                "message": "Venta bloqueada",
                "datasnap_text": "Venta bloqueada",
            }
        try:
            # Se conserva el orden del Delphi: primero VENCAJ, despues VENCUR.
            self.db.execute(
                "DELETE FROM VENCAJ WHERE CBV_NUMEMP=? AND CBV_EJERCI=? AND CBV_NUMDOC=?",
                (self.settings.empresa, ejerci, numdoc),
            )
            self.db.execute(
                "DELETE FROM VENCUR WHERE DMV_NUMEMP=? AND DMV_EJERCI=? AND DMV_NUMDOC=?",
                (self.settings.empresa, ejerci, numdoc),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {
            "venta": str(venta),
            "deleted": True,
            "blocked": False,
            "message": "",
            "datasnap_text": "",
        }


    # ------------------------------------------------------------------
    # Fase 2D - Conversion de pedidos a venta abierta y documentos
    # (Grabar_Venta_Abierta_Pedido, Grabar_Albaran)
    # ------------------------------------------------------------------

    def _next_detmov_line(self, cbv: dict[str, Any]) -> int:
        """Replica NUMERAR_DETMOV para un documento CABDOCV."""
        row = self.db.fetch_one(
            "SELECT MAX(DMV_NUMLIN) AS DMV_NUMLIN FROM DETMOV WHERE DMV_NUMEMP=? AND DMV_CENTRO=? "
            "AND DMV_TIPDOC=? AND DMV_TIPAC=? AND DMV_EJERCI=? AND DMV_SERIE=? AND DMV_NUMDOC=? "
            "AND DMV_NUMLIN<>999",
            (
                cbv["CBV_NUMEMP"], cbv["CBV_CENTRO"], cbv["CBV_TIPDOC"], cbv["CBV_TIPAC"],
                cbv["CBV_EJERCI"], cbv["CBV_SERIE"], cbv["CBV_NUMDOC"],
            ),
        )
        current = row.get("DMV_NUMLIN") if row else None
        numero = int(current) + 1 if current is not None else 1
        # Condicion literal heredada de NUMERAR_DETMOV.
        if numero == 9999:
            numero = 1000
        return numero

    def _document_line_base(self, cbv: dict[str, Any], numlin: int) -> dict[str, Any]:
        return {
            "DMV_NUMEMP": cbv["CBV_NUMEMP"], "DMV_CENTRO": cbv["CBV_CENTRO"],
            "DMV_TIPDOC": cbv["CBV_TIPDOC"], "DMV_TIPAC": cbv["CBV_TIPAC"],
            "DMV_EJERCI": cbv["CBV_EJERCI"], "DMV_SERIE": cbv["CBV_SERIE"],
            "DMV_NUMDOC": cbv["CBV_NUMDOC"], "DMV_NUMLIN": int(numlin), "DMV_SIGNO": "1",
            "DMV_CAJA": cbv["CBV_CAJA"], "DMV_USUAR": cbv["CBV_USUMOD"], "DMV_TIPLIN": "D",
            "DMV_FECMOV": cbv["CBV_FECHA"], "DMV_CODART": "", "DMV_DESCRI": ".",
            "DMV_CODMON": cbv["CBV_CODMON"], "DMV_TIPPRE": "", "DMV_PREVEN": Decimal("0"),
            "DMV_PORIVA": Decimal("0"), "DMV_PORREQ": Decimal("0"), "DMV_PVP": Decimal("0"),
            "DMV_CANTID": Decimal("0"), "DMV_CANPRE": Decimal("1"), "DMV_UNIMED": "",
            "DMV_DTO1": Decimal("0"), "DMV_DTO2": Decimal("0"), "DMV_VALLIN": Decimal("0"),
            "DMV_VALLINS": Decimal("0"), "DMV_IMPDTO": Decimal("0"), "DMV_EJEOFE": 0,
            "DMV_NUMOFE": 0, "DMV_EJERCIO": 0, "DMV_TIPDOCO": "", "DMV_SERIEO": "",
            "DMV_NUMDOCO": 0, "DMV_NUMLINO": 0, "DMV_PREIVA": "",
        }

    def _parse_document_sale_line(self, cbv: dict[str, Any], numlin: int, raw: str) -> dict[str, Any]:
        """Parsea el protocolo de 14 campos usado por Grabar_Albaran."""
        fields = str(raw or "").split("|")
        if len(fields) < 14:
            fields += [""] * (14 - len(fields))
        line = self._document_line_base(cbv, numlin)
        line["DMV_CODART"] = fields[0].strip()
        line["DMV_DESCRI"] = fields[1].strip()
        line["DMV_CANTID"] = self._parse_decimal_pedido(fields[2], "CANTID")
        line["DMV_PREVEN"] = self._parse_decimal_pedido(fields[3], "PREVEN")
        line["DMV_DTO1"] = self._parse_decimal_pedido(fields[4], "DTO1")
        line["DMV_DTO2"] = self._parse_decimal_pedido(fields[5], "DTO2")
        line["DMV_PORIVA"] = self._parse_decimal_pedido(fields[6], "PORIVA")
        line["DMV_PORREQ"] = self._parse_decimal_pedido(fields[7], "PORREQ")
        line["DMV_TIPPRE"] = fields[8].strip()
        line["DMV_UNIMED"] = fields[9].strip()
        line["DMV_PREIVA"] = fields[10].strip()
        line["DMV_PVP"] = self._parse_decimal_pedido(fields[11], "PVP")
        try:
            line["DMV_EJEOFE"] = int((fields[12] or "0").strip())
            line["DMV_NUMOFE"] = int((fields[13] or "0").strip())
        except ValueError as exc:
            raise FaroError(f"Oferta invalida en linea de documento: {raw!r}") from exc
        return line

    def _copy_open_sale_lines_to_document(self, cbv: dict[str, Any], sale_year: int, sale_num: int) -> int:
        rows = self.db.fetch_all(
            "SELECT * FROM VENCUR WHERE DMV_NUMEMP=? AND DMV_EJERCI=? AND DMV_NUMDOC=? ORDER BY DMV_NUMLIN",
            (cbv["CBV_NUMEMP"], sale_year, sale_num),
        )
        copied = 0
        for row in rows:
            source = normalize(row)
            line = self._document_line_base(cbv, int(source.get("DMV_NUMLIN") or ((copied + 1) * 10)))
            for key in (
                "DMV_CAJA", "DMV_USUAR", "DMV_TIPLIN", "DMV_FECMOV", "DMV_CODART", "DMV_DESCRI",
                "DMV_CODMON", "DMV_TIPPRE", "DMV_PREVEN", "DMV_PORIVA", "DMV_PORREQ", "DMV_PVP",
                "DMV_CANTID", "DMV_CANPRE", "DMV_UNIMED", "DMV_DTO1", "DMV_DTO2", "DMV_VALLIN",
                "DMV_VALLINS", "DMV_IMPDTO", "DMV_EJEOFE", "DMV_NUMOFE", "DMV_EJERCIO",
                "DMV_TIPDOCO", "DMV_SERIEO", "DMV_NUMDOCO", "DMV_NUMLINO", "DMV_PREIVA",
            ):
                if key in source:
                    line[key] = source[key]
            line["DMV_CAJA"] = cbv["CBV_CAJA"]
            line["DMV_USUAR"] = cbv["CBV_USUMOD"]
            line["DMV_FECMOV"] = cbv["CBV_FECHA"]
            self._grabar_detmov_g_albaran(line)
            copied += 1
        return copied

    def _insert_document_canon_comment(self, source: dict[str, Any]) -> None:
        line = dict(source)
        line.update({
            "DMV_NUMLIN": 999, "DMV_TIPLIN": "C", "DMV_SIGNO": "0", "DMV_CODART": "",
            "DMV_DESCRI": "COSTE R.A.E.E INCLUIDO R.D.208/2005", "DMV_CANTID": Decimal("0"),
            "DMV_CANPRE": Decimal("1"), "DMV_UNIMED": "", "DMV_CODMON": "E", "DMV_TIPPRE": "0",
            "DMV_PREVEN": Decimal("0"), "DMV_PVP": Decimal("0"), "DMV_PREIVA": "N",
            "DMV_DTO1": Decimal("0"), "DMV_DTO2": Decimal("0"), "DMV_EJEOFE": 0, "DMV_NUMOFE": 0,
            "DMV_VALLIN": Decimal("0"), "DMV_VALLINS": Decimal("0"),
        })
        self._grabar_detmov_g_albaran(line)

    def _record_document_canon(self, source: dict[str, Any], codcli: int) -> int:
        """Replica GRABAR_CANON_DETMOV para altas de DETMOV."""
        if str(source.get("DMV_TIPLIN") or "") != "D" or int(source.get("DMV_EJEOFE") or 0) != 0:
            return 0
        codart = str(source.get("DMV_CODART") or "")
        if self.parameter("CANON", "") == "I":
            art = self.db.fetch_one(
                "SELECT ART_TIPPRE FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                (self.settings.empresa, codart),
            )
            if art and str(art.get("ART_TIPPRE") or "") == "C":
                self._insert_document_canon_comment(source)
                return 1
            return 0

        rows = self.db.fetch_all(
            "SELECT ARTI_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_CODINF=?",
            (self.settings.empresa, codart, "CANON"),
        )
        inserted = 0
        for info in rows:
            canon_code = str(info.get("ARTI_DESCRI") or "").strip()
            if not canon_code:
                continue
            art = self.db.fetch_one(
                "SELECT * FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                (self.settings.empresa, canon_code),
            )
            if not art:
                continue
            art = normalize(art)
            line = dict(source)
            line.update({
                "DMV_NUMLIN": self._next_detmov_line(source), "DMV_TIPLIN": "D",
                "DMV_CODART": str(art.get("ART_CODART") or ""),
                "DMV_DESCRI": str(art.get("ART_DESCRI") or ""),
                "DMV_UNIMED": str(art.get("ART_UNIMED") or ""),
                "DMV_CODMON": str(art.get("ART_CODMON") or "E"), "DMV_TIPPRE": "0",
                "DMV_PREIVA": "N", "DMV_DTO1": Decimal("0"), "DMV_DTO2": Decimal("0"),
                "DMV_EJEOFE": 0, "DMV_NUMOFE": 0, "DMV_PVP": Decimal("0"),
            })
            price = dec(art.get("ART_PVP"))
            if codcli != 99999:
                special = self.db.fetch_one(
                    "SELECT CLIA_PRECIO FROM CLIART WHERE CLIA_NUMEMP=? AND CLIA_CODART=? AND CLIA_CODCLI=?",
                    (self.settings.empresa, line["DMV_CODART"], codcli),
                )
                if special and dec(special.get("CLIA_PRECIO")) != 0:
                    price = dec(special.get("CLIA_PRECIO"))
            line["DMV_PREVEN"] = price
            self._grabar_detmov_g_albaran(line)
            inserted += 1
        return inserted

    def _record_document_gifts(self, source: dict[str, Any]) -> int:
        """Replica GRABAR_REGALO_DETMOV, incluidos sus efectos historicos."""
        if str(source.get("DMV_TIPLIN") or "") != "D" or int(source.get("DMV_EJEOFE") or 0) != 0:
            return 0
        articulo = str(source.get("DMV_CODART") or "")
        rows = self.db.fetch_all(
            "SELECT ARTI_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_CODINF=?",
            (self.settings.empresa, articulo, "REGAL"),
        )
        inserted = 0
        for info in rows:
            spec = str(info.get("ARTI_DESCRI") or "")
            parts = spec.split("|", 2)
            gift_code = parts[0].strip() if parts else ""
            qty_text = parts[1].strip() if len(parts) > 1 else ""
            description = parts[2] if len(parts) > 2 else ""
            try:
                threshold = Decimal(qty_text.replace(",", ".")) if qty_text else Decimal("1")
            except Exception:
                threshold = Decimal("1")
            if threshold <= 0:
                threshold = Decimal("1")
            original_qty = dec(source.get("DMV_CANTID"))
            if original_qty < threshold:
                continue

            # Bug heredado: una descripcion adicional pone CANTID=0 y esa
            # cantidad mutada se reutiliza despues para calcular el regalo.
            working_qty = original_qty
            if description:
                extra = dict(source)
                extra.update({
                    "DMV_NUMLIN": self._next_detmov_line(source), "DMV_CODART": "",
                    "DMV_DESCRI": description, "DMV_UNIMED": "", "DMV_TIPLIN": "X",
                    "DMV_CANTID": Decimal("0"), "DMV_CODMON": "E", "DMV_TIPPRE": "0",
                    "DMV_PREVEN": Decimal("0"), "DMV_PVP": Decimal("0"), "DMV_PREIVA": "N",
                    "DMV_DTO1": Decimal("0"), "DMV_DTO2": Decimal("0"), "DMV_EJEOFE": 0,
                    "DMV_NUMOFE": 0, "DMV_VALLIN": Decimal("0"), "DMV_VALLINS": Decimal("0"),
                })
                self._grabar_detmov_g_albaran(extra)
                inserted += 1
                working_qty = Decimal("0")

            gift = self.db.fetch_one(
                "SELECT ART_CODART, ART_DESCRI, ART_UNIMED, ART_PREVEN4, ART_PVP FROM ARTICUL "
                "WHERE ART_NUMEMP=? AND ART_CODART=?",
                (self.settings.empresa, gift_code),
            )
            if not gift:
                continue
            gift = normalize(gift)
            line = dict(source)
            line.update({
                "DMV_NUMLIN": self._next_detmov_line(source), "DMV_TIPLIN": "D",
                "DMV_CODART": str(gift.get("ART_CODART") or ""),
                "DMV_DESCRI": str(gift.get("ART_DESCRI") or ""),
                "DMV_UNIMED": str(gift.get("ART_UNIMED") or ""),
                "DMV_PREVEN": dec(gift.get("ART_PREVEN4")), "DMV_PVP": Decimal("0"),
                "DMV_DTO1": Decimal("100"), "DMV_CANTID": Decimal(int(working_qty / threshold)),
                "DMV_CODMON": "E", "DMV_TIPPRE": "0", "DMV_PREIVA": "N",
                "DMV_DTO2": Decimal("0"), "DMV_EJEOFE": 0, "DMV_NUMOFE": 0,
            })
            self._grabar_detmov_g_albaran(line)
            inserted += 1
        return inserted

    def _minimum_delivery_amount(self, codcli: int, subcli: int) -> Decimal | None:
        value = self._cliente_info_adicional(codcli, subcli, "IMPMI")
        if not value:
            return None
        try:
            return Decimal(str(value).replace(",", "."))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Fase 2E - Facturacion, efectos, riesgo y cobros de caja
    # ------------------------------------------------------------------
    @staticmethod
    def _date_with_clamped_day(year: int, month: int, day: int) -> date:
        last = calendar.monthrange(year, month)[1]
        return date(year, month, min(max(int(day), 1), last))

    @staticmethod
    def _add_months_clamped(base: date, months: int) -> date:
        month0 = base.month - 1 + int(months)
        year = base.year + month0 // 12
        month = month0 % 12 + 1
        last = calendar.monthrange(year, month)[1]
        day = min(base.day, last)
        # LIBFEC_U considera 28/29/30/31 como "fin de mes" cuando quedan
        # menos de 4 dias para terminar el mes de destino.
        if last - day < 4:
            day = last
        return date(year, month, day)

    def _spfechas(
        self,
        envio: date,
        cadencias: list[int],
        dias_pago: list[int],
        meses_no_vencimiento: list[int],
        modo: int,
    ) -> list[date]:
        """Port Python de SPFECHAS (LIBFEC_U.pas).

        Mantiene las reglas historicas: cadencias multiples de 30 se tratan
        como meses exactos; se respetan hasta tres dias fijos, dos meses sin
        vencimientos y los modos 1=siguiente, 2=anterior, 3=mas proximo.
        """
        dias = [int(x or 0) for x in (dias_pago + [0, 0, 0])[:3]]
        meses = [int(x or 0) for x in (meses_no_vencimiento + [0, 0])[:2]]
        if dias[0] < 0 or dias[0] > 31:
            raise FaroError("Dia fijo de pago 1 incorrecto.")
        # El Delphi contiene un typo y valida DIAFP[1] tres veces; se mantiene
        # la validacion util de los otros dos aqui para no construir fechas
        # imposibles desde un MCP.
        if any(x < 0 or x > 31 for x in dias[1:]):
            raise FaroError("Dia fijo de pago incorrecto.")
        if any(x < 0 or x > 12 for x in meses):
            raise FaroError("Mes de no vencimiento incorrecto.")
        if modo not in (1, 2, 3):
            raise FaroError("Modo de calculo de vencimiento incorrecto.")

        # Clasificacion/relleno exacto de los dias fijos del original.
        normalized = [0, 0, 0]
        last_idx = 0
        for i, value in enumerate(dias, 1):
            if value != 0:
                normalized[i - 1] = value
                last_idx = i
        if last_idx == 1:
            normalized[1] = normalized[0]
            normalized[2] = normalized[0]
        elif last_idx == 2:
            normalized[2] = normalized[1]
        normalized.sort()
        meses.sort()

        vencimientos: list[date] = []
        for n, raw_cadencia in enumerate((cadencias + [0] * 12)[:12]):
            cadencia = int(raw_cadencia or 0)
            if cadencia == 0 and n != 0:
                continue

            if cadencia % 30 == 0:
                theoretical = self._add_months_clamped(envio, cadencia // 30)
            else:
                theoretical = envio + timedelta(days=cadencia)

            # Meses sin vencimiento: mover al mes siguiente y, si existe,
            # usar el primer dia fijo de pago.
            year, month = theoretical.year, theoretical.month
            if month == meses[0]:
                month += 1
                if month > 12:
                    month, year = 1, year + 1
                theoretical = self._date_with_clamped_day(year, month, normalized[0] or 1)
            if month == meses[1]:
                month += 1
                if month > 12:
                    month, year = 1, year + 1
                theoretical = self._date_with_clamped_day(year, month, normalized[0] or 1)

            theoretical_day = theoretical.day
            if 30 in normalized and theoretical_day in (28, 29, 30, 31):
                theoretical_day = 30

            if all(x != 0 for x in normalized) and theoretical_day not in normalized:
                y, m = theoretical.year, theoretical.month
                prev_m, prev_y = m - 1, y
                if prev_m < 1:
                    prev_m, prev_y = 12, y - 1
                next_m, next_y = m + 1, y
                if next_m > 12:
                    next_m, next_y = 1, y + 1
                candidates = [
                    self._date_with_clamped_day(prev_y, prev_m, normalized[2]),
                    self._date_with_clamped_day(y, m, normalized[0]),
                    self._date_with_clamped_day(y, m, normalized[1]),
                    self._date_with_clamped_day(y, m, normalized[2]),
                    self._date_with_clamped_day(next_y, next_m, normalized[0]),
                ]

                # Replica el bucle de LIBFEC_U que evita candidatos anteriores
                # a la fecha de envio sustituyendolos por los siguientes.
                for i in range(4):
                    for j in range(i + 1, 5):
                        if candidates[i] < envio:
                            candidates[i] = candidates[j]

                if candidates[0].month in meses:
                    candidates[0] = candidates[1]
                for _ in range(2):
                    if candidates[4].month in meses:
                        ny, nm = candidates[4].year, candidates[4].month + 1
                        if nm > 12:
                            nm, ny = 1, ny + 1
                        candidates[4] = self._date_with_clamped_day(ny, nm, normalized[0])

                if modo == 1:
                    theoretical = next((d for d in candidates if d >= theoretical), candidates[-1])
                elif modo == 2:
                    previous = [d for d in candidates if d < theoretical]
                    theoretical = previous[-1] if previous else candidates[0]
                else:
                    theoretical = min(candidates, key=lambda d: (abs((d - theoretical).days), d))

            vencimientos.append(theoretical)
        return vencimientos

    def _generate_invoice_effects(self, cbv: dict[str, Any]) -> int:
        """Replica LIBFAC_GENERAR_EFECTOS para una factura pendiente."""
        key = (
            cbv["CBV_NUMEMP"], cbv["CBV_CENTRO"], cbv["CBV_TIPDOC"], cbv["CBV_TIPAC"],
            cbv["CBV_EJERCI"], cbv["CBV_SERIE"], cbv["CBV_NUMDOC"],
        )
        existing = self.db.fetch_one(
            "SELECT FIRST 1 CBVE_NUMDOC, CBVE_IMPCOB, CBVE_EJEREM FROM CABDOCVE WHERE "
            "CBVE_NUMEMP=? AND CBVE_CENTRO=? AND CBVE_TIPDOC=? AND CBVE_TIPAC=? AND "
            "CBVE_EJERCI=? AND CBVE_SERIE=? AND CBVE_NUMDOC=?",
            key,
        )
        if existing:
            # El original muestra un aviso distinto si ya estan cobrados o
            # remesados, pero a continuacion los borra igualmente.
            self.db.execute(
                "DELETE FROM CABDOCVE WHERE CBVE_NUMEMP=? AND CBVE_CENTRO=? AND CBVE_TIPDOC=? AND "
                "CBVE_TIPAC=? AND CBVE_EJERCI=? AND CBVE_SERIE=? AND CBVE_NUMDOC=?",
                key,
            )

        cli = self.db.fetch_one(
            "SELECT CLI_CODCLI, CLI_SUBCLI, CLI_DIAPAG1, CLI_DIAPAG2, CLI_DIAPAG3, CLI_MESNOV1, "
            "CLI_MESNOV2 FROM CLIEN WHERE CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
            (self.settings.empresa, cbv["CBV_CODCLI"], cbv["CBV_SUBCLI"]),
        )
        if not cli:
            raise FaroError("Codigo de cliente inexistente")
        cli = normalize(cli)

        fpg = self.db.fetch_one(
            "SELECT FPG_CODIGO, FPG_TIPDOC, FPG_CODACEP FROM FORPAG WHERE FPG_NUMEMP=? AND FPG_CODIGO=?",
            (self.settings.empresa, cbv["CBV_CODPAG"]),
        )
        if not fpg:
            raise FaroError("ERROR forma de pago inexistente")
        fpg = normalize(fpg)
        rows = self.db.fetch_all(
            "SELECT FPGA_APLAZ FROM FORPAGA WHERE FPGA_NUMEMP=? AND FPGA_CODIGO=?",
            (self.settings.empresa, cbv["CBV_CODPAG"]),
        )
        cadencias = [int(row.get("FPGA_APLAZ") or 0) for row in rows[:12]]
        count = len(cadencias) or 1
        if not cadencias:
            cadencias = [0]
        modo_text = self.parameter("MODOVE", "1") or "1"
        try:
            modo = int(modo_text)
        except ValueError:
            modo = 1
        due_dates = self._spfechas(
            cbv["CBV_FECHA"], cadencias,
            [int(cli.get("CLI_DIAPAG1") or 0), int(cli.get("CLI_DIAPAG2") or 0), int(cli.get("CLI_DIAPAG3") or 0)],
            [int(cli.get("CLI_MESNOV1") or 0), int(cli.get("CLI_MESNOV2") or 0)],
            modo,
        )
        importe = self.round_price_order(dec(cbv["CBV_TOTALD"]) / Decimal(count), cbv["CBV_CODMON"], "I")
        ajuste = dec(cbv["CBV_TOTALD"]) - importe * Decimal(count - 1)
        cobrado_restante = dec(cbv.get("CBV_IMPCOB"))
        tipges = self.parameter("TIPGES", "")
        cols = [
            "CBVE_NUMEMP", "CBVE_CENTRO", "CBVE_TIPDOC", "CBVE_TIPAC", "CBVE_EJERCI", "CBVE_SERIE",
            "CBVE_NUMDOC", "CBVE_NUMORD", "CBVE_TIPGES", "CBVE_TIPOEF", "CBVE_CODACEP", "CBVE_FECHA",
            "CBVE_FECVTO", "CBVE_IMPORT", "CBVE_CODMON", "CBVE_CODCLI", "CBVE_SUBCLI", "CBVE_FECCAN",
            "CBVE_IMPCOB", "CBVE_IMPGAS", "CBVE_FECIMP", "CBVE_INDEDI", "CBVE_OBSERV", "CBVE_EJEREM",
            "CBVE_CODREM",
        ]
        placeholders = ",".join(["?"] * len(cols))
        for j in range(count):
            amount = ajuste if j == 0 else importe
            effect_paid = min(max(cobrado_restante, Decimal("0")), amount)
            cobrado_restante -= effect_paid
            fec_can = cbv["CBV_FECHA"] if effect_paid >= amount else None
            values = (
                cbv["CBV_NUMEMP"], cbv["CBV_CENTRO"], cbv["CBV_TIPDOC"], cbv["CBV_TIPAC"], cbv["CBV_EJERCI"],
                cbv["CBV_SERIE"], cbv["CBV_NUMDOC"], j + 1, tipges, str(fpg.get("FPG_TIPDOC") or ""),
                str(fpg.get("FPG_CODACEP") or ""), cbv["CBV_FECHA"], due_dates[j], amount, cbv["CBV_CODMON"],
                int(cli.get("CLI_CODCLI") or cbv["CBV_CODCLI"]), int(cli.get("CLI_SUBCLI") or cbv["CBV_SUBCLI"]),
                fec_can, effect_paid, Decimal("0"), None, "N", "", 0, 0,
            )
            self.db.execute(f"INSERT INTO CABDOCVE ({', '.join(cols)}) VALUES ({placeholders})", values)
        return count

    def _risk_convert(self, amount: Decimal, currency: str, target: str) -> Decimal:
        if str(currency or "") == str(target or ""):
            return amount
        return self._change_price_currency(amount, str(currency or "E"), str(target or "E"), "I")

    def _riesgo_actual(self, codcli: int, subcli: int) -> tuple[Decimal, str] | None:
        """Port de RIESGO_ACTUAL (LIBESP_U.pas)."""
        if codcli == 99999 and subcli == 0:
            return Decimal("-1"), "E"
        cli = self.db.fetch_one(
            "SELECT CLI_CODCLI, CLI_SUBCLI, CLI_AGRUPAC, CLI_RIESGO, CLI_CODMON FROM CLIEN "
            "WHERE CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
            (self.settings.empresa, codcli, subcli),
        )
        if not cli:
            return None
        cli = normalize(cli)
        riesgo = dec(cli.get("CLI_RIESGO"))
        moneda = str(cli.get("CLI_CODMON") or "E")
        agrupa = codcli != 99999 and str(cli.get("CLI_AGRUPAC") or "") == "S"

        def subtract_rows(rows: list[dict[str, Any]], amount_field: str, currency_field: str, paid_field: str | None = None):
            nonlocal riesgo
            for row in rows:
                amount = dec(row.get(amount_field))
                if paid_field:
                    amount -= dec(row.get(paid_field))
                riesgo -= self._risk_convert(amount, str(row.get(currency_field) or moneda), moneda)

        if codcli == 99999:
            credit = self.db.fetch_one(
                "SELECT FIRST 1 CBV_TOTALD, CBV_IMPCOB, CBV_CODMON FROM CABDOCV WHERE CBV_NUMEMP=? AND "
                "CBV_TIPDOC='C' AND CBV_CODCLI=? AND CBV_SUBCLI=?",
                (self.settings.empresa, codcli, subcli),
            )
            if credit:
                subtract_rows([credit], "CBV_TOTALD", "CBV_CODMON", "CBV_IMPCOB")
            rows = self.db.fetch_all(
                "SELECT SUM(CBV_TOTALD-CBV_IMPCOB) AS IMPORTE, CBV_CODMON FROM CABDOCV WHERE CBV_NUMEMP=? "
                "AND CBV_TIPDOC='F' AND CBV_CODPAG=0 AND CBV_IMPCOB<CBV_TOTALD AND CBV_TOTALD>0 "
                "AND CBV_CODCLI=? AND CBV_SUBCLI=? GROUP BY CBV_CODMON",
                (self.settings.empresa, codcli, subcli),
            )
            subtract_rows(rows, "IMPORTE", "CBV_CODMON")
        else:
            sub_clause = "1=1" if agrupa else "CBV_SUBCLI=?"
            params: tuple[Any, ...] = (self.settings.empresa, codcli) if agrupa else (self.settings.empresa, codcli, subcli)
            rows = self.db.fetch_all(
                f"SELECT SUM(CBV_TOTALD-CBV_IMPCOB) AS IMPORTE, CBV_CODMON FROM CABDOCV WHERE CBV_NUMEMP=? "
                f"AND CBV_TIPDOC='A' AND CBV_CODCLI=? AND {sub_clause} AND CBV_SITUAC='P' GROUP BY CBV_CODMON",
                params,
            )
            subtract_rows(rows, "IMPORTE", "CBV_CODMON")

            eff_clause = "1=1" if agrupa else "CBVE_SUBCLI=?"
            eff_params: tuple[Any, ...] = (self.settings.empresa, codcli) if agrupa else (self.settings.empresa, codcli, subcli)
            rows = self.db.fetch_all(
                f"SELECT SUM(CBVE_IMPORT) AS CBVE_IMPORT, SUM(CBVE_IMPCOB) AS CBVE_IMPCOB, CBVE_CODMON "
                f"FROM CABDOCVE WHERE CBVE_NUMEMP=? AND CBVE_TIPDOC='F' AND CBVE_CODCLI=? AND {eff_clause} "
                f"AND CBVE_FECCAN IS NULL GROUP BY CBVE_CODMON",
                eff_params,
            )
            subtract_rows(rows, "CBVE_IMPORT", "CBVE_CODMON", "CBVE_IMPCOB")

            rows = self.db.fetch_all(
                f"SELECT SUM(CBV_TOTALD-CBV_IMPCOB) AS IMPORTE, CBV_CODMON FROM CABDOCV WHERE CBV_NUMEMP=? "
                f"AND CBV_TIPDOC='F' AND CBV_CODPAG=0 AND CBV_IMPCOB<CBV_TOTALD AND CBV_TOTALD>0 "
                f"AND CBV_CODCLI=? AND {sub_clause} GROUP BY CBV_CODMON",
                params,
            )
            subtract_rows(rows, "IMPORTE", "CBV_CODMON")
            if self.parameter("RIEPED", "").upper() == "S":
                rows = self.db.fetch_all(
                    f"SELECT SUM(CBV_TOTALD) AS IMPORTE, CBV_CODMON FROM CABDOCV WHERE CBV_NUMEMP=? "
                    f"AND CBV_TIPDOC='P' AND CBV_CODCLI=? AND {sub_clause} GROUP BY CBV_CODMON",
                    params,
                )
                subtract_rows(rows, "IMPORTE", "CBV_CODMON")
        return riesgo, moneda

    def _actualiza_riesgo_cliente(self, cbv: dict[str, Any]) -> dict[str, Any] | None:
        result = self._riesgo_actual(int(cbv["CBV_CODCLI"]), int(cbv["CBV_SUBCLI"]))
        if result is None:
            return None
        riesgo, moneda = result
        warning = ""
        if cbv["CBV_TIPDOC"] in ("A", "C") and riesgo < 0:
            warning = f"Se ha superado el riesgo del cliente en {-riesgo} {moneda}"
        user = f"{self.settings.centro} {cbv.get('CBV_USUMOD') or ''}"[:15]
        self.db.execute(
            "UPDATE CLIEN SET CLI_RIESGOA=?, CLI_FECCOM=?, CLI_FECMOD=?, CLI_USUMOD=? WHERE "
            "CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
            (
                riesgo, cbv.get("CBV_FECHA"), cbv.get("CBV_FECMOD") or datetime.now(), user,
                cbv["CBV_NUMEMP"], cbv["CBV_CODCLI"], cbv["CBV_SUBCLI"],
            ),
        )
        return {"valor": riesgo, "moneda": moneda, "warning": warning}

    @staticmethod
    def _effect_type_label(tipo: Any) -> str:
        value = str(tipo or "").strip().upper()
        return {
            "R": "Recibo",
            "I": "Impagado",
            "E": "Giro negociado",
            "N": "Giro no negociado",
            "T": "Transferencia",
            "O": "Reembolso",
            "G": "Giro",
        }.get(value, value or "Sin tipo")

    @staticmethod
    def _effect_status(row: dict[str, Any], today: date) -> str:
        if row.get("CBVE_FECCAN"):
            return "cobrado"
        due = FaroPhase1Service._parse_optional_date(row.get("CBVE_FECVTO"))
        if due and due <= today:
            return "vencido"
        return "pendiente"

    @staticmethod
    def _is_remitted_effect(row: dict[str, Any]) -> bool:
        return int(row.get("CBVE_EJEREM") or 0) != 0 or int(row.get("CBVE_CODREM") or 0) != 0

    def _cartera_effect_where(self, args: dict[str, Any]) -> tuple[list[str], list[Any]]:
        where = ["CBVE_NUMEMP=?"]
        params: list[Any] = [self.settings.empresa]
        if args.get("centro") not in (None, "", 0):
            where.append("CBVE_CENTRO=?")
            params.append(int(args["centro"]))
        tipo_doc = str(args.get("tipo_documento", "F") or "F").strip().upper()
        if tipo_doc:
            where.append("CBVE_TIPDOC=?")
            params.append(tipo_doc[:1])
        if args.get("cliente") not in (None, "", 0):
            where.append("CBVE_CODCLI=?")
            params.append(int(args["cliente"]))
        if args.get("subcliente") not in (None, "", 0):
            where.append("CBVE_SUBCLI=?")
            params.append(int(args["subcliente"]))
        if args.get("cliente_desde") not in (None, "", 0):
            where.append("CBVE_CODCLI>=?")
            params.append(int(args["cliente_desde"]))
        if args.get("cliente_hasta") not in (None, "", 0):
            where.append("CBVE_CODCLI<=?")
            params.append(int(args["cliente_hasta"]))
        if args.get("ejercicio") not in (None, "", 0):
            where.append("CBVE_EJERCI=?")
            params.append(int(args["ejercicio"]))
        if str(args.get("serie") or "").strip():
            where.append("CBVE_SERIE=?")
            params.append(str(args["serie"]).strip())
        if str(args.get("tipo_efecto") or "").strip():
            where.append("CBVE_TIPOEF=?")
            params.append(str(args["tipo_efecto"]).strip().upper()[:1])
        for arg_name, field, op in (
            ("fecha_desde", "CBVE_FECHA", ">="),
            ("fecha_hasta", "CBVE_FECHA", "<="),
            ("vencimiento_desde", "CBVE_FECVTO", ">="),
            ("vencimiento_hasta", "CBVE_FECVTO", "<="),
        ):
            parsed = self._parse_optional_date(args.get(arg_name))
            if parsed:
                where.append(f"{field}{op}?")
                params.append(parsed)
        situacion = str(args.get("situacion", "") or "").strip().lower()
        if situacion in {"pendiente", "pendientes"}:
            where.append("CBVE_FECCAN IS NULL")
        elif situacion in {"cobrado", "cobrados", "cancelado", "cancelados"}:
            where.append("CBVE_FECCAN IS NOT NULL")
        elif situacion in {"vencido", "vencidos"}:
            where.append("CBVE_FECCAN IS NULL")
            where.append("CBVE_FECVTO<=?")
            params.append(self._parse_optional_date(args.get("fecha_referencia"), date.today()))
        remesado = str(args.get("remesado", "") or "").strip().upper()
        if remesado == "S":
            where.append("(CBVE_EJEREM<>0 OR CBVE_CODREM<>0)")
        elif remesado == "N":
            where.append("CBVE_EJEREM=0")
            where.append("CBVE_CODREM=0")
        return where, params

    def cartera_effect_details(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = max(1, min(int(args.get("limite", 500) or 500), 5000))
        today = self._parse_optional_date(args.get("fecha_referencia"), date.today()) or date.today()
        where, params = self._cartera_effect_where(args)
        rows = self.db.fetch_all(
            f"""
            SELECT FIRST {limit}
                CBVE_NUMEMP, CBVE_CENTRO, CBVE_TIPDOC, CBVE_TIPAC, CBVE_EJERCI, CBVE_SERIE,
                CBVE_NUMDOC, CBVE_NUMORD, CBVE_TIPGES, CBVE_TIPOEF, CBVE_CODACEP, CBVE_FECHA,
                CBVE_FECVTO, CBVE_IMPORT, CBVE_CODMON, CBVE_CODCLI, CBVE_SUBCLI, CBVE_FECCAN,
                CBVE_IMPCOB, CBVE_IMPGAS, CBVE_FECIMP, CBVE_INDEDI, CBVE_OBSERV, CBVE_EJEREM,
                CBVE_CODREM
            FROM CABDOCVE
            WHERE {" AND ".join(where)}
            ORDER BY CBVE_FECVTO, CBVE_CODCLI, CBVE_SUBCLI, CBVE_EJERCI, CBVE_SERIE, CBVE_NUMDOC, CBVE_NUMORD
            """,
            tuple(params),
        )
        efectos: list[dict[str, Any]] = []
        totals = {"nominal": Decimal("0"), "gastos": Decimal("0"), "cobrado": Decimal("0"), "pendiente": Decimal("0")}
        for row in rows:
            nominal = dec(row.get("CBVE_IMPORT"))
            gastos = dec(row.get("CBVE_IMPGAS"))
            cobrado = dec(row.get("CBVE_IMPCOB"))
            pendiente = Decimal("0") if row.get("CBVE_FECCAN") else nominal + gastos - cobrado
            totals["nominal"] += nominal
            totals["gastos"] += gastos
            totals["cobrado"] += cobrado
            totals["pendiente"] += pendiente
            efectos.append({
                "documento": {
                    "centro": int(row.get("CBVE_CENTRO") or 0),
                    "tipo": str(row.get("CBVE_TIPDOC") or ""),
                    "tipo_acumulado": str(row.get("CBVE_TIPAC") or ""),
                    "ejercicio": int(row.get("CBVE_EJERCI") or 0),
                    "serie": str(row.get("CBVE_SERIE") or ""),
                    "numero": int(row.get("CBVE_NUMDOC") or 0),
                    "orden": int(row.get("CBVE_NUMORD") or 0),
                },
                "cliente": {
                    "codigo": int(row.get("CBVE_CODCLI") or 0),
                    "subcliente": int(row.get("CBVE_SUBCLI") or 0),
                },
                "tipo_efecto": str(row.get("CBVE_TIPOEF") or ""),
                "tipo_efecto_nombre": self._effect_type_label(row.get("CBVE_TIPOEF")),
                "tipo_gestion": str(row.get("CBVE_TIPGES") or ""),
                "aceptacion": str(row.get("CBVE_CODACEP") or ""),
                "fecha": normalize(row.get("CBVE_FECHA")),
                "vencimiento": normalize(row.get("CBVE_FECVTO")),
                "fecha_impagado": normalize(row.get("CBVE_FECIMP")),
                "fecha_cancelacion": normalize(row.get("CBVE_FECCAN")),
                "situacion": self._effect_status(row, today),
                "remesado": self._is_remitted_effect(row),
                "remesa": {
                    "ejercicio": int(row.get("CBVE_EJEREM") or 0),
                    "codigo": int(row.get("CBVE_CODREM") or 0),
                },
                "moneda": str(row.get("CBVE_CODMON") or ""),
                "nominal": normalize(nominal),
                "gastos": normalize(gastos),
                "cobrado": normalize(cobrado),
                "pendiente": normalize(pendiente),
                "editable": str(row.get("CBVE_INDEDI") or ""),
                "observaciones": clean_text_value(row.get("CBVE_OBSERV")),
            })
        return {
            "filtros": normalize(args),
            "referencia": today.isoformat(),
            "totales": {key: normalize(value) for key, value in totals.items()} | {"efectos": len(efectos)},
            "efectos": efectos,
        }

    def cartera_pending_effects_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        data = self.cartera_effect_details({**args, "situacion": args.get("situacion", "pendientes"), "limite": args.get("limite", 5000)})
        today = self._parse_optional_date(args.get("fecha_referencia"), date.today()) or date.today()
        groups: dict[str, dict[str, Any]] = {}
        for item in data["efectos"]:
            key = f"{item['tipo_efecto']}|{item['situacion']}|{'S' if item['remesado'] else 'N'}"
            group = groups.setdefault(key, {
                "tipo_efecto": item["tipo_efecto"],
                "tipo_efecto_nombre": item["tipo_efecto_nombre"],
                "situacion": item["situacion"],
                "remesado": item["remesado"],
                "efectos": 0,
                "nominal": Decimal("0"),
                "cobrado": Decimal("0"),
                "pendiente": Decimal("0"),
                "vencidos": 0,
            })
            group["efectos"] += 1
            group["nominal"] += dec(item["nominal"])
            group["cobrado"] += dec(item["cobrado"])
            group["pendiente"] += dec(item["pendiente"])
            due = self._parse_optional_date(item.get("vencimiento"))
            if item["situacion"] != "cobrado" and due and due <= today:
                group["vencidos"] += 1
        items = [
            {**group, "nominal": normalize(group["nominal"]), "cobrado": normalize(group["cobrado"]), "pendiente": normalize(group["pendiente"])}
            for group in groups.values()
        ]
        items.sort(key=lambda item: dec(item["pendiente"]), reverse=True)
        return {**data, "resumen": items, "efectos": data["efectos"][:max(1, min(int(args.get("limite_detalle", 50) or 50), 500))]}

    def cartera_effects_by_customer(self, args: dict[str, Any]) -> dict[str, Any]:
        data = self.cartera_effect_details({**args, "situacion": args.get("situacion", "pendientes"), "limite": args.get("limite", 5000)})
        groups: dict[tuple[int, int], dict[str, Any]] = {}
        for item in data["efectos"]:
            cli = item["cliente"]
            key = (int(cli["codigo"]), int(cli["subcliente"]))
            group = groups.setdefault(key, {
                "cliente": cli,
                "efectos": 0,
                "pendiente": Decimal("0"),
                "vencido": Decimal("0"),
                "proximo_vencimiento": None,
                "remesado": Decimal("0"),
                "no_remesado": Decimal("0"),
            })
            pendiente = dec(item["pendiente"])
            group["efectos"] += 1
            group["pendiente"] += pendiente
            if item["situacion"] == "vencido":
                group["vencido"] += pendiente
            if item["remesado"]:
                group["remesado"] += pendiente
            else:
                group["no_remesado"] += pendiente
            due = item.get("vencimiento")
            if due and (group["proximo_vencimiento"] is None or due < group["proximo_vencimiento"]):
                group["proximo_vencimiento"] = due
        items = [
            {
                **group,
                "pendiente": normalize(group["pendiente"]),
                "vencido": normalize(group["vencido"]),
                "remesado": normalize(group["remesado"]),
                "no_remesado": normalize(group["no_remesado"]),
            }
            for group in groups.values()
        ]
        items.sort(key=lambda item: dec(item["pendiente"]), reverse=True)
        limit = max(1, min(int(args.get("limite_clientes", args.get("limite_detalle", 100)) or 100), 500))
        return {**data, "clientes": items[:limit], "efectos": data["efectos"][:max(1, min(int(args.get("limite_detalle", 50) or 50), 500))]}

    def cartera_pending_remittance(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.cartera_effect_details({**args, "situacion": "pendientes", "remesado": "N"})

    def cartera_remittance_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = max(1, min(int(args.get("limite", 500) or 500), 5000))
        where = ["R.REM_NUMEMP=?"]
        params: list[Any] = [self.settings.empresa]
        if args.get("ejercicio") not in (None, "", 0):
            where.append("R.REM_EJERCI=?")
            params.append(int(args["ejercicio"]))
        for arg_name, field, op in (
            ("fecha_desde", "R.REM_FECHA", ">="),
            ("fecha_hasta", "R.REM_FECHA", "<="),
        ):
            parsed = self._parse_optional_date(args.get(arg_name))
            if parsed:
                where.append(f"{field}{op}?")
                params.append(parsed)
        if str(args.get("situacion") or "").strip():
            where.append("R.REM_SITUAC=?")
            params.append(str(args["situacion"]).strip().upper()[:1])
        rows = self.db.fetch_all(
            f"""
            SELECT FIRST {limit}
                R.REM_EJERCI, R.REM_CODIGO, R.REM_TIPO, R.REM_FECHA, R.REM_FECCON, R.REM_FECENV,
                R.REM_TOTAL, R.REM_CODMON, R.REM_CODBAN, R.REM_CODSUC, R.REM_DIGITO,
                R.REM_NUMCUE, R.REM_CUECON, R.REM_SITUAC,
                COUNT(E.CBVE_NUMORD) AS EFECTOS,
                SUM(E.CBVE_IMPORT + E.CBVE_IMPGAS - E.CBVE_IMPCOB) AS PENDIENTE_EFECTOS
            FROM REMESA R
            LEFT JOIN CABDOCVE E ON E.CBVE_NUMEMP=R.REM_NUMEMP AND E.CBVE_EJEREM=R.REM_EJERCI AND E.CBVE_CODREM=R.REM_CODIGO
            WHERE {" AND ".join(where)}
            GROUP BY R.REM_EJERCI, R.REM_CODIGO, R.REM_TIPO, R.REM_FECHA, R.REM_FECCON, R.REM_FECENV,
                R.REM_TOTAL, R.REM_CODMON, R.REM_CODBAN, R.REM_CODSUC, R.REM_DIGITO,
                R.REM_NUMCUE, R.REM_CUECON, R.REM_SITUAC
            ORDER BY R.REM_EJERCI DESC, R.REM_CODIGO DESC
            """,
            tuple(params),
        )
        remesas = []
        total = Decimal("0")
        pendiente = Decimal("0")
        for row in rows:
            total += dec(row.get("REM_TOTAL"))
            pendiente += dec(row.get("PENDIENTE_EFECTOS"))
            remesas.append({
                "ejercicio": int(row.get("REM_EJERCI") or 0),
                "codigo": int(row.get("REM_CODIGO") or 0),
                "tipo": str(row.get("REM_TIPO") or ""),
                "fecha": normalize(row.get("REM_FECHA")),
                "fecha_contabilizacion": normalize(row.get("REM_FECCON")),
                "fecha_envio": normalize(row.get("REM_FECENV")),
                "total": normalize(dec(row.get("REM_TOTAL"))),
                "moneda": str(row.get("REM_CODMON") or ""),
                "banco": {
                    "codigo": int(row.get("REM_CODBAN") or 0),
                    "sucursal": int(row.get("REM_CODSUC") or 0),
                    "digito": int(row.get("REM_DIGITO") or 0),
                    "cuenta": str(row.get("REM_NUMCUE") or ""),
                    "cuenta_contable": str(row.get("REM_CUECON") or ""),
                },
                "situacion": str(row.get("REM_SITUAC") or ""),
                "efectos": int(row.get("EFECTOS") or 0),
                "pendiente_efectos": normalize(dec(row.get("PENDIENTE_EFECTOS"))),
            })
        return {
            "filtros": normalize(args),
            "totales": {"remesas": len(remesas), "total": normalize(total), "pendiente_efectos": normalize(pendiente)},
            "remesas": remesas,
        }

    def cartera_customer_credit_risk(self, args: dict[str, Any]) -> dict[str, Any]:
        codcli = int(args["cliente"])
        subcli = int(args.get("subcliente", 0) or 0)
        detail = self._riesgo_actual_detalle(codcli, subcli)
        if detail is None:
            raise FaroError("Cliente no encontrado")
        return detail

    def cartera_customer_credit_risk_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = max(1, min(int(args.get("limite", 100) or 100), 1000))
        where = ["CLI_NUMEMP=?"]
        params: list[Any] = [self.settings.empresa]
        if args.get("cliente_desde") not in (None, "", 0):
            where.append("CLI_CODCLI>=?")
            params.append(int(args["cliente_desde"]))
        if args.get("cliente_hasta") not in (None, "", 0):
            where.append("CLI_CODCLI<=?")
            params.append(int(args["cliente_hasta"]))
        rows = self.db.fetch_all(
            f"""
            SELECT FIRST {limit} CLI_CODCLI, CLI_SUBCLI
            FROM CLIEN
            WHERE {" AND ".join(where)}
            ORDER BY CLI_CODCLI, CLI_SUBCLI
            """,
            tuple(params),
        )
        items = []
        for row in rows:
            detail = self._riesgo_actual_detalle(int(row.get("CLI_CODCLI") or 0), int(row.get("CLI_SUBCLI") or 0))
            if not detail:
                continue
            if bool(args.get("solo_excedidos", False)) and dec(detail["riesgo_actual"]) >= 0:
                continue
            items.append(detail)
        items.sort(key=lambda item: dec(item["riesgo_actual"]))
        return {
            "filtros": normalize(args),
            "totales": {
                "clientes": len(items),
                "excedidos": len([item for item in items if dec(item["riesgo_actual"]) < 0]),
                "riesgo_concedido": normalize(sum((dec(item["riesgo_concedido"]) for item in items), Decimal("0"))),
                "riesgo_actual": normalize(sum((dec(item["riesgo_actual"]) for item in items), Decimal("0"))),
                "consumido": normalize(sum((dec(item["riesgo_consumido"]) for item in items), Decimal("0"))),
            },
            "clientes": items,
        }

    def _riesgo_actual_detalle(self, codcli: int, subcli: int) -> dict[str, Any] | None:
        if codcli == 99999 and subcli == 0:
            return {
                "cliente": {"codigo": codcli, "subcliente": subcli, "nombre": "Cliente contado"},
                "agrupa_subclientes": False,
                "moneda": "E",
                "riesgo_concedido": "-1",
                "riesgo_actual": "-1",
                "riesgo_consumido": "0",
                "excedido": False,
                "componentes": [],
                "warnings": ["Cliente contado especial: el Delphi devuelve riesgo -1."],
            }
        cli = self.db.fetch_one(
            "SELECT CLI_CODCLI, CLI_SUBCLI, CLI_NOMCLI, CLI_RAZSOC, CLI_AGRUPAC, CLI_RIESGO, CLI_RIESGOA, CLI_CODMON "
            "FROM CLIEN WHERE CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
            (self.settings.empresa, codcli, subcli),
        )
        if not cli:
            return None
        cli = normalize(cli)
        moneda = str(cli.get("CLI_CODMON") or "E")
        concedido = dec(cli.get("CLI_RIESGO"))
        actual = concedido
        agrupa = codcli != 99999 and str(cli.get("CLI_AGRUPAC") or "") == "S"
        componentes: list[dict[str, Any]] = []

        def add_component(nombre: str, rows: list[dict[str, Any]], amount_field: str, currency_field: str, paid_field: str | None = None):
            nonlocal actual
            total = Decimal("0")
            for row in rows:
                amount = dec(row.get(amount_field))
                if paid_field:
                    amount -= dec(row.get(paid_field))
                converted = self._risk_convert(amount, str(row.get(currency_field) or moneda), moneda)
                total += converted
                actual -= converted
            componentes.append({"concepto": nombre, "importe": normalize(total), "moneda": moneda, "filas": len(rows)})

        sub_clause = "1=1" if agrupa else "CBV_SUBCLI=?"
        params: tuple[Any, ...] = (self.settings.empresa, codcli) if agrupa else (self.settings.empresa, codcli, subcli)
        rows = self.db.fetch_all(
            f"SELECT SUM(CBV_TOTALD-CBV_IMPCOB) AS IMPORTE, CBV_CODMON FROM CABDOCV WHERE CBV_NUMEMP=? "
            f"AND CBV_TIPDOC='A' AND CBV_CODCLI=? AND {sub_clause} AND CBV_SITUAC='P' GROUP BY CBV_CODMON",
            params,
        )
        add_component("albaranes_pendientes", rows, "IMPORTE", "CBV_CODMON")
        eff_clause = "1=1" if agrupa else "CBVE_SUBCLI=?"
        eff_params: tuple[Any, ...] = (self.settings.empresa, codcli) if agrupa else (self.settings.empresa, codcli, subcli)
        rows = self.db.fetch_all(
            f"SELECT SUM(CBVE_IMPORT) AS CBVE_IMPORT, SUM(CBVE_IMPCOB) AS CBVE_IMPCOB, CBVE_CODMON "
            f"FROM CABDOCVE WHERE CBVE_NUMEMP=? AND CBVE_TIPDOC='F' AND CBVE_CODCLI=? AND {eff_clause} "
            f"AND CBVE_FECCAN IS NULL GROUP BY CBVE_CODMON",
            eff_params,
        )
        add_component("efectos_factura_pendientes", rows, "CBVE_IMPORT", "CBVE_CODMON", "CBVE_IMPCOB")
        rows = self.db.fetch_all(
            f"SELECT SUM(CBV_TOTALD-CBV_IMPCOB) AS IMPORTE, CBV_CODMON FROM CABDOCV WHERE CBV_NUMEMP=? "
            f"AND CBV_TIPDOC='F' AND CBV_CODPAG=0 AND CBV_IMPCOB<CBV_TOTALD AND CBV_TOTALD>0 "
            f"AND CBV_CODCLI=? AND {sub_clause} GROUP BY CBV_CODMON",
            params,
        )
        add_component("facturas_contado_pendientes", rows, "IMPORTE", "CBV_CODMON")
        if self.parameter("RIEPED", "").upper() == "S":
            rows = self.db.fetch_all(
                f"SELECT SUM(CBV_TOTALD) AS IMPORTE, CBV_CODMON FROM CABDOCV WHERE CBV_NUMEMP=? "
                f"AND CBV_TIPDOC='P' AND CBV_CODCLI=? AND {sub_clause} GROUP BY CBV_CODMON",
                params,
            )
            add_component("pedidos_pendientes", rows, "IMPORTE", "CBV_CODMON")
        return {
            "cliente": {
                "codigo": codcli,
                "subcliente": subcli,
                "nombre": clean_text_value(cli.get("CLI_NOMCLI")) or clean_text_value(cli.get("CLI_RAZSOC")),
            },
            "agrupa_subclientes": agrupa,
            "moneda": moneda,
            "riesgo_concedido": normalize(concedido),
            "riesgo_actual": normalize(actual),
            "riesgo_actual_guardado": normalize(cli.get("CLI_RIESGOA")),
            "riesgo_consumido": normalize(concedido - actual),
            "excedido": actual < 0,
            "componentes": componentes,
            "fuente": "Port de RIESGO_ACTUAL: CABDOCV albaranes/facturas contado, CABDOCVE efectos vivos y RIEPED para pedidos.",
        }

    def _update_cabdocv_runtime_fields(self, cbv: dict[str, Any]) -> None:
        # FINALIZAR_CABDOCV llama a GRABAR_CABDOCV('M'), que reescribe todos
        # los campos. En Python los totales se actualizan de forma dirigida;
        # estos son los campos que Grabar_Ticket_Factura modifica despues del
        # INSERT inicial y que, por tanto, tambien hay que persistir.
        self.db.execute(
            "UPDATE CABDOCV SET CBV_IMPCOB=?, CBV_COMREP=?, CBV_FORCOB=?, CBV_OBSERV=?, CBV_CODPAG=?, "
            "CBV_FECMOD=?, CBV_USUMOD=? WHERE CBV_NUMEMP=? AND CBV_CENTRO=? AND CBV_TIPDOC=? AND "
            "CBV_TIPAC=? AND CBV_EJERCI=? AND CBV_SERIE=? AND CBV_NUMDOC=?",
            (
                cbv.get("CBV_IMPCOB", 0), cbv.get("CBV_COMREP", 0), cbv.get("CBV_FORCOB", ""),
                cbv.get("CBV_OBSERV", ""), cbv.get("CBV_CODPAG", 0), cbv.get("CBV_FECMOD") or datetime.now(),
                cbv.get("CBV_USUMOD", ""), cbv["CBV_NUMEMP"], cbv["CBV_CENTRO"], cbv["CBV_TIPDOC"],
                cbv["CBV_TIPAC"], cbv["CBV_EJERCI"], cbv["CBV_SERIE"], cbv["CBV_NUMDOC"],
            ),
        )

    def _next_opecaj_line(self, opc: dict[str, Any]) -> int:
        row = self.db.fetch_one(
            "SELECT MAX(OPC_NUMLIN) AS OPC_NUMLIN FROM OPECAJ WHERE OPC_NUMEMP=? AND OPC_CENTRO=? "
            "AND OPC_EJERCI=? AND OPC_CAJA=?",
            (opc["OPC_NUMEMP"], opc["OPC_CENTRO"], opc["OPC_EJERCI"], opc["OPC_CAJA"]),
        )
        current = row.get("OPC_NUMLIN") if row else None
        return int(current) + 1 if current is not None else 1

    def _insert_opecaj(self, opc: dict[str, Any]) -> int:
        numlin = int(opc.get("OPC_NUMLIN") or 0) or self._next_opecaj_line(opc)
        while numlin <= 999999:
            exists = self.db.fetch_one(
                "SELECT FIRST 1 OPC_NUMLIN FROM OPECAJ WHERE OPC_NUMEMP=? AND OPC_CENTRO=? AND OPC_EJERCI=? "
                "AND OPC_CAJA=? AND OPC_NUMLIN=?",
                (opc["OPC_NUMEMP"], opc["OPC_CENTRO"], opc["OPC_EJERCI"], opc["OPC_CAJA"], numlin),
            )
            if not exists:
                break
            numlin += 1
        if numlin > 999999:
            raise FaroError("Error en la numeracion de OPECAJ")
        opc["OPC_NUMLIN"] = numlin
        cols = [
            "OPC_NUMEMP", "OPC_CENTRO", "OPC_EJERCI", "OPC_CAJA", "OPC_NUMLIN", "OPC_VENDED", "OPC_HORA",
            "OPC_TIPOPE", "OPC_IMPORT", "OPC_CODMON", "OPC_FORPAG", "OPC_OBSERV", "OPC_TIPDOC", "OPC_TIPAC",
            "OPC_EJEDOC", "OPC_SERIE", "OPC_NUMDOC", "OPC_NUMORD", "OPC_CODCLI", "OPC_SUBCLI", "OPC_SITUAC",
            "OPC_FECSIT",
        ]
        placeholders = ",".join(["?"] * len(cols))
        self.db.execute(f"INSERT INTO OPECAJ ({', '.join(cols)}) VALUES ({placeholders})", tuple(opc.get(c) for c in cols))
        return numlin

    def _ticket_payment_op(self, cbv: dict[str, Any], amount: Decimal, method: str) -> dict[str, Any]:
        if cbv["CBV_TIPDOC"] == "T":
            observ = "Cobro de Ticket"
        elif cbv["CBV_TIPDOC"] == "F":
            observ = "Cobro de Factura Contado"
        elif cbv["CBV_TIPDOC"] == "A":
            observ = "Cobro de Albaran"
        else:
            observ = "Cobro de Documento"
        return {
            "OPC_NUMEMP": cbv["CBV_NUMEMP"], "OPC_CENTRO": cbv["CBV_CENTRO"], "OPC_EJERCI": cbv["CBV_EJERCI"],
            "OPC_CAJA": cbv["CBV_CAJA"], "OPC_NUMLIN": 0, "OPC_VENDED": cbv["CBV_USUMOD"],
            "OPC_HORA": datetime.now(), "OPC_TIPOPE": "E", "OPC_IMPORT": amount, "OPC_CODMON": cbv["CBV_CODMON"],
            "OPC_FORPAG": method, "OPC_OBSERV": observ, "OPC_TIPDOC": cbv["CBV_TIPDOC"], "OPC_TIPAC": cbv["CBV_TIPAC"],
            "OPC_EJEDOC": cbv["CBV_EJERCI"], "OPC_SERIE": cbv["CBV_SERIE"], "OPC_NUMDOC": cbv["CBV_NUMDOC"],
            "OPC_NUMORD": 0, "OPC_CODCLI": cbv["CBV_CODCLI"], "OPC_SUBCLI": cbv["CBV_SUBCLI"],
            "OPC_SITUAC": 0, "OPC_FECSIT": cbv["CBV_FECHA"],
        }

    def _print_ticket_best_effort(self, cbv: dict[str, Any]) -> dict[str, Any]:
        """Port del envio TCP a localhost:45000; la impresion nunca revierte el documento ya confirmado."""
        try:
            row = self.db.fetch_one(
                "SELECT FIRST 1 TIV_IMPRES, TIV_LISTAD FROM TIPVEN WHERE TIV_NUMEMP=? AND TIV_TIPDOC=? "
                "AND TIV_TIPAC='0' ORDER BY TIV_CODIGO",
                (self.settings.empresa, cbv["CBV_TIPDOC"]),
            )
            if not row:
                return {"intentada": False, "enviada": False}
            impresora = str(row.get("TIV_IMPRES") or "")
            listado_raw = str(row.get("TIV_LISTAD") or "")
            parts = listado_raw.split()
            listado = parts[0] if parts else ""
            plantilla = parts[1] if len(parts) > 1 else ""
            exe_dir = os.getenv("FARO_DIR_PROGRAMAS", "")
            message = (
                f"{exe_dir}{listado}.exe {cbv['CBV_NUMEMP']} {cbv['CBV_CENTRO']} {cbv['CBV_TIPDOC']} "
                f"{cbv['CBV_TIPAC']} {cbv['CBV_EJERCI']} {cbv['CBV_SERIE']} {cbv['CBV_NUMDOC']} {impresora} "
                f"1 D c:\\FaroERP\\Faro_local.ini 1{plantilla}"
            )
            host = os.getenv("FARO_PRINT_HOST", "localhost")
            port = int(os.getenv("FARO_PRINT_PORT", "45000"))
            with socket.create_connection((host, port), timeout=float(os.getenv("FARO_PRINT_TIMEOUT", "0.5"))) as sock:
                sock.sendall((message + "\r\n").encode("cp1252", errors="replace"))
            return {"intentada": True, "enviada": True, "mensaje": message}
        except Exception as exc:
            # Igual que la intencion del bloque try/except Delphi: un problema
            # de impresion no invalida una venta/factura ya grabada.
            return {"intentada": True, "enviada": False, "error": str(exc)}

    def save_ticket_invoice(
        self,
        caja: Any,
        efectivo: Any,
        tarjeta: Any,
        otros: Any,
        autorizacion: str,
        total: Any,
        venta: str,
        centro: Any,
        codcli: Any,
        subcli: Any,
        texto: str,
        tipdoc: str,
        usuario: str,
        serie: str = "",
    ) -> dict[str, Any]:
        """Migra Grabar_Ticket_Factura completamente a Python nativo."""
        empresa = self.settings.empresa
        centro_i, codcli_i, subcli_i, caja_i = int(centro), int(codcli), int(subcli), int(caja)
        tipdoc_s = str(tipdoc or "").strip()
        if tipdoc_s not in ("T", "F", "A", "C"):
            # El Delphi acepta mas tipos, pero estos son los documentales con
            # semantica definida de cobro. No se impide otro valor no vacio.
            if not tipdoc_s:
                raise FaroError("TIPDOC no puede estar vacio en Grabar_Ticket_Factura.")
        today, now = date.today(), datetime.now()
        serie_s = str(serie or "").strip()
        if not serie_s:
            if tipdoc_s == "T":
                # GRABAR_TICKET (Delphi): la serie de un ticket no sale de
                # 'T'+centro sino de 'TT'+centro, y si esa fila de
                # PARAMETROS no existe, se calcula con SERIE_TICKET en vez
                # de quedar vacia.
                serie_s = self._serie_ticket(centro_i)
            else:
                serie_lookup = "FC" if tipdoc_s == "F" else tipdoc_s
                serie_s = self._serie_documento(serie_lookup, centro_i)
        cbv: dict[str, Any] = {
            "CBV_NUMEMP": empresa, "CBV_CENTRO": centro_i, "CBV_TIPDOC": tipdoc_s, "CBV_TIPAC": "0",
            "CBV_EJERCI": today.year, "CBV_SERIE": serie_s, "CBV_NUMDOC": 0,
            "CBV_CAJA": caja_i, "CBV_FECHA": today, "CBV_FECHAE": today, "CBV_CODCLI": codcli_i,
            "CBV_SUBCLI": subcli_i, "CBV_CODREP": 0, "CBV_COMREP": Decimal("0"), "CBV_NOMCLI": "",
            "CBV_CIF": "", "CBV_DOMCLI": "", "CBV_CODPOS": "", "CBV_POBLAC": "", "CBV_CODPAG": 0,
            "CBV_FORENV": 0, "CBV_PORDTO": Decimal("0"), "CBV_IMPPOR": Decimal("0"),
            "CBV_BASIMP1": Decimal("0"), "CBV_PORIVA1": Decimal("0"), "CBV_PORREQ1": Decimal("0"),
            "CBV_BASIMP2": Decimal("0"), "CBV_PORIVA2": Decimal("0"), "CBV_PORREQ2": Decimal("0"),
            "CBV_BASIMP3": Decimal("0"), "CBV_PORIVA3": Decimal("0"), "CBV_PORREQ3": Decimal("0"),
            "CBV_BASIMP4": Decimal("0"), "CBV_PORIVA4": Decimal("0"), "CBV_PORREQ4": Decimal("0"),
            "CBV_TOTALS": Decimal("0"), "CBV_TOTALD": Decimal("0"), "CBV_IMPCOB": Decimal("0"),
            "CBV_CODMON": "E", "CBV_FORCOB": "", "CBV_NUMTAR": 0, "CBV_TIPVEN": 0,
            "CBV_SITUAC": "P", "CBV_INDEDI": "N", "CBV_OBSERV": "", "CBV_EJERCID": 0,
            "CBV_TIPDOCD": "", "CBV_SERIED": "", "CBV_NUMDOCD": 0, "CBV_FECMOD": now,
            "CBV_USUMOD": str(usuario or ""), "CBV_REFCLI": "", "CBV_RETIRA": "", "CBV_CODTAR": "",
        }
        texto_s = "" if texto is None else str(texto).strip()
        if texto_s == "[]":
            texto_s = ""
        origin_sale = None
        origin_sale_key: tuple[int, int] | None = None
        try:
            if str(venta or "").strip():
                sale_year, sale_num = self._parse_vencaj_key(str(venta))
                origin_sale_key = (sale_year, sale_num)
                code = self._vencaj_semaphore_code(sale_year, sale_num)
                if not self._probe_vencaj_lock(code, commit=False):
                    self.db.rollback()
                    return {"documento": "", "blocked": True, "message": "Venta bloqueada", "datasnap_text": "Venta bloqueada"}
                origin_sale = self.db.fetch_one(
                    "SELECT * FROM VENCAJ WHERE CBV_NUMEMP=? AND CBV_EJERCI=? AND CBV_NUMDOC=?",
                    (empresa, sale_year, sale_num),
                )
                if not origin_sale:
                    raise FaroError(f"Venta abierta no encontrada: {venta}")
                origin_sale = normalize(origin_sale)
                for key in (
                    "CBV_CODREP", "CBV_NOMCLI", "CBV_CIF", "CBV_DOMCLI", "CBV_CODPOS", "CBV_POBLAC",
                    "CBV_CODPAG", "CBV_FORENV", "CBV_PORDTO", "CBV_TIPVEN",
                ):
                    cbv[key] = origin_sale.get(key, cbv[key])
            elif (codcli_i != 99999) or (subcli_i != 0):
                cliente = self._busqueda_clien_pedido(codcli_i, subcli_i)
                cbv.update({
                    "CBV_CODREP": cliente["codrep"], "CBV_NOMCLI": cliente["razsoc"], "CBV_CIF": cliente["cif"],
                    "CBV_DOMCLI": cliente["domici"], "CBV_CODPOS": cliente["codpos"], "CBV_POBLAC": cliente["poblac"],
                    "CBV_FORENV": cliente["forenv"], "CBV_PORDTO": cliente["dtoesp"],
                    "CBV_TIPVEN": self._busqueda_tipven2(tipdoc_s, "0"),
                })
                if tipdoc_s != "F":
                    cbv["CBV_CODPAG"] = cliente["forpag"]
                else:
                    fpgcon = self.parameter("FPGCON", "0")
                    try:
                        if fpgcon != "0":
                            cbv["CBV_CODPAG"] = int(fpgcon)
                    except ValueError:
                        pass
            else:
                cbv["CBV_TIPVEN"] = self._busqueda_tipven2(tipdoc_s, "0")

            def money(value: Any, name: str, allow_empty: bool = True) -> Decimal:
                text = "" if value is None else str(value).strip()
                if text == "" and allow_empty:
                    return Decimal("0")
                try:
                    return Decimal(text.replace(",", "."))
                except Exception as exc:
                    raise FaroError(f"Importe no valido para {name}: {value!r}") from exc

            cash = money(efectivo, "EFECTIVO")
            card = money(tarjeta, "TARJETA")
            other = money(otros, "OTROS")
            total_expected = money(total, "TOTAL", allow_empty=False)
            total_collected = cash + card + other
            cash_applied = cash
            if total_expected > 0 and total_collected > total_expected:
                cbv["CBV_IMPCOB"] = total_expected
                cbv["CBV_COMREP"] = total_collected
                cash_applied = cash - (total_collected - total_expected)
            else:
                cbv["CBV_IMPCOB"] = total_collected
                cbv["CBV_COMREP"] = total_collected
            if str(efectivo or "").strip() and str(tarjeta or "").strip():
                cbv["CBV_FORCOB"] = "M"
            if str(autorizacion or ""):
                cbv["CBV_OBSERV"] = str(autorizacion)

            cbv["CBV_NUMDOC"] = self._insert_cabdocv_order(cbv)
            line_count = canon_count = gift_count = 0
            if origin_sale_key is not None and not texto_s:
                line_count = self._copy_open_sale_lines_to_document(cbv, *origin_sale_key)
            if origin_sale is not None:
                sale_year, sale_num = origin_sale_key if origin_sale_key is not None else self._parse_vencaj_key(str(venta))
                self.db.execute("DELETE FROM VENCAJ WHERE CBV_NUMEMP=? AND CBV_EJERCI=? AND CBV_NUMDOC=?", (empresa, sale_year, sale_num))
                self.db.execute("DELETE FROM VENCUR WHERE DMV_NUMEMP=? AND DMV_EJERCI=? AND DMV_NUMDOC=?", (empresa, sale_year, sale_num))

            payments: list[dict[str, Any]] = []
            if str(efectivo or "").strip():
                cbv["CBV_FORCOB"] = "E"
                opc = self._ticket_payment_op(cbv, cash_applied, "E")
                opc["OPC_NUMLIN"] = self._insert_opecaj(opc)
                payments.append(opc)
            if str(tarjeta or "").strip():
                cbv["CBV_FORCOB"] = "T"
                opc = self._ticket_payment_op(cbv, card, "T")
                opc["OPC_NUMLIN"] = self._insert_opecaj(opc)
                payments.append(opc)
            if str(otros or "").strip():
                cbv["CBV_FORCOB"] = "O"
                opc = self._ticket_payment_op(cbv, other, "O")
                opc["OPC_NUMLIN"] = self._insert_opecaj(opc)
                payments.append(opc)

            numlin, rest = 10, texto_s
            while rest:
                raw, rest = self._procesar_cadena(rest, "#")
                if raw == "":
                    break
                line = self._parse_document_sale_line(cbv, numlin, raw)
                # Grabar_Ticket_Factura SI distingue C/X una vez ya ha leido
                # PREVEN (a diferencia de la peculiaridad de Grabar_Venta).
                if str(line.get("DMV_CODART") or "") == "":
                    line["DMV_TIPLIN"] = "C" if dec(line.get("DMV_PREVEN")) == 0 else "X"
                line = self._grabar_detmov_g_albaran(line)
                line_count += 1
                canon_count += self._record_document_canon(line, codcli_i)
                gift_count += self._record_document_gifts(line)
                numlin += 10

            final = self._finalizar_documento_venta(cbv)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        printing = self._print_ticket_best_effort(cbv)
        document = f"{cbv['CBV_TIPDOC']}-{cbv['CBV_EJERCI']}-{cbv['CBV_SERIE']}-{cbv['CBV_NUMDOC']}"
        return {
            "documento": document, "tipdoc": cbv["CBV_TIPDOC"], "ejerci": cbv["CBV_EJERCI"],
            "serie": cbv["CBV_SERIE"], "numdoc": cbv["CBV_NUMDOC"], "venta_origen": str(venta or ""),
            "venta_eliminada": bool(origin_sale), "blocked": False, "lineas_principales": line_count,
            "lineas_canon": canon_count, "lineas_regalo": gift_count, "cobros": [normalize(x) for x in payments],
            "totals": normalize((final.get("totals") or {}).get("totals")),
            "totald": normalize((final.get("totals") or {}).get("totald")),
            "efectos": int(final.get("efectos") or 0), "riesgo": normalize(final.get("riesgo")),
            "impresion": printing, "datasnap_text": document,
        }

    def save_sales_document(
        self,
        venta: str,
        centro: Any,
        codcli: Any,
        subcli: Any,
        texto: str,
        tipdoc: str,
        usuario: str,
        serie: str = "",
    ) -> dict[str, Any]:
        """Migra Grabar_Albaran a CABDOCV/DETMOV Python nativo.

        Si ``venta`` contiene ``EJERCI-NUMDOC`` se copian los datos de cliente
        de la venta abierta y esta se elimina en la misma transaccion. Si esta
        vacia, los datos se cargan de CLIEN. Las lineas usan el mismo protocolo
        de 14 campos que Grabar_Venta.
        """
        empresa = self.settings.empresa
        centro_i, codcli_i, subcli_i = int(centro), int(codcli), int(subcli)
        tipdoc_s, usuario_s = str(tipdoc or "").strip(), str(usuario or "")
        serie_s = str(serie or "").strip()
        if not tipdoc_s:
            raise FaroError("TIPDOC no puede estar vacio en Grabar_Albaran.")
        today, now = date.today(), datetime.now()
        cbv: dict[str, Any] = {
            "CBV_NUMEMP": empresa, "CBV_CENTRO": centro_i, "CBV_TIPDOC": tipdoc_s, "CBV_TIPAC": "0",
            "CBV_EJERCI": today.year, "CBV_SERIE": serie_s or self._serie_documento(tipdoc_s, centro_i), "CBV_NUMDOC": 0,
            "CBV_CAJA": 1, "CBV_FECHA": today, "CBV_FECHAE": today, "CBV_CODCLI": codcli_i,
            "CBV_SUBCLI": subcli_i, "CBV_CODREP": 0, "CBV_COMREP": Decimal("0"), "CBV_NOMCLI": "",
            "CBV_CIF": "", "CBV_DOMCLI": "", "CBV_CODPOS": "", "CBV_POBLAC": "", "CBV_CODPAG": 0,
            "CBV_FORENV": 0, "CBV_PORDTO": Decimal("0"), "CBV_IMPPOR": Decimal("0"),
            "CBV_BASIMP1": Decimal("0"), "CBV_PORIVA1": Decimal("0"), "CBV_PORREQ1": Decimal("0"),
            "CBV_BASIMP2": Decimal("0"), "CBV_PORIVA2": Decimal("0"), "CBV_PORREQ2": Decimal("0"),
            "CBV_BASIMP3": Decimal("0"), "CBV_PORIVA3": Decimal("0"), "CBV_PORREQ3": Decimal("0"),
            "CBV_BASIMP4": Decimal("0"), "CBV_PORIVA4": Decimal("0"), "CBV_PORREQ4": Decimal("0"),
            "CBV_TOTALS": Decimal("0"), "CBV_TOTALD": Decimal("0"), "CBV_IMPCOB": Decimal("0"),
            "CBV_CODMON": "E", "CBV_FORCOB": "", "CBV_NUMTAR": 0, "CBV_TIPVEN": 0,
            "CBV_SITUAC": "P", "CBV_INDEDI": "N", "CBV_OBSERV": "", "CBV_EJERCID": 0,
            "CBV_TIPDOCD": "", "CBV_SERIED": "", "CBV_NUMDOCD": 0, "CBV_FECMOD": now,
            "CBV_USUMOD": usuario_s, "CBV_REFCLI": "", "CBV_RETIRA": "", "CBV_CODTAR": "",
        }
        origin_sale = None
        try:
            if str(venta or "").strip():
                sale_year, sale_num = self._parse_vencaj_key(venta)
                code = self._vencaj_semaphore_code(sale_year, sale_num)
                if not self._probe_vencaj_lock(code, commit=False):
                    self.db.rollback()
                    return {
                        "documento": "", "venta": str(venta), "blocked": True,
                        "message": "Venta bloqueada", "datasnap_text": "Venta bloqueada",
                    }
                origin_sale = self.db.fetch_one(
                    "SELECT * FROM VENCAJ WHERE CBV_NUMEMP=? AND CBV_EJERCI=? AND CBV_NUMDOC=?",
                    (empresa, sale_year, sale_num),
                )
                if not origin_sale:
                    raise FaroError(f"Venta abierta no encontrada: {venta}")
                origin_sale = normalize(origin_sale)
                for key in (
                    "CBV_CODREP", "CBV_NOMCLI", "CBV_CIF", "CBV_DOMCLI", "CBV_CODPOS", "CBV_POBLAC",
                    "CBV_CODPAG", "CBV_FORENV", "CBV_PORDTO", "CBV_TIPVEN",
                ):
                    cbv[key] = origin_sale.get(key, cbv[key])
                # La eliminacion se difiere hasta despues de numerar/insertar CABDOCV.
                # _insert_cabdocv_order puede hacer rollback durante un reintento por
                # colision de numeracion; borrarla antes podria deshacer el borrado y
                # terminar generando el documento sin consumir realmente VENCAJ.
            else:
                cliente = self._busqueda_clien_pedido(codcli_i, subcli_i)
                cbv.update({
                    "CBV_CODREP": cliente["codrep"], "CBV_NOMCLI": cliente["razsoc"], "CBV_CIF": cliente["cif"],
                    "CBV_DOMCLI": cliente["domici"], "CBV_CODPOS": cliente["codpos"], "CBV_POBLAC": cliente["poblac"],
                    "CBV_CODPAG": cliente["forpag"], "CBV_FORENV": cliente["forenv"], "CBV_PORDTO": cliente["dtoesp"],
                    "CBV_TIPVEN": self._busqueda_tipven2(tipdoc_s, "0"),
                })

            cbv["CBV_NUMDOC"] = self._insert_cabdocv_order(cbv)
            if origin_sale is not None:
                sale_year, sale_num = self._parse_vencaj_key(venta)
                self.db.execute(
                    "DELETE FROM VENCAJ WHERE CBV_NUMEMP=? AND CBV_EJERCI=? AND CBV_NUMDOC=?",
                    (empresa, sale_year, sale_num),
                )
                self.db.execute(
                    "DELETE FROM VENCUR WHERE DMV_NUMEMP=? AND DMV_EJERCI=? AND DMV_NUMDOC=?",
                    (empresa, sale_year, sale_num),
                )
            line_count = canon_count = gift_count = 0
            numlin, rest = 10, str(texto or "")
            while rest:
                raw, rest = self._procesar_cadena(rest, "#")
                if raw == "":
                    break
                line = self._parse_document_sale_line(cbv, numlin, raw)
                line = self._grabar_detmov_g_albaran(line)
                line_count += 1
                canon_count += self._record_document_canon(line, codcli_i)
                gift_count += self._record_document_gifts(line)
                numlin += 10

            final = self._finalizar_documento_venta(cbv)
            totals = final.get("totals") or {}
            if tipdoc_s == "A" and totals and dec(totals.get("totals")) > 0:
                minimum = self._minimum_delivery_amount(codcli_i, subcli_i)
                if minimum is not None and minimum > dec(totals.get("totals")):
                    raise FaroError(f"No se pueden hacer albaranes de menos de {minimum} EUR")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        document = f"{tipdoc_s}-{cbv['CBV_EJERCI']}-{cbv['CBV_SERIE']}-{cbv['CBV_NUMDOC']}"
        return {
            "documento": document, "tipdoc": tipdoc_s, "ejerci": cbv["CBV_EJERCI"], "serie": cbv["CBV_SERIE"],
            "numdoc": cbv["CBV_NUMDOC"], "venta_origen": str(venta or ""), "venta_eliminada": bool(origin_sale),
            "blocked": False, "lineas_principales": line_count, "lineas_canon": canon_count,
            "lineas_regalo": gift_count, "totals": normalize((final.get("totals") or {}).get("totals")),
            "totald": normalize((final.get("totals") or {}).get("totald")),
            # El Delphi tenia la impresion comentada; no hay efecto externo que portar aqui.
            "impresion_omitida": True, "datasnap_text": document,
        }

    def _cabdocv_to_open_sale(self, pedido: dict[str, Any], tipdoc: str) -> dict[str, Any]:
        cols = [
            "CBV_NUMEMP", "CBV_EJERCI", "CBV_NUMDOC", "CBV_CAJA", "CBV_USUMOD", "CBV_TIPDOC", "CBV_TIPAC",
            "CBV_SERIE", "CBV_FECHA", "CBV_FECHAE", "CBV_CODCLI", "CBV_SUBCLI", "CBV_CODREP", "CBV_COMREP",
            "CBV_NOMCLI", "CBV_CIF", "CBV_DOMCLI", "CBV_CODPOS", "CBV_POBLAC", "CBV_CODPAG", "CBV_FORENV",
            "CBV_PORDTO", "CBV_IMPPOR", "CBV_BASIMP1", "CBV_PORIVA1", "CBV_PORREQ1", "CBV_BASIMP2",
            "CBV_PORIVA2", "CBV_PORREQ2", "CBV_BASIMP3", "CBV_PORIVA3", "CBV_PORREQ3", "CBV_BASIMP4",
            "CBV_PORIVA4", "CBV_PORREQ4", "CBV_TOTALS", "CBV_TOTALD", "CBV_IMPCOB", "CBV_CODMON", "CBV_FORCOB",
            "CBV_NUMTAR", "CBV_TIPVEN", "CBV_SITUAC", "CBV_OBSERV", "CBV_FECMOD", "CBV_REFCLI", "CBV_RETIRA",
            "CBV_CODTAR",
        ]
        v = {key: pedido.get(key) for key in cols}
        today = date.today()
        v["CBV_TIPDOC"] = tipdoc
        v["CBV_EJERCI"] = today.year
        v["CBV_FECHA"] = today
        centro_pedido = pedido.get("CBV_CENTRO")
        if tipdoc == "A":
            serie = self._serie_albaran_cliente(int(v["CBV_CODCLI"]), int(v["CBV_SUBCLI"]))
            v["CBV_SERIE"] = serie if serie else self._serie_documento("A", centro_pedido)
        elif tipdoc == "F":
            v["CBV_SERIE"] = self._serie_documento("FC", centro_pedido)
        else:
            # Ticket: misma regla 'TT'+centro (+ fallback SERIE_TICKET) que
            # save_ticket_invoice, no 'T'+centro.
            v["CBV_SERIE"] = self._serie_ticket(centro_pedido)
        v["CBV_NUMDOC"] = 0
        v["CBV_TIPVEN"] = self._formato_documento_cliente(
            tipdoc, str(v.get("CBV_TIPAC") or "0"), int(v["CBV_CODCLI"]), int(v["CBV_SUBCLI"])
        )
        v["CBV_FECMOD"] = datetime.now()  # GRABAR_VENCAJ('G') lo fuerza a NOW.
        return v

    def _insert_open_sale_numbered(self, cbv: dict[str, Any]) -> int:
        numdoc = self._next_vencaj_numero(int(cbv["CBV_EJERCI"]))
        while numdoc <= 999999:
            code = self._vencaj_semaphore_code(int(cbv["CBV_EJERCI"]), numdoc)
            has_lines = self.db.fetch_one(
                "SELECT FIRST 1 DMV_NUMDOC FROM VENCUR WHERE DMV_NUMEMP=? AND DMV_EJERCI=? AND DMV_NUMDOC=?",
                (cbv["CBV_NUMEMP"], cbv["CBV_EJERCI"], numdoc),
            )
            exists = self.db.fetch_one(
                "SELECT FIRST 1 CBV_NUMDOC FROM VENCAJ WHERE CBV_NUMEMP=? AND CBV_EJERCI=? AND CBV_NUMDOC=?",
                (cbv["CBV_NUMEMP"], cbv["CBV_EJERCI"], numdoc),
            )
            if not has_lines and not exists and self._probe_vencaj_lock(code, commit=False):
                candidate = dict(cbv)
                candidate["CBV_NUMDOC"] = numdoc
                try:
                    self._insert_vencaj_row(candidate)
                    cbv["CBV_NUMDOC"] = numdoc
                    return numdoc
                except Exception:
                    # La insercion es la primera operacion persistente de esta
                    # conversion; un rollback permite reintentar limpiamente
                    # tras una colision concurrente de numeracion.
                    self.db.rollback()
            numdoc += 1
        raise FaroError("Error en la numeracion de VENCAJ")

    def save_open_sale_from_order(
        self, centro: Any, codigo_pedido: str, tipdoc: str, texto: str
    ) -> dict[str, Any]:
        """Migra Grabar_Venta_Abierta_Pedido a Python nativo.

        Sirve cantidades de un pedido P, conserva las cantidades pendientes,
        mueve lo servido a DETMOV tipo S y crea las lineas equivalentes en
        VENCUR de una nueva venta abierta.
        """
        centro_i = int(centro)
        ejerci_txt, rest = self._procesar_cadena(str(codigo_pedido or ""), "-")
        serie_txt, rest = self._procesar_cadena(rest, "-")
        numdoc_txt, _ = self._procesar_cadena(rest, "-")
        try:
            ejerci_ped, numdoc_ped = int(ejerci_txt), int(numdoc_txt)
        except Exception as exc:
            raise FaroError(
                f"CODIGO_PEDIDO invalido: {codigo_pedido!r}; se esperaba EJERCICIO-SERIE-NUMERO."
            ) from exc
        serie_ped, tipdoc_s = serie_txt.strip(), str(tipdoc or "").strip()
        pedido = self.db.fetch_one(
            "SELECT * FROM CABDOCV WHERE CBV_NUMEMP=? AND CBV_CENTRO=? AND CBV_TIPDOC='P' AND CBV_TIPAC='0' "
            "AND CBV_EJERCI=? AND CBV_SERIE=? AND CBV_NUMDOC=?",
            (self.settings.empresa, centro_i, ejerci_ped, serie_ped, numdoc_ped),
        )
        if not pedido:
            return {
                "ok": False, "pedido": str(codigo_pedido), "message": "Pedido no encontrado", "datasnap_text": "False"
            }
        pedido = dict(pedido)
        vencaj = self._cabdocv_to_open_sale(pedido, tipdoc_s)
        served: list[dict[str, Any]] = []
        skipped: list[int | None] = []
        try:
            self._insert_open_sale_numbered(vencaj)
            rest_lines = str(texto or "")
            numlin_sale = 10
            while rest_lines:
                raw, rest_lines = self._procesar_cadena(rest_lines, "#")
                if raw == "":
                    break
                numlin_txt, fields = self._procesar_cadena(raw, "|")
                _codart, fields = self._procesar_cadena(fields, "|")
                _descri, fields = self._procesar_cadena(fields, "|")
                cantid_txt, _fields = self._procesar_cadena(fields, "|")
                try:
                    numlin_ped = int(numlin_txt)
                except Exception:
                    numlin_ped = None
                cantid = self._parse_decimal_pedido(cantid_txt, "CANTID")
                dmv = None
                if numlin_ped is not None:
                    dmv = self.db.fetch_one(
                        "SELECT * FROM DETMOV WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPDOC='P' AND DMV_TIPAC='0' "
                        "AND DMV_EJERCI=? AND DMV_SERIE=? AND DMV_NUMDOC=? AND DMV_NUMLIN=?",
                        (self.settings.empresa, centro_i, ejerci_ped, serie_ped, numdoc_ped, numlin_ped),
                    )
                if not dmv:
                    # El Delphi reutiliza un record no inicializado/stale aqui;
                    # producir una linea VENCUR con basura seria inseguro.
                    skipped.append(numlin_ped)
                    continue
                dmv = dict(dmv)
                pending = dec(dmv.get("DMV_CANTID")) - cantid
                if pending > 0:
                    self._insertar_linea_servida(dmv, cantid)
                    self._reducir_linea_pedido_pendiente(dmv, pending)
                else:
                    self._actualizar_linea_pedido_servida(dmv, cantid)

                line = {
                    "DMV_NUMEMP": vencaj["CBV_NUMEMP"], "DMV_EJERCI": vencaj["CBV_EJERCI"],
                    "DMV_NUMDOC": vencaj["CBV_NUMDOC"], "DMV_NUMLIN": numlin_sale,
                    "DMV_CAJA": dmv.get("DMV_CAJA", vencaj.get("CBV_CAJA", 1)),
                    "DMV_USUAR": dmv.get("DMV_USUAR", vencaj.get("CBV_USUMOD", "")),
                    "DMV_TIPLIN": dmv.get("DMV_TIPLIN", "D"), "DMV_FECMOV": date.today(),
                    "DMV_CODART": dmv.get("DMV_CODART", ""), "DMV_DESCRI": dmv.get("DMV_DESCRI", ""),
                    "DMV_CODMON": dmv.get("DMV_CODMON", "E"), "DMV_TIPPRE": dmv.get("DMV_TIPPRE", ""),
                    "DMV_PREVEN": dmv.get("DMV_PREVEN", 0), "DMV_PORIVA": dmv.get("DMV_PORIVA", 0),
                    "DMV_PORREQ": dmv.get("DMV_PORREQ", 0), "DMV_PVP": dmv.get("DMV_PVP", 0),
                    "DMV_CANTID": cantid, "DMV_CANPRE": dmv.get("DMV_CANPRE", 1),
                    "DMV_UNIMED": dmv.get("DMV_UNIMED", ""), "DMV_DTO1": dmv.get("DMV_DTO1", 0),
                    "DMV_DTO2": dmv.get("DMV_DTO2", 0), "DMV_VALLIN": dmv.get("DMV_VALLIN", 0),
                    "DMV_VALLINS": dmv.get("DMV_VALLINS", 0), "DMV_IMPDTO": dmv.get("DMV_IMPDTO", 0),
                    "DMV_EJEOFE": dmv.get("DMV_EJEOFE", 0), "DMV_NUMOFE": dmv.get("DMV_NUMOFE", 0),
                    "DMV_EJERCIO": dmv.get("DMV_EJERCI", 0), "DMV_TIPDOCO": dmv.get("DMV_TIPDOC", "P"),
                    "DMV_SERIEO": dmv.get("DMV_SERIE", ""), "DMV_NUMDOCO": dmv.get("DMV_NUMDOC", 0),
                    "DMV_NUMLINO": dmv.get("DMV_NUMLIN", 0), "DMV_PREIVA": dmv.get("DMV_PREIVA", ""),
                    "DMV_NSERIE": dmv.get("DMV_NSERIE", ""),
                }
                self._insert_valued_vencur(line)
                served.append({"numlin_pedido": numlin_ped, "cantidad": str(cantid)})
                numlin_sale += 10

            vencaj = self._value_vencaj_header(vencaj)
            self._update_vencaj_totals(vencaj)

            served_header = dict(pedido)
            served_header["CBV_TIPDOC"] = "S"
            served_header["CBV_FECHAE"] = date.today()
            served_header["CBV_USUMOD"] = self.settings.usuario
            served_header["CBV_FECMOD"] = datetime.now()
            try:
                self._insert_cabdocv_row(served_header)
            except Exception:
                # Entrega parcial previa: la cabecera S ya puede existir.
                pass
            served_final = self._finalizar_documento_venta(served_header)
            pending_final = self._finalizar_documento_venta(dict(pedido))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "ok": True, "pedido": {"ejerci": ejerci_ped, "serie": serie_ped, "numdoc": numdoc_ped},
            "venta": {"tipdoc": tipdoc_s, "ejerci": vencaj["CBV_EJERCI"], "serie": vencaj["CBV_SERIE"],
                      "numdoc": vencaj["CBV_NUMDOC"]},
            "lineas_servidas": served, "lineas_omitidas": skipped,
            "pedido_historico_servido": served_final, "pedido_pendiente": pending_final,
            "totals": normalize(vencaj.get("CBV_TOTALS")), "totald": normalize(vencaj.get("CBV_TOTALD")),
            "datasnap_text": "True",
        }


    # ------------------------------------------------------------------
    # Clientes, actividades y seguridad
    # ------------------------------------------------------------------

    def _province_name(self, codpos: Any) -> str:
        # BUSQUEDA_PROVIN (funcion anidada en Busqueda_Cliente): usa los 2
        # primeros digitos del codigo postal como PRV_CODIGO.
        codigo = str(codpos or "")[:2]
        if not codigo.isdigit():
            return ""
        row = self.db.fetch_one("SELECT PRV_NOMBRE FROM PROVIN WHERE PRV_CODIGO=?", (codigo,))
        return str(row["PRV_NOMBRE"]).strip() if row and row.get("PRV_NOMBRE") is not None else ""

    def search_client(self, codcli: Any, subcli: Any) -> dict[str, Any]:
        # Replica Busqueda_Cliente: consulta directa a CLIEN (sin pasar por
        # BUSQUEDA_CLIEN, por lo que no aplica el caso especial "Clientes
        # Caja" 99999/0 ni enriquece con los campos de CLIENI).
        codcli_int = int(codcli)
        subcli_int = int(subcli)
        row = self.db.fetch_one(
            "SELECT * FROM CLIEN WHERE CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
            (self.settings.empresa, codcli_int, subcli_int),
        )
        if not row:
            return {"codcli": codcli_int, "subcli": subcli_int, "found": False, "datasnap_text": ""}
        row = normalize(row)
        fields = {
            "codcli": row.get("CLI_CODCLI"),
            "nomcli": clean_text_value(row.get("CLI_NOMCLI")),
            "razsoc": clean_text_value(row.get("CLI_RAZSOC")),
            "domici": clean_text_value(row.get("CLI_DOMICI")),
            "codpos": row.get("CLI_CODPOS"),
            "poblac": row.get("CLI_POBLAC"),
            "provincia": self._province_name(row.get("CLI_CODPOS")),
            "telefo": row.get("CLI_TELEFO"),
            "fax": row.get("CLI_FAX"),
            "email": row.get("CLI_EMAIL"),
            "cif": row.get("CLI_CIF"),
        }
        order = ["codcli", "nomcli", "razsoc", "domici", "codpos", "poblac", "provincia", "telefo", "fax", "email", "cif"]
        return {**fields, "found": True, "datasnap_text": "|".join(serialize_text_value(fields[k]) for k in order)}

    def list_clients(
        self,
        codcli: Any = None,
        subcli: Any = None,
        nombre_like: str = "",
        poblacion_like: str = "",
        cif: str = "",
        codrep: Any = None,
        limit: int = MAX_ROWS_DEFAULT,
    ) -> dict[str, Any]:
        # Replica Consulta_Clientes, pero con filtros tipados en lugar de
        # aceptar un fragmento de SQL crudo como hacia el Delphi original
        # (CADENA_SQL se concatenaba directamente a la sentencia). Aceptar
        # SQL arbitrario desde una herramienta MCP es un riesgo de inyeccion
        # inaceptable, asi que esta es una desviacion deliberada por
        # seguridad, no un descuido de fidelidad. MAXREG (limite de filas del
        # original) es una variable global cuyo valor en tiempo de ejecucion
        # no conocemos; usamos MAX_ROWS_DEFAULT como equivalente razonable.
        sql = "SELECT * FROM CLIEN WHERE CLI_NUMEMP=?"
        params: list[Any] = [self.settings.empresa]
        if codcli is not None:
            sql += " AND CLI_CODCLI=?"
            params.append(int(codcli))
        if subcli is not None:
            sql += " AND CLI_SUBCLI=?"
            params.append(int(subcli))
        if nombre_like:
            sql += " AND UPPER(CLI_NOMCLI) LIKE ?"
            params.append(f"%{nombre_like.upper()}%")
        if poblacion_like:
            sql += " AND UPPER(CLI_POBLAC) LIKE ?"
            params.append(f"%{poblacion_like.upper()}%")
        if cif:
            sql += " AND CLI_CIF=?"
            params.append(cif)
        if codrep is not None:
            sql += " AND CLI_CODREP=?"
            params.append(int(codrep))
        sql += " ORDER BY CLI_CODCLI, CLI_SUBCLI"
        rows = self.db.fetch_all(sql, tuple(params))[: max(1, min(int(limit), MAX_ROWS_DEFAULT))]
        order = ["codcli", "subcli", "nomcli", "razsoc", "domici", "codpos", "poblac", "telefo", "fax", "email", "cif", "codrep"]
        items = []
        parts = []
        for row in rows:
            row = normalize(row)
            item = {
                "codcli": row.get("CLI_CODCLI"),
                "subcli": row.get("CLI_SUBCLI"),
                "nomcli": clean_text_value(row.get("CLI_NOMCLI")),
                "razsoc": clean_text_value(row.get("CLI_RAZSOC")),
                "domici": clean_text_value(row.get("CLI_DOMICI")),
                "codpos": clean_text_value(row.get("CLI_CODPOS")),
                "poblac": clean_text_value(row.get("CLI_POBLAC")),
                "telefo": clean_text_value(row.get("CLI_TELEFO")),
                "fax": clean_text_value(row.get("CLI_FAX")),
                "email": clean_text_value(row.get("CLI_EMAIL")),
                "cif": clean_text_value(row.get("CLI_CIF")),
                "codrep": row.get("CLI_CODREP"),
            }
            items.append(item)
            parts.append("|".join(serialize_text_value(item[k]) for k in order))
        return {"count": len(items), "items": items, "datasnap_text": "#".join(parts) + ("#" if parts else "")}

    def _provider_ficha_fields(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "empresa": row.get("PRO_NUMEMP"),
            "codigo": row.get("PRO_CODPRO"),
            "nombre_fiscal": clean_text_value(row.get("PRO_NOMFIS")),
            "nombre_comercial": clean_text_value(row.get("PRO_NOMCOR")),
            "nombre_abreviado": clean_text_value(row.get("PRO_NOMABR")),
            "cif": clean_text_value(row.get("PRO_CIF")),
            "domicilio": clean_text_value(row.get("PRO_DOMICI")),
            "codigo_postal": clean_text_value(row.get("PRO_CODPOS")),
            "codpos": clean_text_value(row.get("PRO_CODPOS")),
            "poblacion": clean_text_value(row.get("PRO_POBLAC")),
            "provincia": self._province_name(row.get("PRO_CODPOS")),
            "telefono": clean_text_value(row.get("PRO_TELEFO")),
            "fax": clean_text_value(row.get("PRO_FAX")),
            "email": clean_text_value(row.get("PRO_EMAIL")),
            "contacto": clean_text_value(row.get("PRO_CONTAC")),
            "codigo_representante": row.get("PRO_CODREP"),
            "delegacion_nombre": clean_text_value(row.get("PRO_NOMDEL")),
            "delegacion_domicilio": clean_text_value(row.get("PRO_DOMDEL")),
            "delegacion_codigo_postal": clean_text_value(row.get("PRO_CODPOSD")),
            "delegacion_codpos": clean_text_value(row.get("PRO_CODPOSD")),
            "delegacion_poblacion": clean_text_value(row.get("PRO_POBDEL")),
            "delegacion_provincia": self._province_name(row.get("PRO_CODPOSD")),
            "delegacion_telefono": clean_text_value(row.get("PRO_TELDEL")),
            "delegacion_fax": clean_text_value(row.get("PRO_FAXDEL")),
            "delegacion_contacto": clean_text_value(row.get("PRO_CONDEL")),
            "compra_minima": row.get("PRO_COMMIN"),
            "moneda": clean_text_value(row.get("PRO_CODMON")),
            "portes": clean_text_value(row.get("PRO_PORTES")),
            "forma_pago": row.get("PRO_CODPAG"),
            "cuenta_contable": clean_text_value(row.get("PRO_CUECON")),
            "observaciones_internas": clean_text_value(row.get("PRO_OBSINT")),
            "observaciones_forma_pago": clean_text_value(row.get("PRO_OBSFOR")),
            "fecha_modificacion": row.get("PRO_FECMOD"),
            "usuario_modificacion": clean_text_value(row.get("PRO_USUMOD")),
            "fecha_alta": row.get("PRO_FEALTA"),
            "fecha_baja": row.get("PRO_FEBAJA"),
            "registro": normalize(row),
        }

    def search_provider(self, codpro: Any) -> dict[str, Any]:
        # Ficha de detalle de un proveedor por su codigo (PRO_CODPRO), en el
        # mismo estilo que search_client. No replica una funcion Delphi
        # concreta 1:1 (es una consulta nueva, PROVEEDORES_BUSCAR), pero el
        # conjunto de campos devueltos se apoya en PROVEE_UDM.pas (campos de
        # PROVEE) y en las columnas visibles del dialogo de busqueda de
        # proveedores PROVEE_UB.pas/.dfm (nombres, direccion, telefonos,
        # email, representante, direccion de delegacion).
        codigo_int = int(codpro)
        row = self.db.fetch_one(
            "SELECT * FROM PROVEE WHERE PRO_NUMEMP=? AND PRO_CODPRO=?",
            (self.settings.empresa, codigo_int),
        )
        if not row:
            return {"codigo": codigo_int, "found": False, "datasnap_text": ""}
        row = normalize(row)
        fields = self._provider_ficha_fields(row)
        order = [
            "codigo", "nombre_fiscal", "nombre_comercial", "nombre_abreviado", "cif",
            "domicilio", "codpos", "poblacion", "provincia", "telefono", "fax", "email",
            "contacto", "codigo_representante", "fecha_alta", "fecha_baja",
            "delegacion_nombre", "delegacion_domicilio", "delegacion_codpos",
            "delegacion_poblacion", "delegacion_provincia", "delegacion_telefono",
            "delegacion_fax",
        ]
        return {**fields, "found": True, "datasnap_text": "|".join(serialize_text_value(fields[k]) for k in order)}

    def list_providers(
        self,
        codpro: Any = None,
        nombre_comercial_like: str = "",
        nombre_fiscal_like: str = "",
        nombre_abreviado_like: str = "",
        cif: str = "",
        fecha_alta: str = "",
        fecha_alta_desde: str = "",
        fecha_alta_hasta: str = "",
        limit: int = MAX_ROWS_DEFAULT,
    ) -> dict[str, Any]:
        # Listado filtrado de proveedores. Al igual que list_clients, usa
        # filtros tipados con parametros ligados en lugar de aceptar SQL
        # crudo (a diferencia de GENERAR_CONSULTA en el Delphi original, que
        # concatena fragmentos de SQL directamente); esta es una desviacion
        # deliberada por seguridad. El match de texto es "contiene"
        # (UPPER(campo) LIKE '%TEXTO%'), igual que nombre_like/poblacion_like
        # en list_clients, en lugar del prefijo por defecto de
        # PROCESAR_STRING en LIBGEN_U.pas (UPPER(campo) LIKE 'TEXTO%'), para
        # mantener la misma convencion que el resto de herramientas de
        # busqueda de este servidor MCP.
        sql = "SELECT * FROM PROVEE WHERE PRO_NUMEMP=?"
        params: list[Any] = [self.settings.empresa]
        if codpro is not None:
            sql += " AND PRO_CODPRO=?"
            params.append(int(codpro))
        if nombre_comercial_like:
            sql += " AND UPPER(PRO_NOMCOR) LIKE ?"
            params.append(f"%{nombre_comercial_like.upper()}%")
        if nombre_fiscal_like:
            sql += " AND UPPER(PRO_NOMFIS) LIKE ?"
            params.append(f"%{nombre_fiscal_like.upper()}%")
        if nombre_abreviado_like:
            sql += " AND UPPER(PRO_NOMABR) LIKE ?"
            params.append(f"%{nombre_abreviado_like.upper()}%")
        if cif:
            sql += " AND PRO_CIF=?"
            params.append(cif)
        if fecha_alta:
            sql += " AND PRO_FEALTA=?"
            params.append(fecha_alta)
        if fecha_alta_desde:
            sql += " AND PRO_FEALTA>=?"
            params.append(fecha_alta_desde)
        if fecha_alta_hasta:
            sql += " AND PRO_FEALTA<=?"
            params.append(fecha_alta_hasta)
        sql += " ORDER BY PRO_CODPRO"
        rows = self.db.fetch_all(sql, tuple(params))[: max(1, min(int(limit), MAX_ROWS_DEFAULT))]
        order = [
            "codigo", "nombre_fiscal", "nombre_comercial", "nombre_abreviado", "cif",
            "domicilio", "codigo_postal", "poblacion", "provincia", "telefono", "fax", "email",
            "contacto", "codigo_representante", "fecha_alta", "fecha_baja",
            "delegacion_nombre", "delegacion_domicilio", "delegacion_codigo_postal",
            "delegacion_poblacion", "delegacion_provincia", "delegacion_telefono",
            "delegacion_fax",
        ]
        items = []
        parts = []
        for row in rows:
            row = normalize(row)
            item = self._provider_ficha_fields(row)
            items.append(item)
            parts.append("|".join(serialize_text_value(item[k]) for k in order))
        return {"count": len(items), "items": items, "datasnap_text": "#".join(parts) + ("#" if parts else "")}

    def save_client(self, texto: str) -> dict[str, Any]:
        # Replica Grabar_Cliente. Formato TEXTO (10 campos separados por '|'):
        # CODCLI|SUBCLI|NOMCLI|RAZSOC|DOMICI|CODPOS|POBLAC|TELEFO|EMAIL|CIF
        #
        # Es una funcion de MODIFICACION UNICAMENTE: si el cliente no existe
        # (BUSQUEDA_CLIEN devuelve CLI_CODCLI=-1), el Delphi original sale
        # sin grabar nada y sin avisar (Result queda ''); aqui se refleja con
        # found=False, updated=False.
        #
        # Caso especial "Clientes Caja" (CODCLI=99999, SUBCLI=0): BUSQUEDA_CLIEN
        # no consulta la BD en absoluto para este par y devuelve un registro
        # sintetico con CLI_CODCLI=99999 (no -1), por lo que Grabar_Cliente NO
        # sale y continua intentando el UPDATE. Si esa fila no existe
        # fisicamente en CLIEN, el UPDATE simplemente no afecta filas (no es
        # un error). Replicamos ese mismo comportamiento.
        #
        # Simplificaciones deliberadas frente a GRABAR_CLIEN('M'):
        #  1) El Delphi original reescribe con MODIFICAR_CLIEN las ~40
        #     columnas de CLIEN, pero solo 8 (NOMCLI, RAZSOC, DOMICI, CODPOS,
        #     POBLAC, TELEFO, EMAIL, CIF) contienen datos nuevos: el resto
        #     vienen del registro cargado por BUSQUEDA_CLIEN y se
        #     "reescriben" con su propio valor (no-op). Aqui hacemos un
        #     UPDATE dirigido solo a esas 8 columnas + CLI_FECMOD/CLI_USUMOD,
        #     con el mismo resultado neto pero sin el riesgo de pisar con un
        #     valor obsoleto un cambio concurrente en alguna de esas ~32
        #     columnas no tocadas por Grabar_Cliente.
        #  2) GRABAR_CLIEN('M') tambien recorre una larga cascada de ~27
        #     campos "adicionales" en CLIENI (ALB, IMPMI, SERIE, CANPM,
        #     ACECR, ACEOF, ACEPR, TIVEN, TIVFA, TIVFC, TIVR, COBAL, PUBLI,
        #     FEMAI, ACDTO, WEB, DOMIC, DOMEN, EMAIP, IBAN, FACMI, RUPRE,
        #     SERIP, CAUCI, ACTIV, PIVA, PAIS) haciendo upsert/borrado segun
        #     esten vacios o no. Como el formato TEXTO de Grabar_Cliente
        #     nunca asigna ninguno de esos campos (solo llegan precargados
        #     por BUSQUEDA_CLIEN desde su valor previo en CLIENI), esa
        #     cascada es, en la practica, un reescribir-lo-mismo: no cambia
        #     nada. Se omite aqui a proposito en lugar de reproducirla sin
        #     motivo.
        parts = texto.split("|")
        if len(parts) < 10:
            raise FaroError(
                "Formato de TEXTO invalido para Grabar_Cliente: se esperan 10 campos "
                "'CODCLI|SUBCLI|NOMCLI|RAZSOC|DOMICI|CODPOS|POBLAC|TELEFO|EMAIL|CIF'."
            )
        codcli_txt, subcli_txt, nomcli, razsoc, domici, codpos, poblac, telefo, email, cif = parts[:10]
        try:
            codcli = int(codcli_txt)
            subcli = int(subcli_txt)
        except ValueError as exc:
            raise FaroError(f"CODCLI/SUBCLI no validos: {codcli_txt}|{subcli_txt}") from exc

        is_caja = codcli == 99999 and subcli == 0
        if not is_caja:
            existing = self.db.fetch_one(
                "SELECT CLI_CODCLI FROM CLIEN WHERE CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
                (self.settings.empresa, codcli, subcli),
            )
            if not existing:
                return {"codcli": codcli, "subcli": subcli, "found": False, "updated": False}

        now = datetime.now()
        # CLI_USUMOD en GRABAR_CLIEN('M') va siempre prefijado de centro,
        # a diferencia de otras tablas (FALTAS, RECUENTO, ...) que solo
        # graban el usuario.
        usumod = f"{self.settings.centro} {self.settings.usuario}"
        try:
            self.db.execute(
                "UPDATE CLIEN SET CLI_NOMCLI=?, CLI_RAZSOC=?, CLI_DOMICI=?, CLI_CODPOS=?, CLI_POBLAC=?, "
                "CLI_TELEFO=?, CLI_EMAIL=?, CLI_CIF=?, CLI_FECMOD=?, CLI_USUMOD=? "
                "WHERE CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
                (
                    nomcli, razsoc, domici, codpos, poblac, telefo, email, cif, now, usumod,
                    self.settings.empresa, codcli, subcli,
                ),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"codcli": codcli, "subcli": subcli, "found": True, "updated": True}

    def _activity_type_name(self, codact: Any) -> str:
        row = self.db.fetch_one(
            "SELECT TAC_DESCRI FROM TIPACT WHERE TAC_NUMEMP=? AND TAC_CODIGO=?",
            (self.settings.empresa, int(codact or 0)),
        )
        return str(row["TAC_DESCRI"]).strip() if row and row.get("TAC_DESCRI") is not None else ""

    def _client_name(self, codcli: Any, subcli: Any = 0) -> str:
        row = self.db.fetch_one(
            "SELECT CLI_NOMCLI FROM CLIEN WHERE CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
            (self.settings.empresa, int(codcli or 0), int(subcli or 0)),
        )
        return str(row["CLI_NOMCLI"]).strip() if row and row.get("CLI_NOMCLI") is not None else ""

    def activity_types(self) -> dict[str, Any]:
        rows = self.db.fetch_all(
            "SELECT TAC_CODIGO, TAC_DESCRI FROM TIPACT WHERE TAC_NUMEMP=?",
            (self.settings.empresa,),
        )
        items = [
            {"codigo": normalize(row.get("TAC_CODIGO")), "descri": clean_text_value(row.get("TAC_DESCRI"))}
            for row in rows
        ]
        parts = [f"{item['codigo']}|{item['descri']}" for item in items]
        return {"count": len(items), "items": items, "datasnap_text": "#".join(parts) + ("#" if parts else "")}

    def list_client_activities(self, codcli: Any) -> dict[str, Any]:
        # Replica Lista_Actividades. ACT_OBSERV no se limpia de '|'/'#' en el
        # Delphi original (no llama a ELIMINAR_CARACTERES); se mantiene igual
        # aqui por fidelidad, aunque eso significa que una observacion con
        # esos caracteres puede romper el formato de texto historico (comportamiento conservado
        # en el original).
        codcli_int = int(codcli)
        rows = self.db.fetch_all(
            "SELECT * FROM ACTIVI WHERE ACT_NUMEMP=? AND ACT_CODCLI=? ORDER BY ACT_NUMLIN DESC",
            (self.settings.empresa, codcli_int),
        )
        items = []
        parts = []
        for row in rows:
            row = normalize(row)
            item = {
                "numlin": row.get("ACT_NUMLIN"),
                "fecha": row.get("ACT_FECHA"),
                "tipo": self._activity_type_name(row.get("ACT_CODACT")),
                "observ": row.get("ACT_OBSERV"),
            }
            items.append(item)
            parts.append("|".join(serialize_text_value(item[k]) for k in ["numlin", "fecha", "tipo", "observ"]))
        return {
            "codcli": codcli_int,
            "count": len(items),
            "items": items,
            "datasnap_text": "#".join(parts) + ("#" if parts else ""),
        }

    def list_rep_activities(self, codrep: Any) -> dict[str, Any]:
        # Replica Lista_Actividades_Representante, incluido el limite de 50
        # actividades (I > 50: Break tras insertar la 50).
        codrep_int = int(codrep)
        rows = self.db.fetch_all(
            "SELECT * FROM ACTIVI WHERE ACT_NUMEMP=? AND ACT_REPRES=? ORDER BY ACT_NUMLIN DESC",
            (self.settings.empresa, codrep_int),
        )[:50]
        items = []
        parts = []
        for row in rows:
            row = normalize(row)
            item = {
                "numlin": row.get("ACT_NUMLIN"),
                "codcli": row.get("ACT_CODCLI"),
                "nomcli": self._client_name(row.get("ACT_CODCLI"), 0),
                "fecha": row.get("ACT_FECHA"),
                "tipo": self._activity_type_name(row.get("ACT_CODACT")),
                "observ": row.get("ACT_OBSERV"),
            }
            items.append(item)
            parts.append(
                "|".join(serialize_text_value(item[k]) for k in ["numlin", "codcli", "nomcli", "fecha", "tipo", "observ"])
            )
        return {
            "codrep": codrep_int,
            "count": len(items),
            "items": items,
            "datasnap_text": "#".join(parts) + ("#" if parts else ""),
        }

    def list_activities(
        self,
        codcli: Any = None,
        codact: Any = None,
        codrep: Any = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        limit: int = MAX_ROWS_DEFAULT,
    ) -> dict[str, Any]:
        """Lista actividades combinando filtros opcionales (cliente, tipo de
        actividad, representante, rango de fechas) con AND. A diferencia de
        Lista_Actividades/Lista_Actividades_Representante (que solo aceptan
        exactamente un criterio y no existen combinadas en el Delphi
        original), esta funcion es nueva en el contrato v2: no replica ningun
        RPC legacy, se anadio para poder filtrar por cualquier combinacion de
        campos. El rango de fechas admite extremos abiertos (solo desde, solo
        hasta, o ambos). Se exige al menos un filtro para no volcar toda la
        tabla ACTIVI sin acotar.
        """
        conditions = ["ACT_NUMEMP=?"]
        params: list[Any] = [self.settings.empresa]
        if codcli is not None:
            conditions.append("ACT_CODCLI=?")
            params.append(int(codcli))
        if codact is not None:
            conditions.append("ACT_CODACT=?")
            params.append(int(codact))
        if codrep is not None:
            conditions.append("ACT_REPRES=?")
            params.append(int(codrep))
        fecha_desde_dt = None
        fecha_hasta_dt = None
        if fecha_desde is not None:
            try:
                fecha_desde_dt = datetime.strptime(str(fecha_desde), "%Y-%m-%d").date()
            except ValueError as exc:
                raise FaroError(f"fecha_desde no valida (usar AAAA-MM-DD): {fecha_desde}") from exc
            conditions.append("ACT_FECHA>=?")
            params.append(fecha_desde_dt)
        if fecha_hasta is not None:
            try:
                fecha_hasta_dt = datetime.strptime(str(fecha_hasta), "%Y-%m-%d").date()
            except ValueError as exc:
                raise FaroError(f"fecha_hasta no valida (usar AAAA-MM-DD): {fecha_hasta}") from exc
            conditions.append("ACT_FECHA<=?")
            params.append(fecha_hasta_dt)
        if fecha_desde_dt is not None and fecha_hasta_dt is not None and fecha_desde_dt > fecha_hasta_dt:
            raise FaroError("fecha_desde no puede ser posterior a fecha_hasta")
        if len(conditions) == 1:
            raise FaroError(
                "Indica al menos un filtro: cliente, tipo_actividad, representante, fecha_desde o fecha_hasta"
            )
        rows = self.db.fetch_all(
            "SELECT * FROM ACTIVI WHERE " + " AND ".join(conditions)
            + " ORDER BY ACT_FECHA DESC, ACT_NUMLIN DESC",
            tuple(params),
        )[: max(1, int(limit))]
        items = []
        parts = []
        for row in rows:
            row = normalize(row)
            item = {
                "numlin": row.get("ACT_NUMLIN"),
                "codcli": row.get("ACT_CODCLI"),
                "nomcli": self._client_name(row.get("ACT_CODCLI"), row.get("ACT_SUBCLI")),
                "codrep": row.get("ACT_REPRES"),
                "fecha": row.get("ACT_FECHA"),
                "tipo": self._activity_type_name(row.get("ACT_CODACT")),
                "observ": row.get("ACT_OBSERV"),
            }
            items.append(item)
            parts.append(
                "|".join(
                    serialize_text_value(item[k])
                    for k in ["numlin", "codcli", "nomcli", "fecha", "tipo", "observ"]
                )
            )
        return {
            "count": len(items),
            "items": items,
            "datasnap_text": "#".join(parts) + ("#" if parts else ""),
        }

    def _next_activi_line(self) -> int:
        # NUMERAR_ACTIVI: MAX(ACT_NUMLIN) global de la empresa (no por cliente).
        row = self.db.fetch_one(
            "SELECT MAX(ACT_NUMLIN) AS NUMLIN FROM ACTIVI WHERE ACT_NUMEMP=?",
            (self.settings.empresa,),
        )
        return int(row.get("NUMLIN") or 0) + 1 if row else 1

    def save_activity(
        self,
        codcli: Any,
        subcli: Any,
        fecha: str,
        codact: Any,
        codrep: Any,
        texto: str,
    ) -> dict[str, Any]:
        # Replica Grabar_Actividad: busca una actividad del cliente en esa
        # fecha exacta (solo por ACT_CODCLI + ACT_FECHA, sin filtrar por
        # SUBCLI ni CODACT, igual que el original); si no existe, inserta una
        # nueva numerada con NUMERAR_ACTIVI (con reintento si colisiona el
        # numero, igual que GRABAR_ACTIVI('G')); si existe, actualiza
        # representante/tipo/fecha/observacion de esa misma linea.
        #
        # Correccion consciente de un bug heredado: el Delphi original hace
        # FIN_TRANSACCION(TRUE) incondicional (confirma pase lo que pase),
        # aunque R_PARSQL.CODERR indique fallo. Aqui se hace rollback si
        # falla cualquier paso, igual que en el resto de funciones Grabar_*
        # ya corregidas en fases anteriores (etiquetas, recuento, faltas).
        codcli_int = int(codcli)
        subcli_int = int(subcli)
        codact_int = int(codact)
        codrep_int = int(codrep)
        try:
            fecha_dt = datetime.strptime(fecha, "%Y-%m-%d").date()
        except ValueError as exc:
            raise FaroError(f"Fecha no valida (usar AAAA-MM-DD): {fecha}") from exc

        existing = self.db.fetch_one(
            "SELECT ACT_NUMLIN FROM ACTIVI WHERE ACT_NUMEMP=? AND ACT_CODCLI=? AND ACT_FECHA=?",
            (self.settings.empresa, codcli_int, fecha_dt),
        )
        now = datetime.now()
        numlin: int
        try:
            if not existing:
                numlin = self._next_activi_line()
                attempts = 0
                while True:
                    try:
                        self.db.execute(
                            "INSERT INTO ACTIVI (ACT_NUMEMP, ACT_NUMLIN, ACT_CODCLI, ACT_SUBCLI, ACT_REPRES, "
                            "ACT_CODACT, ACT_FECHA, ACT_OBSERV, ACT_FECMOD, ACT_USUMOD) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                self.settings.empresa, numlin, codcli_int, subcli_int, codrep_int,
                                codact_int, fecha_dt, texto, now, self.settings.usuario,
                            ),
                        )
                        break
                    except Exception as exc:
                        self.db.rollback()
                        if not _is_duplicate_key_error(exc):
                            # No es una colision de numeracion (p.ej. representante,
                            # tipo de actividad o cliente invalidos): reintentar no lo
                            # arregla, solo alarga la espera hasta parecer colgado.
                            raise
                        numlin += 1
                        attempts += 1
                        if attempts >= 999999:
                            raise FaroError("No se pudo numerar la actividad (ACT_NUMLIN agotado).")
            else:
                numlin = int(existing["ACT_NUMLIN"])
                self.db.execute(
                    "UPDATE ACTIVI SET ACT_REPRES=?, ACT_CODACT=?, ACT_FECHA=?, ACT_OBSERV=?, "
                    "ACT_FECMOD=?, ACT_USUMOD=? WHERE ACT_NUMEMP=? AND ACT_NUMLIN=?",
                    (codrep_int, codact_int, fecha_dt, texto, now, self.settings.usuario, self.settings.empresa, numlin),
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "codcli": codcli_int,
            "subcli": subcli_int,
            "fecha": fecha_dt.isoformat(),
            "numlin": numlin,
            "mode": "modificar" if existing else "insertar",
            "updated": True,
        }

    def user_security(self, centro: Any, usuario: str) -> dict[str, Any]:
        # Replica Seguridad_Usuario.
        centro_int = int(centro)
        row = self.db.fetch_one(
            "SELECT GRUPUSU.GRU_NIVEL, GRUPUSU.GRU_NIVPRI, GRUPUSU.GRU_AUTVEN, GRUPUSU.GRU_AUTDTO "
            "FROM GRUPUSU, USUAR WHERE USU_NUMEMP=? AND USU_CODCEN=? AND USU_NOMUSU=? "
            "AND USU_IDGRUPO=GRU_IDGRUPO",
            (self.settings.empresa, centro_int, usuario),
        )
        if not row:
            return {"centro": centro_int, "usuario": usuario, "found": False, "datasnap_text": ""}
        row = normalize(row)
        fields = {
            "nivel": row.get("GRU_NIVEL"),
            "nivpri": row.get("GRU_NIVPRI"),
            "autven": row.get("GRU_AUTVEN"),
            "autdto": row.get("GRU_AUTDTO"),
        }
        return {
            "centro": centro_int,
            "usuario": usuario,
            "found": True,
            **fields,
            "datasnap_text": "|".join(serialize_text_value(fields[k]) for k in ["nivel", "nivpri", "autven", "autdto"]),
        }

    def login_usuario(self, usuario: str, password: str) -> dict[str, Any]:
        # Replica Conexion_Usuario. Usa el centro configurado en el MCP
        # (self.settings.centro), igual que R_PARAMETROS.CENTRO en Delphi
        # (la sesion ya esta conectada a un centro concreto).
        row = self.db.fetch_one(
            "SELECT USU_PASSWORD FROM USUAR WHERE USU_NUMEMP=? AND USU_CODCEN=? AND USU_NOMUSU=?",
            (self.settings.empresa, self.settings.centro, usuario),
        )
        if not row:
            return {"usuario": usuario, "ok": False, "motivo": "Usuario inexistente"}
        stored = str(row.get("USU_PASSWORD") or "")
        if stored != cript(1, password, ""):
            return {"usuario": usuario, "ok": False, "motivo": "Contrasena incorrecta"}
        return {"usuario": usuario, "ok": True, "motivo": ""}

    def login_cliente(self, usuario: str, password: str) -> dict[str, Any]:
        # Replica Conexion_Cliente. NOTA DE SEGURIDAD: en el Delphi original
        # la contrasena de cliente se guarda y compara en TEXTO PLANO en
        # CLIENI (CLII_CODINF='PASSW'), sin CRIPT ni hash de ningun tipo. Se
        # replica tal cual (no es competencia de esta fase cambiar el
        # esquema de datos), pero queda documentado como riesgo conocido.
        row = self.db.fetch_one(
            "SELECT CLII_CODCLI, CLII_SUBCLI FROM CLIENI WHERE CLII_NUMEMP=? AND CLII_CODINF=? AND CLII_DESCRI=?",
            (self.settings.empresa, "USUAR", usuario),
        )
        if not row:
            return {"codcli": None, "subcli": None, "ok": False, "motivo": "Usuario inexistente"}
        codcli = row.get("CLII_CODCLI")
        subcli = row.get("CLII_SUBCLI")
        pass_row = self.db.fetch_one(
            "SELECT CLII_DESCRI FROM CLIENI WHERE CLII_NUMEMP=? AND CLII_CODCLI=? AND CLII_SUBCLI=? AND CLII_CODINF=?",
            (self.settings.empresa, codcli, subcli, "PASSW"),
        )
        if not pass_row:
            return {
                "codcli": normalize(codcli), "subcli": normalize(subcli),
                "ok": False, "motivo": "Contrasena inexistente",
            }
        if password != str(pass_row.get("CLII_DESCRI") or ""):
            return {
                "codcli": normalize(codcli), "subcli": normalize(subcli),
                "ok": False, "motivo": "Contrasena incorrecta",
            }
        return {"codcli": normalize(codcli), "subcli": normalize(subcli), "ok": True, "motivo": ""}

    # ------------------------------------------------------------------
    # Pedidos de cliente (Grabar_Pedido_Cliente)
    # ------------------------------------------------------------------

    def round_price_order(self, value: Decimal, currency: str, price_type: str) -> Decimal:
        # Duplica REDONDEAR_PRECIO (igual que FaroArticleService.round_price,
        # pero en esta clase, que tiene su propia conexion/self.parameter).
        numdec = int(self.parameter("NUMDEC", "2") or "2")
        declin = int(self.parameter("DECLIN", "2") or "2")
        if value == 0:
            return Decimal("0")
        if price_type == "P":
            return redondea(value, numdec)
        if price_type == "L":
            return redondea(value, declin)
        if currency == "P":
            return redondea(value, 0)
        return redondea(value, 2)

    def _procesar_cadena(self, cadena: str, separador: str = "#") -> tuple[str, str]:
        # Replica PROCESAR_CADENA (LIBTIP_U.pas): corta en la primera aparicion
        # de SEPARADOR; VALOR es el primer trozo (recortado de espacios),
        # CADENA es el resto. Si no aparece el separador, VALOR es la cadena
        # completa (recortada) y CADENA queda vacia.
        cadena = cadena or ""
        idx = cadena.find(separador)
        if idx == -1:
            return cadena.strip(), ""
        return cadena[:idx].strip(), cadena[idx + len(separador):]

    def _parse_decimal_pedido(self, texto: str, campo: str) -> Decimal:
        texto = (texto or "").strip()
        if not texto:
            raise FaroError(f"Valor numerico vacio para '{campo}' en linea de pedido.")
        try:
            return Decimal(texto.replace(",", "."))
        except Exception as exc:
            raise FaroError(f"Valor numerico no valido para '{campo}': '{texto}'") from exc

    def _busqueda_clien_pedido(self, codcli: int, subcli: int) -> dict[str, Any]:
        # Replica BUSQUEDA_CLIEN, limitado a los campos que usa
        # Grabar_Pedido_Cliente (cabecera + CLI_REGIVA para IVA/totales).
        #
        # Caso especial "Clientes Caja" (99999/0): igual que en el Delphi
        # original, no se consulta CLIEN en absoluto; se devuelve un registro
        # sintetico (CLI_TIPPRE='4' y CLI_PORAUM=0 tambien se fuerzan asi en
        # PRECIO_VENTA, pero quedan fuera de nuestro alcance al no usarse aqui).
        #
        # DESVIACION DELIBERADA (correccion de un descuido del original): fuera
        # del caso Caja, si el cliente no existe BUSQUEDA_CLIEN devuelve un
        # CLIEN con CLI_CODCLI=-1 como centinela, pero Grabar_Pedido_Cliente
        # nunca comprueba ese centinela: graba felizmente un pedido con
        # cabecera en blanco (NOMCLI='', CIF='', etc.) para un cliente
        # inexistente. Aqui se rechaza la operacion con FaroError en su
        # lugar, en vez de persistir un pedido con datos de cliente
        # incompletos/incorrectos.
        if codcli == 99999 and subcli == 0:
            return {
                "codcli": 99999, "subcli": 0, "codrep": 0, "razsoc": "Clientes Caja",
                "cif": "", "domici": "", "codpos": "", "poblac": "",
                "forpag": 0, "forenv": 0, "dtoesp": Decimal("0"), "regiva": "N",
            }
        row = self.db.fetch_one(
            "SELECT CLI_CODREP, CLI_RAZSOC, CLI_CIF, CLI_DOMICI, CLI_CODPOS, CLI_POBLAC, "
            "CLI_FORPAG, CLI_FORENV, CLI_DTOESP, CLI_REGIVA FROM CLIEN "
            "WHERE CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
            (self.settings.empresa, codcli, subcli),
        )
        if not row:
            raise FaroError(
                f"Cliente {codcli}/{subcli} no encontrado (Grabar_Pedido_Cliente original no "
                "comprueba esto y grabaria un pedido con cabecera de cliente en blanco; aqui se "
                "rechaza en su lugar)."
            )
        row = normalize(row)
        return {
            "codcli": codcli, "subcli": subcli,
            "codrep": int(row.get("CLI_CODREP") or 0),
            "razsoc": clean_text_value(row.get("CLI_RAZSOC")),
            "cif": clean_text_value(row.get("CLI_CIF")),
            "domici": clean_text_value(row.get("CLI_DOMICI")),
            "codpos": clean_text_value(row.get("CLI_CODPOS")),
            "poblac": clean_text_value(row.get("CLI_POBLAC")),
            "forpag": int(row.get("CLI_FORPAG") or 0),
            "forenv": int(row.get("CLI_FORENV") or 0),
            "dtoesp": dec(row.get("CLI_DTOESP")),
            "regiva": str(row.get("CLI_REGIVA") or ""),
        }

    def _busqueda_tipven2(self, tipdoc: str, tipac: str) -> int:
        # Replica BUSQUEDA_TIPVEN2. NOTA: esta funcion no existe en el
        # DataModules/TIPVEN_UDM.pas actual (fuente de verdad del resto del
        # proyecto); solo se ha localizado en la copia obsoleta
        # la implementacion historica de CABDOCV. Se replica esa version (trivial:
        # primer TIV_CODIGO ordenado ascendente, o -1) por ser la unica
        # disponible, documentando aqui la discrepancia.
        row = self.db.fetch_one(
            "SELECT FIRST 1 TIV_CODIGO FROM TIPVEN WHERE TIV_NUMEMP=? AND TIV_TIPDOC=? AND TIV_TIPAC=? "
            "ORDER BY TIV_CODIGO",
            (self.settings.empresa, tipdoc, tipac),
        )
        return int(row["TIV_CODIGO"]) if row and row.get("TIV_CODIGO") is not None else -1

    def _next_cabdocv_numero(self, centro: int, tipac: str, tipdoc: str, ejerci: int, serie: str) -> int:
        # Replica NUMERAR_CABDOCV: MAX(NUM_NUMERO)+1 en NUMERA para esta
        # combinacion (empresa, centro, tipac, tipdoc, ejercicio, serie).
        row = self.db.fetch_one(
            "SELECT MAX(NUM_NUMERO) AS NUMERO FROM NUMERA WHERE NUM_NUMEMP=? AND NUM_CENTRO=? "
            "AND NUM_TIPAC=? AND NUM_TIPDOC=? AND NUM_EJERCI=? AND NUM_SERIE=?",
            (self.settings.empresa, centro, tipac, tipdoc, ejerci, serie),
        )
        maximo = row.get("NUMERO") if row else None
        return int(maximo) + 1 if maximo is not None else 1

    def _insert_cabdocv_row(self, cbv: dict[str, Any]) -> None:
        columns = [
            "CBV_NUMEMP", "CBV_CENTRO", "CBV_TIPDOC", "CBV_TIPAC", "CBV_EJERCI", "CBV_SERIE",
            "CBV_NUMDOC", "CBV_CAJA", "CBV_FECHA", "CBV_FECHAE", "CBV_CODCLI", "CBV_SUBCLI",
            "CBV_CODREP", "CBV_COMREP", "CBV_NOMCLI", "CBV_CIF", "CBV_DOMCLI", "CBV_CODPOS",
            "CBV_POBLAC", "CBV_CODPAG", "CBV_FORENV", "CBV_PORDTO", "CBV_IMPPOR",
            "CBV_BASIMP1", "CBV_PORIVA1", "CBV_PORREQ1", "CBV_BASIMP2", "CBV_PORIVA2", "CBV_PORREQ2",
            "CBV_BASIMP3", "CBV_PORIVA3", "CBV_PORREQ3", "CBV_BASIMP4", "CBV_PORIVA4", "CBV_PORREQ4",
            "CBV_TOTALS", "CBV_TOTALD", "CBV_IMPCOB", "CBV_CODMON", "CBV_FORCOB", "CBV_NUMTAR",
            "CBV_TIPVEN", "CBV_SITUAC", "CBV_INDEDI", "CBV_OBSERV", "CBV_EJERCID", "CBV_TIPDOCD",
            "CBV_SERIED", "CBV_NUMDOCD", "CBV_FECMOD", "CBV_USUMOD", "CBV_REFCLI", "CBV_RETIRA",
            "CBV_CODTAR",
        ]
        values = tuple(cbv[col] for col in columns)
        placeholders = ",".join(["?"] * len(columns))
        self.db.execute(f"INSERT INTO CABDOCV ({', '.join(columns)}) VALUES ({placeholders})", values)

    def _grabar_numera_upsert(self, cbv: dict[str, Any]) -> None:
        # Replica GRABAR_NUMERA (intenta INSERT, si falla hace UPDATE), pero
        # decidiendo con un SELECT previo en vez de dejar fallar el INSERT:
        # esta llamada ocurre justo despues de insertar la cabecera CABDOCV
        # (sin commit todavia), y en esta conexion un statement fallido deja
        # la transaccion en un estado que exige rollback() para seguir
        # operando (ver el patron ya usado en save_activity); un rollback()
        # aqui borraria tambien el INSERT de CABDOCV recien hecho. Comprobar
        # antes con SELECT consigue el mismo upsert sin ese riesgo.
        key_cols = "NUM_NUMEMP=? AND NUM_CENTRO=? AND NUM_TIPAC=? AND NUM_TIPDOC=? AND NUM_EJERCI=? AND NUM_SERIE=?"
        key_vals = (
            cbv["CBV_NUMEMP"], cbv["CBV_CENTRO"], cbv["CBV_TIPAC"], cbv["CBV_TIPDOC"],
            cbv["CBV_EJERCI"], cbv["CBV_SERIE"],
        )
        existing = self.db.fetch_one(f"SELECT NUM_NUMERO FROM NUMERA WHERE {key_cols}", key_vals)
        if existing:
            self.db.execute(f"UPDATE NUMERA SET NUM_NUMERO=? WHERE {key_cols}", (cbv["CBV_NUMDOC"], *key_vals))
        else:
            self.db.execute(
                "INSERT INTO NUMERA (NUM_NUMEMP, NUM_CENTRO, NUM_TIPAC, NUM_TIPDOC, NUM_EJERCI, NUM_SERIE, "
                "NUM_NUMERO) VALUES (?,?,?,?,?,?,?)",
                (*key_vals, cbv["CBV_NUMDOC"]),
            )

    def _insert_cabdocv_order(self, cbv: dict[str, Any]) -> int:
        # Replica el bucle de numeracion-con-reintento de GRABAR_CABDOCV('G'):
        # intenta insertar con el siguiente numero libre y, si colisiona
        # (choque de clave), reintenta con el numero siguiente (limite 999999,
        # igual que el original). Aqui SI se hace rollback() entre intentos
        # (a diferencia de _grabar_numera_upsert) porque este es el primer
        # statement de la transaccion: no hay nada valioso que perder todavia.
        numdoc = self._next_cabdocv_numero(cbv["CBV_CENTRO"], cbv["CBV_TIPAC"], cbv["CBV_TIPDOC"], cbv["CBV_EJERCI"], cbv["CBV_SERIE"])
        attempts = 0
        while True:
            cbv["CBV_NUMDOC"] = numdoc
            try:
                self._insert_cabdocv_row(cbv)
                break
            except Exception:
                self.db.rollback()
                numdoc += 1
                attempts += 1
                if attempts >= 999999:
                    raise FaroError("No se pudo numerar el pedido (CBV_NUMDOC agotado).")
        self._grabar_numera_upsert(cbv)
        return numdoc

    def _resolve_order_article(self, codart_in: str, codcli: int) -> dict[str, Any]:
        # Replica el arranque de PRECIO_VENTA: BUSQUEDA_ARTICUL directo, y si
        # no aparece, intenta el codigo propio del cliente via CLIART
        # (BUSQUEDA_CODIGO_CLIEN_ARTICUL: CLIA_CODARTC + CLIA_CODCLI ->
        # CLIA_CODART, sin filtrar por subcliente, igual que el original).
        #
        # DESVIACION DELIBERADA: si tras ambos intentos no se resuelve el
        # articulo, PRECIO_VENTA en Delphi solo marca CODERR=2 en su propio
        # resultado, pero Grabar_Pedido_Cliente NUNCA comprueba ese CODERR
        # antes de seguir: acaba grabando una linea de DETMOV con el
        # DMV_CODART original sin validar, DMV_PORIVA/PORREQ=0 y
        # DMV_UNIMED/CODMON/PVP vacios/0. Aqui se rechaza la linea entera con
        # FaroError en vez de grabar un DETMOV incompleto.
        codart = (codart_in or "").strip()
        row = self.db.fetch_one(
            "SELECT ART_CODART, ART_DESCRI, ART_CODMON, ART_UNIMED, ART_PVP, ART_TIPIVA "
            "FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        if not row:
            fallback = self.db.fetch_one(
                "SELECT CLIA_CODART FROM CLIART WHERE CLIA_NUMEMP=? AND CLIA_CODARTC=? AND CLIA_CODCLI=?",
                (self.settings.empresa, codart, codcli),
            )
            codart_real = str(fallback.get("CLIA_CODART") or "").strip() if fallback else ""
            if codart_real:
                row = self.db.fetch_one(
                    "SELECT ART_CODART, ART_DESCRI, ART_CODMON, ART_UNIMED, ART_PVP, ART_TIPIVA "
                    "FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                    (self.settings.empresa, codart_real),
                )
        if not row:
            raise FaroError(
                f"Codigo de articulo incorrecto: '{codart_in}' (equivale al CODERR=2 'Codigo de "
                "articulo incorrecto' de PRECIO_VENTA; aqui se rechaza la linea en vez de grabarla "
                "incompleta como hace el Delphi original)."
            )
        return normalize(row)

    def _poriva_cliente(self, codcli: int, subcli: int) -> Decimal | None:
        # PORIVA_CLIENTE no se ha podido localizar en las fuentes disponibles;
        # se infiere (igual que en la fase de Grabar_Cliente) que corresponde
        # al campo adicional CLIENI 'PIVA' (override de % de IVA por cliente).
        # Si no hay valor o no es un decimal valido (equivalente a
        # DECIMAL_VALIDO), se considera que no hay override.
        row = self.db.fetch_one(
            "SELECT CLII_DESCRI FROM CLIENI WHERE CLII_NUMEMP=? AND CLII_CODCLI=? AND CLII_SUBCLI=? "
            "AND CLII_CODINF=?",
            (self.settings.empresa, codcli, subcli, "PIVA"),
        )
        valor = row.get("CLII_DESCRI") if row else None
        if valor in (None, ""):
            return None
        try:
            return dec(valor)
        except Exception:
            return None

    def _valorar_detmov_pedido(self, dmv: dict[str, Any]) -> dict[str, Any]:
        # Replica VALORAR_DETMOV, restringido al caso real de
        # Grabar_Pedido_Cliente: TIPLIN 'D' o 'C' (nunca 'X'), DMV_PREIVA
        # siempre '' (por lo que siempre cae en la rama ELSE, calculo desde
        # DMV_PREVEN), y sin cambio de divisa (moneda de linea y cabecera
        # asumidas 'E'; ver _resolve_order_article y _iva_cabdocv_pedido).
        if dmv["DMV_TIPLIN"] == "C":
            dmv["DMV_VALLIN"] = Decimal("0")
            dmv["DMV_VALLINS"] = Decimal("0")
            return dmv
        moneda = dmv["DMV_CODMON"]
        dmv["DMV_CANTID"] = redondea(dec(dmv["DMV_CANTID"]), 2)
        preven = self.round_price_order(dec(dmv["DMV_PREVEN"]), moneda, "P")
        dmv["DMV_PREVEN"] = preven
        vallins = self.round_price_order(preven * dmv["DMV_CANTID"], moneda, "I")
        vallins = vallins * (1 - dec(dmv["DMV_DTO1"]) / 100) * (1 - dec(dmv["DMV_DTO2"]) / 100)
        vallins = self.round_price_order(vallins, moneda, "I")
        dmv["DMV_VALLINS"] = vallins
        vallin = vallins * (1 + dec(dmv["DMV_PORIVA"]) / 100 + dec(dmv["DMV_PORREQ"]) / 100)
        dmv["DMV_VALLIN"] = self.round_price_order(vallin, moneda, "I")
        return dmv

    def _build_order_line(
        self,
        cbv: dict[str, Any],
        numlin: int,
        codart_in: str,
        descri_in: str,
        cantid_txt: str,
        preven_txt: str,
        dto1_txt: str,
        cliente: dict[str, Any],
    ) -> dict[str, Any]:
        cantid = self._parse_decimal_pedido(cantid_txt, "CANTID")
        preven = self._parse_decimal_pedido(preven_txt, "PREVEN")
        dto1 = self._parse_decimal_pedido(dto1_txt, "DTO1")

        art = self._resolve_order_article(codart_in, cbv["CBV_CODCLI"])
        codmon_art = str(art.get("ART_CODMON") or "E")
        if codmon_art != "E":
            raise FaroError(
                f"El articulo {art.get('ART_CODART')} tiene moneda '{codmon_art}': el cambio de "
                "divisa (CAMBIAR_PRECIO) no esta implementado en esta fase (se asume moneda unica 'E')."
            )

        is_caja = cbv["CBV_CODCLI"] == 99999 and cbv["CBV_SUBCLI"] == 0
        recargo = (not is_caja) and cliente["regiva"] == "R"

        poriva_override = self._poriva_cliente(cbv["CBV_CODCLI"], cbv["CBV_SUBCLI"])
        if poriva_override is not None:
            poriva = poriva_override
            porreq = Decimal("0")
        else:
            tipiva_code = int(art.get("ART_TIPIVA") or 0)
            tax = self.db.fetch_one(
                "SELECT TIV_PORIVA, TIV_PORREQ FROM TIPIVA WHERE TIV_NUMEMP=? AND TIV_TIPIVA=?",
                (self.settings.empresa, tipiva_code),
            )
            if not tax:
                raise FaroError(
                    f"Tipo de IVA inexistente para el articulo {art.get('ART_CODART')} "
                    f"(ART_TIPIVA={tipiva_code})."
                )
            poriva = dec(tax.get("TIV_PORIVA"))
            porreq = dec(tax.get("TIV_PORREQ")) if recargo else Decimal("0")

        dmv = {
            "DMV_NUMEMP": cbv["CBV_NUMEMP"], "DMV_CENTRO": cbv["CBV_CENTRO"], "DMV_TIPDOC": cbv["CBV_TIPDOC"],
            "DMV_TIPAC": cbv["CBV_TIPAC"], "DMV_EJERCI": cbv["CBV_EJERCI"], "DMV_SERIE": cbv["CBV_SERIE"],
            "DMV_NUMDOC": cbv["CBV_NUMDOC"], "DMV_NUMLIN": numlin, "DMV_SIGNO": "0",
            "DMV_CAJA": cbv["CBV_CAJA"], "DMV_USUAR": cbv["CBV_USUMOD"], "DMV_TIPLIN": "D",
            "DMV_FECMOV": cbv["CBV_FECHA"], "DMV_CODART": str(art["ART_CODART"]).strip(),
            "DMV_DESCRI": descri_in or "", "DMV_CODMON": codmon_art, "DMV_TIPPRE": "",
            "DMV_PREVEN": preven, "DMV_PORIVA": poriva, "DMV_PORREQ": porreq,
            "DMV_PVP": dec(art.get("ART_PVP")), "DMV_CANTID": cantid, "DMV_CANPRE": Decimal("0"),
            "DMV_UNIMED": str(art.get("ART_UNIMED") or ""), "DMV_DTO1": dto1, "DMV_DTO2": Decimal("0"),
            "DMV_VALLIN": Decimal("0"), "DMV_VALLINS": Decimal("0"), "DMV_IMPDTO": Decimal("0"),
            "DMV_EJEOFE": 0, "DMV_NUMOFE": 0, "DMV_EJERCIO": 0, "DMV_TIPDOCO": "", "DMV_SERIEO": "",
            "DMV_NUMDOCO": 0, "DMV_NUMLINO": 0, "DMV_PREIVA": "",
        }
        return self._valorar_detmov_pedido(dmv)

    def _build_comment_line(self, cbv: dict[str, Any], numlin: int, texto_linea: str) -> dict[str, Any]:
        dmv = {
            "DMV_NUMEMP": cbv["CBV_NUMEMP"], "DMV_CENTRO": cbv["CBV_CENTRO"], "DMV_TIPDOC": cbv["CBV_TIPDOC"],
            "DMV_TIPAC": cbv["CBV_TIPAC"], "DMV_EJERCI": cbv["CBV_EJERCI"], "DMV_SERIE": cbv["CBV_SERIE"],
            "DMV_NUMDOC": cbv["CBV_NUMDOC"], "DMV_NUMLIN": numlin, "DMV_SIGNO": "0",
            "DMV_CAJA": cbv["CBV_CAJA"], "DMV_USUAR": cbv["CBV_USUMOD"], "DMV_TIPLIN": "C",
            "DMV_FECMOV": cbv["CBV_FECHA"], "DMV_CODART": "", "DMV_DESCRI": texto_linea[:100],
            "DMV_CODMON": cbv["CBV_CODMON"], "DMV_TIPPRE": "", "DMV_PREVEN": Decimal("0"),
            "DMV_PORIVA": Decimal("0"), "DMV_PORREQ": Decimal("0"), "DMV_PVP": Decimal("0"),
            "DMV_CANTID": Decimal("0"), "DMV_CANPRE": Decimal("1"), "DMV_UNIMED": "",
            "DMV_DTO1": Decimal("0"), "DMV_DTO2": Decimal("0"), "DMV_VALLIN": Decimal("0"),
            "DMV_VALLINS": Decimal("0"), "DMV_IMPDTO": Decimal("0"), "DMV_EJEOFE": 0, "DMV_NUMOFE": 0,
            "DMV_EJERCIO": 0, "DMV_TIPDOCO": "", "DMV_SERIEO": "", "DMV_NUMDOCO": 0, "DMV_NUMLINO": 0,
            "DMV_PREIVA": "",
        }
        return self._valorar_detmov_pedido(dmv)

    def _insert_detmov_pedido(self, dmv: dict[str, Any]) -> None:
        columns = [
            "DMV_NUMEMP", "DMV_CENTRO", "DMV_TIPDOC", "DMV_TIPAC", "DMV_EJERCI", "DMV_SERIE",
            "DMV_NUMDOC", "DMV_NUMLIN", "DMV_SIGNO", "DMV_CAJA", "DMV_USUAR", "DMV_TIPLIN",
            "DMV_FECMOV", "DMV_CODART", "DMV_DESCRI", "DMV_CODMON", "DMV_TIPPRE", "DMV_PREVEN",
            "DMV_PORIVA", "DMV_PORREQ", "DMV_PVP", "DMV_CANTID", "DMV_CANPRE", "DMV_UNIMED",
            "DMV_DTO1", "DMV_DTO2", "DMV_VALLIN", "DMV_VALLINS", "DMV_IMPDTO", "DMV_EJEOFE",
            "DMV_NUMOFE", "DMV_EJERCIO", "DMV_TIPDOCO", "DMV_SERIEO", "DMV_NUMDOCO", "DMV_NUMLINO",
            "DMV_PREIVA",
        ]
        values = tuple(dmv[col] for col in columns)
        placeholders = ",".join(["?"] * len(columns))
        self.db.execute(f"INSERT INTO DETMOV ({', '.join(columns)}) VALUES ({placeholders})", values)

    def _iva_cabdocv_pedido(self, cbv: dict[str, Any]) -> list[dict[str, Any]]:
        # Replica IVA_CABDOCV: agrupa las lineas 'D'/'X' del documento en
        # hasta 4 "cubos" por combinacion (PORIVA,PORREQ) unica, sumando
        # DMV_VALLINS en cada uno. Un 5º tipo de IVA distinto simplemente no
        # se acumula (igual que el "IF I < 5" del original: bug heredado, no
        # corregido aqui por fidelidad).
        rows = self.db.fetch_all(
            "SELECT DMV_TIPLIN, DMV_PORIVA, DMV_PORREQ, DMV_VALLINS, DMV_CODMON FROM DETMOV "
            "WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPDOC=? AND DMV_TIPAC=? AND DMV_EJERCI=? "
            "AND DMV_SERIE=? AND DMV_NUMDOC=?",
            (cbv["CBV_NUMEMP"], cbv["CBV_CENTRO"], cbv["CBV_TIPDOC"], cbv["CBV_TIPAC"], cbv["CBV_EJERCI"],
             cbv["CBV_SERIE"], cbv["CBV_NUMDOC"]),
        )
        buckets: list[dict[str, Any]] = []
        for row in rows:
            row = normalize(row)
            if row.get("DMV_TIPLIN") not in ("D", "X"):
                continue
            poriva = dec(row.get("DMV_PORIVA"))
            porreq = dec(row.get("DMV_PORREQ"))
            vallins = dec(row.get("DMV_VALLINS"))
            codmon = str(row.get("DMV_CODMON") or "E")
            if codmon != cbv["CBV_CODMON"]:
                raise FaroError(
                    "Linea de pedido con moneda distinta a la de la cabecera: el cambio de divisa "
                    "(CAMBIAR_PRECIO) no esta implementado en esta fase."
                )
            bucket = next((b for b in buckets if b["poriva"] == poriva and b["porreq"] == porreq), None)
            if bucket is None:
                if len(buckets) >= 4:
                    continue
                bucket = {"poriva": poriva, "porreq": porreq, "baseimp": Decimal("0")}
                buckets.append(bucket)
            bucket["baseimp"] += vallins
        return buckets

    def _totales_cabecera_pedido(
        self, cbv: dict[str, Any], buckets: list[dict[str, Any]], cliente: dict[str, Any]
    ) -> dict[str, Any]:
        # Replica TOTALES_CABECERA, solo la rama aplicable a pedidos/
        # presupuestos (la rama especial "Facturas de Albaran" es
        # CBV_TIPDOC='F', que nunca ocurre aqui). Incluye el caso
        # CLI_REGIVA IN ('S','I') que fusiona toda la base en BASIMP1 con
        # PORIVA/PORREQ a 0 para ese cubo.
        cbv = dict(cbv)
        for i in range(1, 5):
            cbv[f"CBV_BASIMP{i}"] = Decimal("0")
            cbv[f"CBV_PORIVA{i}"] = Decimal("0")
            cbv[f"CBV_PORREQ{i}"] = Decimal("0")

        regiva_exento = cliente["regiva"] in ("S", "I")
        basimp1_extra = Decimal("0")
        slot = 0
        for bucket in buckets:
            slot += 1
            if slot > 4:
                break
            baseimp = bucket["baseimp"]
            poriva = bucket["poriva"]
            porreq = bucket["porreq"]
            if regiva_exento:
                basimp1_extra += baseimp
                baseimp = Decimal("0")
                poriva = Decimal("0")
                porreq = Decimal("0")
            if slot == 1:
                if not regiva_exento:
                    cbv["CBV_BASIMP1"] = baseimp
                cbv["CBV_PORIVA1"] = poriva
                cbv["CBV_PORREQ1"] = porreq
            elif slot == 2:
                cbv["CBV_BASIMP2"] = baseimp
                cbv["CBV_PORIVA2"] = poriva
                cbv["CBV_PORREQ2"] = porreq
            elif slot == 3:
                cbv["CBV_BASIMP3"] = baseimp
                cbv["CBV_PORIVA3"] = poriva
                cbv["CBV_PORREQ3"] = porreq
            elif slot == 4:
                cbv["CBV_BASIMP4"] = baseimp
                cbv["CBV_PORIVA4"] = poriva
                cbv["CBV_PORREQ4"] = porreq
        if regiva_exento:
            cbv["CBV_BASIMP1"] = cbv["CBV_BASIMP1"] + basimp1_extra

        pordto = dec(cbv["CBV_PORDTO"])
        total_sin_iva = (
            cbv["CBV_BASIMP1"] * (1 - pordto / 100) + cbv["CBV_IMPPOR"]
            + cbv["CBV_BASIMP2"] * (1 - pordto / 100)
            + cbv["CBV_BASIMP3"] * (1 - pordto / 100)
            + cbv["CBV_BASIMP4"] * (1 - pordto / 100)
        )
        cbv["CBV_TOTALS"] = self.round_price_order(total_sin_iva, cbv["CBV_CODMON"], "I")

        total_con_iva = (
            (cbv["CBV_BASIMP1"] * (1 - pordto / 100) + cbv["CBV_IMPPOR"])
            * (1 + cbv["CBV_PORIVA1"] / 100 + cbv["CBV_PORREQ1"] / 100)
            + cbv["CBV_BASIMP2"] * (1 - pordto / 100) * (1 + cbv["CBV_PORIVA2"] / 100 + cbv["CBV_PORREQ2"] / 100)
            + cbv["CBV_BASIMP3"] * (1 - pordto / 100) * (1 + cbv["CBV_PORIVA3"] / 100 + cbv["CBV_PORREQ3"] / 100)
            + cbv["CBV_BASIMP4"] * (1 - pordto / 100) * (1 + cbv["CBV_PORIVA4"] / 100 + cbv["CBV_PORREQ4"] / 100)
        )
        cbv["CBV_TOTALD"] = self.round_price_order(total_con_iva, cbv["CBV_CODMON"], "I")

        for i in range(1, 5):
            cbv[f"CBV_BASIMP{i}"] = self.round_price_order(cbv[f"CBV_BASIMP{i}"], cbv["CBV_CODMON"], "I")

        return cbv

    def _modificar_cabdocv_totales(self, cbv: dict[str, Any]) -> None:
        # UPDATE dirigido solo a las columnas de totales/IVA (en vez de
        # reescribir con MODIFICAR_CABDOCV las ~40 columnas de la cabecera,
        # igual simplificacion deliberada que en save_client frente a
        # GRABAR_CLIEN('M')).
        self.db.execute(
            "UPDATE CABDOCV SET CBV_BASIMP1=?, CBV_PORIVA1=?, CBV_PORREQ1=?, CBV_BASIMP2=?, CBV_PORIVA2=?, "
            "CBV_PORREQ2=?, CBV_BASIMP3=?, CBV_PORIVA3=?, CBV_PORREQ3=?, CBV_BASIMP4=?, CBV_PORIVA4=?, "
            "CBV_PORREQ4=?, CBV_TOTALS=?, CBV_TOTALD=? "
            "WHERE CBV_NUMEMP=? AND CBV_CENTRO=? AND CBV_TIPDOC=? AND CBV_TIPAC=? AND CBV_EJERCI=? "
            "AND CBV_SERIE=? AND CBV_NUMDOC=?",
            (
                cbv["CBV_BASIMP1"], cbv["CBV_PORIVA1"], cbv["CBV_PORREQ1"],
                cbv["CBV_BASIMP2"], cbv["CBV_PORIVA2"], cbv["CBV_PORREQ2"],
                cbv["CBV_BASIMP3"], cbv["CBV_PORIVA3"], cbv["CBV_PORREQ3"],
                cbv["CBV_BASIMP4"], cbv["CBV_PORIVA4"], cbv["CBV_PORREQ4"],
                cbv["CBV_TOTALS"], cbv["CBV_TOTALD"],
                cbv["CBV_NUMEMP"], cbv["CBV_CENTRO"], cbv["CBV_TIPDOC"], cbv["CBV_TIPAC"], cbv["CBV_EJERCI"],
                cbv["CBV_SERIE"], cbv["CBV_NUMDOC"],
            ),
        )

    def _finalizar_documento_venta(self, cbv: dict[str, Any]) -> dict[str, Any]:
        # Replica FINALIZAR_CABDOCV (rama SITUAC='P', siempre aplicable a los
        # casos de esta fase): si el documento se queda sin lineas en DETMOV
        # para su clave (NUMEMP,CENTRO,TIPDOC,TIPAC,EJERCI,SERIE,NUMDOC), se
        # borra la cabecera igual que GRABAR_CABDOCV(R_CBV,'A',...) hace para
        # TIPDOC<>'F' con 0 lineas (solo BORRAR_CABDOCV; no aplica el bloque
        # de Efectos/reasignacion, que es solo para TIPDOC='F', ni el de
        # PROMOCION, que se salta explicitamente para TIPDOC IN ('P','R')).
        # ACTUALIZA_RIESGO_CLIENTE se omite en ambos casos (fuera de alcance
        # de esta fase, ver docstring de save_client_order).
        #
        # Generico a proposito (no asume CBV_TIPDOC='P'): ademas de en
        # save_client_order, se reutiliza en save_order_delivery tanto para
        # la cabecera 'S' (historico de lo servido de un Albaran) como para
        # recortar/borrar la cabecera 'P' original del pedido tras servirlo
        # total o parcialmente.
        count_row = self.db.fetch_one(
            "SELECT COUNT(*) AS N FROM DETMOV WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPDOC=? "
            "AND DMV_TIPAC=? AND DMV_EJERCI=? AND DMV_SERIE=? AND DMV_NUMDOC=?",
            (cbv["CBV_NUMEMP"], cbv["CBV_CENTRO"], cbv["CBV_TIPDOC"], cbv["CBV_TIPAC"], cbv["CBV_EJERCI"],
             cbv["CBV_SERIE"], cbv["CBV_NUMDOC"]),
        )
        total_lineas = int(count_row.get("N") or 0) if count_row else 0
        if total_lineas == 0:
            self.db.execute(
                "DELETE FROM CABDOCV WHERE CBV_NUMEMP=? AND CBV_CENTRO=? AND CBV_TIPDOC=? AND CBV_TIPAC=? "
                "AND CBV_EJERCI=? AND CBV_SERIE=? AND CBV_NUMDOC=?",
                (cbv["CBV_NUMEMP"], cbv["CBV_CENTRO"], cbv["CBV_TIPDOC"], cbv["CBV_TIPAC"], cbv["CBV_EJERCI"],
                 cbv["CBV_SERIE"], cbv["CBV_NUMDOC"]),
            )
            return {"cabecera_borrada": True, "totals": None}

        cliente = self._busqueda_clien_pedido(cbv["CBV_CODCLI"], cbv["CBV_SUBCLI"])
        buckets = self._iva_cabdocv_pedido(cbv)
        cbv_totales = self._totales_cabecera_pedido(cbv, buckets, cliente)

        if cbv_totales["CBV_PORDTO"] != 0:
            self.db.execute(
                "UPDATE DETMOV SET DMV_IMPDTO = DMV_VALLINS * ? WHERE DMV_NUMEMP=? AND DMV_CENTRO=? "
                "AND DMV_TIPDOC=? AND DMV_TIPAC=? AND DMV_EJERCI=? AND DMV_SERIE=? AND DMV_NUMDOC=?",
                (
                    dec(cbv_totales["CBV_PORDTO"]) / 100, cbv_totales["CBV_NUMEMP"], cbv_totales["CBV_CENTRO"],
                    cbv_totales["CBV_TIPDOC"], cbv_totales["CBV_TIPAC"], cbv_totales["CBV_EJERCI"],
                    cbv_totales["CBV_SERIE"], cbv_totales["CBV_NUMDOC"],
                ),
            )

        efectos = 0
        if (cbv_totales["CBV_TIPDOC"] == "F" and cbv_totales["CBV_SITUAC"] == "P"
                and int(cbv_totales.get("CBV_CODPAG") or 0) > 0):
            efectos = self._generate_invoice_effects(cbv_totales)

        self._modificar_cabdocv_totales(cbv_totales)
        self._update_cabdocv_runtime_fields(cbv_totales)

        riesgo = None
        if (int(cbv_totales["CBV_CODCLI"]) != 99999) or (int(cbv_totales["CBV_SUBCLI"]) != 0):
            riesgo = self._actualiza_riesgo_cliente(cbv_totales)

        return {
            "cabecera_borrada": False,
            "efectos": efectos,
            "riesgo": riesgo,
            "totals": {
                "basimp1": cbv_totales["CBV_BASIMP1"], "poriva1": cbv_totales["CBV_PORIVA1"],
                "porreq1": cbv_totales["CBV_PORREQ1"],
                "basimp2": cbv_totales["CBV_BASIMP2"], "poriva2": cbv_totales["CBV_PORIVA2"],
                "porreq2": cbv_totales["CBV_PORREQ2"],
                "basimp3": cbv_totales["CBV_BASIMP3"], "poriva3": cbv_totales["CBV_PORIVA3"],
                "porreq3": cbv_totales["CBV_PORREQ3"],
                "basimp4": cbv_totales["CBV_BASIMP4"], "poriva4": cbv_totales["CBV_PORIVA4"],
                "porreq4": cbv_totales["CBV_PORREQ4"],
                "totals": cbv_totales["CBV_TOTALS"], "totald": cbv_totales["CBV_TOTALD"],
            },
        }

    def save_client_order(
        self,
        centro: Any,
        codcli: Any,
        subcli: Any,
        texto: str,
        observaciones: str = "",
        email: str = "",
        urgente: str = "",
    ) -> dict[str, Any]:
        # Replica Grabar_Pedido_Cliente. Formato de TEXTO: lineas separadas
        # por '#', cada una con 5 campos separados por '|':
        #   CODART|DESCRI|CANTID|PREVEN|DTO1
        # OBSERVACIONES: lineas de comentario separadas por retorno de carro
        # (\r), cada una se graba como un DETMOV de tipo 'C' (TIPLIN='C'),
        # truncada a 100 caracteres, igual que el original.
        # URGENTE='R' crea un Presupuesto (CBV_TIPDOC='R'); cualquier otro
        # valor crea un Pedido (CBV_TIPDOC='P').
        #
        # ACUMULA_DETMOV (que es lo unico que toca ARTICULE/stock en el flujo
        # de insercion de GRABAR_DETMOV) siempre hace no-op cuando
        # DMV_SIGNO='0', y DMV_SIGNO solo llega a '1' para TIPDOC en
        # ('T','A','C','F') -- nunca para 'P'/'R'. Por eso Grabar_Pedido_Cliente
        # NUNCA toca existencias/stock, y este puerto tampoco lo hace.
        #
        # Simplificaciones y exclusiones deliberadas frente al Delphi original
        # (documentadas tambien en FASE1_PYTHON_DIRECTO.md):
        #  1) PRECIO_VENTA completo (ofertas activas, precios especiales por
        #     cliente/grupo/tabla, descuentos por familia, tarifas por
        #     actividad, articulos-canon) se omite: como Grabar_Pedido_Cliente
        #     siempre sobrescribe DMV_PREVEN/DMV_DTO1 con los valores que
        #     llegan en TEXTO justo despues de llamar a PRECIO_VENTA, toda esa
        #     cascada de precios especiales es trabajo desechado. Solo se
        #     replica lo que si sobrevive: resolucion del articulo (con su
        #     fallback CLIART), DMV_UNIMED/DMV_CODMON/DMV_PVP y el calculo de
        #     DMV_PORIVA/DMV_PORREQ (override PIVA o TIPIVA+recargo). Como
        #     efecto secundario, DMV_NUMOFE/DMV_EJEOFE (estadisticas de
        #     ofertas) quedan siempre a 0 en vez de heredar una oferta activa.
        #  2) El multiplicador ART.CANTIDAD de PRECIO_VENTA
        #     (DMV_CANTID := ART.CANTIDAD * DMV_CANTID) se omite: ese campo
        #     nunca se asigna en CARGAR_ARTICUL (comportamiento indefinido de
        #     un campo de registro Delphi sin inicializar), asi que replicarlo
        #     significaria adivinar basura de pila. Se usa DMV_CANTID tal cual
        #     llega del llamante.
        #  3) Cambio de divisa (CAMBIAR_PRECIO) no implementado: se asume
        #     'E' (Euro) en cabecera, articulos y lineas; si un articulo o
        #     linea resuelve a otra moneda se lanza FaroError en vez de
        #     adivinar una conversion.
        #  4) ACTUALIZA_RIESGO_CLIENTE / RIESGO_ACTUAL (riesgo de credito del
        #     cliente) no implementado: es un subsistema grande, solo
        #     parcialmente analizado, y queda fuera de alcance de esta fase.
        #  5) Envio de email (ENVIAR_CORREO) no implementado: este MCP no
        #     tiene SMTP configurado. El parametro EMAIL se acepta por
        #     fidelidad de firma pero se ignora (se informa en el resultado).
        #  6) CBV_USUMOD/DMV_USUAR se graban siempre como el literal 'admin'
        #     (no self.settings.usuario): asi lo hace tambien el Delphi
        #     original (linea literal, no un descuido), probablemente porque
        #     este RPC se expone a un canal externo sin sesion de usuario
        #     interna real. Se replica tal cual.
        #  7) BUSQUEDA_CLIEN: se corrige el descuido de no comprobar el
        #     centinela CLI_CODCLI=-1 (cliente inexistente) -- ver
        #     _busqueda_clien_pedido -- y la resolucion de articulo rechaza
        #     con FaroError un CODART que no se puede resolver -- ver
        #     _resolve_order_article -- en vez de grabar datos en blanco/a
        #     medias como hace el original.
        #  8) Correccion de un bug heredado (igual que en fases anteriores:
        #     etiquetas, recuento, faltas, actividad): el Delphi original hace
        #     FIN_TRANSACCION(TRUE) incondicional (confirma la transaccion
        #     pase lo que pase, incluso con R_PARSQL.CODERR<>0). Aqui se hace
        #     rollback si cualquier paso falla.
        centro_int = int(centro)
        codcli_int = int(codcli)
        subcli_int = int(subcli)
        tipdoc = "R" if urgente == "R" else "P"
        tipac = "0"
        ejerci = date.today().year
        serie = "PM"
        hoy = date.today()
        now = datetime.now()

        cliente = self._busqueda_clien_pedido(codcli_int, subcli_int)
        tipven = self._busqueda_tipven2(tipdoc, tipac)

        cbv: dict[str, Any] = {
            "CBV_NUMEMP": self.settings.empresa, "CBV_CENTRO": centro_int, "CBV_TIPDOC": tipdoc,
            "CBV_TIPAC": tipac, "CBV_EJERCI": ejerci, "CBV_SERIE": serie, "CBV_NUMDOC": 0,
            "CBV_CAJA": 1, "CBV_FECHA": hoy, "CBV_FECHAE": hoy, "CBV_CODCLI": codcli_int,
            "CBV_SUBCLI": subcli_int, "CBV_CODREP": cliente["codrep"], "CBV_COMREP": Decimal("0"),
            "CBV_NOMCLI": cliente["razsoc"], "CBV_CIF": cliente["cif"], "CBV_DOMCLI": cliente["domici"],
            "CBV_CODPOS": cliente["codpos"], "CBV_POBLAC": cliente["poblac"], "CBV_CODPAG": cliente["forpag"],
            "CBV_FORENV": cliente["forenv"], "CBV_PORDTO": cliente["dtoesp"], "CBV_IMPPOR": Decimal("0"),
            "CBV_BASIMP1": Decimal("0"), "CBV_PORIVA1": Decimal("0"), "CBV_PORREQ1": Decimal("0"),
            "CBV_BASIMP2": Decimal("0"), "CBV_PORIVA2": Decimal("0"), "CBV_PORREQ2": Decimal("0"),
            "CBV_BASIMP3": Decimal("0"), "CBV_PORIVA3": Decimal("0"), "CBV_PORREQ3": Decimal("0"),
            "CBV_BASIMP4": Decimal("0"), "CBV_PORIVA4": Decimal("0"), "CBV_PORREQ4": Decimal("0"),
            "CBV_TOTALS": Decimal("0"), "CBV_TOTALD": Decimal("0"), "CBV_IMPCOB": Decimal("0"),
            "CBV_CODMON": "E", "CBV_FORCOB": "", "CBV_NUMTAR": 0, "CBV_TIPVEN": tipven,
            "CBV_SITUAC": "P", "CBV_INDEDI": "N", "CBV_OBSERV": "", "CBV_EJERCID": 0,
            "CBV_TIPDOCD": "", "CBV_SERIED": "", "CBV_NUMDOCD": 0, "CBV_FECMOD": now,
            "CBV_USUMOD": "admin", "CBV_REFCLI": "", "CBV_RETIRA": "", "CBV_CODTAR": "",
        }

        numdoc = None
        lineas = 0
        lineas_comentario = 0
        try:
            numdoc = self._insert_cabdocv_order(cbv)
            cbv["CBV_NUMDOC"] = numdoc

            numlin = 10
            resto = texto or ""
            valor, resto = self._procesar_cadena(resto, "#")
            while valor != "":
                codart_in, resto_campos = self._procesar_cadena(valor, "|")
                descri_in, resto_campos = self._procesar_cadena(resto_campos, "|")
                cantid_txt, resto_campos = self._procesar_cadena(resto_campos, "|")
                preven_txt, resto_campos = self._procesar_cadena(resto_campos, "|")
                dto1_txt, _resto_campos = self._procesar_cadena(resto_campos, "|")

                dmv = self._build_order_line(
                    cbv, numlin, codart_in, descri_in, cantid_txt, preven_txt, dto1_txt, cliente
                )
                self._insert_detmov_pedido(dmv)
                lineas += 1
                numlin += 10
                valor, resto = self._procesar_cadena(resto, "#")

            resto_obs = observaciones or ""
            valor, resto_obs = self._procesar_cadena(resto_obs, "\r")
            while valor != "":
                dmv = self._build_comment_line(cbv, numlin, valor)
                self._insert_detmov_pedido(dmv)
                lineas_comentario += 1
                numlin += 10
                valor, resto_obs = self._procesar_cadena(resto_obs, "\r")

            finalizacion = self._finalizar_documento_venta(cbv)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "centro": centro_int, "codcli": codcli_int, "subcli": subcli_int,
            "tipdoc": tipdoc, "ejerci": ejerci, "serie": serie, "numdoc": numdoc,
            "lineas": lineas, "lineas_comentario": lineas_comentario,
            **finalizacion,
            "email_omitido": bool(email),
        }

    # ------------------------------------------------------------------
    # Cierre de pedidos (Cerrar_Pedido)
    # ------------------------------------------------------------------

    def close_client_order(
        self, usuario: str, centro: Any, tipdoc: str, ejerci: Any, serie: str, numdoc: Any
    ) -> dict[str, Any]:
        # Replica CERRAR_PEDIDO. Renumera un documento abierto de cliente
        # (Pedido/Presupuesto CBV_TIPDOC 'P'/'R') a TIPDOC='S' tanto en
        # CABDOCV como en DETMOV: lo marca como historico/cerrado sin
        # borrarlo.
        #
        # BUG DEL ORIGINAL Y CORRECCION DELIBERADA: el Delphi original
        # ejecuta, sin ninguna comprobacion de error entre medias:
        #   1) UPDATE CABDOCV SET CBV_TIPDOC='S', CBV_FECHA=DATE,
        #      CBV_USUMOD=usuario, CBV_FECMOD=NOW WHERE <clave con el
        #      TIPDOC ORIGINAL>
        #   2) UPDATE DETMOV SET DMV_TIPDOC='S' WHERE <misma clave>
        #   3) DELETE FROM CABDOCV WHERE <MISMA clave, TIPDOC ORIGINAL>
        #   4) DELETE FROM DETMOV WHERE <misma clave>
        # y confirma con FIN_TRANSACCION(True) de forma incondicional,
        # devolviendo Result := (CODERR del ULTIMO statement = 0) -- solo
        # refleja si el DELETE de DETMOV (paso 4) fue bien.
        #
        # En el caso normal, el paso 1 ya ha renombrado la cabecera a
        # TIPDOC='S', asi que los pasos 3/4 (que siguen filtrando por el
        # TIPDOC ORIGINAL) no encuentran nada y son inofensivos (no-op).
        # PERO si el paso 1 falla por colision de clave primaria -- ya
        # existe una cabecera CBV_TIPDOC='S' con el mismo
        # (NUMEMP,CENTRO,TIPAC,EJERCI,SERIE,NUMDOC), por ejemplo porque este
        # documento ya se cerro una vez antes -- la fila original NUNCA se
        # renombra (sigue con su TIPDOC original), y entonces los pasos 3/4
        # SI la encuentran y la BORRAN, junto con todas sus lineas: el
        # documento desaparece silenciosamente y, como el paso 4 (el DELETE
        # de DETMOV) normalmente tiene exito, Result sigue devolviendo True.
        # Perdida de datos silenciosa.
        #
        # Aqui, en su lugar: se comprueba que el documento original exista;
        # se comprueba explicitamente ANTES de tocar nada si ya existe una
        # cabecera TIPDOC='S' en esa misma clave y, si es asi, se rechaza la
        # operacion con FaroError en vez de proceder al borrado; los
        # DELETE (pasos 3/4, no-op en el caso normal una vez descartada la
        # colision) se omiten; y se hace rollback si cualquier paso falla,
        # en vez de confirmar siempre la transaccion.
        centro_int = int(centro)
        ejerci_int = int(ejerci)
        numdoc_int = int(numdoc)
        tipdoc_norm = (tipdoc or "").strip().upper()
        serie_norm = (serie or "").strip()
        tipac = "0"
        empresa = self.settings.empresa
        if tipdoc_norm not in {"P", "R"}:
            raise FaroError(
                "pedido_cerrar solo puede cerrar pedidos (P) o presupuestos (R). "
                f"Tipo recibido: {tipdoc_norm or '<vacio>'}."
            )
        documento_nombre = "pedido" if tipdoc_norm == "P" else "presupuesto"

        key_cols = (
            "CBV_NUMEMP=? AND CBV_CENTRO=? AND CBV_TIPDOC=? AND CBV_TIPAC=? AND CBV_EJERCI=? "
            "AND CBV_SERIE=? AND CBV_NUMDOC=?"
        )
        key_vals = (empresa, centro_int, tipdoc_norm, tipac, ejerci_int, serie_norm, numdoc_int)

        original = self.db.fetch_one(f"SELECT CBV_NUMDOC FROM CABDOCV WHERE {key_cols}", key_vals)
        if not original:
            raise FaroError(
                f"Documento {tipdoc_norm}-{ejerci_int}-{serie_norm}-{numdoc_int} (centro {centro_int}) "
                "no encontrado; nada que cerrar."
            )
        colision = self.db.fetch_one(
            "SELECT CBV_NUMDOC FROM CABDOCV WHERE CBV_NUMEMP=? AND CBV_CENTRO=? AND CBV_TIPDOC='S' "
            "AND CBV_TIPAC=? AND CBV_EJERCI=? AND CBV_SERIE=? AND CBV_NUMDOC=?",
            (empresa, centro_int, tipac, ejerci_int, serie_norm, numdoc_int),
        )
        if colision:
            raise FaroError(
                f"Ya existe una cabecera cerrada (TIPDOC='S') para {ejerci_int}-{serie_norm}-{numdoc_int} "
                f"en el centro {centro_int}: este documento ya se cerro anteriormente. El Delphi "
                "original no comprueba esto y, en ese caso, BORRARIA silenciosamente el documento "
                "original en vez de renombrarlo (perdida de datos); aqui se rechaza la operacion en "
                "su lugar."
            )

        try:
            self.db.execute(
                "UPDATE CABDOCV SET CBV_TIPDOC='S', CBV_FECHA=?, CBV_USUMOD=?, CBV_FECMOD=? "
                f"WHERE {key_cols}",
                (date.today(), usuario, datetime.now(), *key_vals),
            )
            self.db.execute(
                "UPDATE DETMOV SET DMV_TIPDOC='S' WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPDOC=? "
                "AND DMV_TIPAC=? AND DMV_EJERCI=? AND DMV_SERIE=? AND DMV_NUMDOC=?",
                key_vals,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "centro": centro_int, "tipdoc": tipdoc_norm, "ejerci": ejerci_int, "serie": serie_norm,
            "numdoc": numdoc_int, "tipo_origen": tipdoc_norm, "tipo_destino": "S",
            "documento": documento_nombre, "cerrado": True,
        }

    # ------------------------------------------------------------------
    # Cierre de ordenes de compra (CABORC_UDM.CERRAR_CABORC)
    # ------------------------------------------------------------------

    def close_purchase_order(
        self, usuario: str, centro: Any, ejerci: Any, serie: str, numdoc: Any
    ) -> dict[str, Any]:
        """Replica el efecto de CERRAR_CABORC para una orden de compra completa.

        El Delphi marca cada linea DETORC con DOC_CIEMAN='S' y la regraba con
        GRABAR_DETORC(...,'M'), lo que fuerza DOC_SITUAC='C', DOC_CANPEN=0 y
        DOC_VALPEN=0 (via SITUACION_DETORC, que cierra la linea en cuanto ve
        DOC_CIEMAN='S', y VALORAR_DETORC, que revalora DOC_VALPEN a partir de
        DOC_CANPEN=0). Despues recalcula la situacion de CABORC; al haber
        cerrado manualmente todas las lineas, la cabecera queda COC_SITUAC='C'
        y COC_IMPPEN=0.

        Nota sobre la fuente: a diferencia del resto de herramientas de este
        fichero, CERRAR_CABORC no se invoca desde ningun RPC de
        ServerMethodsUnit1.pas (no hay equivalente DataSnap): su unico punto
        de llamada real es FuentesDelphi/CABORC_UB.pas
        (TCABORC_FB.CerrarPedido1Click), la pantalla de busqueda de ordenes de
        compra del cliente Delphi de escritorio.

        Dos diferencias deliberadas frente a ese origen, no presentes en el
        Delphi original:

        1. Commit incondicional (mismo patron que Grabar_Etiquetas/
           Grabar_Recuento/Cerrar_Pedido, ya documentados en otras fases):
           CerrarPedido1Click hace INICIO_TRANSACCION/FIN_TRANSACCION(TRUE)
           sin mirar el CODERR de CERRAR_CABORC, asi que si GRABAR_DETORC
           falla a mitad de las lineas, la transaccion se confirma igual con
           el pedido a medio cerrar. Esta funcion hace rollback si cualquier
           UPDATE falla.
        2. COC_FECMOD/COC_USUMOD: el Delphi original los deja tal cual estaban
           (CARGAR_CABORC carga el registro antes de cerrarlo y
           MODIFICAR_CABORC regraba esos dos campos sin cambiarlos), es decir,
           el cierre real no dejaba constancia de quien ni cuando se cerro.
           Esta funcion los actualiza explicitamente a la fecha/usuario
           actuales para dejar rastro de auditoria del cierre.
        """
        centro_int = int(centro)
        ejerci_int = int(ejerci)
        numdoc_int = int(numdoc)
        serie_norm = str(serie or "").strip()
        usuario_s = str(usuario or self.settings.usuario or "").strip()
        empresa = self.settings.empresa
        key_vals = (empresa, centro_int, ejerci_int, serie_norm, numdoc_int)
        key_where = (
            "COC_NUMEMP=? AND COC_CENTRO=? AND COC_EJERCI=? AND COC_SERIE=? AND COC_NUMDOC=?"
        )

        header = self.db.fetch_one(f"SELECT * FROM CABORC WHERE {key_where}", key_vals)
        if not header:
            raise FaroError(
                f"Orden de compra {ejerci_int}-{serie_norm}-{numdoc_int} "
                f"(centro {centro_int}) no encontrada; nada que cerrar."
            )
        header = normalize(header)
        lines = self.db.fetch_all(
            "SELECT DOC_NUMLIN, DOC_SITUAC, DOC_CIEMAN, DOC_CANPEN, DOC_VALPEN FROM DETORC "
            "WHERE DOC_NUMEMP=? AND DOC_CENTRO=? AND DOC_EJERCI=? AND DOC_SERIE=? AND DOC_NUMDOC=? "
            "ORDER BY DOC_NUMLIN",
            key_vals,
        )
        now = datetime.now()
        try:
            for line in lines:
                self.db.execute(
                    "UPDATE DETORC SET DOC_CIEMAN='S', DOC_SITUAC='C', DOC_CANPEN=0, DOC_VALPEN=0 "
                    "WHERE DOC_NUMEMP=? AND DOC_CENTRO=? AND DOC_EJERCI=? AND DOC_SERIE=? "
                    "AND DOC_NUMDOC=? AND DOC_NUMLIN=?",
                    (*key_vals, int(line["DOC_NUMLIN"])),
                )
            self.db.execute(
                "UPDATE CABORC SET COC_SITUAC='C', COC_IMPPEN=0, COC_FECMOD=?, COC_USUMOD=? "
                f"WHERE {key_where}",
                (now, usuario_s, *key_vals),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "centro": centro_int,
            "ejercicio": ejerci_int,
            "serie": serie_norm,
            "numero": numdoc_int,
            "cerrada": True,
            "lineas_cerradas": len(lines),
            "situacion_anterior": clean_text_value(header.get("COC_SITUAC")),
            "situacion": "C",
        }

    # ------------------------------------------------------------------
    # Entrega de pedidos: conversion en Albaran (Grabar_Albaran_Pedido)
    # ------------------------------------------------------------------

    def _busqueda_cabdocv(
        self, centro: int, tipac: str, tipdoc: str, ejerci: int, serie: str, numdoc: int
    ) -> dict[str, Any] | None:
        # Replica BUSQUEDA_CABDOCV. Solo se ha localizado en la copia
        # obsoleta la implementacion historica de CABDOCV (misma discrepancia ya
        # documentada para BUSQUEDA_TIPVEN2 en save_client_order: no existe
        # en los DataModules/ vigentes, pero opera sobre columnas estandar
        # de CABDOCV, sin logica adicional sospechosa). Devuelve None si no
        # se encuentra (equivalente al centinela CBV_NUMDOC=0 del original).
        row = self.db.fetch_one(
            "SELECT * FROM CABDOCV WHERE CBV_NUMEMP=? AND CBV_CENTRO=? AND CBV_TIPDOC=? AND CBV_TIPAC=? "
            "AND CBV_EJERCI=? AND CBV_SERIE=? AND CBV_NUMDOC=?",
            (self.settings.empresa, centro, tipdoc, tipac, ejerci, serie, numdoc),
        )
        if not row:
            return None
        return normalize(row)

    def _cliente_info_adicional(self, codcli: int, subcli: int, codinf: str) -> str:
        row = self.db.fetch_one(
            "SELECT CLII_DESCRI FROM CLIENI WHERE CLII_NUMEMP=? AND CLII_CODCLI=? AND CLII_SUBCLI=? "
            "AND CLII_CODINF=?",
            (self.settings.empresa, codcli, subcli, codinf),
        )
        return clean_text_value(row.get("CLII_DESCRI")) if row else ""

    def _serie_albaran_cliente(self, codcli: int, subcli: int) -> str:
        # Replica SERIE_ALBARAN_CLIENTE (solo en la copia obsoleta, misma
        # discrepancia que BUSQUEDA_CABDOCV): CLIENI adicional 'SERIE'.
        return self._cliente_info_adicional(codcli, subcli, "SERIE")

    def _forma_pago_cliente(self, codcli: int, subcli: int) -> int:
        # Replica FORMA_PAGO_CLIENTE (solo en la copia obsoleta): CLI_FORPAG.
        row = self.db.fetch_one(
            "SELECT CLI_FORPAG FROM CLIEN WHERE CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
            (self.settings.empresa, codcli, subcli),
        )
        return int(row["CLI_FORPAG"]) if row and row.get("CLI_FORPAG") is not None else 0

    def _formato_documento_cliente(self, tipdoc: str, tipac: str, codcli: int, subcli: int) -> int:
        # Replica FORMATO_DOCUMENTO_CLIENTE (solo en la copia obsoleta):
        # segun TIPDOC, consulta un campo adicional de CLIENI especifico
        # (TIPDOC='A' -> 'TIVEN', TIPDOC='F' -> 'TIVFC', TIPDOC='D' ->
        # 'TIVFA'); si no hay valor (u otro TIPDOC), cae a
        # BUSQUEDA_TIPVEN2(TIPDOC,TIPAC).
        formato = ""
        if tipdoc == "A":
            formato = self._cliente_info_adicional(codcli, subcli, "TIVEN")
        elif tipdoc == "F":
            formato = self._cliente_info_adicional(codcli, subcli, "TIVFC")
        elif tipdoc == "D":
            formato = self._cliente_info_adicional(codcli, subcli, "TIVFA")
        if not formato:
            return self._busqueda_tipven2(tipdoc, tipac)
        try:
            return int(formato)
        except Exception:
            return 0

    # Tabla de SERIE_TICKET (Delphi): TABLA[1..9] son los digitos '1'..'9' y
    # TABLA[10..31] son las letras 'A'..'V', en ese orden; solo hacen falta
    # las 31 primeras posiciones porque codifica un mes (1-12) o un dia
    # (1-31). Se indexa restando 1 (aqui es una cadena 0-based).
    _SERIE_TICKET_TABLA = "123456789ABCDEFGHIJKLMNOPQRSTUV"

    def _serie_ticket_fallback(self, fecha: Any | None = None) -> str:
        """Replica SERIE_TICKET(FECHA) del Delphi: dos caracteres, mes y dia
        codificados con _SERIE_TICKET_TABLA. El Delphi usa
        R_PARAMETROS.FECHA_PROCESO cuando no se pasa FECHA explicita; ese
        concepto de "fecha de proceso" separada no existe en FARO_MCP.PY
        (que usa la fecha de hoy como fecha actual en todo el resto del
        fichero), asi que aqui se hace lo mismo."""
        f = fecha if fecha is not None else date.today()
        return self._SERIE_TICKET_TABLA[f.month - 1] + self._SERIE_TICKET_TABLA[f.day - 1]

    def _serie_ticket(self, centro: Any | None = None) -> str:
        """Serie de un ticket (TIPDOC='T'). GRABAR_TICKET busca en
        PARAMETROS la clave 'TT'+centro -no 'T'+centro, a diferencia del
        resto de tipos de documento (_serie_documento)- y, si no hay
        ninguna fila configurada para ese centro, cae al algoritmo
        SERIE_TICKET en vez de dejar la serie vacia."""
        centro_serie = self.settings.centro if centro is None else int(centro)
        serie = str(self.parameter(f"TT{centro_serie}", "") or "")
        return serie if serie else self._serie_ticket_fallback()

    def _serie_documento(self, tipdoc: str, centro: Any | None = None) -> str:
        centro_serie = self.settings.centro if centro is None else int(centro)
        return str(self.parameter(f"{tipdoc}{centro_serie}", "") or "")

    def _grabar_existencias_albaran(
        self, codart: str, centro: int, delta_bruto: Decimal, fecmov: Any
    ) -> None:
        # Replica GRABAR_EXISTENCIAS (funcion anidada de ACUMULA_DETMOV),
        # con ARTE_FECVEN=DMV_FECMOV (a diferencia de
        # FaroPhase1Service.accumulate_stock, que fija ARTE_FECVEN=None:
        # se usa este helper nuevo en vez de aquel, deliberadamente, para no
        # arriesgar el comportamiento ya probado de accumulate_stock en
        # regularize_stock). ARTE_EXIST:=0 si el articulo no es inventariado
        # (ART_INDINV='N'), igual que el original.
        art = self.db.fetch_one(
            "SELECT ART_INDINV FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        if not art:
            return  # BUSQUEDA_ARTICUL sin resultado => GOTO FIN (no-op), replica fiel.
        delta = Decimal("0") if str(art.get("ART_INDINV") or "") == "N" else delta_bruto
        now = datetime.now()
        try:
            self.db.execute(
                "INSERT INTO ARTICULE (ARTE_NUMEMP, ARTE_CODART, ARTE_CENTRO, ARTE_EXIST, ARTE_MINIMO, "
                "ARTE_MAXIMO, ARTE_FECCOM, ARTE_FECVEN, ARTE_FECMOV) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.settings.empresa, codart, centro, delta, 0, 0, None, fecmov, now),
            )
            try:
                self.db.execute(
                    "INSERT INTO STOCKS (STO_NUMEMP, STO_CODART, STO_CENTRO, STO_FECHA, STO_EXIST) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (self.settings.empresa, codart, self.settings.centro, fecmov, 0),
                )
            except Exception:
                pass
        except Exception:
            self.db.execute(
                "UPDATE ARTICULE SET ARTE_EXIST=ARTE_EXIST + ?, ARTE_FECVEN=?, ARTE_FECMOV=? WHERE "
                "ARTE_NUMEMP=? AND ARTE_CODART=? AND ARTE_CENTRO=?",
                (delta, fecmov, now, self.settings.empresa, codart, centro),
            )

    def _acumula_detmov_albaran(self, dmv: dict[str, Any], operacion: int) -> None:
        # Replica ACUMULA_DETMOV. No-op si DMV_SIGNO='0' (siempre el caso
        # para lineas de comentario, TIPLIN='C'). Para lineas de producto de
        # Albaran (TIPLIN='D', SIGNO='1') decrementa existencias del propio
        # articulo, o de cada componente de ARTICULB si el articulo es un
        # blister (ART_INDBLI='S') y el parametro global 'BLISTE' esta
        # activo, en cuyo caso la cantidad de cada componente es
        # DMV_CANTID * ARTB_CANTID.
        if dmv.get("DMV_SIGNO") != "1":
            return
        codart = str(dmv.get("DMV_CODART") or "").strip()
        if not codart:
            return
        art = self.db.fetch_one(
            "SELECT ART_INDBLI FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        if not art:
            return
        es_blister = str(art.get("ART_INDBLI") or "") == "S" and self.parameter("BLISTE", "") == "S"
        cantid = dec(dmv["DMV_CANTID"])
        if es_blister:
            componentes = self.db.fetch_all(
                "SELECT ARTB_CODARTB, ARTB_CANTID FROM ARTICULB WHERE ARTB_CODART=?", (codart,)
            )
            for comp in componentes:
                comp = normalize(comp)
                cantid_comp = cantid * dec(comp.get("ARTB_CANTID"))
                self._grabar_existencias_albaran(
                    str(comp.get("ARTB_CODARTB") or "").strip(),
                    dmv["DMV_CENTRO"],
                    -cantid_comp * operacion,
                    dmv["DMV_FECMOV"],
                )
        else:
            self._grabar_existencias_albaran(codart, dmv["DMV_CENTRO"], -cantid * operacion, dmv["DMV_FECMOV"])

    def _grabar_detmov_g_albaran(self, dmv: dict[str, Any]) -> dict[str, Any]:
        # Replica GRABAR_DETMOV en su rama 'G' (alta), restringido al caso
        # real de una linea nueva de Albaran (DMV_TIPDOC='A'):
        #  - DMV_SIGNO: 'D' + TIPDOC in ('T','A','C','F') => '1'; para
        #    cualquier otra combinacion (incluida TIPLIN='C', comentario),
        #    '0'. Para TIPDOC='A' con TIPLIN='D' siempre da '1' -- a
        #    diferencia de las lineas de pedido/presupuesto (SIGNO='0', ver
        #    _valorar_detmov_pedido/save_client_order), asi que ESTA linea
        #    SI dispara ACUMULA_DETMOV (decremento real de existencias).
        #  - Validacion "No tiene precio asignado": SI se aplica aqui (a
        #    diferencia de las lineas de pedido, exentas via
        #    DMV_TIPDOC IN ('P','R')), salvo que el articulo tenga
        #    ART_TIPPRE='F' (precio fijo) o la linea venga de una oferta
        #    activa (DMV_NUMOFE<>0; en la practica siempre 0 aqui, porque el
        #    pedido de origen nunca registra ofertas -- ver limitacion ya
        #    documentada en save_client_order/_build_order_line -- asi que
        #    esta validacion si puede saltar en la practica para articulos
        #    sin precio fijo y DMV_PREVEN=0).
        dmv["DMV_SIGNO"] = "1" if dmv["DMV_TIPLIN"] == "D" and dmv["DMV_TIPDOC"] in ("T", "A", "C", "F") else "0"

        if dmv["DMV_TIPLIN"] == "D" and dec(dmv["DMV_PREVEN"]) == 0:
            art = self.db.fetch_one(
                "SELECT ART_TIPPRE FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                (self.settings.empresa, dmv["DMV_CODART"]),
            )
            tippre = str(art.get("ART_TIPPRE") or "") if art else ""
            exento = (not art) or tippre == "F" or int(dmv.get("DMV_NUMOFE") or 0) != 0 or dmv["DMV_TIPDOC"] in ("P", "R")
            if not exento:
                raise FaroError(
                    f"{dmv['DMV_CODART']}-{dmv['DMV_DESCRI']}  --> ! No tiene precio asignado !"
                )

        self._acumula_detmov_albaran(dmv, 1)
        dmv = self._valorar_vencur_line(dmv)
        self._insert_detmov_pedido(dmv)
        return dmv

    def _insertar_linea_servida(self, dmv_ped: dict[str, Any], cantid_servida: Decimal) -> None:
        # Replica INSERTAR_LINEA_DETMOV (rama de servicio parcial de
        # Grabar_Albaran_Pedido): copia la linea de pedido, cambia
        # DMV_TIPDOC a 'S' y DMV_CANTID a lo servido, y la inserta bajo el
        # MISMO NUMDOC del pedido (fila distinta porque DMV_TIPDOC forma
        # parte de la clave). Llamada directa a INSERTAR_DETMOV en el
        # original -- SIN pasar por GRABAR_DETMOV -- por lo que no hay
        # revalorizacion (VALLIN/VALLINS quedan igual que en la linea de
        # pedido original, calculados para la cantidad TOTAL, no la
        # servida) ni efecto sobre existencias/stock. Replica fiel,
        # incluida esta inexactitud del original.
        servida = dict(dmv_ped)
        servida["DMV_TIPDOC"] = "S"
        servida["DMV_CANTID"] = cantid_servida
        self._insert_detmov_pedido(servida)

    def _actualizar_linea_pedido_servida(self, dmv_ped: dict[str, Any], cantid_servida: Decimal) -> None:
        # Replica ACTUALIZAR_LINEA_DETMOV (rama de servicio total, o
        # sobre-servicio, de Grabar_Albaran_Pedido): UPDATE directo (sin
        # GRABAR_DETMOV, sin revalorizacion) que convierte la linea de
        # pedido EN SU SITIO a TIPDOC='S' con la cantidad servida. El WHERE
        # de este UPDATE usa el valor ANTIGUO de DMV_TIPDOC ('P'), por lo
        # que localiza correctamente la fila antes de renombrarla.
        #
        # El GRABAR_DETMOV(R_DMV,'A',...) (borrado) que el original ejecuta
        # justo despues de esto se omite aqui a proposito: BORRAR_DETMOV
        # filtra tambien por el DMV_TIPDOC antiguo ('P'), que ya no existe
        # tras este UPDATE -- es codigo muerto/no-op confirmado releyendo
        # BORRAR_DETMOV (DataModules/CABDOCV_UDM.pas), no una correccion de
        # bug.
        self.db.execute(
            "UPDATE DETMOV SET DMV_TIPDOC='S', DMV_CANTID=? WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND "
            "DMV_TIPDOC=? AND DMV_TIPAC=? AND DMV_EJERCI=? AND DMV_SERIE=? AND DMV_NUMDOC=? AND DMV_NUMLIN=?",
            (
                cantid_servida,
                dmv_ped["DMV_NUMEMP"], dmv_ped["DMV_CENTRO"], dmv_ped["DMV_TIPDOC"], dmv_ped["DMV_TIPAC"],
                dmv_ped["DMV_EJERCI"], dmv_ped["DMV_SERIE"], dmv_ped["DMV_NUMDOC"], dmv_ped["DMV_NUMLIN"],
            ),
        )

    def _reducir_linea_pedido_pendiente(self, dmv_ped: dict[str, Any], cantid_pendiente: Decimal) -> None:
        # Replica el efecto util de GRABAR_DETMOV('M') sobre la linea de
        # pedido original en el caso de servicio parcial: revaloriza
        # VALLIN/VALLINS para la cantidad pendiente restante y actualiza
        # DMV_CANTID. ACUMULA_DETMOV (des/re-acumulacion de stock, que el
        # original SI ejecuta en esta rama) se omite a proposito porque
        # siempre es no-op aqui: DMV_SIGNO sigue siendo '0' en una linea de
        # pedido/presupuesto (TIPDOC 'P'/'R'), igual que ya se establece en
        # _valorar_detmov_pedido/save_client_order.
        dmv_pendiente = dict(dmv_ped)
        dmv_pendiente["DMV_CANTID"] = cantid_pendiente
        dmv_pendiente = self._valorar_detmov_pedido(dmv_pendiente)
        self.db.execute(
            "UPDATE DETMOV SET DMV_CANTID=?, DMV_VALLIN=?, DMV_VALLINS=? WHERE DMV_NUMEMP=? AND "
            "DMV_CENTRO=? AND DMV_TIPDOC=? AND DMV_TIPAC=? AND DMV_EJERCI=? AND DMV_SERIE=? AND "
            "DMV_NUMDOC=? AND DMV_NUMLIN=?",
            (
                dmv_pendiente["DMV_CANTID"], dmv_pendiente["DMV_VALLIN"], dmv_pendiente["DMV_VALLINS"],
                dmv_pendiente["DMV_NUMEMP"], dmv_pendiente["DMV_CENTRO"], dmv_pendiente["DMV_TIPDOC"],
                dmv_pendiente["DMV_TIPAC"], dmv_pendiente["DMV_EJERCI"], dmv_pendiente["DMV_SERIE"],
                dmv_pendiente["DMV_NUMDOC"], dmv_pendiente["DMV_NUMLIN"],
            ),
        )

    def save_order_delivery(self, centro: Any, codigo_pedido: str, texto: str) -> dict[str, Any]:
        # Replica Grabar_Albaran_Pedido: convierte (total o parcialmente) un
        # Pedido (CBV_TIPDOC='P') en un Albaran (CBV_TIPDOC='A'), sirviendo
        # cada linea por la cantidad indicada.
        #
        # CODIGO_PEDIDO: 'EJERCICIO-SERIE-NUMERO' (PROCESAR_CADENA con '-').
        # TEXTO: lineas separadas por '#', cada una con 4 campos separados
        # por '|': NUMLIN|CODART|DESCRI|CANTID. CODART y DESCRI se parsean
        # pero NUNCA se usan en el original (campos muertos en el formato de
        # cable) -- solo NUMLIN (para localizar la linea de pedido) y CANTID
        # (lo que se sirve) importan realmente; se replica esa misma
        # irrelevancia.
        #
        # Por cada linea servida:
        #  - Si queda cantidad pendiente (CANTID_PEDIDO - CANTID_SERVIDA >
        #    0): la linea de pedido original se reduce (revalorizada,
        #    sigue TIPDOC='P') y se inserta una copia "servida" con
        #    TIPDOC='S' bajo el numero del propio pedido, sin revalorizar
        #    (ver _insertar_linea_servida/_reducir_linea_pedido_pendiente).
        #  - Si no queda pendiente (servicio total o sobre-servicio): la
        #    linea de pedido se convierte en su sitio a TIPDOC='S' con la
        #    cantidad servida, sin revalorizar (ver
        #    _actualizar_linea_pedido_servida).
        #  - En ambos casos se crea ademas una linea NUEVA en el Albaran,
        #    copiando los datos de articulo/precio de la linea de pedido
        #    ORIGINAL (antes de las modificaciones anteriores) pero con
        #    CANTID=lo servido y numeracion/origen propios (ver
        #    _grabar_detmov_g_albaran). Esta es la UNICA linea de las tres
        #    que dispara descuento real de existencias (DMV_SIGNO='1'
        #    porque su DMV_TIPDOC='A'; las otras dos son TIPDOC 'P'/'S',
        #    SIGNO siempre '0').
        #  - Una linea de pedido con NUMLIN inexistente (por ejemplo, ya
        #    consumida del todo en una entrega anterior) se ignora en
        #    silencio -- igual que el original, que simplemente no entra en
        #    la rama "IF FOUND".
        #
        # Al terminar todas las lineas: se replica el cierre final del
        # original (R_CBV3/doble FINALIZAR_CABDOCV), que crea/actualiza una
        # cabecera CABDOCV historica con CBV_TIPDOC='S' (mismo NUMDOC que el
        # pedido) reflejando el total de lo servido hasta ahora -- incluye
        # lo servido en entregas anteriores, porque las lineas 'S' de
        # entregas previas siguen bajo la misma clave -- y despues recalcula
        # (o borra si ya no quedan lineas 'P') la cabecera del PEDIDO
        # original. Se reutiliza _finalizar_documento_venta (generico) para
        # ambas.
        #
        # CORRECCION DE UN BUG DEL ORIGINAL (fuga de recursos): el Delphi
        # original hace INICIO_TRANSACCION antes de comprobar si el pedido
        # existe, y en TODOS sus puntos de salida por error
        # (Result:=False; Exit;) -- pedido no encontrado, fallo al grabar la
        # cabecera del Albaran, fallo al grabar cualquier linea -- termina
        # la funcion SIN LLAMAR A FIN_TRANSACCION, dejando la transaccion
        # abierta indefinidamente. Aqui, en su lugar: la existencia del
        # pedido se comprueba ANTES de escribir nada, y todo lo demas va
        # dentro de un try/except que siempre hace commit o rollback.
        #
        # La insercion de la cabecera 'S' (R_CBV3) puede fallar en el
        # original si el pedido ya se entrego parcialmente antes (colision
        # de clave primaria con la cabecera 'S' de esa entrega previa); el
        # original ignora ese fallo (sigue con FINALIZAR_CABDOCV igualmente)
        # -- aqui se replica esa tolerancia explicitamente (insercion
        # "mejor esfuerzo"), pero como FINALIZAR_CABDOCV siempre recalcula
        # los totales de la cabecera 'S' a partir de TODAS sus lineas
        # actuales (UPDATE, no depende de que la insercion haya tenido
        # exito), no hay perdida de datos: los totales quedan siempre
        # correctos.
        #
        # FUERA DE ALCANCE (documentado, no implementado):
        #  - Impresion/generacion del Albaran via TIdTCPClient a
        #    localhost:45000 (proceso externo ALBLASF.exe): no hay ese
        #    servicio de impresion disponible en este entorno; esta funcion
        #    solo graba los datos y los devuelve.
        #  - BUSQUEDA_CABDOCV, SERIE_ALBARAN_CLIENTE, FORMA_PAGO_CLIENTE,
        #    FORMATO_DOCUMENTO_CLIENTE (y sus variantes de factura): solo
        #    localizadas en la copia obsoleta la implementacion historica de CABDOCV
        #    (misma discrepancia ya documentada para BUSQUEDA_TIPVEN2).
        #  - Mismas exclusiones ya documentadas en save_client_order:
        #    PRECIO_VENTA completo, cambio de divisa, riesgo de cliente.
        #  - CBV_USUMOD de la cabecera del Albaran NO se sobrescribe: hereda
        #    el valor de la cabecera del pedido de origen (asi lo hace
        #    tambien el Delphi original: R_CBV es una copia de R_CBV2 y
        #    nunca se toca ese campo).
        centro_int = int(centro)
        ejerci_txt, resto = self._procesar_cadena(codigo_pedido or "", "-")
        serie_txt, resto = self._procesar_cadena(resto, "-")
        numdoc_txt, _resto = self._procesar_cadena(resto, "-")
        try:
            ejerci_ped = int(ejerci_txt)
            numdoc_ped = int(numdoc_txt)
        except Exception as exc:
            raise FaroError(
                f"CODIGO_PEDIDO invalido: '{codigo_pedido}' (formato esperado 'EJERCICIO-SERIE-NUMERO')."
            ) from exc
        serie_ped = serie_txt.strip()
        tipac = "0"

        pedido = self._busqueda_cabdocv(centro_int, tipac, "P", ejerci_ped, serie_ped, numdoc_ped)
        if pedido is None:
            raise FaroError(
                f"Pedido {ejerci_ped}-{serie_ped}-{numdoc_ped} (centro {centro_int}) no encontrado. El "
                "Delphi original devuelve un centinela (CBV_NUMDOC=0) y aborta con Result:=False sin "
                "cerrar la transaccion ya abierta (fuga de recursos); aqui se rechaza con FaroError "
                "antes de abrir ninguna transaccion."
            )

        hoy = date.today()

        alb: dict[str, Any] = dict(pedido)
        alb["CBV_TIPDOC"] = "A"
        alb["CBV_EJERCI"] = hoy.year
        alb["CBV_FECHA"] = hoy
        serie_alb = self._serie_albaran_cliente(pedido["CBV_CODCLI"], pedido["CBV_SUBCLI"])
        alb["CBV_SERIE"] = serie_alb if serie_alb else self._serie_documento("A")
        alb["CBV_NUMDOC"] = 0
        alb["CBV_CODPAG"] = self._forma_pago_cliente(pedido["CBV_CODCLI"], pedido["CBV_SUBCLI"])
        alb["CBV_TIPDOCD"] = pedido["CBV_TIPDOC"]
        alb["CBV_EJERCID"] = pedido["CBV_EJERCI"]
        alb["CBV_SERIED"] = pedido["CBV_SERIE"]
        alb["CBV_NUMDOCD"] = pedido["CBV_NUMDOC"]
        alb["CBV_TIPVEN"] = self._formato_documento_cliente("A", tipac, pedido["CBV_CODCLI"], pedido["CBV_SUBCLI"])

        lineas_servidas: list[dict[str, Any]] = []
        numlin_alb = 10
        try:
            numdoc_alb = self._insert_cabdocv_order(alb)
            alb["CBV_NUMDOC"] = numdoc_alb

            resto_lineas = texto or ""
            valor, resto_lineas = self._procesar_cadena(resto_lineas, "#")
            while valor != "":
                numlin_txt, campos = self._procesar_cadena(valor, "|")
                _codart_txt, campos = self._procesar_cadena(campos, "|")  # dead field, ver docstring
                _descri_txt, campos = self._procesar_cadena(campos, "|")  # dead field, ver docstring
                cantid_txt, _campos = self._procesar_cadena(campos, "|")

                try:
                    numlin_ped = int(numlin_txt)
                except Exception:
                    numlin_ped = None
                cantid_servida = self._parse_decimal_pedido(cantid_txt, "CANTID")

                dmv_ped = None
                if numlin_ped is not None:
                    dmv_ped = self.db.fetch_one(
                        "SELECT * FROM DETMOV WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPDOC=? AND "
                        "DMV_TIPAC=? AND DMV_EJERCI=? AND DMV_SERIE=? AND DMV_NUMDOC=? AND DMV_NUMLIN=?",
                        (pedido["CBV_NUMEMP"], pedido["CBV_CENTRO"], pedido["CBV_TIPDOC"], pedido["CBV_TIPAC"],
                         pedido["CBV_EJERCI"], pedido["CBV_SERIE"], pedido["CBV_NUMDOC"], numlin_ped),
                    )
                if not dmv_ped:
                    valor, resto_lineas = self._procesar_cadena(resto_lineas, "#")
                    continue
                dmv_ped = normalize(dmv_ped)

                dmv_alb = dict(dmv_ped)
                dmv_alb["DMV_NUMEMP"] = alb["CBV_NUMEMP"]
                dmv_alb["DMV_CENTRO"] = alb["CBV_CENTRO"]
                dmv_alb["DMV_TIPDOC"] = "A"
                dmv_alb["DMV_TIPAC"] = alb["CBV_TIPAC"]
                dmv_alb["DMV_EJERCI"] = alb["CBV_EJERCI"]
                dmv_alb["DMV_SERIE"] = alb["CBV_SERIE"]
                dmv_alb["DMV_NUMDOC"] = alb["CBV_NUMDOC"]
                dmv_alb["DMV_CANTID"] = cantid_servida
                dmv_alb["DMV_FECMOV"] = hoy
                dmv_alb["DMV_EJERCIO"] = pedido["CBV_EJERCI"]
                dmv_alb["DMV_TIPDOCO"] = pedido["CBV_TIPDOC"]
                dmv_alb["DMV_SERIEO"] = pedido["CBV_SERIE"]
                dmv_alb["DMV_NUMDOCO"] = pedido["CBV_NUMDOC"]
                dmv_alb["DMV_NUMLINO"] = numlin_ped
                dmv_alb["DMV_NUMLIN"] = numlin_alb
                numlin_alb += 10

                cantid_pendiente = dec(dmv_ped["DMV_CANTID"]) - cantid_servida
                if cantid_pendiente > 0:
                    self._insertar_linea_servida(dmv_ped, cantid_servida)
                    self._reducir_linea_pedido_pendiente(dmv_ped, cantid_pendiente)
                else:
                    self._actualizar_linea_pedido_servida(dmv_ped, cantid_servida)

                self._grabar_detmov_g_albaran(dmv_alb)
                lineas_servidas.append({"numlin_pedido": numlin_ped, "cantidad": str(cantid_servida)})
                valor, resto_lineas = self._procesar_cadena(resto_lineas, "#")

            cbv3 = dict(pedido)
            cbv3["CBV_TIPDOC"] = "S"
            try:
                self._insert_cabdocv_row(cbv3)
            except Exception:
                pass  # ya existe de una entrega parcial anterior; se recalculan sus totales igualmente.
            finalizacion_servido = self._finalizar_documento_venta(cbv3)
            finalizacion_pendiente = self._finalizar_documento_venta(dict(pedido))

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "centro": centro_int,
            "pedido": {"ejerci": ejerci_ped, "serie": serie_ped, "numdoc": numdoc_ped},
            "albaran": {"tipdoc": "A", "ejerci": alb["CBV_EJERCI"], "serie": alb["CBV_SERIE"], "numdoc": alb["CBV_NUMDOC"]},
            "lineas_servidas": lineas_servidas,
            "pedido_historico_servido": finalizacion_servido,
            "pedido_pendiente": finalizacion_pendiente,
            "impresion_omitida": True,
        }

    # ------------------------------------------------------------------
    # Fase 2H - documentos, ficheros, imagenes y correo
    # ------------------------------------------------------------------

    def _main_root(self) -> Path:
        return Path(self.settings.main_dir or r"C:\FaroERP")

    def _documents_root(self) -> Path:
        configured = (self.settings.documents_dir or "").strip()
        return Path(configured) if configured else self._main_root() / "Documentos"

    def _images_root(self) -> Path:
        configured = (self.settings.images_dir or "").strip()
        return Path(configured) if configured else self._main_root() / "Imagenes"

    def _order_pdf_dir(self) -> Path:
        configured = os.getenv("FARO_PEDIDOS_PDF_DIR", "").strip()
        return Path(configured) if configured else self._main_root() / "Documentos" / "Ventas" / "Pedidos"

    @staticmethod
    def _path_inside(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            return False

    def _allowed_file_roots(self) -> list[Path]:
        roots = [self._main_root(), self._documents_root(), self._images_root(), self._order_pdf_dir()]
        extra = os.getenv("FARO_FILE_ROOTS", "").strip()
        if extra:
            roots.extend(Path(item.strip()) for item in extra.split(os.pathsep) if item.strip())
        # Quitar duplicados conservando orden.
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root)
            if key not in seen:
                seen.add(key)
                unique.append(root)
        return unique

    def _safe_child(self, root: Path, relative_name: str) -> Path:
        # Los paths guardados por Delphi suelen contener '\\' incluso si se
        # ejecutan pruebas/migraciones desde otro SO.
        normalized = str(relative_name or "").replace("\\", os.sep).replace("/", os.sep)
        candidate = root / normalized
        if not self._path_inside(candidate, root):
            raise FaroError("Ruta fuera del directorio permitido.")
        return candidate

    def _resolve_read_file(self, nombre_fichero: str) -> Path:
        raw = str(nombre_fichero or "").strip()
        if not raw:
            raise FaroError("NombreFichero no puede estar vacio.")
        normalized = raw.replace("\\", os.sep).replace("/", os.sep)
        supplied = Path(normalized)
        roots = self._allowed_file_roots()
        if supplied.is_absolute():
            candidate = supplied
            if not any(self._path_inside(candidate, root) for root in roots):
                raise FaroError("GetFichero no permite leer fuera de los directorios Faro configurados.")
            return candidate
        # Para un nombre relativo, el servidor anterior recibia normalmente un path ya
        # resuelto. En MCP buscamos primero Documentos y despues el raiz Faro.
        for root in [self._documents_root(), self._main_root(), self._images_root(), self._order_pdf_dir()]:
            candidate = self._safe_child(root, normalized)
            if candidate.exists():
                return candidate
        return self._safe_child(self._documents_root(), normalized)

    def save_text_file(self, nombre_fichero: str, texto: str) -> dict[str, Any]:
        """Migra Grabar_Fichero: DIR\\NombreFichero.TXT + una linea de texto."""
        name = str(nombre_fichero or "").strip()
        if not name:
            raise FaroError("NombreFichero no puede estar vacio.")
        target = self._safe_child(self._documents_root(), name + ".TXT")
        target.parent.mkdir(parents=True, exist_ok=True)
        encoding = os.getenv("FARO_TEXT_ENCODING", "cp1252")
        # WRITELN del Delphi anade fin de linea.
        target.write_text(str(texto or "") + os.linesep, encoding=encoding, newline="")
        return {"ok": True, "path": str(target), "datasnap_text": ""}

    def _file_payload(self, path: Path) -> dict[str, Any]:
        if not path.exists() or not path.is_file():
            return {
                "exists": False, "path": str(path), "size": 0,
                "content_base64": "", "mime_type": "application/octet-stream",
            }
        data = path.read_bytes()
        return {
            "exists": True,
            "path": str(path),
            "size": len(data),
            "content_base64": base64.b64encode(data).decode("ascii"),
            "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        }

    def get_file(self, nombre_fichero: str) -> dict[str, Any]:
        """Equivalente MCP de GetFichero(TBytesStream), transportado como Base64."""
        return self._file_payload(self._resolve_read_file(nombre_fichero))

    def get_file_as_string(self, nombre_fichero: str) -> dict[str, Any]:
        """Migra GetFicheroAsString: Base64 del stream devuelto por GetFichero."""
        payload = self.get_file(nombre_fichero)
        return {
            **payload,
            "datasnap_text": payload["content_base64"],
        }

    def _article_image_path(self, articulo: str, tamano: str) -> Path | None:
        row = self.db.fetch_one(
            "SELECT ARTI_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND ARTI_CODINF=?",
            (self.settings.empresa, str(articulo), "IMAGE"),
        )
        if not row:
            return None
        root = self._images_root()
        if str(tamano or "").upper() == "P":
            return self._safe_child(root, os.path.join("resized", f"{articulo}.jpg"))
        file_name = str(row.get("ARTI_DESCRI") or "").strip()
        if not file_name:
            return None
        return self._safe_child(root, file_name)

    def article_image_as_string(self, articulo: str, tamano: str = "") -> dict[str, Any]:
        """Migra GetImagenBannerAsString."""
        path = self._article_image_path(articulo, tamano)
        payload = self._file_payload(path) if path else {
            "exists": False, "path": "", "size": 0, "content_base64": "", "mime_type": "application/octet-stream"
        }
        return {"articulo": str(articulo), "tamano": str(tamano), **payload, "datasnap_text": payload["content_base64"]}

    def article_image_as_json(self, articulo: str, tamano: str = "") -> dict[str, Any]:
        """Migra GetImagenBannerAsJSON usando Base64, formato natural para contenido MCP JSON."""
        result = self.article_image_as_string(articulo, tamano)
        result["transport"] = "base64"
        return result

    def _order_pdf_path(self, ejerci: Any, serie: str, numdoc: Any) -> Path:
        serie_safe = str(serie or "").strip().replace("/", "").replace("\\", "")
        if not serie_safe:
            raise FaroError("SERIE no puede estar vacia.")
        return self._safe_child(
            self._order_pdf_dir(),
            f"P-{int(ejerci)}-{serie_safe}-{int(numdoc)}.pdf",
        )

    def order_pdf_as_json(self, ejerci: Any, serie: str, numdoc: Any) -> dict[str, Any]:
        """Migra GetPdfAsJSON para los PDF de pedidos."""
        payload = self._file_payload(self._order_pdf_path(ejerci, serie, numdoc))
        return {"ejerci": int(ejerci), "serie": str(serie).strip(), "numdoc": int(numdoc), **payload, "transport": "base64"}

    def _load_order_for_pdf(self, centro: Any, ejerci: Any, serie: str, numdoc: Any) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
        centro_i, ejerci_i, numdoc_i = int(centro), int(ejerci), int(numdoc)
        serie_s = str(serie or "").strip()
        header = self.db.fetch_one(
            "SELECT * FROM CABDOCV WHERE CBV_NUMEMP=? AND CBV_CENTRO=? AND CBV_TIPDOC='P' AND CBV_TIPAC='0' "
            "AND CBV_EJERCI=? AND CBV_SERIE=? AND CBV_NUMDOC=?",
            (self.settings.empresa, centro_i, ejerci_i, serie_s, numdoc_i),
        )
        if not header:
            raise FaroError(f"Pedido no encontrado: {centro_i}/{ejerci_i}/{serie_s}/{numdoc_i}")
        header = normalize(header)
        client = self.db.fetch_one(
            "SELECT * FROM CLIEN WHERE CLI_NUMEMP=? AND CLI_CODCLI=? AND CLI_SUBCLI=?",
            (self.settings.empresa, int(header.get("CBV_CODCLI") or 0), int(header.get("CBV_SUBCLI") or 0)),
        )
        client = normalize(client) if client else None
        lines = self.db.fetch_all(
            "SELECT * FROM DETMOV WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPDOC='P' AND DMV_TIPAC='0' "
            "AND DMV_EJERCI=? AND DMV_SERIE=? AND DMV_NUMDOC=? ORDER BY DMV_NUMLIN",
            (self.settings.empresa, centro_i, ejerci_i, serie_s, numdoc_i),
        )
        return header, client, [normalize(row) for row in lines]

    @staticmethod
    def _pdf_number(value: Any) -> str:
        try:
            return f"{Decimal(str(value or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return str(value or "")

    def generate_order_pdf(self, centro: Any, ejerci: Any, serie: str, numdoc: Any) -> dict[str, Any]:
        """Migra Generar_PDF_Pedido sin EDITAR_CABDOCV/FastReport."""
        try:
            from reportlab.lib import colors  # type: ignore
            from reportlab.lib.enums import TA_RIGHT  # type: ignore
            from reportlab.lib.pagesizes import A4  # type: ignore
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # type: ignore
            from reportlab.lib.units import mm  # type: ignore
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # type: ignore
        except ImportError as exc:
            raise FaroError("Instala 'reportlab' para generar PDF de pedidos.") from exc

        header, client, lines = self._load_order_for_pdf(centro, ejerci, serie, numdoc)
        target = self._order_pdf_path(ejerci, serie, numdoc)
        target.parent.mkdir(parents=True, exist_ok=True)

        styles = getSampleStyleSheet()
        right = ParagraphStyle("right", parent=styles["Normal"], alignment=TA_RIGHT)
        doc = SimpleDocTemplate(str(target), pagesize=A4, rightMargin=15 * mm, leftMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm)
        story: list[Any] = []
        story.append(Paragraph(f"<b>PEDIDO {int(ejerci)}-{str(serie).strip()}-{int(numdoc)}</b>", styles["Title"]))
        story.append(Spacer(1, 4 * mm))

        fecha = header.get("CBV_FECHA") or ""
        codcli = int(header.get("CBV_CODCLI") or 0)
        subcli = int(header.get("CBV_SUBCLI") or 0)
        razsoc = clean_text_value((client or {}).get("CLI_RAZSOC"))
        nif = clean_text_value((client or {}).get("CLI_NIF") or (client or {}).get("CLI_CIF"))
        domici = clean_text_value((client or {}).get("CLI_DOMICI"))
        poblac = clean_text_value((client or {}).get("CLI_POBLAC"))
        codpos = clean_text_value((client or {}).get("CLI_CODPOS"))
        meta = [
            ["Fecha", str(fecha), "Cliente", f"{codcli}/{subcli}"],
            ["Razon social", razsoc, "NIF", nif],
            ["Direccion", " ".join(x for x in [domici, codpos, poblac] if x), "", ""],
        ]
        mt = Table(meta, colWidths=[25 * mm, 65 * mm, 25 * mm, 55 * mm])
        mt.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.extend([mt, Spacer(1, 5 * mm)])

        data: list[list[Any]] = [["Cod.", "Descripcion", "Cantidad", "Precio", "Dto.", "Importe"]]
        for line in lines:
            tiplin = str(line.get("DMV_TIPLIN") or "D").strip()
            if tiplin == "C":
                data.append(["", clean_text_value(line.get("DMV_DESCRI")), "", "", "", ""])
                continue
            dto = dec(line.get("DMV_DTO1")) + dec(line.get("DMV_DTO2"))
            importe = line.get("DMV_VALLINS")
            if importe is None:
                importe = line.get("DMV_VALLIN")
            data.append([
                clean_text_value(line.get("DMV_CODART")),
                clean_text_value(line.get("DMV_DESCRI")),
                self._pdf_number(line.get("DMV_CANTID")),
                self._pdf_number(line.get("DMV_PREVEN")),
                self._pdf_number(dto),
                self._pdf_number(importe),
            ])
        table = Table(data, repeatRows=1, colWidths=[24 * mm, 73 * mm, 20 * mm, 22 * mm, 17 * mm, 24 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.extend([table, Spacer(1, 5 * mm)])
        total = header.get("CBV_TOTALD") if header.get("CBV_TOTALD") is not None else header.get("CBV_TOTALS")
        story.append(Paragraph(f"<b>Total: {self._pdf_number(total)}</b>", right))
        observ = clean_text_value(header.get("CBV_OBSERV"))
        if observ:
            story.extend([Spacer(1, 3 * mm), Paragraph(f"<b>Observaciones:</b> {observ}", styles["Normal"])])
        doc.build(story)
        return {
            "ok": True, "centro": int(centro), "ejerci": int(ejerci), "serie": str(serie).strip(),
            "numdoc": int(numdoc), "path": str(target), "size": target.stat().st_size,
            "datasnap_text": "",
        }

    def _send_email_message(
        self, direccion: str, tema: str, texto: str, attachments: list[Path] | None = None
    ) -> dict[str, Any]:
        address = str(direccion or "").strip()
        if not address:
            raise FaroError("DIRECCION no puede estar vacia.")
        if not self.settings.smtp_host:
            raise FaroError("Falta FARO_SMTP_HOST para enviar correo.")
        sender = self.settings.smtp_from or self.settings.smtp_user
        if not sender:
            raise FaroError("Falta FARO_SMTP_FROM o FARO_SMTP_USER.")

        msg = EmailMessage()
        if self.settings.smtp_from_name:
            from email.utils import formataddr
            msg["From"] = formataddr((self.settings.smtp_from_name, sender))
        else:
            msg["From"] = sender
        msg["To"] = address
        msg["Subject"] = str(tema or "")
        msg.set_content(str(texto or ""))
        attached: list[str] = []
        for path in attachments or []:
            if not path.exists() or not path.is_file():
                raise FaroError(f"Adjunto no encontrado: {path}")
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            maintype, subtype = mime.split("/", 1)
            msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
            attached.append(str(path))

        timeout = float(os.getenv("FARO_SMTP_TIMEOUT", "15"))
        if self.settings.smtp_ssl:
            smtp: Any = smtplib.SMTP_SSL(
                self.settings.smtp_host, self.settings.smtp_port, timeout=timeout,
                context=ssl.create_default_context(),
            )
        else:
            smtp = smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=timeout)
        try:
            if self.settings.smtp_starttls and not self.settings.smtp_ssl:
                smtp.starttls(context=ssl.create_default_context())
            if self.settings.smtp_user:
                smtp.login(self.settings.smtp_user, self.settings.smtp_password)
            smtp.send_message(msg)
        finally:
            try:
                smtp.quit()
            except Exception:
                smtp.close()
        return {
            "ok": True, "to": address, "subject": str(tema or ""), "attachments": attached,
            "datasnap_text": f"Enviado correo a {address} con exito",
        }

    def send_email(self, direccion: str, tema: str, texto: str) -> dict[str, Any]:
        """Migra ENVIAR_CORREO usando smtplib en lugar de Indy."""
        return self._send_email_message(direccion, tema, texto)

    def send_order(self, centro: Any, ejerci: Any, serie: str, numdoc: Any, email: str) -> dict[str, Any]:
        """Migra Enviar_Pedido: genera el PDF del pedido y lo envia adjunto."""
        generated = self.generate_order_pdf(centro, ejerci, serie, numdoc)
        header, client, _ = self._load_order_for_pdf(centro, ejerci, serie, numdoc)
        razsoc = clean_text_value((client or {}).get("CLI_RAZSOC"))
        subject = f"Pedido Nº: {int(numdoc)}"
        if razsoc:
            subject += f" Cliente: {razsoc}"
        body = os.getenv("FARO_PEDIDO_EMAIL_BODY", "Adjuntamos el pedido solicitado.")
        sent = self._send_email_message(str(email), subject, body, [Path(generated["path"])])
        # Enviar_Pedido devolvia siempre cadena vacia. Se conserva en
        # Se conserva el campo de texto historico y se anade resultado estructurado MCP.
        return {
            "ok": True, "centro": int(centro), "ejerci": int(ejerci), "serie": str(serie).strip(),
            "numdoc": int(numdoc), "pdf": generated["path"], "email": sent, "datasnap_text": "",
        }


    # ------------------------------------------------------------------
    # Consulta y preparacion de pedidos (Pedidos_Cliente, Cuadro_Pedidos,
    # Detalle_Pedido, Detalle_Pedido_Preparacion, Mover_Linea_Pedido,
    # Grabar_Pedido_Preparado, Finalizar_Pedido)
    # ------------------------------------------------------------------
    #
    # FUERA DE ALCANCE, documentado y no implementado: EDITAR_CABDOCV,
    # Enviar_Pedido y Generar_PDF_Pedido. Las tres delegan en
    # EDITAR_CABDOCV, que no hace nada con datos ni devuelve nada util: solo
    # envia un mensaje Windows WM_COPYDATA a un proceso GUI externo
    # (identificado por un manejador de ventana, MANEJADOR) pidiendole que
    # imprima/genere el PDF de un documento con una plantilla FastReport
    # ('PedidoW.fr3') o que lo envie por correo. No hay ningun proceso asi
    # en este entorno (ni un mecanismo equivalente), y las tres funciones
    # devuelven siempre cadena vacia incluso en el Delphi original si
    # MANEJADOR=0 (proceso no arrancado) o en cualquier otro caso (nunca
    # comprueban el resultado del envio). Implementar un stub que solo
    # devuelva '' no aportaria nada; se documenta la exclusion en su lugar.

    def list_client_orders(self, centro: Any, codcli: Any, subcli: Any) -> list[dict[str, Any]]:
        # Replica Pedidos_Cliente: lista de Pedidos ('P') de un cliente,
        # mas recientes primero.
        centro_int = int(centro)
        rows = self.db.fetch_all(
            "SELECT CBV_EJERCI, CBV_SERIE, CBV_NUMDOC, CBV_FECHA, CBV_TOTALS, CBV_TOTALD FROM CABDOCV "
            "WHERE CBV_NUMEMP=? AND CBV_CENTRO=? AND CBV_TIPAC='0' AND CBV_TIPDOC='P' AND CBV_CODCLI=? "
            "AND CBV_SUBCLI=? ORDER BY CBV_EJERCI DESC, CBV_NUMDOC DESC",
            (self.settings.empresa, centro_int, int(codcli), int(subcli)),
        )
        resultado = []
        artzon_columns = self.db.table_columns("ARTZON") if hasattr(self.db, "table_columns") else set()
        has_zon_ubica = "ZON_UBICA" in artzon_columns
        zon_select = "ZON_UBICA, ZON_CANTID" if has_zon_ubica else "ZON_CANTID"
        for row in rows:
            row = normalize(row)
            resultado.append({
                "ejerci": row.get("CBV_EJERCI"), "serie": clean_text_value(row.get("CBV_SERIE")),
                "numdoc": row.get("CBV_NUMDOC"),
                "fecha": str(row.get("CBV_FECHA")) if row.get("CBV_FECHA") is not None else "",
                "totals": row.get("CBV_TOTALS"), "totald": row.get("CBV_TOTALD"),
            })
        return resultado

    def _nombre_zona(self, zona: int) -> str:
        # Replica NOMBRE_ZONA (ARTUBI_UDM.pas).
        return {0: "Almacen", 1: "Dispensing", 2: "Zona 2", 3: "Zona 3", 4: "Zona 4"}.get(zona, "")

    def _descri_articul(self, codart: str) -> str:
        if not codart:
            return ""
        row = self.db.fetch_one(
            "SELECT ART_DESCRI FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
            (self.settings.empresa, codart),
        )
        return clean_text_value(row.get("ART_DESCRI")) if row else ""

    def _has_artubi_tables(self) -> bool:
        if not hasattr(self.db, "table_columns"):
            return True
        return bool(self.db.table_columns("ARTZON")) and bool(self.db.table_columns("ARTUBI"))

    def _require_artubi_tables(self) -> None:
        if not self._has_artubi_tables():
            raise FaroError(
                "La estructura de Faro no incluye ARTZON/ARTUBI; las herramientas de preparacion "
                "por zonas no estan disponibles en esta base."
            )

    def _codigo_linea(self, dmv: dict[str, Any]) -> str:
        # Replica CODIGO_LINEA (ARTUBI_UDM.pas): clave de texto que
        # identifica una linea de documento en ARTUBI.UBI_DOCUME.
        return (
            f"{dmv['DMV_CENTRO']}-{dmv['DMV_TIPDOC']}-{dmv['DMV_TIPAC']}-{dmv['DMV_EJERCI']}-"
            f"{dmv['DMV_SERIE']}-{dmv['DMV_NUMDOC']}-{dmv['DMV_NUMLIN']}"
        )

    def _acumula_artubi(self, ubi: dict[str, Any], operacion: int) -> None:
        self._require_artubi_tables()
        # Replica ACUMULA_ARTUBI: mantiene en ARTZON el saldo por
        # (centro, zona, articulo). Intenta INSERT; si ya existe fila para
        # esa clave, hace UPDATE sumando el delta. A diferencia del INSERT,
        # el UPDATE de repliegue solo toca ZON_CANTID/ZON_FECMOD/ZON_UBICA
        # (no ZON_ARTICULO/ZON_DESCRI/ZON_USUMOD): se replica fielmente esa
        # asimetria del original, no es un descuido de esta implementacion.
        delta = dec(ubi["UBI_CANTID"]) * operacion
        now = datetime.now()
        try:
            self.db.execute(
                "INSERT INTO ARTZON (ZON_NUMEMP, ZON_CENTRO, ZON_CODART, ZON_ZONA, ZON_CANTID, ZON_ARTICULO, "
                "ZON_DESCRI, ZON_FECMOD, ZON_USUMOD, ZON_UBICA) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ubi["UBI_NUMEMP"], ubi["UBI_CENTRO"], ubi["UBI_CODART"], ubi["UBI_ZONA"], delta,
                    self._descri_articul(ubi["UBI_CODART"]), self._nombre_zona(ubi["UBI_ZONA"]), now,
                    self.settings.usuario, ubi["UBI_UBICA"],
                ),
            )
        except Exception:
            self.db.execute(
                "UPDATE ARTZON SET ZON_CANTID = ZON_CANTID + ?, ZON_FECMOD=?, ZON_UBICA=? WHERE ZON_NUMEMP=? "
                "AND ZON_CENTRO=? AND ZON_ZONA=? AND ZON_CODART=?",
                (
                    delta, now, ubi["UBI_UBICA"], ubi["UBI_NUMEMP"], ubi["UBI_CENTRO"], ubi["UBI_ZONA"],
                    ubi["UBI_CODART"],
                ),
            )

    def _grabar_artubi_g(self, ubi: dict[str, Any]) -> None:
        # Replica GRABAR_ARTUBI('G'): acumula primero el saldo en ARTZON, y
        # solo si eso no lanza excepcion, inserta la fila de movimiento en
        # ARTUBI (bitacora). UBI_ID se inserta como NULL, igual que el
        # original (`INSERT INTO ARTUBI VALUES (NULL, ...)`), asumiendo un
        # generador/trigger de Firebird que lo autoasigna -- no se necesita
        # recuperar ese id despues, porque ninguna de las funciones de esta
        # fase modifica o borra una fila de ARTUBI por su id (solo insertan).
        self._acumula_artubi(ubi, 1)
        self.db.execute(
            "INSERT INTO ARTUBI (UBI_ID, UBI_NUMEMP, UBI_CENTRO, UBI_CODART, UBI_DESCRI, UBI_ZONA, UBI_UBICA, "
            "UBI_CANTID, UBI_FECHA, UBI_DOCUME) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                None, ubi["UBI_NUMEMP"], ubi["UBI_CENTRO"], ubi["UBI_CODART"], ubi["UBI_DESCRI"],
                ubi["UBI_ZONA"], ubi["UBI_UBICA"], ubi["UBI_CANTID"], ubi["UBI_FECHA"], ubi["UBI_DOCUME"],
            ),
        )

    def _sum_artubi(self, linea: str, zona: int) -> Decimal:
        self._require_artubi_tables()
        row = self.db.fetch_one(
            "SELECT SUM(UBI_CANTID) AS UBI_CANTID FROM ARTUBI WHERE UBI_NUMEMP=? AND UBI_DOCUME=? AND UBI_ZONA=?",
            (self.settings.empresa, linea, zona),
        )
        total = row.get("UBI_CANTID") if row else None
        return dec(total) if total is not None else Decimal("0")

    def order_board(self, centro: Any) -> list[dict[str, Any]]:
        # Replica Cuadro_Pedidos: panel de pedidos pendientes de preparar
        # para el almacen de un centro. Primera pasada: para cada articulo
        # con existencias > 0 en ZONA1 (almacen/"Dispensing"), localiza
        # todos los Pedidos que tengan una linea de ese articulo (sin
        # filtrar por cantidad pendiente ni firma, igual que el original) y
        # los añade con la ubicacion de ESE articulo -- si un pedido ya
        # estaba añadido (por otro articulo procesado antes), no se
        # actualiza su ubicacion: el original solo se queda con la del
        # primer articulo que lo encontro, no es un bug, es como esta
        # escrito (TFDMemTable.Locate + salto si ya existe). Segunda pasada:
        # añade tambien los pedidos con CBV_INDEDI='L' (en preparacion) que
        # aun no estuvieran en la lista, con ubicacion vacia. Al final,
        # para cada pedido (ordenados por ejercicio+numero) se recarga la
        # cabecera completa via BUSQUEDA_CABDOCV para sacar cliente/fecha/
        # total/estado.
        centro_int = int(centro)
        empresa = self.settings.empresa
        pedidos: dict[tuple, dict[str, Any]] = {}
        if not self._has_artubi_tables():
            en_prep = self.db.fetch_all(
                "SELECT CBV_TIPDOC, CBV_TIPAC, CBV_EJERCI, CBV_SERIE, CBV_NUMDOC FROM CABDOCV WHERE CBV_NUMEMP=? "
                "AND CBV_CENTRO=? AND CBV_TIPDOC='P' AND CBV_INDEDI='L'",
                (empresa, centro_int),
            )
            for cbv in en_prep:
                cbv = normalize(cbv)
                clave = (cbv["CBV_TIPDOC"], cbv["CBV_EJERCI"], cbv["CBV_SERIE"], cbv["CBV_NUMDOC"])
                pedidos[clave] = {
                    "tipdoc": cbv["CBV_TIPDOC"], "tipac": cbv["CBV_TIPAC"], "ejerci": cbv["CBV_EJERCI"],
                    "serie": clean_text_value(cbv["CBV_SERIE"]), "numdoc": cbv["CBV_NUMDOC"], "ubicacion": "",
                }
            resultado = []
            for clave in sorted(pedidos.keys(), key=lambda c: (c[1], c[3])):
                info = pedidos[clave]
                cabecera = self._busqueda_cabdocv(
                    centro_int, info["tipac"], info["tipdoc"], info["ejerci"], info["serie"], info["numdoc"]
                )
                if cabecera is None:
                    continue
                resultado.append({
                    "ejerci": cabecera["CBV_EJERCI"], "serie": clean_text_value(cabecera["CBV_SERIE"]),
                    "numdoc": cabecera["CBV_NUMDOC"], "codcli": cabecera["CBV_CODCLI"],
                    "subcli": cabecera["CBV_SUBCLI"], "nomcli": clean_text_value(cabecera["CBV_NOMCLI"]),
                    "fecha": str(cabecera["CBV_FECHA"]) if cabecera.get("CBV_FECHA") is not None else "",
                    "totald": cabecera["CBV_TOTALD"], "indedi": cabecera.get("CBV_INDEDI"),
                    "ubicacion": info["ubicacion"], "zonas_disponibles": False,
                })
            return resultado
        artzon_columns = self.db.table_columns("ARTZON") if hasattr(self.db, "table_columns") else set()
        has_zon_ubica = "ZON_UBICA" in artzon_columns

        zon_select = "ZON_CODART, ZON_UBICA" if has_zon_ubica else "ZON_CODART"
        zonas = self.db.fetch_all(
            f"SELECT {zon_select} FROM ARTZON WHERE ZON_NUMEMP=? AND ZON_CENTRO=? AND ZON_ZONA=1 "
            "AND ZON_CANTID > 0",
            (empresa, centro_int),
        )
        for zon in zonas:
            zon = normalize(zon)
            codart = zon.get("ZON_CODART")
            lineas = self.db.fetch_all(
                "SELECT DISTINCT DMV_TIPDOC, DMV_TIPAC, DMV_EJERCI, DMV_SERIE, DMV_NUMDOC FROM DETMOV "
                "WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPDOC='P' AND DMV_CODART=?",
                (empresa, centro_int, codart),
            )
            for lin in lineas:
                lin = normalize(lin)
                clave = (lin["DMV_TIPDOC"], lin["DMV_EJERCI"], lin["DMV_SERIE"], lin["DMV_NUMDOC"])
                if clave not in pedidos:
                    pedidos[clave] = {
                        "tipdoc": lin["DMV_TIPDOC"], "tipac": lin["DMV_TIPAC"], "ejerci": lin["DMV_EJERCI"],
                        "serie": clean_text_value(lin["DMV_SERIE"]), "numdoc": lin["DMV_NUMDOC"],
                        "ubicacion": clean_text_value(zon.get("ZON_UBICA")) if has_zon_ubica else "",
                    }

        en_prep = self.db.fetch_all(
            "SELECT CBV_TIPDOC, CBV_TIPAC, CBV_EJERCI, CBV_SERIE, CBV_NUMDOC FROM CABDOCV WHERE CBV_NUMEMP=? "
            "AND CBV_CENTRO=? AND CBV_TIPDOC='P' AND CBV_INDEDI='L'",
            (empresa, centro_int),
        )
        for cbv in en_prep:
            cbv = normalize(cbv)
            clave = (cbv["CBV_TIPDOC"], cbv["CBV_EJERCI"], cbv["CBV_SERIE"], cbv["CBV_NUMDOC"])
            if clave not in pedidos:
                pedidos[clave] = {
                    "tipdoc": cbv["CBV_TIPDOC"], "tipac": cbv["CBV_TIPAC"], "ejerci": cbv["CBV_EJERCI"],
                    "serie": clean_text_value(cbv["CBV_SERIE"]), "numdoc": cbv["CBV_NUMDOC"], "ubicacion": "",
                }

        resultado = []
        for clave in sorted(pedidos.keys(), key=lambda c: (c[1], c[3])):
            info = pedidos[clave]
            cabecera = self._busqueda_cabdocv(
                centro_int, info["tipac"], info["tipdoc"], info["ejerci"], info["serie"], info["numdoc"]
            )
            if cabecera is None:
                continue
            resultado.append({
                "ejerci": cabecera["CBV_EJERCI"], "serie": clean_text_value(cabecera["CBV_SERIE"]),
                "numdoc": cabecera["CBV_NUMDOC"], "codcli": cabecera["CBV_CODCLI"],
                "subcli": cabecera["CBV_SUBCLI"], "nomcli": clean_text_value(cabecera["CBV_NOMCLI"]),
                "fecha": str(cabecera["CBV_FECHA"]) if cabecera.get("CBV_FECHA") is not None else "",
                "totald": cabecera["CBV_TOTALD"], "indedi": cabecera.get("CBV_INDEDI"),
                "ubicacion": info["ubicacion"],
            })
        return resultado

    def order_lines(self, centro: Any, ejerci: Any, serie: str, numdoc: Any) -> list[dict[str, Any]]:
        # Replica Detalle_Pedido: lineas de un Pedido con su stock actual y
        # ubicaciones (ARTICULI, ARTI_CODINF LIKE 'UBIC%') para el articulo
        # de cada linea.
        centro_int = int(centro)
        rows = self.db.fetch_all(
            "SELECT * FROM DETMOV WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPAC='0' AND DMV_TIPDOC='P' "
            "AND DMV_EJERCI=? AND DMV_SERIE=? AND DMV_NUMDOC=? ORDER BY DMV_NUMLIN",
            (self.settings.empresa, centro_int, int(ejerci), (serie or "").strip(), int(numdoc)),
        )
        lineas = []
        for row in rows:
            row = normalize(row)
            codart = str(row.get("DMV_CODART") or "").strip()
            linea = {
                "numlin": row.get("DMV_NUMLIN"), "codart": codart,
                "descri": clean_text_value(row.get("DMV_DESCRI")),
                "cantid": row.get("DMV_CANTID"), "preven": row.get("DMV_PREVEN"),
                "dto1": row.get("DMV_DTO1"), "dto2": row.get("DMV_DTO2"),
                "poriva": row.get("DMV_PORIVA"), "pvp": row.get("DMV_PVP"),
                "vallins": row.get("DMV_VALLINS"), "vallin": row.get("DMV_VALLIN"),
            }
            if codart:
                linea["stock"] = self.current_stock_decimal(codart, centro_int)
                ubicaciones = self.db.fetch_all(
                    "SELECT ARTI_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND "
                    "ARTI_CODINF LIKE 'UBIC%'",
                    (self.settings.empresa, codart),
                )
                linea["ubicaciones"] = " ".join(
                    clean_text_value(u.get("ARTI_DESCRI")) for u in ubicaciones
                ).strip()
            else:
                linea["stock"] = None
                linea["ubicaciones"] = ""
            lineas.append(linea)
        return lineas

    def order_preparation_lines(self, centro: Any, ejerci: Any, serie: str, numdoc: Any) -> list[dict[str, Any]]:
        # Replica Detalle_Pedido_Preparacion: para cada linea del pedido,
        # cuanta cantidad hay disponible en almacen (ZONA1/ARTZON), en
        # preparacion (ZONA2/ARTUBI) y ya preparada (ZONA3/ARTUBI), con sus
        # ubicaciones, mas el stock global del articulo (UTL_STOCK, ya
        # implementado como current_stock_decimal).
        centro_int = int(centro)
        empresa = self.settings.empresa
        self._require_artubi_tables()
        artzon_columns = self.db.table_columns("ARTZON") if hasattr(self.db, "table_columns") else set()
        has_zon_ubica = "ZON_UBICA" in artzon_columns
        zon_select = "ZON_UBICA, ZON_CANTID" if has_zon_ubica else "ZON_CANTID"
        rows = self.db.fetch_all(
            "SELECT * FROM DETMOV WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPAC='0' AND DMV_TIPDOC='P' "
            "AND DMV_EJERCI=? AND DMV_SERIE=? AND DMV_NUMDOC=? ORDER BY DMV_NUMLIN",
            (empresa, centro_int, int(ejerci), (serie or "").strip(), int(numdoc)),
        )
        resultado = []
        for row in rows:
            dmv = normalize(row)
            codart = str(dmv.get("DMV_CODART") or "").strip()
            linea = self._codigo_linea(dmv)

            ubicacion = ""
            if codart:
                art_row = self.db.fetch_one(
                    "SELECT ARTI_DESCRI FROM ARTICULI WHERE ARTI_NUMEMP=? AND ARTI_CODART=? AND "
                    "ARTI_NUMLIN > 0 AND ARTI_CODINF='UBICA'",
                    (empresa, codart),
                )
                ubicacion = clean_text_value(art_row.get("ARTI_DESCRI")) if art_row else ""

            zon_row = self.db.fetch_one(
                f"SELECT {zon_select} FROM ARTZON WHERE ZON_NUMEMP=? AND ZON_CENTRO=? AND "
                "ZON_CODART=? AND ZON_ZONA=1",
                (empresa, centro_int, codart),
            )
            cantid1 = dec(zon_row.get("ZON_CANTID")) if zon_row and zon_row.get("ZON_CANTID") is not None else Decimal("0")
            ubic1 = clean_text_value(zon_row.get("ZON_UBICA")) if has_zon_ubica and zon_row and cantid1 > 0 else ""

            cantid2 = self._sum_artubi(linea, 2)
            ubic2 = ""
            if cantid2 > 0:
                ubi_row = self.db.fetch_one(
                    "SELECT FIRST 1 UBI_UBICA FROM ARTUBI WHERE UBI_NUMEMP=? AND UBI_DOCUME=? AND UBI_ZONA=2 "
                    "ORDER BY UBI_ID DESC",
                    (empresa, linea),
                )
                ubic2 = clean_text_value(ubi_row.get("UBI_UBICA")) if ubi_row else ""

            cantid3 = self._sum_artubi(linea, 3)
            ubic3 = ""
            if cantid3 > 0:
                ubi_row = self.db.fetch_one(
                    "SELECT FIRST 1 UBI_UBICA FROM ARTUBI WHERE UBI_NUMEMP=? AND UBI_DOCUME=? AND UBI_ZONA=3 "
                    "ORDER BY UBI_ID DESC",
                    (empresa, linea),
                )
                ubic3 = clean_text_value(ubi_row.get("UBI_UBICA")) if ubi_row else ""

            stock = self.current_stock_decimal(codart, centro_int) if codart else Decimal("0")

            resultado.append({
                "codart": codart, "descri": clean_text_value(dmv.get("DMV_DESCRI")),
                "cantidad_pedida": dmv.get("DMV_CANTID"), "ubicacion_articulo": ubicacion,
                "cantidad_almacen": cantid1, "ubicacion_almacen": ubic1,
                "ubicacion_preparacion": ubic2, "ubicacion_preparado": ubic3,
                "cantidad_en_preparacion": cantid2, "cantidad_preparada": cantid3,
                "cantidad_total_localizada": cantid1 + cantid2 + cantid3, "stock": stock, "linea": linea,
            })
        return resultado

    def move_order_line_zone(
        self, centro: Any, codart: str, descri: str, cantid: Any, linea: str,
        zona_origen: Any, zona_destino: Any, ubi_origen: str, ubi_destino: str,
    ) -> dict[str, Any]:
        # Replica Mover_Linea_Pedido: mueve manualmente una cantidad de un
        # articulo de una zona de almacen a otra (bitacora ARTUBI + saldo
        # ARTZON), para una LINEA (clave de texto, ver _codigo_linea) dada
        # por el llamante. Si ZONA_ORIGEN es '0' (ZONA0, "sin origen") no se
        # graba salida, solo la entrada en destino: la cantidad se
        # materializa sin descontar de ninguna zona real (igual que el
        # original).
        #
        # DETALLE REPLICADO LITERALMENTE (no es un descuido de esta
        # implementacion): a diferencia de la funcion COMPARTIDA
        # MOVER_LINEA_PEDIDO de ARTUBI_UDM.pas (usada internamente por
        # MARCAR_PEDIDO_PREPARADO/EN_PREPARACION, no por este RPC), que
        # ademas actualiza CBV_SITUAC='F' en la cabecera cuando el destino
        # es ZONA2, este RPC (Mover_Linea_Pedido) NUNCA toca CABDOCV: es una
        # reimplementacion manual e independiente en ServerMethodsUnit1.pas,
        # no una llamada a esa funcion compartida. Se replica exactamente
        # el comportamiento del RPC expuesto, no el de la funcion interna.
        centro_int = int(centro)
        self._require_artubi_tables()
        cantid_dec = self._parse_decimal_pedido(str(cantid), "CANTID")
        zona_origen_int = int(zona_origen)
        zona_destino_int = int(zona_destino)
        hoy = date.today()
        try:
            if zona_origen_int != 0:
                salida = {
                    "UBI_NUMEMP": self.settings.empresa, "UBI_CENTRO": centro_int, "UBI_CODART": codart,
                    "UBI_DESCRI": descri, "UBI_ZONA": zona_origen_int, "UBI_UBICA": ubi_origen,
                    "UBI_CANTID": -cantid_dec, "UBI_FECHA": hoy, "UBI_DOCUME": linea,
                }
                self._grabar_artubi_g(salida)
            entrada = {
                "UBI_NUMEMP": self.settings.empresa, "UBI_CENTRO": centro_int, "UBI_CODART": codart,
                "UBI_DESCRI": descri, "UBI_ZONA": zona_destino_int, "UBI_UBICA": ubi_destino,
                "UBI_CANTID": cantid_dec, "UBI_FECHA": hoy, "UBI_DOCUME": linea,
            }
            self._grabar_artubi_g(entrada)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {
            "centro": centro_int, "codart": codart, "cantidad": str(cantid_dec), "linea": linea,
            "zona_origen": zona_origen_int, "zona_destino": zona_destino_int, "movido": True,
        }

    def _mover_linea_pedido_auto(self, dmv: dict[str, Any], zona_origen: int, zona_destino: int) -> None:
        # Replica la funcion anidada MOV_LINEA_PEDIDO de Grabar_Pedido_Preparado
        # (misma logica de bitacora que move_order_line_zone/_grabar_artubi_g,
        # pero derivando linea/articulo/cantidad de un DETMOV, con
        # UBI_UBICA='' siempre, y sin tocar CBV_SITUAC -- igual que
        # move_order_line_zone, a diferencia de la funcion COMPARTIDA
        # MOVER_LINEA_PEDIDO de ARTUBI_UDM.pas).
        centro = dmv["DMV_CENTRO"]
        codart = dmv["DMV_CODART"]
        descri = dmv["DMV_DESCRI"]
        cantid = dec(dmv["DMV_CANTID"])
        linea = self._codigo_linea(dmv)
        hoy = date.today()
        if zona_origen > 0:
            salida = {
                "UBI_NUMEMP": self.settings.empresa, "UBI_CENTRO": centro, "UBI_CODART": codart,
                "UBI_DESCRI": descri, "UBI_ZONA": zona_origen, "UBI_UBICA": "", "UBI_CANTID": -cantid,
                "UBI_FECHA": hoy, "UBI_DOCUME": linea,
            }
            self._grabar_artubi_g(salida)
        entrada = {
            "UBI_NUMEMP": self.settings.empresa, "UBI_CENTRO": centro, "UBI_CODART": codart,
            "UBI_DESCRI": descri, "UBI_ZONA": zona_destino, "UBI_UBICA": "", "UBI_CANTID": cantid,
            "UBI_FECHA": hoy, "UBI_DOCUME": linea,
        }
        self._grabar_artubi_g(entrada)

    def save_order_prepared(self, centro: Any, tipdoc: str, ejerci: Any, serie: str, numdoc: Any) -> dict[str, Any]:
        # Replica Grabar_Pedido_Preparado: intenta dejar TODAS las lineas de
        # producto (TIPLIN='D', CANTID>0) de un documento marcadas como
        # "preparadas" (ZONA3) de un solo golpe, y despues pone
        # CBV_INDEDI='P' (PREPARADO) en la cabecera.
        #
        # Por cada linea que aun no tenga nada en ZONA3: si tiene cantidad
        # "en preparacion" (ZONA2), la mueve entera a ZONA3; si no, pero hay
        # existencias en ZONA1 (almacen), mueve el minimo entre lo
        # disponible y lo pedido; y si NO HAY NADA disponible en ninguna
        # zona, la mueve de todos modos desde ZONA0 ("sin origen"),
        # materializando la cantidad pedida completa sin descontar de
        # ningun sitio real.
        #
        # DETALLE IMPORTANTE REPLICADO LITERALMENTE (no es un bug que se
        # corrija aqui, es como funciona el original): por ese ultimo caso,
        # esta funcion SIEMPRE termina marcando cada linea como "preparada"
        # y la cabecera como CBV_INDEDI='P', exista o no exista de verdad
        # esa cantidad en el almacen. Es, en efecto, un "forzar preparado"
        # que no verifica stock real; se usa tal cual la expone el RPC
        # original, sin añadir una validacion de existencias que el Delphi
        # original no tiene.
        centro_int = int(centro)
        ejerci_int = int(ejerci)
        numdoc_int = int(numdoc)
        tipdoc_norm = (tipdoc or "").strip()
        serie_norm = (serie or "").strip()
        tipac = "0"
        empresa = self.settings.empresa
        self._require_artubi_tables()

        lineas_movidas: list[dict[str, Any]] = []
        try:
            rows = self.db.fetch_all(
                "SELECT * FROM DETMOV WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPDOC=? AND DMV_TIPAC=? "
                "AND DMV_EJERCI=? AND DMV_SERIE=? AND DMV_NUMDOC=? AND DMV_TIPLIN='D'",
                (empresa, centro_int, tipdoc_norm, tipac, ejerci_int, serie_norm, numdoc_int),
            )
            for row in rows:
                dmv = normalize(row)
                cantid_pedido = dec(dmv["DMV_CANTID"])
                if cantid_pedido <= 0:
                    continue
                linea = self._codigo_linea(dmv)
                if self._sum_artubi(linea, 3) != 0:
                    continue  # ya hay algo en ZONA3 para esta linea; no se reprocesa (replica fiel)

                cantid2 = self._sum_artubi(linea, 2)
                if cantid2 > 0:
                    dmv_mov = dict(dmv)
                    dmv_mov["DMV_CANTID"] = cantid2
                    self._mover_linea_pedido_auto(dmv_mov, 2, 3)
                    lineas_movidas.append({
                        "numlin": dmv["DMV_NUMLIN"], "origen": "preparacion", "cantidad": str(cantid2),
                    })
                    continue

                zon = self.db.fetch_one(
                    "SELECT ZON_CANTID FROM ARTZON WHERE ZON_NUMEMP=? AND ZON_CENTRO=? AND ZON_ZONA=1 "
                    "AND ZON_CODART=?",
                    (empresa, centro_int, dmv["DMV_CODART"]),
                )
                cantid1 = dec(zon.get("ZON_CANTID")) if zon else Decimal("0")
                if cantid1 > 0:
                    dmv_mov = dict(dmv)
                    dmv_mov["DMV_CANTID"] = min(cantid1, cantid_pedido)
                    self._mover_linea_pedido_auto(dmv_mov, 1, 3)
                    lineas_movidas.append({
                        "numlin": dmv["DMV_NUMLIN"], "origen": "almacen", "cantidad": str(dmv_mov["DMV_CANTID"]),
                    })
                else:
                    self._mover_linea_pedido_auto(dmv, 0, 3)
                    lineas_movidas.append({
                        "numlin": dmv["DMV_NUMLIN"], "origen": "sin_origen", "cantidad": str(cantid_pedido),
                    })

            cbv_row = self.db.fetch_one(
                "SELECT CBV_NUMDOC FROM CABDOCV WHERE CBV_NUMEMP=? AND CBV_CENTRO=? AND CBV_TIPDOC=? AND "
                "CBV_TIPAC=? AND CBV_EJERCI=? AND CBV_SERIE=? AND CBV_NUMDOC=?",
                (empresa, centro_int, tipdoc_norm, tipac, ejerci_int, serie_norm, numdoc_int),
            )
            marcado = False
            if cbv_row:
                self.db.execute(
                    "UPDATE CABDOCV SET CBV_INDEDI='P', CBV_FECMOD=? WHERE CBV_NUMEMP=? AND CBV_CENTRO=? AND "
                    "CBV_TIPDOC=? AND CBV_TIPAC=? AND CBV_EJERCI=? AND CBV_SERIE=? AND CBV_NUMDOC=?",
                    (datetime.now(), empresa, centro_int, tipdoc_norm, tipac, ejerci_int, serie_norm, numdoc_int),
                )
                marcado = True
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "centro": centro_int, "tipdoc": tipdoc_norm, "ejerci": ejerci_int, "serie": serie_norm,
            "numdoc": numdoc_int, "lineas_movidas": lineas_movidas, "cabecera_marcada_preparado": marcado,
        }

    def check_order_preparation_status(
        self, centro: Any, tipdoc: str, ejerci: Any, serie: str, numdoc: Any
    ) -> dict[str, Any]:
        # Replica Finalizar_Pedido: recorre las lineas de producto
        # (TIPLIN='D', CANTID>0) del documento y determina si esta
        # completamente preparado (todas tienen algo en ZONA3) o solo en
        # preparacion (alguna tiene algo en ZONA2); si alguno de los dos
        # es cierto, actualiza CBV_INDEDI/CBV_FECMOD en la cabecera.
        #
        # BUG REAL CORREGIDO (fuga de recursos, misma familia que el ya
        # corregido en Grabar_Albaran_Pedido): el Delphi original hace
        # INICIO_TRANSACCION incondicionalmente al principio, pero solo
        # llama a FIN_TRANSACCION dentro del bloque
        # "IF E_PREPARADO OR E_PREPARACION" -- si el pedido no esta ni
        # preparado ni en preparacion (caso normal de un pedido recien
        # creado que el almacen aun no ha tocado: ninguna linea tiene nada
        # en ZONA2 ni ZONA3), esa condicion es FALSA y la transaccion
        # abierta al principio NUNCA se cierra (ni commit ni rollback).
        # Aqui se hace commit/rollback siempre, se escriba o no la
        # cabecera.
        #
        # DETALLE REPLICADO LITERALMENTE (no es un bug que se corrija, es
        # una rareza real del original que se documenta): E_PREPARADO
        # empieza en True por defecto y solo se pone a False si alguna
        # linea tiene ZONA3=0. Un pedido SIN lineas de producto (o con
        # todas sus lineas a cantidad 0) nunca entra en el cuerpo del
        # bucle, asi que E_PREPARADO se queda en True y la cabecera se
        # marca como PREPARADO sin haber comprobado nada en realidad.
        centro_int = int(centro)
        ejerci_int = int(ejerci)
        numdoc_int = int(numdoc)
        tipdoc_norm = (tipdoc or "").strip()
        serie_norm = (serie or "").strip()
        tipac = "0"
        empresa = self.settings.empresa

        e_preparado = True
        e_preparacion = False
        try:
            rows = self.db.fetch_all(
                "SELECT * FROM DETMOV WHERE DMV_NUMEMP=? AND DMV_CENTRO=? AND DMV_TIPDOC=? AND DMV_TIPAC=? "
                "AND DMV_EJERCI=? AND DMV_SERIE=? AND DMV_NUMDOC=? AND DMV_TIPLIN='D'",
                (empresa, centro_int, tipdoc_norm, tipac, ejerci_int, serie_norm, numdoc_int),
            )
            for row in rows:
                dmv = normalize(row)
                if dec(dmv["DMV_CANTID"]) > 0:
                    linea = self._codigo_linea(dmv)
                    if self._sum_artubi(linea, 3) == 0:
                        e_preparado = False
                    if self._sum_artubi(linea, 2) > 0:
                        e_preparacion = True
                if (not e_preparado) and e_preparacion:
                    break

            marcado = False
            estado = None
            if e_preparado or e_preparacion:
                estado = "P" if e_preparado else "L"
                cbv_row = self.db.fetch_one(
                    "SELECT CBV_NUMDOC FROM CABDOCV WHERE CBV_NUMEMP=? AND CBV_CENTRO=? AND CBV_TIPDOC=? AND "
                    "CBV_TIPAC=? AND CBV_EJERCI=? AND CBV_SERIE=? AND CBV_NUMDOC=?",
                    (empresa, centro_int, tipdoc_norm, tipac, ejerci_int, serie_norm, numdoc_int),
                )
                if cbv_row:
                    self.db.execute(
                        "UPDATE CABDOCV SET CBV_INDEDI=?, CBV_FECMOD=? WHERE CBV_NUMEMP=? AND CBV_CENTRO=? AND "
                        "CBV_TIPDOC=? AND CBV_TIPAC=? AND CBV_EJERCI=? AND CBV_SERIE=? AND CBV_NUMDOC=?",
                        (
                            estado, datetime.now(), empresa, centro_int, tipdoc_norm, tipac, ejerci_int,
                            serie_norm, numdoc_int,
                        ),
                    )
                    marcado = True
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "centro": centro_int, "tipdoc": tipdoc_norm, "ejerci": ejerci_int, "serie": serie_norm,
            "numdoc": numdoc_int, "preparado": e_preparado, "en_preparacion": e_preparacion,
            "cabecera_marcada": marcado, "indedi": estado,
        }


    # ------------------------------------------------------------------
    # Fase 2I - utilidades y SQL interno de compatibilidad
    # ------------------------------------------------------------------
    @staticmethod
    def _single_sql_statement(cadena_sql: str) -> str:
        sql = str(cadena_sql or "").strip()
        if not sql:
            raise FaroError("La sentencia SQL no puede estar vacia.")
        if "\x00" in sql:
            raise FaroError("La sentencia SQL contiene caracteres no validos.")
        # Se tolera exclusivamente el ';' final habitual. Cualquier otro
        # separador permitiria encadenar varias sentencias.
        if sql.endswith(";"):
            sql = sql[:-1].rstrip()
        if ";" in sql:
            raise FaroError("Solo se permite una sentencia SQL por llamada.")
        if re.search(r"--|/\*|\*/", sql):
            raise FaroError("No se permiten comentarios SQL en las consultas internas de compatibilidad.")
        return sql

    @classmethod
    def _validate_internal_read_sql(cls, cadena_sql: str) -> str:
        sql = cls._single_sql_statement(cadena_sql)
        upper = re.sub(r"\s+", " ", sql.upper()).strip()
        if not (upper.startswith("SELECT ") or upper.startswith("WITH ")):
            raise FaroError("Busqueda_SQL y Abrir_Consulta solo admiten SELECT/CTE de lectura.")
        forbidden = (
            "INSERT", "UPDATE", "DELETE", "MERGE", "EXECUTE", "ALTER", "DROP", "CREATE",
            "RECREATE", "GRANT", "REVOKE", "COMMIT", "ROLLBACK", "CONNECT", "DISCONNECT",
        )
        for word in forbidden:
            if re.search(rf"\b{word}\b", upper):
                raise FaroError(f"Operacion SQL no permitida en una consulta de lectura: {word}.")
        return sql

    @classmethod
    def _validate_internal_write_sql(cls, cadena_sql: str) -> str:
        sql = cls._single_sql_statement(cadena_sql)
        upper = re.sub(r"\s+", " ", sql.upper()).strip()
        # Ejecutar_SQL se conserva por compatibilidad, pero no se usa para
        # control transaccional ni DDL. Esas operaciones deben vivir en
        # herramientas tipadas del MCP.
        allowed_starts = ("INSERT ", "UPDATE ", "DELETE ", "MERGE ", "EXECUTE PROCEDURE ")
        if not upper.startswith(allowed_starts):
            raise FaroError(
                "Ejecutar_SQL solo admite INSERT/UPDATE/DELETE/MERGE/EXECUTE PROCEDURE; "
                "DDL y control de transacciones no estan permitidos."
            )
        return sql

    def initialize_connection(self) -> dict[str, Any]:
        """Migra InicializaConexion al modelo por llamada de MCP.

        El servidor anterior dejaba una transaccion abierta en la sesion. MCP crea
        una conexion por invocacion, por lo que dejarla abierta no tendria
        utilidad ni seria seguro. Se valida la conexion/transaccion con una
        lectura minima y se devuelve el mismo resultado logico True.
        """
        row = self.db.fetch_one("SELECT 1 AS OK FROM RDB$DATABASE")
        if not row:
            raise FaroError("No se pudo inicializar/verificar la conexion con Faro.")
        return {"initialized": True, "ok": True, "datasnap_value": True}

    @staticmethod
    def echo_string(value: str) -> dict[str, Any]:
        value = str(value or "")
        return {"value": value, "datasnap_text": value}

    @staticmethod
    def reverse_string(value: str) -> dict[str, Any]:
        value = str(value or "")
        reversed_value = value[::-1]
        return {"value": reversed_value, "datasnap_text": reversed_value}

    def internal_search_sql(self, cadena_sql: str, campo: str) -> dict[str, Any]:
        """Migra Busqueda_SQL limitandola a SELECT de una unica sentencia."""
        sql = self._validate_internal_read_sql(cadena_sql)
        field = str(campo or "").strip().upper()
        if not field:
            raise FaroError("CAMPO no puede estar vacio.")
        columns, rows = self._query_internal_rows(sql, 1)
        if field not in columns:
            raise FaroError(f"Campo inexistente en el resultado SQL: {campo}")
        value = "" if not rows else serialize_text_value(rows[0].get(field))
        return {"campo": field, "value": normalize(value), "datasnap_text": clean_text_value(value)}

    def internal_open_query(self, cadena_sql: str) -> dict[str, Any]:
        """Migra Abrir_Consulta con serializacion |/# y limite configurable."""
        sql = self._validate_internal_read_sql(cadena_sql)
        columns, rows = self._query_internal_rows(sql, int(self.settings.sql_max_rows))
        normalized = [normalize(row) for row in rows]
        parts: list[str] = []
        for row in rows:
            parts.append("|".join(clean_text_value(row.get(column)) for column in columns) + "|")
        compatibility_text = "#".join(parts) + ("#" if parts else "")
        return {
            "count": len(normalized),
            "columns": columns,
            "items": normalized,
            "max_rows": int(self.settings.sql_max_rows),
            "truncated_possible": len(normalized) >= int(self.settings.sql_max_rows),
            "datasnap_text": compatibility_text,
        }

    def _query_internal_rows(self, sql: str, limit: int) -> tuple[list[str], list[dict[str, Any]]]:
        if hasattr(self.db, "query_rows"):
            columns, rows = self.db.query_rows(sql, (), limit)
            return [str(c).upper() for c in columns], [normalize(r) for r in rows]
        # Compatibilidad con dobles de prueba / adaptadores existentes.
        rows = self.db.fetch_all(sql, ())[: max(1, int(limit))]
        rows = [normalize(r) for r in rows]
        columns = [str(c).upper() for c in rows[0].keys()] if rows else []
        return columns, rows

    def internal_execute_sql(self, cadena_sql: str) -> dict[str, Any]:
        """Migra Ejecutar_SQL, protegido por una opcion explicita de servidor."""
        if not bool(self.settings.allow_internal_sql_write):
            raise FaroError(
                "Ejecutar_SQL esta deshabilitado por seguridad. Para diagnostico interno, habilita "
                "FARO_ALLOW_INTERNAL_SQL_WRITE=true en el servidor."
            )
        sql = self._validate_internal_write_sql(cadena_sql)
        try:
            self.db.execute(sql)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        # EJECUTA_SQL devuelve MSGERR vacio cuando CODERR=0.
        return {"ok": True, "message": "", "datasnap_text": ""}

    @staticmethod
    def _safe_identifier(name: str) -> str:
        normalized = str(name or "").strip().upper()
        if not normalized.replace("_", "").isalnum():
            raise FaroError(f"Identificador no valido: {name!r}")
        return normalized

    def _ordered_table_columns(self, table: str) -> tuple[str, ...]:
        table = self._safe_identifier(table)
        rows = self.db.fetch_all(
            """
            SELECT TRIM(RDB$FIELD_NAME) AS FIELD_NAME
            FROM RDB$RELATION_FIELDS
            WHERE RDB$RELATION_NAME = ?
            ORDER BY RDB$FIELD_POSITION
            """,
            (table,),
        )
        if not rows:
            raise FaroError(f"No se encontraron columnas para la tabla {table}.")
        return tuple(self._safe_identifier(str(row["FIELD_NAME"])) for row in rows)

    def _company_row_count(self, table: str, company_column: str, empresa: int) -> int:
        table = self._safe_identifier(table)
        company_column = self._safe_identifier(company_column)
        row = self.db.fetch_one(
            f"SELECT COUNT(*) AS N FROM {table} WHERE {company_column}=?",
            (int(empresa),),
        )
        return int(row["N"] if row else 0)

    def _copy_company_table(
        self,
        table: str,
        company_column: str,
        source: int,
        target: int,
        overrides: dict[str, Any],
        batch_size: int = 500,
    ) -> int:
        table = self._safe_identifier(table)
        company_column = self._safe_identifier(company_column)
        columns = self._ordered_table_columns(table)
        placeholders = ", ".join("?" for _ in columns)
        insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
        read_cur = self.db.conn.cursor()
        write_cur = self.db.conn.cursor()
        inserted = 0
        try:
            read_cur.execute(
                f"SELECT {', '.join(columns)} FROM {table} WHERE {company_column}=?",
                (int(source),),
            )
            rows = read_cur.fetchmany(max(1, int(batch_size)))
            while rows:
                params_batch = []
                for row in rows:
                    data = {columns[i]: row[i] for i in range(len(columns))}
                    data[company_column] = int(target)
                    data.update(overrides)
                    params_batch.append(tuple(data[column] for column in columns))
                write_cur.executemany(insert_sql, params_batch)
                inserted += len(params_batch)
                rows = read_cur.fetchmany(max(1, int(batch_size)))
        finally:
            write_cur.close()
            read_cur.close()
        return inserted

    def replicate_company_from_template(self, empresa_destino: int, nombre: str, direccion: str) -> dict[str, Any]:
        """Replica configuracion y auxiliares desde la empresa 1 hacia una empresa nueva."""
        target = int(empresa_destino)
        source = COMPANY_REPLICATION_SOURCE
        name = str(nombre or "").strip()
        address = str(direccion or "").strip()
        if target <= 0:
            raise FaroError("empresa_destino debe ser mayor que cero.")
        if target == source:
            raise FaroError("La empresa destino debe ser distinta de la empresa 1.")
        if not name:
            raise FaroError("nombre no puede estar vacio.")
        if not address:
            raise FaroError("direccion no puede estar vacia.")

        plan = []
        blocked = []
        for table, company_column in COMPANY_REPLICATION_TABLES:
            source_rows = self._company_row_count(table, company_column, source)
            target_rows = self._company_row_count(table, company_column, target)
            item = {
                "tabla": table,
                "campo_empresa": company_column,
                "filas_origen": source_rows,
                "filas_destino": target_rows,
            }
            plan.append(item)
            if target_rows:
                blocked.append(item)
        if blocked:
            raise FaroError(
                "La empresa destino ya tiene datos en tablas seleccionadas: "
                + ", ".join(f"{item['tabla']}={item['filas_destino']}" for item in blocked)
            )

        inserted_total = 0
        inserted_by_table: list[dict[str, Any]] = []
        overrides_by_table = {
            "EMPRES": {"EMP_NOMEMP": name, "EMP_NOMFIS": name, "EMP_DOMFIS1": address},
            "CENTROS": {"CEN_NOMCEN": name, "CEN_DOMIC1": address},
        }
        try:
            for table, company_column in COMPANY_REPLICATION_TABLES:
                inserted = self._copy_company_table(
                    table,
                    company_column,
                    source,
                    target,
                    overrides_by_table.get(table, {}),
                )
                inserted_total += inserted
                inserted_by_table.append({"tabla": table, "filas_insertadas": inserted})
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return {
            "ok": True,
            "empresa_origen": source,
            "empresa_destino": target,
            "nombre": name,
            "direccion": address,
            "tablas_replicadas": len(COMPANY_REPLICATION_TABLES),
            "filas_insertadas": inserted_total,
            "detalle": inserted_by_table,
        }


def normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def pick(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: normalize(row.get(key)) for key in keys}


def same_value(before: Any, after: Any) -> bool:
    if before is None or after is None:
        return before is after
    try:
        return dec(before) == dec(after)
    except Exception:
        return str(before) == str(after)


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key in before:
        if not same_value(before.get(key), after.get(key)):
            result[key] = {"before": normalize(before.get(key)), "after": normalize(after.get(key))}
    return result


def _all_centers(value: Any) -> bool:
    return isinstance(value, str) and value.strip() == ""


def _center_filter_is_set(value: Any) -> bool:
    return value is not None and not _all_centers(value)


# Fase 11: el contrato MCP usa exclusivamente nombres canonicos.
# No existen aliases publicos ni filtros de nombres heredados.

# Limpieza Fase 10: contrato publico congelado por perfiles de dominio.
#
# - core: operaciones habituales que un agente ERP puede necesitar cada dia.
# - admin: core + mantenimiento/operaciones avanzadas del ERP.
# - integrations: core + conectores especificos de instalaciones externas.
# - all: composicion de todos los perfiles; ``full`` se acepta solo como alias
#   de compatibilidad y se normaliza a ``all``.
CORE_PUBLIC_TOOL_NAMES = frozenset({
    # Articulos / compras / precios.
    "articulo_buscar",
    "articulo_obtener",
    "articulo_compra_consultar",
    "articulo_catalogo_listar",
    "articulo_precio_cliente",
    "articulo_precio_coste",
    "articulo_cambiar_tabla_precio",
    "articulo_familia_guardar",
    "articulo_familiancc_tabla_guardar",
    "tarifa_proveedor_actualizar",
    "proveedor_buscar",
    # Clientes / CRM.
    "cliente_buscar",
    "cliente_actualizar",
    "cliente_ultimas_ventas",
    "actividad_grabar",
    "actividad_listar",
    "actividad_tipo_listar",
    # Stock / almacen.
    "stock_consultar",
    "stock_regularizar",
    "stock_trasvasar",
    "entrada_almacen_crear",
    "etiqueta_gestion",
    "recuento_gestion",
    "falta_gestion",
    # Pedidos.
    "pedido_crear",
    "pedido_cerrar",
    "pedido_albaranar",
    "pedido_listar",
    "pedido_detalle",
    "pedido_linea_mover",
    "pedido_marcar_preparado",
    "pedido_finalizar",
    "pedido_pdf_gestion",
    "pedido_enviar",
    # Ofertas.
    "oferta_crear",
    # Compras.
    "orden_compra_cerrar",
    "orden_compra_propuesta_pedidos_cliente",
    "orden_compra_propuesta_stock_minimo",
    # Ventas / mostrador.
    "mostrador_venta_gestion",
    "mostrador_cobrar",
    "negocio_clientes_riesgo",
    "negocio_cuadro_mando",
    "negocio_diagnostico_cambios",
    "negocio_stock_rotacion",
    "negocio_stock_tendencias",
    "negocio_tendencias",
    "clientes_acciones_recomendadas",
    "dashboard_acciones_recomendadas",
    "dashboard_alertas",
    "dashboard_filtros",
    "dashboard_resumen",
    "dashboard_series_temporales",
    "clientes_resumen",
    "compras_articulos_pendientes_recibir",
    "compras_documentos_pendientes_resumen",
    "compras_pedidos_pendientes_resumen",
    "compras_resumen",
    "cartera_efectos_detalle",
    "cartera_efectos_pendientes_resumen",
    "cartera_efectos_por_cliente",
    "cartera_pendiente_remesar",
    "cartera_remesas_resumen",
    "cartera_riesgo_cliente",
    "cartera_riesgo_clientes_resumen",
    "documentos_pendientes_resumen",
    "pedidos_acciones_recomendadas",
    "pedidos_resumen",
    "proveedores_resumen",
    "stock_acciones_recomendadas",
    "stock_resumen",
    "tesoreria_acciones_recomendadas",
    "tesoreria_resumen",
    "ventas_acciones_recomendadas",
    "ventas_resumen",
    "venta_documento_crear",
    "venta_alertas_rentabilidad",
    "venta_documentos_abc",
    "venta_documentos_detalle",
    "venta_documentos_resumen",
    "venta_rentabilidad_lineas",
    "venta_rentabilidad_resumen",
})

ADMIN_PUBLIC_TOOL_NAMES = frozenset({
    "precio_tabla_listar",
    "articulo_ubicacion_guardar",
    "articulo_ean_grabar",
    "articulo_precio_oferta",
    "cliente_tipo_venta",
    "empresa_replicar",
    "entrada_pedidos_relacionados",
    "pedido_situacion_actualizar",
    "pedido_retirada_actualizar",
})

INTEGRATION_PUBLIC_TOOL_NAMES = frozenset({
    "integracion_coinfer_stock",
})

ALL_PUBLIC_TOOL_NAMES = frozenset(
    CORE_PUBLIC_TOOL_NAMES | ADMIN_PUBLIC_TOOL_NAMES | INTEGRATION_PUBLIC_TOOL_NAMES
)

CENTER_SCOPED_TOOL_NAMES = frozenset(
    name for name in ALL_PUBLIC_TOOL_NAMES
    if name.startswith((
        "stock_",
        "venta_",
        "ventas_",
        "compras_",
        "dashboard_",
        "negocio_",
        "orden_compra_",
    ))
    or name in {
        "articulo_buscar",
        "articulo_ubicacion_guardar",
        "entrada_almacen_crear",
        "entrada_pedidos_relacionados",
        "etiqueta_gestion",
        "falta_gestion",
        "integracion_coinfer_stock",
        "mostrador_cobrar",
        "mostrador_venta_gestion",
        "proveedores_resumen",
        "recuento_gestion",
    }
)

def public_tool_profile(value: str | None = None) -> str:
    """Normaliza el perfil publico de herramientas.

    ``full`` se mantiene como alias de compatibilidad de ``all``. Cualquier
    valor desconocido cae en ``core`` para aplicar siempre la superficie mas
    conservadora.
    """
    raw = value if value is not None else os.getenv("FARO_MCP_TOOL_PROFILE", "core")
    profile = str(raw or "core").strip().lower()
    if profile == "full":
        return "all"
    return profile if profile in {"core", "admin", "integrations", "all"} else "core"


def public_tool_names_for_profile(value: str | None = None) -> frozenset[str]:
    """Devuelve el contrato exacto de nombres publicos para un perfil."""
    profile = public_tool_profile(value)
    if profile == "admin":
        return frozenset(CORE_PUBLIC_TOOL_NAMES | ADMIN_PUBLIC_TOOL_NAMES)
    if profile == "integrations":
        return frozenset(CORE_PUBLIC_TOOL_NAMES | INTEGRATION_PUBLIC_TOOL_NAMES)
    if profile == "all":
        return ALL_PUBLIC_TOOL_NAMES
    return CORE_PUBLIC_TOOL_NAMES


# ---------------------------------------------------------------------------
# Seguridad y auditoria (Fase 13)
#
# El perfil funcional (core/admin/integrations/all) decide que herramientas
# existen. El nivel de acceso decide cuales pueden ejecutarse. Se mantiene el
# catalogo estable para no romper el contrato MCP: una herramienta puede estar
# visible y, aun asi, quedar bloqueada en tools/call por permisos.
ACCESS_LEVEL_ORDER = {"read": 0, "write": 1, "critical": 2}

READ_ONLY_TOOL_NAMES = frozenset({
    "actividad_listar",
    "actividad_tipo_listar",
    "articulo_buscar",
    "articulo_catalogo_listar",
    "articulo_compra_consultar",
    "articulo_obtener",
    "articulo_precio_cliente",
    "articulo_precio_coste",
    "articulo_precio_oferta",
    "cliente_buscar",
    "cliente_tipo_venta",
    "cliente_ultimas_ventas",
    "entrada_pedidos_relacionados",
    "integracion_coinfer_stock",
    "pedido_detalle",
    "pedido_listar",
    "precio_tabla_listar",
    "proveedor_buscar",
    "stock_consultar",
    "orden_compra_propuesta_pedidos_cliente",
    "orden_compra_propuesta_stock_minimo",
    "negocio_clientes_riesgo",
    "negocio_cuadro_mando",
    "negocio_diagnostico_cambios",
    "negocio_stock_rotacion",
    "negocio_stock_tendencias",
    "negocio_tendencias",
    "clientes_acciones_recomendadas",
    "dashboard_acciones_recomendadas",
    "dashboard_alertas",
    "dashboard_filtros",
    "dashboard_resumen",
    "dashboard_series_temporales",
    "clientes_resumen",
    "compras_articulos_pendientes_recibir",
    "compras_documentos_pendientes_resumen",
    "compras_pedidos_pendientes_resumen",
    "compras_resumen",
    "cartera_efectos_detalle",
    "cartera_efectos_pendientes_resumen",
    "cartera_efectos_por_cliente",
    "cartera_pendiente_remesar",
    "cartera_remesas_resumen",
    "cartera_riesgo_cliente",
    "cartera_riesgo_clientes_resumen",
    "documentos_pendientes_resumen",
    "pedidos_acciones_recomendadas",
    "pedidos_resumen",
    "proveedores_resumen",
    "stock_acciones_recomendadas",
    "stock_resumen",
    "tesoreria_acciones_recomendadas",
    "tesoreria_resumen",
    "ventas_acciones_recomendadas",
    "ventas_resumen",
    "venta_alertas_rentabilidad",
    "venta_documentos_abc",
    "venta_documentos_detalle",
    "venta_documentos_resumen",
    "venta_rentabilidad_lineas",
    "venta_rentabilidad_resumen",
})

WRITE_TOOL_NAMES = frozenset({
    "actividad_grabar",
    "articulo_ean_grabar",
    "articulo_familia_guardar",
    "articulo_familiancc_tabla_guardar",
    "articulo_ubicacion_guardar",
    "cliente_actualizar",
    "etiqueta_gestion",
    "falta_gestion",
    "oferta_crear",
    "pedido_crear",
    "pedido_linea_mover",
    "pedido_marcar_preparado",
    "pedido_pdf_gestion",
    "pedido_retirada_actualizar",
    "pedido_situacion_actualizar",
    "recuento_gestion",
})

CRITICAL_TOOL_NAMES = frozenset({
    "articulo_cambiar_tabla_precio",
    "tarifa_proveedor_actualizar",
    "empresa_replicar",
    "mostrador_cobrar",
    "mostrador_venta_gestion",
    "orden_compra_cerrar",
    "pedido_albaranar",
    "pedido_cerrar",
    "entrada_almacen_crear",
    "pedido_enviar",
    "pedido_finalizar",
    "stock_regularizar",
    "stock_trasvasar",
    "venta_documento_crear",
})

if (READ_ONLY_TOOL_NAMES | WRITE_TOOL_NAMES | CRITICAL_TOOL_NAMES) != ALL_PUBLIC_TOOL_NAMES:
    missing = ALL_PUBLIC_TOOL_NAMES.difference(READ_ONLY_TOOL_NAMES | WRITE_TOOL_NAMES | CRITICAL_TOOL_NAMES)
    extra = (READ_ONLY_TOOL_NAMES | WRITE_TOOL_NAMES | CRITICAL_TOOL_NAMES).difference(ALL_PUBLIC_TOOL_NAMES)
    raise RuntimeError(f"Clasificacion de seguridad incompleta. missing={sorted(missing)} extra={sorted(extra)}")
if (READ_ONLY_TOOL_NAMES & WRITE_TOOL_NAMES) or (READ_ONLY_TOOL_NAMES & CRITICAL_TOOL_NAMES) or (WRITE_TOOL_NAMES & CRITICAL_TOOL_NAMES):
    raise RuntimeError("Las categorias de seguridad de herramientas deben ser disjuntas")


def public_access_level(value: str | None = None) -> str:
    """Normaliza el nivel de acceso MCP. Por defecto permite operaciones critical.

    Un valor configurado pero desconocido sigue cayendo a ``read`` para evitar
    elevar permisos por un error tipografico de configuracion.
    """
    raw = value if value is not None else os.getenv("FARO_MCP_ACCESS_LEVEL", "critical")
    level = str(raw or "critical").strip().lower()
    aliases = {"readonly": "read", "read_only": "read", "rw": "write", "admin": "critical", "full": "critical"}
    level = aliases.get(level, level)
    return level if level in ACCESS_LEVEL_ORDER else "read"


def effective_tool_risk(tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    """Devuelve el riesgo efectivo de una invocacion concreta.

    Algunas fachadas mezclan lectura y escritura. En esos casos se baja el
    riesgo solo cuando la accion solicitada es inequívocamente de lectura.
    Ante argumentos ausentes/desconocidos se aplica el riesgo maximo de la
    herramienta (fail closed).
    """
    args = arguments if isinstance(arguments, dict) else {}
    if tool_name in READ_ONLY_TOOL_NAMES:
        return "read"

    if tool_name in {"etiqueta_gestion", "recuento_gestion", "falta_gestion"}:
        return "read" if str(args.get("accion", "")).lower() == "listar" else "write"
    if tool_name == "pedido_pdf_gestion":
        return "read" if str(args.get("accion", "")).lower() == "obtener" else "write"
    if tool_name == "articulo_cambiar_tabla_precio":
        # La simulacion es lectura. Si simular falta se respeta el default
        # publico true; solo simular=false autoriza una mutacion real.
        return "read" if ("simular" not in args or args.get("simular") is True) else "critical"
    if tool_name == "mostrador_venta_gestion":
        action = str(args.get("accion", "")).lower()
        if action in {"guardar", "cargar_pedido"}:
            return "write"
        return "critical"  # borrar o accion desconocida: fail closed.

    if tool_name in CRITICAL_TOOL_NAMES:
        return "critical"
    return "write"


def access_allows(access_level: str, risk: str) -> bool:
    return ACCESS_LEVEL_ORDER[public_access_level(access_level)] >= ACCESS_LEVEL_ORDER[risk]


class FaroPermissionError(FaroError):
    pass


class FaroAuditError(FaroError):
    pass


@dataclass(frozen=True)
class SecuritySettings:
    access_level: str
    tool_profile: str
    actor: str
    client_id: str
    audit_log: str
    audit_reads: bool
    audit_required: bool
    empresa: int
    centro: int

    @classmethod
    def from_env(cls) -> "SecuritySettings":
        main_dir = os.getenv("FARO_MAIN_DIR", r"C:\FaroERP")
        default_log = str(Path(main_dir) / "logs" / "faro_mcp_audit.jsonl")
        return cls(
            access_level=public_access_level(),
            tool_profile=public_tool_profile(),
            actor=(os.getenv("FARO_MCP_ACTOR") or os.getenv("FARO_USUARIO") or "mcp").strip(),
            client_id=os.getenv("FARO_MCP_CLIENT_ID", "").strip(),
            audit_log=os.getenv("FARO_MCP_AUDIT_LOG", default_log).strip(),
            audit_reads=os.getenv("FARO_MCP_AUDIT_READS", "false").lower() in {"1", "true", "yes", "si"},
            audit_required=os.getenv("FARO_MCP_AUDIT_REQUIRED", "true").lower() in {"1", "true", "yes", "si"},
            empresa=int(os.getenv("FARO_EMPRESA", str(DEFAULT_EMPRESA))),
            centro=int(os.getenv("FARO_CENTRO", "0")),
        )


_SENSITIVE_AUDIT_KEYS = frozenset({
    "contrasena", "password", "smtp_password", "token", "secret", "authorization", "autorizacion"
})


def _sanitize_audit_value(value: Any, key: str = "", depth: int = 0) -> Any:
    if key.lower() in _SENSITIVE_AUDIT_KEYS:
        return "***REDACTED***"
    if depth >= 4:
        return "<max-depth>"
    if isinstance(value, dict):
        return {str(k): _sanitize_audit_value(v, str(k), depth + 1) for k, v in list(value.items())[:50]}
    if isinstance(value, list):
        items = [_sanitize_audit_value(v, key, depth + 1) for v in value[:20]]
        if len(value) > 20:
            items.append(f"<+{len(value) - 20} items>")
        return items
    if isinstance(value, str):
        return value if len(value) <= 256 else value[:256] + "..."
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:256]


_AUDIT_RESULT_KEYS = frozenset({
    "accion", "articulo", "codart", "centro", "cliente", "codcli", "codigo_pedido",
    "documento", "ejercicio", "ejerci", "factura", "numero", "numdoc", "pedido",
    "serie", "ticket", "tipo", "tipdoc", "tipo_oferta", "venta", "albaran", "diferencia", "lineas",
})


def _audit_result_summary(value: Any) -> dict[str, Any]:
    """Extrae solo identificadores operativos; nunca copia el resultado completo."""
    if not isinstance(value, dict):
        return {}
    summary: dict[str, Any] = {}
    for key, item in value.items():
        if str(key).lower() in _AUDIT_RESULT_KEYS and not isinstance(item, (dict, list)):
            summary[str(key)] = _sanitize_audit_value(item, str(key))
    return summary


class AuditLogger:
    """Auditoria JSONL append-only a nivel de aplicacion.

    Se registra el intento antes de una mutacion para que un fallo del sink de
    auditoria bloquee la operacion si FARO_MCP_AUDIT_REQUIRED=true. Despues
    se registra el resultado. No se incluyen resultados de negocio completos
    para evitar duplicar datos personales en el log.
    """

    def __init__(self, settings: SecuritySettings):
        self.settings = settings

    def _append(self, event: dict[str, Any]) -> None:
        if not self.settings.audit_log:
            if self.settings.audit_required:
                raise FaroAuditError("FARO_MCP_AUDIT_LOG no esta configurado")
            return
        path = Path(self.settings.audit_log)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
                fh.flush()
        except OSError as exc:
            if self.settings.audit_required:
                raise FaroAuditError(f"No se puede escribir el log de auditoria: {path}: {exc}") from exc
            print(f"[faro-mcp] AUDIT WARNING: {exc}", file=sys.stderr)

    def record(
        self,
        *,
        request_id: str,
        tool: str,
        risk: str,
        status: str,
        arguments: dict[str, Any] | None = None,
        error_code: str = "",
        error_message: str = "",
        duration_ms: float | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> None:
        empresa = self.settings.empresa
        if isinstance(arguments, dict) and "empresa" in arguments:
            try:
                empresa = int(arguments["empresa"])
            except (TypeError, ValueError):
                empresa = self.settings.empresa
        event = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "event_id": uuid.uuid4().hex,
            "request_id": request_id,
            "actor": self.settings.actor,
            "client_id": self.settings.client_id,
            "empresa": empresa,
            "centro": self.settings.centro,
            "tool": tool,
            "risk": risk,
            "access_level": self.settings.access_level,
            "tool_profile": self.settings.tool_profile,
            "server_version": SERVER_VERSION,
            "contract_version": PUBLIC_CONTRACT_VERSION,
            "status": status,
        }
        if arguments is not None:
            event["arguments"] = _sanitize_audit_value(arguments)
            if isinstance(arguments, dict) and arguments.get("usuario"):
                event["business_user"] = _sanitize_audit_value(arguments.get("usuario"), "usuario")
        if error_code:
            event["error_code"] = error_code
        if error_message:
            event["error_message"] = str(error_message)[:512]
        if duration_ms is not None:
            event["duration_ms"] = round(float(duration_ms), 3)
        if result_summary:
            event["result"] = _sanitize_audit_value(result_summary)
        self._append(event)


class FaroToolRuntime:
    def __init__(self):
        self.tool_profile = public_tool_profile()
        self.security = SecuritySettings.from_env()
        self.audit = AuditLogger(self.security)
        all_tools: dict[str, Callable[[dict[str, Any]], Any]] = {
            'actividad_grabar': self.tool_actividad_grabar,
            'actividad_listar': self.tool_actividad_listar,
            'actividad_tipo_listar': self.tool_actividad_tipo_listar,
            'articulo_buscar': self.tool_articulo_buscar,
            'articulo_cambiar_tabla_precio': self.tool_articulo_cambiar_tabla_precio,
            'articulo_catalogo_listar': self.tool_articulo_catalogo_listar,
            'articulo_compra_consultar': self.tool_articulo_compra_consultar,
            'articulo_ean_grabar': self.tool_articulo_ean_grabar,
            'articulo_familia_guardar': self.tool_articulo_familia_guardar,
            'articulo_familiancc_tabla_guardar': self.tool_articulo_familiancc_tabla_guardar,
            'articulo_obtener': self.tool_articulo_obtener,
            'articulo_precio_cliente': self.tool_articulo_precio_cliente,
            'articulo_precio_coste': self.tool_articulo_precio_coste,
            'articulo_precio_oferta': self.tool_articulo_precio_oferta,
            'articulo_ubicacion_guardar': self.tool_articulo_ubicacion_guardar,
            'tarifa_proveedor_actualizar': self.tool_tarifa_proveedor_actualizar,
            'cliente_actualizar': self.tool_cliente_actualizar,
            'cliente_buscar': self.tool_cliente_buscar,
            'cliente_tipo_venta': self.tool_cliente_tipo_venta,
            'cliente_ultimas_ventas': self.tool_cliente_ultimas_ventas,
            'clientes_acciones_recomendadas': self.tool_clientes_acciones_recomendadas,
            'clientes_resumen': self.tool_clientes_resumen,
            'compras_articulos_pendientes_recibir': self.tool_compras_articulos_pendientes_recibir,
            'compras_documentos_pendientes_resumen': self.tool_compras_documentos_pendientes_resumen,
            'compras_pedidos_pendientes_resumen': self.tool_compras_pedidos_pendientes_resumen,
            'control_horario_fichar': self.tool_control_horario_fichar,
            'compras_resumen': self.tool_compras_resumen,
            'cartera_efectos_detalle': self.tool_cartera_efectos_detalle,
            'cartera_efectos_pendientes_resumen': self.tool_cartera_efectos_pendientes_resumen,
            'cartera_efectos_por_cliente': self.tool_cartera_efectos_por_cliente,
            'cartera_pendiente_remesar': self.tool_cartera_pendiente_remesar,
            'cartera_remesas_resumen': self.tool_cartera_remesas_resumen,
            'cartera_riesgo_cliente': self.tool_cartera_riesgo_cliente,
            'cartera_riesgo_clientes_resumen': self.tool_cartera_riesgo_clientes_resumen,
            'dashboard_acciones_recomendadas': self.tool_dashboard_acciones_recomendadas,
            'dashboard_alertas': self.tool_dashboard_alertas,
            'dashboard_filtros': self.tool_dashboard_filtros,
            'dashboard_resumen': self.tool_dashboard_resumen,
            'dashboard_series_temporales': self.tool_dashboard_series_temporales,
            'documentos_pendientes_resumen': self.tool_documentos_pendientes_resumen,
            'empresa_replicar': self.tool_empresa_replicar,
            'entrada_almacen_crear': self.tool_entrada_almacen_crear,
            'entrada_pedidos_relacionados': self.tool_entrada_pedidos_relacionados,
            'etiqueta_gestion': self.tool_etiqueta_gestion,
            'falta_gestion': self.tool_falta_gestion,
            'integracion_coinfer_stock': self.tool_integracion_coinfer_stock,
            'mostrador_cobrar': self.tool_mostrador_cobrar,
            'mostrador_venta_gestion': self.tool_mostrador_venta_gestion,
            'negocio_clientes_riesgo': self.tool_negocio_clientes_riesgo,
            'negocio_cuadro_mando': self.tool_negocio_cuadro_mando,
            'negocio_diagnostico_cambios': self.tool_negocio_diagnostico_cambios,
            'negocio_stock_rotacion': self.tool_negocio_stock_rotacion,
            'negocio_stock_tendencias': self.tool_negocio_stock_tendencias,
            'negocio_tendencias': self.tool_negocio_tendencias,
            'oferta_crear': self.tool_oferta_crear,
            'orden_compra_cerrar': self.tool_orden_compra_cerrar,
            'orden_compra_propuesta_pedidos_cliente': self.tool_orden_compra_propuesta_pedidos_cliente,
            'orden_compra_propuesta_stock_minimo': self.tool_orden_compra_propuesta_stock_minimo,
            'pedido_albaranar': self.tool_pedido_albaranar,
            'pedido_cerrar': self.tool_pedido_cerrar,
            'pedido_crear': self.tool_pedido_crear,
            'pedido_detalle': self.tool_pedido_detalle,
            'pedido_enviar': self.tool_pedido_enviar,
            'pedido_finalizar': self.tool_pedido_finalizar,
            'pedido_linea_mover': self.tool_pedido_linea_mover,
            'pedido_listar': self.tool_pedido_listar,
            'pedido_marcar_preparado': self.tool_pedido_marcar_preparado,
            'pedido_pdf_gestion': self.tool_pedido_pdf_gestion,
            'pedidos_acciones_recomendadas': self.tool_pedidos_acciones_recomendadas,
            'pedidos_resumen': self.tool_pedidos_resumen,
            'pedido_retirada_actualizar': self.tool_pedido_retirada_actualizar,
            'pedido_situacion_actualizar': self.tool_pedido_situacion_actualizar,
            'precio_tabla_listar': self.tool_precio_tabla_listar,
            'proveedores_resumen': self.tool_proveedores_resumen,
            'proveedor_buscar': self.tool_proveedor_buscar,
            'recuento_gestion': self.tool_recuento_gestion,
            'stock_consultar': self.tool_stock_consultar,
            'stock_regularizar': self.tool_stock_regularizar,
            'stock_acciones_recomendadas': self.tool_stock_acciones_recomendadas,
            'stock_resumen': self.tool_stock_resumen,
            'stock_trasvasar': self.tool_stock_trasvasar,
            'tesoreria_acciones_recomendadas': self.tool_tesoreria_acciones_recomendadas,
            'tesoreria_resumen': self.tool_tesoreria_resumen,
            'venta_documento_crear': self.tool_venta_documento_crear,
            'venta_alertas_rentabilidad': self.tool_venta_alertas_rentabilidad,
            'venta_documentos_abc': self.tool_venta_documentos_abc,
            'venta_documentos_detalle': self.tool_venta_documentos_detalle,
            'venta_documentos_resumen': self.tool_venta_documentos_resumen,
            'venta_rentabilidad_lineas': self.tool_venta_rentabilidad_lineas,
            'venta_rentabilidad_resumen': self.tool_venta_rentabilidad_resumen,
            'ventas_acciones_recomendadas': self.tool_ventas_acciones_recomendadas,
            'ventas_resumen': self.tool_ventas_resumen,
        }
        expected_names = public_tool_names_for_profile(self.tool_profile)
        missing = expected_names.difference(all_tools)
        if missing:
            raise FaroError(
                "Contrato MCP incompleto; faltan handlers: " + ", ".join(sorted(missing))
            )
        self.tools = {name: all_tools[name] for name in sorted(expected_names)}

    def _settings_for_call(self) -> Settings:
        settings = Settings.from_env()
        empresa = _CURRENT_EMPRESA.get()
        if empresa is not None:
            settings.empresa = empresa
        return settings

    @contextmanager
    def _empresa_context(self, empresa: Any):
        try:
            value = int(empresa)
        except (TypeError, ValueError) as exc:
            raise FaroError("empresa debe ser entero") from exc
        token = _CURRENT_EMPRESA.set(value)
        try:
            yield
        finally:
            _CURRENT_EMPRESA.reset(token)

    def service(self) -> FaroArticleService:
        db = FaroDb(self._settings_for_call())
        return FaroArticleService(db)

    def phase1_service(self) -> FaroPhase1Service:
        db = FaroDb(self._settings_for_call())
        return FaroPhase1Service(db)

    # ------------------------------------------------------------------
    # Limpieza Fase 9: Mostrador / ventas abiertas
    # ------------------------------------------------------------------
    def tool_mostrador_venta_gestion(self, args: dict[str, Any]) -> Any:
        """Gestiona el ciclo previo al cobro de una venta abierta de mostrador.

        Mantiene ``mostrador_cobrar`` como operacion separada para que la IA
        no mezcle por accidente mantenimiento de VENCAJ/VENCUR con la emision
        fiscal y el registro de cobros.
        """
        accion = str(args.get("accion", "")).strip().lower()
        if accion == "guardar":
            obligatorios = ("codcli", "subcli", "texto", "tipdoc", "usuario")
            faltan = [name for name in obligatorios if name not in args]
            if faltan:
                raise FaroError("Faltan parametros para guardar: " + ", ".join(faltan))
            return self._tool_mostrador_venta_guardar(args)
        if accion == "borrar":
            venta = str(args.get("venta", "")).strip()
            if not venta:
                raise FaroError("venta es obligatorio para borrar")
            return self._tool_mostrador_venta_borrar({"venta": venta})
        if accion == "cargar_pedido":
            obligatorios = ("centro", "codigo_pedido", "tipdoc", "texto")
            faltan = [name for name in obligatorios if name not in args]
            if faltan:
                raise FaroError("Faltan parametros para cargar_pedido: " + ", ".join(faltan))
            return self._tool_mostrador_pedido_cargar(args)
        raise FaroError("accion debe ser guardar, borrar o cargar_pedido")

    # ------------------------------------------------------------------
    # Limpieza Fase 2: fachadas de dominio consolidadas
    # ------------------------------------------------------------------
    def tool_articulo_obtener(self, args: dict[str, Any]) -> Any:
        """Obtiene la ficha base del articulo y, opcionalmente, recursos pesados.

        ``incluir`` evita multiplicar herramientas publicas sin convertir la
        consulta habitual en una operacion costosa. Actualmente admite
        ``tecnica`` e ``imagen``.
        """
        identificador = str(args.get("identificador", "")).strip()
        if not identificador:
            raise FaroError("identificador es obligatorio")
        incluir_raw = args.get("incluir", [])
        if incluir_raw is None:
            incluir_raw = []
        if not isinstance(incluir_raw, list):
            raise FaroError("incluir debe ser una lista")
        incluir = {str(value).strip().lower() for value in incluir_raw}
        permitidos = {"tecnica", "imagen"}
        desconocidos = sorted(incluir - permitidos)
        if desconocidos:
            raise FaroError("Valores de incluir no permitidos: " + ", ".join(desconocidos))

        svc = self.phase1_service()
        try:
            resumen = svc.find_article(identificador)
            if not resumen:
                return {"found": False, "identificador": identificador}
            codart = str(resumen.get("codart") or "").strip()
            row = svc.db.fetch_one(
                "SELECT * FROM ARTICUL WHERE ART_NUMEMP=? AND ART_CODART=?",
                (svc.settings.empresa, codart),
            )
            marca = svc.article_brand(codart)
            result = {
                "found": True,
                "identificador": identificador,
                "codart": codart,
                "marca": marca.get("marca", ""),
                "resumen": resumen,
                "articulo": normalize(row) if row else {},
            }
            if "tecnica" in incluir:
                result["tecnica"] = svc.article_technical_info(codart)
            if "imagen" in incluir:
                result["imagen"] = svc.article_image_as_json(codart, str(args.get("tamano_imagen", "")))
            return result
        finally:
            svc.db.close()

    def tool_articulo_compra_consultar(self, args: dict[str, Any]) -> Any:
        """Consulta proveedores del articulo o la ficha de un proveedor concreto."""
        codart = str(args.get("codart", "")).strip()
        if not codart:
            raise FaroError("codart es obligatorio")
        svc = self.phase1_service()
        try:
            if args.get("codpro") is None:
                return {"modo": "proveedores", **svc.article_suppliers(codart)}
            return {
                "modo": "ficha",
                **svc.article_purchase_sheet(codart, args["codpro"]),
            }
        finally:
            svc.db.close()

    def tool_articulo_precio_coste(self, args: dict[str, Any]) -> Any:
        """Calcula el precio de coste de rentabilidad replicando ARTICUL_UB.pas."""
        codart = str(args.get("codart", "")).strip()
        if not codart:
            raise FaroError("codart es obligatorio")
        fecha = FaroPhase1Service._parse_optional_date(args.get("fecha"), date.today())
        if fecha is None:
            raise FaroError("fecha es obligatoria")
        svc = self.service()
        try:
            return svc.article_cost_price(codart, fecha, str(args.get("moneda", "E")))
        finally:
            svc.db.close()

    def tool_articulo_catalogo_listar(self, args: dict[str, Any]) -> Any:
        """Lista marcas, familias ERP o familias web desde una unica fachada."""
        tipo = str(args.get("tipo", "familias")).strip().lower()
        padre = str(args.get("padre", ""))
        svc = self.phase1_service()
        try:
            if tipo == "marcas":
                if padre:
                    raise FaroError("padre no se aplica cuando tipo='marcas'")
                return {"tipo": "marcas", **svc.list_brands()}
            if tipo == "familias":
                return {"tipo": "familias", **svc.list_families(padre)}
            if tipo == "familias_web":
                return {"tipo": "familias_web", **svc.list_web_families(padre)}
            raise FaroError("tipo debe ser 'marcas', 'familias' o 'familias_web'")
        finally:
            svc.db.close()

    def tool_stock_consultar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            codart = str(args["codart"])
            if _center_filter_is_set(args.get("centro")):
                result = svc.article_stock(codart, args["centro"])
                return {
                    "codart": codart,
                    "scope": "centro",
                    "items": [{
                        "centro": result.get("centro"),
                        "existencias": result.get("existencias"),
                    }],
                    "datasnap_text": result.get("datasnap_text", ""),
                }
            result = svc.article_stocks(codart)
            return {**result, "scope": "todos"}
        finally:
            svc.db.close()


    def tool_etiqueta_gestion(self, args: dict[str, Any]) -> Any:
        accion = str(args.get("accion", "listar")).strip().lower()
        if accion not in {"listar", "grabar", "borrar"}:
            raise FaroError("accion debe ser 'listar', 'grabar' o 'borrar'")
        if accion == "listar":
            return self._tool_etiqueta_listar(args)
        if accion == "grabar":
            required = ("codart", "cantid", "aumentar", "modelo", "imprimir")
            missing = [name for name in required if name not in args]
            if missing:
                raise FaroError("Faltan campos para grabar etiqueta: " + ", ".join(missing))
            return self._tool_etiqueta_grabar(args)
        if not str(args.get("codart", "")).strip():
            raise FaroError("codart es obligatorio para borrar una etiqueta")
        return self._tool_etiqueta_borrar(args)

    def tool_recuento_gestion(self, args: dict[str, Any]) -> Any:
        accion = str(args.get("accion", "listar")).strip().lower()
        if accion not in {"listar", "grabar", "borrar"}:
            raise FaroError("accion debe ser 'listar', 'grabar' o 'borrar'")
        if "centro" not in args:
            raise FaroError("centro es obligatorio para gestionar recuentos")
        if accion == "listar":
            return self._tool_recuento_listar(args)
        if accion == "grabar":
            required = ("codart", "cantid", "aumentar")
            missing = [name for name in required if name not in args]
            if missing:
                raise FaroError("Faltan campos para grabar recuento: " + ", ".join(missing))
            return self._tool_recuento_grabar(args)
        if not str(args.get("codart", "")).strip():
            raise FaroError("codart es obligatorio para borrar un recuento")
        return self._tool_recuento_borrar(args)

    def tool_falta_gestion(self, args: dict[str, Any]) -> Any:
        accion = str(args.get("accion", "listar")).strip().lower()
        if accion not in {"listar", "grabar", "borrar"}:
            raise FaroError("accion debe ser 'listar', 'grabar' o 'borrar'")
        if "centro" not in args:
            raise FaroError("centro es obligatorio para gestionar faltas")
        if accion == "listar":
            return self._tool_falta_listar(args)
        if not str(args.get("codart", "")).strip():
            raise FaroError("codart es obligatorio para grabar o borrar una falta")
        if accion == "grabar":
            required = ("cantid", "aumentar")
            missing = [name for name in required if name not in args]
            if missing:
                raise FaroError("Faltan campos para grabar falta: " + ", ".join(missing))
            routed = dict(args)
            routed["codpro"] = int(args.get("proveedor", args.get("codpro", 0)) or 0)
            return self._tool_falta_grabar(routed)
        proveedor = args.get("proveedor", args.get("provee"))
        if proveedor is None:
            raise FaroError("proveedor es obligatorio para borrar una falta")
        routed = dict(args)
        routed["provee"] = int(proveedor)
        return self._tool_falta_borrar(routed)

    def _tool_etiqueta_listar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            codart = str(args.get("codart", "")).strip()
            if codart:
                return svc.get_labels(codart)
            return svc.list_labels()
        finally:
            svc.db.close()

    def _tool_recuento_listar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            codart = str(args.get("codart", "")).strip()
            if codart:
                return svc.article_recount(codart, args["centro"])
            return svc.list_recounts(args["centro"])
        finally:
            svc.db.close()

    def _tool_falta_listar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            codart = str(args.get("codart", "")).strip()
            if codart:
                return svc.article_shortage(codart, args["centro"])
            return svc.list_shortages(args["centro"])
        finally:
            svc.db.close()

    def tool_articulo_ubicacion_guardar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            numero = int(args.get("numero", 1))
            if numero == 1:
                return svc.save_location(str(args["codart"]), str(args["ubicacion"]))
            if numero == 2:
                return svc.save_location_secondary(str(args["codart"]), str(args["ubicacion"]))
            raise FaroError("numero debe ser 1 (principal) o 2 (secundaria)")
        finally:
            svc.db.close()

    def tool_tarifa_proveedor_actualizar(self, args: dict[str, Any]) -> Any:
        svc = self.service()
        try:
            return svc.update_supplier_tariff(
                int(args["proveedor"]),
                list(args["lineas"]),
                bool(args.get("actualizar_precio_venta", False)),
                solo_si_sube_precio=bool(args.get("actualizar_solo_si_sube_precio", False)),
                solo_proveedor_principal=bool(args.get("actualizar_solo_proveedor_principal", False)),
                solo_si_propio=bool(args.get("actualizar_solo_si_propio", False)),
                generar_etiquetas=bool(args.get("generar_etiquetas", False)),
                etiqueta_modelo=int(args.get("etiqueta_modelo", 0) or 0),
                dar_de_alta=bool(args.get("dar_de_alta", False)),
                usar_referencia_proveedor_como_codigo=bool(
                    args.get("usar_referencia_proveedor_como_codigo", False)
                ),
                digitos_codigo_articulo=int(args.get("digitos_codigo_articulo", 9) or 9),
                numerador_inicial=int(args.get("numerador_inicial", 0) or 0),
            )
        finally:
            svc.db.close()

    def tool_cliente_buscar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            broader = any(str(args.get(k, "")).strip() for k in ("nombre_like", "poblacion_like", "cif"))
            broader = broader or args.get("codrep") is not None
            exact = args.get("codcli") is not None and args.get("subcli") is not None and not broader
            if exact:
                result = svc.search_client(args["codcli"], args["subcli"])
                return {"modo": "detalle", "resultado": result}
            result = svc.list_clients(
                args.get("codcli"), args.get("subcli"),
                str(args.get("nombre_like", "")), str(args.get("poblacion_like", "")),
                str(args.get("cif", "")), args.get("codrep"),
                int(args.get("limit", MAX_ROWS_DEFAULT)),
            )
            return {"modo": "listado", **result}
        finally:
            svc.db.close()

    def tool_proveedor_buscar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            broader = any(
                str(args.get(k, "")).strip()
                for k in (
                    "nombre_comercial_like", "nombre_fiscal_like", "nombre_abreviado_like", "cif",
                    "fecha_alta", "fecha_alta_desde", "fecha_alta_hasta",
                )
            )
            exact = args.get("codpro") is not None and not broader
            if exact:
                result = svc.search_provider(args["codpro"])
                return {"modo": "detalle", "resultado": result}
            result = svc.list_providers(
                args.get("codpro"),
                str(args.get("nombre_comercial_like", "")),
                str(args.get("nombre_fiscal_like", "")),
                str(args.get("nombre_abreviado_like", "")),
                str(args.get("cif", "")),
                str(args.get("fecha_alta", "")),
                str(args.get("fecha_alta_desde", "")),
                str(args.get("fecha_alta_hasta", "")),
                int(args.get("limit", MAX_ROWS_DEFAULT)),
            )
            return {"modo": "listado", **result}
        finally:
            svc.db.close()

    def tool_actividad_listar(self, args: dict[str, Any]) -> Any:
        """Lista actividades filtrando por cliente, tipo de actividad, representante
        y/o rango de fechas; los filtros son combinables (AND) y se exige al menos uno."""
        svc = self.phase1_service()
        try:
            return svc.list_activities(
                args.get("codcli"),
                args.get("codact"),
                args.get("codrep"),
                args.get("fecha_desde"),
                args.get("fecha_hasta"),
                int(args.get("limit", MAX_ROWS_DEFAULT)),
            )
        finally:
            svc.db.close()

    def tool_actividad_tipo_listar(self, args: dict[str, Any]) -> Any:
        return self._tool_actividad_tipos(args)

    def tool_actividad_grabar(self, args: dict[str, Any]) -> Any:
        required = ("codcli", "subcli", "fecha", "codact", "codrep")
        missing = [name for name in required if args.get(name) is None]
        if missing:
            raise FaroError("Faltan campos para grabar actividad: " + ", ".join(missing))
        return self._tool_actividad_grabar(args)

    def tool_articulo_cambiar_tabla_precio(self, args: dict[str, Any]) -> Any:
        svc = self.service()
        try:
            codart = str(args["codart"])
            new_table = int(args["new_table"])
            simular = bool(args.get("simular", True))
            if simular:
                return {"simulado": True, **svc.simulate_price_table_change(codart, new_table)}
            return {
                "simulado": False,
                **svc.change_article_price_table(
                    codart, new_table, bool(args.get("force_blister_current_cost", False))
                ),
            }
        finally:
            svc.db.close()

    def tool_articulo_familia_guardar(self, args: dict[str, Any]) -> Any:
        svc = self.service()
        try:
            return svc.change_article_family(
                str(args["codart"]),
                int(args["codfam"]),
                int(args["subfam"]),
                args.get("ssubfam") if "ssubfam" in args else None,
                args.get("new_table") if "new_table" in args else None,
            )
        finally:
            svc.db.close()

    def tool_articulo_familiancc_tabla_guardar(self, args: dict[str, Any]) -> Any:
        svc = self.service()
        try:
            return svc.change_article_famncc_table(
                str(args["codart"]),
                str(args.get("famncc", "")),
                args.get("new_table") if "new_table" in args else None,
            )
        finally:
            svc.db.close()

    def tool_pedido_listar(self, args: dict[str, Any]) -> Any:
        """Lista el cuadro operativo o el historico de pedidos de un cliente.

        Sin codcli/subcli conserva el comportamiento de Cuadro_Pedidos. Si se
        informan ambos, conserva Pedidos_Cliente. Se exige la pareja completa
        para evitar consultas ambiguas.
        """
        svc = self.phase1_service()
        try:
            has_codcli = args.get("codcli") is not None
            has_subcli = args.get("subcli") is not None
            if has_codcli != has_subcli:
                raise FaroError("codcli y subcli deben indicarse juntos")
            if has_codcli:
                return svc.list_client_orders(args["centro"], args["codcli"], args["subcli"])
            return svc.order_board(args["centro"])
        finally:
            svc.db.close()

    def tool_pedido_pdf_gestion(self, args: dict[str, Any]) -> Any:
        """Genera o recupera el PDF historico de un pedido."""
        accion = str(args.get("accion", "")).strip().lower()
        if accion not in {"generar", "obtener"}:
            raise FaroError("accion debe ser 'generar' u 'obtener'")
        svc = self.phase1_service()
        try:
            if accion == "generar":
                if args.get("centro") is None:
                    raise FaroError("centro es obligatorio para generar el PDF")
                return svc.generate_order_pdf(
                    args["centro"], args["ejerci"], str(args["serie"]), args["numdoc"]
                )
            return svc.order_pdf_as_json(args["ejerci"], str(args["serie"]), args["numdoc"])
        finally:
            svc.db.close()

    def tool_pedido_detalle(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            modo = str(args.get("modo", "normal")).lower()
            common = (args["centro"], args["ejerci"], str(args["serie"]), args["numdoc"])
            if modo == "normal":
                result = svc.order_lines(*common)
            elif modo == "preparacion":
                result = svc.order_preparation_lines(*common)
            else:
                raise FaroError("modo debe ser 'normal' o 'preparacion'")
            # Las implementaciones reales devuelven listas; algunos adaptadores
            # historicos devolvian un objeto. Se aceptan ambas formas.
            if isinstance(result, dict):
                return {"modo": modo, **result}
            return {"modo": modo, "items": result}
        finally:
            svc.db.close()


    def tool_precio_tabla_listar(self, args: dict[str, Any]) -> Any:
        svc = self.service()
        try:
            return svc.list_price_tables()
        finally:
            svc.db.close()




    def tool_articulo_buscar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.search_articles(
                str(args.get("texto", "")),
                str(args.get("order_by", "ART_DESCRI")),
                int(args.get("limit", MAX_ROWS_DEFAULT)),
                str(args.get("codart_prefix", "")),
                args.get("centro"),
                bool(args.get("with_stock", False)),
                args.get("purchase_before"),
                args.get("sale_before"),
                args.get("movement_before"),
            )
        finally:
            svc.db.close()










    def tool_articulo_precio_oferta(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.offer_pvp(str(args["codart"]))
        finally:
            svc.db.close()



    def _tool_etiqueta_grabar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_labels(
                str(args["codart"]),
                str(args.get("descri", "")),
                args["cantid"],
                bool(args["aumentar"]),
                args["modelo"],
                bool(args["imprimir"]),
            )
        finally:
            svc.db.close()

    def tool_stock_regularizar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.regularize_stock(
                str(args["codart"]),
                args["centro"],
                str(args.get("descri", "")),
                str(args.get("unimed", "")),
                args["cantid"],
            )
        finally:
            svc.db.close()



    def _tool_recuento_grabar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_recount(
                str(args["codart"]),
                args["centro"],
                str(args.get("descri", "")),
                str(args.get("unimed", "")),
                args["cantid"],
                bool(args["aumentar"]),
            )
        finally:
            svc.db.close()

    def _tool_recuento_borrar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.delete_recount(str(args["codart"]), args["centro"])
        finally:
            svc.db.close()

    def _tool_etiqueta_borrar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.delete_labels(str(args["codart"]))
        finally:
            svc.db.close()



    def _tool_falta_grabar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_shortage(
                str(args["codart"]),
                args["centro"],
                args["codpro"],
                args["cantid"],
                bool(args["aumentar"]),
            )
        finally:
            svc.db.close()

    def _tool_falta_borrar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.delete_shortage(str(args["codart"]), args["centro"], args["provee"])
        finally:
            svc.db.close()



    def tool_articulo_ean_grabar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_ean(str(args["codart"]), str(args["ean"]))
        finally:
            svc.db.close()



    def tool_cliente_actualizar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_client(str(args["texto"]))
        finally:
            svc.db.close()

    def _tool_actividad_tipos(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.activity_types()
        finally:
            svc.db.close()



    def _tool_actividad_grabar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_activity(
                args["codcli"],
                args["subcli"],
                str(args["fecha"]),
                args["codact"],
                args["codrep"],
                str(args.get("texto", "")),
            )
        finally:
            svc.db.close()





    def tool_pedido_crear(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_client_order(
                args["centro"],
                args["codcli"],
                args["subcli"],
                str(args.get("texto", "")),
                str(args.get("observaciones", "")),
                str(args.get("email", "")),
                str(args.get("urgente", "")),
            )
        finally:
            svc.db.close()

    def tool_pedido_cerrar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.close_client_order(
                str(args.get("usuario", "")),
                args["centro"],
                str(args["tipdoc"]),
                args["ejerci"],
                str(args["serie"]),
                args["numdoc"],
            )
        finally:
            svc.db.close()

    def tool_orden_compra_cerrar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.close_purchase_order(
                str(args.get("usuario", "")),
                args["centro"],
                args["ejerci"],
                str(args["serie"]),
                args["numdoc"],
            )
        finally:
            svc.db.close()

    def tool_orden_compra_propuesta_stock_minimo(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.purchase_stock_minimum_proposal(args)
        finally:
            svc.db.close()

    def tool_orden_compra_propuesta_pedidos_cliente(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.purchase_customer_orders_proposal(args)
        finally:
            svc.db.close()

    def tool_pedido_albaranar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_order_delivery(
                args["centro"],
                str(args["codigo_pedido"]),
                str(args.get("texto", "")),
            )
        finally:
            svc.db.close()





    def tool_pedido_linea_mover(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.move_order_line_zone(
                args["centro"], str(args["codart"]), str(args.get("descri", "")), args["cantid"],
                str(args["linea"]), args["zona_origen"], args["zona_destino"],
                str(args.get("ubi_origen", "")), str(args.get("ubi_destino", "")),
            )
        finally:
            svc.db.close()

    def tool_pedido_marcar_preparado(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_order_prepared(
                args["centro"], str(args["tipdoc"]), args["ejerci"], str(args["serie"]), args["numdoc"]
            )
        finally:
            svc.db.close()

    def tool_pedido_finalizar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.check_order_preparation_status(
                args["centro"], str(args["tipdoc"]), args["ejerci"], str(args["serie"]), args["numdoc"]
            )
        finally:
            svc.db.close()

    def tool_articulo_precio_cliente(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.customer_article_price(str(args["codart"]), args.get("cantidad", "1"), args["codcli"], args["subcli"])
        finally:
            svc.db.close()

    def tool_cliente_ultimas_ventas(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.last_customer_sales(args["codcli"], args["subcli"])
        finally:
            svc.db.close()

    def tool_cliente_tipo_venta(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.customer_sale_type(str(args["tipdoc"]), args["codcli"], args["subcli"])
        finally:
            svc.db.close()

    def tool_pedido_situacion_actualizar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_order_status(
                str(args["situac"]), args["centro"], str(args["tipdoc"]), args["ejerci"],
                str(args["serie"]), args["numdoc"]
            )
        finally:
            svc.db.close()

    def tool_entrada_pedidos_relacionados(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.incoming_order_customer_orders(
                args["centro"], args["ejerci"], str(args["serie"]), args["numdoc"]
            )
        finally:
            svc.db.close()

    def tool_entrada_almacen_crear(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.create_purchase_entry(args["cabecera"], args["lineas"])
        finally:
            svc.db.close()

    def tool_pedido_retirada_actualizar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_order_withdrawal_reference(
                str(args["documento"]), str(args.get("retirado", "")), str(args.get("referencia", ""))
            )
        finally:
            svc.db.close()


    def _tool_mostrador_venta_guardar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_open_sale(
                str(args.get("venta", "")), args["codcli"], args["subcli"], str(args.get("texto", "")),
                str(args["tipdoc"]), str(args.get("usuario", "")),
            )
        finally:
            svc.db.close()

    def _tool_mostrador_venta_borrar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.delete_open_sale(str(args["venta"]))
        finally:
            svc.db.close()

    def _tool_mostrador_pedido_cargar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_open_sale_from_order(
                args["centro"], str(args["codigo_pedido"]), str(args["tipdoc"]), str(args.get("texto", ""))
            )
        finally:
            svc.db.close()

    def tool_venta_documento_crear(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_sales_document(
                str(args.get("venta", "")), args["centro"], args["codcli"], args["subcli"],
                str(args.get("texto", "")), str(args["tipdoc"]), str(args.get("usuario", "")),
                str(args.get("serie", "")),
            )
        finally:
            svc.db.close()

    def tool_venta_alertas_rentabilidad(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.sales_profit_alerts(args)
        finally:
            svc.db.close()

    def tool_negocio_tendencias(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.business_trends(args)
        finally:
            svc.db.close()

    def tool_negocio_diagnostico_cambios(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.business_change_diagnosis(args)
        finally:
            svc.db.close()

    def tool_negocio_clientes_riesgo(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.customer_risk_analysis(args)
        finally:
            svc.db.close()

    def tool_negocio_cuadro_mando(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.business_dashboard_summary(args)
        finally:
            svc.db.close()

    def tool_dashboard_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.business_dashboard_summary(args)
        finally:
            svc.db.close()

    def tool_dashboard_series_temporales(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.dashboard_time_series(args)
        finally:
            svc.db.close()

    def tool_dashboard_alertas(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.dashboard_alerts(args)
        finally:
            svc.db.close()

    def tool_dashboard_filtros(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.dashboard_filters(args)
        finally:
            svc.db.close()

    def tool_dashboard_acciones_recomendadas(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.dashboard_recommended_actions(args)
        finally:
            svc.db.close()

    def tool_ventas_acciones_recomendadas(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.sales_recommended_actions(args)
        finally:
            svc.db.close()

    def tool_clientes_acciones_recomendadas(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.customers_recommended_actions(args)
        finally:
            svc.db.close()

    def tool_stock_acciones_recomendadas(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.stock_recommended_actions(args)
        finally:
            svc.db.close()

    def tool_pedidos_acciones_recomendadas(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.pending_recommended_actions(args)
        finally:
            svc.db.close()

    def tool_tesoreria_acciones_recomendadas(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.treasury_recommended_actions(args)
        finally:
            svc.db.close()

    def tool_ventas_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.sales_dashboard_summary(args)
        finally:
            svc.db.close()

    def tool_compras_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.purchases_dashboard_summary(args)
        finally:
            svc.db.close()

    def tool_cartera_efectos_detalle(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.cartera_effect_details(args)
        finally:
            svc.db.close()

    def tool_cartera_efectos_pendientes_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.cartera_pending_effects_summary(args)
        finally:
            svc.db.close()

    def tool_cartera_efectos_por_cliente(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.cartera_effects_by_customer(args)
        finally:
            svc.db.close()

    def tool_cartera_pendiente_remesar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.cartera_pending_remittance(args)
        finally:
            svc.db.close()

    def tool_cartera_remesas_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.cartera_remittance_summary(args)
        finally:
            svc.db.close()

    def tool_cartera_riesgo_cliente(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.cartera_customer_credit_risk(args)
        finally:
            svc.db.close()

    def tool_cartera_riesgo_clientes_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.cartera_customer_credit_risk_summary(args)
        finally:
            svc.db.close()

    def tool_compras_articulos_pendientes_recibir(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.purchase_items_pending_receipt_summary(args)
        finally:
            svc.db.close()

    def tool_compras_pedidos_pendientes_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.purchase_orders_pending_summary(args)
        finally:
            svc.db.close()

    def tool_compras_documentos_pendientes_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.purchase_documents_pending_summary(args)
        finally:
            svc.db.close()

    def tool_stock_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.stock_dashboard_summary(args)
        finally:
            svc.db.close()

    def tool_pedidos_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.pending_orders_dashboard_summary(args)
        finally:
            svc.db.close()

    def tool_documentos_pendientes_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.pending_documents_dashboard_summary(args)
        finally:
            svc.db.close()

    def tool_clientes_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.customers_dashboard_summary(args)
        finally:
            svc.db.close()

    def tool_proveedores_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.providers_dashboard_summary(args)
        finally:
            svc.db.close()

    def tool_tesoreria_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.treasury_dashboard_summary(args)
        finally:
            svc.db.close()

    def tool_negocio_stock_rotacion(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.stock_rotation_analysis(args)
        finally:
            svc.db.close()

    def tool_negocio_stock_tendencias(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.stock_trends_analysis(args)
        finally:
            svc.db.close()

    def tool_venta_rentabilidad_lineas(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.sales_profit_lines(**args)
        finally:
            svc.db.close()

    def tool_venta_rentabilidad_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.sales_profit_summary(args)
        finally:
            svc.db.close()

    def tool_venta_documentos_detalle(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.sales_document_details(**args)
        finally:
            svc.db.close()

    def tool_venta_documentos_resumen(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.sales_document_summary(args)
        finally:
            svc.db.close()

    def tool_venta_documentos_abc(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.sales_document_abc(args)
        finally:
            svc.db.close()

    def tool_oferta_crear(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.create_offer(
                str(args["tipo_oferta"]),
                str(args["nombre"]),
                args["fecha_inicio"],
                args["fecha_fin"],
                args["articulos"],
                args.get("proveedor", 0),
                args.get("ejercicio"),
                str(args.get("moneda", "E")),
                args.get("gastos", 0),
                args.get("fecha"),
            )
        finally:
            svc.db.close()

    def tool_mostrador_cobrar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.save_ticket_invoice(
                args["caja"], args.get("efectivo", ""), args.get("tarjeta", ""), args.get("otros", ""),
                str(args.get("autorizacion", "")), args["total"], str(args.get("venta", "")),
                args["centro"], args["codcli"], args["subcli"], str(args.get("texto", "")),
                str(args["tipdoc"]), str(args.get("usuario", "")),
            )
        finally:
            svc.db.close()

    def tool_stock_trasvasar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.transfer_centers(args["centroo"], args["centrod"], str(args.get("texto", "")))
        finally:
            svc.db.close()

    def tool_integracion_coinfer_stock(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.coinfer_stock(str(args["codart"]))
        finally:
            svc.db.close()

    def tool_empresa_replicar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.replicate_company_from_template(
                int(args["empresa_destino"]),
                str(args["nombre"]),
                str(args["direccion"]),
            )
        finally:
            svc.db.close()

    def tool_control_horario_fichar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.check_time_clock_user(str(args.get("password", "")))
        finally:
            svc.db.close()

    def tool_pedido_enviar(self, args: dict[str, Any]) -> Any:
        svc = self.phase1_service()
        try:
            return svc.send_order(args["centro"], args["ejerci"], str(args["serie"]), args["numdoc"], str(args["email"]))
        finally:
            svc.db.close()















    def invoke_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Ejecuta una herramienta Faro sin implementar protocolo MCP.

        Esta es la frontera de negocio usada por el adaptador del SDK oficial.
        Devuelve ``(envelope_publico, is_error)`` y conserva en un unico lugar
        validacion de contrato, permisos y auditoria.
        """
        tool_name = str(name)
        args: dict[str, Any] = arguments if isinstance(arguments, dict) else {}
        audit_args = dict(args)
        audit_args.setdefault("empresa", DEFAULT_EMPRESA)
        request_id = str(request_id or uuid.uuid4().hex)

        if tool_name not in self.tools:
            result = normalize_public_error(
                tool_name, self.tool_profile, FaroError(f"Herramienta desconocida: {tool_name}")
            )
            return result, True

        risk = effective_tool_risk(tool_name, args)
        should_audit = risk != "read" or self.security.audit_reads
        started = time.perf_counter()

        if not access_allows(self.security.access_level, risk):
            exc = FaroPermissionError(
                f"Permiso insuficiente para {tool_name}: requiere '{risk}' "
                f"y el servidor esta en '{self.security.access_level}'"
            )
            result = normalize_public_error(tool_name, self.tool_profile, exc)
            if should_audit:
                try:
                    self.audit.record(
                        request_id=request_id, tool=tool_name, risk=risk, status="denied",
                        arguments=audit_args,
                        error_code=result["error"]["code"], error_message=result["error"]["message"],
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                except FaroAuditError as audit_exc:
                    # No hay mutacion que proteger: no se oculta FORBIDDEN.
                    print(f"[faro-mcp] AUDIT WARNING: {audit_exc}", file=sys.stderr)
            return result, True

        if should_audit:
            # Fail closed: toda mutacion deja constancia antes de ejecutarse.
            try:
                self.audit.record(
                    request_id=request_id, tool=tool_name, risk=risk, status="started", arguments=audit_args
                )
            except FaroAuditError as audit_exc:
                return normalize_public_error(tool_name, self.tool_profile, audit_exc), True

        try:
            internal_args = translate_public_arguments(tool_name, args)
            empresa = internal_args.pop("empresa", DEFAULT_EMPRESA)
            with self._empresa_context(empresa):
                raw_result = self.tools[tool_name](internal_args)
            result = normalize_public_result(tool_name, self.tool_profile, raw_result)
            is_error = not bool(result.get("ok"))
            if should_audit:
                try:
                    self.audit.record(
                        request_id=request_id, tool=tool_name, risk=risk,
                        status="business_error" if is_error else "success",
                        error_code=(result.get("error") or {}).get("code", "") if is_error else "",
                        error_message=(result.get("error") or {}).get("message", "") if is_error else "",
                        duration_ms=(time.perf_counter() - started) * 1000,
                        result_summary=_audit_result_summary(
                            (result.get("error") or {}).get("details", {}) if is_error else result.get("data")
                        ),
                    )
                except FaroAuditError as audit_exc:
                    # El evento started ya existe; no se devuelve fallo tras commit.
                    result.setdefault("warnings", []).append(
                        "La operacion se completo, pero no se pudo registrar el cierre de auditoria."
                    )
                    print(f"[faro-mcp] AUDIT WARNING: {audit_exc}", file=sys.stderr)
            return result, is_error
        except Exception as tool_exc:
            result = normalize_public_error(tool_name, self.tool_profile, tool_exc)
            if should_audit:
                try:
                    self.audit.record(
                        request_id=request_id, tool=tool_name, risk=risk, status="error",
                        error_code=result["error"]["code"], error_message=result["error"]["message"],
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                except FaroAuditError:
                    pass
            return result, True


_INTERNAL_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {'actividad_grabar': {'description': 'Clientes/CRM. ESCRITURA. Registra una actividad comercial de un '
                                      'cliente en una fecha, o actualiza la ya existente para ese '
                                      'cliente y esa fecha.',
                       'inputSchema': {'properties': {'codact': {'description': 'Tipo de actividad.',
                                                                 'type': 'integer'},
                                                      'codcli': {'type': 'integer'},
                                                      'codrep': {'description': 'Representante.',
                                                                 'type': 'integer'},
                                                      'fecha': {'description': 'AAAA-MM-DD.',
                                                                'type': 'string'},
                                                      'subcli': {'type': 'integer'},
                                                      'texto': {'description': 'Observacion de la actividad.',
                                                                'type': 'string'}},
                                       'required': ['codcli', 'subcli', 'fecha', 'codact', 'codrep'],
                                       'type': 'object'},
                       'name': 'actividad_grabar'},
 'actividad_listar': {'description': 'Clientes/CRM. Lista actividades filtrando por cliente, tipo de actividad, '
                                     'representante y/o un rango de fechas; los filtros son combinables. Se '
                                     'exige al menos uno.',
                      'inputSchema': {'properties': {'codact': {'description': 'Tipo de actividad.',
                                                                'type': 'integer'},
                                                     'codcli': {'type': 'integer'},
                                                     'codrep': {'description': 'Representante.',
                                                                'type': 'integer'},
                                                     'fecha_desde': {'description': 'AAAA-MM-DD.',
                                                                     'type': 'string'},
                                                     'fecha_hasta': {'description': 'AAAA-MM-DD.',
                                                                     'type': 'string'},
                                                     'limit': {'type': 'integer'}},
                                      'type': 'object'},
                      'name': 'actividad_listar'},
 'actividad_tipo_listar': {'description': 'Clientes/CRM. Lista los tipos de actividad comercial disponibles.',
                           'inputSchema': {'properties': {}, 'type': 'object'},
                           'name': 'actividad_tipo_listar'},
 'oferta_crear': {'description': 'Ofertas. ESCRITURA. Crea una oferta con cabecera y lineas de articulos.',
                  'inputSchema': {'properties': {'articulos': {'description': 'Lineas de articulos de la oferta.',
                                                               'type': 'array'},
                                                 'ejercicio': {'description': 'Ejercicio de numeracion. Si se omite '
                                                                              'se usa el anio de fecha_inicio.',
                                                               'type': 'integer'},
                                                 'fecha': {'description': 'Fecha de alta. Si se omite se usa hoy.',
                                                           'type': 'string'},
                                                 'fecha_fin': {'description': 'AAAA-MM-DD. Fin de validez.',
                                                               'type': 'string'},
                                                 'fecha_inicio': {'description': 'AAAA-MM-DD. Inicio de validez.',
                                                                  'type': 'string'},
                                                 'gastos': {'default': 0, 'type': ['number', 'string']},
                                                 'moneda': {'default': 'E', 'type': 'string'},
                                                 'nombre': {'type': 'string'},
                                                 'proveedor': {'default': 0, 'type': 'integer'},
                                                 'tipo_oferta': {'description': 'R=Solo Profesional, P=Preguntar '
                                                                                'Siempre, T=Todos, S=Sin Precios, '
                                                                                'W=Todos + Web.',
                                                                 'enum': ['R', 'P', 'T', 'S', 'W'],
                                                                 'type': 'string'}},
                                  'required': ['tipo_oferta', 'nombre', 'fecha_inicio', 'fecha_fin', 'articulos'],
                                  'type': 'object'},
                  'name': 'oferta_crear'},
 'orden_compra_cerrar': {'description': 'Compras. ESCRITURA. Cierra manualmente una orden de compra (CABORC) y todas sus lineas.',
                         'inputSchema': {'properties': {'centro': {'type': 'integer'},
                                                        'ejerci': {'type': 'integer'},
                                                        'numdoc': {'type': 'integer'},
                                                        'serie': {'type': 'string'},
                                                        'usuario': {'description': 'Usuario que realiza el cierre (COC_USUMOD).',
                                                                    'type': 'string'}},
                                         'required': ['centro', 'ejerci', 'serie', 'numdoc'],
                                         'type': 'object'},
                         'name': 'orden_compra_cerrar'},
 'tarifa_proveedor_actualizar': {'description': 'Compras/precios. CRITICA. Da de alta o actualiza tarifas de proveedor en ARTICULP siguiendo IMPTAR_U.pas; opcionalmente recalcula ARTICUL.',
                                  'inputSchema': {'properties': {'actualizar_precio_venta': {'default': False,
                                                                                              'type': 'boolean'},
                                                                 'actualizar_solo_si_sube_precio': {'default': False,
                                                                                                     'type': 'boolean'},
                                                                 'actualizar_solo_proveedor_principal': {'default': False,
                                                                                                          'type': 'boolean'},
                                                                 'actualizar_solo_si_propio': {'default': False,
                                                                                               'type': 'boolean'},
                                                                 'generar_etiquetas': {'default': False,
                                                                                       'type': 'boolean'},
                                                                 'etiqueta_modelo': {'default': 0,
                                                                                     'type': 'integer'},
                                                                 'dar_de_alta': {'default': False,
                                                                                 'type': 'boolean'},
                                                                 'usar_referencia_proveedor_como_codigo': {'default': False,
                                                                                                            'type': 'boolean'},
                                                                 'digitos_codigo_articulo': {'default': 9,
                                                                                             'type': 'integer'},
                                                                 'numerador_inicial': {'default': 0,
                                                                                       'type': 'integer'},
                                                                 'lineas': {'type': 'array'},
                                                                 'proveedor': {'type': 'integer'}},
                                                  'required': ['proveedor', 'lineas'],
                                                  'type': 'object'},
                                  'name': 'tarifa_proveedor_actualizar'},
 'articulo_buscar': {'description': 'Articulos. Busca articulos por texto, descripcion o prefijo de codigo con orden y '
                                    'limite controlados. Puede filtrar por existencias del centro y por fechas '
                                    'de compra, venta o ultimo movimiento registradas en ARTICULE.',
                     'inputSchema': {'properties': {'codart_prefix': {'description': 'Prefijo de ART_CODART para '
                                                                                     'busqueda por codigo.',
                                                                      'type': 'string'},
                                                    'centro': {'description': 'Centro para leer ARTICULE. Si se omite '
                                                                             'se usa el centro configurado.',
                                                               'type': 'integer'},
                                                    'movement_before': {'description': 'Fecha maxima exclusiva de ultimo '
                                                                                       'movimiento en ARTICULE.',
                                                                        'type': 'string'},
                                                    'purchase_before': {'description': 'Fecha maxima exclusiva de compra '
                                                                                       'en ARTICULE.',
                                                                        'type': 'string'},
                                                    'sale_before': {'description': 'Fecha maxima exclusiva de venta '
                                                                                   'en ARTICULE.',
                                                                    'type': 'string'},
                                                    'with_stock': {'default': False,
                                                                   'description': 'Si es true exige existencias mayores '
                                                                                  'que cero en el centro.',
                                                                   'type': 'boolean'},
                                                    'limit': {'type': 'integer'},
                                                    'order_by': {'description': 'Uno de ART_CODART, ART_DESCRI, '
                                                                                'ART_UNIMED, ART_PRECOS, ART_PREVEN4, '
                                                                                'ART_PVP, ART_CODPRO, PRO_NOMCOR, '
                                                                                'ARTE_EXIST, ARTE_FECCOM, '
                                                                                'ARTE_FECVEN, ARTE_FECMOV.',
                                                                 'type': 'string'},
                                                    'texto': {'type': 'string'}},
                                     'type': 'object'},
                     'name': 'articulo_buscar'},
 'articulo_cambiar_tabla_precio': {'description': 'Articulos/precios. Simula o aplica un cambio de tabla de precio y '
                                                  'recalcula precios. Por seguridad simular=true por defecto.',
                                   'inputSchema': {'properties': {'codart': {'type': 'string'},
                                                                  'force_blister_current_cost': {'default': False,
                                                                                                 'type': 'boolean'},
                                                                  'new_table': {'type': 'integer'},
                                                                  'simular': {'default': True, 'type': 'boolean'}},
                                                   'required': ['codart', 'new_table'],
                                                   'type': 'object'},
                                   'name': 'articulo_cambiar_tabla_precio'},
 'articulo_catalogo_listar': {'description': 'Articulos. Lista catalogos auxiliares: marcas, familias ERP o familias '
                                             'web.',
                              'inputSchema': {'properties': {'padre': {'description': 'Codigo padre para '
                                                                                      'familias/subfamilias. No se usa '
                                                                                      'para marcas.',
                                                                       'type': 'string'},
                                                             'tipo': {'default': 'familias',
                                                                      'enum': ['marcas', 'familias', 'familias_web'],
                                                                      'type': 'string'}},
                                              'type': 'object'},
                              'name': 'articulo_catalogo_listar'},
 'articulo_compra_consultar': {'description': 'Compras. Sin codpro lista los proveedores asociados al articulo; con '
                                              'codpro devuelve su ficha de compra y coste calculado.',
                               'inputSchema': {'properties': {'codart': {'type': 'string'},
                                                              'codpro': {'description': 'Proveedor opcional. Si se '
                                                                                        'omite se listan todos los '
                                                                                        'proveedores del articulo.',
                                                                         'type': 'integer'}},
                                               'required': ['codart'],
                                               'type': 'object'},
                               'name': 'articulo_compra_consultar'},
 'articulo_ean_grabar': {'description': 'Articulos. ESCRITURA. Agrega o actualiza un codigo EAN asociado a un '
                                        'articulo.',
                         'inputSchema': {'properties': {'codart': {'type': 'string'},
                                                        'ean': {'description': 'Codigo de barras. Debe ser numerico.',
                                                                'type': 'string'}},
                                         'required': ['codart', 'ean'],
                                         'type': 'object'},
                         'name': 'articulo_ean_grabar'},
 'articulo_familia_guardar': {'description': 'Articulos. ESCRITURA. Cambia la familia, subfamilia, tercer nivel y tabla de precio de un articulo.',
                              'inputSchema': {'properties': {'codart': {'type': 'string'},
                                                             'codfam': {'description': 'Codigo de familia ERP.',
                                                                        'type': 'integer'},
                                                             'new_table': {'description': 'Tabla de precio manual. Si se omite, viene vacia o es 0, se toma de SSUBFAM o SUBFAM cuando exista.',
                                                                           'type': ['integer', 'string']},
                                                             'subfam': {'description': 'Codigo de subfamilia ERP.',
                                                                        'type': 'integer'},
                                                             'ssubfam': {'description': 'Codigo de sub-subfamilia ERP. Se guarda como informacion adicional SSUBF; 0 o vacio lo borra.',
                                                                         'type': ['integer', 'string']}},
                                              'required': ['codart', 'codfam', 'subfam'],
                                              'type': 'object'},
                              'name': 'articulo_familia_guardar'},
 'articulo_familiancc_tabla_guardar': {'description': 'Articulos. ESCRITURA. Cambia la familia NCC y la tabla de precio de un articulo.',
                                       'inputSchema': {'properties': {'codart': {'type': 'string'},
                                                                      'famncc': {'description': 'Codigo de familia NCC. Se guarda como informacion adicional FAMNC; vacio lo borra.',
                                                                                 'type': 'string'},
                                                                      'new_table': {'description': 'Tabla de precio manual. Si se omite, viene vacia o es 0, se toma de FAMNCC.NCC_TABLA cuando exista.',
                                                                                    'type': ['integer', 'string']}},
                                                       'required': ['codart', 'famncc'],
                                                       'type': 'object'},
                                       'name': 'articulo_familiancc_tabla_guardar'},
 'articulo_obtener': {'description': 'Articulos. Obtiene la ficha de un articulo por codigo o EAN. Puede incluir bajo '
                                     'demanda informacion tecnica e imagen sin hacer pesada la consulta normal.',
                      'inputSchema': {'properties': {'identificador': {'description': 'Codigo de articulo o codigo de '
                                                                                      'barras/EAN.',
                                                                       'type': 'string'},
                                                     'incluir': {'description': 'Recursos opcionales a adjuntar a la '
                                                                                'ficha.',
                                                                 'items': {'enum': ['tecnica', 'imagen'],
                                                                           'type': 'string'},
                                                                 'type': 'array'},
                                                     'tamano_imagen': {'description': 'Tamano historico de imagen; '
                                                                                      'solo se usa si incluir contiene '
                                                                                      'imagen.',
                                                                       'type': 'string'}},
                                      'required': ['identificador'],
                                      'type': 'object'},
                      'name': 'articulo_obtener'},
 'articulo_precio_cliente': {'description': 'Precios. Calcula el precio efectivo de un articulo para un cliente '
                                            'aplicando sus reglas comerciales.',
                             'inputSchema': {'properties': {'cantidad': {'default': '1', 'type': ['string', 'number']},
                                                            'codart': {'type': 'string'},
                                                            'codcli': {'type': 'integer'},
                                                            'subcli': {'type': 'integer'}},
                                             'required': ['codart', 'codcli', 'subcli'],
                                             'type': 'object'},
                             'name': 'articulo_precio_cliente'},
 'articulo_precio_coste': {'description': 'Rentabilidad. Calcula el precio de coste de un articulo en una fecha segun '
                                          'el parametro RENTAB del ERP.',
                           'inputSchema': {'properties': {'codart': {'type': 'string'},
                                                          'fecha': {'description': 'AAAA-MM-DD.',
                                                                    'type': 'string'},
                                                          'moneda': {'default': 'E',
                                                                     'enum': ['E', 'P'],
                                                                     'type': 'string'}},
                                           'required': ['codart', 'fecha'],
                                           'type': 'object'},
                           'name': 'articulo_precio_coste'},
 'articulo_precio_oferta': {'description': 'Precios. Obtiene el PVP de oferta vigente de un articulo.',
                            'inputSchema': {'properties': {'codart': {'type': 'string'}},
                                            'required': ['codart'],
                                            'type': 'object'},
                            'name': 'articulo_precio_oferta'},
 'articulo_ubicacion_guardar': {'description': 'Articulos/almacen. ESCRITURA. Guarda la ubicacion principal (numero=1) '
                                               'o secundaria (numero=2) de un articulo.',
                                'inputSchema': {'properties': {'codart': {'type': 'string'},
                                                               'numero': {'default': 1,
                                                                          'enum': [1, 2],
                                                                          'type': 'integer'},
                                                               'ubicacion': {'type': 'string'}},
                                                'required': ['codart', 'ubicacion'],
                                                'type': 'object'},
                                'name': 'articulo_ubicacion_guardar'},
 'cliente_actualizar': {'description': 'Clientes. ESCRITURA. Actualiza los datos admitidos de un cliente existente.',
                        'inputSchema': {'properties': {'texto': {'description': 'CODCLI|SUBCLI|NOMCLI|RAZSOC|DOMICI|CODPOS|POBLAC|TELEFO|EMAIL|CIF',
                                                                 'type': 'string'}},
                                        'required': ['texto'],
                                        'type': 'object'},
                        'name': 'cliente_actualizar'},
 'cliente_buscar': {'description': 'Clientes. Busca clientes con filtros tipados. Si se indican solo codcli y subcli '
                                   'devuelve la ficha detallada; en otro caso devuelve un listado filtrado.',
                    'inputSchema': {'properties': {'cif': {'type': 'string'},
                                                   'codcli': {'type': 'integer'},
                                                   'codrep': {'type': 'integer'},
                                                   'limit': {'description': 'Maximo de filas; por defecto 500.',
                                                             'type': 'integer'},
                                                   'nombre_like': {'type': 'string'},
                                                   'poblacion_like': {'type': 'string'},
                                                   'subcli': {'type': 'integer'}},
                                    'type': 'object'},
                    'name': 'cliente_buscar'},
 'cliente_tipo_venta': {'description': 'Clientes. Determina el tipo de venta aplicable a un cliente.',
                        'inputSchema': {'properties': {'codcli': {'type': 'integer'},
                                                       'subcli': {'type': 'integer'},
                                                       'tipdoc': {'type': 'string'}},
                                        'required': ['tipdoc', 'codcli', 'subcli'],
                                        'type': 'object'},
                        'name': 'cliente_tipo_venta'},
 'cliente_ultimas_ventas': {'description': 'Clientes. Consulta las ultimas ventas de articulos realizadas a un '
                                           'cliente.',
                            'inputSchema': {'properties': {'codcli': {'type': 'integer'},
                                                           'subcli': {'type': 'integer'}},
                                            'required': ['codcli', 'subcli'],
                                            'type': 'object'},
                            'name': 'cliente_ultimas_ventas'},
 'control_horario_fichar': {'description': 'Control horario. ESCRITURA. Valida la clave del usuario y registra entrada '
                                           'o salida.',
                            'inputSchema': {'properties': {'password': {'description': 'Clave de fichaje del usuario, '
                                                                                       'en texto original antes de '
                                                                                       'CRIPT.',
                                                                        'type': 'string'}},
                                            'required': ['password'],
                                            'type': 'object'},
                            'name': 'control_horario_fichar'},
 'entrada_almacen_crear': {'description': 'Compras/almacen. ESCRITURA. Crea una entrada de almacen con cabecera y '
                                          'lineas estructuradas, enlazando pedidos pendientes cuando proceda y '
                                          'actualizando existencias.',
                           'inputSchema': {'properties': {'cabecera': {'additionalProperties': False,
                                                                        'properties': {'albaran': {'type': 'string'},
                                                                                       'base1': {'type': ['number', 'string']},
                                                                                       'base2': {'type': ['number', 'string']},
                                                                                       'base3': {'type': ['number', 'string']},
                                                                                       'base4': {'type': ['number', 'string']},
                                                                                       'centro': {'type': 'integer'},
                                                                                       'cif': {'description': 'CIF del proveedor; solo se usa si proveedor es 0.',
                                                                                               'type': 'string'},
                                                                                       'descuento': {'type': ['number', 'string']},
                                                                                       'ejercicio': {'type': 'integer'},
                                                                                       'factura': {'type': 'string'},
                                                                                       'fecha': {'description': 'AAAA-MM-DD o DD/MM/AAAA. Por defecto hoy.',
                                                                                                 'type': 'string'},
                                                                                       'fecha_factura': {'type': 'string'},
                                                                                       'fecha_recepcion': {'type': 'string'},
                                                                                       'iva1': {'type': ['number', 'string']},
                                                                                       'iva2': {'type': ['number', 'string']},
                                                                                       'iva3': {'type': ['number', 'string']},
                                                                                       'iva4': {'type': ['number', 'string']},
                                                                                       'moneda': {'type': 'string'},
                                                                                       'numero': {'type': 'integer'},
                                                                                       'observaciones': {'type': 'string'},
                                                                                       'portes': {'type': ['number', 'string']},
                                                                                       'proveedor': {'description': 'Codigo de proveedor. Si es 0 se busca por cif.',
                                                                                                     'type': 'integer'},
                                                                                       'recargo1': {'type': ['number', 'string']},
                                                                                       'recargo2': {'type': ['number', 'string']},
                                                                                       'recargo3': {'type': ['number', 'string']},
                                                                                       'recargo4': {'type': ['number', 'string']},
                                                                                       'serie': {'type': 'string'}},
                                                                        'type': 'object'},
                                                       'lineas': {'items': {'additionalProperties': False,
                                                                            'properties': {'articulo': {'description': 'Referencia recibida; si existe en ARTICULP para el proveedor se traduce a articulo interno.',
                                                                                                         'type': 'string'},
                                                                                           'cantidad': {'type': ['number', 'string']},
                                                                                           'descripcion': {'type': 'string'},
                                                                                           'descuento1': {'type': ['number', 'string']},
                                                                                           'descuento2': {'type': ['number', 'string']},
                                                                                           'descuento3': {'type': ['number', 'string']},
                                                                                           'descuento4': {'type': ['number', 'string']},
                                                                                           'descuento5': {'type': ['number', 'string']},
                                                                                           'descuento6': {'type': ['number', 'string']},
                                                                                           'iva': {'type': ['number', 'string']},
                                                                                           'linea': {'type': 'integer'},
                                                                                           'moneda': {'type': 'string'},
                                                                                           'precio': {'type': ['number', 'string']},
                                                                                           'recargo': {'type': ['number', 'string']},
                                                                                           'referencia_proveedor': {'type': 'string'},
                                                                                           'unidad_medida': {'type': 'string'}},
                                                                            'required': ['cantidad'],
                                                                            'type': 'object'},
                                                                  'minItems': 1,
                                                                  'type': 'array'}},
                                           'required': ['cabecera', 'lineas'],
                                           'type': 'object'},
                           'name': 'entrada_almacen_crear'},
 'entrada_pedidos_relacionados': {'description': 'Compras/almacen. Localiza pedidos de cliente relacionados con los '
                                                 'articulos de una entrada.',
                                  'inputSchema': {'properties': {'centro': {'description': 'Centro del documento '
                                                                                           'DETMOVM de entrada.',
                                                                            'type': 'integer'},
                                                                 'ejerci': {'type': 'integer'},
                                                                 'numdoc': {'type': 'integer'},
                                                                 'serie': {'type': 'string'}},
                                                  'required': ['centro', 'ejerci', 'serie', 'numdoc'],
                                                  'type': 'object'},
                                  'name': 'entrada_pedidos_relacionados'},
 'etiqueta_gestion': {'description': 'Almacen. Gestiona etiquetas con accion=listar, grabar o borrar. Listar admite '
                                     'codart opcional; grabar y borrar requieren codart.',
                      'inputSchema': {'properties': {'accion': {'default': 'listar',
                                                                'enum': ['listar', 'grabar', 'borrar'],
                                                                'type': 'string'},
                                                     'aumentar': {'type': 'boolean'},
                                                     'cantid': {'type': 'string'},
                                                     'codart': {'type': 'string'},
                                                     'descri': {'type': 'string'},
                                                     'imprimir': {'type': 'boolean'},
                                                     'modelo': {'type': 'integer'}},
                                      'type': 'object'},
                      'name': 'etiqueta_gestion'},
 'falta_gestion': {'description': 'Almacen. Gestiona faltas con accion=listar, grabar o borrar. centro es obligatorio; '
                                  'proveedor=0 en grabar permite resolverlo automaticamente.',
                   'inputSchema': {'properties': {'accion': {'default': 'listar',
                                                             'enum': ['listar', 'grabar', 'borrar'],
                                                             'type': 'string'},
                                                  'aumentar': {'type': 'boolean'},
                                                  'cantid': {'type': 'string'},
                                                  'centro': {'type': 'integer'},
                                                  'codart': {'type': 'string'},
                                                  'proveedor': {'description': 'Proveedor. En grabar puede ser 0 para '
                                                                               'resolucion automatica; en borrar es '
                                                                               'obligatorio.',
                                                                'type': 'integer'}},
                                   'required': ['centro'],
                                   'type': 'object'},
                   'name': 'falta_gestion'},
 'integracion_coinfer_stock': {'description': 'Integraciones. Consulta el stock Coinfer de un articulo desde la fuente '
                                              'configurada.',
                               'inputSchema': {'properties': {'codart': {'type': 'string'}},
                                               'required': ['codart'],
                                               'type': 'object'},
                               'name': 'integracion_coinfer_stock'},
 'mostrador_cobrar': {'description': 'Mostrador/caja. ESCRITURA. Genera ticket o factura y registra los cobros, '
                                     'efectos y riesgo correspondientes.',
                      'inputSchema': {'properties': {'autorizacion': {'default': '', 'type': 'string'},
                                                     'caja': {'type': 'integer'},
                                                     'centro': {'type': 'integer'},
                                                     'codcli': {'type': 'integer'},
                                                     'efectivo': {'default': '', 'type': ['string', 'number']},
                                                     'otros': {'default': '', 'type': ['string', 'number']},
                                                     'subcli': {'type': 'integer'},
                                                     'tarjeta': {'default': '', 'type': ['string', 'number']},
                                                     'texto': {'description': 'Lineas # con 14 campos separados por |.',
                                                               'type': 'string'},
                                                     'tipdoc': {'description': 'Normalmente T o F.', 'type': 'string'},
                                                     'total': {'type': ['string', 'number']},
                                                     'usuario': {'type': 'string'},
                                                     'venta': {'default': '',
                                                               'description': 'Venta abierta EJERCI-NUMDOC o vacio.',
                                                               'type': 'string'}},
                                      'required': ['caja',
                                                   'total',
                                                   'centro',
                                                   'codcli',
                                                   'subcli',
                                                   'texto',
                                                   'tipdoc',
                                                   'usuario'],
                                      'type': 'object'},
                      'name': 'mostrador_cobrar'},
 'mostrador_venta_gestion': {'description': 'Mostrador. Gestiona una venta abierta antes del cobro: accion=guardar '
                                            'crea/modifica, accion=borrar elimina y accion=cargar_pedido sirve un '
                                            'pedido creando la venta abierta.',
                             'inputSchema': {'properties': {'accion': {'enum': ['guardar', 'borrar', 'cargar_pedido'],
                                                                       'type': 'string'},
                                                            'centro': {'description': 'Obligatorio para cargar_pedido.',
                                                                       'type': 'integer'},
                                                            'codcli': {'description': 'Obligatorio para guardar.',
                                                                       'type': 'integer'},
                                                            'codigo_pedido': {'description': 'EJERCICIO-SERIE-NUMERO; '
                                                                                             'obligatorio para '
                                                                                             'cargar_pedido.',
                                                                              'type': 'string'},
                                                            'subcli': {'description': 'Obligatorio para guardar.',
                                                                       'type': 'integer'},
                                                            'texto': {'description': 'Lineas del contrato historico; '
                                                                                     'obligatorio en '
                                                                                     'guardar/cargar_pedido.',
                                                                      'type': 'string'},
                                                            'tipdoc': {'description': 'Tipo de venta/documento; '
                                                                                      'obligatorio en '
                                                                                      'guardar/cargar_pedido.',
                                                                       'type': 'string'},
                                                            'usuario': {'description': 'Obligatorio para guardar.',
                                                                        'type': 'string'},
                                                            'venta': {'description': 'Clave EJERCI-NUMDOC. En guardar '
                                                                                     'puede ir vacia para alta; '
                                                                                     'obligatoria al borrar.',
                                                                      'type': 'string'}},
                                             'required': ['accion'],
                                             'type': 'object'},
                             'name': 'mostrador_venta_gestion'},
 'pedido_albaranar': {'description': 'Pedidos. ESCRITURA. Convierte cantidades servidas de un pedido en albaran.',
                      'inputSchema': {'properties': {'centro': {'type': 'integer'},
                                                     'codigo_pedido': {'description': 'Clave del pedido en formato '
                                                                                      "'EJERCICIO-SERIE-NUMERO', p.ej. "
                                                                                      "'2026-PM-123'.",
                                                                       'type': 'string'},
                                                     'texto': {'description': "Lineas a servir separadas por '#', cada "
                                                                              "una 'NUMLIN|CODART|DESCRI|CANTID' "
                                                                              '(CODART y DESCRI se aceptan por '
                                                                              'fidelidad de formato pero se ignoran; '
                                                                              'solo importan NUMLIN y CANTID).',
                                                               'type': 'string'}},
                                      'required': ['centro', 'codigo_pedido', 'texto'],
                                      'type': 'object'},
                      'name': 'pedido_albaranar'},
 'pedido_cerrar': {'description': 'Pedidos. ESCRITURA. Cierra un pedido de cliente.',
                   'inputSchema': {'properties': {'centro': {'type': 'integer'},
                                                  'ejerci': {'type': 'integer'},
                                                  'numdoc': {'type': 'integer'},
                                                  'serie': {'type': 'string'},
                                                  'tipdoc': {'description': "Tipo de documento a cerrar (p.ej. 'P' "
                                                                            "Pedido, 'R' Presupuesto).",
                                                             'type': 'string'},
                                                  'usuario': {'description': 'Usuario que realiza el cierre '
                                                                             '(CBV_USUMOD).',
                                                              'type': 'string'}},
                                   'required': ['centro', 'tipdoc', 'ejerci', 'serie', 'numdoc'],
                                   'type': 'object'},
                   'name': 'pedido_cerrar'},
 'pedido_crear': {'description': 'Pedidos. ESCRITURA. Crea un pedido de cliente con sus lineas y valoracion comercial.',
                  'inputSchema': {'properties': {'centro': {'type': 'integer'},
                                                 'codcli': {'type': 'integer'},
                                                 'email': {'description': 'Aceptado por fidelidad de firma; el envio '
                                                                          'de correo no esta implementado.',
                                                           'type': 'string'},
                                                 'observaciones': {'description': 'Lineas de comentario separadas por '
                                                                                  'retorno de carro (\\r).',
                                                                   'type': 'string'},
                                                 'subcli': {'type': 'integer'},
                                                 'texto': {'description': "Lineas del pedido separadas por '#': "
                                                                          "'CODART|DESCRI|CANTID|PREVEN|DTO1'.",
                                                           'type': 'string'},
                                                 'urgente': {'description': "'R' crea un Presupuesto en vez de un "
                                                                            'Pedido.',
                                                             'type': 'string'}},
                                  'required': ['centro', 'codcli', 'subcli', 'texto'],
                                  'type': 'object'},
                  'name': 'pedido_crear'},
 'pedido_detalle': {'description': 'Pedidos. Devuelve el detalle normal del pedido o el detalle de preparacion/picking '
                                   'segun modo.',
                    'inputSchema': {'properties': {'centro': {'type': 'integer'},
                                                   'ejerci': {'type': 'integer'},
                                                   'modo': {'default': 'normal',
                                                            'enum': ['normal', 'preparacion'],
                                                            'type': 'string'},
                                                   'numdoc': {'type': 'integer'},
                                                   'serie': {'type': 'string'}},
                                    'required': ['centro', 'ejerci', 'serie', 'numdoc'],
                                    'type': 'object'},
                    'name': 'pedido_detalle'},
 'pedido_enviar': {'description': 'Pedidos. Genera el PDF de un pedido y lo envia por correo al destinatario indicado.',
                   'inputSchema': {'properties': {'centro': {'type': 'integer'},
                                                  'ejerci': {'type': 'integer'},
                                                  'email': {'type': 'string'},
                                                  'numdoc': {'type': 'integer'},
                                                  'serie': {'type': 'string'}},
                                   'required': ['centro', 'ejerci', 'serie', 'numdoc', 'email'],
                                   'type': 'object'},
                   'name': 'pedido_enviar'},
 'pedido_finalizar': {'description': 'Pedidos. ESCRITURA. Finaliza la preparacion de un pedido.',
                      'inputSchema': {'properties': {'centro': {'type': 'integer'},
                                                     'ejerci': {'type': 'integer'},
                                                     'numdoc': {'type': 'integer'},
                                                     'serie': {'type': 'string'},
                                                     'tipdoc': {'type': 'string'}},
                                      'required': ['centro', 'tipdoc', 'ejerci', 'serie', 'numdoc'],
                                      'type': 'object'},
                      'name': 'pedido_finalizar'},
 'pedido_linea_mover': {'description': 'Pedidos/almacen. ESCRITURA. Mueve una linea de pedido entre zonas de '
                                       'preparacion.',
                        'inputSchema': {'properties': {'cantid': {'description': 'Cantidad a mover.', 'type': 'string'},
                                                       'centro': {'type': 'integer'},
                                                       'codart': {'type': 'string'},
                                                       'descri': {'type': 'string'},
                                                       'linea': {'description': 'Clave de la linea: '
                                                                                "'CENTRO-TIPDOC-TIPAC-EJERCI-SERIE-NUMDOC-NUMLIN'.",
                                                                 'type': 'string'},
                                                       'ubi_destino': {'type': 'string'},
                                                       'ubi_origen': {'type': 'string'},
                                                       'zona_destino': {'type': 'integer'},
                                                       'zona_origen': {'type': 'integer'}},
                                        'required': ['centro',
                                                     'codart',
                                                     'cantid',
                                                     'linea',
                                                     'zona_origen',
                                                     'zona_destino'],
                                        'type': 'object'},
                        'name': 'pedido_linea_mover'},
 'pedido_listar': {'description': 'Pedidos. Lista el cuadro operativo del centro; si se indican codcli y subcli, lista '
                                  'el historico de pedidos de ese cliente.',
                   'inputSchema': {'properties': {'centro': {'type': 'integer'},
                                                  'codcli': {'type': 'integer'},
                                                  'subcli': {'type': 'integer'}},
                                   'required': ['centro'],
                                   'type': 'object'},
                   'name': 'pedido_listar'},
 'pedido_marcar_preparado': {'description': 'Pedidos/almacen. ESCRITURA. Registra cantidades preparadas de un pedido.',
                             'inputSchema': {'properties': {'centro': {'type': 'integer'},
                                                            'ejerci': {'type': 'integer'},
                                                            'numdoc': {'type': 'integer'},
                                                            'serie': {'type': 'string'},
                                                            'tipdoc': {'type': 'string'}},
                                             'required': ['centro', 'tipdoc', 'ejerci', 'serie', 'numdoc'],
                                             'type': 'object'},
                             'name': 'pedido_marcar_preparado'},
 'pedido_pdf_gestion': {'description': 'Pedidos. Genera o recupera el PDF historico de un pedido. accion=generar '
                                       'requiere centro; accion=obtener devuelve el PDF en Base64.',
                        'inputSchema': {'properties': {'accion': {'enum': ['generar', 'obtener'], 'type': 'string'},
                                                       'centro': {'description': 'Obligatorio cuando accion=generar.',
                                                                  'type': 'integer'},
                                                       'ejerci': {'type': 'integer'},
                                                       'numdoc': {'type': 'integer'},
                                                       'serie': {'type': 'string'}},
                                        'required': ['accion', 'ejerci', 'serie', 'numdoc'],
                                        'type': 'object'},
                        'name': 'pedido_pdf_gestion'},
 'pedido_retirada_actualizar': {'description': 'Pedidos. ESCRITURA. Actualiza el estado de retirada y la referencia de '
                                               'cliente de un pedido/documento.',
                                'inputSchema': {'properties': {'documento': {'type': 'string'},
                                                               'referencia': {'type': 'string'},
                                                               'retirado': {'type': 'string'}},
                                                'required': ['documento', 'retirado', 'referencia'],
                                                'type': 'object'},
                                'name': 'pedido_retirada_actualizar'},
 'pedido_situacion_actualizar': {'description': 'Pedidos. ESCRITURA. Actualiza la situacion de un pedido.',
                                 'inputSchema': {'properties': {'centro': {'type': 'integer'},
                                                                'ejerci': {'type': 'integer'},
                                                                'numdoc': {'type': 'integer'},
                                                                'serie': {'type': 'string'},
                                                                'situac': {'type': 'string'},
                                                                'tipdoc': {'type': 'string'}},
                                                 'required': ['situac',
                                                              'centro',
                                                              'tipdoc',
                                                              'ejerci',
                                                              'serie',
                                                              'numdoc'],
                                                 'type': 'object'},
                                 'name': 'pedido_situacion_actualizar'},
 'precio_tabla_listar': {'description': 'Precios. Lista las tablas de precio disponibles para la empresa configurada.',
                         'inputSchema': {'properties': {}, 'type': 'object'},
                         'name': 'precio_tabla_listar'},
 'proveedor_buscar': {'description': 'Proveedores. Busca proveedores con filtros tipados y devuelve todos los datos '
                                     'del maestro PROVEE. Si se indica solo codigo devuelve la ficha detallada; en '
                                     'otro caso devuelve un listado filtrado.',
                      'inputSchema': {'properties': {'cif': {'type': 'string'},
                                                     'codpro': {'description': 'Codigo de proveedor (PRO_CODPRO).',
                                                                'type': 'integer'},
                                                     'fecha_alta': {'description': 'Fecha de alta exacta (PRO_FEALTA), formato YYYY-MM-DD.',
                                                                    'type': 'string'},
                                                     'fecha_alta_desde': {'description': 'Fecha de alta minima incluida, formato YYYY-MM-DD.',
                                                                          'type': 'string'},
                                                     'fecha_alta_hasta': {'description': 'Fecha de alta maxima incluida, formato YYYY-MM-DD.',
                                                                          'type': 'string'},
                                                     'limit': {'description': 'Maximo de filas; por defecto 500.',
                                                               'type': 'integer'},
                                                     'nombre_abreviado_like': {'type': 'string'},
                                                     'nombre_comercial_like': {'type': 'string'},
                                                     'nombre_fiscal_like': {'type': 'string'}},
                                      'type': 'object'},
                      'name': 'proveedor_buscar'},
 'recuento_gestion': {'description': 'Almacen. Gestiona recuentos con accion=listar, grabar o borrar. centro es '
                                     'obligatorio; listar admite codart opcional.',
                      'inputSchema': {'properties': {'accion': {'default': 'listar',
                                                                'enum': ['listar', 'grabar', 'borrar'],
                                                                'type': 'string'},
                                                     'aumentar': {'type': 'boolean'},
                                                     'cantid': {'type': 'string'},
                                                     'centro': {'type': 'integer'},
                                                     'codart': {'type': 'string'},
                                                     'descri': {'type': 'string'},
                                                     'unimed': {'type': 'string'}},
                                      'required': ['centro'],
                                      'type': 'object'},
                      'name': 'recuento_gestion'},
 'stock_consultar': {'description': 'Stock. Consulta existencias de un articulo. Si se indica centro devuelve ese '
                                    'centro; si se omite devuelve todos los centros.',
                     'inputSchema': {'properties': {'centro': {'type': 'integer'}, 'codart': {'type': 'string'}},
                                     'required': ['codart'],
                                     'type': 'object'},
                     'name': 'stock_consultar'},
 'stock_regularizar': {'description': 'Stock. ESCRITURA. Regulariza las existencias de un articulo en un centro hasta '
                                      'la cantidad final indicada.',
                       'inputSchema': {'properties': {'cantid': {'description': 'Existencia final contada. La funcion '
                                                                                'calcula diferencia contra stock '
                                                                                'actual.',
                                                                 'type': 'string'},
                                                      'centro': {'type': 'integer'},
                                                      'codart': {'type': 'string'},
                                                      'descri': {'type': 'string'},
                                                      'unimed': {'type': 'string'}},
                                       'required': ['codart', 'centro', 'descri', 'unimed', 'cantid'],
                                       'type': 'object'},
                       'name': 'stock_regularizar'},
 'stock_trasvasar': {'description': 'Stock. ESCRITURA. Trasvasa articulos entre centros y genera los movimientos '
                                    'origen/destino.',
                     'inputSchema': {'properties': {'centrod': {'description': 'Centro destino.', 'type': 'integer'},
                                                    'centroo': {'description': 'Centro origen.', 'type': 'integer'},
                                                    'texto': {'description': 'Lineas en formato '
                                                                             'CODART|DESCRI|CANTID|UNIMED#...',
                                                              'type': 'string'}},
                                     'required': ['centroo', 'centrod', 'texto'],
                                     'type': 'object'},
                     'name': 'stock_trasvasar'},
 'venta_documento_crear': {'description': 'Ventas. ESCRITURA. Crea un documento de venta (albaran o factura, segun '
                                          'tipdoc) desde lineas o desde una venta abierta.',
                           'inputSchema': {'properties': {'centro': {'type': 'integer'},
                                                          'codcli': {'type': 'integer'},
                                                          'serie': {'default': '',
                                                                    'description': 'Serie del documento. Si se deja vacia se calcula automaticamente.',
                                                                    'type': 'string'},
                                                          'subcli': {'type': 'integer'},
                                                          'texto': {'description': 'Lineas # con 14 campos separados '
                                                                                   'por |.',
                                                                    'type': 'string'},
                                                          'tipdoc': {'type': 'string'},
                                                          'usuario': {'type': 'string'},
                                                          'venta': {'default': '',
                                                                    'description': 'Venta abierta EJERCI-NUMDOC o '
                                                                                   'vacio.',
                                                                    'type': 'string'}},
                                           'required': ['centro', 'codcli', 'subcli', 'texto', 'tipdoc', 'usuario'],
                                           'type': 'object'},
                           'name': 'venta_documento_crear'},
 'venta_documentos_abc': {'description': 'Ventas/ANADOC. LECTURA. Genera un analisis ABC de ventas sin duplicar '
                                         'documentos: por defecto cuenta facturas y creditos, y solo albaranes '
                                         'pendientes no facturados.',
                          'inputSchema': {'properties': {'agrupar_por': {'default': 'cliente',
                                                                         'enum': sorted(SALE_DOCUMENT_GROUP_FIELDS),
                                                                         'type': 'string'},
                                                         'centro': {'type': 'integer'},
                                                         'cliente_desde': {'type': 'integer'},
                                                         'cliente_hasta': {'type': 'integer'},
                                                         'fecha_desde': {'type': 'string'},
                                                         'fecha_hasta': {'type': 'string'},
                                                         'limite': {'default': 10000,
                                                                    'description': 'Maximo de documentos base a analizar, hasta 10000.',
                                                                    'type': 'integer'},
                                                         'limite_grupos': {'type': 'integer'},
                                                         'moneda': {'default': 'E',
                                                                    'enum': ['E', 'P'],
                                                                    'type': 'string'},
                                                         'politica': {'default': 'ventas_reales',
                                                                      'enum': ['ventas_reales', 'documentos'],
                                                                      'type': 'string'},
                                                         'representante': {'type': 'integer'},
                                                         'situacion': {'type': 'string'},
                                                         'subcliente_desde': {'type': 'integer'},
                                                         'subcliente_hasta': {'type': 'integer'},
                                                         'tarjeta': {'type': 'string'},
                                                         'tipos_documento': {'items': {'enum': ['T', 'A', 'F', 'C', 'P', 'R', 'S'],
                                                                                       'type': 'string'},
                                                                             'type': 'array'},
                                                         'umbral_a': {'default': '80',
                                                                      'type': 'string'},
                                                         'umbral_b': {'default': '95',
                                                                      'type': 'string'},
                                                         'zona_desde': {'type': 'integer'},
                                                         'zona_hasta': {'type': 'integer'}},
                                          'required': ['fecha_desde', 'fecha_hasta'],
                                          'type': 'object'},
                          'name': 'venta_documentos_abc'},
 'venta_documentos_detalle': {'description': 'Ventas/ANADOC. LECTURA. Lista cabeceras de venta en un periodo con '
                                             'totales y categoria de documento. La politica ventas_reales evita '
                                             'duplicar tickets/albaranes facturados y excluye pedidos/presupuestos.',
                              'inputSchema': {'properties': {'centro': {'type': 'integer'},
                                                             'cliente_desde': {'type': 'integer'},
                                                             'cliente_hasta': {'type': 'integer'},
                                                             'fecha_desde': {'type': 'string'},
                                                             'fecha_hasta': {'type': 'string'},
                                                             'limite': {'default': 500,
                                                                        'description': 'Maximo de documentos a devolver, hasta 10000.',
                                                                        'type': 'integer'},
                                                             'moneda': {'default': 'E',
                                                                        'enum': ['E', 'P'],
                                                                        'type': 'string'},
                                                             'numero_desde': {'type': 'integer'},
                                                             'numero_hasta': {'type': 'integer'},
                                                             'politica': {'default': 'ventas_reales',
                                                                          'enum': ['ventas_reales', 'documentos'],
                                                                          'type': 'string'},
                                                             'representante': {'type': 'integer'},
                                                             'serie_desde': {'type': 'string'},
                                                             'serie_hasta': {'type': 'string'},
                                                             'situacion': {'type': 'string'},
                                                             'subcliente_desde': {'type': 'integer'},
                                                             'subcliente_hasta': {'type': 'integer'},
                                                             'tarjeta': {'type': 'string'},
                                                             'tipo_acumulado': {'default': '0',
                                                                                'description': 'CBV_TIPAC; usar 9 para no filtrar.',
                                                                                'type': 'string'},
                                                             'tipos_documento': {'description': 'Tipos documentales. En ventas_reales se omiten T/P/R/S para no duplicar o anticipar ventas.',
                                                                                 'items': {'enum': ['T', 'A', 'F', 'C', 'P', 'R', 'S'],
                                                                                           'type': 'string'},
                                                                                 'type': 'array'},
                                                             'zona_desde': {'type': 'integer'},
                                                             'zona_hasta': {'type': 'integer'}},
                                              'required': ['fecha_desde', 'fecha_hasta'],
                                              'type': 'object'},
                              'name': 'venta_documentos_detalle'},
 'venta_documentos_resumen': {'description': 'Ventas/ANADOC. LECTURA. Resume documentos de venta por cliente, '
                                            'ejercicio, tipo, categoria, centro, mes, trimestre u otras dimensiones '
                                            'con politica antiduplicado por defecto.',
                             'inputSchema': {'properties': {'agrupar_por': {'default': 'cliente',
                                                                            'enum': sorted(SALE_DOCUMENT_GROUP_FIELDS),
                                                                            'type': 'string'},
                                                            'centro': {'type': 'integer'},
                                                            'cliente_desde': {'type': 'integer'},
                                                            'cliente_hasta': {'type': 'integer'},
                                                            'fecha_desde': {'type': 'string'},
                                                            'fecha_hasta': {'type': 'string'},
                                                            'limite': {'default': 10000,
                                                                       'type': 'integer'},
                                                            'limite_grupos': {'type': 'integer'},
                                                            'moneda': {'default': 'E',
                                                                       'enum': ['E', 'P'],
                                                                       'type': 'string'},
                                                            'ordenar_por': {'default': 'total',
                                                                            'enum': ['base_imponible', 'iva', 'recargo', 'total', 'cobrado', 'pendiente', 'documentos'],
                                                                            'type': 'string'},
                                                            'politica': {'default': 'ventas_reales',
                                                                         'enum': ['ventas_reales', 'documentos'],
                                                                         'type': 'string'},
                                                            'representante': {'type': 'integer'},
                                                            'sentido': {'default': 'desc',
                                                                        'enum': ['asc', 'desc'],
                                                                        'type': 'string'},
                                                            'situacion': {'type': 'string'},
                                                            'subcliente_desde': {'type': 'integer'},
                                                            'subcliente_hasta': {'type': 'integer'},
                                                            'tarjeta': {'type': 'string'},
                                                            'tipos_documento': {'items': {'enum': ['T', 'A', 'F', 'C', 'P', 'R', 'S'],
                                                                                          'type': 'string'},
                                                                                'type': 'array'},
                                                            'zona_desde': {'type': 'integer'},
                                                            'zona_hasta': {'type': 'integer'}},
                                             'required': ['fecha_desde', 'fecha_hasta'],
                                             'type': 'object'},
                             'name': 'venta_documentos_resumen'},
 'negocio_cuadro_mando': {'description': 'Cuadro de mando. LECTURA. Resume en una sola respuesta ventas, margen, '
                                         'rentabilidad, clientes en riesgo y stock/rotacion para una vision ejecutiva '
                                         'del negocio.',
                          'inputSchema': {'properties': {'agrupar_por': {'default': 'familia',
                                                                         'enum': sorted(SALE_PROFIT_GROUP_FIELDS),
                                                                         'type': 'string'},
                                                         'articulo_desde': {'type': 'string'},
                                                         'articulo_hasta': {'type': 'string'},
                                                         'centro': {'type': 'integer'},
                                                         'cliente_desde': {'type': 'integer'},
                                                         'cliente_hasta': {'type': 'integer'},
                                                         'comparar_fecha_desde': {'description': 'Fecha inicial del periodo comparativo. Si se omite, se usa el periodo anterior equivalente.',
                                                                                  'type': 'string'},
                                                         'comparar_fecha_hasta': {'description': 'Fecha final del periodo comparativo. Si se omite, se usa el periodo anterior equivalente.',
                                                                                 'type': 'string'},
                                                         'descripcion': {'type': 'string'},
                                                         'dias_cobertura_alta': {'default': '180',
                                                                                  'type': ['number', 'string']},
                                                         'dias_sin_vender_alerta': {'default': 180,
                                                                                     'type': 'integer'},
                                                         'fecha_desde': {'description': 'Fecha inicial del periodo actual en formato YYYY-MM-DD.',
                                                                         'type': 'string'},
                                                         'fecha_hasta': {'description': 'Fecha final del periodo actual en formato YYYY-MM-DD.',
                                                                        'type': 'string'},
                                                         'incluir_pedidos': {'default': False,
                                                                             'type': 'boolean'},
                                                         'limite': {'default': 3000,
                                                                    'description': 'Maximo de lineas base a analizar por bloque.',
                                                                    'type': 'integer'},
                                                         'limite_alertas': {'default': 10,
                                                                            'description': 'Maximo de elementos por bloque ejecutivo.',
                                                                            'type': 'integer'},
                                                         'moneda': {'default': 'E',
                                                                    'enum': ['E', 'P'],
                                                                    'type': 'string'},
                                                         'proveedor_desde': {'type': 'integer'},
                                                         'proveedor_hasta': {'type': 'integer'},
                                                         'representante': {'type': 'integer'},
                                                         'solo_con_stock': {'default': True,
                                                                            'type': 'boolean'},
                                                         'solo_en_oferta': {'default': False,
                                                                            'type': 'boolean'},
                                                         'stock_minimo': {'default': '0',
                                                                          'type': ['number', 'string']},
                                                         'subcliente_desde': {'type': 'integer'},
                                                         'subcliente_hasta': {'type': 'integer'},
                                                         'tipo_familia': {'default': 'ncc',
                                                                          'description': 'Origen de familia al agrupar por familia/subfamilia: ncc, propia o cooperativa.',
                                                                          'enum': sorted(SALE_FAMILY_TYPES),
                                                                          'type': 'string'},
                                                         'tipos_documento': {'items': {'enum': ['T', 'F', 'A', 'C', 'P', 'R', 'S'],
                                                                                       'type': 'string'},
                                                                             'type': 'array'},
                                                         'umbral_rentabilidad_baja': {'default': '10',
                                                                                      'type': ['number', 'string']},
                                                         'umbral_variacion_pct': {'default': '10',
                                                                                   'type': ['number', 'string']}},
                                          'required': ['fecha_desde', 'fecha_hasta'],
                                          'type': 'object'},
                          'name': 'negocio_cuadro_mando'},
 'negocio_clientes_riesgo': {'description': 'Cuadro de mando. LECTURA. Analiza clientes en riesgo comparando ventas '
                                            'y rentabilidad entre periodos: clientes que bajan, desaparecen, empeoran '
                                            'margen, tienen rentabilidad negativa o concentran demasiada venta.',
                             'inputSchema': {'properties': {'articulo_desde': {'type': 'string'},
                                                            'articulo_hasta': {'type': 'string'},
                                                            'centro': {'type': 'integer'},
                                                            'cliente_desde': {'type': 'integer'},
                                                            'cliente_hasta': {'type': 'integer'},
                                                            'comparar_fecha_desde': {'description': 'Fecha inicial del periodo comparativo. Si se omite, se usa el periodo anterior equivalente.',
                                                                                     'type': 'string'},
                                                            'comparar_fecha_hasta': {'description': 'Fecha final del periodo comparativo. Si se omite, se usa el periodo anterior equivalente.',
                                                                                    'type': 'string'},
                                                            'descripcion': {'type': 'string'},
                                                            'fecha_desde': {'description': 'Fecha inicial del periodo actual en formato YYYY-MM-DD.',
                                                                            'type': 'string'},
                                                            'fecha_hasta': {'description': 'Fecha final del periodo actual en formato YYYY-MM-DD.',
                                                                           'type': 'string'},
                                                            'incluir_pedidos': {'default': False,
                                                                                'type': 'boolean'},
                                                            'limite': {'default': 5000,
                                                                       'description': 'Maximo de lineas base a analizar por periodo, hasta 5000.',
                                                                       'type': 'integer'},
                                                            'limite_alertas': {'default': 50,
                                                                               'description': 'Maximo de clientes devueltos por bloque.',
                                                                               'type': 'integer'},
                                                            'moneda': {'default': 'E',
                                                                       'enum': ['E', 'P'],
                                                                       'type': 'string'},
                                                            'proveedor_desde': {'type': 'integer'},
                                                            'proveedor_hasta': {'type': 'integer'},
                                                            'representante': {'type': 'integer'},
                                                            'solo_en_oferta': {'default': False,
                                                                               'type': 'boolean'},
                                                            'subcliente_desde': {'type': 'integer'},
                                                            'subcliente_hasta': {'type': 'integer'},
                                                            'tipos_documento': {'items': {'enum': ['T', 'F', 'A', 'C', 'P', 'R', 'S'],
                                                                                          'type': 'string'},
                                                                                'type': 'array'},
                                                            'venta_minima': {'default': '0',
                                                                             'description': 'Venta minima actual o comparativa para incluir el cliente en el analisis.',
                                                                             'type': ['number', 'string']}},
                                             'required': ['fecha_desde', 'fecha_hasta'],
                                             'type': 'object'},
                             'name': 'negocio_clientes_riesgo'},
 'negocio_stock_rotacion': {'description': 'Cuadro de mando. LECTURA. Analiza stock actual, valor inmovilizado, '
                                           'ventas, compras y rotacion por articulo o familia para detectar stock sin '
                                           'ventas, sobrestock, baja rotacion y compras sin salida.',
                            'inputSchema': {'properties': {'agrupar_por': {'default': 'familia',
                                                                           'enum': sorted(SALE_PROFIT_GROUP_FIELDS),
                                                                           'type': 'string'},
                                                           'articulo_desde': {'type': 'string'},
                                                           'articulo_hasta': {'type': 'string'},
                                                           'centro': {'type': 'integer'},
                                                           'cliente_desde': {'type': 'integer'},
                                                           'cliente_hasta': {'type': 'integer'},
                                                           'descripcion': {'type': 'string'},
                                                           'dias_cobertura_alta': {'default': '180',
                                                                                    'description': 'Dias de cobertura a partir de los cuales se marca sobrestock.',
                                                                                    'type': ['number', 'string']},
                                                           'dias_sin_vender_alerta': {'default': 180,
                                                                                       'description': 'Dias sin venta a partir de los cuales se marca baja_rotacion.',
                                                                                       'type': 'integer'},
                                                           'fecha_desde': {'description': 'Fecha inicial del periodo de ventas/compras en formato YYYY-MM-DD.',
                                                                           'type': 'string'},
                                                           'fecha_hasta': {'description': 'Fecha final del periodo de ventas/compras en formato YYYY-MM-DD.',
                                                                          'type': 'string'},
                                                           'incluir_pedidos': {'default': False,
                                                                               'type': 'boolean'},
                                                           'limite': {'default': 5000,
                                                                      'description': 'Maximo de filas de stock base a analizar, hasta 10000.',
                                                                      'type': 'integer'},
                                                           'limite_detalle': {'default': 50,
                                                                              'description': 'Maximo de grupos/articulos devueltos por bloque.',
                                                                              'type': 'integer'},
                                                           'moneda': {'default': 'E',
                                                                      'enum': ['E', 'P'],
                                                                      'type': 'string'},
                                                           'proveedor_desde': {'type': 'integer'},
                                                           'proveedor_hasta': {'type': 'integer'},
                                                           'representante': {'type': 'integer'},
                                                           'solo_con_stock': {'default': True,
                                                                              'type': 'boolean'},
                                                           'solo_en_oferta': {'default': False,
                                                                              'type': 'boolean'},
                                                           'stock_minimo': {'default': '0',
                                                                            'type': ['number', 'string']},
                                                           'subcliente_desde': {'type': 'integer'},
                                                           'subcliente_hasta': {'type': 'integer'},
                                                           'tipo_familia': {'default': 'ncc',
                                                                            'description': 'Origen de familia al agrupar por familia/subfamilia: ncc usa FAMNC/FAMNCC, propia usa ART_CODFAM/ART_SUBFAM y cooperativa usa ART_AGRUP1/2/3.',
                                                                            'enum': sorted(SALE_FAMILY_TYPES),
                                                                            'type': 'string'},
                                                           'tipos_documento': {'items': {'enum': ['T', 'F', 'A', 'C', 'P', 'R', 'S'],
                                                                                         'type': 'string'},
                                                                               'type': 'array'}},
                                            'required': ['fecha_desde', 'fecha_hasta'],
                                            'type': 'object'},
                            'name': 'negocio_stock_rotacion'},
 'negocio_stock_tendencias': {'description': 'Cuadro de mando. LECTURA. Compara dos periodos de stock/ventas/compras '
                                             'para detectar articulos donde sube el stock mientras bajan ventas o margen.',
                              'inputSchema': {'properties': {'articulo_desde': {'type': 'string'},
                                                             'articulo_hasta': {'type': 'string'},
                                                             'centro': {'type': 'integer'},
                                                             'cliente_desde': {'type': 'integer'},
                                                             'cliente_hasta': {'type': 'integer'},
                                                             'comparar_fecha_desde': {'description': 'Fecha inicial del periodo comparativo. Si se omite, se usa el periodo anterior equivalente.',
                                                                                      'type': 'string'},
                                                             'comparar_fecha_hasta': {'description': 'Fecha final del periodo comparativo. Si se omite, se usa el periodo anterior equivalente.',
                                                                                     'type': 'string'},
                                                             'descripcion': {'type': 'string'},
                                                             'dias_cobertura_alta': {'default': '180',
                                                                                      'type': ['number', 'string']},
                                                             'dias_sin_vender_alerta': {'default': 180,
                                                                                         'type': 'integer'},
                                                             'fecha_desde': {'description': 'Fecha inicial del periodo actual en formato YYYY-MM-DD.',
                                                                             'type': 'string'},
                                                             'fecha_hasta': {'description': 'Fecha final del periodo actual en formato YYYY-MM-DD.',
                                                                            'type': 'string'},
                                                             'incluir_pedidos': {'default': False,
                                                                                 'type': 'boolean'},
                                                             'limite': {'default': 5000,
                                                                        'description': 'Maximo de filas de stock base a analizar por periodo, hasta 10000.',
                                                                        'type': 'integer'},
                                                             'limite_detalle': {'default': 50,
                                                                                'description': 'Maximo de articulos devueltos por bloque.',
                                                                                'type': 'integer'},
                                                             'moneda': {'default': 'E',
                                                                        'enum': ['E', 'P'],
                                                                        'type': 'string'},
                                                             'proveedor_desde': {'type': 'integer'},
                                                             'proveedor_hasta': {'type': 'integer'},
                                                             'representante': {'type': 'integer'},
                                                             'solo_con_stock': {'default': True,
                                                                                'type': 'boolean'},
                                                             'solo_en_oferta': {'default': False,
                                                                                'type': 'boolean'},
                                                             'stock_minimo': {'default': '0',
                                                                              'type': ['number', 'string']},
                                                             'subcliente_desde': {'type': 'integer'},
                                                             'subcliente_hasta': {'type': 'integer'},
                                                             'tipo_familia': {'default': 'ncc',
                                                                              'description': 'Origen de familia: ncc, propia o cooperativa.',
                                                                              'enum': sorted(SALE_FAMILY_TYPES),
                                                                              'type': 'string'},
                                                             'tipos_documento': {'items': {'enum': ['T', 'F', 'A', 'C', 'P', 'R', 'S'],
                                                                                           'type': 'string'},
                                                                                 'type': 'array'}},
                                              'required': ['fecha_desde', 'fecha_hasta'],
                                              'type': 'object'},
                              'name': 'negocio_stock_tendencias'},
 'negocio_diagnostico_cambios': {'description': 'Cuadro de mando. LECTURA. Diagnostica por que cambian ventas o margen '
                                                'entre dos periodos, opcionalmente enfocado en una familia, articulo, '
                                                'cliente u otra dimension, desglosando articulos, clientes, unidades, '
                                                'precio medio, coste medio y lineas negativas.',
                                 'inputSchema': {'properties': {'agrupar_por': {'default': 'familia',
                                                                                'enum': sorted(SALE_PROFIT_GROUP_FIELDS),
                                                                                'type': 'string'},
                                                                'articulo_desde': {'type': 'string'},
                                                                'articulo_hasta': {'type': 'string'},
                                                                'centro': {'type': 'integer'},
                                                                'cliente_desde': {'type': 'integer'},
                                                                'cliente_hasta': {'type': 'integer'},
                                                                'codigo_grupo': {'description': 'Codigo del grupo a diagnosticar segun agrupar_por. Si se omite, diagnostica todo el conjunto filtrado.',
                                                                                 'type': 'string'},
                                                                'comparar_fecha_desde': {'description': 'Fecha inicial del periodo comparativo. Si se omite, se usa el periodo anterior equivalente.',
                                                                                         'type': 'string'},
                                                                'comparar_fecha_hasta': {'description': 'Fecha final del periodo comparativo. Si se omite, se usa el periodo anterior equivalente.',
                                                                                        'type': 'string'},
                                                                'descripcion': {'type': 'string'},
                                                                'fecha_desde': {'description': 'Fecha inicial del periodo actual en formato YYYY-MM-DD.',
                                                                                'type': 'string'},
                                                                'fecha_hasta': {'description': 'Fecha final del periodo actual en formato YYYY-MM-DD.',
                                                                               'type': 'string'},
                                                                'incluir_pedidos': {'default': False,
                                                                                    'type': 'boolean'},
                                                                'limite': {'default': 5000,
                                                                           'description': 'Maximo de lineas base a analizar por periodo, hasta 5000.',
                                                                           'type': 'integer'},
                                                                'limite_detalle': {'default': 20,
                                                                                   'description': 'Maximo de articulos, clientes y lineas negativas devueltas.',
                                                                                   'type': 'integer'},
                                                                'moneda': {'default': 'E',
                                                                           'enum': ['E', 'P'],
                                                                           'type': 'string'},
                                                                'proveedor_desde': {'type': 'integer'},
                                                                'proveedor_hasta': {'type': 'integer'},
                                                                'representante': {'type': 'integer'},
                                                                'solo_en_oferta': {'default': False,
                                                                                   'type': 'boolean'},
                                                                'subcliente_desde': {'type': 'integer'},
                                                                'subcliente_hasta': {'type': 'integer'},
                                                                'tipo_familia': {'default': 'ncc',
                                                                                 'description': 'Origen de familia al agrupar por familia/subfamilia: ncc usa FAMNC/FAMNCC, propia usa ART_CODFAM/ART_SUBFAM y cooperativa usa ART_AGRUP1/2/3.',
                                                                                 'enum': sorted(SALE_FAMILY_TYPES),
                                                                                 'type': 'string'},
                                                                'tipos_documento': {'items': {'enum': ['T', 'F', 'A', 'C', 'P', 'R', 'S'],
                                                                                              'type': 'string'},
                                                                                    'type': 'array'}},
                                                 'required': ['fecha_desde', 'fecha_hasta'],
                                                 'type': 'object'},
                                 'name': 'negocio_diagnostico_cambios'},
 'negocio_tendencias': {'description': 'Cuadro de mando. LECTURA. Compara ventas y rentabilidad por articulo, familia, '
                                       'cliente u otra dimension entre un periodo actual y uno comparativo, detectando '
                                       'subidas, bajadas, grupos nuevos, grupos desaparecidos y deterioros de margen.',
                        'inputSchema': {'properties': {'agrupar_por': {'default': 'familia',
                                                                       'enum': sorted(SALE_PROFIT_GROUP_FIELDS),
                                                                       'type': 'string'},
                                                       'articulo_desde': {'type': 'string'},
                                                       'articulo_hasta': {'type': 'string'},
                                                       'centro': {'type': 'integer'},
                                                       'cliente_desde': {'type': 'integer'},
                                                       'cliente_hasta': {'type': 'integer'},
                                                       'comparar_fecha_desde': {'description': 'Fecha inicial del periodo comparativo. Si se omite, se usa el periodo anterior equivalente.',
                                                                                'type': 'string'},
                                                       'comparar_fecha_hasta': {'description': 'Fecha final del periodo comparativo. Si se omite, se usa el periodo anterior equivalente.',
                                                                               'type': 'string'},
                                                       'descripcion': {'type': 'string'},
                                                       'fecha_desde': {'description': 'Fecha inicial del periodo actual en formato YYYY-MM-DD.',
                                                                       'type': 'string'},
                                                       'fecha_hasta': {'description': 'Fecha final del periodo actual en formato YYYY-MM-DD.',
                                                                      'type': 'string'},
                                                       'incluir_pedidos': {'default': False,
                                                                           'type': 'boolean'},
                                                       'limite': {'default': 5000,
                                                                  'description': 'Maximo de lineas base a analizar por periodo, hasta 5000.',
                                                                  'type': 'integer'},
                                                       'limite_alertas': {'default': 20,
                                                                          'description': 'Maximo de elementos devueltos por bloque de tendencias.',
                                                                          'type': 'integer'},
                                                       'moneda': {'default': 'E',
                                                                  'enum': ['E', 'P'],
                                                                  'type': 'string'},
                                                       'proveedor_desde': {'type': 'integer'},
                                                       'proveedor_hasta': {'type': 'integer'},
                                                       'representante': {'type': 'integer'},
                                                       'solo_en_oferta': {'default': False,
                                                                          'type': 'boolean'},
                                                       'subcliente_desde': {'type': 'integer'},
                                                       'subcliente_hasta': {'type': 'integer'},
                                                       'tipo_familia': {'default': 'ncc',
                                                                        'description': 'Origen de familia al agrupar por familia/subfamilia: ncc usa FAMNC/FAMNCC, propia usa ART_CODFAM/ART_SUBFAM y cooperativa usa ART_AGRUP1/2/3.',
                                                                        'enum': sorted(SALE_FAMILY_TYPES),
                                                                        'type': 'string'},
                                                       'tipos_documento': {'items': {'enum': ['T', 'F', 'A', 'C', 'P', 'R', 'S'],
                                                                                     'type': 'string'},
                                                                           'type': 'array'},
                                                       'umbral_variacion_pct': {'default': '10',
                                                                                 'description': 'Variacion porcentual minima para clasificar subidas o bajadas.',
                                                                                 'type': ['number', 'string']}},
                                        'required': ['fecha_desde', 'fecha_hasta'],
                                        'type': 'object'},
                        'name': 'negocio_tendencias'},
 'venta_alertas_rentabilidad': {'description': 'Ventas/rentabilidad. LECTURA. Detecta alertas estilo ANAVEN: '
                                               'lineas negativas, articulos con alguna linea negativa, articulos '
                                               'negativos agregados y grupos bajo umbral.',
                                'inputSchema': {'properties': {'articulo_desde': {'type': 'string'},
                                                               'articulo_hasta': {'type': 'string'},
                                                               'centro': {'type': 'integer'},
                                                               'cliente_desde': {'type': 'integer'},
                                                               'cliente_hasta': {'type': 'integer'},
                                                               'descripcion': {'type': 'string'},
                                                               'fecha_desde': {'description': 'Fecha inicial en formato YYYY-MM-DD.',
                                                                               'type': 'string'},
                                                               'fecha_hasta': {'description': 'Fecha final en formato YYYY-MM-DD.',
                                                                               'type': 'string'},
                                                               'incluir_pedidos': {'default': False,
                                                                                   'type': 'boolean'},
                                                               'limite': {'default': 5000,
                                                                          'description': 'Maximo de lineas base a analizar, hasta 5000.',
                                                                          'type': 'integer'},
                                                               'limite_alertas': {'default': 50,
                                                                                  'description': 'Maximo de elementos devueltos por bloque de alertas.',
                                                                                  'type': 'integer'},
                                                               'moneda': {'default': 'E',
                                                                          'enum': ['E', 'P'],
                                                                          'type': 'string'},
                                                               'proveedor_desde': {'type': 'integer'},
                                                               'proveedor_hasta': {'type': 'integer'},
                                                               'representante': {'type': 'integer'},
                                                               'solo_en_oferta': {'default': False,
                                                                                  'type': 'boolean'},
                                                               'subcliente_desde': {'type': 'integer'},
                                                               'subcliente_hasta': {'type': 'integer'},
                                                               'tipo_familia': {'default': 'ncc',
                                                                                'description': 'Origen de familia para familias_bajo_umbral: ncc usa FAMNC/FAMNCC, propia usa ART_CODFAM/ART_SUBFAM y cooperativa usa ART_AGRUP1/2/3.',
                                                                                'enum': sorted(SALE_FAMILY_TYPES),
                                                                                'type': 'string'},
                                                               'tipos_documento': {'items': {'enum': ['T', 'F', 'A', 'C', 'P', 'R', 'S'],
                                                                                             'type': 'string'},
                                                                                   'type': 'array'},
                                                               'umbral_rentabilidad_baja': {'default': '10',
                                                                                            'description': 'Porcentaje minimo aceptable para clasificar baja rentabilidad.',
                                                                                            'type': ['number', 'string']}},
                                                'required': ['fecha_desde', 'fecha_hasta'],
                                                'type': 'object'},
                                'name': 'venta_alertas_rentabilidad'},
 'venta_rentabilidad_lineas': {'description': 'Ventas/rentabilidad. LECTURA. Devuelve lineas de venta en un rango de '
                                              'fechas con coste, margen y rentabilidad calculados con la misma regla '
                                              'de coste que Faro/ANAVEN.',
                               'inputSchema': {'properties': {'articulo_desde': {'type': 'string'},
                                                              'articulo_hasta': {'type': 'string'},
                                                              'centro': {'type': 'integer'},
                                                              'cliente_desde': {'type': 'integer'},
                                                              'cliente_hasta': {'type': 'integer'},
                                                              'descripcion': {'description': 'Texto a buscar en la descripcion de la linea.',
                                                                              'type': 'string'},
                                                              'fecha_desde': {'description': 'Fecha inicial en formato YYYY-MM-DD.',
                                                                              'type': 'string'},
                                                              'fecha_hasta': {'description': 'Fecha final en formato YYYY-MM-DD.',
                                                                              'type': 'string'},
                                                              'incluir_pedidos': {'default': False,
                                                                                  'description': 'Incluye documentos no firmados y pedidos/presupuestos si se solicitan.',
                                                                                  'type': 'boolean'},
                                                              'limite': {'default': 500,
                                                                         'description': 'Maximo de lineas a devolver, hasta 5000.',
                                                                         'type': 'integer'},
                                                              'moneda': {'default': 'E',
                                                                         'description': 'Moneda de calculo: E euros, P pesetas.',
                                                                         'enum': ['E', 'P'],
                                                                         'type': 'string'},
                                                              'proveedor_desde': {'type': 'integer'},
                                                              'proveedor_hasta': {'type': 'integer'},
                                                              'representante': {'type': 'integer'},
                                                              'solo_en_oferta': {'default': False,
                                                                                 'type': 'boolean'},
                                                              'subcliente_desde': {'type': 'integer'},
                                                              'subcliente_hasta': {'type': 'integer'},
                                                              'tipos_documento': {'description': 'Tipos de venta: T tickets, F facturas, A albaranes, C creditos, P pedidos, R presupuestos, S servicios.',
                                                                                  'items': {'enum': ['T', 'F', 'A', 'C', 'P', 'R', 'S'],
                                                                                            'type': 'string'},
                                                                                  'type': 'array'}},
                                               'required': ['fecha_desde', 'fecha_hasta'],
                                               'type': 'object'},
                               'name': 'venta_rentabilidad_lineas'},
 'venta_rentabilidad_resumen': {'description': 'Ventas/rentabilidad. LECTURA. Resume las lineas de venta por articulo, '
                                               'familia, seccion, proveedor, cliente, mes u otras dimensiones para '
                                               'analisis de margen.',
                                'inputSchema': {'properties': {'agrupar_por': {'default': 'articulo',
                                                                               'enum': sorted(SALE_PROFIT_GROUP_FIELDS),
                                                                               'type': 'string'},
                                                               'articulo_desde': {'type': 'string'},
                                                               'articulo_hasta': {'type': 'string'},
                                                               'centro': {'type': 'integer'},
                                                               'cliente_desde': {'type': 'integer'},
                                                               'cliente_hasta': {'type': 'integer'},
                                                               'descripcion': {'type': 'string'},
                                                               'fecha_desde': {'description': 'Fecha inicial en formato YYYY-MM-DD.',
                                                                               'type': 'string'},
                                                               'fecha_hasta': {'description': 'Fecha final en formato YYYY-MM-DD.',
                                                                               'type': 'string'},
                                                               'incluir_pedidos': {'default': False,
                                                                                   'type': 'boolean'},
                                                               'limite': {'default': 5000,
                                                                          'description': 'Maximo de lineas base a analizar, hasta 5000.',
                                                                          'type': 'integer'},
                                                               'limite_grupos': {'description': 'Maximo de grupos devueltos.',
                                                                                 'type': 'integer'},
                                                               'moneda': {'default': 'E',
                                                                          'enum': ['E', 'P'],
                                                                          'type': 'string'},
                                                               'ordenar_por': {'default': 'margen',
                                                                               'enum': ['venta_neta', 'coste', 'margen', 'rentabilidad_pct', 'unidades', 'lineas'],
                                                                               'type': 'string'},
                                                               'proveedor_desde': {'type': 'integer'},
                                                               'proveedor_hasta': {'type': 'integer'},
                                                               'representante': {'type': 'integer'},
                                                               'sentido': {'default': 'desc',
                                                                           'enum': ['asc', 'desc'],
                                                                           'type': 'string'},
                                                               'solo_en_oferta': {'default': False,
                                                                                  'type': 'boolean'},
                                                               'subcliente_desde': {'type': 'integer'},
                                                               'subcliente_hasta': {'type': 'integer'},
                                                               'tipo_familia': {'default': 'ncc',
                                                                                'description': 'Origen de familia al agrupar por familia/subfamilia: ncc usa FAMNC/FAMNCC, propia usa ART_CODFAM/ART_SUBFAM y cooperativa usa ART_AGRUP1/2/3.',
                                                                                'enum': sorted(SALE_FAMILY_TYPES),
                                                                                'type': 'string'},
                                                               'tipos_documento': {'items': {'enum': ['T', 'F', 'A', 'C', 'P', 'R', 'S'],
                                                                                             'type': 'string'},
                                                                                   'type': 'array'}},
                                                'required': ['fecha_desde', 'fecha_hasta'],
                                                'type': 'object'},
                                'name': 'venta_rentabilidad_resumen'}}

_DASHBOARD_ANALYTICS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fecha_desde": {"type": "string", "description": "Fecha inicial en formato YYYY-MM-DD."},
        "fecha_hasta": {"type": "string", "description": "Fecha final en formato YYYY-MM-DD."},
        "comparar_fecha_desde": {
            "type": "string",
            "description": "Fecha inicial comparativa. Si se omite, se usa el periodo anterior equivalente.",
        },
        "comparar_fecha_hasta": {
            "type": "string",
            "description": "Fecha final comparativa. Si se omite, se usa el periodo anterior equivalente.",
        },
        "agrupar_por": {"default": "familia", "enum": sorted(SALE_PROFIT_GROUP_FIELDS), "type": "string"},
        "tipo_familia": {
            "default": "ncc",
            "description": "Origen de familia: ncc, propia o cooperativa.",
            "enum": sorted(SALE_FAMILY_TYPES),
            "type": "string",
        },
        "centro": {"type": "integer"},
        "cliente_desde": {"type": "integer"},
        "cliente_hasta": {"type": "integer"},
        "subcliente_desde": {"type": "integer"},
        "subcliente_hasta": {"type": "integer"},
        "proveedor_desde": {"type": "integer"},
        "proveedor_hasta": {"type": "integer"},
        "representante": {"type": "integer"},
        "articulo_desde": {"type": "string"},
        "articulo_hasta": {"type": "string"},
        "descripcion": {"type": "string"},
        "tipos_documento": {
            "items": {"enum": ["T", "F", "A", "C", "P", "R", "S"], "type": "string"},
            "type": "array",
        },
        "moneda": {"default": "E", "enum": ["E", "P"], "type": "string"},
        "incluir_pedidos": {"default": False, "type": "boolean"},
        "solo_en_oferta": {"default": False, "type": "boolean"},
        "limite": {"default": 3000, "type": "integer"},
        "limite_alertas": {"default": 20, "type": "integer"},
        "limite_detalle": {"default": 50, "type": "integer"},
        "limite_grupos": {"type": "integer"},
        "umbral_variacion_pct": {"default": "10", "type": ["number", "string"]},
        "umbral_rentabilidad_baja": {"default": "10", "type": ["number", "string"]},
        "dias_cobertura_alta": {"default": "180", "type": ["number", "string"]},
        "dias_sin_vender_alerta": {"default": 180, "type": "integer"},
        "solo_con_stock": {"default": True, "type": "boolean"},
        "stock_minimo": {"default": "0", "type": ["number", "string"]},
        "venta_minima": {"default": "0", "type": ["number", "string"]},
    },
    "required": ["fecha_desde", "fecha_hasta"],
}

_DASHBOARD_DOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fecha_desde": {"type": "string", "description": "Fecha inicial en formato YYYY-MM-DD."},
        "fecha_hasta": {"type": "string", "description": "Fecha final en formato YYYY-MM-DD."},
        "agrupar_por": {"default": "categoria", "enum": sorted(SALE_DOCUMENT_GROUP_FIELDS), "type": "string"},
        "ordenar_por": {
            "default": "pendiente",
            "enum": ["base_imponible", "iva", "recargo", "total", "cobrado", "pendiente", "documentos"],
            "type": "string",
        },
        "sentido": {"default": "desc", "enum": ["asc", "desc"], "type": "string"},
        "tipos_documento": {
            "items": {"enum": ["T", "F", "A", "C", "P", "R", "S"], "type": "string"},
            "type": "array",
        },
        "centro": {"type": "integer"},
        "cliente_desde": {"type": "integer"},
        "cliente_hasta": {"type": "integer"},
        "subcliente_desde": {"type": "integer"},
        "subcliente_hasta": {"type": "integer"},
        "representante": {"type": "integer"},
        "situacion": {"type": "string"},
        "moneda": {"default": "E", "enum": ["E", "P"], "type": "string"},
        "limite": {"default": 10000, "type": "integer"},
        "limite_grupos": {"type": "integer"},
    },
    "required": ["fecha_desde", "fecha_hasta"],
}

_DASHBOARD_PURCHASE_PENDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fecha_desde": {"type": "string", "description": "Fecha inicial en formato YYYY-MM-DD."},
        "fecha_hasta": {"type": "string", "description": "Fecha final en formato YYYY-MM-DD."},
        "centro": {"type": "integer"},
        "proveedor_desde": {"type": "integer"},
        "proveedor_hasta": {"type": "integer"},
        "situacion": {"type": "string", "description": "Situacion interna del documento/cabecera."},
        "solo_pendiente": {"default": True, "type": "boolean"},
        "limite": {"default": 500, "type": "integer"},
    },
    "required": ["fecha_desde", "fecha_hasta"],
}

_DASHBOARD_PURCHASE_ITEMS_PENDING_SCHEMA: dict[str, Any] = {
    **_DASHBOARD_PURCHASE_PENDING_SCHEMA,
    "properties": {
        **_DASHBOARD_PURCHASE_PENDING_SCHEMA["properties"],
        "limite_pedidos": {
            "default": 5000,
            "type": "integer",
            "description": "Maximo de pedidos de compra pendientes a leer antes de agrupar por articulo.",
        },
    },
}

_PURCHASE_ORDER_PROPOSAL_STOCK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "centro": {"type": "integer", "description": "Centro de stock. Por defecto el centro de sesion."},
        "proveedor": {"type": "integer", "description": "Filtra por ARTP_CODPRO; si se omite se usa el proveedor principal ART_CODPRO."},
        "solo_proveedor_principal": {"default": False, "type": "boolean"},
        "articulo": {"type": "string"},
        "articulo_desde": {"type": "string"},
        "articulo_hasta": {"type": "string"},
        "seccion": {"type": "string"},
        "familia": {"type": "integer"},
        "subfamilia": {"type": "integer"},
        "propio": {"type": "string", "description": "ART_INDPROP: S/N."},
        "solo_activos": {"default": True, "type": "boolean"},
        "excluir_obsoletos": {"default": False, "type": "boolean"},
        "incluir_sin_stock_minimo": {"default": False, "type": "boolean"},
        "solo_con_cantidad": {"default": True, "type": "boolean"},
        "pedir_hasta_maximo": {"default": False, "type": "boolean"},
        "pedido_optimo": {"default": False, "type": "boolean"},
        "unidades_paquete": {"default": True, "type": "boolean"},
        "limite": {"default": 200, "type": "integer"},
    },
}

_PURCHASE_ORDER_PROPOSAL_CUSTOMER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "centro": {"type": "integer", "description": "Centro de los pedidos de cliente."},
        "proveedor": {"type": "integer"},
        "cliente": {"type": "integer"},
        "articulo": {"type": "string"},
        "articulo_desde": {"type": "string"},
        "articulo_hasta": {"type": "string"},
        "fecha_desde": {"type": "string"},
        "fecha_hasta": {"type": "string"},
        "incluir_stock_minimo": {"default": False, "type": "boolean"},
        "unidades_paquete": {"default": True, "type": "boolean"},
        "incluir_todos_documentos": {"default": False, "type": "boolean"},
        "limite": {"default": 200, "type": "integer"},
    },
}

_DASHBOARD_TREASURY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fecha_desde": {"type": "string", "description": "Fecha inicial en formato YYYY-MM-DD."},
        "fecha_hasta": {"type": "string", "description": "Fecha final en formato YYYY-MM-DD."},
        "centro": {"type": "integer"},
        "caja": {"type": "integer"},
        "tipo_operacion": {"type": "string", "description": "Tipo OPECAJ: E=entrada, S=salida, C=cierre de caja."},
        "forma_pago": {"type": "string"},
        "limite": {"default": 500, "type": "integer"},
    },
    "required": ["fecha_desde", "fecha_hasta"],
}

_CARTERA_EFFECTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fecha_desde": {"type": "string", "description": "Fecha inicial de emision en formato YYYY-MM-DD."},
        "fecha_hasta": {"type": "string", "description": "Fecha final de emision en formato YYYY-MM-DD."},
        "vencimiento_desde": {"type": "string", "description": "Fecha inicial de vencimiento en formato YYYY-MM-DD."},
        "vencimiento_hasta": {"type": "string", "description": "Fecha final de vencimiento en formato YYYY-MM-DD."},
        "fecha_referencia": {"type": "string", "description": "Fecha para clasificar vencidos; por defecto hoy."},
        "centro": {"type": "integer"},
        "tipo_documento": {"default": "F", "description": "CBVE_TIPDOC; por defecto facturas F.", "type": "string"},
        "ejercicio": {"type": "integer"},
        "serie": {"type": "string"},
        "cliente": {"type": "integer"},
        "subcliente": {"type": "integer"},
        "cliente_desde": {"type": "integer"},
        "cliente_hasta": {"type": "integer"},
        "tipo_efecto": {"description": "CBVE_TIPOEF: R/I/E/N/T/O/G segun datos Faro.", "type": "string"},
        "situacion": {
            "default": "pendientes",
            "enum": ["todos", "pendientes", "pendiente", "vencidos", "vencido", "cobrados", "cobrado"],
            "type": "string",
        },
        "remesado": {"description": "S=con remesa, N=sin remesa.", "enum": ["S", "N"], "type": "string"},
        "limite": {"default": 500, "type": "integer"},
        "limite_detalle": {"default": 50, "type": "integer"},
        "limite_clientes": {"default": 100, "type": "integer"},
    },
}

_CARTERA_REMESAS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ejercicio": {"type": "integer"},
        "fecha_desde": {"type": "string"},
        "fecha_hasta": {"type": "string"},
        "situacion": {"type": "string", "description": "REM_SITUAC."},
        "limite": {"default": 500, "type": "integer"},
    },
}

_CARTERA_RISK_CLIENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cliente": {"type": "integer"},
        "subcliente": {"default": 0, "type": "integer"},
    },
    "required": ["cliente"],
}

_CARTERA_RISK_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cliente_desde": {"type": "integer"},
        "cliente_hasta": {"type": "integer"},
        "solo_excedidos": {"default": False, "type": "boolean"},
        "limite": {"default": 100, "type": "integer"},
    },
}

_DASHBOARD_ACTIONS_SCHEMA: dict[str, Any] = {
    **_DASHBOARD_ANALYTICS_SCHEMA,
    "properties": {
        **_DASHBOARD_ANALYTICS_SCHEMA["properties"],
        "areas": {
            "type": "array",
            "items": {"enum": ["ventas", "clientes", "stock", "pendientes", "tesoreria"], "type": "string"},
            "description": "Areas de accion a evaluar. Si se omite, se evaluan todas.",
        },
        "caja": {"type": "integer"},
        "forma_pago": {"type": "string"},
        "tipo_operacion": {"type": "string", "description": "Tipo OPECAJ: E=entrada, S=salida, C=cierre de caja."},
        "limite_acciones": {"default": 20, "type": "integer"},
        "prioridad_minima": {"default": 0, "type": "integer"},
        "importe_minimo_accion": {"default": "0", "type": ["number", "string"]},
    },
}

_INTERNAL_TOOL_DEFINITIONS.update({
    "empresa_replicar": {
        "name": "empresa_replicar",
        "description": (
            "Empresas. CRITICA. Crea una empresa destino replicando desde la empresa 1 "
            "las tablas auxiliares y de configuracion acordadas; actualiza el nombre y "
            "direccion en EMPRES y CENTROS."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "empresa_destino": {
                    "type": "integer",
                    "description": "Numero de empresa nueva a crear. Debe ser distinta de 1.",
                },
                "nombre": {
                    "type": "string",
                    "description": "Nombre comercial/fiscal que se grabara en EMPRES y CENTROS.",
                },
                "direccion": {
                    "type": "string",
                    "description": "Direccion principal que se grabara en EMPRES y CENTROS.",
                },
            },
            "required": ["empresa_destino", "nombre", "direccion"],
        },
    },
    "dashboard_acciones_recomendadas": {
        "name": "dashboard_acciones_recomendadas",
        "description": "Dashboard ERP. LECTURA. Recomienda acciones priorizadas combinando ventas, clientes, stock, pendientes y tesoreria, con evidencia trazable.",
        "inputSchema": _DASHBOARD_ACTIONS_SCHEMA,
    },
    "dashboard_resumen": {
        "name": "dashboard_resumen",
        "description": "Dashboard ERP. LECTURA. Resume ventas, rentabilidad, clientes, stock e insights accionables usando las funciones de negocio existentes.",
        "inputSchema": _DASHBOARD_ANALYTICS_SCHEMA,
    },
    "dashboard_series_temporales": {
        "name": "dashboard_series_temporales",
        "description": "Dashboard ERP. LECTURA. Devuelve series agregadas de ventas y documentos para graficas del cuadro de mando.",
        "inputSchema": _DASHBOARD_ANALYTICS_SCHEMA,
    },
    "dashboard_alertas": {
        "name": "dashboard_alertas",
        "description": "Dashboard ERP. LECTURA. Consolida alertas de rentabilidad, clientes y stock en una lista accionable.",
        "inputSchema": _DASHBOARD_ANALYTICS_SCHEMA,
    },
    "dashboard_filtros": {
        "name": "dashboard_filtros",
        "description": "Dashboard ERP. LECTURA. Devuelve catalogos existentes para poblar filtros del dashboard.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "incluir": {
                    "type": "array",
                    "items": {
                        "enum": ["marcas", "familias", "familias_web", "clientes", "proveedores", "tipos_documento"],
                        "type": "string",
                    },
                    "description": "Bloques de filtros a devolver.",
                },
                "padre_familia": {"type": "string"},
                "padre_familia_web": {"type": "string"},
                "limite": {"default": 100, "type": "integer"},
            },
        },
    },
    "ventas_resumen": {
        "name": "ventas_resumen",
        "description": "Dashboard ERP. LECTURA. Resume ventas y documentos apoyandose en rentabilidad y ANADOC existentes.",
        "inputSchema": _DASHBOARD_ANALYTICS_SCHEMA,
    },
    "ventas_acciones_recomendadas": {
        "name": "ventas_acciones_recomendadas",
        "description": "Dashboard ERP. LECTURA. Recomienda acciones sobre lineas y articulos con margen negativo.",
        "inputSchema": _DASHBOARD_ACTIONS_SCHEMA,
    },
    "compras_resumen": {
        "name": "compras_resumen",
        "description": "Dashboard ERP. LECTURA. Resume compras del periodo usando los movimientos de almacen ya usados por rotacion de stock.",
        "inputSchema": _DASHBOARD_ANALYTICS_SCHEMA,
    },
    "cartera_efectos_detalle": {
        "name": "cartera_efectos_detalle",
        "description": "Cartera. LECTURA. Lista efectos de CABDOCVE con vencimiento, importes, cobrado, pendiente, estado y remesa.",
        "inputSchema": _CARTERA_EFFECTS_SCHEMA,
    },
    "cartera_efectos_pendientes_resumen": {
        "name": "cartera_efectos_pendientes_resumen",
        "description": "Cartera. LECTURA. Resume efectos pendientes/vencidos por tipo, situacion y estado de remesa usando CABDOCVE.",
        "inputSchema": _CARTERA_EFFECTS_SCHEMA,
    },
    "cartera_efectos_por_cliente": {
        "name": "cartera_efectos_por_cliente",
        "description": "Cartera. LECTURA. Agrupa efectos pendientes de CABDOCVE por cliente/subcliente con vencido, remesado y no remesado.",
        "inputSchema": _CARTERA_EFFECTS_SCHEMA,
    },
    "cartera_pendiente_remesar": {
        "name": "cartera_pendiente_remesar",
        "description": "Cartera. LECTURA. Lista efectos pendientes sin remesa asignada, candidatos a preparar remesa.",
        "inputSchema": _CARTERA_EFFECTS_SCHEMA,
    },
    "cartera_remesas_resumen": {
        "name": "cartera_remesas_resumen",
        "description": "Cartera. LECTURA. Resume remesas desde REMESA y sus efectos vinculados en CABDOCVE.",
        "inputSchema": _CARTERA_REMESAS_SCHEMA,
    },
    "cartera_riesgo_cliente": {
        "name": "cartera_riesgo_cliente",
        "description": "Cartera. LECTURA. Calcula el riesgo actual de credito de un cliente con la regla RIESGO_ACTUAL del ERP.",
        "inputSchema": _CARTERA_RISK_CLIENT_SCHEMA,
    },
    "cartera_riesgo_clientes_resumen": {
        "name": "cartera_riesgo_clientes_resumen",
        "description": "Cartera. LECTURA. Calcula riesgo actual de credito para clientes, ordenando primero los excedidos.",
        "inputSchema": _CARTERA_RISK_SUMMARY_SCHEMA,
    },
    "compras_articulos_pendientes_recibir": {
        "name": "compras_articulos_pendientes_recibir",
        "description": "Dashboard ERP. LECTURA. Agrupa por articulo las cantidades pendientes de recibir desde pedidos de compra CABORC/DETORC.",
        "inputSchema": _DASHBOARD_PURCHASE_ITEMS_PENDING_SCHEMA,
    },
    "compras_pedidos_pendientes_resumen": {
        "name": "compras_pedidos_pendientes_resumen",
        "description": "Dashboard ERP. LECTURA. Resume ordenes de compra pendientes desde CABORC/DETORC.",
        "inputSchema": _DASHBOARD_PURCHASE_PENDING_SCHEMA,
    },
    "compras_documentos_pendientes_resumen": {
        "name": "compras_documentos_pendientes_resumen",
        "description": "Dashboard ERP. LECTURA. Resume documentos de proveedor pendientes desde CABDOCM.",
        "inputSchema": _DASHBOARD_PURCHASE_PENDING_SCHEMA,
    },
    "orden_compra_propuesta_stock_minimo": {
        "name": "orden_compra_propuesta_stock_minimo",
        "description": "Compras. LECTURA. Propone cantidades a pedir desde stock minimo/maximo replicando GENPEDM y UTL_STOCK_TERMINO, sin crear CABORC.",
        "inputSchema": _PURCHASE_ORDER_PROPOSAL_STOCK_SCHEMA,
    },
    "orden_compra_propuesta_pedidos_cliente": {
        "name": "orden_compra_propuesta_pedidos_cliente",
        "description": "Compras. LECTURA. Propone cantidades a pedir desde pedidos de cliente replicando GENPEDC y UTL_STOCK_TERMINO, sin crear CABORC.",
        "inputSchema": _PURCHASE_ORDER_PROPOSAL_CUSTOMER_SCHEMA,
    },
    "stock_resumen": {
        "name": "stock_resumen",
        "description": "Dashboard ERP. LECTURA. Resume stock, valor inmovilizado y alertas de rotacion.",
        "inputSchema": _DASHBOARD_ANALYTICS_SCHEMA,
    },
    "stock_acciones_recomendadas": {
        "name": "stock_acciones_recomendadas",
        "description": "Dashboard ERP. LECTURA. Recomienda acciones sobre stock parado, sobrestock y compras sin salida.",
        "inputSchema": _DASHBOARD_ACTIONS_SCHEMA,
    },
    "pedidos_resumen": {
        "name": "pedidos_resumen",
        "description": "Dashboard ERP. LECTURA. Resume pedidos y presupuestos de venta desde documentos existentes.",
        "inputSchema": _DASHBOARD_DOCUMENT_SCHEMA,
    },
    "pedidos_acciones_recomendadas": {
        "name": "pedidos_acciones_recomendadas",
        "description": "Dashboard ERP. LECTURA. Recomienda acciones sobre pedidos, presupuestos y documentos pendientes.",
        "inputSchema": _DASHBOARD_ACTIONS_SCHEMA,
    },
    "documentos_pendientes_resumen": {
        "name": "documentos_pendientes_resumen",
        "description": "Dashboard ERP. LECTURA. Resume albaranes, facturas y creditos pendientes usando ANADOC existente.",
        "inputSchema": _DASHBOARD_DOCUMENT_SCHEMA,
    },
    "clientes_resumen": {
        "name": "clientes_resumen",
        "description": "Dashboard ERP. LECTURA. Resume clientes en riesgo, bajadas de venta y concentracion comercial.",
        "inputSchema": _DASHBOARD_ANALYTICS_SCHEMA,
    },
    "clientes_acciones_recomendadas": {
        "name": "clientes_acciones_recomendadas",
        "description": "Dashboard ERP. LECTURA. Recomienda acciones comerciales sobre clientes que caen, desaparecen o deterioran margen.",
        "inputSchema": _DASHBOARD_ACTIONS_SCHEMA,
    },
    "proveedores_resumen": {
        "name": "proveedores_resumen",
        "description": "Dashboard ERP. LECTURA. Resume ventas y compras agrupadas por proveedor con funciones ya existentes.",
        "inputSchema": _DASHBOARD_ANALYTICS_SCHEMA,
    },
    "tesoreria_resumen": {
        "name": "tesoreria_resumen",
        "description": "Dashboard ERP. LECTURA. Resume operaciones de caja/tesoreria desde OPECAJ.",
        "inputSchema": _DASHBOARD_TREASURY_SCHEMA,
    },
    "tesoreria_acciones_recomendadas": {
        "name": "tesoreria_acciones_recomendadas",
        "description": "Dashboard ERP. LECTURA. Recomienda acciones sobre cierres de caja y operaciones de caja revisables desde OPECAJ.",
        "inputSchema": _DASHBOARD_ACTIONS_SCHEMA,
    },
})

# ---------------------------------------------------------------------------
# Fase 12: contrato publico v2 - parametros legibles y respuestas uniformes.
# ---------------------------------------------------------------------------
# Los handlers internos conservan los nombres de campo historicos porque son
# los mismos que usa la capa de negocio/BD. El contrato MCP publica nombres
# orientados al dominio y esta tabla realiza la traduccion en el borde.
_CANONICAL_PARAMETER_NAMES: dict[str, str] = {
    "codart": "articulo",
    "codcli": "cliente",
    "subcli": "subcliente",
    "codrep": "representante",
    "codpro": "proveedor",
    "codact": "tipo_actividad",
    "tipdoc": "tipo_documento",
    "ejerci": "ejercicio",
    "numdoc": "numero",
    "cantid": "cantidad",
    "descri": "descripcion",
    "unimed": "unidad_medida",
    "centroo": "centro_origen",
    "centrod": "centro_destino",
    "ubi_origen": "ubicacion_origen",
    "ubi_destino": "ubicacion_destino",
    "situac": "situacion",
    "password": "contrasena",
    "limit": "limite",
    "order_by": "ordenar_por",
    "codart_prefix": "prefijo_articulo",
    "with_stock": "con_stock",
    "purchase_before": "fecha_compra_antes",
    "sale_before": "fecha_venta_antes",
    "movement_before": "fecha_movimiento_antes",
    "new_table": "tabla_nueva",
    "force_blister_current_cost": "forzar_coste_blister_actual",
    "codfam": "familia",
    "subfam": "subfamilia",
    "ssubfam": "ssubfamilia",
    "famncc": "familia_ncc",
    "nombre_like": "nombre",
    "poblacion_like": "poblacion",
    "nombre_comercial_like": "nombre_comercial",
    "nombre_fiscal_like": "nombre_fiscal",
    "nombre_abreviado_like": "nombre_abreviado",
}

_TOOL_PARAMETER_OVERRIDES: dict[str, dict[str, str]] = {
    "actividad_grabar": {"texto": "observacion"},
    "cliente_actualizar": {"texto": "datos"},
    "mostrador_cobrar": {"texto": "lineas"},
    "mostrador_venta_gestion": {"texto": "lineas"},
    "pedido_albaranar": {"texto": "lineas"},
    "pedido_crear": {"texto": "lineas", "observaciones": "comentarios", "urgente": "crear_presupuesto"},
    "stock_trasvasar": {"texto": "lineas"},
    "venta_documento_crear": {"texto": "lineas"},
}

_ORDER_LINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "articulo": {"type": "string"},
        "descripcion": {"type": "string"},
        "cantidad": {"type": ["number", "string"]},
        "precio": {"type": ["number", "string"]},
        "descuento": {"type": ["number", "string"], "default": 0},
    },
    "required": ["articulo", "cantidad", "precio"],
}

_DELIVERY_LINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "linea": {"type": "integer", "description": "Numero de linea del pedido origen."},
        "cantidad": {"type": ["number", "string"]},
    },
    "required": ["linea", "cantidad"],
}

_TRANSFER_LINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "articulo": {"type": "string"},
        "descripcion": {"type": "string", "description": "Si se deja vacia se lee de ARTICUL."},
        "cantidad": {"type": ["number", "string"]},
        "unidad_medida": {"type": "string", "description": "Si se deja vacia se lee de ARTICUL."},
    },
    "required": ["articulo", "cantidad"],
}

_OFFER_LINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "articulo": {"type": "string"},
        "precio_oferta": {"type": ["number", "string"], "description": "PVP de oferta que se graba en DOF_PVP."},
        "precio_sin_iva": {"type": ["number", "string"], "default": 0, "description": "Precio sin IVA opcional para DOF_PRECIO."},
        "descuento1": {"type": ["number", "string"], "default": 0},
        "descuento2": {"type": ["number", "string"], "default": 0},
        "descuentos": {
            "type": "array",
            "items": {"type": ["number", "string"]},
            "maxItems": 2,
            "description": "Alternativa compacta a descuento1/descuento2.",
        },
    },
    "required": ["articulo", "precio_oferta"],
}

_SUPPLIER_TARIFF_LINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "articulo": {"type": "string", "description": "Codigo interno. Si no se informa, puede resolverse por codigo_barras o referencia_proveedor; con dar_de_alta=true y el articulo inexistente, si tampoco se informa se autogenera o se toma de referencia_proveedor (ver usar_referencia_proveedor_como_codigo en tarifa_proveedor_actualizar)."},
        "codigo_barras": {"type": "string", "description": "Codigo EAN/ARTICULC alternativo para resolver el articulo."},
        "referencia_proveedor": {"type": "string", "description": "ARTP_REFPRO. Tambien puede usarse para localizar una tarifa existente."},
        "descripcion": {"type": "string", "description": "Descripcion de compra ARTP_DESCRI."},
        "unidad_medida": {"type": "string", "description": "Unidad de medida de compra."},
        "precio_base": {"type": ["number", "string"], "description": "Nuevo ARTP_PREBAS."},
        "descuento1": {"type": ["number", "string"]},
        "descuento2": {"type": ["number", "string"]},
        "descuento3": {"type": ["number", "string"]},
        "descuento4": {"type": ["number", "string"]},
        "descuento5": {"type": ["number", "string"]},
        "descuento6": {"type": ["number", "string"]},
        "descuentos": {"type": "array", "items": {"type": ["number", "string"]}, "maxItems": 6,
                         "description": "Alternativa compacta a descuento1..descuento6."},
        "cantidad_conversion_compra": {"type": ["number", "string"], "description": "ARTP_CANCON."},
        "cantidad_conversion_venta": {"type": ["number", "string"], "description": "ARTP_CANVEN."},
        "unidades_paquete": {"type": ["number", "string"], "description": "ARTP_UNIPAQ."},
        "ampliacion_unidad_venta": {"type": "string", "description": "ARTP_AMPUNIV."},
        "ajuste": {"type": "string", "description": "ARTP_AJUSTE."},
        "seccion": {"type": "string", "description": "ART_SECCIO. Obligatorio si dar_de_alta=true y el articulo no existe. Tambien se usa como prefijo del ART_CODART autogenerado cuando la linea no informa articulo (ver usar_referencia_proveedor_como_codigo/digitos_codigo_articulo/numerador_inicial en tarifa_proveedor_actualizar)."},
        "tipo_iva": {"type": ["integer", "string"], "description": "ART_TIPIVA. Obligatorio si dar_de_alta=true y el articulo no existe."},
        "tipo_precio": {"type": "string", "description": "ART_TIPPRE ('V'/'C'/'M'/...). Obligatorio si dar_de_alta=true y el articulo no existe. Se fuerza a 'C' si se informa canon, igual que IMPTAR_U.pas."},
        "familia": {"type": "integer", "description": "ART_CODFAM. Solo para altas; por defecto 0 (sin familia), igual que IMPTAR_U.pas cuando se deja en blanco."},
        "subfamilia": {"type": "integer", "description": "ART_SUBFAM. Solo para altas; por defecto 0."},
        "tabla_precios": {"type": "integer", "description": "ART_TABPREC. Solo para altas; por defecto 0 (usa la tabla de precios del sistema)."},
        "canon": {"type": ["number", "string"], "description": "ART_IMPFIJ. Solo para altas. Si se informa, fuerza tipo_precio='C' (replica IMPTAR_U.pas)."},
        "tarifa": {"type": ["number", "string"], "description": "ART_PRETAR. Solo para altas."},
        "pvp": {"type": ["number", "string"], "description": "ART_PVP. Solo para altas; fuerza el PVP directo cuando tipo_precio no es 'V'/'C'."},
        "cantidad_pedido_minimo": {"type": ["number", "string"], "description": "ART_CANPMI. Solo para altas."},
        "norma": {"type": "string", "description": "ART_NORMA. Solo para altas."},
    },
    "required": ["precio_base"],
}

_SALE_LINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "articulo": {"type": "string", "default": ""},
        "descripcion": {"type": "string", "default": ""},
        "cantidad": {"type": ["number", "string"], "default": 0},
        "precio": {"type": ["number", "string"], "default": 0},
        "descuento1": {"type": ["number", "string"], "default": 0},
        "descuento2": {"type": ["number", "string"], "default": 0},
        "iva": {"type": ["number", "string"], "default": 0},
        "recargo": {"type": ["number", "string"], "default": 0},
        "tipo_precio": {"type": "string", "default": ""},
        "unidad_medida": {"type": "string", "default": ""},
        "precio_iva_incluido": {"type": "boolean", "default": False},
        "pvp": {"type": ["number", "string"], "default": 0},
        "oferta_ejercicio": {"type": "integer", "default": 0},
        "oferta_numero": {"type": "integer", "default": 0},
    },
}

_CLIENT_DATA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "cliente": {"type": "integer"},
        "subcliente": {"type": "integer"},
        "nombre": {"type": "string"},
        "razon_social": {"type": "string"},
        "domicilio": {"type": "string"},
        "codigo_postal": {"type": "string"},
        "poblacion": {"type": "string"},
        "telefono": {"type": "string"},
        "email": {"type": "string"},
        "cif": {"type": "string"},
    },
    "required": [
        "cliente", "subcliente", "nombre", "razon_social", "domicilio",
        "codigo_postal", "poblacion", "telefono", "email", "cif",
    ],
}

_ARTICLE_ORDER_BY_TO_INTERNAL: dict[str, str] = {
    "codigo": "ART_CODART",
    "descripcion": "ART_DESCRI",
    "unidad_medida": "ART_UNIMED",
    "coste": "ART_PRECOS",
    "precio4": "ART_PREVEN4",
    "pvp": "ART_PVP",
    "proveedor": "ART_CODPRO",
    "nombre_proveedor": "PRO_NOMCOR",
    "existencias": "ARTE_EXIST",
    "fecha_compra": "ARTE_FECCOM",
    "fecha_venta": "ARTE_FECVEN",
    "fecha_movimiento": "ARTE_FECMOV",
}


def _public_parameter_name(tool_name: str, internal_name: str) -> str:
    return _TOOL_PARAMETER_OVERRIDES.get(tool_name, {}).get(
        internal_name, _CANONICAL_PARAMETER_NAMES.get(internal_name, internal_name)
    )


def _build_public_tool_definitions() -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for tool_name, original in _INTERNAL_TOOL_DEFINITIONS.items():
        item = json.loads(json.dumps(original, ensure_ascii=False))
        schema = item.setdefault("inputSchema", {"type": "object", "properties": {}})
        old_props = schema.get("properties", {})
        new_props: dict[str, Any] = {}
        for internal_name, property_schema in old_props.items():
            public_name = _public_parameter_name(tool_name, internal_name)
            new_props[public_name] = property_schema
        new_props.setdefault(
            "empresa",
            {
                "type": "integer",
                "default": DEFAULT_EMPRESA,
                "description": "Numero de empresa Faro sobre la que ejecutar la herramienta. Por defecto 1.",
            },
        )
        if tool_name in CENTER_SCOPED_TOOL_NAMES:
            new_props["centro"] = {
                **new_props.get("centro", {}),
                "type": ["integer", "string"],
                "default": DEFAULT_CENTRO,
                "description": (
                    "Centro Faro sobre el que ejecutar la consulta. Por defecto 0. "
                    "Si se informa como cadena vacia, consulta todos los centros."
                ),
            }
        schema["properties"] = new_props
        schema["required"] = [
            _public_parameter_name(tool_name, name) for name in schema.get("required", [])
        ]
        if tool_name in CENTER_SCOPED_TOOL_NAMES:
            schema["required"] = [name for name in schema["required"] if name != "centro"]
        if not schema["required"]:
            schema.pop("required", None)
        schema["additionalProperties"] = False
        definitions[tool_name] = item

    # El contrato v2 deja de exponer protocolos de texto separados por |/#.
    definitions["cliente_actualizar"]["inputSchema"]["properties"]["datos"] = _CLIENT_DATA_SCHEMA
    definitions["cliente_actualizar"]["inputSchema"]["required"] = ["datos"]
    definitions["cliente_actualizar"]["description"] = (
        "Clientes. ESCRITURA. Actualiza un cliente existente mediante un objeto de datos estructurado."
    )

    definitions["pedido_crear"]["inputSchema"]["properties"]["lineas"] = {
        "type": "array", "items": _ORDER_LINE_SCHEMA, "minItems": 1,
        "description": "Lineas estructuradas del pedido."
    }
    definitions["pedido_crear"]["inputSchema"]["properties"]["comentarios"] = {
        "type": "array", "items": {"type": "string"}, "default": [],
        "description": "Comentarios opcionales que se guardan como lineas de comentario."
    }
    definitions["pedido_crear"]["inputSchema"]["properties"]["crear_presupuesto"] = {
        "type": "boolean", "default": False,
        "description": "Si es true crea un presupuesto (R); en caso contrario un pedido (P)."
    }

    definitions["pedido_albaranar"]["inputSchema"]["properties"]["lineas"] = {
        "type": "array", "items": _DELIVERY_LINE_SCHEMA, "minItems": 1,
        "description": "Lineas del pedido y cantidades que se sirven."
    }
    definitions["pedido_cerrar"]["description"] = (
        "Pedidos. ESCRITURA. Cierra un pedido o presupuesto de cliente, renombrandolo a historico (S)."
    )
    close_props = definitions["pedido_cerrar"]["inputSchema"]["properties"]
    close_props["tipo_documento"]["enum"] = ["P", "R"]
    close_props["tipo_documento"]["description"] = "Tipo de documento origen: P=pedido, R=presupuesto."

    definitions["stock_trasvasar"]["inputSchema"]["properties"]["lineas"] = {
        "type": "array", "items": _TRANSFER_LINE_SCHEMA, "minItems": 1,
        "description": "Articulos y cantidades que se trasvasan entre centros."
    }

    definitions["oferta_crear"]["inputSchema"]["properties"]["articulos"] = {
        "type": "array", "items": _OFFER_LINE_SCHEMA, "minItems": 1,
        "description": "Articulos de la oferta; precio_oferta se graba como PVP de oferta."
    }

    definitions["tarifa_proveedor_actualizar"]["inputSchema"]["properties"]["lineas"] = {
        "type": "array", "items": _SUPPLIER_TARIFF_LINE_SCHEMA, "minItems": 1, "maxItems": 500,
        "description": "Tarifas a dar de alta o actualizar. Cada linea requiere precio_base y algun identificador de articulo."
    }
    definitions["tarifa_proveedor_actualizar"]["inputSchema"]["properties"]["actualizar_precio_venta"]["description"] = (
        "Si es true, calcula el coste neto con los seis descuentos de proveedor y recalcula los precios de ARTICUL."
    )
    definitions["tarifa_proveedor_actualizar"]["inputSchema"]["properties"]["actualizar_solo_si_sube_precio"]["description"] = (
        "Con actualizar_precio_venta=true: omite el recalculo de precios de venta de una linea si el coste neto "
        "nuevo es menor que el anterior (replica B_MAS de IMPTAR_U.pas). La tarifa de compra en ARTICULP se "
        "actualiza igualmente; solo se omite la propagacion a ARTICUL."
    )
    definitions["tarifa_proveedor_actualizar"]["inputSchema"]["properties"]["actualizar_solo_proveedor_principal"]["description"] = (
        "Con actualizar_precio_venta=true: solo recalcula el precio de venta si el proveedor de la linea coincide "
        "con el proveedor principal del articulo (ART_CODPRO). Replica B_PRINCIPAL de IMPTAR_U.pas."
    )
    definitions["tarifa_proveedor_actualizar"]["inputSchema"]["properties"]["actualizar_solo_si_propio"]["description"] = (
        "Con actualizar_precio_venta=true: solo recalcula el precio de venta si el articulo esta marcado como "
        "propio (ART_INDPROP<>'N'). Replica B_PROPIO de IMPTAR_U.pas."
    )
    definitions["tarifa_proveedor_actualizar"]["inputSchema"]["properties"]["generar_etiquetas"]["description"] = (
        "Si es true, encola una etiqueta (tabla ETIQUE) por cada linea cuyo precio de venta haya cambiado "
        "realmente, replicando B_ETIQUETAS de IMPTAR_U.pas. Requiere actualizar_precio_venta=true para tener "
        "efecto, ya que sin recalculo de venta no hay cambio de precio que detectar."
    )
    definitions["tarifa_proveedor_actualizar"]["inputSchema"]["properties"]["etiqueta_modelo"]["description"] = (
        "Modelo de etiqueta (MODETI) a usar con generar_etiquetas. IMPTAR_U.pas resuelve un modelo por defecto "
        "via MODELO_ETIQUETA_ARTICUL (funcion no localizada en las fuentes disponibles); por eso aqui se pide "
        "explicito y por defecto es 0, igual que el valor de respaldo del propio Delphi cuando esa resolucion "
        "no encuentra nada."
    )
    definitions["tarifa_proveedor_actualizar"]["inputSchema"]["properties"]["dar_de_alta"]["description"] = (
        "Si es true, cuando una linea no resuelve a un articulo existente (por articulo/codigo_barras/"
        "referencia_proveedor), lo da de alta creando ARTICUL y ARTICULP en el mismo lote, replicando la rama "
        "'ELSE IF B_ALTA.Checked' de IMPTAR_U.pas. En ese caso la linea debe informar tambien descripcion, "
        "seccion, tipo_iva, tipo_precio y unidad_medida; el codigo de articulo (articulo) es opcional: si no "
        "se informa, se resuelve via usar_referencia_proveedor_como_codigo/digitos_codigo_articulo/"
        "numerador_inicial. Si es false (por defecto) una linea sin articulo existente sigue lanzando error y "
        "revirtiendo todo el lote, igual que antes."
    )
    definitions["tarifa_proveedor_actualizar"]["inputSchema"]["properties"]["usar_referencia_proveedor_como_codigo"]["description"] = (
        "Con dar_de_alta=true: cuando una linea no informa articulo, usa su referencia_proveedor tal cual como "
        "nuevo ART_CODART en lugar de autogenerarlo. Replica la casilla B_REFPRO 'Codigo de Articulo = "
        "Referencia Proveedor' de IMPTAR_U.pas. Si esta activo y la linea no trae referencia_proveedor, es "
        "error. Sin efecto si la linea ya informa articulo o si dar_de_alta es false."
    )
    definitions["tarifa_proveedor_actualizar"]["inputSchema"]["properties"]["digitos_codigo_articulo"]["description"] = (
        "Con dar_de_alta=true y usar_referencia_proveedor_como_codigo=false: numero total de digitos del "
        "ART_CODART autogenerado para lineas sin articulo (seccion + proveedor a 4 digitos + un contador que "
        "ocupa el resto). Debe estar entre 8 y 15, igual que B_DIGITOS (TRxSpinEdit) de IMPTAR_U.pas; por "
        "defecto 9 (igual que la pantalla)."
    )
    definitions["tarifa_proveedor_actualizar"]["inputSchema"]["properties"]["numerador_inicial"]["description"] = (
        "Con dar_de_alta=true y usar_referencia_proveedor_como_codigo=false: valor inicial del contador usado "
        "para autogenerar ART_CODART (seccion+proveedor+contador). Se incrementa automaticamente si el codigo "
        "resultante ya existe, y el contador se comparte para todas las lineas del lote sin reiniciarse entre "
        "ellas, igual que NumInicial/CONTADOR en IMPTAR_U.pas. Por defecto 0."
    )

    for tool_name in ("mostrador_cobrar", "venta_documento_crear"):
        definitions[tool_name]["inputSchema"]["properties"]["lineas"] = {
            "type": "array", "items": _SALE_LINE_SCHEMA,
            "description": "Lineas estructuradas de venta. Puede estar vacio si se consume una venta abierta."
        }

    # Mostrador tiene dos formas de linea segun accion. Se documenta el objeto
    # flexible y el traductor valida/serializa segun guardar o cargar_pedido.
    definitions["mostrador_venta_gestion"]["inputSchema"]["properties"]["lineas"] = {
        "type": "array",
        "items": {"type": "object"},
        "description": (
            "Con accion=guardar: lineas de venta estructuradas. Con accion=cargar_pedido: "
            "objetos con linea y cantidad. No se usa al borrar."
        ),
    }

    # Orden de articulos: se ocultan nombres fisicos de columnas.
    order_schema = definitions["articulo_buscar"]["inputSchema"]["properties"]["ordenar_por"]
    order_schema["enum"] = list(_ARTICLE_ORDER_BY_TO_INTERNAL)
    order_schema["default"] = "descripcion"
    order_schema["description"] = "Criterio de orden funcional, sin nombres fisicos de columnas."

    # Ajusta textos visibles para que tampoco mencionen nombres de parametros legacy.
    definitions["articulo_compra_consultar"]["description"] = (
        "Compras. Sin proveedor lista los proveedores asociados al articulo; con proveedor "
        "devuelve su ficha de compra y coste calculado."
    )
    definitions["cliente_buscar"]["description"] = (
        "Clientes. Busca clientes con filtros tipados. Si se indican solo cliente y subcliente "
        "devuelve la ficha detallada; en otro caso devuelve un listado filtrado."
    )
    definitions["pedido_listar"]["description"] = (
        "Pedidos. Lista el cuadro operativo del centro; si se indican cliente y subcliente, "
        "lista el historico de pedidos de ese cliente."
    )
    definitions["etiqueta_gestion"]["description"] = (
        "Almacen. Gestiona etiquetas con accion=listar, grabar o borrar. Listar admite articulo "
        "opcional; grabar y borrar requieren articulo."
    )
    definitions["recuento_gestion"]["description"] = (
        "Almacen. Gestiona recuentos con accion=listar, grabar o borrar. centro es obligatorio; "
        "listar admite articulo opcional. Al grabar, descripcion y unidad_medida son opcionales "
        "y se autocompletan desde ARTICUL si se dejan vacias."
    )
    recuento_props = definitions["recuento_gestion"]["inputSchema"]["properties"]
    recuento_props["descripcion"]["description"] = (
        "Descripcion del articulo. Si se deja vacia se lee de ARTICUL."
    )
    recuento_props["unidad_medida"]["description"] = (
        "Unidad de medida. Si se deja vacia se lee de ARTICUL."
    )
    stock_schema = definitions["stock_regularizar"]["inputSchema"]
    stock_schema["required"] = ["articulo", "cantidad"]
    stock_props = stock_schema["properties"]
    stock_props["descripcion"]["description"] = (
        "Descripcion del articulo. Si se deja vacia se lee de ARTICUL."
    )
    stock_props["unidad_medida"]["description"] = (
        "Unidad de medida. Si se deja vacia se lee de ARTICUL."
    )
    stock_props["cantidad"]["type"] = ["number", "string"]
    definitions["venta_documento_crear"]["description"] = (
        "Ventas. ESCRITURA. Crea un documento de venta (albaran o factura, segun tipo_documento) "
        "desde lineas o desde una venta abierta."
    )
    sale_props = definitions["venta_documento_crear"]["inputSchema"]["properties"]
    sale_props["tipo_documento"]["enum"] = ["R", "P", "A", "F", "T", "C"]
    sale_props["tipo_documento"]["description"] = "Tipo de documento."
    sale_props["serie"]["description"] = (
        "Serie del documento. Si se deja vacia se calcula automaticamente; si se informa, prevalece."
    )
    definitions["actividad_grabar"]["inputSchema"]["properties"]["representante"]["description"] = (
        "Representante."
    )
    actividad_listar_props = definitions["actividad_listar"]["inputSchema"]["properties"]
    actividad_listar_props["cliente"]["description"] = "Filtro opcional, combinable con los demas."
    actividad_listar_props["tipo_actividad"]["description"] = "Filtro opcional, combinable con los demas."
    actividad_listar_props["representante"]["description"] = "Filtro opcional, combinable con los demas."
    actividad_listar_props["fecha_desde"]["description"] = (
        "AAAA-MM-DD. Inicio del rango de fechas (inclusive). Filtro opcional, combinable con los demas."
    )
    actividad_listar_props["fecha_hasta"]["description"] = (
        "AAAA-MM-DD. Fin del rango de fechas (inclusive). Filtro opcional, combinable con los demas."
    )

    # Descripciones de parametros canonicos especialmente relevantes.
    for tool_name, item in definitions.items():
        props = item["inputSchema"].get("properties", {})
        if "articulo" in props:
            props["articulo"].setdefault("description", "Codigo del articulo.")
        if "cliente" in props:
            props["cliente"].setdefault("description", "Codigo del cliente.")
        if "subcliente" in props:
            props["subcliente"].setdefault("description", "Subcodigo del cliente.")
        if "ejercicio" in props:
            props["ejercicio"].setdefault("description", "Ejercicio del documento.")
        if "numero" in props:
            props["numero"].setdefault("description", "Numero del documento.")
        if "cantidad" in props:
            props["cantidad"].setdefault("description", "Cantidad.")
        if "unidad_medida" in props:
            props["unidad_medida"].setdefault("description", "Unidad de medida.")

    return definitions


PUBLIC_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = _build_public_tool_definitions()


def _stringify_line_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "S" if value else "N"
    return str(value)


def _encode_order_lines(lines: Any) -> str:
    if isinstance(lines, str):
        return lines  # Compatibilidad interna/no anunciada.
    if not isinstance(lines, list):
        raise FaroError("lineas debe ser una lista")
    encoded: list[str] = []
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            raise FaroError(f"lineas[{index}] debe ser un objeto")
        for field in ("articulo", "cantidad", "precio"):
            if field not in line:
                raise FaroError(f"Falta lineas[{index}].{field}")
        encoded.append("|".join([
            _stringify_line_value(line.get("articulo", "")),
            _stringify_line_value(line.get("descripcion", "")),
            _stringify_line_value(line.get("cantidad", 0)),
            _stringify_line_value(line.get("precio", 0)),
            _stringify_line_value(line.get("descuento", 0)),
        ]))
    return "#".join(encoded) + ("#" if encoded else "")


def _encode_delivery_lines(lines: Any) -> str:
    if isinstance(lines, str):
        return lines
    if not isinstance(lines, list):
        raise FaroError("lineas debe ser una lista")
    encoded: list[str] = []
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            raise FaroError(f"lineas[{index}] debe ser un objeto")
        if "linea" not in line or "cantidad" not in line:
            raise FaroError(f"lineas[{index}] requiere linea y cantidad")
        # CODART/DESCRI eran campos muertos en DataSnap, por lo que se envian vacios.
        encoded.append("|".join([
            _stringify_line_value(line["linea"]), "", "", _stringify_line_value(line["cantidad"])
        ]))
    return "#".join(encoded) + ("#" if encoded else "")


def _encode_transfer_lines(lines: Any) -> str:
    if isinstance(lines, str):
        return lines
    if not isinstance(lines, list):
        raise FaroError("lineas debe ser una lista")
    encoded: list[str] = []
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            raise FaroError(f"lineas[{index}] debe ser un objeto")
        required = ("articulo", "cantidad")
        missing = [field for field in required if field not in line]
        if missing:
            raise FaroError(f"Faltan campos en lineas[{index}]: {', '.join(missing)}")
        encoded.append("|".join([
            _stringify_line_value(line.get("articulo", "")),
            _stringify_line_value(line.get("descripcion", "")),
            _stringify_line_value(line.get("cantidad", 0)),
            _stringify_line_value(line.get("unidad_medida", "")),
        ]))
    return "#".join(encoded) + ("#" if encoded else "")


def _encode_sale_lines(lines: Any) -> str:
    if isinstance(lines, str):
        return lines
    if lines is None:
        return ""
    if not isinstance(lines, list):
        raise FaroError("lineas debe ser una lista")
    encoded: list[str] = []
    fields = (
        "articulo", "descripcion", "cantidad", "precio", "descuento1", "descuento2",
        "iva", "recargo", "tipo_precio", "unidad_medida", "precio_iva_incluido",
        "pvp", "oferta_ejercicio", "oferta_numero",
    )
    defaults = {
        "articulo": "", "descripcion": "", "cantidad": 0, "precio": 0,
        "descuento1": 0, "descuento2": 0, "iva": 0, "recargo": 0,
        "tipo_precio": "", "unidad_medida": "", "precio_iva_incluido": False,
        "pvp": 0, "oferta_ejercicio": 0, "oferta_numero": 0,
    }
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            raise FaroError(f"lineas[{index}] debe ser un objeto")
        unknown = set(line).difference(fields)
        if unknown:
            raise FaroError(f"Campos no permitidos en lineas[{index}]: {', '.join(sorted(unknown))}")
        values = []
        for field in fields:
            value = line.get(field, defaults[field])
            if field == "precio_iva_incluido":
                value = "S" if bool(value) else "N"
            values.append(_stringify_line_value(value))
        encoded.append("|".join(values))
    return "#".join(encoded) + ("#" if encoded else "")


def _encode_client_data(data: Any) -> str:
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        raise FaroError("datos debe ser un objeto")
    fields = (
        "cliente", "subcliente", "nombre", "razon_social", "domicilio",
        "codigo_postal", "poblacion", "telefono", "email", "cif",
    )
    missing = [field for field in fields if field not in data]
    if missing:
        raise FaroError("Faltan campos en datos: " + ", ".join(missing))
    unknown = set(data).difference(fields)
    if unknown:
        raise FaroError("Campos no permitidos en datos: " + ", ".join(sorted(unknown)))
    return "|".join(_stringify_line_value(data[field]) for field in fields)


def _matches_public_schema_type(value: Any, expected: str) -> bool:
    """Comprueba los tipos JSON Schema soportados sin confundir bool con int/number."""
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _public_schema_type_error(path: str, expected: str) -> FaroError:
    """Mantiene los mensajes historicos para tipos simples del contrato publico."""
    messages = {
        "object": f"{path} debe ser un objeto",
        "array": f"{path} debe ser una lista",
        "string": f"{path} debe ser texto",
        "integer": f"{path} debe ser entero",
        "number": f"{path} debe ser numerico",
        "boolean": f"{path} debe ser booleano",
        "null": f"{path} debe ser nulo",
    }
    return FaroError(messages.get(expected, f"{path} usa un tipo de esquema no soportado: {expected}"))


def _validate_public_schema(value: Any, schema: dict[str, Any], path: str = "arguments") -> None:
    """Validador estricto del subconjunto JSON Schema usado por el contrato v2."""
    expected = schema.get("type")
    expected_types: list[str] = []
    if isinstance(expected, str):
        expected_types = [expected]
    elif isinstance(expected, list):
        expected_types = [item for item in expected if isinstance(item, str)]
        if len(expected_types) != len(expected) or not expected_types:
            raise FaroError(f"{path} contiene una declaracion de tipo no soportada")
    elif expected is not None:
        raise FaroError(f"{path} contiene una declaracion de tipo no soportada")

    if expected_types:
        unknown_types = [item for item in expected_types if item not in {"object", "array", "string", "integer", "number", "boolean", "null"}]
        if unknown_types:
            raise FaroError(
                f"{path} usa tipo(s) de esquema no soportado(s): {', '.join(unknown_types)}"
            )
        if not any(_matches_public_schema_type(value, item) for item in expected_types):
            if len(expected_types) == 1:
                raise _public_schema_type_error(path, expected_types[0])
            allowed = " o ".join(expected_types)
            raise FaroError(f"{path} debe ser de tipo {allowed}")

    # Las restricciones estructurales se aplican tambien cuando el tipo forma
    # parte de una union (por ejemplo, ["object", "null"]).
    if isinstance(value, dict) and "object" in expected_types:
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = set(value).difference(properties)
            if unknown:
                raise FaroError(f"Parametros no permitidos en {path}: {', '.join(sorted(unknown))}")
        missing = [name for name in schema.get("required", []) if name not in value]
        if missing:
            raise FaroError(f"Faltan parametros obligatorios en {path}: {', '.join(missing)}")
        for name, item in value.items():
            child = properties.get(name)
            if child:
                _validate_public_schema(item, child, f"{path}.{name}")

    if isinstance(value, list) and "array" in expected_types:
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise FaroError(f"{path} requiere al menos {schema['minItems']} elemento(s)")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise FaroError(f"{path} permite como maximo {schema['maxItems']} elemento(s)")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_public_schema(item, item_schema, f"{path}[{index}]")

    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(str(v) for v in schema["enum"])
        raise FaroError(f"{path} no es valido; valores permitidos: {allowed}")


def translate_public_arguments(tool_name: str, arguments: Any) -> dict[str, Any]:
    """Valida el borde MCP v2 y traduce nombres/estructuras a la capa interna."""
    if not isinstance(arguments, dict):
        raise FaroError("arguments debe ser un objeto JSON")
    definition = PUBLIC_TOOL_DEFINITIONS.get(tool_name)
    if not definition:
        raise FaroError(f"Herramienta desconocida: {tool_name}")
    schema = definition.get("inputSchema", {})
    _validate_public_schema(arguments, schema)

    inverse = {
        _public_parameter_name(tool_name, internal): internal
        for internal in _INTERNAL_TOOL_DEFINITIONS[tool_name].get("inputSchema", {}).get("properties", {})
    }
    result: dict[str, Any] = {}
    for public_name, value in arguments.items():
        result[inverse.get(public_name, public_name)] = value
    if tool_name in CENTER_SCOPED_TOOL_NAMES and "centro" not in result:
        result["centro"] = DEFAULT_CENTRO

    # Adaptadores estructurados: a partir de aqui la capa interna no necesita
    # saber que el contrato publico ya no usa cadenas separadas por |/#.
    if tool_name == "cliente_actualizar" and "texto" in result:
        result["texto"] = _encode_client_data(result["texto"])
    elif tool_name == "pedido_crear":
        if "texto" in result:
            result["texto"] = _encode_order_lines(result["texto"])
        if "observaciones" in result:
            comments = result["observaciones"]
            if isinstance(comments, list):
                result["observaciones"] = "\r".join(str(v) for v in comments) + ("\r" if comments else "")
            elif not isinstance(comments, str):
                raise FaroError("comentarios debe ser una lista de textos")
        if "urgente" in result:
            value = result["urgente"]
            if isinstance(value, bool):
                result["urgente"] = "R" if value else ""
    elif tool_name == "pedido_albaranar" and "texto" in result:
        result["texto"] = _encode_delivery_lines(result["texto"])
    elif tool_name == "stock_trasvasar" and "texto" in result:
        result["texto"] = _encode_transfer_lines(result["texto"])
    elif tool_name in {"mostrador_cobrar", "venta_documento_crear"} and "texto" in result:
        result["texto"] = _encode_sale_lines(result["texto"])
    elif tool_name == "mostrador_venta_gestion" and "texto" in result:
        action = str(result.get("accion", "")).strip().lower()
        result["texto"] = (
            _encode_delivery_lines(result["texto"])
            if action == "cargar_pedido" else _encode_sale_lines(result["texto"])
        )

    if tool_name == "articulo_buscar" and "order_by" in result:
        raw = str(result["order_by"] or "descripcion").strip().lower()
        if raw not in _ARTICLE_ORDER_BY_TO_INTERNAL:
            raise FaroError("ordenar_por no es valido")
        result["order_by"] = _ARTICLE_ORDER_BY_TO_INTERNAL[raw]

    return result


_COMPATIBILITY_RESPONSE_KEYS = frozenset({"datasnap_text", "datasnap_value"})


def _clean_public_data(value: Any) -> Any:
    """Normaliza tipos y elimina artefactos del transporte DataSnap del borde MCP."""
    if isinstance(value, dict):
        return {
            str(key): _clean_public_data(item)
            for key, item in value.items()
            if str(key) not in _COMPATIBILITY_RESPONSE_KEYS
        }
    if isinstance(value, list):
        return [_clean_public_data(item) for item in value]
    return normalize(value)


def _result_warnings(data: Any) -> list[str]:
    warnings: list[str] = []
    if isinstance(data, dict):
        raw_warning = data.get("warning")
        if raw_warning:
            warnings.append(str(raw_warning))
        for key, label in (
            ("email_omitido", "El envio de email solicitado no forma parte de esta operacion."),
            ("impresion_omitida", "La impresion se ha omitido."),
        ):
            if data.get(key) is True:
                warnings.append(label)
    return warnings


def _tool_meta(tool_name: str, profile: str) -> dict[str, Any]:
    return {"tool": tool_name, "profile": profile, "contract_version": PUBLIC_CONTRACT_VERSION}


def normalize_public_result(tool_name: str, profile: str, raw_result: Any) -> dict[str, Any]:
    cleaned = _clean_public_data(raw_result)
    warnings = _result_warnings(cleaned)
    if isinstance(cleaned, dict) and "warning" in cleaned:
        cleaned = dict(cleaned)
        cleaned.pop("warning", None)
    if isinstance(cleaned, dict) and cleaned.get("ok") is False:
        details = dict(cleaned)
        details.pop("ok", None)
        message = str(
            details.pop("message", "") or details.pop("motivo", "") or details.pop("reason", "")
            or "La operacion no se pudo completar."
        )
        return {
            "ok": False,
            "error": {"code": "BUSINESS_ERROR", "message": message, "details": details},
            "warnings": warnings,
            "meta": _tool_meta(tool_name, profile),
        }
    if isinstance(cleaned, dict) and "ok" in cleaned:
        cleaned = dict(cleaned)
        cleaned.pop("ok", None)
    return {
        "ok": True,
        "data": cleaned,
        "warnings": warnings,
        "meta": _tool_meta(tool_name, profile),
    }


def _public_error_code(exc: Exception) -> str:
    if isinstance(exc, FaroPermissionError):
        return "FORBIDDEN"
    if isinstance(exc, FaroAuditError):
        return "AUDIT_ERROR"
    if isinstance(exc, FaroError):
        text = str(exc).lower()
        validation_markers = (
            "obligatorio", "obligatorios", "faltan", "debe ser", "deben indicarse",
            "no permitido", "no permitidos", "no es valido", "invalido", "indica exactamente",
            "se esperaba", "requiere",
        )
        if any(marker in text for marker in validation_markers):
            return "INVALID_ARGUMENT"
        if "no encontrado" in text or "no existe" in text:
            return "NOT_FOUND"
        if "bloquead" in text:
            return "RESOURCE_LOCKED"
        return "FARO_ERROR"
    return "INTERNAL_ERROR"


def normalize_public_error(tool_name: str, profile: str, exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {"code": _public_error_code(exc), "message": str(exc)},
        "warnings": [],
        "meta": _tool_meta(tool_name, profile),
    }



def tool_definitions(profile: str | None = None) -> list[dict[str, Any]]:
    """Devuelve schemas canonicos congelados para el perfil solicitado."""
    expected_names = public_tool_names_for_profile(profile)
    missing = expected_names.difference(PUBLIC_TOOL_DEFINITIONS)
    if missing:
        raise FaroError(
            "Contrato MCP incompleto; faltan schemas: " + ", ".join(sorted(missing))
        )
    # Copia por JSON para impedir que un consumidor modifique la definicion global.
    return [json.loads(json.dumps(PUBLIC_TOOL_DEFINITIONS[name], ensure_ascii=False)) for name in sorted(expected_names)]
