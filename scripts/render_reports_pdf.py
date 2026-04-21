from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from bs4 import BeautifulSoup, NavigableString, Tag
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "docs" / "reports"


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "StormhelmTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=colors.HexColor("#103252"),
            spaceAfter=12,
        ),
        "subtitle": ParagraphStyle(
            "StormhelmSubtitle",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#38556E"),
            spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "StormhelmH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#103252"),
            spaceBefore=12,
            spaceAfter=8,
        ),
        "h3": ParagraphStyle(
            "StormhelmH3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#103252"),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "h4": ParagraphStyle(
            "StormhelmH4",
            parent=base["Heading4"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=13,
            textColor=colors.HexColor("#103252"),
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "StormhelmBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "StormhelmSmall",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#50657A"),
            spaceAfter=6,
        ),
        "code": ParagraphStyle(
            "StormhelmCode",
            parent=base["BodyText"],
            fontName="Courier",
            fontSize=8.5,
            leading=10.5,
            spaceAfter=6,
        ),
        "list": ParagraphStyle(
            "StormhelmList",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            leftIndent=18,
            firstLineIndent=-12,
            spaceAfter=3,
        ),
        "table": ParagraphStyle(
            "StormhelmTable",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=10.5,
            spaceAfter=0,
        ),
        "pre": ParagraphStyle(
            "StormhelmPre",
            parent=base["Code"],
            fontName="Courier",
            fontSize=6.5,
            leading=7.6,
        ),
    }
    return styles


def render_reports() -> None:
    styles = build_styles()
    for html_path in [
        REPORTS_DIR / "stormhelm-feature-book.html",
        REPORTS_DIR / "stormhelm-improvement-book.html",
        REPORTS_DIR / "stormhelm-full-file-manifest.html",
    ]:
        story = build_story(html_path, styles)
        output_path = html_path.with_suffix(".pdf")
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=LETTER,
            leftMargin=0.7 * inch,
            rightMargin=0.7 * inch,
            topMargin=0.7 * inch,
            bottomMargin=0.7 * inch,
            title=html_path.stem.replace("-", " ").title(),
        )
        doc.build(story, onFirstPage=_page_number, onLaterPages=_page_number)
        print(f"rendered {output_path.name}\t{output_path.stat().st_size}")


def _page_number(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#50657A"))
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.45 * inch, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


def build_story(html_path: Path, styles: dict[str, ParagraphStyle]) -> list:
    html_text = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html_text, "html.parser")
    body = soup.body or soup
    story: list = []

    for node in body.children:
        _append_node(story, node, styles)

    return story


def _append_node(story: list, node, styles: dict[str, ParagraphStyle]) -> None:
    if isinstance(node, NavigableString):
        if str(node).strip():
            story.append(Paragraph(escape(str(node).strip()), styles["body"]))
        return
    if not isinstance(node, Tag):
        return

    name = node.name.lower()
    classes = set(node.get("class", []))

    if name == "h1":
        story.append(Paragraph(escape(node.get_text(" ", strip=True)), styles["title"]))
        return
    if name == "h2":
        story.append(Paragraph(escape(node.get_text(" ", strip=True)), styles["h2"]))
        return
    if name == "h3":
        story.append(Paragraph(escape(node.get_text(" ", strip=True)), styles["h3"]))
        return
    if name == "h4":
        story.append(Paragraph(escape(node.get_text(" ", strip=True)), styles["h4"]))
        return
    if name == "p":
        text = node.get_text(" ", strip=True)
        if not text:
            return
        if "code" in classes:
            story.append(Preformatted(text, styles["code"]))
        elif "small" in classes:
            story.append(Paragraph(escape(text), styles["small"]))
        else:
            story.append(Paragraph(escape(text), styles["body"]))
        return
    if name in {"ul", "ol"}:
        ordered = name == "ol"
        for index, li in enumerate(node.find_all("li", recursive=False), start=1):
            text = li.get_text(" ", strip=True)
            if not text:
                continue
            prefix = f"{index}. " if ordered else "• "
            story.append(Paragraph(escape(prefix + text), styles["list"]))
        story.append(Spacer(1, 0.04 * inch))
        return
    if name == "table":
        _append_table(story, node, styles)
        return
    if name == "pre":
        pre_text = node.get_text("\n", strip=False).rstrip()
        if pre_text:
            for chunk in _chunk_lines(pre_text, 110):
                story.append(Preformatted(chunk, styles["pre"]))
        return
    if name == "div" and ("meta" in classes or "callout" in classes):
        lines = []
        for child in node.children:
            if isinstance(child, NavigableString):
                if str(child).strip():
                    lines.append(str(child).strip())
            elif isinstance(child, Tag):
                text = child.get_text(" ", strip=True)
                if text:
                    lines.append(text)
        if lines:
            box_text = "<br/>".join(escape(line) for line in lines)
            box = Table([[Paragraph(box_text, styles["body"])]], colWidths=[6.6 * inch])
            background = colors.HexColor("#EEF5FB") if "callout" in classes else colors.HexColor("#F4F8FB")
            box.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), background),
                        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#C8D7E3")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.append(box)
            story.append(Spacer(1, 0.08 * inch))
        return
    if name == "ol" and node.get("class") and "toc" in classes:
        for index, li in enumerate(node.find_all("li", recursive=False), start=1):
            text = li.get_text(" ", strip=True)
            if text:
                story.append(Paragraph(escape(f"{index}. {text}"), styles["list"]))
        story.append(Spacer(1, 0.04 * inch))
        return
    if name == "div" and "page-break" in classes:
        story.append(PageBreak())
        return

    for child in node.children:
        _append_node(story, child, styles)


def _append_table(story: list, node: Tag, styles: dict[str, ParagraphStyle]) -> None:
    rows: list[list] = []
    max_cols = 0
    for tr in node.find_all("tr", recursive=False):
        row: list = []
        for cell in tr.find_all(["th", "td"], recursive=False):
            text = cell.get_text(" ", strip=True)
            row.append(Paragraph(escape(text), styles["table"]))
        if row:
            max_cols = max(max_cols, len(row))
            rows.append(row)
    if not rows:
        return
    for row in rows:
        while len(row) < max_cols:
            row.append(Paragraph("", styles["table"]))
    table = Table(rows, repeatRows=1)
    style_commands = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B8CAD8")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7EFF6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    table.setStyle(TableStyle(style_commands))
    story.append(table)
    story.append(Spacer(1, 0.08 * inch))


def _chunk_lines(text: str, lines_per_chunk: int) -> list[str]:
    lines = text.splitlines()
    return ["\n".join(lines[index:index + lines_per_chunk]) for index in range(0, len(lines), lines_per_chunk)]


if __name__ == "__main__":
    render_reports()
