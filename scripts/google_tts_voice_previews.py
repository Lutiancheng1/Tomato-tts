#!/usr/bin/env python3
"""
Generate preview MP3 files for Chinese-related Google TTS voices.

This script avoids shell encoding pitfalls by using unicode escape sequences
for default preview text.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate preview MP3 files for Chinese Google TTS voices."
    )
    parser.add_argument(
        "--output-dir",
        default="wodebooks_output/google_tts_voice_previews_20260304_fixed",
        help="Output directory for preview MP3 files and manifest.csv",
    )
    parser.add_argument(
        "--language-prefixes",
        default="cmn-,yue-,zh-",
        help="Comma-separated language code prefixes to include.",
    )
    parser.add_argument(
        "--speaking-rate",
        type=float,
        default=1.0,
        help="Speaking rate for preview files.",
    )
    parser.add_argument(
        "--pitch",
        type=float,
        default=0.0,
        help="Pitch for preview files.",
    )
    parser.add_argument(
        "--volume-gain-db",
        type=float,
        default=0.0,
        help="Volume gain (dB) for preview files.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of voices for quick tests. 0 means all.",
    )
    return parser.parse_args()


def select_preview_text(language_code: str) -> str:
    # Mandarin sample.
    mandarin = (
        "\u4f60\u597d\uff0c\u8fd9\u662f\u4e2d\u6587\u8bed\u97f3\u8bd5\u542c\u3002"
        "\u4eca\u5929\u5929\u6c14\u5f88\u597d\uff0c\u6211\u4eec\u4e00\u8d77\u53bb\u516c\u56ed\u6563\u6b65\uff0c"
        "\u7136\u540e\u559d\u4e00\u676f\u70ed\u8336\u3002"
    )
    # Cantonese sample.
    cantonese = (
        "\u4f60\u597d\uff0c\u5462\u6bb5\u4fc2\u5ee3\u6771\u8a71\u8a66\u807d\u3002"
        "\u4eca\u65e5\u5929\u6c23\u5514\u932f\uff0c\u6211\u54cb\u4e00\u9f4a\u53bb\u516c\u5712\u884c\u4e0b\uff0c"
        "\u518d\u98f2\u676f\u71b1\u8336\u3002"
    )

    if language_code.startswith("yue-"):
        return cantonese
    return mandarin


def safe_file_stem(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def main() -> None:
    args = parse_args()
    from google.cloud import texttospeech

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    prefixes = tuple(
        p.strip() for p in args.language_prefixes.split(",") if p.strip()
    )
    client = texttospeech.TextToSpeechClient()
    all_voices = client.list_voices().voices

    voices = [
        v
        for v in all_voices
        if any(code.startswith(prefixes) for code in v.language_codes)
    ]
    voices.sort(key=lambda v: v.name)
    if args.limit > 0:
        voices = voices[: args.limit]

    if not voices:
        raise RuntimeError("No voices matched the given language prefixes.")

    rows: list[dict[str, str]] = []
    for i, voice in enumerate(voices, start=1):
        lang = voice.language_codes[0] if voice.language_codes else "cmn-CN"
        text = select_preview_text(lang)
        out_name = f"{i:03d}_{safe_file_stem(voice.name)}.mp3"
        out_file = out_dir / out_name

        resp = client.synthesize_speech(
            request={
                "input": texttospeech.SynthesisInput(text=text),
                "voice": texttospeech.VoiceSelectionParams(
                    language_code=lang,
                    name=voice.name,
                    ssml_gender=voice.ssml_gender,
                ),
                "audio_config": texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.MP3,
                    speaking_rate=args.speaking_rate,
                    pitch=args.pitch,
                    volume_gain_db=args.volume_gain_db,
                ),
            },
            timeout=120,
        )
        out_file.write_bytes(resp.audio_content)

        rows.append(
            {
                "index": str(i),
                "voice_name": voice.name,
                "language_code": lang,
                "sample_rate_hz": str(voice.natural_sample_rate_hertz),
                "preview_file": out_name,
            }
        )
        print(f"[{i}/{len(voices)}] {voice.name}")

    manifest = out_dir / "manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "index",
                "voice_name",
                "language_code",
                "sample_rate_hz",
                "preview_file",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\nDone.")
    print(f"Output dir : {out_dir.resolve()}")
    print(f"Manifest   : {manifest.resolve()}")
    print(f"Voices     : {len(rows)}")


if __name__ == "__main__":
    main()
