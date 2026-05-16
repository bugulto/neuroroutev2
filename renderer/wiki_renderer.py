import html
import re
from typing import Dict, List


HEADING_PATTERN = re.compile(r"^(={2,6})\s*(.*?)\s*\1$")
INLINE_TOKEN_PATTERN = re.compile(
    r"(<ref[^>/]*/>)"
    r"|(<ref[^>]*>.*?</ref>)"
    r"|(\[\[.*?\]\])"
    r"|(\[https?://[^\s\]]+(?:\s+[^\]]+)?\])"
    r"|(\{\{.*?\}\})",
    re.IGNORECASE | re.DOTALL,
)
BOLD_ITALIC_PATTERN = re.compile(r"('''.*?'''|''.*?'')", re.DOTALL)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _escape_text(text: str) -> str:
    return html.escape(text, quote=True)


def _render_bold_italic(text: str) -> str:
    parts: List[str] = []
    last = 0
    for match in BOLD_ITALIC_PATTERN.finditer(text):
        start, end = match.span()
        if start > last:
            parts.append(_escape_text(text[last:start]))
        token = match.group(1)
        if token.startswith("'''"):
            inner = token[3:-3]
            parts.append(f"<b>{_escape_text(inner)}</b>")
        else:
            inner = token[2:-2]
            parts.append(f"<i>{_escape_text(inner)}</i>")
        last = end

    if last < len(text):
        parts.append(_escape_text(text[last:]))

    return "".join(parts)


def _render_internal_link(token: str) -> str:
    content = token[2:-2].strip()
    parts = [part.strip() for part in content.split("|") if part.strip()]
    if not parts:
        return _escape_text(token)

    title = parts[0]
    label = parts[-1] if len(parts) > 1 else title

    lower_title = title.lower()
    if lower_title.startswith("file:") or lower_title.startswith("image:"):
        filename = title.split(":", 1)[1].strip()
        caption = parts[-1] if len(parts) > 1 else filename
        return f"<img src=\"{_escape_text(filename)}\" alt=\"{_escape_text(caption)}\">"

    if lower_title.startswith("category:"):
        category = title.split(":", 1)[1].strip()
        href = f"/wiki/Category:{category.replace(' ', '_')}"
        return (
            f"<a class=\"category\" href=\"{_escape_text(href)}\">"
            f"{_escape_text(category)}</a>"
        )

    href = f"/wiki/{title.replace(' ', '_')}"
    return f"<a href=\"{_escape_text(href)}\">{_escape_text(label)}</a>"


def _render_external_link(token: str) -> str:
    content = token[1:-1].strip()
    if not content:
        return _escape_text(token)

    parts = content.split(None, 1)
    url = parts[0]
    label = parts[1] if len(parts) > 1 else url
    return f"<a href=\"{_escape_text(url)}\">{_escape_text(label)}</a>"


def _render_template(token: str) -> str:
    content = token[2:-2].strip()
    name = content.split("|", 1)[0].strip() if content else ""
    if not name:
        return _escape_text(token)
    return f"<div class=\"template\">{_escape_text(name)}</div>"


def _render_ref(token: str) -> str:
    if token.endswith("/>"):
        return "<sup class=\"reference\"></sup>"

    match = re.match(r"<ref[^>]*>(.*?)</ref>", token, re.IGNORECASE | re.DOTALL)
    if not match:
        return _escape_text(token)

    inner = match.group(1).strip()
    return f"<sup class=\"reference\">{_render_bold_italic(inner)}</sup>"


def _render_inline(text: str) -> str:
    parts: List[str] = []
    last = 0
    for match in INLINE_TOKEN_PATTERN.finditer(text):
        start, end = match.span()
        if start > last:
            parts.append(_render_bold_italic(text[last:start]))

        token = match.group(0)
        if token.startswith("{{"):
            parts.append(_render_template(token))
        elif token.startswith("[["):
            parts.append(_render_internal_link(token))
        elif token.startswith("["):
            parts.append(_render_external_link(token))
        elif token.lower().startswith("<ref"):
            parts.append(_render_ref(token))
        else:
            parts.append(_escape_text(token))

        last = end

    if last < len(text):
        parts.append(_render_bold_italic(text[last:]))

    return "".join(parts)


def _render_table(lines: List[str]) -> str:
    output: List[str] = ["<table>"]
    in_row = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|-"):
            if in_row:
                output.append("</tr>")
            output.append("<tr>")
            in_row = True
            continue

        if stripped.startswith("!"):
            if not in_row:
                output.append("<tr>")
                in_row = True
            cells = [c.strip() for c in stripped[1:].split("!!")]
            for cell in cells:
                output.append(f"<th>{_render_inline(cell)}</th>")
            continue

        if stripped.startswith("|"):
            if not in_row:
                output.append("<tr>")
                in_row = True
            cells = [c.strip() for c in stripped[1:].split("||")]
            for cell in cells:
                output.append(f"<td>{_render_inline(cell)}</td>")
            continue

    if in_row:
        output.append("</tr>")
    output.append("</table>")
    return "".join(output)


def render_wikitext(raw_wikitext: str) -> Dict[str, int | str]:
    lines = raw_wikitext.splitlines()
    output: List[str] = []
    paragraph: List[str] = []
    table_lines: List[str] = []
    in_table = False

    def flush_paragraph() -> None:
        if not paragraph:
            return
        text = " ".join(line.strip() for line in paragraph if line.strip())
        paragraph.clear()
        if text:
            output.append(f"<p>{_render_inline(text)}</p>")

    for line in lines:
        stripped = line.strip()

        if in_table:
            if stripped.startswith("|}"):
                output.append(_render_table(table_lines))
                table_lines.clear()
                in_table = False
            else:
                table_lines.append(line)
            continue

        if stripped.startswith("{|"):
            flush_paragraph()
            in_table = True
            table_lines.clear()
            continue

        if not stripped:
            flush_paragraph()
            continue

        heading_match = HEADING_PATTERN.match(stripped)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            title = heading_match.group(2)
            output.append(f"<h{level}>{_render_inline(title)}</h{level}>")
            continue

        paragraph.append(line)

    flush_paragraph()
    if in_table:
        output.append(_render_table(table_lines))

    rendered_html = "".join(output)
    table_tag_count = rendered_html.count("<table")
    paragraph_tag_count = rendered_html.count("<p>")
    rendered_html_length_bytes = len(rendered_html.encode("utf-8"))
    html_tag_count = len(HTML_TAG_PATTERN.findall(rendered_html))

    return {
        "html": rendered_html,
        "table_tag_count": table_tag_count,
        "paragraph_tag_count": paragraph_tag_count,
        "rendered_html_length_bytes": rendered_html_length_bytes,
        "html_tag_count": html_tag_count,
    }
