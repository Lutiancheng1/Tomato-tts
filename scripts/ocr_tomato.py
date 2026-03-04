#!/usr/bin/env python3
"""
Batch OCR long Chinese novel screenshots and clean metadata/noise lines.

Outputs:
- ocr_results/raw/*.txt
- ocr_results/clean/*.txt
- ocr_results/merged_with_markers.txt
- ocr_results/merged_for_tts.txt
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


META_PATTERNS = [
    re.compile(r"本章.{0,8}[字效].{0,24}"),
    re.compile(r"[字产学总]数[:：]?\s*\d{2,6}$"),
    re.compile(r"更新.{0,4}时间"),
    re.compile(r"^\s*\d{4}[-年/.]\d{1,2}[-月/.]\d{1,2}(日)?\s*$"),
    re.compile(r"^\s*(上|下)?一?章\s*$"),
    re.compile(r"^\s*目录\s*$"),
    re.compile(r"番茄小说"),
]

CHAPTER_PATTERN = re.compile(r"^第[0-9一二三四五六七八九十百千万两]+章")
END_PUNCT = set("。！？!?；;：:”』）】》…")
NOISE_EXACT_LINES = {"日：", "滴。", "下-", "过。"}
SHORT_KEEP_PATTERN = re.compile(r"^[他她你我它谁啥嗯啊哦哎哈][？?！!。]?$")

VISION_SWIFT_SOURCE = r"""
import Foundation
import Vision
import AppKit

if CommandLine.arguments.count < 2 {
    fputs("usage: swift vision_ocr.swift <image>\n", stderr)
    exit(1)
}

let imagePath = CommandLine.arguments[1]
let url = URL(fileURLWithPath: imagePath)

guard let nsImage = NSImage(contentsOf: url) else {
    fputs("failed to open image\n", stderr)
    exit(1)
}

var rect = NSRect(origin: .zero, size: nsImage.size)
guard let cgImage = nsImage.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
    fputs("failed to decode CGImage\n", stderr)
    exit(1)
}

var lines: [(String, CGFloat, CGFloat)] = []

let request = VNRecognizeTextRequest { request, error in
    if let error = error {
        fputs("Vision error: \(error)\n", stderr)
        return
    }
    guard let results = request.results as? [VNRecognizedTextObservation] else { return }
    for obs in results {
        guard let cand = obs.topCandidates(1).first else { continue }
        let text = cand.string.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { continue }
        lines.append((text, obs.boundingBox.minX, obs.boundingBox.maxY))
    }
}

request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.minimumTextHeight = 0.008

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    fputs("perform failed: \(error)\n", stderr)
    exit(1)
}

let sorted = lines.sorted { a, b in
    if abs(a.2 - b.2) < 0.01 {
        return a.1 < b.1
    }
    return a.2 > b.2
}
for item in sorted {
    print(item.0)
}
"""


def cjk_count(text: str) -> int:
    return sum(1 for c in text if "\u4e00" <= c <= "\u9fff")


def score_text_quality(text: str) -> float:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return -1.0
    total = len(chars)
    cjk = cjk_count("".join(chars))
    ascii_letters = sum(1 for c in chars if c.isascii() and c.isalpha())
    junk = sum(1 for c in chars if c in {"|", "\\", "_", "~", "^", "*"})
    return (cjk / total) - (0.5 * ascii_letters / total) - (0.5 * junk / total)


def run_tesseract(image: Path, psm: int) -> str:
    cmd = [
        "tesseract",
        str(image),
        "stdout",
        "-l",
        "chi_sim+eng",
        "--psm",
        str(psm),
        "--oem",
        "1",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"OCR failed for {image.name}: {stderr}")
    return proc.stdout.decode("utf-8", errors="ignore")


def write_vision_swift_script(workdir: Path) -> Path:
    script_path = workdir / "vision_ocr.swift"
    script_path.write_text(VISION_SWIFT_SOURCE, encoding="utf-8")
    return script_path


def run_vision_ocr(image: Path, swift_script: Path) -> str:
    if shutil.which("swift") is None:
        raise RuntimeError("swift not found")

    cmd = ["swift", str(swift_script), str(image)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"Vision OCR failed for {image.name}: {stderr}")
    return proc.stdout.decode("utf-8", errors="ignore")


def preprocess_image(src: Path, dst: Path) -> None:
    cmd = [
        "magick",
        str(src),
        "-colorspace",
        "Gray",
        "-resize",
        "180%",
        "-contrast-stretch",
        "1%x1%",
        "-sharpen",
        "0x1.0",
        str(dst),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def choose_best_ocr(
    image: Path,
    workdir: Path,
    with_preprocess: bool,
    engine: str,
    swift_script: Path | None,
) -> str:
    candidates: list[str] = []

    if engine in {"vision", "auto"} and swift_script is not None:
        try:
            candidates.append(run_vision_ocr(image, swift_script))
        except RuntimeError:
            if engine == "vision":
                raise

    if engine in {"tesseract", "auto"}:
        # Raw image candidates
        for psm in (6, 4):
            try:
                candidates.append(run_tesseract(image, psm))
            except RuntimeError:
                if engine == "tesseract":
                    raise

        # Optional preprocessed image candidates (slower, may help some blurry screenshots).
        if with_preprocess:
            pre = workdir / f"{image.stem}.pre.png"
            try:
                preprocess_image(image, pre)
                for psm in (6, 4):
                    try:
                        candidates.append(run_tesseract(pre, psm))
                    except RuntimeError:
                        pass
            except subprocess.CalledProcessError:
                pass

    if not candidates:
        raise RuntimeError(f"No OCR output for {image.name}")

    return max(candidates, key=score_text_quality)


def normalize_line(line: str) -> str:
    line = line.replace("\u3000", " ").strip()
    line = line.replace("系統", "系统")
    line = re.sub(r"(?i)bug", "BUG", line)
    line = line.replace(".⋯", "……").replace("⋯", "…")
    # Remove inline metadata fragments that may be glued to normal text.
    line = re.sub(r"本章.{0,8}[字效].{0,24}", "", line)
    line = re.sub(r"本章.{0,12}[字产学总]数[:：]?\s*\d{2,6}", "", line)
    line = re.sub(r"更新.{0,4}时间[:：]?\s*", "", line)
    line = re.sub(r"到期.{0,8}\d{4}[-./]\d{1,2}[-./]\d{1,2}\|?", "", line)
    line = re.sub(r"[|｜•·]?\s*\d{4}[-./年]\d{1,2}[-./月]\d{1,2}(日)?\s*[|｜]?", "", line)
    line = re.sub(r"[ \t]+", " ", line)
    return line


def looks_like_meta(line: str) -> bool:
    return any(p.search(line) for p in META_PATTERNS)


def looks_like_noise(line: str) -> bool:
    if not line:
        return True
    if line in NOISE_EXACT_LINES:
        return True
    if looks_like_meta(line):
        return True

    cjk = cjk_count(line)
    ascii_letters = sum(1 for c in line if c.isascii() and c.isalpha())
    digits = sum(1 for c in line if c.isdigit())
    symbols = sum(1 for c in line if not c.isalnum() and not ("\u4e00" <= c <= "\u9fff"))
    total = len(line)

    # Drop short non-Chinese noise lines.
    if cjk == 0 and total <= 20 and (ascii_letters > 0 or symbols > 0):
        return True
    # Drop symbol-heavy garbage lines.
    if total > 0 and symbols / total >= 0.6 and cjk <= 1:
        return True
    # Drop mixed garbage with barely any Chinese signal.
    if cjk <= 1 and ascii_letters + digits >= 4 and total <= 30:
        return True
    # Drop ultra-short broken fragments unless they are meaningful utterances like "他？".
    pure = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", line)
    if len(pure) <= 1 and not SHORT_KEEP_PATTERN.fullmatch(line):
        return True

    return False


def merge_wrapped_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for line in lines:
        if not merged:
            merged.append(line)
            continue

        prev = merged[-1]
        prev_ends = prev[-1] if prev else ""
        should_break = (
            prev_ends in END_PUNCT
            or CHAPTER_PATTERN.match(line) is not None
            or line.startswith(("“", "”", "‘", "’", "【", "（"))
        )

        if should_break:
            merged.append(line)
        else:
            merged[-1] = prev + line
    return merged


def clean_text(raw: str, merge_lines_for_paragraphs: bool) -> str:
    lines = [normalize_line(x) for x in raw.splitlines()]
    filtered = [line for line in lines if not looks_like_noise(line)]
    if merge_lines_for_paragraphs:
        filtered = merge_wrapped_lines(filtered)
    return "\n".join(filtered).strip()


def is_suspicious_line(line: str) -> bool:
    if SHORT_KEEP_PATTERN.fullmatch(line):
        return False
    line_for_ascii = re.sub(r"BUG", "", line, flags=re.IGNORECASE)
    ascii_letters = sum(1 for c in line_for_ascii if c.isascii() and c.isalpha())
    weird = any(c in {"�", "⋯", "|", "\\", "_", "~"} for c in line)
    too_short = len(line) <= 2 and cjk_count(line) <= 1
    return ascii_letters > 0 or weird or too_short


def find_images(input_dir: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    images = [p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    # Prefer mtime order, then filename to stabilize ties.
    return sorted(images, key=lambda p: (p.stat().st_mtime, p.name))


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch OCR + cleaning for tomato novel screenshots")
    parser.add_argument("--input-dir", default=".", help="Directory with images")
    parser.add_argument("--output-dir", default="ocr_results", help="Output directory")
    parser.add_argument(
        "--with-preprocess",
        action="store_true",
        help="Also OCR enhanced images (slower, sometimes better for blurry shots).",
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "vision", "tesseract"],
        default="auto",
        help="OCR engine. auto=prefer vision on macOS and fallback to tesseract.",
    )
    parser.add_argument(
        "--merge-lines",
        action="store_true",
        help="Merge wrapped OCR lines into longer paragraphs (may reduce precision on noisy images).",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    raw_dir = output_dir / "raw"
    clean_dir = output_dir / "clean"
    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_dir.mkdir(parents=True, exist_ok=True)

    images = find_images(input_dir)
    if not images:
        print("No images found.")
        return 1

    merged_with_markers: list[str] = []
    merged_for_tts: list[str] = []
    review_flags: list[str] = []

    with tempfile.TemporaryDirectory(prefix="ocr_tomato_") as td:
        temp_dir = Path(td)
        swift_script = write_vision_swift_script(temp_dir) if args.engine in {"auto", "vision"} else None
        for img in images:
            raw_text = choose_best_ocr(
                img,
                temp_dir,
                with_preprocess=args.with_preprocess,
                engine=args.engine,
                swift_script=swift_script,
            )
            clean_text_value = clean_text(raw_text, merge_lines_for_paragraphs=args.merge_lines)

            raw_path = raw_dir / f"{img.stem}.txt"
            clean_path = clean_dir / f"{img.stem}.txt"
            raw_path.write_text(raw_text, encoding="utf-8")
            clean_path.write_text(clean_text_value + "\n", encoding="utf-8")

            merged_with_markers.append(f"===== {img.name} =====")
            merged_with_markers.append(clean_text_value)
            if clean_text_value:
                merged_for_tts.append(clean_text_value)
                for idx, line in enumerate(clean_text_value.splitlines(), start=1):
                    if is_suspicious_line(line):
                        review_flags.append(f"{img.name}:{idx} {line}")

    (output_dir / "merged_with_markers.txt").write_text(
        "\n\n".join(merged_with_markers).strip() + "\n",
        encoding="utf-8",
    )
    (output_dir / "merged_for_tts.txt").write_text(
        "\n\n".join(merged_for_tts).strip() + "\n",
        encoding="utf-8",
    )
    (output_dir / "review_flags.txt").write_text(
        "\n".join(review_flags).strip() + ("\n" if review_flags else ""),
        encoding="utf-8",
    )

    print(f"Done. Processed {len(images)} images.")
    print(f"Output: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
