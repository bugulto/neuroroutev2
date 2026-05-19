import hashlib
import html
import re
from typing import Dict, List

import mwparserfromhell


HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _build_mwparser_payload(raw_wikitext: str) -> Dict[str, int | str]:
    code = mwparserfromhell.parse(raw_wikitext)

    templates = code.filter_templates()
    wikilinks = code.filter_wikilinks()
    external_links = code.filter_external_links()
    headings = code.filter_headings()
    tags = code.filter_tags()

    processed_text = code.strip_code()
    processed_text_length_bytes = len(processed_text.encode("utf-8"))

    parts: List[str] = ["<mw>"]
    for heading in headings:
        parts.append(f"<h>{html.escape(str(heading.title))}</h>")
    for template in templates:
        parts.append(f"<tpl>{html.escape(str(template.name))}</tpl>")
    for link in wikilinks:
        parts.append(f"<wl>{html.escape(str(link.title))}</wl>")
    for link in external_links:
        parts.append(f"<el>{html.escape(str(link))}</el>")
    for tag in tags:
        parts.append(f"<tag>{html.escape(str(tag.tag))}</tag>")
    parts.append(f"<text>{html.escape(processed_text[:2000])}</text>")
    parts.append("</mw>")

    rendered_html = "".join(parts)
    rendered_html_length_bytes = len(rendered_html.encode("utf-8"))
    html_tag_count = len(HTML_TAG_PATTERN.findall(rendered_html))
    checksum = hashlib.sha256(rendered_html.encode("utf-8")).hexdigest()

    return {
        "rendered_html_length_bytes": rendered_html_length_bytes,
        "html_tag_count": html_tag_count,
        "template_count_mw": len(templates),
        "wikilink_count_mw": len(wikilinks),
        "external_link_count_mw": len(external_links),
        "heading_count_mw": len(headings),
        "tag_count_mw": len(tags),
        "processed_text_length_bytes": processed_text_length_bytes,
        "checksum": checksum,
        "rendered_html": rendered_html,
    }


def render_with_mwparser(raw_wikitext: str) -> Dict[str, int | str]:
    payload = _build_mwparser_payload(raw_wikitext)

    return {
        "rendered_html_length_bytes": int(payload["rendered_html_length_bytes"]),
        "html_tag_count": int(payload["html_tag_count"]),
        "template_count_mw": int(payload["template_count_mw"]),
        "wikilink_count_mw": int(payload["wikilink_count_mw"]),
        "external_link_count_mw": int(payload["external_link_count_mw"]),
        "heading_count_mw": int(payload["heading_count_mw"]),
        "tag_count_mw": int(payload["tag_count_mw"]),
        "processed_text_length_bytes": int(payload["processed_text_length_bytes"]),
        "checksum": str(payload["checksum"]),
    }


def process_with_mwparser(raw_wikitext: str) -> Dict[str, int | str]:
    payload = _build_mwparser_payload(raw_wikitext)

    return {
        "rendered_html_length_bytes": int(payload["rendered_html_length_bytes"]),
        "html_tag_count": int(payload["html_tag_count"]),
        "checksum": str(payload["checksum"]),
    }
