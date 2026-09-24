from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from textwrap import shorten

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    Flowable,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import faro_mcp  # noqa: E402


DOMAIN_LABELS = {
    "actividad": "Actividad",
    "articulo": "Articulo",
    "cartera": "Cartera",
    "cliente": "Cliente",
    "clientes": "Clientes",
    "compras": "Compras",
    "dashboard": "Dashboard",
    "documentos": "Documentos",
    "entrada": "Entrada almacen",
    "etiqueta": "Etiqueta",
    "falta": "Falta",
    "integracion": "Integracion",
    "mostrador": "Mostrador",
    "negocio": "Negocio",
    "oferta": "Oferta",
    "orden": "Orden compra",
    "pedido": "Pedido",
    "pedidos": "Pedidos",
    "precio": "Precio",
    "proveedor": "Proveedor",
    "proveedores": "Proveedores",
    "recuento": "Recuento",
    "stock": "Stock",
    "tarifa": "Tarifa proveedor",
    "tesoreria": "Tesoreria",
    "venta": "Venta",
    "ventas": "Ventas",
}

DOMAIN_COLORS = [
    colors.HexColor("#2F6F73"),
    colors.HexColor("#9A6A21"),
    colors.HexColor("#5D6FA8"),
    colors.HexColor("#7A5B91"),
    colors.HexColor("#547A39"),
    colors.HexColor("#A45143"),
    colors.HexColor("#53606B"),
    colors.HexColor("#2E7D62"),
]

RISK_COLORS = {
    "lectura": colors.HexColor("#DCEFE9"),
    "escritura": colors.HexColor("#FFF1C9"),
    "critica": colors.HexColor("#F8D8D4"),
}
RISK_TEXT = {
    "lectura": colors.HexColor("#1D5C4D"),
    "escritura": colors.HexColor("#7A5400"),
    "critica": colors.HexColor("#8A2F26"),
}


def domain_for(name: str) -> str:
    if name.startswith("orden_compra"):
        return "orden"
    return name.split("_", 1)[0]


def risk_for(name: str) -> str:
    if name in faro_mcp.READ_ONLY_TOOL_NAMES:
        return "lectura"
    if name in faro_mcp.WRITE_TOOL_NAMES:
        return "escritura"
    if name in faro_mcp.CRITICAL_TOOL_NAMES:
        return "critica"
    return "lectura"


def profile_for(name: str) -> str:
    in_core = name in faro_mcp.CORE_PUBLIC_TOOL_NAMES
    in_admin = name in faro_mcp.ADMIN_PUBLIC_TOOL_NAMES
    in_integration = name in faro_mcp.INTEGRATION_PUBLIC_TOOL_NAMES
    if in_core:
        return "core"
    if in_admin:
        return "admin"
    if in_integration:
        return "integrations"
    return "all"


def short_description(text: str, max_chars: int = 130) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return shorten(text, width=max_chars, placeholder="...")


class Pill(Flowable):
    def __init__(self, text: str, fill, text_color=colors.white, width: float | None = None):
        super().__init__()
        self.text = text
        self.fill = fill
        self.text_color = text_color
        self.width = width or (stringWidth(text, "Helvetica-Bold", 8) + 9 * mm)
        self.height = 6.5 * mm

    def wrap(self, avail_width, avail_height):
        return min(self.width, avail_width), self.height

    def draw(self):
        c = self.canv
        c.setFillColor(self.fill)
        c.roundRect(0, 0, self.width, self.height, 3 * mm, fill=1, stroke=0)
        c.setFillColor(self.text_color)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(self.width / 2, 2.05 * mm, self.text)


class BarChart(Flowable):
    def __init__(self, values: list[tuple[str, int, colors.Color]], width=170 * mm, bar_height=7 * mm):
        super().__init__()
        self.values = values
        self.width = width
        self.bar_height = bar_height
        self.height = len(values) * (bar_height + 4 * mm)

    def wrap(self, avail_width, avail_height):
        self.width = min(self.width, avail_width)
        return self.width, self.height

    def draw(self):
        max_value = max((v for _, v, _ in self.values), default=1)
        label_width = 38 * mm
        usable = self.width - label_width - 14 * mm
        y = self.height - self.bar_height
        c = self.canv
        c.setFont("Helvetica", 8)
        for label, value, color in self.values:
            c.setFillColor(colors.HexColor("#28323A"))
            c.drawString(0, y + 1.7 * mm, label[:24])
            bar_width = usable * (value / max_value if max_value else 0)
            c.setFillColor(color)
            c.roundRect(label_width, y, max(1, bar_width), self.bar_height, 2 * mm, fill=1, stroke=0)
            c.setFillColor(colors.HexColor("#28323A"))
            c.setFont("Helvetica-Bold", 8)
            c.drawRightString(self.width, y + 1.7 * mm, str(value))
            c.setFont("Helvetica", 8)
            y -= self.bar_height + 4 * mm


def styles():
    base = getSampleStyleSheet()
    base.add(ParagraphStyle(
        "TitleK",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=25,
        leading=30,
        textColor=colors.HexColor("#263238"),
        alignment=TA_LEFT,
        spaceAfter=5 * mm,
    ))
    base.add(ParagraphStyle(
        "SubtitleK",
        parent=base["BodyText"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#52616B"),
        spaceAfter=6 * mm,
    ))
    base.add(ParagraphStyle(
        "SectionK",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=colors.HexColor("#263238"),
        spaceBefore=2 * mm,
        spaceAfter=3 * mm,
    ))
    base.add(ParagraphStyle(
        "SmallK",
        parent=base["BodyText"],
        fontSize=7.6,
        leading=9.5,
        textColor=colors.HexColor("#34444F"),
    ))
    base.add(ParagraphStyle(
        "TinyCenter",
        parent=base["BodyText"],
        fontSize=7.4,
        leading=9,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#34444F"),
    ))
    return base


def header_footer(canvas, doc):
    canvas.saveState()
    w, h = landscape(A4)
    canvas.setFillColor(colors.HexColor("#EEF3F4"))
    canvas.rect(0, h - 13 * mm, w, 13 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#2D3A40"))
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(12 * mm, h - 8.2 * mm, "Faro MCP - mapa visual de funciones")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(w - 12 * mm, h - 8.2 * mm, f"Pagina {doc.page}")
    canvas.setFillColor(colors.HexColor("#7A878E"))
    canvas.drawString(12 * mm, 8 * mm, "Generado desde faro_mcp.tool_definitions('all').")
    canvas.drawRightString(w - 12 * mm, 8 * mm, f"Servidor {faro_mcp.SERVER_VERSION} - Contrato {faro_mcp.PUBLIC_CONTRACT_VERSION}")
    canvas.restoreState()


def make_pdf(output: Path):
    tools = sorted(faro_mcp.tool_definitions("all"), key=lambda item: item["name"])
    grouped: dict[str, list[dict]] = defaultdict(list)
    for tool in tools:
        grouped[domain_for(tool["name"])].append(tool)

    color_by_domain = {
        domain: DOMAIN_COLORS[i % len(DOMAIN_COLORS)]
        for i, domain in enumerate(sorted(grouped))
    }
    style = styles()

    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=18 * mm,
        bottomMargin=15 * mm,
        title="Faro MCP - mapa visual de funciones",
        author="Codex",
    )
    story = []
    story.append(Paragraph("Mapa visual de funciones MCP Faro", style["TitleK"]))
    story.append(Paragraph(
        f"Catalogo generado automaticamente el {date.today().isoformat()} desde el contrato publico completo. "
        f"Incluye {len(tools)} herramientas, agrupadas por dominio y nivel de riesgo.",
        style["SubtitleK"],
    ))

    counts_by_risk = defaultdict(int)
    counts_by_profile = defaultdict(int)
    for tool in tools:
        counts_by_risk[risk_for(tool["name"])] += 1
        counts_by_profile[profile_for(tool["name"])] += 1

    overview = Table(
        [
            [Paragraph("<b>Total</b><br/>funciones", style["TinyCenter"]), Paragraph("<b>Lectura</b><br/>sin escritura", style["TinyCenter"]), Paragraph("<b>Escritura</b><br/>mutacion ordinaria", style["TinyCenter"]), Paragraph("<b>Critica</b><br/>alto impacto", style["TinyCenter"])],
            [Paragraph(f"<font size='24'><b>{len(tools)}</b></font>", style["TinyCenter"]), Paragraph(f"<font size='22'><b>{counts_by_risk['lectura']}</b></font>", style["TinyCenter"]), Paragraph(f"<font size='22'><b>{counts_by_risk['escritura']}</b></font>", style["TinyCenter"]), Paragraph(f"<font size='22'><b>{counts_by_risk['critica']}</b></font>", style["TinyCenter"])],
        ],
        colWidths=[31 * mm, 31 * mm, 31 * mm, 31 * mm],
        rowHeights=[14 * mm, 18 * mm],
    )
    overview.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7F9FA")),
        ("BACKGROUND", (1, 1), (1, 1), RISK_COLORS["lectura"]),
        ("BACKGROUND", (2, 1), (2, 1), RISK_COLORS["escritura"]),
        ("BACKGROUND", (3, 1), (3, 1), RISK_COLORS["critica"]),
        ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#C9D3D7")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9E1E4")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    top_domains = sorted(
        [(DOMAIN_LABELS.get(k, k.title()), len(v), color_by_domain[k]) for k, v in grouped.items()],
        key=lambda item: item[1],
        reverse=True,
    )[:10]
    intro_table = Table(
        [[overview, BarChart(top_domains, width=125 * mm)]],
        colWidths=[132 * mm, 130 * mm],
    )
    intro_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(intro_table)
    story.append(Spacer(1, 6 * mm))

    legend = Table(
        [[Pill("lectura", RISK_COLORS["lectura"], RISK_TEXT["lectura"], 28 * mm),
          Pill("escritura", RISK_COLORS["escritura"], RISK_TEXT["escritura"], 31 * mm),
          Pill("critica", RISK_COLORS["critica"], RISK_TEXT["critica"], 27 * mm),
          Paragraph("El perfil indica donde aparece por defecto: core, admin o integrations.", style["SmallK"])]],
        colWidths=[31 * mm, 34 * mm, 30 * mm, 175 * mm],
    )
    story.append(legend)
    story.append(PageBreak())

    for domain in sorted(grouped, key=lambda key: DOMAIN_LABELS.get(key, key)):
        label = DOMAIN_LABELS.get(domain, domain.title())
        tools_in_domain = grouped[domain]
        story.append(KeepTogether([
            Paragraph(label, style["SectionK"]),
            Paragraph(f"{len(tools_in_domain)} funciones disponibles", style["SubtitleK"]),
        ]))
        rows = [[
            Paragraph("<b>Funcion</b>", style["SmallK"]),
            Paragraph("<b>Nivel</b>", style["SmallK"]),
            Paragraph("<b>Perfil</b>", style["SmallK"]),
            Paragraph("<b>Uso principal</b>", style["SmallK"]),
        ]]
        row_backgrounds = []
        for idx, tool in enumerate(tools_in_domain, start=1):
            risk = risk_for(tool["name"])
            rows.append([
                Paragraph(f"<b>{tool['name']}</b>", style["SmallK"]),
                Paragraph(risk, style["SmallK"]),
                Paragraph(profile_for(tool["name"]), style["SmallK"]),
                Paragraph(short_description(tool.get("description", "")), style["SmallK"]),
            ])
            row_backgrounds.append((idx, RISK_COLORS[risk]))
        table = Table(rows, colWidths=[68 * mm, 24 * mm, 27 * mm, 148 * mm], repeatRows=1)
        commands = [
            ("BACKGROUND", (0, 0), (-1, 0), color_by_domain[domain]),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#C9D3D7")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDE5E7")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for row_index, fill in row_backgrounds:
            commands.append(("BACKGROUND", (1, row_index), (1, row_index), fill))
        table.setStyle(TableStyle(commands))
        story.append(table)
        story.append(Spacer(1, 5 * mm))

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)


if __name__ == "__main__":
    make_pdf(ROOT / "output" / "pdf" / "mapa_funciones_mcp_faro.pdf")
