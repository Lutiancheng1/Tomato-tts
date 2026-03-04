#!/usr/bin/env python3
"""
Batch synthesize audio from tts_chunks using Azure Speech Text-to-Speech REST API.

Input layout:
  tts_chunks/
    001_xxx/
      part_001.txt
      part_002.txt
      ...

Output layout:
  azure_tts_audio/
    001_xxx/
      part_001.wav|mp3|ogg
      part_002.wav|mp3|ogg
      chapter.wav                # only for RIFF PCM formats
    ...
  azure_tts_manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import urllib.error
import urllib.request
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape as xml_escape


FORMAT_META = {
    "riff-24khz-16bit-mono-pcm": {"ext": ".wav", "mergeable_wav": True},
    "riff-16khz-16bit-mono-pcm": {"ext": ".wav", "mergeable_wav": True},
    "audio-24khz-160kbitrate-mono-mp3": {"ext": ".mp3", "mergeable_wav": False},
    "audio-24khz-96kbitrate-mono-mp3": {"ext": ".mp3", "mergeable_wav": False},
    "ogg-24khz-16bit-mono-opus": {"ext": ".ogg", "mergeable_wav": False},
}

DEFAULT_VOICE_BY_LOCALE = {
    "zh-CN": "zh-CN-XiaochenNeural",
    "zh-HK": "zh-HK-HiuMaanNeural",
    "en-US": "en-US-JennyNeural",
}

MANIFEST_FIELDS = [
    "index",
    "chapter_dir",
    "parts",
    "chars",
    "region",
    "voice_name",
    "locale",
    "output_format",
    "style",
    "chapter_audio_seconds",
    "chapter_audio_file",
    "output_subdir",
    "updated_at_utc",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthesize audio files from tts_chunks with Azure Speech TTS."
    )
    parser.add_argument(
        "--book-dir",
        default="wodebooks_output/book_94814546_full_20260304",
        help="Book directory containing tts_chunks.",
    )
    parser.add_argument(
        "--chunks-root",
        default="",
        help="Chunk root directory. Default: <book-dir>/tts_chunks",
    )
    parser.add_argument(
        "--output-root",
        default="",
        help="Output root directory. Default: <book-dir>/azure_tts_audio",
    )
    parser.add_argument(
        "--manifest-file",
        default="",
        help="Manifest CSV file. Default: <book-dir>/azure_tts_manifest.csv",
    )
    parser.add_argument(
        "--progress-file",
        default="",
        help="Progress CSV file. Default: <book-dir>/azure_tts_progress.csv",
    )

    parser.add_argument(
        "--region",
        default="",
        help=(
            "Azure Speech region, e.g. eastus. "
            "If empty, reads AZURE_TTS_REGION or AZURE_SPEECH_REGION."
        ),
    )
    parser.add_argument(
        "--api-key",
        default="",
        help=(
            "Azure Speech key. "
            "If empty, reads AZURE_TTS_KEY or AZURE_SPEECH_KEY."
        ),
    )
    parser.add_argument(
        "--endpoint-base",
        default="",
        help=(
            "Optional endpoint base URL, e.g. https://eastus.tts.speech.microsoft.com . "
            "If set, this overrides --region for endpoint building."
        ),
    )

    parser.add_argument(
        "--locale",
        default="zh-CN",
        help="Locale for synthesis/listing, e.g. zh-CN, en-US.",
    )
    parser.add_argument(
        "--voice-name",
        default="",
        help=(
            "Optional exact Azure short voice name, e.g. zh-CN-XiaochenNeural. "
            "If empty, script uses a built-in default for common locales."
        ),
    )
    parser.add_argument(
        "--output-format",
        default="riff-24khz-16bit-mono-pcm",
        choices=sorted(FORMAT_META.keys()),
        help="Azure output format (maps to wav/mp3/ogg).",
    )
    parser.add_argument(
        "--speaking-rate",
        type=float,
        default=1.0,
        help="Speaking rate multiplier (e.g. 1.0 normal, 1.1 faster).",
    )
    parser.add_argument(
        "--pitch",
        type=float,
        default=0.0,
        help="Pitch in semitones (e.g. -2.0 ~ +2.0).",
    )
    parser.add_argument(
        "--style",
        default="",
        help="Optional speaking style if the voice supports it, e.g. cheerful.",
    )
    parser.add_argument(
        "--style-degree",
        type=float,
        default=1.0,
        help="Optional style degree for --style (typically 0.01~2.0).",
    )
    parser.add_argument(
        "--role",
        default="",
        help="Optional role when using --style, e.g. YoungAdultFemale.",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0.05,
        help="Delay seconds between API requests.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Request timeout seconds.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retries per part on transient errors.",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=1.2,
        help="Base seconds for linear retry backoff.",
    )
    parser.add_argument(
        "--gap-ms",
        type=int,
        default=250,
        help="Silence gap when merging wav parts to chapter.wav.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Start chapter index (1-based from folder prefix).",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=0,
        help="End chapter index (inclusive). 0 means all.",
    )
    parser.add_argument(
        "--max-parts",
        type=int,
        default=0,
        help="Limit parts per chapter for quick tests. 0 means all.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing audio files.",
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="List voices for --locale and exit.",
    )
    return parser.parse_args()


def chapter_index_from_name(name: str, fallback: int) -> int:
    match = re.match(r"^(\d+)_", name)
    return int(match.group(1)) if match else fallback


def default_voice_name(locale: str) -> str:
    for key, val in DEFAULT_VOICE_BY_LOCALE.items():
        if locale.startswith(key):
            return val
    return ""


def rate_to_ssml(rate: float) -> str:
    if rate <= 0:
        raise ValueError("--speaking-rate must be > 0")
    pct = (rate - 1.0) * 100.0
    return f"{pct:+.0f}%"


def pitch_to_ssml(pitch_st: float) -> str:
    return f"{pitch_st:+.1f}st"


def endpoint_base(args: argparse.Namespace, region: str) -> str:
    base = args.endpoint_base.strip()
    if base:
        return base.rstrip("/")
    return f"https://{region}.tts.speech.microsoft.com"


def merge_wavs(wav_files: list[Path], out_file: Path, gap_ms: int) -> float:
    if not wav_files:
        return 0.0

    with wave.open(str(wav_files[0]), "rb") as wf0:
        nchannels = wf0.getnchannels()
        sampwidth = wf0.getsampwidth()
        framerate = wf0.getframerate()
        comptype = wf0.getcomptype()
        compname = wf0.getcompname()

    gap_frames = int(framerate * gap_ms / 1000)
    silence = b"\x00" * (gap_frames * nchannels * sampwidth)

    total_frames = 0
    with wave.open(str(out_file), "wb") as out:
        out.setnchannels(nchannels)
        out.setsampwidth(sampwidth)
        out.setframerate(framerate)
        out.setcomptype(comptype, compname)

        for i, wav_file in enumerate(wav_files, start=1):
            with wave.open(str(wav_file), "rb") as w:
                if (
                    w.getnchannels() != nchannels
                    or w.getsampwidth() != sampwidth
                    or w.getframerate() != framerate
                ):
                    raise RuntimeError(f"WAV format mismatch: {wav_file}")
                frames = w.readframes(w.getnframes())
                out.writeframes(frames)
                total_frames += w.getnframes()
            if i != len(wav_files) and gap_frames > 0:
                out.writeframes(silence)
                total_frames += gap_frames

    return float(total_frames) / float(framerate)


def load_existing_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for raw in reader:
            chapter_dir = (raw.get("chapter_dir") or "").strip()
            if not chapter_dir:
                continue
            normalized: dict[str, str] = {}
            for key in MANIFEST_FIELDS:
                normalized[key] = str(raw.get(key, "") or "")
            rows[chapter_dir] = normalized
    return rows


def rows_sorted_by_index(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    def key_fn(row: dict[str, str]) -> tuple[int, str]:
        raw = (row.get("index") or "").strip()
        try:
            idx = int(raw)
        except ValueError:
            idx = 10**9
        return (idx, row.get("chapter_dir", ""))

    return sorted(rows, key=key_fn)


def count_audio_parts(chapter_out_dir: Path) -> int:
    if not chapter_out_dir.exists():
        return 0
    count = 0
    for path in chapter_out_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".wav", ".mp3", ".ogg"}:
            continue
        if re.match(r"^part_\d+\.(wav|mp3|ogg)$", path.name, flags=re.IGNORECASE):
            count += 1
    return count


def request_json(url: str, headers: dict[str, str], timeout_s: float) -> object:
    req = urllib.request.Request(url=url, method="GET", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_http_error(ex: urllib.error.HTTPError) -> str:
    try:
        return ex.read().decode("utf-8", errors="replace")
    except Exception:
        return str(ex)


def list_voices(
    args: argparse.Namespace,
    api_key: str,
    region: str,
) -> None:
    base = endpoint_base(args, region)
    url = f"{base}/cognitiveservices/voices/list"
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    payload = request_json(url, headers, args.timeout)
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected voices response: {payload}")

    locale = args.locale.strip().lower()
    rows: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        voice_locale = str(item.get("Locale", ""))
        if locale and not voice_locale.lower().startswith(locale):
            continue
        rows.append(
            {
                "short": str(item.get("ShortName", "")),
                "locale": voice_locale,
                "gender": str(item.get("Gender", "")),
                "sample_rate": str(item.get("SampleRateHertz", "")),
                "voice_type": str(item.get("VoiceType", "")),
                "style_list": ",".join(item.get("StyleList", []) or []),
            }
        )

    rows.sort(key=lambda x: x["short"])
    print(f"Voices for locale={args.locale} ({len(rows)}):")
    for row in rows:
        print(
            "  - "
            f"{row['short']} | locale={row['locale']} | gender={row['gender']} | "
            f"hz={row['sample_rate']} | type={row['voice_type']} | styles={row['style_list']}"
        )


def build_ssml(
    text: str,
    locale: str,
    voice_name: str,
    speaking_rate: float,
    pitch_st: float,
    style: str,
    style_degree: float,
    role: str,
) -> str:
    escaped_text = xml_escape(text)
    rate_val = rate_to_ssml(speaking_rate)
    pitch_val = pitch_to_ssml(pitch_st)
    prosody = (
        f'<prosody rate="{rate_val}" pitch="{pitch_val}">'
        f"{escaped_text}</prosody>"
    )

    if style:
        attrs = [f'style="{xml_escape(style)}"', f'styledegree="{style_degree:.2f}"']
        if role:
            attrs.append(f'role="{xml_escape(role)}"')
        inner = f"<mstts:express-as {' '.join(attrs)}>{prosody}</mstts:express-as>"
    else:
        inner = prosody

    return (
        f'<speak version="1.0" xml:lang="{xml_escape(locale)}" '
        'xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts">'
        f'<voice name="{xml_escape(voice_name)}">{inner}</voice>'
        "</speak>"
    )


def synthesize_rest(
    text: str,
    args: argparse.Namespace,
    api_key: str,
    region: str,
    voice_name: str,
) -> bytes:
    base = endpoint_base(args, region)
    url = f"{base}/cognitiveservices/v1"
    ssml = build_ssml(
        text=text,
        locale=args.locale,
        voice_name=voice_name,
        speaking_rate=args.speaking_rate,
        pitch_st=args.pitch,
        style=args.style.strip(),
        style_degree=args.style_degree,
        role=args.role.strip(),
    )
    headers = {
        "Ocp-Apim-Subscription-Key": api_key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": args.output_format,
        "User-Agent": "tomato-tts/azure-tts",
    }
    req = urllib.request.Request(
        url=url,
        data=ssml.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as ex:
        detail = read_http_error(ex)
        raise RuntimeError(f"Azure TTS HTTP {ex.code}: {detail}") from ex


def synthesize_with_retries(
    text: str,
    synthesize_fn: Callable[[str], bytes],
    retries: int,
    retry_backoff: float,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            return synthesize_fn(text)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, Exception) as ex:
            last_error = ex
            if attempt > retries:
                break
            wait_s = retry_backoff * attempt
            print(f"[retry {attempt}/{retries}] {ex}")
            time.sleep(wait_s)
    raise RuntimeError(f"Synthesize failed after retries: {last_error}") from last_error


def main() -> None:
    args = parse_args()

    api_key = (
        args.api_key.strip()
        or os.environ.get("AZURE_TTS_KEY", "").strip()
        or os.environ.get("AZURE_SPEECH_KEY", "").strip()
    )
    region = (
        args.region.strip()
        or os.environ.get("AZURE_TTS_REGION", "").strip()
        or os.environ.get("AZURE_SPEECH_REGION", "").strip()
    )
    if not api_key:
        raise RuntimeError(
            "Missing Azure API key. Set --api-key or AZURE_TTS_KEY/AZURE_SPEECH_KEY."
        )
    if not region and not args.endpoint_base.strip():
        raise RuntimeError(
            "Missing Azure region. Set --region or AZURE_TTS_REGION/AZURE_SPEECH_REGION."
        )

    book_dir = Path(args.book_dir).resolve()
    chunks_root = Path(args.chunks_root).resolve() if args.chunks_root else (book_dir / "tts_chunks")
    output_root = (
        Path(args.output_root).resolve() if args.output_root else (book_dir / "azure_tts_audio")
    )
    manifest_file = (
        Path(args.manifest_file).resolve()
        if args.manifest_file
        else (book_dir / "azure_tts_manifest.csv")
    )
    progress_file = (
        Path(args.progress_file).resolve()
        if args.progress_file
        else (book_dir / "azure_tts_progress.csv")
    )

    if not chunks_root.exists():
        raise RuntimeError(f"Chunk root not found: {chunks_root}")

    output_root.mkdir(parents=True, exist_ok=True)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    progress_file.parent.mkdir(parents=True, exist_ok=True)

    if args.list_voices:
        list_voices(args, api_key, region)
        return

    voice_name = args.voice_name.strip() or default_voice_name(args.locale)
    if not voice_name:
        raise RuntimeError(
            "No voice selected. Pass --voice-name explicitly for this locale."
        )
    if args.style and args.style_degree <= 0:
        raise RuntimeError("--style-degree must be > 0 when --style is set.")

    fmt_meta = FORMAT_META[args.output_format]
    audio_ext = str(fmt_meta["ext"])
    can_merge_wav = bool(fmt_meta["mergeable_wav"])

    synthesize_fn = lambda text: synthesize_rest(text, args, api_key, region, voice_name)

    chapter_dirs = sorted([p for p in chunks_root.iterdir() if p.is_dir()])
    selected: list[Path] = []
    for i, chapter_dir in enumerate(chapter_dirs, start=1):
        idx = chapter_index_from_name(chapter_dir.name, i)
        if idx < args.start:
            continue
        if args.end > 0 and idx > args.end:
            continue
        selected.append(chapter_dir)

    if not selected:
        raise RuntimeError("No chapter directories selected.")

    rows: list[dict[str, str]] = []
    updated_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    total_parts = 0
    total_chars = 0
    total_secs = 0.0

    for i, chapter_dir in enumerate(selected, start=1):
        part_files = sorted(chapter_dir.glob("part_*.txt"))
        if args.max_parts > 0:
            part_files = part_files[: args.max_parts]
        if not part_files:
            continue

        out_chapter_dir = output_root / chapter_dir.name
        out_chapter_dir.mkdir(parents=True, exist_ok=True)

        produced_parts: list[Path] = []
        chapter_chars = 0

        for part_txt in part_files:
            text = part_txt.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                continue

            chapter_chars += len(text)
            out_audio = out_chapter_dir / f"{part_txt.stem}{audio_ext}"
            if args.overwrite or not out_audio.exists():
                audio_bytes = synthesize_with_retries(
                    text=text,
                    synthesize_fn=synthesize_fn,
                    retries=args.retries,
                    retry_backoff=args.retry_backoff,
                )
                out_audio.write_bytes(audio_bytes)
                if args.delay > 0:
                    time.sleep(args.delay)

            if out_audio.exists():
                produced_parts.append(out_audio)

        if not produced_parts:
            continue

        chapter_audio_file = ""
        chapter_audio_seconds = ""
        if can_merge_wav:
            chapter_wav = out_chapter_dir / "chapter.wav"
            merged_secs = merge_wavs(produced_parts, chapter_wav, args.gap_ms)
            chapter_audio_file = str(chapter_wav.relative_to(output_root))
            chapter_audio_seconds = f"{merged_secs:.3f}"
            total_secs += merged_secs

        idx = chapter_index_from_name(chapter_dir.name, i)
        rows.append(
            {
                "index": str(idx),
                "chapter_dir": chapter_dir.name,
                "parts": str(len(produced_parts)),
                "chars": str(chapter_chars),
                "region": region or "custom-endpoint",
                "voice_name": voice_name,
                "locale": args.locale,
                "output_format": args.output_format,
                "style": args.style.strip(),
                "chapter_audio_seconds": chapter_audio_seconds,
                "chapter_audio_file": chapter_audio_file,
                "output_subdir": str(out_chapter_dir.relative_to(output_root)),
                "updated_at_utc": updated_at_utc,
            }
        )

        total_parts += len(produced_parts)
        total_chars += chapter_chars
        print(
            f"[{i}/{len(selected)}] parts={len(produced_parts):>3} "
            f"chars={chapter_chars:>5} {chapter_dir.name}"
        )

    existing_rows = load_existing_manifest(manifest_file)
    for row in rows:
        existing_rows[row["chapter_dir"]] = row
    merged_rows = rows_sorted_by_index(list(existing_rows.values()))

    with manifest_file.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=MANIFEST_FIELDS,
        )
        writer.writeheader()
        writer.writerows(merged_rows)

    progress_rows: list[dict[str, str]] = []
    done_count = 0
    partial_count = 0
    todo_count = 0

    for i, chapter_dir in enumerate(chapter_dirs, start=1):
        idx = chapter_index_from_name(chapter_dir.name, i)
        expected_parts = len(list(chapter_dir.glob("part_*.txt")))
        out_chapter_dir = output_root / chapter_dir.name
        generated_parts = count_audio_parts(out_chapter_dir)
        chapter_wav_exists = (out_chapter_dir / "chapter.wav").exists()
        merged_meta = existing_rows.get(chapter_dir.name, {})

        if expected_parts == 0:
            status = "TODO"
        else:
            enough_parts = generated_parts >= expected_parts
            wav_ok = (not can_merge_wav) or chapter_wav_exists
            if enough_parts and wav_ok:
                status = "DONE"
            elif generated_parts > 0:
                status = "PARTIAL"
            else:
                status = "TODO"

        if status == "DONE":
            done_count += 1
        elif status == "PARTIAL":
            partial_count += 1
        else:
            todo_count += 1

        progress_rows.append(
            {
                "index": str(idx),
                "chapter_dir": chapter_dir.name,
                "status": status,
                "expected_parts": str(expected_parts),
                "generated_parts": str(generated_parts),
                "chapter_wav_exists": str(chapter_wav_exists),
                "voice_name": str(merged_meta.get("voice_name", "")),
                "output_format": str(merged_meta.get("output_format", "")),
                "updated_at_utc": str(merged_meta.get("updated_at_utc", "")),
            }
        )

    with progress_file.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "index",
                "chapter_dir",
                "status",
                "expected_parts",
                "generated_parts",
                "chapter_wav_exists",
                "voice_name",
                "output_format",
                "updated_at_utc",
            ],
        )
        writer.writeheader()
        writer.writerows(rows_sorted_by_index(progress_rows))

    print("\nDone.")
    print(f"Voice         : {voice_name}")
    print(f"Locale        : {args.locale}")
    print(f"Format        : {args.output_format}")
    print(f"Chunks root   : {chunks_root}")
    print(f"Output root   : {output_root}")
    print(f"Manifest      : {manifest_file}")
    print(f"Progress      : {progress_file}")
    print(f"Chapters done : {len(rows)}")
    print(f"Parts done    : {total_parts}")
    print(f"Chars done    : {total_chars}")
    print(f"Progress stat : DONE={done_count} PARTIAL={partial_count} TODO={todo_count}")
    if can_merge_wav:
        print(f"Total seconds : {total_secs:.2f}")


if __name__ == "__main__":
    main()
