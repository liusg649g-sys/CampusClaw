"""Export the public acceptance report to self-contained HTML and A4 PDF.

Only the specified Markdown and explicitly referenced images below
submission/evidence are read. This utility never reads application settings,
databases, accounts, logs, or environment secrets. Install requirements-report.txt
in a virtual environment or an isolated --target directory before running it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
TITLE = "CampusClaw · 阶段性验收报告"
RED = "#b91c32"

CSS = """
:root { color-scheme: light; --accent: #b91c32; --ink: #202733; }
* { box-sizing: border-box; }
html { background: #f2f4f7; color: var(--ink); }
body { max-width: 1060px; margin: 32px auto; padding: 42px 50px;
  background: white; font: 15px/1.8 'Microsoft YaHei','Noto Sans CJK SC',sans-serif;
  box-shadow: 0 3px 24px #10182812; overflow-wrap: anywhere; }
.brand { color: var(--accent); font-size: 12px; font-weight: 700;
  letter-spacing: .12em; border-top: 5px solid var(--accent); padding-top: 14px; }
h1 { font-size: 29px; line-height: 1.4; color: var(--accent); margin: 16px 0 24px; }
h2 { font-size: 21px; line-height: 1.5; color: var(--accent);
  border-bottom: 1px solid #e5e7eb; padding-bottom: 7px; margin-top: 30px; }
h3,h4 { font-size: 17px; line-height: 1.5; margin-top: 24px; }
p { margin: 10px 0; }
a { color: #a1162a; text-decoration-thickness: 1px; }
code { background: #f3f4f6; border-radius: 3px; padding: 1px 4px;
  font: .9em/1.7 Consolas,'Microsoft YaHei',monospace; overflow-wrap: anywhere; }
pre { background: #f6f7f9; border: 1px solid #e2e5ea; border-left: 3px solid var(--accent);
  border-radius: 4px; padding: 13px 15px; white-space: pre-wrap;
  overflow-wrap: anywhere; word-break: break-word; font: 12px/1.7 Consolas,'Microsoft YaHei',monospace; }
pre code { padding: 0; background: transparent; font: inherit; }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin: 16px 0; table-layout: fixed; }
th,td { padding: 9px 10px; border: 1px solid #dce0e7; vertical-align: top; overflow-wrap: anywhere; }
th { background: var(--accent); color: white; font-weight: 700; }
tbody tr:nth-child(even) { background: #fafafb; }
blockquote { margin: 14px 0; padding: 3px 16px; border-left: 3px solid var(--accent);
  background: #fdf4f5; color: #4b5563; }
li { margin: 5px 0; } img { max-width: 100%; height: auto; border: 1px solid #e5e7eb; }
hr { border: 0; border-top: 1px solid #dce0e7; margin: 22px 0; }
.export-note { margin-top: 30px; border-top: 1px solid #dce0e7; padding-top: 12px;
  font-size: 11px; color: #6b7280; }
@page { size: A4; margin: 17mm; }
@media print {
  html { background: white; } body { margin: 0; padding: 0; max-width: none; box-shadow: none; font-size: 10pt; }
  .brand { font-size: 9pt; } h1 { font-size: 20pt; } h2 { font-size: 15pt; } h3 { font-size: 12pt; }
  h1,h2,h3,h4 { break-after: avoid; } p,li { orphans: 3; widows: 3; }
  table { font-size: 8.5pt; } thead { display: table-header-group; }
  tr,img { break-inside: avoid; } pre { font-size: 8pt; } a { color: inherit; }
}
"""


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node | str"] = field(default_factory=list)


class FragmentParser(HTMLParser):
    """Keep a small HTML tree, without loading external resources."""

    VOID = {"img", "br", "hr", "input", "meta", "link"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def text_of(item: Node | str) -> str:
    if isinstance(item, str):
        return item
    return "".join(text_of(child) for child in item.children)


def basic_markdown(source: str) -> str:
    """Dependency-free fallback for headings, lists, fences and pipe tables."""
    lines = source.splitlines()
    result: list[str] = []
    paragraph: list[str] = []
    code: list[str] | None = None
    list_tag: str | None = None

    def inline(value: str) -> str:
        value = escape(value)
        value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
        value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
        return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', value)

    def flush() -> None:
        if paragraph:
            result.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            result.append(f"</{list_tag}>")
            list_tag = None

    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.lstrip().startswith("```"):
            flush()
            close_list()
            if code is None:
                code = []
            else:
                result.append("<pre><code>" + escape("\n".join(code)) + "</code></pre>")
                code = None
            continue
        if code is not None:
            code.append(line)
            continue
        if not line.strip():
            flush()
            close_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush()
            close_list()
            size = len(heading[1])
            result.append(f"<h{size}>" + inline(heading[2]) + f"</h{size}>")
            continue
        if "|" in line and index < len(lines) and re.fullmatch(r"\s*\|?[\s:|\-]+\|?\s*", lines[index]):
            flush()
            close_list()
            rows = [line]
            index += 1
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(lines[index])
                index += 1
            result.append("<table><thead>")
            for number, row in enumerate(rows):
                if number == 1:
                    result.append("</thead><tbody>")
                cell_tag = "th" if number == 0 else "td"
                cells = row.strip().strip("|").split("|")
                result.append("<tr>" + "".join(f"<{cell_tag}>" + inline(cell.strip()) + f"</{cell_tag}>" for cell in cells) + "</tr>")
            result.append("</tbody></table>")
            continue
        match = re.match(r"^\s*(?:([-*+])|\d+[.)])\s+(.*)$", line)
        if match:
            flush()
            tag = "ul" if match[1] else "ol"
            if list_tag != tag:
                close_list()
                result.append(f"<{tag}>")
                list_tag = tag
            result.append("<li>" + inline(match[2]) + "</li>")
            continue
        close_list()
        paragraph.append(line.strip())
    flush()
    close_list()
    if code is not None:
        result.append("<pre><code>" + escape("\n".join(code)) + "</code></pre>")
    return "\n".join(result)


def parse_markdown(source: str) -> tuple[Node, str]:
    try:
        import markdown
        fragment = markdown.markdown(source, extensions=["tables", "fenced_code", "sane_lists"])
        engine = "Markdown"
    except ImportError:
        fragment = basic_markdown(source)
        engine = "basic fallback"
    parser = FragmentParser()
    parser.feed(fragment)
    return parser.root, engine


def safe_href(value: str) -> str | None:
    try:
        parts = urlsplit(value)
        if parts.username or parts.password or parts.scheme.lower() not in {"", "http", "https", "mailto"}:
            return None
        if value.startswith("//") or "\\" in value:
            return None
        return value
    except ValueError:
        return None


def public_image(value: str, markdown_path: Path) -> Path | None:
    """Only explicitly referenced public evidence images can enter an export."""
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or parts.query or parts.fragment:
        return None
    try:
        candidate = (markdown_path.parent / unquote(parts.path)).resolve()
        candidate.relative_to((ROOT / "submission" / "evidence").resolve())
    except (ValueError, OSError):
        return None
    if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg"} or not candidate.is_file():
        return None
    return candidate


def render_html(root: Node, markdown_path: Path, html_path: Path) -> None:
    allowed = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "b", "em", "i", "code", "pre", "blockquote", "table", "thead", "tbody", "tr", "th", "td", "a", "br", "hr", "img", "del"}
    suppressed = {"script", "style", "iframe", "object", "embed"}

    def render(item: Node | str) -> str:
        if isinstance(item, str):
            return escape(item)
        if item.tag in suppressed:
            return ""
        body = "".join(render(child) for child in item.children)
        if item.tag not in allowed:
            return body
        attrs = ""
        if item.tag == "a":
            href = safe_href(item.attrs.get("href", ""))
            if not href:
                return body
            attrs = f' href="{escape(href, quote=True)}"'
        if item.tag == "img":
            image = public_image(item.attrs.get("src", ""), markdown_path)
            if image is None:
                return "<em>" + escape(item.attrs.get("alt", "图像未导出：仅允许公开证据目录中的本地图片")) + "</em>"
            src = Path(os.path.relpath(image, html_path.parent)).as_posix()
            return f'<img src="{escape(src, quote=True)}" alt="{escape(item.attrs.get("alt", ""), quote=True)}">'
        if item.tag in {"hr", "br"}:
            return f"<{item.tag}>"
        return f"<{item.tag}{attrs}>{body}</{item.tag}>"

    body = "".join(render(child) for child in root.children)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text("<!doctype html>\n<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>" + TITLE + "</title><style>" + CSS + "</style></head><body><div class=\"brand\">CAMPUSCLAW / STAGE ACCEPTANCE</div>" + body + '<div class="export-note">此文件由项目中的公开验收 Markdown 生成。可直接使用浏览器“打印 / 另存为 PDF”。</div></body></html>\n', encoding="utf-8")


def register_fonts() -> tuple[str, str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont

    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [(fonts / "msyh.ttc", fonts / "msyhbd.ttc"), (fonts / "simhei.ttf", fonts / "simhei.ttf")]
    for regular, bold in candidates:
        if not regular.is_file() or not bold.is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont("CampusRegular", str(regular), subfontIndex=0))
            pdfmetrics.registerFont(TTFont("CampusBold", str(bold), subfontIndex=0))
            pdfmetrics.registerFontFamily("CampusRegular", normal="CampusRegular", bold="CampusBold", italic="CampusRegular", boldItalic="CampusBold")
            return "CampusRegular", "CampusBold", regular.name
        except Exception:
            continue
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdfmetrics.registerFontFamily("STSong-Light", normal="STSong-Light", bold="STSong-Light", italic="STSong-Light", boldItalic="STSong-Light")
    return "STSong-Light", "STSong-Light", "STSong-Light (CID fallback)"


def wrap_code(text: str, width: float, font: str, size: float) -> str:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    output: list[str] = []
    for line in text.expandtabs(4).splitlines() or [""]:
        chunk = ""
        used = 0.0
        continuation = "    " if line.startswith(" ") else "  "
        for char in line:
            measure = stringWidth(char, font, size)
            if chunk and used + measure > width:
                output.append(chunk)
                chunk = continuation
                used = stringWidth(chunk, font, size)
            chunk += char
            used += measure
        output.append(chunk)
    return "\n".join(output)


def render_pdf(root: Node, markdown_path: Path, pdf_path: Path) -> str:
    try:
        from reportlab import rl_config
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import HRFlowable, Image, KeepTogether, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as error:
        raise RuntimeError("缺少 PDF 依赖。请在虚拟环境中安装 requirements-report.txt；HTML 已可直接打印。") from error

    # Explicitly keep all temporary rendering resources inside this process.
    rl_config.warnOnMissingFontGlyphs = 1
    regular, bold, font_label = register_fonts()
    page_width, page_height = A4
    margin = 17.5 * mm
    # SimpleDocTemplate's frame has six points of inner padding on each side.
    # Use its actual available width, including for tables and preformatted JSON.
    width = page_width - 2 * margin - 12
    accent = colors.HexColor(RED)
    ink = colors.HexColor("#202733")
    grey = colors.HexColor("#667085")
    base = ParagraphStyle("Body", fontName=regular, fontSize=9.25, leading=14.7, textColor=ink, spaceAfter=6, wordWrap="CJK", splitLongWords=True, allowWidows=False, allowOrphans=False, alignment=TA_LEFT)
    styles = {
        "body": base,
        "title": ParagraphStyle("Title", parent=base, fontName=bold, fontSize=21, leading=30, textColor=accent, spaceBefore=4, spaceAfter=17, keepWithNext=True),
        "h2": ParagraphStyle("Heading2", parent=base, fontName=bold, fontSize=13.2, leading=20, textColor=accent, spaceBefore=12, spaceAfter=7, keepWithNext=True),
        "h3": ParagraphStyle("Heading3", parent=base, fontName=bold, fontSize=10.6, leading=17, spaceBefore=8, spaceAfter=5, keepWithNext=True),
        "small": ParagraphStyle("Small", parent=base, fontSize=8, leading=12, textColor=grey, spaceAfter=5),
        "cell": ParagraphStyle("Cell", parent=base, fontSize=7.8, leading=11.5, spaceAfter=0, allowWidows=True, allowOrphans=True),
        "headcell": ParagraphStyle("HeadCell", parent=base, fontName=bold, fontSize=8, leading=12, spaceAfter=0, textColor=colors.white, allowWidows=True, allowOrphans=True),
        "quote": ParagraphStyle("Quote", parent=base, fontSize=8.7, leading=13.5, leftIndent=10, textColor=grey),
        "code": ParagraphStyle("Code", parent=base, fontSize=7.35, leading=10.3, leftIndent=7, rightIndent=7, spaceBefore=3, spaceAfter=8, splitLongWords=True, allowWidows=True, allowOrphans=True),
    }
    story: list = []

    def inline(item: Node | str) -> str:
        if isinstance(item, str):
            return escape(item.replace("\n", " "))
        body = "".join(inline(child) for child in item.children)
        if item.tag in {"script", "style", "iframe", "object", "embed"}:
            return ""
        if item.tag in {"b", "strong"}:
            return "<b>" + body + "</b>"
        if item.tag in {"i", "em"}:
            return "<i>" + body + "</i>"
        if item.tag == "code":
            return '<font color="#8d1830">' + body + "</font>"
        if item.tag == "a":
            href = safe_href(item.attrs.get("href", ""))
            if href and href.startswith(("http://", "https://", "mailto:")):
                return '<a href="' + escape(href, quote=True) + '" color="#a1162a">' + body + "</a>"
            return body
        if item.tag == "br":
            return "<br/>"
        if item.tag == "img":
            return escape(item.attrs.get("alt", ""))
        return body

    def paragraph(value: str, style: str = "body") -> Paragraph:
        return Paragraph(value or "&#160;", styles[style])

    def image_block(node: Node) -> None:
        path = public_image(node.attrs.get("src", ""), markdown_path)
        if path is None:
            story.append(paragraph(escape(node.attrs.get("alt", "未导出非公开图片")), "small"))
            return
        from PIL import Image as PillowImage
        with PillowImage.open(path) as original:
            pixel_width, pixel_height = original.size
        factor = min(width / pixel_width, 100 * mm / pixel_height)
        rendered = Image(str(path), width=pixel_width * factor, height=pixel_height * factor)
        rendered.hAlign = "CENTER"
        caption = paragraph(escape(node.attrs.get("alt", "公开验收截图")), "small")
        block = [Spacer(1, 4), rendered, Spacer(1, 4), caption]
        if story and isinstance(story[-1], Paragraph) and story[-1].style.keepWithNext:
            block.insert(0, story.pop())
        story.extend([KeepTogether(block), Spacer(1, 5)])

    def table_rows(node: Node) -> list[Node]:
        rows: list[Node] = []
        for child in node.children:
            if isinstance(child, Node):
                if child.tag == "tr":
                    rows.append(child)
                elif child.tag in {"thead", "tbody", "tfoot"}:
                    rows.extend(table_rows(child))
        return rows

    def table_block(node: Node) -> None:
        rows = table_rows(node)
        if not rows:
            return
        raw_cells = [[child for child in row.children if isinstance(child, Node) and child.tag in {"th", "td"}] for row in rows]
        columns = max(len(row) for row in raw_cells)
        if not columns:
            return
        weights = []
        for column in range(columns):
            sizes = [len(text_of(row[column])) for row in raw_cells if column < len(row)]
            typical = sum(min(value, 100) for value in sizes) / max(len(sizes), 1)
            weights.append(max(12.0, min(26.0, math.sqrt(typical + 1) * 4.0)))
        widths = [width * value / sum(weights) for value in weights]
        cell_grid = []
        for row_index, row in enumerate(raw_cells):
            cell_grid.append([paragraph(inline(row[column]) if column < len(row) else "", "headcell" if row_index == 0 else "cell") for column in range(columns)])
        table = Table(cell_grid, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1, splitInRow=1)
        commands = [
            ("BACKGROUND", (0, 0), (-1, 0), accent),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9dee6")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
        for row_index in range(2, len(cell_grid), 2):
            commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f7f8fa")))
        table.setStyle(TableStyle(commands))
        story.extend([Spacer(1, 3), table, Spacer(1, 10)])

    def visit(item: Node | str, depth: int = 0) -> None:
        if isinstance(item, str):
            if item.strip():
                story.append(paragraph(escape(item)))
            return
        tag = item.tag
        if tag in {"script", "style", "iframe", "object", "embed"}:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            story.append(paragraph(inline(item), "title" if tag == "h1" else "h2" if tag == "h2" else "h3"))
        elif tag == "p":
            images = [child for child in item.children if isinstance(child, Node) and child.tag == "img"]
            rest = [child for child in item.children if not (isinstance(child, Node) and child.tag == "img")]
            content = "".join(inline(child) for child in rest)
            if content.strip():
                story.append(paragraph(content))
            for node in images:
                image_block(node)
        elif tag == "pre":
            value = wrap_code(text_of(item).rstrip("\n"), width - 15, regular, styles["code"].fontSize)
            story.append(Preformatted(value, styles["code"]))
        elif tag == "table":
            table_block(item)
        elif tag == "img":
            image_block(item)
        elif tag in {"ul", "ol"}:
            number = 0
            for child in item.children:
                if not isinstance(child, Node) or child.tag != "li":
                    continue
                number += 1
                rest = [node for node in child.children if not (isinstance(node, Node) and node.tag in {"ul", "ol"})]
                content = "".join(inline(node) for node in rest)
                prefix = f"{number}. " if tag == "ol" else "• "
                list_style = ParagraphStyle(f"List{depth}", parent=base, leftIndent=9 + depth * 8, firstLineIndent=-7, spaceAfter=4)
                story.append(Paragraph(escape(prefix) + content, list_style))
                for nested in child.children:
                    if isinstance(nested, Node) and nested.tag in {"ul", "ol"}:
                        visit(nested, depth + 1)
        elif tag == "blockquote":
            story.append(paragraph(inline(item), "quote"))
        elif tag == "hr":
            story.extend([Spacer(1, 6), HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#d9dee6")), Spacer(1, 6)])
        else:
            for child in item.children:
                visit(child, depth)

    for child in root.children:
        visit(child)

    def page(canvas, document) -> None:
        canvas.saveState()
        canvas.setTitle(TITLE)
        canvas.setAuthor("CampusClaw")
        canvas.setSubject("第五、六课个人项目阶段性验收；公开脱敏版本")
        canvas.setStrokeColor(accent)
        canvas.setLineWidth(2)
        canvas.line(margin, page_height - 12 * mm, page_width - margin, page_height - 12 * mm)
        canvas.setFont(regular, 7.6)
        canvas.setFillColor(grey)
        canvas.drawString(margin, page_height - 9.5 * mm, "CAMPUSCLAW / 个人项目阶段性验收")
        canvas.setStrokeColor(colors.HexColor("#d9dee6"))
        canvas.setLineWidth(0.4)
        canvas.line(margin, 13 * mm, page_width - margin, 13 * mm)
        canvas.drawString(margin, 9 * mm, "公开提交版 · 请求样例与证据已脱敏")
        canvas.drawRightString(page_width - margin, 9 * mm, f"{document.page}")
        canvas.restoreState()

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(str(pdf_path), pagesize=A4, rightMargin=margin, leftMargin=margin, topMargin=18 * mm, bottomMargin=18 * mm, title=TITLE, author="CampusClaw", allowSplitting=True, pageCompression=True)
    document.build(story, onFirstPage=page, onLaterPages=page)
    return font_label


def main() -> int:
    parser = argparse.ArgumentParser(description="将公开的 CampusClaw 验收 Markdown 导出 HTML 和 A4 PDF")
    parser.add_argument("--markdown", type=Path, default=ROOT / "STAGE_ACCEPTANCE_REPORT.md", help="输入 Markdown；默认项目根目录报告")
    parser.add_argument("--html", type=Path, default=ROOT / "STAGE_ACCEPTANCE_REPORT.html", help="输出 HTML")
    parser.add_argument("--pdf", type=Path, default=ROOT / "output" / "pdf" / "STAGE_ACCEPTANCE_REPORT.pdf", help="输出 PDF")
    parser.add_argument("--html-only", action="store_true", help="只生成可本地打印的 HTML，无需 ReportLab")
    options = parser.parse_args()
    markdown_path = options.markdown.resolve()
    if not markdown_path.is_file():
        parser.error("Markdown 输入文件不存在。请先生成公开验收报告。")
    html_path = options.html.resolve()
    pdf_path = options.pdf.resolve()
    if len({markdown_path, html_path, pdf_path}) != 3:
        parser.error("Markdown、HTML 和 PDF 必须使用三个不同的文件路径。")
    source = markdown_path.read_text(encoding="utf-8-sig")
    root, engine = parse_markdown(source)
    render_html(root, markdown_path, html_path)
    print(f"HTML: {html_path}")
    if not options.html_only:
        try:
            font = render_pdf(root, markdown_path, pdf_path)
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            return 2
        print(f"PDF: {pdf_path}")
        print(f"PDF font: {font}")
    print(f"Markdown parser: {engine}; no network requests performed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
