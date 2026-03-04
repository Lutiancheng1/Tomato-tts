# 项目目录说明（清晰版）

更新时间：2026-03-05

这份文档用于回答三件事：

1. 每个目录是干什么的
2. 哪些应该提交到 Git
3. 换设备后如何继续跑

---

## 1) 当前主流程（你现在在用的）

主流程是：`文本 -> tts_chunks -> Azure TTS -> 进度追踪`

关键目录（以本书为例）：

- `wodebooks_output/book_94814546_full_20260304/chapters/`
  - 抓取后的原始分章文本
- `wodebooks_output/book_94814546_full_20260304/tts_chapters/`
  - 清洗后的按章文本（适合直接喂 TTS）
- `wodebooks_output/book_94814546_full_20260304/tts_chunks/`
  - 切块文本（`part_*.txt`）
- `wodebooks_output/book_94814546_full_20260304/azure_tts_audio/`
  - Azure 正式音频产物（分章目录，含 `part_*.wav` 和 `chapter.wav`）
- `wodebooks_output/book_94814546_full_20260304/azure_tts_manifest.csv`
  - Azure 章节生成清单
- `wodebooks_output/book_94814546_full_20260304/azure_tts_progress.csv`
  - Azure 全书进度（`DONE/PARTIAL/TODO`）

主脚本：

- `scripts/azure_tts_from_chunks.py`

---

## 2) 目录分类（是否提交 Git）

### A. 应该提交（跨设备继续生产必需）

- `scripts/azure_tts_from_chunks.py`
- `README.md`
- `docs/DIRECTORY_LAYOUT.md`
- `wodebooks_output/book_94814546_full_20260304/azure_tts_audio/**`
- `wodebooks_output/book_94814546_full_20260304/azure_tts_manifest.csv`
- `wodebooks_output/book_94814546_full_20260304/azure_tts_progress.csv`

### B. 可选提交（测试用途）

- `wodebooks_output/book_94814546_full_20260304/azure_tts_audio_test/**`
- `wodebooks_output/book_94814546_full_20260304/azure_tts_manifest_test.csv`

### C. 不应提交（本地环境 / 缓存 / 密钥）

- `.venv_google310/`
- `.venv_melo310/`
- `.venv_gsv310/`
- `.cache/`
- `huggingface/`
- `third_party/`
- `google-credentials/`
- `*.sa-key.json`
- `secrets/google/`

### D. 本地模型目录（你问的重点）

- `voice_assets/piper/voices/`
  - 这是本地下载的 Piper 模型目录
  - 不是只给 Windows，用于本地运行 Piper，Linux/macOS 也可用
  - 体积大、可再下载，应该保持 **不提交 Git**

- `voice_assets/piper/voices.json`
  - 这是索引清单（小文件），可以提交

---

## 3) 现在项目里那些“看起来很乱”的目录怎么理解

以下多为历史方案或测试产物，不是你当前 Azure 主流程必须依赖：

- `google_tts_audio/`
- `google_tts_audio_test_client/`
- `google_tts_audio_test_rest/`
- `melo_wav*`
- `gptsovits_wav*`
- `gptsovits_ref_6s.wav`

建议：

1. 日常只关注 `azure_tts_*`、`chapters/`、`tts_chapters/`、`tts_chunks/`。
2. 历史测试目录可以先保留，不影响主流程。
3. 后续若要瘦身，再按“测试目录清理清单”统一清理。

---

## 4) 换设备后最短续跑步骤

1. `git pull`
2. 配置 Azure 环境变量：`AZURE_TTS_KEY`、`AZURE_TTS_REGION`
3. 打开 `azure_tts_progress.csv` 看 `TODO` 章节
4. 按范围续跑：

```powershell
python scripts/azure_tts_from_chunks.py `
  --book-dir wodebooks_output/book_94814546_full_20260304 `
  --start <起始章节> --end <结束章节> `
  --output-root wodebooks_output/book_94814546_full_20260304/azure_tts_audio `
  --manifest-file wodebooks_output/book_94814546_full_20260304/azure_tts_manifest.csv `
  --progress-file wodebooks_output/book_94814546_full_20260304/azure_tts_progress.csv `
  --locale zh-CN `
  --voice-name zh-CN-XiaochenNeural `
  --output-format riff-24khz-16bit-mono-pcm
```

---

## 5) 当前结论（直接回答你的问题）

- `voice_assets/piper/voices/`：是本地模型目录，不仅是 Windows，可跨平台本地用。
- 这个目录应该继续保持不提交 Git（当前规则也是这样）。
