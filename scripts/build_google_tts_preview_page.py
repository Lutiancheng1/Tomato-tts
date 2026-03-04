#!/usr/bin/env python3
"""
Build an interactive local preview page for Google TTS voice samples.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build preview.html from manifest_with_gender.csv"
    )
    parser.add_argument(
        "--manifest",
        default=(
            "wodebooks_output/google_tts_voice_previews_20260304_fixed/"
            "manifest_with_gender.csv"
        ),
        help="Input manifest_with_gender.csv path",
    )
    parser.add_argument(
        "--output",
        default="wodebooks_output/google_tts_voice_previews_20260304_fixed/preview.html",
        help="Output HTML path",
    )
    return parser.parse_args()


def read_manifest(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for raw in reader:
            preview_file = (raw.get("preview_file") or "").strip()
            if not preview_file:
                continue
            exists = (raw.get("exists") or "True").strip().lower() == "true"
            if not exists:
                continue
            try:
                index = int((raw.get("index") or "").strip())
            except ValueError:
                continue

            rows.append(
                {
                    "index": index,
                    "voice_name": (raw.get("voice_name") or "").strip(),
                    "language_code": (raw.get("language_code") or "").strip(),
                    "gender": (raw.get("gender") or "UNKNOWN").strip().upper(),
                    "sample_rate_hz": int((raw.get("sample_rate_hz") or "0").strip() or 0),
                    "preview_file": preview_file,
                }
            )
    rows.sort(key=lambda x: int(x["index"]))
    return rows


def render_html(voices: list[dict[str, object]]) -> str:
    voices_json = json.dumps(voices, ensure_ascii=False)
    template = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Google TTS Voice Preview</title>
  <style>
    :root {
      --bg: #f2eee7;
      --panel: #fffdf9;
      --ink: #1f2a2e;
      --muted: #667076;
      --line: #e4dacd;
      --brand: #0f6f66;
      --brand-2: #0c5a53;
      --warm: #c0603f;
      --focus: rgba(15, 111, 102, 0.16);
      --shadow: 0 14px 36px rgba(20, 30, 32, 0.08);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      color: var(--ink);
      font-family: "PingFang SC", "Noto Sans SC", "Microsoft YaHei", "Source Han Sans SC", sans-serif;
      background:
        radial-gradient(1200px 520px at 8% -10%, #f9f4e9 0%, transparent 68%),
        radial-gradient(820px 360px at 100% 0%, #ebe2d3 0%, transparent 66%),
        var(--bg);
      min-height: 100vh;
    }

    .app {
      max-width: 1260px;
      margin: 26px auto;
      padding: 0 18px;
    }

    .head {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 12px;
      margin-bottom: 14px;
    }

    .title {
      margin: 0;
      font-size: 29px;
      font-weight: 720;
      letter-spacing: 0.2px;
    }

    .sub {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 14px;
    }

    .count {
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      padding: 7px 12px;
      font-size: 12px;
      color: #4e5961;
      white-space: nowrap;
    }

    .layout {
      display: grid;
      grid-template-columns: 1.02fr 1fr;
      gap: 14px;
      min-height: 74vh;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .toolbar {
      display: grid;
      gap: 10px;
      padding: 14px;
      border-bottom: 1px solid var(--line);
      background: #fffaf2;
    }

    .tabs {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .chip {
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 999px;
      padding: 8px 14px;
      color: #314046;
      font-size: 13px;
      cursor: pointer;
      transition: all .18s ease;
    }

    .chip.active {
      background: var(--brand);
      border-color: var(--brand);
      color: #fff;
    }

    .search {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 14px;
      background: #fff;
      outline: none;
    }

    .search:focus {
      border-color: #72a99f;
      box-shadow: 0 0 0 3px var(--focus);
    }

    .list {
      max-height: calc(74vh - 130px);
      overflow: auto;
      padding: 8px;
      scrollbar-width: thin;
    }

    .item {
      border: 1px solid transparent;
      border-radius: 12px;
      padding: 12px;
      margin-bottom: 8px;
      background: #fff;
      cursor: pointer;
      transition: all .16s ease;
    }

    .item:hover {
      border-color: #d4c7b7;
      transform: translateY(-1px);
    }

    .item.active {
      border-color: var(--brand);
      box-shadow: inset 0 0 0 1px var(--brand);
      background: #f4fcfa;
    }

    .name {
      font-size: 14px;
      font-weight: 650;
      line-height: 1.35;
      word-break: break-all;
      margin-bottom: 7px;
    }

    .meta {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      color: #61717a;
      font-size: 12px;
    }

    .tag {
      border: 1px solid #dccfbf;
      border-radius: 999px;
      padding: 2px 8px;
      background: #fff9f0;
    }

    .detail {
      padding: 16px;
      display: grid;
      gap: 14px;
      align-content: start;
    }

    .gender-badge {
      display: inline-flex;
      align-items: center;
      padding: 5px 10px;
      border: 1px solid #d2e5e2;
      border-radius: 999px;
      color: #0d4f49;
      background: #ecf7f5;
      font-size: 12px;
      width: fit-content;
    }

    .voice-title {
      margin: 4px 0 0;
      font-size: 22px;
      line-height: 1.35;
      word-break: break-all;
    }

    .desc {
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }

    .kv {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      background: #fff;
    }

    .k {
      color: #6d777d;
      font-size: 12px;
      margin-bottom: 4px;
    }

    .v {
      font-size: 14px;
      font-weight: 650;
      line-height: 1.35;
      word-break: break-all;
    }

    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    .btn {
      border: 0;
      border-radius: 10px;
      padding: 10px 16px;
      font-size: 14px;
      font-weight: 650;
      cursor: pointer;
      transition: transform .16s ease, opacity .16s ease;
    }

    .btn:hover { transform: translateY(-1px); }
    .btn:active { transform: translateY(0); }

    .btn.primary { color: #fff; background: var(--brand); }
    .btn.secondary { color: #403a34; background: #eee5d8; }
    .btn.warm { color: #fff; background: var(--warm); }

    audio { width: 100%; }

    .empty {
      padding: 20px;
      color: #65727a;
      text-align: center;
      font-size: 14px;
    }

    @media (max-width: 980px) {
      .layout { grid-template-columns: 1fr; min-height: auto; }
      .list { max-height: 44vh; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="head">
      <div>
        <h1 class="title" id="title"></h1>
        <p class="sub" id="subtitle"></p>
      </div>
      <div class="count" id="countInfo"></div>
    </header>

    <div class="layout">
      <section class="panel">
        <div class="toolbar">
          <div class="tabs">
            <button class="chip active" data-filter="ALL" id="tabAll"></button>
            <button class="chip" data-filter="MALE" id="tabMale"></button>
            <button class="chip" data-filter="FEMALE" id="tabFemale"></button>
          </div>
          <input id="search" class="search" />
        </div>
        <div id="voiceList" class="list"></div>
      </section>

      <section class="panel detail">
        <span class="gender-badge" id="genderBadge"></span>
        <h2 class="voice-title" id="voiceName"></h2>
        <p class="desc" id="tip"></p>

        <div class="grid">
          <div class="kv"><div class="k" id="kLang"></div><div class="v" id="vLang">-</div></div>
          <div class="kv"><div class="k" id="kGender"></div><div class="v" id="vGender">-</div></div>
          <div class="kv"><div class="k" id="kRate"></div><div class="v" id="vRate">-</div></div>
          <div class="kv"><div class="k" id="kFile"></div><div class="v" id="vFile">-</div></div>
        </div>

        <div class="actions">
          <button class="btn primary" id="btnPlay"></button>
          <button class="btn secondary" id="btnStop"></button>
          <button class="btn warm" id="btnOpen"></button>
        </div>

        <audio id="audio" controls preload="none"></audio>
      </section>
    </div>
  </div>

  <script>
    const UI = {
      title: "\\u8bed\\u97f3\\u8bd5\\u542c\\u9762\\u677f",
      subtitle: "\\u5de6\\u4fa7\\u9009\\u62e9\\u97f3\\u8272\\uff0c\\u53f3\\u4fa7\\u70b9\\u51fb\\u64ad\\u653e\\u5373\\u53ef\\u8bd5\\u542c\\u3002\\u53ef\\u53cc\\u51fb\\u6761\\u76ee\\u76f4\\u63a5\\u64ad\\u653e\\u3002",
      all: "\\u5168\\u90e8",
      male: "\\u7537\\u58f0",
      female: "\\u5973\\u58f0",
      search: "\\u641c\\u7d22\\u97f3\\u8272\\u540d\\u6216\\u8bed\\u8a00\\u4ee3\\u7801\\uff08\\u4f8b\\uff1AAchernar / cmn-CN\\uff09",
      count: "\\u663e\\u793a {shown} / {total}",
      empty: "\\u5f53\\u524d\\u7b5b\\u9009\\u6761\\u4ef6\\u4e0b\\u6ca1\\u6709\\u7ed3\\u679c",
      pick: "\\u8bf7\\u5728\\u5de6\\u4fa7\\u9009\\u62e9\\u4e00\\u4e2a\\u97f3\\u8272",
      tip: "\\u8bd5\\u542c\\u6309\\u94ae\\u652f\\u6301\\u76f4\\u63a5\\u64ad\\u653e\\u4e0e\\u6253\\u5f00 MP3 \\u6587\\u4ef6",
      play: "\\u64ad\\u653e",
      stop: "\\u505c\\u6b62",
      open: "\\u6253\\u5f00 MP3",
      lang: "\\u8bed\\u8a00",
      gender: "\\u6027\\u522b",
      rate: "\\u91c7\\u6837\\u7387",
      file: "\\u6587\\u4ef6",
      maleTag: "\\u7537\\u58f0",
      femaleTag: "\\u5973\\u58f0",
      neutralTag: "\\u4e2d\\u6027",
      unknownTag: "\\u672a\\u77e5"
    };

    const VOICES = __VOICES_JSON__;

    const state = {
      filter: "ALL",
      query: "",
      shown: [],
      selectedId: null
    };

    const titleEl = document.getElementById("title");
    const subtitleEl = document.getElementById("subtitle");
    const countInfoEl = document.getElementById("countInfo");

    const tabAllEl = document.getElementById("tabAll");
    const tabMaleEl = document.getElementById("tabMale");
    const tabFemaleEl = document.getElementById("tabFemale");
    const searchEl = document.getElementById("search");
    const listEl = document.getElementById("voiceList");

    const genderBadgeEl = document.getElementById("genderBadge");
    const voiceNameEl = document.getElementById("voiceName");
    const tipEl = document.getElementById("tip");

    const kLangEl = document.getElementById("kLang");
    const kGenderEl = document.getElementById("kGender");
    const kRateEl = document.getElementById("kRate");
    const kFileEl = document.getElementById("kFile");

    const vLangEl = document.getElementById("vLang");
    const vGenderEl = document.getElementById("vGender");
    const vRateEl = document.getElementById("vRate");
    const vFileEl = document.getElementById("vFile");

    const audioEl = document.getElementById("audio");
    const btnPlayEl = document.getElementById("btnPlay");
    const btnStopEl = document.getElementById("btnStop");
    const btnOpenEl = document.getElementById("btnOpen");

    function genderText(gender) {
      if (gender === "MALE") return UI.maleTag;
      if (gender === "FEMALE") return UI.femaleTag;
      if (gender === "NEUTRAL") return UI.neutralTag;
      return UI.unknownTag;
    }

    function matchVoice(voice) {
      if (state.filter !== "ALL" && voice.gender !== state.filter) return false;
      const q = state.query.trim().toLowerCase();
      if (!q) return true;
      return (
        String(voice.index).includes(q) ||
        voice.voice_name.toLowerCase().includes(q) ||
        voice.language_code.toLowerCase().includes(q) ||
        voice.preview_file.toLowerCase().includes(q)
      );
    }

    function getSelectedVoice() {
      if (state.selectedId == null) return null;
      return VOICES.find(v => v.index === state.selectedId) || null;
    }

    function setSelectedVoice(voice, autoplay) {
      if (!voice) return;
      state.selectedId = voice.index;
      renderList();
      updateDetail();
      if (autoplay) {
        audioEl.play().catch(() => {});
      }
    }

    function updateDetail() {
      const voice = getSelectedVoice();
      if (!voice) {
        genderBadgeEl.textContent = UI.pick;
        voiceNameEl.textContent = "-";
        vLangEl.textContent = "-";
        vGenderEl.textContent = "-";
        vRateEl.textContent = "-";
        vFileEl.textContent = "-";
        audioEl.removeAttribute("src");
        audioEl.load();
        return;
      }

      const gText = genderText(voice.gender);
      genderBadgeEl.textContent = gText + " / " + voice.language_code;
      voiceNameEl.textContent = voice.voice_name;
      vLangEl.textContent = voice.language_code;
      vGenderEl.textContent = gText;
      vRateEl.textContent = String(voice.sample_rate_hz) + " Hz";
      vFileEl.textContent = voice.preview_file;
      audioEl.src = encodeURI(voice.preview_file);
    }

    function renderList() {
      state.shown = VOICES.filter(matchVoice);
      countInfoEl.textContent = UI.count
        .replace("{shown}", String(state.shown.length))
        .replace("{total}", String(VOICES.length));

      if (state.shown.length === 0) {
        listEl.innerHTML = '<div class="empty">' + UI.empty + "</div>";
        return;
      }

      if (!state.shown.some(v => v.index === state.selectedId)) {
        state.selectedId = state.shown[0].index;
      }

      const html = state.shown.map((voice) => {
        const active = voice.index === state.selectedId ? " active" : "";
        return (
          '<article class="item' + active + '" data-index="' + voice.index + '">' +
            '<div class="name">' + voice.voice_name + "</div>" +
            '<div class="meta">' +
              '<span class="tag">#' + voice.index + "</span>" +
              '<span class="tag">' + voice.language_code + "</span>" +
              '<span class="tag">' + genderText(voice.gender) + "</span>" +
            "</div>" +
          "</article>"
        );
      }).join("");
      listEl.innerHTML = html;

      const items = listEl.querySelectorAll(".item");
      items.forEach((el) => {
        el.addEventListener("click", () => {
          const id = Number(el.getAttribute("data-index"));
          const picked = state.shown.find(v => v.index === id);
          setSelectedVoice(picked, false);
        });
        el.addEventListener("dblclick", () => {
          const id = Number(el.getAttribute("data-index"));
          const picked = state.shown.find(v => v.index === id);
          setSelectedVoice(picked, true);
        });
      });
    }

    function setFilter(filter) {
      state.filter = filter;
      [tabAllEl, tabMaleEl, tabFemaleEl].forEach((el) => {
        if (el.getAttribute("data-filter") === filter) {
          el.classList.add("active");
        } else {
          el.classList.remove("active");
        }
      });
      renderList();
      updateDetail();
    }

    titleEl.textContent = UI.title;
    subtitleEl.textContent = UI.subtitle;
    tabAllEl.textContent = UI.all;
    tabMaleEl.textContent = UI.male;
    tabFemaleEl.textContent = UI.female;
    searchEl.placeholder = UI.search;
    tipEl.textContent = UI.tip;
    kLangEl.textContent = UI.lang;
    kGenderEl.textContent = UI.gender;
    kRateEl.textContent = UI.rate;
    kFileEl.textContent = UI.file;
    btnPlayEl.textContent = UI.play;
    btnStopEl.textContent = UI.stop;
    btnOpenEl.textContent = UI.open;

    tabAllEl.addEventListener("click", () => setFilter("ALL"));
    tabMaleEl.addEventListener("click", () => setFilter("MALE"));
    tabFemaleEl.addEventListener("click", () => setFilter("FEMALE"));

    searchEl.addEventListener("input", () => {
      state.query = searchEl.value || "";
      renderList();
      updateDetail();
    });

    btnPlayEl.addEventListener("click", () => {
      const voice = getSelectedVoice();
      if (!voice && state.shown.length) {
        setSelectedVoice(state.shown[0], false);
      }
      if (audioEl.src) {
        audioEl.play().catch(() => {});
      }
    });

    btnStopEl.addEventListener("click", () => {
      audioEl.pause();
      audioEl.currentTime = 0;
    });

    btnOpenEl.addEventListener("click", () => {
      const voice = getSelectedVoice();
      if (!voice) return;
      window.open(encodeURI(voice.preview_file), "_blank");
    });

    renderList();
    updateDetail();
  </script>
</body>
</html>
"""
    return template.replace("__VOICES_JSON__", voices_json)


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest)
    output_path = Path(args.output)

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    voices = read_manifest(manifest_path)
    if not voices:
        raise RuntimeError("No voice rows found in manifest.")

    html_text = render_html(voices)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8", newline="\n")

    print(f"Voices : {len(voices)}")
    print(f"Input  : {manifest_path.resolve()}")
    print(f"Output : {output_path.resolve()}")


if __name__ == "__main__":
    main()
