#!/usr/bin/env python3
"""
Download Piper voice model files from the official voice index.

Default source:
- voice index: voice_assets/piper/voices.json
- model base: https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0

Output:
- voice_assets/piper/voices/<voice_key>/*
- voice_assets/piper/download_manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_PRESET = [
    "zh_CN-huayan-x_low",
    "zh_CN-huayan-medium",
    "en_US-amy-medium",
    "en_US-joe-medium",
    "en_GB-alba-medium",
    "en_GB-alan-medium",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Piper voices to local folder.")
    parser.add_argument(
        "--index-file",
        default="voice_assets/piper/voices.json",
        help="Path to Piper voices.json file.",
    )
    parser.add_argument(
        "--base-url",
        default="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0",
        help="Base URL for Piper voice files.",
    )
    parser.add_argument(
        "--output-root",
        default="voice_assets/piper/voices",
        help="Directory to store downloaded voice files.",
    )
    parser.add_argument(
        "--manifest-file",
        default="voice_assets/piper/download_manifest.csv",
        help="CSV path for download manifest.",
    )
    parser.add_argument(
        "--voice",
        action="append",
        default=[],
        help="Voice key to download. Repeat or use comma-separated values.",
    )
    parser.add_argument(
        "--language",
        action="append",
        default=[],
        help="Language code filter, e.g. zh_CN, en_US. Repeatable.",
    )
    parser.add_argument(
        "--quality",
        action="append",
        default=[],
        help="Quality filter, e.g. x_low/low/medium/high. Repeatable.",
    )
    parser.add_argument(
        "--preset",
        choices=["starter", "none"],
        default="starter",
        help="Voice preset when --voice is empty.",
    )
    parser.add_argument(
        "--include-model-card",
        action="store_true",
        help="Also download MODEL_CARD files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing local files.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP timeout in seconds for each file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print planned downloads.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available voices from index and exit.",
    )
    return parser.parse_args()


def read_index(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Index not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_voice_args(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        for part in item.split(","):
            key = part.strip()
            if key:
                result.append(key)
    deduped: list[str] = []
    seen = set()
    for key in result:
        if key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped


def pick_voices(index: dict, args: argparse.Namespace) -> list[str]:
    user_voices = normalize_voice_args(args.voice)
    if user_voices:
        return user_voices

    langs = {x.strip() for x in args.language if x.strip()}
    quals = {x.strip() for x in args.quality if x.strip()}
    if langs or quals:
        matched: list[str] = []
        for key, meta in index.items():
            lang = str(meta.get("language", {}).get("code", ""))
            quality = str(meta.get("quality", ""))
            if langs and lang not in langs:
                continue
            if quals and quality not in quals:
                continue
            matched.append(key)
        matched.sort()
        return matched

    if args.preset == "starter":
        return list(DEFAULT_PRESET)
    return []


def should_keep_file(rel_path: str, include_model_card: bool) -> bool:
    if rel_path.endswith(".onnx") or rel_path.endswith(".onnx.json"):
        return True
    if include_model_card and rel_path.endswith("MODEL_CARD"):
        return True
    return False


def download(url: str, out_path: Path, timeout: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        data = r.read()
    out_path.write_bytes(data)


def main() -> None:
    args = parse_args()

    index_file = Path(args.index_file)
    output_root = Path(args.output_root)
    manifest_file = Path(args.manifest_file)

    index = read_index(index_file)

    if args.list:
        for key in sorted(index.keys()):
            meta = index[key]
            lang = str(meta.get("language", {}).get("code", ""))
            quality = str(meta.get("quality", ""))
            speakers = int(meta.get("num_speakers", 0))
            line = f"{key}\tlang={lang}\tquality={quality}\tspeakers={speakers}"
            try:
                print(line)
            except UnicodeEncodeError:
                # Windows GBK consoles may fail on some voice keys.
                print(line.encode("ascii", "backslashreplace").decode("ascii"))
        return

    selected = pick_voices(index, args)

    if not selected:
        raise RuntimeError("No voices selected. Use --voice or --preset starter.")

    missing = [v for v in selected if v not in index]
    if missing:
        raise RuntimeError(
            "Unknown voice key(s): "
            + ", ".join(missing)
            + "\nTip: inspect voice_assets/piper/voices.json for valid keys."
        )

    rows: list[dict[str, str]] = []
    ok = 0
    skip = 0
    fail = 0

    for voice_key in selected:
        meta = index[voice_key]
        language_code = str(meta.get("language", {}).get("code", ""))
        quality = str(meta.get("quality", ""))
        num_speakers = int(meta.get("num_speakers", 0))

        file_items = []
        for rel_path, info in meta.get("files", {}).items():
            if should_keep_file(rel_path, args.include_model_card):
                file_items.append((rel_path, info))

        if not file_items:
            continue

        file_items.sort(key=lambda x: x[0])
        voice_dir = output_root / voice_key
        voice_dir.mkdir(parents=True, exist_ok=True)

        for rel_path, info in file_items:
            filename = Path(rel_path).name
            out_path = voice_dir / filename
            url = args.base_url.rstrip("/") + "/" + rel_path
            expected_size = int(info.get("size_bytes", 0))
            md5 = str(info.get("md5_digest", ""))

            status = "downloaded"
            err = ""

            if out_path.exists() and not args.overwrite:
                status = "exists"
                skip += 1
            elif args.dry_run:
                status = "planned"
            else:
                try:
                    download(url, out_path, timeout=args.timeout)
                    ok += 1
                except (urllib.error.URLError, TimeoutError, OSError) as e:
                    status = "failed"
                    err = str(e)
                    fail += 1

            rows.append(
                {
                    "voice_key": voice_key,
                    "language": language_code,
                    "quality": quality,
                    "num_speakers": str(num_speakers),
                    "remote_path": rel_path,
                    "url": url,
                    "expected_size_bytes": str(expected_size),
                    "md5": md5,
                    "local_file": str(out_path),
                    "status": status,
                    "error": err,
                }
            )

    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    with manifest_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "voice_key",
                "language",
                "quality",
                "num_speakers",
                "remote_path",
                "url",
                "expected_size_bytes",
                "md5",
                "local_file",
                "status",
                "error",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Selected voices: {len(selected)}")
    print(f"Manifest: {manifest_file}")
    print(f"Downloaded: {ok}, skipped(existing): {skip}, failed: {fail}")

    if fail > 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
