import argparse
import os
import random
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import psycopg2
import psycopg2.extras


HEADING_PATTERN = re.compile(r"^={2,6}.*?={2,6}$", re.MULTILINE)
CATEGORY_PATTERN = re.compile(r"\[\[\s*Category\s*:", re.IGNORECASE)
FILE_PATTERN = re.compile(r"\[\[\s*File\s*:", re.IGNORECASE)
IMAGE_PATTERN = re.compile(r"\[\[\s*Image\s*:", re.IGNORECASE)
REF_PATTERN = re.compile(r"<ref", re.IGNORECASE)
REDIRECT_PATTERN = re.compile(r"^\s*#redirect\b", re.IGNORECASE)


@dataclass
class PageCandidate:
    page_id: int
    title: str
    revision_id: Optional[int]
    revision_timestamp: Optional[str]
    raw_wikitext: str
    features: Dict[str, int]


@dataclass
class ParseStats:
    total_pages: int = 0
    redirects_skipped: int = 0
    non_article_skipped: int = 0
    empty_or_tiny_skipped: int = 0
    valid_candidates: int = 0


def _extract_namespace(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[0][1:]

    return ""


def _qname(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}" if namespace else tag


def _safe_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def extract_features(raw_wikitext: str) -> Dict[str, int]:
    length_bytes = len(raw_wikitext.encode("utf-8"))

    return {
        "wikitext_length_bytes": length_bytes,
        "template_count": raw_wikitext.count("{{"),
        "image_count": len(FILE_PATTERN.findall(raw_wikitext)) + len(IMAGE_PATTERN.findall(raw_wikitext)),
        "reference_count": len(REF_PATTERN.findall(raw_wikitext)),
        "heading_count": len(HEADING_PATTERN.findall(raw_wikitext)),
        "internal_link_count": raw_wikitext.count("[["),
        "external_link_count": raw_wikitext.count("http://") + raw_wikitext.count("https://"),
        "category_count": len(CATEGORY_PATTERN.findall(raw_wikitext)),
    }


def is_redirect(raw_wikitext: str) -> bool:
    return bool(REDIRECT_PATTERN.match(raw_wikitext))


def iter_pages(xml_path: str) -> Iterable[Tuple[Optional[int], Optional[str], Optional[int], Optional[str], Optional[str], bool, int]]:
    namespace = ""
    for event, elem in ET.iterparse(xml_path, events=("start", "end")):
        if event == "start" and not namespace:
            namespace = _extract_namespace(elem.tag)

        if event != "end":
            continue

        if elem.tag != _qname(namespace, "page"):
            continue

        page_id = _safe_int(elem.findtext(_qname(namespace, "id")))
        title = elem.findtext(_qname(namespace, "title"))
        ns = _safe_int(elem.findtext(_qname(namespace, "ns")))
        is_redirect_tag = elem.find(_qname(namespace, "redirect")) is not None

        revision = elem.find(_qname(namespace, "revision"))
        revision_id = _safe_int(revision.findtext(_qname(namespace, "id")) if revision is not None else None)
        revision_timestamp = revision.findtext(_qname(namespace, "timestamp")) if revision is not None else None
        text = revision.findtext(_qname(namespace, "text")) if revision is not None else None

        yield page_id, title, ns, revision_id, revision_timestamp, text, is_redirect_tag

        elem.clear()


def collect_candidates(xml_path: str, min_length: int) -> Tuple[List[PageCandidate], ParseStats]:
    candidates: List[PageCandidate] = []
    stats = ParseStats()

    for page_id, title, ns, revision_id, revision_timestamp, text, is_redirect_tag in iter_pages(xml_path):
        stats.total_pages += 1

        if is_redirect_tag:
            stats.redirects_skipped += 1
            continue

        if ns != 0:
            stats.non_article_skipped += 1
            continue

        if not page_id or not title:
            stats.non_article_skipped += 1
            continue

        if not text:
            stats.empty_or_tiny_skipped += 1
            continue

        if is_redirect(text):
            stats.redirects_skipped += 1
            continue

        if len(text) < min_length:
            stats.empty_or_tiny_skipped += 1
            continue

        features = extract_features(text)

        candidates.append(
            PageCandidate(
                page_id=page_id,
                title=title,
                revision_id=revision_id,
                revision_timestamp=revision_timestamp,
                raw_wikitext=text,
                features=features,
            )
        )

        stats.valid_candidates += 1

        if stats.total_pages % 50000 == 0:
            print(
                "Parsed pages:"
                f" total={stats.total_pages}"
                f" redirects_skipped={stats.redirects_skipped}"
                f" non_article_skipped={stats.non_article_skipped}"
                f" empty_or_tiny_skipped={stats.empty_or_tiny_skipped}"
                f" valid_candidates={stats.valid_candidates}"
            )

    return candidates, stats


def select_pages(
    candidates: List[PageCandidate],
    target_count: int,
    random_count: int,
    largest_count: int,
    template_heavy_count: int,
    complex_count: int,
    seed: int,
) -> Tuple[List[PageCandidate], Dict[str, int]]:
    if len(candidates) <= target_count:
        return candidates, {
            "random": len(candidates),
            "largest": 0,
            "template_heavy": 0,
            "complex": 0,
        }

    rng = random.Random(seed)
    shuffled = candidates[:]
    rng.shuffle(shuffled)

    selection: Dict[int, PageCandidate] = {}

    for candidate in shuffled[:random_count]:
        selection[candidate.page_id] = candidate

    largest_sorted = sorted(
        candidates,
        key=lambda c: c.features["wikitext_length_bytes"],
        reverse=True,
    )[:largest_count]
    for candidate in largest_sorted:
        selection[candidate.page_id] = candidate

    template_sorted = sorted(
        candidates,
        key=lambda c: c.features["template_count"],
        reverse=True,
    )[:template_heavy_count]
    for candidate in template_sorted:
        selection[candidate.page_id] = candidate

    complex_sorted = sorted(
        candidates,
        key=lambda c: (
            c.features["reference_count"]
            + c.features["internal_link_count"]
            + c.features["external_link_count"]
            + c.features["category_count"]
        ),
        reverse=True,
    )[:complex_count]
    for candidate in complex_sorted:
        selection[candidate.page_id] = candidate

    selected = list(selection.values())

    if len(selected) < target_count:
        for candidate in shuffled:
            if candidate.page_id in selection:
                continue
            selection[candidate.page_id] = candidate
            selected.append(candidate)
            if len(selected) >= target_count:
                break

    return selected[:target_count], {
        "random": min(random_count, len(shuffled)),
        "largest": min(largest_count, len(largest_sorted)),
        "template_heavy": min(template_heavy_count, len(template_sorted)),
        "complex": min(complex_count, len(complex_sorted)),
    }


def connect_db() -> psycopg2.extensions.connection:
    try:
        return psycopg2.connect(
            dbname=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
        )
    except psycopg2.Error as exc:
        raise RuntimeError(f"Database connection failed: {exc}")


def upsert_pages(conn: psycopg2.extensions.connection, pages: List[PageCandidate], batch_size: int) -> int:
    page_sql = """
        INSERT INTO wiki_pages (
            page_id,
            title,
            revision_id,
            revision_timestamp,
            raw_wikitext
        )
        VALUES %s
        ON CONFLICT (page_id)
        DO UPDATE SET
            title = EXCLUDED.title,
            revision_id = EXCLUDED.revision_id,
            revision_timestamp = EXCLUDED.revision_timestamp,
            raw_wikitext = EXCLUDED.raw_wikitext
    """

    feature_sql = """
        INSERT INTO wiki_page_features (
            page_id,
            wikitext_length_bytes,
            template_count,
            image_count,
            reference_count,
            heading_count,
            internal_link_count,
            external_link_count,
            category_count
        )
        VALUES %s
        ON CONFLICT (page_id)
        DO UPDATE SET
            wikitext_length_bytes = EXCLUDED.wikitext_length_bytes,
            template_count = EXCLUDED.template_count,
            image_count = EXCLUDED.image_count,
            reference_count = EXCLUDED.reference_count,
            heading_count = EXCLUDED.heading_count,
            internal_link_count = EXCLUDED.internal_link_count,
            external_link_count = EXCLUDED.external_link_count,
            category_count = EXCLUDED.category_count
    """

    inserted = 0
    with conn:
        with conn.cursor() as cursor:
            for i in range(0, len(pages), batch_size):
                batch = pages[i : i + batch_size]

                page_rows = [
                    (
                        candidate.page_id,
                        candidate.title,
                        candidate.revision_id,
                        candidate.revision_timestamp,
                        candidate.raw_wikitext,
                    )
                    for candidate in batch
                ]

                feature_rows = [
                    (
                        candidate.page_id,
                        candidate.features["wikitext_length_bytes"],
                        candidate.features["template_count"],
                        candidate.features["image_count"],
                        candidate.features["reference_count"],
                        candidate.features["heading_count"],
                        candidate.features["internal_link_count"],
                        candidate.features["external_link_count"],
                        candidate.features["category_count"],
                    )
                    for candidate in batch
                ]

                psycopg2.extras.execute_values(cursor, page_sql, page_rows)
                psycopg2.extras.execute_values(cursor, feature_sql, feature_rows)
                inserted += len(batch)

    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Simple Wikipedia XML and load 10k pages into Postgres."
    )
    parser.add_argument("--xml-path", required=True, help="Path to the SimpleWiki XML dump")
    parser.add_argument("--target-count", type=int, default=10000)
    parser.add_argument("--random-count", type=int, default=6000)
    parser.add_argument("--largest-count", type=int, default=2000)
    parser.add_argument("--template-heavy-count", type=int, default=1000)
    parser.add_argument("--complex-count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    if not os.path.exists(args.xml_path):
        print(f"XML file not found: {args.xml_path}", file=sys.stderr)
        sys.exit(1)

    try:
        candidates, stats = collect_candidates(args.xml_path, min_length=50)
    except ET.ParseError as exc:
        print(f"Malformed XML: {exc}", file=sys.stderr)
        sys.exit(1)

    selection, selection_counts = select_pages(
        candidates,
        target_count=args.target_count,
        random_count=args.random_count,
        largest_count=args.largest_count,
        template_heavy_count=args.template_heavy_count,
        complex_count=args.complex_count,
        seed=args.seed,
    )

    if len(candidates) < args.target_count:
        print(
            f"Warning: only {len(candidates)} valid pages found; inserting all.",
            file=sys.stderr,
        )

    try:
        conn = connect_db()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    inserted = upsert_pages(conn, selection, args.batch_size)
    conn.close()

    print("Final summary:")
    print(f"  total pages seen: {stats.total_pages}")
    print(f"  redirects skipped: {stats.redirects_skipped}")
    print(f"  non-article skipped: {stats.non_article_skipped}")
    print(f"  empty/tiny skipped: {stats.empty_or_tiny_skipped}")
    print(f"  valid candidates: {stats.valid_candidates}")
    print(f"  selected pages: {len(selection)}")
    print(f"  inserted/updated pages: {inserted}")
    print(f"  random sample count: {selection_counts['random']}")
    print(f"  largest sample count: {selection_counts['largest']}")
    print(f"  template-heavy sample count: {selection_counts['template_heavy']}")
    print(f"  complex sample count: {selection_counts['complex']}")


if __name__ == "__main__":
    main()
