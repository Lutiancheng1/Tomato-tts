#!/usr/bin/env python3
"""
Scrape chapter text from wodebooks novel pages.

Features:
- Discover TOC pages from the TOC page selector.
- Extract chapter start URLs from the main chapter list on each TOC page.
- Follow intra-chapter pagination (e.g. xxx.html -> xxx_2.html -> ...).
- Export per-chapter txt files, a merged txt, and index.csv.
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def fetch_html(session: requests.Session, url: str, retries: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.8 * attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def strip_tags(fragment: str) -> str:
    text = re.sub(r"<script.*?</script>", "", fragment, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<p[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\r", "")
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines).strip()


def sanitize_filename(name: str, max_len: int = 80) -> str:
    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        name = "chapter"
    return name[:max_len].rstrip(" .")


def parse_base_chapter_id(url: str) -> str | None:
    path = urlparse(url).path
    match = re.search(r"/(\d+)(?:_\d+)?\.html$", path)
    return match.group(1) if match else None


def parse_chapter_page(html_doc: str) -> tuple[str, str, str | None]:
    title_match = re.search(
        r'<h1[^>]*class="title"[^>]*>(.*?)</h1>',
        html_doc,
        flags=re.I | re.S,
    )
    content_match = re.search(
        r'<div[^>]*id="content"[^>]*>(.*?)</div>',
        html_doc,
        flags=re.I | re.S,
    )
    next_match = re.search(
        r'<a[^>]*id="next_url"[^>]*href="([^"]+)"',
        html_doc,
        flags=re.I,
    )
    title = strip_tags(title_match.group(1)) if title_match else ""
    content = strip_tags(content_match.group(1)) if content_match else ""
    next_href = next_match.group(1).strip() if next_match else None
    return title, content, next_href


def sort_toc_urls(urls: Iterable[str], expected_prefix: str) -> list[str]:
    def toc_order(u: str) -> tuple[int, str]:
        path = urlparse(u).path.rstrip("/")
        prefix = expected_prefix.rstrip("/")
        if path == prefix:
            return (1, u)
        match = re.search(r"/(\d+)$", path)
        if match:
            return (int(match.group(1)), u)
        return (10_000, u)

    return sorted(set(urls), key=toc_order)


def discover_toc_urls(
    session: requests.Session,
    book_url: str,
    book_path_prefix: str,
) -> list[str]:
    first_html = fetch_html(session, book_url)
    option_paths = re.findall(
        r'<option[^>]*value="(/book_\d+/(?:\d+/)?)"',
        first_html,
        flags=re.I,
    )
    urls = [book_url]
    for path in option_paths:
        urls.append(urljoin(book_url, path))
    return sort_toc_urls(urls, book_path_prefix)


def extract_main_chapter_links(toc_html: str, book_id: str) -> list[tuple[str, str]]:
    chapter_link_re = re.compile(
        rf'<a[^>]*href="(/book_{book_id}/\d+\.html)"[^>]*>(.*?)</a>',
        flags=re.I | re.S,
    )

    # Use selected page range (e.g. "1 - 100章") to know how many chapters this TOC page holds.
    expected_count = 0
    selected_match = re.search(
        r"<option[^>]*selected[^>]*>([^<]+)</option>",
        toc_html,
        flags=re.I,
    )
    if selected_match:
        nums = re.findall(r"\d+", selected_match.group(1))
        if len(nums) >= 2:
            start_num = int(nums[0])
            end_num = int(nums[1])
            if end_num >= start_num:
                expected_count = end_num - start_num + 1

    # Chapter list appears right before the pager container.
    pager_pos = toc_html.find('class="index-container"')
    if pager_pos == -1:
        pager_pos = len(toc_html)
    candidate_region = toc_html[:pager_pos]

    all_links: list[tuple[str, str]] = []
    for href, raw_title in chapter_link_re.findall(candidate_region):
        all_links.append((href, strip_tags(raw_title)))

    if expected_count > 0 and len(all_links) >= expected_count:
        return all_links[-expected_count:]

    # Fallback: dedupe in original order.
    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href, title in all_links:
        if href in seen:
            continue
        seen.add(href)
        deduped.append((href, title))
    return deduped


def collect_chapter_urls(
    session: requests.Session,
    toc_urls: list[str],
    book_id: str,
) -> list[tuple[str, str]]:
    chapters: list[tuple[str, str]] = []
    seen: set[str] = set()
    for toc_url in toc_urls:
        toc_html = fetch_html(session, toc_url)
        links = extract_main_chapter_links(toc_html, book_id)
        for href, toc_title in links:
            abs_url = urljoin(toc_url, href)
            if abs_url in seen:
                continue
            seen.add(abs_url)
            chapters.append((abs_url, toc_title))
    return chapters


def fetch_full_chapter(
    session: requests.Session,
    start_url: str,
    delay_seconds: float,
) -> tuple[str, str, int]:
    chapter_id = parse_base_chapter_id(start_url)
    if not chapter_id:
        raise RuntimeError(f"Invalid chapter URL: {start_url}")

    page_count = 0
    page_texts: list[str] = []
    chapter_title = ""
    current_url = start_url
    visited: set[str] = set()

    while current_url not in visited:
        visited.add(current_url)
        html_doc = fetch_html(session, current_url)
        title, content, next_href = parse_chapter_page(html_doc)
        page_count += 1
        if title and not chapter_title:
            chapter_title = title
        if content:
            if not page_texts or content != page_texts[-1]:
                page_texts.append(content)

        if not next_href or next_href.lower().startswith("javascript:"):
            break
        next_url = urljoin(current_url, next_href)
        next_chapter_id = parse_base_chapter_id(next_url)
        if next_chapter_id != chapter_id:
            break
        current_url = next_url
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    return chapter_title, "\n\n".join(page_texts).strip(), page_count


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape full novel text from a wodebooks book page."
    )
    parser.add_argument(
        "--book-url",
        default="https://www.wodebooks.com/book_94814546/",
        help="Book TOC URL, e.g. https://www.wodebooks.com/book_94814546/",
    )
    parser.add_argument(
        "--output-dir",
        default="wodebooks_output/book_94814546",
        help="Output directory for txt/csv files.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="1-based start chapter index (after TOC collection).",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=0,
        help="1-based end chapter index, 0 means all.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="Delay between chapter/page requests in seconds.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    book_url = args.book_url

    parsed = urlparse(book_url)
    path = parsed.path
    book_match = re.search(r"/book_(\d+)/", path)
    if not book_match:
        raise RuntimeError(f"Cannot parse book_id from URL: {book_url}")
    book_id = book_match.group(1)
    book_path_prefix = f"/book_{book_id}/"

    output_dir = Path(args.output_dir)
    chapters_dir = output_dir / "chapters"
    ensure_dir(chapters_dir)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    toc_urls = discover_toc_urls(session, book_url, book_path_prefix)
    print(f"Discovered TOC pages: {len(toc_urls)}")
    for u in toc_urls:
        print(f"  - {u}")

    chapters = collect_chapter_urls(session, toc_urls, book_id)
    if not chapters:
        raise RuntimeError("No chapter links found from TOC pages.")

    total = len(chapters)
    start_idx = max(args.start, 1)
    end_idx = args.end if args.end > 0 else total
    end_idx = min(end_idx, total)
    if start_idx > end_idx:
        raise RuntimeError(f"Invalid range: start={start_idx}, end={end_idx}")

    selected = chapters[start_idx - 1 : end_idx]
    print(f"Collected chapters: {total}, processing [{start_idx}, {end_idx}] ...")

    merged_parts: list[str] = []
    index_rows: list[dict[str, str]] = []

    for idx, (chapter_url, toc_title) in enumerate(selected, start=start_idx):
        title, text, pages = fetch_full_chapter(session, chapter_url, args.delay)
        final_title = title or toc_title or f"Chapter {idx}"
        safe_name = sanitize_filename(final_title)
        chapter_file = chapters_dir / f"{idx:03d}_{safe_name}.txt"
        chapter_file.write_text(text + "\n", encoding="utf-8")

        merged_parts.append(f"### {idx:03d} {final_title}\n\n{text}\n")
        index_rows.append(
            {
                "index": str(idx),
                "title": final_title,
                "url": chapter_url,
                "pages": str(pages),
                "chars": str(len(text)),
                "file": str(chapter_file.name),
            }
        )
        print(f"[{idx}/{end_idx}] pages={pages:>2} chars={len(text):>5} {final_title}")
        if args.delay > 0:
            time.sleep(args.delay)

    merged_file = output_dir / "merged.txt"
    merged_file.write_text("\n\n".join(merged_parts).strip() + "\n", encoding="utf-8")

    index_file = output_dir / "index.csv"
    with index_file.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(
            fp, fieldnames=["index", "title", "url", "pages", "chars", "file"]
        )
        writer.writeheader()
        writer.writerows(index_rows)

    print("\nDone.")
    print(f"Output dir: {output_dir.resolve()}")
    print(f"Chapter txt: {chapters_dir.resolve()}")
    print(f"Merged file: {merged_file.resolve()}")
    print(f"Index file : {index_file.resolve()}")


if __name__ == "__main__":
    main()
