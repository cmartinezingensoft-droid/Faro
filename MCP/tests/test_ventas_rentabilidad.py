"""Pruebas de las herramientas de rentabilidad de ventas.

Cubren la parte MCP que replica la lectura de ANAVEN: filtrado de DETMOV,
calculo de coste por la regla de sistema y agregacion por dimensiones.
"""
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

import faro_mcp


class FakeProfitDb:
    def __init__(self, rows):
        self.settings = type("S", (), {"empresa": 1, "centro": 7})()
        self.rows = rows
        self.last_sql = ""
        self.last_params = ()
        self.closed = False

    def fetch_one(self, sql, params=()):
        if "FROM PARAMETROS" in " ".join(sql.upper().split()):
            values = {"DESSER": "", "RENTAF": "25"}
            return {"PAR_VALOR": values.get(params[1], "")}
        return None

    def fetch_all(self, sql, params=()):
        self.last_sql = sql
        self.last_params = params
        return self.rows

    def close(self):
        self.closed = True


class FakeDashboardDb:
    def __init__(self, rows):
        self.settings = type("S", (), {"empresa": 1, "centro": 7, "usuario": "tester"})()
        self.rows = rows
        self.last_sql = ""
        self.last_params = ()
        self.closed = False

    def fetch_one(self, sql, params=()):
        return None

    def fetch_all(self, sql, params=()):
        self.last_sql = sql
        self.last_params = params
        return self.rows

    def close(self):
        self.closed = True


class FakePurchaseProposalDb:
    def __init__(self, rows, stock_terms, parameters=None, purchase_rows=None):
        self.settings = type("S", (), {"empresa": 1, "centro": 7, "usuario": "tester"})()
        self.rows = rows
        self.stock_terms = stock_terms
        self.parameters = parameters or {}
        self.purchase_rows = purchase_rows or {}
        self.last_sql = ""
        self.last_params = ()
        self.closed = False

    def fetch_one(self, sql, params=()):
        upper = " ".join(sql.upper().split())
        if "FROM PARAMETROS" in upper:
            return {"PAR_VALOR": self.parameters.get(params[1], "")}
        if "FROM ARTICULE" in upper:
            codart = str(params[2])
            term = self.stock_terms.get(codart, {})
            return {
                "ARTE_EXIST": term.get("existencias", Decimal("0")),
                "ARTE_MINIMO": term.get("stock_minimo", Decimal("0")),
                "ARTE_MAXIMO": term.get("stock_maximo", Decimal("0")),
            }
        if "FROM FALTAS" in upper:
            codart = str(params[2])
            return {"FAL_CANTID": self.stock_terms.get(codart, {}).get("faltas", Decimal("0"))}
        if "FROM DETMOV" in upper and "SUM(DMV_CANTID)" in upper:
            codart = str(params[3])
            return {"DMV_CANTID": self.stock_terms.get(codart, {}).get("pedidos_cliente", Decimal("0"))}
        if "FROM DETORC" in upper:
            codart = str(params[2])
            return {"DOC_CANPEN": self.stock_terms.get(codart, {}).get("pedidos_proveedor", Decimal("0"))}
        if "FROM ARTICULP AP" in upper:
            return self.purchase_rows.get((params[1], params[2]))
        return None

    def fetch_all(self, sql, params=()):
        self.last_sql = sql
        self.last_params = params
        return self.rows

    def close(self):
        self.closed = True


def sale_row(**overrides):
    row = {
        "DMV_CENTRO": 7,
        "DMV_EJERCI": 2026,
        "DMV_SERIE": "A",
        "DMV_NUMDOC": 123,
        "DMV_TIPDOC": "F",
        "DMV_TIPLIN": "D",
        "DMV_NUMLIN": 10,
        "DMV_FECMOV": date(2026, 1, 5),
        "DMV_CODART": "ART-1",
        "DMV_DESCRI": "Articulo rentable",
        "DMV_CANTID": Decimal("5"),
        "DMV_PREVEN": Decimal("20"),
        "DMV_DTO1": Decimal("0"),
        "DMV_DTO2": Decimal("0"),
        "DMV_VALLINS": Decimal("100"),
        "DMV_IMPDTO": Decimal("10"),
        "DMV_CODMON": "E",
        "DMV_SIGNO": "1",
        "DMV_CANPRE": Decimal("1"),
        "DMV_EJEOFE": 0,
        "DMV_NUMOFE": 0,
        "DMV_CAJA": 0,
        "CBV_CODCLI": 10,
        "CBV_SUBCLI": 0,
        "CBV_NOMCLI": "Cliente",
        "CBV_FORCOB": "E",
        "CBV_CODREP": 3,
        "CBV_CIF": "B1",
        "CBV_REFCLI": "REF",
        "ART_SECCIO": 2,
        "ART_CODFAM": 4,
        "ART_SUBFAM": 8,
        "ART_AGRUP1": 14,
        "ART_AGRUP2": 18,
        "ART_AGRUP3": 19,
        "ART_CODPRO": 99,
        "ART_INDINV": "S",
        "PRO_NOMCOR": "Proveedor",
        "FAM_DESCRI": "Familia",
        "SUB_DESCRI": "Subfamilia",
        "COOP_FAM_DESCRI": "Familia cooperativa",
        "COOP_SUB_DESCRI": "Subfamilia cooperativa",
        "MARCA": "Marca",
        "FAMILIA_NCC": "123456",
        "NCC_NIVEL1_DESCRI": "Familia NCC",
        "NCC_NIVEL2_DESCRI": "Subfamilia NCC",
        "NCC_NIVEL3_DESCRI": "Nivel 3 NCC",
    }
    row.update(overrides)
    return row


class SalesProfitServiceTests(unittest.TestCase):
    def test_sales_profit_lines_calculates_cost_margin_and_filters(self):
        db = FakeProfitDb([sale_row()])
        svc = faro_mcp.FaroPhase1Service(db)

        with patch.object(
            faro_mcp.FaroArticleService,
            "article_cost_price",
            return_value={"precio_coste": "4"},
        ) as cost_mock:
            result = svc.sales_profit_lines(
                fecha_desde="2026-01-01",
                fecha_hasta="2026-01-31",
                tipos_documento=["F", "T"],
                proveedor_desde=90,
                proveedor_hasta=100,
                moneda="E",
            )

        self.assertIn("FROM DETMOV D", db.last_sql)
        self.assertIn("A.ART_CODPRO>=?", db.last_sql)
        self.assertEqual(db.last_params[:5], (1, date(2026, 1, 1), date(2026, 1, 31), "F", "T"))
        cost_mock.assert_called_once_with("ART-1", date(2026, 1, 5), "E")
        self.assertEqual(result["count"], 1)
        item = result["items"][0]
        self.assertEqual(Decimal(item["venta_neta"]), Decimal("90"))
        self.assertEqual(Decimal(item["coste"]), Decimal("20"))
        self.assertEqual(Decimal(item["margen"]), Decimal("70"))
        self.assertGreater(Decimal(item["rentabilidad_pct"]), Decimal("77"))
        self.assertEqual(result["totales"]["lineas"], 1)

    def test_sales_profit_lines_treats_non_inventory_articles_as_concepts(self):
        db = FakeProfitDb([
            sale_row(
                DMV_CODART="PORTES",
                DMV_DESCRI="PORTES",
                DMV_VALLINS=Decimal("8"),
                DMV_IMPDTO=Decimal("0"),
                DMV_CANTID=Decimal("1"),
                ART_INDINV="N",
            )
        ])
        svc = faro_mcp.FaroPhase1Service(db)

        with patch.object(faro_mcp.FaroArticleService, "article_cost_price") as cost_mock:
            result = svc.sales_profit_lines(
                fecha_desde="2026-01-01",
                fecha_hasta="2026-01-31",
            )

        item = result["items"][0]
        self.assertEqual(item["articulo"]["codigo"], "PORTES")
        self.assertFalse(item["articulo"]["inventariable"])
        self.assertEqual(item["articulo"]["indicador_inventario"], "N")
        self.assertEqual(item["articulo"]["tipo_articulo"], "concepto")
        self.assertEqual(item["coste"], "0")
        self.assertEqual(item["margen"], "8")
        self.assertEqual(item["rentabilidad_pct"], "100")
        cost_mock.assert_not_called()

    def test_sales_profit_lines_calculates_phantom_article_cost_from_canpre(self):
        db = FakeProfitDb([
            sale_row(
                DMV_TIPLIN="X",
                DMV_CODART="",
                DMV_DESCRI="Articulo fantasma",
                DMV_VALLINS=Decimal("100"),
                DMV_IMPDTO=Decimal("0"),
                DMV_CANPRE=Decimal("12"),
                DMV_CANTID=Decimal("2"),
            )
        ])
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.sales_profit_lines(fecha_desde="2026-01-01", fecha_hasta="2026-01-31")

        item = result["items"][0]
        self.assertEqual(item["coste"], "24")
        self.assertEqual(item["margen"], "76")
        self.assertEqual(item["rentabilidad_pct"], "76")

    def test_sales_profit_lines_calculates_phantom_article_cost_from_rentaf(self):
        db = FakeProfitDb([
            sale_row(
                DMV_TIPLIN="X",
                DMV_CODART="",
                DMV_DESCRI="Articulo fantasma",
                DMV_VALLINS=Decimal("100"),
                DMV_IMPDTO=Decimal("0"),
                DMV_CANPRE=Decimal("1"),
                DMV_CANTID=Decimal("1"),
            )
        ])
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.sales_profit_lines(fecha_desde="2026-01-01", fecha_hasta="2026-01-31")

        item = result["items"][0]
        self.assertAlmostEqual(Decimal(item["coste"]), Decimal("75"), places=6)
        self.assertAlmostEqual(Decimal(item["margen"]), Decimal("25"), places=6)
        self.assertAlmostEqual(Decimal(item["rentabilidad_pct"]), Decimal("25"), places=6)

    def test_sales_profit_lines_converts_phantom_article_sales_with_import_price_type(self):
        db = FakeProfitDb([
            sale_row(
                DMV_TIPLIN="X",
                DMV_CODART="",
                DMV_DESCRI="Articulo fantasma",
                DMV_VALLINS=Decimal("1000"),
                DMV_IMPDTO=Decimal("0"),
                DMV_CODMON="P",
                DMV_CANPRE=Decimal("1"),
                DMV_CANTID=Decimal("1"),
            )
        ])
        svc = faro_mcp.FaroPhase1Service(db)

        with patch.object(
            faro_mcp.FaroArticleService,
            "change_price_currency",
            return_value=Decimal("6.01"),
        ) as currency_mock:
            result = svc.sales_profit_lines(fecha_desde="2026-01-01", fecha_hasta="2026-01-31", moneda="E")

        currency_mock.assert_called_once_with(Decimal("1000"), "P", "E", "I")
        item = result["items"][0]
        self.assertEqual(item["venta_neta"], "6.01")
        self.assertAlmostEqual(Decimal(item["coste"]), Decimal("4.5075"), places=6)
        self.assertAlmostEqual(Decimal(item["margen"]), Decimal("1.5025"), places=6)

    def test_sales_profit_summary_groups_and_orders_by_family(self):
        rows = [
            sale_row(DMV_CODART="A", DMV_VALLINS=Decimal("100"), DMV_IMPDTO=Decimal("0"), DMV_CANTID=Decimal("2")),
            sale_row(DMV_CODART="B", DMV_VALLINS=Decimal("50"), DMV_IMPDTO=Decimal("0"), DMV_CANTID=Decimal("1")),
        ]
        db = FakeProfitDb(rows)
        svc = faro_mcp.FaroPhase1Service(db)

        with patch.object(
            faro_mcp.FaroArticleService,
            "article_cost_price",
            return_value={"precio_coste": "10"},
        ):
            result = svc.sales_profit_summary(
                {
                    "fecha_desde": "2026-01-01",
                    "fecha_hasta": "2026-01-31",
                    "agrupar_por": "familia",
                    "tipo_familia": "propia",
                    "ordenar_por": "margen",
                }
            )

        self.assertEqual(result["agrupar_por"], "familia")
        self.assertEqual(result["base_lineas"], 2)
        self.assertEqual(result["count"], 1)
        group = result["items"][0]
        self.assertEqual(group["codigo"], "4")
        self.assertEqual(group["nombre"], "Familia")
        self.assertEqual(Decimal(group["venta_neta"]), Decimal("150"))
        self.assertEqual(Decimal(group["coste"]), Decimal("30"))
        self.assertEqual(Decimal(group["margen"]), Decimal("120"))

    def test_sales_profit_summary_uses_ncc_family_by_default_and_allows_cooperative(self):
        rows = [
            sale_row(DMV_CODART="A", DMV_VALLINS=Decimal("100"), DMV_IMPDTO=Decimal("0")),
            sale_row(DMV_CODART="B", DMV_VALLINS=Decimal("50"), DMV_IMPDTO=Decimal("0")),
        ]
        db = FakeProfitDb(rows)
        svc = faro_mcp.FaroPhase1Service(db)

        with patch.object(
            faro_mcp.FaroArticleService,
            "article_cost_price",
            return_value={"precio_coste": "10"},
        ):
            default_result = svc.sales_profit_summary({
                "fecha_desde": "2026-01-01",
                "fecha_hasta": "2026-01-31",
                "agrupar_por": "familia",
            })
            cooperative_result = svc.sales_profit_summary({
                "fecha_desde": "2026-01-01",
                "fecha_hasta": "2026-01-31",
                "agrupar_por": "subfamilia",
                "tipo_familia": "cooperativa",
            })

        self.assertEqual(default_result["tipo_familia"], "ncc")
        self.assertEqual(default_result["items"][0]["codigo"], "12")
        self.assertEqual(default_result["items"][0]["nombre"], "Familia NCC")
        self.assertEqual(cooperative_result["tipo_familia"], "cooperativa")
        self.assertEqual(cooperative_result["items"][0]["codigo"], "14/18")
        self.assertEqual(cooperative_result["items"][0]["nombre"], "Subfamilia cooperativa")

    def test_sales_profit_alerts_distinguishes_negative_lines_from_aggregated_articles(self):
        rows = [
            sale_row(DMV_CODART="A", DMV_DESCRI="Articulo compensado", DMV_VALLINS=Decimal("100"), DMV_IMPDTO=Decimal("0"), DMV_CANTID=Decimal("1"), DMV_NUMLIN=10),
            sale_row(DMV_CODART="A", DMV_DESCRI="Articulo compensado", DMV_VALLINS=Decimal("10"), DMV_IMPDTO=Decimal("0"), DMV_CANTID=Decimal("1"), DMV_NUMLIN=20),
            sale_row(DMV_CODART="B", DMV_DESCRI="Articulo negativo", DMV_VALLINS=Decimal("20"), DMV_IMPDTO=Decimal("0"), DMV_CANTID=Decimal("1"), DMV_NUMLIN=30),
            sale_row(DMV_CODART="C", DMV_DESCRI="Articulo bajo margen", DMV_VALLINS=Decimal("100"), DMV_IMPDTO=Decimal("0"), DMV_CANTID=Decimal("1"), DMV_NUMLIN=40),
        ]
        db = FakeProfitDb(rows)
        svc = faro_mcp.FaroPhase1Service(db)

        def cost_price(codart, _fecha, _moneda):
            return {"precio_coste": {"A": "20", "B": "30", "C": "95"}[codart]}

        with patch.object(faro_mcp.FaroArticleService, "article_cost_price", side_effect=cost_price):
            result = svc.sales_profit_alerts({
                "fecha_desde": "2026-01-01",
                "fecha_hasta": "2026-01-31",
                "umbral_rentabilidad_baja": "10",
            })

        self.assertEqual(result["resumen_alertas"]["lineas_negativas"], 2)
        self.assertEqual(result["resumen_alertas"]["articulos_con_lineas_negativas"], 2)
        self.assertEqual(result["resumen_alertas"]["articulos_negativos_agregados"], 1)
        self.assertEqual(result["articulos_negativos_agregados"][0]["codigo"], "B")
        self.assertEqual(result["articulos_compensados"][0]["codigo"], "A")
        self.assertEqual(result["lineas_baja_rentabilidad"][0]["articulo"]["codigo"], "C")
        self.assertTrue(result["warnings"])

    def test_business_trends_compares_periods_and_defaults_to_ncc_family(self):
        svc = faro_mcp.FaroPhase1Service(FakeProfitDb([]))
        current = {
            "moneda": "E",
            "totales": {"lineas": 3, "unidades": "30", "venta_neta": "300", "coste": "180", "margen": "120", "rentabilidad_pct": "40"},
            "items": [
                {"codigo": "12", "nombre": "Familia NCC", "lineas": 1, "unidades": "10", "venta_neta": "200", "coste": "100", "margen": "100", "rentabilidad_pct": "50"},
                {"codigo": "34", "nombre": "Nueva", "lineas": 1, "unidades": "5", "venta_neta": "50", "coste": "25", "margen": "25", "rentabilidad_pct": "50"},
                {"codigo": "56", "nombre": "Cae margen", "lineas": 1, "unidades": "15", "venta_neta": "50", "coste": "55", "margen": "-5", "rentabilidad_pct": "-10"},
            ],
        }
        previous = {
            "moneda": "E",
            "totales": {"lineas": 3, "unidades": "25", "venta_neta": "250", "coste": "125", "margen": "125", "rentabilidad_pct": "50"},
            "items": [
                {"codigo": "12", "nombre": "Familia NCC", "lineas": 1, "unidades": "10", "venta_neta": "100", "coste": "50", "margen": "50", "rentabilidad_pct": "50"},
                {"codigo": "56", "nombre": "Cae margen", "lineas": 1, "unidades": "10", "venta_neta": "100", "coste": "50", "margen": "50", "rentabilidad_pct": "50"},
                {"codigo": "78", "nombre": "Desaparece", "lineas": 1, "unidades": "5", "venta_neta": "50", "coste": "25", "margen": "25", "rentabilidad_pct": "50"},
            ],
        }

        with patch.object(svc, "sales_profit_summary", side_effect=[current, previous]) as summary_mock:
            result = svc.business_trends({
                "fecha_desde": "2026-09-01",
                "fecha_hasta": "2026-09-30",
                "agrupar_por": "familia",
                "umbral_variacion_pct": "20",
            })

        self.assertEqual(result["tipo_familia"], "ncc")
        self.assertEqual(result["periodo_comparativo"]["fecha_desde"], "2026-08-02")
        self.assertEqual(result["periodo_comparativo"]["fecha_hasta"], "2026-08-31")
        self.assertEqual(result["suben"][0]["codigo"], "12")
        self.assertEqual(result["bajan"][0]["codigo"], "56")
        self.assertEqual(result["empeoran_rentabilidad"][0]["codigo"], "56")
        self.assertEqual(result["aparecen"][0]["codigo"], "34")
        self.assertEqual(result["desaparecen"][0]["codigo"], "78")
        self.assertEqual(summary_mock.call_args_list[0].args[0]["tipo_familia"], "ncc")

    def test_business_change_diagnosis_explains_family_drop(self):
        svc = faro_mcp.FaroPhase1Service(FakeProfitDb([sale_row()]))
        with patch.object(
            faro_mcp.FaroArticleService,
            "article_cost_price",
            return_value={"precio_coste": "10"},
        ):
            base_item = svc.sales_profit_lines(
                fecha_desde="2026-01-01",
                fecha_hasta="2026-01-01",
                limite=1,
            )["items"][0]

        current_items = [
            {
                **base_item,
                "venta_neta": "60",
                "coste": "55",
                "margen": "5",
                "rentabilidad_pct": "8.333333",
                "cantidad": "6",
            }
        ]
        previous_items = [
            {
                **current_items[0],
                "venta_neta": "120",
                "coste": "60",
                "margen": "60",
                "rentabilidad_pct": "50",
                "cantidad": "12",
            }
        ]
        current_items[0]["articulo"]["familia_ncc"]["familia"] = "12"
        current_items[0]["articulo"]["familia_ncc"]["familia_nombre"] = "Familia NCC"
        previous_items[0]["articulo"]["familia_ncc"]["familia"] = "12"
        previous_items[0]["articulo"]["familia_ncc"]["familia_nombre"] = "Familia NCC"
        current_items[0]["cantidad"] = "6"
        previous_items[0]["cantidad"] = "12"

        current = {
            "count": 1,
            "limite": 5000,
            "moneda": "E",
            "totales": svc._sales_profit_totals(current_items),
            "items": current_items,
        }
        previous = {
            "count": 1,
            "limite": 5000,
            "moneda": "E",
            "totales": svc._sales_profit_totals(previous_items),
            "items": previous_items,
        }

        with patch.object(svc, "sales_profit_lines", side_effect=[current, previous]):
            result = svc.business_change_diagnosis({
                "fecha_desde": "2026-09-01",
                "fecha_hasta": "2026-09-30",
                "agrupar_por": "familia",
                "codigo_grupo": "12",
            })

        self.assertEqual(result["tipo_familia"], "ncc")
        self.assertEqual(result["foco"]["codigo"], "12")
        self.assertEqual(result["diagnostico"]["motivo_principal"], "menos_unidades")
        self.assertEqual(result["diagnostico"]["variacion"]["venta_neta_delta"], "-60")
        self.assertEqual(result["articulos_que_explican_cambio"][0]["codigo"], "ART-1")

    def test_stock_rotation_flags_overstock_and_stock_without_sales(self):
        svc = faro_mcp.FaroPhase1Service(FakeProfitDb([]))
        stock_rows = [
            sale_row(
                ART_DESCRI="Articulo inmovilizado",
                ART_PRECOS=Decimal("5"),
                ARTE_CENTRO=7,
                ARTE_EXIST=Decimal("100"),
                ARTE_MINIMO=Decimal("0"),
                ARTE_MAXIMO=Decimal("10"),
                ARTE_FECCOM=date(2026, 8, 15),
                ARTE_FECVEN=date(2025, 1, 1),
                ARTE_FECMOV=date(2026, 8, 15),
            )
        ]
        stock_rows[0]["ART_CODART"] = "ART-1"
        sales = {"ART-1": {"codigo": "ART-1", "nombre": "Articulo inmovilizado", "lineas": 0, "unidades": "0", "venta_neta": "0", "coste": "0", "margen": "0", "rentabilidad_pct": "0"}}
        purchases = {"ART-1": {"unidades": "25", "importe": "125", "moneda": "E"}}

        with patch.object(svc, "_stock_analysis_rows", return_value=stock_rows), \
             patch.object(svc, "_stock_sales_totals", return_value=sales), \
             patch.object(svc, "_stock_purchase_totals", return_value=purchases):
            result = svc.stock_rotation_analysis({
                "fecha_desde": "2026-09-01",
                "fecha_hasta": "2026-09-30",
                "agrupar_por": "familia",
                "tipo_familia": "ncc",
            })

        self.assertEqual(result["tipo_familia"], "ncc")
        self.assertEqual(result["totales"]["valor_stock"], "500")
        self.assertEqual(result["stock_sin_ventas"][0]["articulo"]["codigo"], "ART-1")
        self.assertIn("compra_sin_salida", result["stock_sin_ventas"][0]["alertas"])

    def test_stock_trends_detects_stock_up_and_sales_down(self):
        svc = faro_mcp.FaroPhase1Service(FakeProfitDb([]))
        article = {"codigo": "ART-1", "descripcion": "Articulo"}
        current = {
            "items": [{
                "articulo": article,
                "stock_actual": "100",
                "valor_stock": "500",
                "ventas_periodo": {"venta_neta": "10", "margen": "1"},
                "compras_periodo": {"unidades": "20"},
                "alertas": [],
            }],
            "totales": {"articulos": 1, "valor_stock": "500"},
            "tipo_familia": "ncc",
            "warnings": [],
        }
        previous = {
            "items": [{
                "articulo": article,
                "stock_actual": "50",
                "valor_stock": "250",
                "ventas_periodo": {"venta_neta": "100", "margen": "40"},
                "compras_periodo": {"unidades": "0"},
                "alertas": [],
            }],
            "totales": {"articulos": 1, "valor_stock": "250"},
            "tipo_familia": "ncc",
            "warnings": [],
        }

        with patch.object(svc, "_stock_rotation_items", side_effect=[current, previous]):
            result = svc.stock_trends_analysis({
                "fecha_desde": "2026-09-01",
                "fecha_hasta": "2026-09-30",
            })

        self.assertEqual(result["resumen"]["stock_sube_ventas_bajan"], 1)
        self.assertEqual(result["stock_sube_ventas_bajan"][0]["articulo"]["codigo"], "ART-1")
        self.assertEqual(result["stock_sube_ventas_bajan"][0]["valor_stock_delta"], "250")

    def test_customer_risk_analysis_detects_drop_disappearance_and_negative_profit(self):
        svc = faro_mcp.FaroPhase1Service(FakeProfitDb([]))
        current = {
            "moneda": "E",
            "totales": {"lineas": 2, "unidades": "2", "venta_neta": "80", "coste": "100", "margen": "-20", "rentabilidad_pct": "-25"},
            "items": [
                {"codigo": "10/0", "nombre": "Cliente baja", "lineas": 1, "unidades": "1", "venta_neta": "80", "coste": "100", "margen": "-20", "rentabilidad_pct": "-25"},
            ],
        }
        previous = {
            "moneda": "E",
            "totales": {"lineas": 2, "unidades": "2", "venta_neta": "300", "coste": "180", "margen": "120", "rentabilidad_pct": "40"},
            "items": [
                {"codigo": "10/0", "nombre": "Cliente baja", "lineas": 1, "unidades": "1", "venta_neta": "200", "coste": "100", "margen": "100", "rentabilidad_pct": "50"},
                {"codigo": "20/0", "nombre": "Cliente desaparece", "lineas": 1, "unidades": "1", "venta_neta": "100", "coste": "80", "margen": "20", "rentabilidad_pct": "20"},
            ],
        }

        with patch.object(svc, "sales_profit_summary", side_effect=[current, previous]):
            result = svc.customer_risk_analysis({
                "fecha_desde": "2026-09-01",
                "fecha_hasta": "2026-09-30",
                "venta_minima": "0",
            })

        self.assertEqual(result["resumen_clientes"]["clientes_desaparecen"], 1)
        self.assertEqual(result["resumen_clientes"]["clientes_rentabilidad_negativa"], 1)
        self.assertEqual(result["clientes_desaparecen"][0]["codigo"], "20/0")
        self.assertEqual(result["clientes_rentabilidad_negativa"][0]["codigo"], "10/0")
        self.assertIn("baja_ventas", result["clientes_bajan"][0]["motivos"])

    def test_business_dashboard_summary_combines_core_blocks(self):
        svc = faro_mcp.FaroPhase1Service(FakeProfitDb([]))
        trends = {
            "moneda": "E",
            "totales_actual": {"venta_neta": "80", "margen": "10", "rentabilidad_pct": "12.5"},
            "totales_comparativo": {"venta_neta": "100", "margen": "20", "rentabilidad_pct": "20"},
            "variacion_totales": {"venta_neta_delta": "-20", "rentabilidad_pct_delta": "-7.5"},
            "bajan": [{"codigo": "12"}],
            "suben": [],
            "warnings": [],
        }
        alerts = {
            "resumen_alertas": {"lineas_negativas": 1, "articulos_negativos_agregados": 1},
            "lineas_negativas": [{"articulo": {"codigo": "A"}}],
            "articulos_negativos_agregados": [{"codigo": "A"}],
            "articulos_compensados": [],
            "warnings": [],
        }
        customers = {
            "resumen_clientes": {"clientes_en_riesgo": 2},
            "clientes_riesgo": [{"codigo": "10/0"}],
            "warnings": [],
        }
        stock = {
            "totales": {"valor_stock": "500"},
            "stock_sin_ventas": [{"articulo": {"codigo": "S"}}],
            "sobrestock": [],
            "compra_sin_salida": [],
            "warnings": ["stock warning"],
        }

        with patch.object(svc, "business_trends", return_value=trends), \
             patch.object(svc, "sales_profit_alerts", return_value=alerts), \
             patch.object(svc, "customer_risk_analysis", return_value=customers), \
             patch.object(svc, "stock_rotation_analysis", return_value=stock):
            result = svc.business_dashboard_summary({
                "fecha_desde": "2026-09-01",
                "fecha_hasta": "2026-09-30",
            })

        self.assertEqual(result["kpis"]["ventas"]["actual"]["venta_neta"], "80")
        self.assertEqual(result["kpis"]["clientes"]["clientes_en_riesgo"], 2)
        self.assertEqual(result["kpis"]["stock"]["valor_stock"], "500")
        self.assertEqual([item["tipo"] for item in result["insights"]], [
            "ventas_bajan",
            "rentabilidad_baja",
            "lineas_negativas",
            "clientes_en_riesgo",
            "stock_sin_ventas",
        ])
        self.assertEqual(result["warnings"], ["stock warning"])

    def test_dashboard_recommended_actions_combines_action_blocks(self):
        svc = faro_mcp.FaroPhase1Service(FakeProfitDb([]))
        sales = {
            "filtros": {"periodo": {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"}},
            "lineas_negativas": [{
                "articulo": {"codigo": "A1", "descripcion": "Articulo negativo"},
                "documento": {"tipo": "F", "numero": 1},
                "cliente": {"codigo": 10, "subcliente": 0},
                "venta_neta": "100",
                "coste": "130",
                "margen": "-30",
                "rentabilidad_pct": "-30",
            }],
            "articulos_negativos_agregados": [],
            "warnings": [],
        }
        customers = {
            "periodo_actual": {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"},
            "clientes_riesgo": [{
                "codigo": "10/0",
                "nombre": "Cliente baja",
                "riesgo": 75,
                "motivos": ["baja_ventas", "baja_ventas_fuerte"],
                "actual": {"venta_neta": "100", "margen": "10"},
                "comparativo": {"venta_neta": "300", "margen": "80"},
                "variacion": {"venta_neta_delta": "-200"},
                "participacion_ventas_pct": "12",
            }],
            "warnings": [],
        }
        stock = {
            "periodo": {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"},
            "stock_sin_ventas": [{
                "articulo": {"codigo": "S1", "descripcion": "Stock parado"},
                "proveedor": {"codigo": 44, "nombre": "Proveedor"},
                "stock_actual": "10",
                "valor_stock": "500",
                "ventas_periodo": {"venta_neta": "0"},
                "compras_periodo": {"unidades": "0"},
                "alertas": ["stock_sin_ventas"],
            }],
            "sobrestock": [],
            "compra_sin_salida": [],
            "warnings": [],
        }
        orders = {
            "periodo": {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"},
            "items": [{"codigo": "P", "nombre": "Pedidos", "documentos": 2, "total": "400", "pendiente": "400", "cobrado": "0"}],
            "warnings": [],
        }
        documents = {
            "periodo": {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"},
            "items": [{"codigo": "A", "nombre": "Albaranes", "documentos": 1, "total": "250", "pendiente": "250", "cobrado": "0"}],
            "avisos": [],
        }
        treasury = {
            "periodo": {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"},
            "totales": {"saldo": "35", "saldo_cierre": "30"},
            "operaciones": [{
                "centro": 7,
                "caja": 1,
                "linea": 2,
                "fecha": "2026-09-02",
                "tipo_operacion": "E",
                "importe": "50",
                "forma_pago": "E",
                "documento": {"numero_efecto": 0},
                "cliente": {"codigo": 10, "subcliente": 0},
            }],
            "warnings": [],
        }

        with patch.object(svc, "sales_profit_alerts", return_value=sales), \
             patch.object(svc, "customer_risk_analysis", return_value=customers), \
             patch.object(svc, "stock_rotation_analysis", return_value=stock), \
             patch.object(svc, "pending_orders_dashboard_summary", return_value=orders), \
             patch.object(svc, "pending_documents_dashboard_summary", return_value=documents), \
             patch.object(svc, "treasury_dashboard_summary", return_value=treasury):
            result = svc.dashboard_recommended_actions({
                "fecha_desde": "2026-09-01",
                "fecha_hasta": "2026-09-30",
                "limite_acciones": 10,
            })

        action_types = {item["tipo"] for item in result["acciones"]}
        self.assertIn("linea_margen_negativo", action_types)
        self.assertIn("cliente_en_caida", action_types)
        self.assertIn("stock_parado", action_types)
        self.assertIn("pedido_o_presupuesto_pendiente", action_types)
        self.assertIn("documento_pendiente", action_types)
        self.assertIn("cierre_caja_difiere_saldo_movimientos", action_types)
        self.assertIn("operacion_caja_sin_efecto", action_types)
        self.assertEqual(result["resumen"]["acciones_devuelve"], 7)

    def test_purchase_orders_pending_summary_aggregates_caborc_detorc(self):
        rows = [
            {
                "COC_CENTRO": 7, "COC_EJERCI": 2026, "COC_SERIE": "OC", "COC_NUMDOC": 1,
                "COC_FECHA": date(2026, 9, 1), "COC_CODPRO": 44, "COC_NOMPRO": "Proveedor",
                "COC_SITUAC": "P", "COC_IMPPEN": Decimal("30"),
                "DOC_NUMLIN": 10, "DOC_CODART": "A1", "DOC_DESCRI": "Articulo 1",
                "DOC_CANPEN": Decimal("2"), "DOC_VALPEN": Decimal("20"), "DOC_SITUAC": "A",
            },
            {
                "COC_CENTRO": 7, "COC_EJERCI": 2026, "COC_SERIE": "OC", "COC_NUMDOC": 1,
                "COC_FECHA": date(2026, 9, 1), "COC_CODPRO": 44, "COC_NOMPRO": "Proveedor",
                "COC_SITUAC": "P", "COC_IMPPEN": Decimal("30"),
                "DOC_NUMLIN": 20, "DOC_CODART": "A2", "DOC_DESCRI": "Articulo 2",
                "DOC_CANPEN": Decimal("1"), "DOC_VALPEN": Decimal("10"), "DOC_SITUAC": "A",
            },
        ]
        db = FakeDashboardDb(rows)
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.purchase_orders_pending_summary({"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"})

        self.assertIn("FROM CABORC C, DETORC D", db.last_sql)
        self.assertEqual(result["totales"]["pedidos"], 1)
        self.assertEqual(result["totales"]["lineas"], 2)
        self.assertEqual(result["totales"]["valor_pendiente"], "30")
        self.assertEqual(result["proveedores"][0]["pedidos"], 1)
        self.assertEqual(result["pedidos"][0]["unidades_pendientes"], "3")

    def test_purchase_items_pending_receipt_summary_groups_by_article(self):
        svc = faro_mcp.FaroPhase1Service(FakeDashboardDb([]))
        orders = {
            "periodo": {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"},
            "filtros": {"situacion": "P", "solo_pendiente": True},
            "pedidos": [
                {
                    "centro": 7,
                    "ejercicio": 2026,
                    "serie": "OC",
                    "numero": 1,
                    "fecha": "2026-09-01",
                    "proveedor": {"codigo": 44, "nombre": "Proveedor"},
                    "lineas": [
                        {"linea": 10, "articulo": "A1", "descripcion": "Articulo 1", "cantidad_pendiente": "2", "valor_pendiente": "20", "situacion": "A"},
                        {"linea": 20, "articulo": "A2", "descripcion": "Articulo 2", "cantidad_pendiente": "1", "valor_pendiente": "10", "situacion": "A"},
                    ],
                },
                {
                    "centro": 7,
                    "ejercicio": 2026,
                    "serie": "OC",
                    "numero": 2,
                    "fecha": "2026-09-05",
                    "proveedor": {"codigo": 45, "nombre": "Proveedor 2"},
                    "lineas": [
                        {"linea": 10, "articulo": "A1", "descripcion": "Articulo 1", "cantidad_pendiente": "3", "valor_pendiente": "45", "situacion": "A"},
                    ],
                },
            ],
        }

        with patch.object(svc, "purchase_orders_pending_summary", return_value=orders) as orders_mock:
            result = svc.purchase_items_pending_receipt_summary({
                "fecha_desde": "2026-09-01",
                "fecha_hasta": "2026-09-30",
                "limite": 10,
            })

        orders_mock.assert_called_once()
        self.assertEqual(result["totales"]["articulos"], 2)
        self.assertEqual(result["totales"]["cantidad_pendiente"], "6")
        self.assertEqual(result["totales"]["valor_pendiente"], "75")
        article = result["articulos"][0]
        self.assertEqual(article["articulo"], "A1")
        self.assertEqual(article["cantidad_pendiente"], "5")
        self.assertEqual(article["valor_pendiente"], "65")
        self.assertEqual(len(article["proveedores"]), 2)
        self.assertEqual(article["primera_fecha_pedido"], "2026-09-01")

    def test_purchase_stock_minimum_proposal_uses_genpedm_quantities_and_package_rounding(self):
        rows = [{
            "ART_CODART": "A1", "ART_DESCRI": "Articulo 1", "ART_UNIMED": "UN",
            "ART_CODPRO": 44, "ART_INDPROP": "S",
            "ARTP_CODART": "A1", "ARTP_CODPRO": 44, "ARTP_REFPRO": "R-A1",
            "ARTP_DESCRI": "Articulo 1 proveedor", "ARTP_UNIMED": "CJ",
            "ARTP_CANCON": Decimal("2"), "ARTP_CANVEN": Decimal("1"),
            "ARTP_UNIPAQ": Decimal("5"), "ARTP_AJUSTE": "S",
            "ARTP_PREBAS": Decimal("10"), "ARTP_DTOAUM1": Decimal("10"),
            "ARTP_DTOAUM2": Decimal("0"), "ARTP_DTOAUM3": Decimal("0"),
            "ARTP_DTOAUM4": Decimal("0"), "ARTP_DTOAUM5": Decimal("0"),
            "ARTP_DTOAUM6": Decimal("0"), "PRO_NOMCOR": "Proveedor 44",
        }]
        db = FakePurchaseProposalDb(rows, {
            "A1": {
                "existencias": Decimal("3"),
                "faltas": Decimal("1"),
                "pedidos_proveedor": Decimal("4"),
                "pedidos_cliente": Decimal("99"),
                "stock_minimo": Decimal("10"),
                "stock_maximo": Decimal("20"),
            }
        })
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.purchase_stock_minimum_proposal({
            "centro": 7,
            "proveedor": 44,
            "pedir_hasta_maximo": True,
            "unidades_paquete": True,
        })

        self.assertIn("FROM ARTICUL A", db.last_sql)
        self.assertEqual(result["origen"], "GENPEDM")
        self.assertEqual(result["totales"]["lineas"], 1)
        line = result["lineas"][0]
        self.assertEqual(line["cantidad_sugerida"], "15.0")
        self.assertEqual(line["cantidad_compra"], "30")
        self.assertEqual(line["valor_estimado"], "270.0")
        self.assertEqual(line["stock"]["stock_a_termino"], "6")
        self.assertIn("hasta_stock_maximo", line["motivos"])
        self.assertIn("redondeo_paquete", line["motivos"])

    def test_purchase_customer_orders_proposal_uses_genpedc_net_customer_demand(self):
        rows = [{
            "CBV_CENTRO": 7, "CBV_EJERCI": 2026, "CBV_SERIE": "P", "CBV_NUMDOC": 9,
            "CBV_FECHA": date(2026, 9, 10), "CBV_CODCLI": 12, "CBV_SUBCLI": 0,
            "CBV_NOMCLI": "Cliente", "DMV_NUMLIN": 10, "DMV_TIPLIN": "D",
            "DMV_CODART": "A2", "DMV_DESCRI": "Articulo 2", "DMV_CANTID": Decimal("7"),
            "ART_CODART": "A2", "ART_DESCRI": "Articulo 2", "ART_UNIMED": "UN",
            "ART_CODPRO": 55, "ART_INDPROP": "S",
            "ARTP_CODART": "A2", "ARTP_CODPRO": 55, "ARTP_REFPRO": "R-A2",
            "ARTP_DESCRI": "Articulo 2 proveedor", "ARTP_UNIMED": "UN",
            "ARTP_CANCON": Decimal("1"), "ARTP_CANVEN": Decimal("1"),
            "ARTP_UNIPAQ": Decimal("4"), "ARTP_AJUSTE": "S",
            "ARTP_PREBAS": Decimal("3"), "ARTP_DTOAUM1": Decimal("0"),
            "ARTP_DTOAUM2": Decimal("0"), "ARTP_DTOAUM3": Decimal("0"),
            "ARTP_DTOAUM4": Decimal("0"), "ARTP_DTOAUM5": Decimal("0"),
            "ARTP_DTOAUM6": Decimal("0"), "PRO_NOMCOR": "Proveedor 55",
        }]
        db = FakePurchaseProposalDb(rows, {
            "A2": {
                "existencias": Decimal("1"),
                "faltas": Decimal("0"),
                "pedidos_proveedor": Decimal("0"),
                "pedidos_cliente": Decimal("7"),
                "stock_minimo": Decimal("0"),
                "stock_maximo": Decimal("0"),
            }
        })
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.purchase_customer_orders_proposal({"centro": 7, "proveedor": 55})

        self.assertIn("FROM CABDOCV C", db.last_sql)
        self.assertEqual(result["origen"], "GENPEDC")
        line = result["lineas"][0]
        self.assertEqual(line["cantidad_sugerida"], "8")
        self.assertEqual(line["cantidad_compra"], "8")
        self.assertEqual(line["valor_estimado"], "24")
        self.assertEqual(line["stock"]["stock_a_termino"], "-6")
        self.assertEqual(line["pedido_origen"]["numero"], 9)
        self.assertIn("pedido_cliente_sin_stock", line["motivos"])

    def test_purchase_documents_pending_summary_reads_cabdocm(self):
        rows = [{
            "CBM_CENTRO": 7, "CBM_EJERCI": 2026, "CBM_SERIE": "E", "CBM_NUMDOC": 3,
            "CBM_FECHA": date(2026, 9, 2), "CBM_FECREC": date(2026, 9, 3),
            "CBM_CODPRO": 44, "CBM_NOMPRO": "Proveedor", "CBM_ALBPRO": "ALB",
            "CBM_FACPRO": "", "CBM_FECFAC": None, "CBM_CODMON": "E",
            "CBM_TOTALD": Decimal("121"), "CBM_TOTALS": Decimal("100"), "CBM_SITUAC": "P",
        }]
        db = FakeDashboardDb(rows)
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.purchase_documents_pending_summary({"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"})

        self.assertIn("FROM CABDOCM", db.last_sql)
        self.assertEqual(result["totales"], {"documentos": 1, "base": "100", "total": "121"})
        self.assertEqual(result["situaciones"][0]["situacion"], "P")
        self.assertEqual(result["documentos"][0]["albaran_proveedor"], "ALB")

    def test_treasury_dashboard_summary_reads_opecaj(self):
        rows = [
            {
                "OPC_CENTRO": 7, "OPC_EJERCI": 2026, "OPC_CAJA": 1, "OPC_NUMLIN": 1,
                "OPC_VENDED": "USR", "OPC_HORA": date(2026, 9, 2), "OPC_TIPOPE": "E",
                "OPC_IMPORT": Decimal("50"), "OPC_CODMON": "E", "OPC_FORPAG": "EF",
                "OPC_OBSERV": "Cobro", "OPC_TIPDOC": "F", "OPC_TIPAC": "0",
                "OPC_EJEDOC": 2026, "OPC_SERIE": "A", "OPC_NUMDOC": 10, "OPC_NUMORD": 25,
                "OPC_CODCLI": 1, "OPC_SUBCLI": 0, "OPC_SITUAC": 0, "OPC_FECSIT": date(2026, 9, 2),
            },
            {
                "OPC_CENTRO": 7, "OPC_EJERCI": 2026, "OPC_CAJA": 1, "OPC_NUMLIN": 2,
                "OPC_VENDED": "USR", "OPC_HORA": date(2026, 9, 2), "OPC_TIPOPE": "S",
                "OPC_IMPORT": Decimal("15"), "OPC_CODMON": "E", "OPC_FORPAG": "EF",
                "OPC_OBSERV": "Pago", "OPC_TIPDOC": "", "OPC_TIPAC": "",
                "OPC_EJEDOC": 0, "OPC_SERIE": "", "OPC_NUMDOC": 0, "OPC_NUMORD": 0,
                "OPC_CODCLI": 0, "OPC_SUBCLI": 0, "OPC_SITUAC": 0, "OPC_FECSIT": date(2026, 9, 2),
            },
            {
                "OPC_CENTRO": 7, "OPC_EJERCI": 2026, "OPC_CAJA": 1, "OPC_NUMLIN": 3,
                "OPC_VENDED": "USR", "OPC_HORA": date(2026, 9, 2), "OPC_TIPOPE": "C",
                "OPC_IMPORT": Decimal("35"), "OPC_CODMON": "E", "OPC_FORPAG": "",
                "OPC_OBSERV": "Cierre", "OPC_TIPDOC": "", "OPC_TIPAC": "",
                "OPC_EJEDOC": 0, "OPC_SERIE": "", "OPC_NUMDOC": 0, "OPC_NUMORD": 0,
                "OPC_CODCLI": 0, "OPC_SUBCLI": 0, "OPC_SITUAC": 0, "OPC_FECSIT": date(2026, 9, 2),
            },
        ]
        db = FakeDashboardDb(rows)
        svc = faro_mcp.FaroPhase1Service(db)

        result = svc.treasury_dashboard_summary({"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"})

        self.assertIn("FROM OPECAJ", db.last_sql)
        self.assertEqual(result["totales"]["entradas"], "50")
        self.assertEqual(result["totales"]["salidas"], "15")
        self.assertEqual(result["totales"]["saldo"], "35")
        self.assertEqual(result["totales"]["cierres"], "35")
        self.assertEqual(result["totales"]["saldo_cierre"], "35")
        self.assertEqual(result["operaciones"][0]["documento"]["numero_efecto"], 25)
        self.assertEqual(result["por_forma_pago"][0]["forma_pago"], "EF")


class SalesProfitRuntimeTests(unittest.TestCase):
    def test_runtime_exposes_sales_profit_tools_as_read_only_core_tools(self):
        self.assertIn("negocio_clientes_riesgo", faro_mcp.CORE_PUBLIC_TOOL_NAMES)
        self.assertIn("negocio_clientes_riesgo", faro_mcp.READ_ONLY_TOOL_NAMES)
        self.assertIn("negocio_cuadro_mando", faro_mcp.CORE_PUBLIC_TOOL_NAMES)
        self.assertIn("negocio_cuadro_mando", faro_mcp.READ_ONLY_TOOL_NAMES)
        self.assertIn("negocio_diagnostico_cambios", faro_mcp.CORE_PUBLIC_TOOL_NAMES)
        self.assertIn("negocio_diagnostico_cambios", faro_mcp.READ_ONLY_TOOL_NAMES)
        self.assertIn("negocio_stock_rotacion", faro_mcp.CORE_PUBLIC_TOOL_NAMES)
        self.assertIn("negocio_stock_rotacion", faro_mcp.READ_ONLY_TOOL_NAMES)
        self.assertIn("negocio_stock_tendencias", faro_mcp.CORE_PUBLIC_TOOL_NAMES)
        self.assertIn("negocio_stock_tendencias", faro_mcp.READ_ONLY_TOOL_NAMES)
        self.assertIn("negocio_tendencias", faro_mcp.CORE_PUBLIC_TOOL_NAMES)
        self.assertIn("negocio_tendencias", faro_mcp.READ_ONLY_TOOL_NAMES)
        for name in (
            "dashboard_resumen",
            "dashboard_acciones_recomendadas",
            "dashboard_series_temporales",
            "dashboard_alertas",
            "dashboard_filtros",
            "ventas_acciones_recomendadas",
            "ventas_resumen",
            "compras_resumen",
            "compras_articulos_pendientes_recibir",
            "compras_pedidos_pendientes_resumen",
            "compras_documentos_pendientes_resumen",
            "orden_compra_propuesta_stock_minimo",
            "orden_compra_propuesta_pedidos_cliente",
            "stock_acciones_recomendadas",
            "stock_resumen",
            "pedidos_acciones_recomendadas",
            "pedidos_resumen",
            "documentos_pendientes_resumen",
            "clientes_acciones_recomendadas",
            "clientes_resumen",
            "proveedores_resumen",
            "tesoreria_acciones_recomendadas",
            "tesoreria_resumen",
        ):
            with self.subTest(tool=name):
                self.assertIn(name, faro_mcp.CORE_PUBLIC_TOOL_NAMES)
                self.assertIn(name, faro_mcp.READ_ONLY_TOOL_NAMES)
        self.assertIn("venta_alertas_rentabilidad", faro_mcp.CORE_PUBLIC_TOOL_NAMES)
        self.assertIn("venta_alertas_rentabilidad", faro_mcp.READ_ONLY_TOOL_NAMES)
        self.assertIn("venta_rentabilidad_lineas", faro_mcp.CORE_PUBLIC_TOOL_NAMES)
        self.assertIn("venta_rentabilidad_resumen", faro_mcp.CORE_PUBLIC_TOOL_NAMES)
        self.assertIn("venta_rentabilidad_lineas", faro_mcp.READ_ONLY_TOOL_NAMES)
        self.assertIn("venta_rentabilidad_resumen", faro_mcp.READ_ONLY_TOOL_NAMES)

    def test_runtime_delegates_sales_profit_lines_and_closes_service(self):
        runtime = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.sales_profit_lines.return_value = {"count": 0, "items": []}
        svc.db.close = Mock()

        with patch.object(runtime, "phase1_service", return_value=svc):
            result = runtime.tool_venta_rentabilidad_lineas({"fecha_desde": "2026-01-01", "fecha_hasta": "2026-01-31"})

        self.assertEqual(result, {"count": 0, "items": []})
        svc.sales_profit_lines.assert_called_once_with(fecha_desde="2026-01-01", fecha_hasta="2026-01-31")
        svc.db.close.assert_called_once()

    def test_runtime_delegates_customer_risk_and_closes_service(self):
        runtime = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.customer_risk_analysis.return_value = {"resumen_clientes": {}}
        svc.db.close = Mock()

        args = {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"}
        with patch.object(runtime, "phase1_service", return_value=svc):
            result = runtime.tool_negocio_clientes_riesgo(args)

        self.assertEqual(result, {"resumen_clientes": {}})
        svc.customer_risk_analysis.assert_called_once_with(args)
        svc.db.close.assert_called_once()

    def test_runtime_delegates_dashboard_summary_and_closes_service(self):
        runtime = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.business_dashboard_summary.return_value = {"kpis": {}}
        svc.db.close = Mock()

        args = {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"}
        with patch.object(runtime, "phase1_service", return_value=svc):
            result = runtime.tool_negocio_cuadro_mando(args)

        self.assertEqual(result, {"kpis": {}})
        svc.business_dashboard_summary.assert_called_once_with(args)
        svc.db.close.assert_called_once()

    def test_runtime_delegates_dashboard_facades_and_closes_service(self):
        runtime = faro_mcp.FaroToolRuntime()
        args = {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"}
        cases = {
            "tool_dashboard_resumen": ("business_dashboard_summary", {"kpis": {}}),
            "tool_dashboard_acciones_recomendadas": ("dashboard_recommended_actions", {"acciones": []}),
            "tool_dashboard_series_temporales": ("dashboard_time_series", {"ventas": {}}),
            "tool_dashboard_alertas": ("dashboard_alerts", {"items": []}),
            "tool_ventas_acciones_recomendadas": ("sales_recommended_actions", {"acciones": []}),
            "tool_ventas_resumen": ("sales_dashboard_summary", {"rentabilidad": {}}),
            "tool_compras_resumen": ("purchases_dashboard_summary", {"items": []}),
            "tool_compras_articulos_pendientes_recibir": ("purchase_items_pending_receipt_summary", {"articulos": []}),
            "tool_compras_pedidos_pendientes_resumen": ("purchase_orders_pending_summary", {"pedidos": []}),
            "tool_compras_documentos_pendientes_resumen": ("purchase_documents_pending_summary", {"documentos": []}),
            "tool_orden_compra_propuesta_stock_minimo": ("purchase_stock_minimum_proposal", {"lineas": []}),
            "tool_orden_compra_propuesta_pedidos_cliente": ("purchase_customer_orders_proposal", {"lineas": []}),
            "tool_stock_acciones_recomendadas": ("stock_recommended_actions", {"acciones": []}),
            "tool_stock_resumen": ("stock_dashboard_summary", {"totales": {}}),
            "tool_pedidos_acciones_recomendadas": ("pending_recommended_actions", {"acciones": []}),
            "tool_pedidos_resumen": ("pending_orders_dashboard_summary", {"items": []}),
            "tool_documentos_pendientes_resumen": ("pending_documents_dashboard_summary", {"items": []}),
            "tool_clientes_acciones_recomendadas": ("customers_recommended_actions", {"acciones": []}),
            "tool_clientes_resumen": ("customers_dashboard_summary", {"clientes_riesgo": []}),
            "tool_proveedores_resumen": ("providers_dashboard_summary", {"compras_por_proveedor": {}}),
            "tool_tesoreria_acciones_recomendadas": ("treasury_recommended_actions", {"acciones": []}),
            "tool_tesoreria_resumen": ("treasury_dashboard_summary", {"operaciones": []}),
        }
        for tool_method, (service_method, expected) in cases.items():
            with self.subTest(tool=tool_method):
                svc = Mock()
                getattr(svc, service_method).return_value = expected
                svc.db.close = Mock()
                with patch.object(runtime, "phase1_service", return_value=svc):
                    result = getattr(runtime, tool_method)(args)
                self.assertEqual(result, expected)
                getattr(svc, service_method).assert_called_once_with(args)
                svc.db.close.assert_called_once()

    def test_runtime_delegates_dashboard_filters_and_closes_service(self):
        runtime = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.dashboard_filters.return_value = {"marcas": {"items": []}}
        svc.db.close = Mock()

        args = {"incluir": ["marcas"]}
        with patch.object(runtime, "phase1_service", return_value=svc):
            result = runtime.tool_dashboard_filtros(args)

        self.assertEqual(result, {"marcas": {"items": []}})
        svc.dashboard_filters.assert_called_once_with(args)
        svc.db.close.assert_called_once()

    def test_runtime_delegates_sales_profit_alerts_and_closes_service(self):
        runtime = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.sales_profit_alerts.return_value = {"base_lineas": 0, "items": []}
        svc.db.close = Mock()

        args = {"fecha_desde": "2026-01-01", "fecha_hasta": "2026-01-31"}
        with patch.object(runtime, "phase1_service", return_value=svc):
            result = runtime.tool_venta_alertas_rentabilidad(args)

        self.assertEqual(result, {"base_lineas": 0, "items": []})
        svc.sales_profit_alerts.assert_called_once_with(args)
        svc.db.close.assert_called_once()

    def test_runtime_delegates_business_trends_and_closes_service(self):
        runtime = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.business_trends.return_value = {"resumen_tendencias": {}}
        svc.db.close = Mock()

        args = {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"}
        with patch.object(runtime, "phase1_service", return_value=svc):
            result = runtime.tool_negocio_tendencias(args)

        self.assertEqual(result, {"resumen_tendencias": {}})
        svc.business_trends.assert_called_once_with(args)
        svc.db.close.assert_called_once()

    def test_runtime_delegates_business_change_diagnosis_and_closes_service(self):
        runtime = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.business_change_diagnosis.return_value = {"diagnostico": {}}
        svc.db.close = Mock()

        args = {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"}
        with patch.object(runtime, "phase1_service", return_value=svc):
            result = runtime.tool_negocio_diagnostico_cambios(args)

        self.assertEqual(result, {"diagnostico": {}})
        svc.business_change_diagnosis.assert_called_once_with(args)
        svc.db.close.assert_called_once()

    def test_runtime_delegates_stock_rotation_and_trends_and_closes_service(self):
        runtime = faro_mcp.FaroToolRuntime()
        svc = Mock()
        svc.stock_rotation_analysis.return_value = {"totales": {}}
        svc.stock_trends_analysis.return_value = {"resumen": {}}
        svc.db.close = Mock()

        args = {"fecha_desde": "2026-09-01", "fecha_hasta": "2026-09-30"}
        with patch.object(runtime, "phase1_service", return_value=svc):
            rotation = runtime.tool_negocio_stock_rotacion(args)
        self.assertEqual(rotation, {"totales": {}})
        svc.stock_rotation_analysis.assert_called_once_with(args)
        svc.db.close.assert_called_once()

        svc.db.close = Mock()
        with patch.object(runtime, "phase1_service", return_value=svc):
            trends = runtime.tool_negocio_stock_tendencias(args)
        self.assertEqual(trends, {"resumen": {}})
        svc.stock_trends_analysis.assert_called_once_with(args)
        svc.db.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
