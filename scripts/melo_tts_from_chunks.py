#!/usr/bin/env python3
"""
Batch synthesize TTS audio from chunked text folders using MeloTTS.

Input layout:
  tts_chunks/
    001_xxx/
      part_001.txt
      part_002.txt
      ...

Output layout:
  melo_wav/
    001_xxx/
      part_001.wav
      part_002.wav
      chapter.wav
    ...
  melo_manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import wave
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthesize wav files from tts_chunks with MeloTTS."
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
        help="Output root directory. Default: <book-dir>/melo_wav",
    )
    parser.add_argument(
        "--manifest-file",
        default="",
        help="Manifest CSV file. Default: <book-dir>/melo_manifest.csv",
    )
    parser.add_argument(
        "--language",
        default="ZH",
        help="Melo language code, e.g. ZH/EN/JP/KR/ES/FR.",
    )
    parser.add_argument(
        "--speaker",
        default="ZH",
        help="Speaker id key in model.hps.data.spk2id, e.g. ZH, EN-US.",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="Device string: auto/cpu/cuda:0.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speech speed passed to MeloTTS.",
    )
    parser.add_argument(
        "--gap-ms",
        type=int,
        default=250,
        help="Silence gap between chunk wav files when merging chapter wav.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Start chapter index (1-based, from folder prefix).",
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
        help="Limit parts per chapter for quick test. 0 means all.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing wav files.",
    )
    parser.add_argument(
        "--hf-endpoint",
        default="",
        help="Optional HuggingFace endpoint mirror, e.g. https://hf-mirror.com",
    )
    parser.add_argument(
        "--list-speakers",
        action="store_true",
        help="List available speakers for --language and exit.",
    )
    return parser.parse_args()


def chapter_index_from_name(name: str, fallback: int) -> int:
    m = re.match(r"^(\d+)_", name)
    return int(m.group(1)) if m else fallback


def duration_seconds(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return float(frames) / float(rate)


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


def main() -> None:
    args = parse_args()
    from melo.api import TTS

    if args.hf_endpoint:
        os.environ["HF_ENDPOINT"] = args.hf_endpoint

    book_dir = Path(args.book_dir)
    chunks_root = Path(args.chunks_root) if args.chunks_root else (book_dir / "tts_chunks")
    output_root = Path(args.output_root) if args.output_root else (book_dir / "melo_wav")
    manifest_file = (
        Path(args.manifest_file) if args.manifest_file else (book_dir / "melo_manifest.csv")
    )

    if not chunks_root.exists():
        raise RuntimeError(f"Chunk root not found: {chunks_root}")

    output_root.mkdir(parents=True, exist_ok=True)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)

    model = TTS(language=args.language, device=args.device)
    speaker_ids = model.hps.data.spk2id
    if args.list_speakers:
        print(f"Language: {args.language}")
        print("Available speakers:")
        for key in speaker_ids.keys():
            print(f"  - {key}")
        return

    if args.speaker not in speaker_ids:
        raise RuntimeError(
            f"Speaker '{args.speaker}' not in available speakers: {list(speaker_ids.keys())}"
        )
    speaker_id = speaker_ids[args.speaker]

    chapter_dirs = sorted([p for p in chunks_root.iterdir() if p.is_dir()])
    selected: list[Path] = []
    for i, d in enumerate(chapter_dirs, start=1):
        idx = chapter_index_from_name(d.name, i)
        if idx < args.start:
            continue
        if args.end > 0 and idx > args.end:
            continue
        selected.append(d)

    if not selected:
        raise RuntimeError("No chapter directories selected.")

    rows: list[dict[str, str]] = []
    total_parts = 0
    total_secs = 0.0

    for i, chapter_dir in enumerate(selected, start=1):
        part_files = sorted(chapter_dir.glob("part_*.txt"))
        if args.max_parts > 0:
            part_files = part_files[: args.max_parts]
        if not part_files:
            continue

        out_chapter_dir = output_root / chapter_dir.name
        out_chapter_dir.mkdir(parents=True, exist_ok=True)

        part_wavs: list[Path] = []
        chapter_part_secs = 0.0
        for part_txt in part_files:
            out_wav = out_chapter_dir / f"{part_txt.stem}.wav"
            if args.overwrite or not out_wav.exists():
                text = part_txt.read_text(encoding="utf-8", errors="ignore").strip()
                if not text:
                    continue
                model.tts_to_file(text, speaker_id, str(out_wav), speed=args.speed)
            if out_wav.exists():
                part_wavs.append(out_wav)
                chapter_part_secs += duration_seconds(out_wav)

        if not part_wavs:
            continue

        chapter_wav = out_chapter_dir / "chapter.wav"
        chapter_total_secs = merge_wavs(part_wavs, chapter_wav, args.gap_ms)

        idx = chapter_index_from_name(chapter_dir.name, i)
        rows.append(
            {
                "index": str(idx),
                "chapter_dir": chapter_dir.name,
                "parts": str(len(part_wavs)),
                "part_audio_seconds": f"{chapter_part_secs:.3f}",
                "chapter_audio_seconds": f"{chapter_total_secs:.3f}",
                "chapter_wav": str(chapter_wav.relative_to(output_root)),
            }
        )
        total_parts += len(part_wavs)
        total_secs += chapter_total_secs
        print(
            f"[{i}/{len(selected)}] parts={len(part_wavs):>3} "
            f"secs={chapter_total_secs:>7.2f} {chapter_dir.name}"
        )

    with manifest_file.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "index",
                "chapter_dir",
                "parts",
                "part_audio_seconds",
                "chapter_audio_seconds",
                "chapter_wav",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\nDone.")
    print(f"Chunks root   : {chunks_root.resolve()}")
    print(f"Output root   : {output_root.resolve()}")
    print(f"Manifest      : {manifest_file.resolve()}")
    print(f"Chapters done : {len(rows)}")
    print(f"Parts done    : {total_parts}")
    print(f"Total seconds : {total_secs:.2f}")


if __name__ == "__main__":
    main()
