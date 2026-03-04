# Tomato-tts

将番茄小说长截图批量 OCR 成文本，并清洗为可直接用于 TTS 配音的输入稿。

## 目前实现

- 支持批量识别 `png/jpg/jpeg/webp/bmp`。
- 支持 OCR 引擎：
  - `vision`（macOS Vision，中文长图效果更好）
  - `tesseract`
  - `auto`（优先 Vision，失败回退 Tesseract）
- 自动过滤常见噪声：
  - `本章字数/更新时间/日期` 等元信息
  - `下一章/目录` 等 UI 文案
  - 常见短碎片噪声（如 `日：`、`滴。`、`下-`、`过。`）
- 自动规范化部分文本：
  - `系統` -> `系统`
  - `bug` -> `BUG`
  - `还真是.⋯` -> `还真是……`
- 生成多份输出：
  - 原始识别文本
  - 清洗文本
  - 合并后的 TTS 输入文本
  - 可疑行复核清单

## 目录结构

```text
.
├── scripts/
│   └── ocr_tomato.py
├── ocr_results_vision/
│   ├── raw/
│   ├── clean/
│   ├── merged_for_tts.txt
│   ├── merged_with_markers.txt
│   └── review_flags.txt
└── *.png
```

## 环境准备

建议 macOS（可直接使用 Vision OCR）：

```bash
brew install tesseract tesseract-lang imagemagick
```

> `vision` 引擎依赖系统自带 `swift + Vision + AppKit`。  
> `tesseract` 引擎跨平台可用。

## 用法

在项目根目录执行：

```bash
python3 scripts/ocr_tomato.py --engine vision --output-dir ocr_results_vision
```

常用参数：

- `--engine {auto,vision,tesseract}`：选择 OCR 引擎
- `--with-preprocess`：Tesseract 增强预处理（更慢）
- `--merge-lines`：将换行合并为长段（噪声图像时可能降低精度）
- `--input-dir`：输入目录
- `--output-dir`：输出目录

查看帮助：

```bash
python3 scripts/ocr_tomato.py --help
```

## 输出说明

- `raw/*.txt`：OCR 原始文本
- `clean/*.txt`：清洗后的逐图文本
- `merged_for_tts.txt`：可直接喂给 TTS 的合并文本
- `merged_with_markers.txt`：带图片分隔标记的合并文本
- `review_flags.txt`：建议人工复核的可疑行

## 推荐 TTS（选型建议）

- 中文落地优先：腾讯云 TTS / 火山引擎 / 阿里云智能语音
- 情感表现优先：ElevenLabs
- API 工程集成优先：OpenAI TTS / Azure Speech / Google Cloud TTS

详细说明见 `docs/IMPLEMENTATION_LOG.md`。
