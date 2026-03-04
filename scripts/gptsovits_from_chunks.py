#!/usr/bin/env python3
"""
Batch synthesize TTS audio from tts_chunks using local GPT-SoVITS inference.

Input layout:
  tts_chunks/
    001_xxx/
      part_001.txt
      part_002.txt
      ...

Output layout:
  gptsovits_wav/
    001_xxx/
      part_001.wav
      part_002.wav
      chapter.wav
    ...
  gptsovits_manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import warnings
import wave
from pathlib import Path
from typing import Any

import soundfile as sf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthesize wav files from tts_chunks with GPT-SoVITS."
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
        help="Output root directory. Default: <book-dir>/gptsovits_wav",
    )
    parser.add_argument(
        "--manifest-file",
        default="",
        help="Manifest CSV file. Default: <book-dir>/gptsovits_manifest.csv",
    )
    parser.add_argument(
        "--gsv-root",
        default="third_party/GPT-SoVITS",
        help="GPT-SoVITS repository root path.",
    )
    parser.add_argument(
        "--config",
        default="GPT_SoVITS/configs/tts_infer.yaml",
        help="GPT-SoVITS inference yaml (absolute or relative to --gsv-root).",
    )
    parser.add_argument(
        "--ref-audio",
        required=True,
        help="Reference audio wav path (best 3~10s).",
    )
    parser.add_argument(
        "--prompt-text",
        default="",
        help="Prompt text matching reference audio. If empty, use --prompt-text-file or no prompt text.",
    )
    parser.add_argument(
        "--prompt-text-file",
        default="",
        help="Path to prompt text file. Ignored if --prompt-text is set.",
    )
    parser.add_argument(
        "--text-lang",
        default="zh",
        help="Target text language code. Usually zh/en/ja/yue/ko.",
    )
    parser.add_argument(
        "--prompt-lang",
        default="zh",
        help="Prompt text language code.",
    )
    parser.add_argument(
        "--split-method",
        default="cut5",
        help="Text split method for GPT-SoVITS.",
    )
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cuda", "cpu"],
        help="Device override for GPT-SoVITS config.",
    )
    parser.add_argument(
        "--half",
        default="auto",
        choices=["auto", "true", "false"],
        help="Half precision override for GPT-SoVITS config.",
    )
    parser.add_argument(
        "--disable-g2pw",
        action="store_true",
        help="Set env is_g2pw=False (more compatible, less polyphone accuracy).",
    )
    parser.add_argument(
        "--parallel-infer",
        action="store_true",
        help="Enable GPT-SoVITS internal parallel inference.",
    )
    parser.add_argument(
        "--split-bucket",
        action="store_true",
        help="Enable GPT-SoVITS split_bucket.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Batch size for GPT-SoVITS inference request.",
    )
    parser.add_argument(
        "--batch-threshold",
        type=float,
        default=0.75,
        help="Batch threshold for GPT-SoVITS inference request.",
    )
    parser.add_argument(
        "--speed-factor",
        type=float,
        default=1.0,
        help="Speech speed factor.",
    )
    parser.add_argument(
        "--fragment-interval",
        type=float,
        default=0.3,
        help="Pause between fragments (seconds).",
    )
    parser.add_argument(
        "--repetition-penalty",
        type=float,
        default=1.35,
        help="Repetition penalty.",
    )
    parser.add_argument(
        "--sample-steps",
        type=int,
        default=32,
        help="Sampling steps for v3/v4; harmless for v2.",
    )
    parser.add_argument(
        "--super-sampling",
        action="store_true",
        help="Enable super sampling.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed. -1 means random by model.",
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
        help="Overwrite existing wav files.",
    )
    parser.add_argument(
        "--fallback-cpu-on-oom",
        action="store_true",
        help="If CUDA OOM happens for a part, retry that part on CPU.",
    )
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="Skip failed parts and continue.",
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


def build_prompt_text(args: argparse.Namespace) -> str:
    if args.prompt_text.strip():
        return args.prompt_text.strip()
    if args.prompt_text_file:
        return Path(args.prompt_text_file).read_text(encoding="utf-8", errors="ignore").strip()
    return ""


def to_config_path(gsv_root: Path, raw: str) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else (gsv_root / p)


def make_request(
    text: str,
    ref_audio: Path,
    prompt_text: str,
    args: argparse.Namespace,
    seed: int,
) -> dict[str, Any]:
    return {
        "text": text,
        "text_lang": args.text_lang,
        "ref_audio_path": str(ref_audio),
        "prompt_text": prompt_text,
        "prompt_lang": args.prompt_lang,
        "text_split_method": args.split_method,
        "batch_size": args.batch_size,
        "batch_threshold": args.batch_threshold,
        "split_bucket": args.split_bucket,
        "speed_factor": args.speed_factor,
        "fragment_interval": args.fragment_interval,
        "seed": seed,
        "media_type": "wav",
        "streaming_mode": False,
        "parallel_infer": args.parallel_infer,
        "repetition_penalty": args.repetition_penalty,
        "sample_steps": args.sample_steps,
        "super_sampling": args.super_sampling,
    }


def main() -> None:
    args = parse_args()

    # Keep logs readable when requests/chardet versions differ.
    warnings.filterwarnings("ignore", message="urllib3 .* doesn't match a supported version")

    book_dir = Path(args.book_dir).resolve()
    chunks_root = Path(args.chunks_root).resolve() if args.chunks_root else (book_dir / "tts_chunks")
    output_root = Path(args.output_root).resolve() if args.output_root else (book_dir / "gptsovits_wav")
    manifest_file = (
        Path(args.manifest_file).resolve()
        if args.manifest_file
        else (book_dir / "gptsovits_manifest.csv")
    )
    gsv_root = Path(args.gsv_root).resolve()
    config_path = to_config_path(gsv_root, args.config).resolve()
    ref_audio = Path(args.ref_audio).resolve()

    if not chunks_root.exists():
        raise RuntimeError(f"Chunk root not found: {chunks_root}")
    if not gsv_root.exists():
        raise RuntimeError(f"GPT-SoVITS root not found: {gsv_root}")
    if not config_path.exists():
        raise RuntimeError(f"Config yaml not found: {config_path}")
    if not ref_audio.exists():
        raise RuntimeError(f"Reference audio not found: {ref_audio}")

    output_root.mkdir(parents=True, exist_ok=True)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)

    prompt_text = build_prompt_text(args)
    if args.disable_g2pw:
        os.environ["is_g2pw"] = "False"

    # GPT-SoVITS code depends on cwd-relative imports/paths.
    os.chdir(gsv_root)
    sys.path.insert(0, str(gsv_root))
    sys.path.insert(0, str(gsv_root / "GPT_SoVITS"))

    from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config

    cfg = TTS_Config(str(config_path))
    if args.device != "auto":
        cfg.device = args.device
    if args.half == "true":
        cfg.is_half = True
    elif args.half == "false":
        cfg.is_half = False

    tts = TTS(cfg)
    tts_cpu = None

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
        used_device = cfg.device

        for part_txt in part_files:
            out_wav = out_chapter_dir / f"{part_txt.stem}.wav"
            text = part_txt.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                continue

            if args.overwrite or not out_wav.exists():
                req = make_request(text, ref_audio, prompt_text, args, args.seed)
                try:
                    sr, audio = next(tts.run(req))
                    sf.write(out_wav, audio, sr)
                except Exception as ex:
                    can_retry_cpu = args.fallback_cpu_on_oom and "cuda" in cfg.device
                    if can_retry_cpu:
                        if tts_cpu is None:
                            cfg_cpu = TTS_Config(str(config_path))
                            cfg_cpu.device = "cpu"
                            cfg_cpu.is_half = False
                            tts_cpu = TTS(cfg_cpu)
                        sr, audio = next(tts_cpu.run(req))
                        sf.write(out_wav, audio, sr)
                        used_device = "cpu_fallback"
                        print(f"[fallback-cpu] {chapter_dir.name}/{part_txt.name}")
                    elif args.skip_errors:
                        print(f"[skip] {chapter_dir.name}/{part_txt.name}: {ex}")
                        continue
                    else:
                        raise

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
                "device": str(used_device),
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
                "device",
                "chapter_wav",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\nDone.")
    print(f"Chunks root   : {chunks_root}")
    print(f"Output root   : {output_root}")
    print(f"Manifest      : {manifest_file}")
    print(f"Chapters done : {len(rows)}")
    print(f"Parts done    : {total_parts}")
    print(f"Total seconds : {total_secs:.2f}")


if __name__ == "__main__":
    main()
