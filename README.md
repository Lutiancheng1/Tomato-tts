# Tomato-tts

这个仓库现在只用于：从小说网站抓取章节文本（不再包含 OCR 流程）。

## 当前脚本

- `scripts/scrape_wodebooks.py`
  - 从 `wodebooks` 目录页自动收集章节
  - 自动拼接同一章的分页（如 `_2.html`）
  - 输出分章 txt、合并 txt、章节索引 csv
- `scripts/prepare_tts_chapters.py`
  - 对已抓取章节做 TTS 预处理（清洗、断句）
  - 生成“按章可直接喂 TTS”的文本
  - 同时生成按字数分块的小文件和清单 csv
- `scripts/melo_tts_from_chunks.py`
  - 读取 `tts_chunks` 并调用 MeloTTS 批量合成
  - 输出每个分块的 wav
  - 自动拼接为每章一个 `chapter.wav`
  - 输出音频清单 `melo_manifest.csv`

## 用法

在项目根目录执行：

```bash
python scripts/scrape_wodebooks.py \
  --book-url https://www.wodebooks.com/book_94814546/ \
  --output-dir wodebooks_output/book_94814546_full_20260304
```

常用参数：

- `--start`：从第几章开始（1-based）
- `--end`：抓到第几章结束（0 表示全部）
- `--delay`：请求间隔秒数（默认 `0.15`）

## TTS 预处理

在抓取完成后执行：

```bash
python scripts/prepare_tts_chapters.py \
  --book-dir wodebooks_output/book_94814546_full_20260304 \
  --chunk-max-chars 280 \
  --sentence-max-chars 60
```

输出：

- `tts_chapters/*.txt`：按章清洗后的文本（适合一章一章喂给 TTS）
- `tts_chunks/<章节>/part_*.txt`：按字数切块后的文本（适合接口长度受限时）
- `tts_manifest.csv`：每章句子数、分块数、字数统计

## 本地 MeloTTS 合成（Windows + NVIDIA）

如果你是 Windows 本地跑（如 3080），建议使用 Python 3.10 虚拟环境：

```powershell
# 安装 Python 3.10（仅首次）
winget install --id Python.Python.3.10 -e --silent --accept-package-agreements --accept-source-agreements

# 创建并激活环境
py -3.10 -m venv .venv_melo310
.\.venv_melo310\Scripts\python -m pip install -U pip

# 安装 MeloTTS
.\.venv_melo310\Scripts\python -m pip install git+https://github.com/myshell-ai/MeloTTS.git

# 下载 unidic 字典（仅首次）
.\.venv_melo310\Scripts\python -m unidic download

# 安装 CUDA 版 torch（启用 GPU）
.\.venv_melo310\Scripts\python -m pip install --upgrade torch==2.10.0+cu128 torchaudio==2.10.0+cu128 --index-url https://download.pytorch.org/whl/cu128
```

先小范围测试（第 1 章前 2 段）：

```powershell
.\.venv_melo310\Scripts\python scripts/melo_tts_from_chunks.py `
  --book-dir wodebooks_output/book_94814546_full_20260304 `
  --start 1 --end 1 --max-parts 2 `
  --output-root wodebooks_output/book_94814546_full_20260304/melo_wav_test `
  --manifest-file wodebooks_output/book_94814546_full_20260304/melo_manifest_test.csv `
  --device cuda:0 --language ZH --speaker ZH --speed 1.0 --gap-ms 250 `
  --hf-endpoint https://hf-mirror.com
```

全量跑全部章节：

```powershell
.\.venv_melo310\Scripts\python scripts/melo_tts_from_chunks.py `
  --book-dir wodebooks_output/book_94814546_full_20260304 `
  --output-root wodebooks_output/book_94814546_full_20260304/melo_wav `
  --manifest-file wodebooks_output/book_94814546_full_20260304/melo_manifest.csv `
  --device cuda:0 --language ZH --speaker ZH --speed 1.0 --gap-ms 250 `
  --hf-endpoint https://hf-mirror.com
```

查看某个语言的可选说话人：

```powershell
.\.venv_melo310\Scripts\python scripts/melo_tts_from_chunks.py `
  --language ZH --device cuda:0 --hf-endpoint https://hf-mirror.com --list-speakers
```

## 本地 GPT-SoVITS 合成（Windows + NVIDIA）

已新增脚本：`scripts/gptsovits_from_chunks.py`

- 输入：`tts_chunks/<章节>/part_*.txt`
- 输出：每段 `wav` + 每章 `chapter.wav` + `gptsovits_manifest.csv`

### 1) 环境（Python 3.10）

```powershell
py -3.10 -m venv .venv_gsv310
.\.venv_gsv310\Scripts\python -m pip install -U pip setuptools wheel

# 推荐的 GPT-SoVITS 稳定组合（Windows 本地）
.\.venv_gsv310\Scripts\python -m pip install torch==2.5.1+cu124 torchaudio==2.5.1+cu124 --index-url https://download.pytorch.org/whl/cu124

# Windows 兼容依赖
.\.venv_gsv310\Scripts\python -m pip install jieba opencc-python-reimplemented pyopenjtalk-prebuilt
```

```powershell
# 拉取 GPT-SoVITS
git clone https://github.com/RVC-Boss/GPT-SoVITS.git third_party/GPT-SoVITS

# 安装其余依赖（跳过 Windows 上常见编译失败的 pyopenjtalk/jieba_fast/opencc）
$req='third_party/GPT-SoVITS/requirements.win_light.txt'
Get-Content 'third_party/GPT-SoVITS/requirements.txt' `
  | Where-Object { $_ -notmatch '^pyopenjtalk' -and $_ -notmatch '^jieba_fast' -and $_ -notmatch '^opencc$' } `
  | Set-Content -Path $req -Encoding UTF8
.\.venv_gsv310\Scripts\python -m pip install -r $req --extra-index-url https://download.pytorch.org/whl/cu124
```

### 2) 下载预训练模型（仅首次）

```powershell
cd third_party/GPT-SoVITS
curl.exe -L -o pretrained_models.zip "https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/pretrained_models.zip"
Expand-Archive pretrained_models.zip GPT_SoVITS -Force

curl.exe -L -o G2PWModel.zip "https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/G2PWModel.zip"
Expand-Archive G2PWModel.zip GPT_SoVITS/text -Force

curl.exe -L -o nltk_data.zip "https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/nltk_data.zip"
$venvPrefix = & "..\..\.venv_gsv310\Scripts\python.exe" -c "import sys; print(sys.prefix)"
Expand-Archive nltk_data.zip $venvPrefix -Force
cd ..\..
```

### 3) 先准备 3~10 秒参考音频

```powershell
ffmpeg -y -i "wodebooks_output\book_94814546_full_20260304\melo_wav_ch1\001_第1章 舔狗三年半，它竟说我攻略错对象！\part_001.wav" `
  -ss 00:00:00 -t 00:00:06 -ac 1 -ar 32000 `
  "wodebooks_output\book_94814546_full_20260304\gptsovits_ref_6s.wav"
```

### 4) 运行（建议先小范围）

```powershell
.\.venv_gsv310\Scripts\python scripts/gptsovits_from_chunks.py `
  --book-dir wodebooks_output/book_94814546_full_20260304 `
  --ref-audio wodebooks_output/book_94814546_full_20260304/gptsovits_ref_6s.wav `
  --start 1 --end 1 --max-parts 1 `
  --output-root wodebooks_output/book_94814546_full_20260304/gptsovits_wav_test `
  --manifest-file wodebooks_output/book_94814546_full_20260304/gptsovits_manifest_test.csv `
  --device cpu --disable-g2pw
```

若你要优先用显卡，把 `--device cpu` 改为 `--device cuda`。

## 下载免费音色到本地（Piper）

已新增脚本：`scripts/download_piper_voices.py`

- 从本地 `voice_assets/piper/voices.json` 读取官方音色索引
- 从 `rhasspy/piper-voices` 下载 `.onnx` + `.onnx.json`（可选 `MODEL_CARD`）
- 保存到 `voice_assets/piper/voices/<voice_key>/`
- 生成清单：`voice_assets/piper/download_manifest.csv`

下载默认音色包（中文 + 英文男女声）：

```powershell
python scripts/download_piper_voices.py --preset starter --include-model-card
```

只下载你指定的音色：

```powershell
python scripts/download_piper_voices.py `
  --preset none `
  --voice zh_CN-huayan-medium `
  --voice en_US-amy-medium `
  --include-model-card
```

查看当前索引里的全部音色 ID：

```powershell
python scripts/download_piper_voices.py --list
```

按语言/质量筛选并下载（示例：下载所有中文 `medium`）：

```powershell
python scripts/download_piper_voices.py `
  --preset none `
  --language zh_CN `
  --quality medium
```

截至 `2026-03-04`，Piper 官方索引里的中文（`zh_CN`）音色为：

- `zh_CN-huayan-x_low`
- `zh_CN-huayan-medium`

## 输出结构

```text
wodebooks_output/
  book_xxx/
    chapters/
      001_章节名.txt
      002_章节名.txt
      ...
    tts_chapters/
      001_章节名.txt
      002_章节名.txt
      ...
    tts_chunks/
      001_章节名/
        part_001.txt
        part_002.txt
      ...
    melo_wav/
      001_章节名/
        part_001.wav
        part_002.wav
        chapter.wav
      ...
    melo_manifest.csv
    tts_manifest.csv
    merged.txt
    index.csv
```

- `chapters/*.txt`：每章一个文件
- `merged.txt`：整本合并文本
- `index.csv`：章节序号、标题、URL、分页数、字数、文件名
