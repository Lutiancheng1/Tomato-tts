#!/usr/bin/env python3
"""
Prepare chapter text files for TTS.

Input:
- chapter txt files (one file per chapter)

Output:
- cleaned chapter files (one file per chapter)
- chunked files under per-chapter folders (API-friendly chunk size)
- tts_manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


NOISE_LINE_PATTERNS = [
    re.compile(r"^\s*(上一[页章]|下一[页章]|返回目录|目录|加入书签|投推荐票).*$"),
    re.compile(r"^\s*本章(完|未完).*$"),
    re.compile(r"^\s*(请收藏|最新网址|手机用户|请记住).*$"),
    re.compile(r"^\s*\d{4}[-/年]\d{1,2}[-/月]\d{1,2}.*$"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean and chunk novel chapters for TTS consumption."
    )
    parser.add_argument(
        "--book-dir",
        default="wodebooks_output/book_94814546_full_20260304",
        help="Book output directory containing chapters/.",
    )
    parser.add_argument(
        "--chapters-dir",
        default="",
        help="Source chapters directory. Default: <book-dir>/chapters",
    )
    parser.add_argument(
        "--tts-chapters-dir",
        default="",
        help="Output cleaned chapters directory. Default: <book-dir>/tts_chapters",
    )
    parser.add_argument(
        "--tts-chunks-dir",
        default="",
        help="Output chunk directory. Default: <book-dir>/tts_chunks",
    )
    parser.add_argument(
        "--manifest-file",
        default="",
        help="Manifest CSV path. Default: <book-dir>/tts_manifest.csv",
    )
    parser.add_argument(
        "--chunk-max-chars",
        type=int,
        default=280,
        help="Max chars per chunk file.",
    )
    parser.add_argument(
        "--sentence-max-chars",
        type=int,
        default=60,
        help="Try splitting long sentences to this max length.",
    )
    return parser.parse_args()


def normalize_text(text: str) -> str:
    text = text.replace("\ufeff", "").replace("\u200b", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ")

    replacements = {
        "...": "……",
        "。。。": "。",
        "！！": "！",
        "？？": "？",
        "﹗": "！",
        "﹖": "？",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)

    text = re.sub(r"\.{3,}", "……", text)
    text = re.sub(r"…{3,}", "……", text)
    text = re.sub(r"—{3,}", "——", text)

    # Remove extra spaces around Chinese punctuation.
    text = re.sub(r"\s+([，。！？；：、“”‘’）】》])", r"\1", text)
    text = re.sub(r"([（【《“‘])\s+", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_noise_line(line: str) -> bool:
    if not line:
        return True
    for pattern in NOISE_LINE_PATTERNS:
        if pattern.match(line):
            return True
    return False


def split_sentences(line: str) -> list[str]:
    # Keep punctuation and ending quotes with the same sentence.
    items = re.findall(r"[^。！？!?；;…]+[。！？!?；;…]*[”’」』】》）]?", line)
    cleaned = [it.strip() for it in items if it.strip()]
    return cleaned if cleaned else [line.strip()]


def split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]

    # Prefer split by comma-like punctuation first.
    parts = re.split(r"(?<=[，、：:])", sentence)
    if len(parts) == 1:
        return [sentence[i : i + max_chars] for i in range(0, len(sentence), max_chars)]

    out: list[str] = []
    buf = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not buf:
            buf = part
            continue
        if len(buf) + len(part) <= max_chars:
            buf += part
        else:
            out.append(buf)
            buf = part
    if buf:
        out.append(buf)

    # Hard split if any piece is still too long.
    final_out: list[str] = []
    for piece in out:
        if len(piece) <= max_chars:
            final_out.append(piece)
        else:
            final_out.extend(
                [piece[i : i + max_chars] for i in range(0, len(piece), max_chars)]
            )
    return final_out


def chapter_to_sentences(text: str, sentence_max_chars: int) -> list[str]:
    normalized = normalize_text(text)
    lines = [ln.strip() for ln in normalized.split("\n")]
    sentences: list[str] = []
    for line in lines:
        if is_noise_line(line):
            continue
        for sent in split_sentences(line):
            for short in split_long_sentence(sent, sentence_max_chars):
                short = short.strip()
                if short:
                    sentences.append(short)
    return sentences


def build_chunks(sentences: list[str], max_chars: int) -> list[str]:
    chunks: list[str] = []
    buf = ""
    for sent in sentences:
        candidate = sent if not buf else (buf + "\n" + sent)
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            chunks.append(buf.strip())
        if len(sent) <= max_chars:
            buf = sent
        else:
            # Final safeguard.
            for i in range(0, len(sent), max_chars):
                chunks.append(sent[i : i + max_chars].strip())
            buf = ""
    if buf:
        chunks.append(buf.strip())
    return [c for c in chunks if c]


def parse_chapter_index(filename: str, fallback: int) -> int:
    match = re.match(r"^(\d+)_", filename)
    if match:
        return int(match.group(1))
    return fallback


def main() -> None:
    args = parse_args()

    book_dir = Path(args.book_dir)
    chapters_dir = Path(args.chapters_dir) if args.chapters_dir else (book_dir / "chapters")
    tts_chapters_dir = (
        Path(args.tts_chapters_dir)
        if args.tts_chapters_dir
        else (book_dir / "tts_chapters")
    )
    tts_chunks_dir = (
        Path(args.tts_chunks_dir) if args.tts_chunks_dir else (book_dir / "tts_chunks")
    )
    manifest_file = (
        Path(args.manifest_file)
        if args.manifest_file
        else (book_dir / "tts_manifest.csv")
    )

    if not chapters_dir.exists():
        raise RuntimeError(f"Chapters dir not found: {chapters_dir}")

    tts_chapters_dir.mkdir(parents=True, exist_ok=True)
    tts_chunks_dir.mkdir(parents=True, exist_ok=True)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)

    chapter_files = sorted(chapters_dir.glob("*.txt"))
    if not chapter_files:
        raise RuntimeError(f"No chapter txt files found in: {chapters_dir}")

    rows: list[dict[str, str]] = []
    total_sentences = 0
    total_chunks = 0

    for i, src_file in enumerate(chapter_files, start=1):
        raw = src_file.read_text(encoding="utf-8", errors="ignore")
        sentences = chapter_to_sentences(raw, args.sentence_max_chars)
        cleaned_text = "\n".join(sentences).strip() + "\n"
        chunks = build_chunks(sentences, args.chunk_max_chars)

        dst_chapter = tts_chapters_dir / src_file.name
        dst_chapter.write_text(cleaned_text, encoding="utf-8")

        chunk_subdir = tts_chunks_dir / src_file.stem
        chunk_subdir.mkdir(parents=True, exist_ok=True)
        for idx, chunk_text in enumerate(chunks, start=1):
            chunk_file = chunk_subdir / f"part_{idx:03d}.txt"
            chunk_file.write_text(chunk_text.strip() + "\n", encoding="utf-8")

        chapter_index = parse_chapter_index(src_file.name, i)
        rows.append(
            {
                "index": str(chapter_index),
                "source_file": src_file.name,
                "clean_file": dst_chapter.name,
                "sentence_count": str(len(sentences)),
                "chunk_count": str(len(chunks)),
                "clean_chars": str(len(cleaned_text.strip())),
            }
        )
        total_sentences += len(sentences)
        total_chunks += len(chunks)
        print(
            f"[{i}/{len(chapter_files)}] sentences={len(sentences):>3} "
            f"chunks={len(chunks):>2} {src_file.name}"
        )

    with manifest_file.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "index",
                "source_file",
                "clean_file",
                "sentence_count",
                "chunk_count",
                "clean_chars",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\nDone.")
    print(f"Source chapters: {chapters_dir.resolve()}")
    print(f"TTS chapters   : {tts_chapters_dir.resolve()}")
    print(f"TTS chunks     : {tts_chunks_dir.resolve()}")
    print(f"Manifest       : {manifest_file.resolve()}")
    print(f"Total chapters : {len(chapter_files)}")
    print(f"Total sentences: {total_sentences}")
    print(f"Total chunks   : {total_chunks}")


if __name__ == "__main__":
    main()
