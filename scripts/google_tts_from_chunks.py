#!/usr/bin/env python3
"""
Batch synthesize audio from tts_chunks using Google Cloud Text-to-Speech.

Input layout:
  tts_chunks/
    001_xxx/
      part_001.txt
      part_002.txt
      ...

Output layout:
  google_tts_audio/
    001_xxx/
      part_001.wav|mp3|ogg
      part_002.wav|mp3|ogg
      chapter.wav                # only for LINEAR16
    ...
  google_tts_manifest.csv
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Callable

ENCODING_TO_EXT = {
    "LINEAR16": ".wav",
    "MP3": ".mp3",
    "OGG_OPUS": ".ogg",
}

GENDER_NAMES = {
    "SSML_VOICE_GENDER_UNSPECIFIED",
    "MALE",
    "FEMALE",
    "NEUTRAL",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthesize audio files from tts_chunks with Google Cloud TTS."
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
        help="Output root directory. Default: <book-dir>/google_tts_audio",
    )
    parser.add_argument(
        "--manifest-file",
        default="",
        help="Manifest CSV file. Default: <book-dir>/google_tts_manifest.csv",
    )

    parser.add_argument(
        "--backend",
        choices=["auto", "client", "rest"],
        default="auto",
        help="Auth transport: client(ADC/service account), rest(API key), or auto.",
    )
    parser.add_argument(
        "--credentials-json",
        default="",
        help="Optional service-account JSON path. Sets GOOGLE_APPLICATION_CREDENTIALS for this run.",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Google Cloud API key. Used by --backend rest (or auto fallback).",
    )

    parser.add_argument(
        "--language-code",
        default="cmn-CN",
        help="BCP-47 language code, e.g. cmn-CN / en-US.",
    )
    parser.add_argument(
        "--voice-name",
        default="",
        help="Optional exact voice name, e.g. cmn-CN-Wavenet-A.",
    )
    parser.add_argument(
        "--ssml-gender",
        default="NEUTRAL",
        choices=sorted(GENDER_NAMES),
        help="Voice gender hint when --voice-name is empty.",
    )
    parser.add_argument(
        "--audio-encoding",
        default="LINEAR16",
        choices=sorted(ENCODING_TO_EXT.keys()),
        help="Output audio encoding.",
    )
    parser.add_argument(
        "--speaking-rate",
        type=float,
        default=1.0,
        help="Speaking rate, range usually 0.25-4.0.",
    )
    parser.add_argument(
        "--pitch",
        type=float,
        default=0.0,
        help="Pitch in semitones, range usually -20.0 to 20.0.",
    )
    parser.add_argument(
        "--volume-gain-db",
        type=float,
        default=0.0,
        help="Output gain in dB.",
    )
    parser.add_argument(
        "--sample-rate-hertz",
        type=int,
        default=0,
        help="Output sample rate. 0 means provider default.",
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
        help="Silence gap used when merging LINEAR16 parts to chapter.wav.",
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
        help="List voices for --language-code and exit.",
    )
    return parser.parse_args()


def chapter_index_from_name(name: str, fallback: int) -> int:
    match = re.match(r"^(\d+)_", name)
    return int(match.group(1)) if match else fallback


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


def pick_backend(args: argparse.Namespace, api_key: str) -> str:
    if args.backend != "auto":
        return args.backend
    return "rest" if api_key else "client"


def build_voice_object(language_code: str, voice_name: str, ssml_gender: str) -> dict[str, str]:
    voice: dict[str, str] = {"languageCode": language_code}
    if voice_name:
        voice["name"] = voice_name
    voice["ssmlGender"] = ssml_gender
    return voice


def build_audio_config(args: argparse.Namespace) -> dict[str, float | int | str]:
    cfg: dict[str, float | int | str] = {
        "audioEncoding": args.audio_encoding,
        "speakingRate": args.speaking_rate,
        "pitch": args.pitch,
        "volumeGainDb": args.volume_gain_db,
    }
    if args.sample_rate_hertz > 0:
        cfg["sampleRateHertz"] = args.sample_rate_hertz
    return cfg


def rest_list_voices(api_key: str, language_code: str, timeout_s: float) -> None:
    if not api_key:
        raise RuntimeError("--backend rest requires --api-key or GOOGLE_TTS_API_KEY.")

    query = urllib.parse.urlencode({"languageCode": language_code, "key": api_key})
    url = f"https://texttospeech.googleapis.com/v1/voices?{query}"
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    voices = data.get("voices", [])
    voices = sorted(voices, key=lambda x: x.get("name", ""))
    if not voices:
        print(f"No voices found for language: {language_code}")
        return

    print(f"Voices for {language_code} ({len(voices)}):")
    for voice in voices:
        langs = ",".join(voice.get("languageCodes", []))
        name = voice.get("name", "")
        gender = voice.get("ssmlGender", "")
        sr = voice.get("naturalSampleRateHertz", "")
        print(f"  - {name} | langs={langs} | gender={gender} | natural_hz={sr}")


def client_list_voices(language_code: str) -> None:
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    resp = client.list_voices(language_code=language_code)
    voices = sorted(resp.voices, key=lambda x: x.name)
    if not voices:
        print(f"No voices found for language: {language_code}")
        return

    gender_lookup = {
        texttospeech.SsmlVoiceGender.SSML_VOICE_GENDER_UNSPECIFIED: "SSML_VOICE_GENDER_UNSPECIFIED",
        texttospeech.SsmlVoiceGender.MALE: "MALE",
        texttospeech.SsmlVoiceGender.FEMALE: "FEMALE",
        texttospeech.SsmlVoiceGender.NEUTRAL: "NEUTRAL",
    }

    print(f"Voices for {language_code} ({len(voices)}):")
    for voice in voices:
        langs = ",".join(voice.language_codes)
        gender = gender_lookup.get(voice.ssml_gender, str(int(voice.ssml_gender)))
        print(
            f"  - {voice.name} | langs={langs} | "
            f"gender={gender} | natural_hz={voice.natural_sample_rate_hertz}"
        )


def synthesize_rest(
    text: str,
    api_key: str,
    voice: dict[str, str],
    audio_cfg: dict[str, float | int | str],
    timeout_s: float,
) -> bytes:
    if not api_key:
        raise RuntimeError("--backend rest requires --api-key or GOOGLE_TTS_API_KEY.")

    url = (
        "https://texttospeech.googleapis.com/v1/text:synthesize?"
        + urllib.parse.urlencode({"key": api_key})
    )
    body = {
        "input": {"text": text},
        "voice": voice,
        "audioConfig": audio_cfg,
    }
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    audio_b64 = data.get("audioContent")
    if not audio_b64:
        raise RuntimeError(f"Google TTS REST returned no audioContent: {data}")
    return base64.b64decode(audio_b64)


def make_client_synthesizer(
    args: argparse.Namespace,
    voice: dict[str, str],
    audio_cfg: dict[str, float | int | str],
) -> Callable[[str], bytes]:
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()

    voice_kwargs: dict[str, str | int] = {
        "language_code": voice["languageCode"],
        "ssml_gender": getattr(texttospeech.SsmlVoiceGender, voice["ssmlGender"]),
    }
    if voice.get("name"):
        voice_kwargs["name"] = voice["name"]
    voice_params = texttospeech.VoiceSelectionParams(**voice_kwargs)

    audio_kwargs: dict[str, float | int] = {
        "audio_encoding": getattr(texttospeech.AudioEncoding, str(audio_cfg["audioEncoding"])),
        "speaking_rate": float(audio_cfg["speakingRate"]),
        "pitch": float(audio_cfg["pitch"]),
        "volume_gain_db": float(audio_cfg["volumeGainDb"]),
    }
    if "sampleRateHertz" in audio_cfg:
        audio_kwargs["sample_rate_hertz"] = int(audio_cfg["sampleRateHertz"])
    audio_params = texttospeech.AudioConfig(**audio_kwargs)

    def synthesize(text: str) -> bytes:
        resp = client.synthesize_speech(
            request={
                "input": texttospeech.SynthesisInput(text=text),
                "voice": voice_params,
                "audio_config": audio_params,
            },
            timeout=args.timeout,
        )
        return resp.audio_content

    return synthesize


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

    if args.credentials_json:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(Path(args.credentials_json).resolve())

    api_key = args.api_key.strip() or os.environ.get("GOOGLE_TTS_API_KEY", "").strip()
    backend = pick_backend(args, api_key)

    book_dir = Path(args.book_dir).resolve()
    chunks_root = Path(args.chunks_root).resolve() if args.chunks_root else (book_dir / "tts_chunks")
    output_root = (
        Path(args.output_root).resolve() if args.output_root else (book_dir / "google_tts_audio")
    )
    manifest_file = (
        Path(args.manifest_file).resolve()
        if args.manifest_file
        else (book_dir / "google_tts_manifest.csv")
    )

    if not chunks_root.exists():
        raise RuntimeError(f"Chunk root not found: {chunks_root}")

    output_root.mkdir(parents=True, exist_ok=True)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)

    voice = build_voice_object(args.language_code, args.voice_name, args.ssml_gender)
    audio_cfg = build_audio_config(args)

    if args.list_voices:
        if backend == "rest":
            rest_list_voices(api_key, args.language_code, args.timeout)
        else:
            client_list_voices(args.language_code)
        return

    if backend == "rest":
        synthesize_fn = lambda text: synthesize_rest(text, api_key, voice, audio_cfg, args.timeout)
    else:
        synthesize_fn = make_client_synthesizer(args, voice, audio_cfg)

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

    audio_ext = ENCODING_TO_EXT[args.audio_encoding]
    can_merge_wav = args.audio_encoding == "LINEAR16"

    rows: list[dict[str, str]] = []
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
                "backend": backend,
                "voice_name": args.voice_name,
                "language_code": args.language_code,
                "audio_encoding": args.audio_encoding,
                "chapter_audio_seconds": chapter_audio_seconds,
                "chapter_audio_file": chapter_audio_file,
                "output_subdir": str(out_chapter_dir.relative_to(output_root)),
            }
        )

        total_parts += len(produced_parts)
        total_chars += chapter_chars
        print(
            f"[{i}/{len(selected)}] parts={len(produced_parts):>3} "
            f"chars={chapter_chars:>5} {chapter_dir.name}"
        )

    with manifest_file.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "index",
                "chapter_dir",
                "parts",
                "chars",
                "backend",
                "voice_name",
                "language_code",
                "audio_encoding",
                "chapter_audio_seconds",
                "chapter_audio_file",
                "output_subdir",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\nDone.")
    print(f"Backend       : {backend}")
    print(f"Chunks root   : {chunks_root}")
    print(f"Output root   : {output_root}")
    print(f"Manifest      : {manifest_file}")
    print(f"Chapters done : {len(rows)}")
    print(f"Parts done    : {total_parts}")
    print(f"Chars done    : {total_chars}")
    if can_merge_wav:
        print(f"Total seconds : {total_secs:.2f}")


if __name__ == "__main__":
    main()
