from __future__ import annotations

import re

from scripts import mcp_tester_web


def _page() -> str:
    return mcp_tester_web.PAGE_HTML


def test_supplier_tariff_has_dedicated_line_editor() -> None:
    html = _page()
    assert "buildSupplierTariffLinesField" in html
    assert "supplierTariffAddLine" in html
    assert "data-tariff-hidden" in html
    assert "+ Añadir línea" in html
    for label in (
        "Artículo",
        "EAN / código barras",
        "Ref. proveedor",
        "Precio base *",
        "Dto. 1 %",
        "Dto. 6 %",
        "Conversión compra",
        "Unidades paquete",
    ):
        assert label in html


def test_supplier_tariff_sample_is_read_only_until_execute() -> None:
    html = _page()
    assert "fillSupplierTariffSampleData" in html
    assert "articulo_compra_consultar" in html
    assert "Los datos de prueba solo rellenan el formulario" in html
    assert "no modifican la base de datos hasta pulsar \"Ejecutar\"" in html


def test_critical_tools_have_a_distinct_visual_category() -> None:
    html = _page()
    assert "Crítica</span>" in html
    assert "includes('CRITICA')" in html
    assert "{kind: 'critical', label: 'Crítica', icon: 'write'}" in html


def test_supplier_tariff_result_defaults_to_summary_and_grid() -> None:
    html = _page()
    assert "supplierTariffSummary" in html
    assert "supplierTariffGridRows" in html
    assert "data.resultados" in html
    assert "name === 'tarifa_proveedor_actualizar'" in html
    assert all(label in html for label in ("Líneas", "Altas", "Modificaciones", "PVP actualizados"))


def test_embedded_javascript_block_is_present_and_balanced_enough_for_static_regression() -> None:
    # No imponemos Node como dependencia de la suite, pero protegemos al menos
    # que la pagina conserve exactamente un bloque principal de JavaScript y
    # las funciones de la Fase 8 dentro de el.
    blocks = re.findall(r"<script>(.*?)</script>", _page(), flags=re.S)
    assert len(blocks) == 1
    script = blocks[0]
    assert "function buildSupplierTariffLinesField" in script
    assert "function showResult" in script
