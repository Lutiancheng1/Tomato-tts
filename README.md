# Tomato-tts

这个仓库现在只用于：从小说网站抓取章节文本（不再包含 OCR 流程）。

## 目录导航

目录较多时，优先看这份说明文档：

- `docs/DIRECTORY_LAYOUT.md`

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
- `scripts/google_tts_from_chunks.py`
  - 读取 `tts_chunks` 并调用 Google Cloud Text-to-Speech 批量合成
  - 支持 `client`（ADC/服务账号）和 `rest`（API Key）两种调用方式
  - 可输出 `LINEAR16/MP3/OGG_OPUS`，其中 `LINEAR16` 会自动拼接 `chapter.wav`
  - 输出音频清单 `google_tts_manifest.csv`
- `scripts/azure_tts_from_chunks.py`
  - 读取 `tts_chunks` 并调用 Azure Speech Text-to-Speech（REST）批量合成
  - 默认可直接用 `zh-CN-XiaochenNeural`（晓辰，年轻女声）
  - 支持 `wav/mp3/ogg` 输出，`wav` 模式会自动拼接每章 `chapter.wav`
  - 输出音频清单 `azure_tts_manifest.csv`
- `scripts/google_tts_voice_previews.py`
  - 批量拉取中文相关音色（`cmn-/yue-/zh-`）并生成试听 MP3
  - 输出 `manifest.csv`，便于按音色名筛选

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

## 换电脑重建分块（重点）

`tts_chunks` 默认不作为长期版本文件维护。  
换到新电脑（例如 macOS）后，建议按下面流程重建并继续批量生产：

### 1) 先拉代码

```bash
git pull
```

### 2) 重建 `tts_chunks`

```bash
python3 scripts/prepare_tts_chapters.py \
  --book-dir wodebooks_output/book_94814546_full_20260304 \
  --chunk-max-chars 280 \
  --sentence-max-chars 60
```

重建后会生成：

- `wodebooks_output/book_94814546_full_20260304/tts_chunks/`
- `wodebooks_output/book_94814546_full_20260304/tts_manifest.csv`

### 3) 用 Google TTS 批量生产

使用 ADC（推荐）：

```bash
python3 scripts/google_tts_from_chunks.py \
  --book-dir wodebooks_output/book_94814546_full_20260304 \
  --output-root wodebooks_output/book_94814546_full_20260304/google_tts_audio \
  --manifest-file wodebooks_output/book_94814546_full_20260304/google_tts_manifest.csv \
  --backend client \
  --language-code cmn-CN \
  --voice-name cmn-CN-Chirp3-HD-Achernar \
  --audio-encoding LINEAR16
```

或用 API Key：

```bash
export GOOGLE_TTS_API_KEY="<YOUR_API_KEY>"
python3 scripts/google_tts_from_chunks.py \
  --book-dir wodebooks_output/book_94814546_full_20260304 \
  --backend rest \
  --language-code cmn-CN \
  --voice-name cmn-CN-Chirp3-HD-Achernar \
  --audio-encoding MP3
```

注意：

- `google-credentials/google_tts_api_key.txt` 不会提交到 git，需要你在新电脑自行配置。
- 若先做小样测试，可加 `--start 1 --end 1 --max-parts 2`。

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

## Google Cloud TTS（API）

已新增脚本：`scripts/google_tts_from_chunks.py`

- 输入：`tts_chunks/<章节>/part_*.txt`
- 输出：`google_tts_audio/<章节>/part_*.wav|mp3|ogg`（`LINEAR16` 还会生成 `chapter.wav`）
- 清单：`google_tts_manifest.csv`

### 1) 开通与认证（推荐用服务账号 / ADC）

> 说明：你说的 Google Pro 会员通常不等于 Google Cloud 的 API 计费。  
> Text-to-Speech API 走 Google Cloud 项目计费和额度，需要在 Cloud 项目里单独启用 API 与 billing。

安装 Cloud SDK（若未安装）：

```powershell
winget install --id Google.CloudSDK -e
```

初始化并选择项目：

```powershell
gcloud init
gcloud config set project <YOUR_PROJECT_ID>
gcloud services enable texttospeech.googleapis.com
```

本机开发（ADC）：

```powershell
gcloud auth application-default login
```

或使用服务账号 key（更适合脚本批处理）：

```powershell
gcloud iam service-accounts create tomato-tts --display-name "Tomato TTS"
gcloud projects add-iam-policy-binding <YOUR_PROJECT_ID> `
  --member="serviceAccount:tomato-tts@<YOUR_PROJECT_ID>.iam.gserviceaccount.com" `
  --role="roles/editor"
gcloud iam service-accounts keys create .\\google-credentials\\tomato-tts.sa-key.json `
  --iam-account="tomato-tts@<YOUR_PROJECT_ID>.iam.gserviceaccount.com"

$env:GOOGLE_APPLICATION_CREDENTIALS = "E:\\coding\\Tomato-tts\\google-credentials\\tomato-tts.sa-key.json"
```

### 2) 安装 Python 依赖

```powershell
py -3.10 -m venv .venv_google310
.\.venv_google310\Scripts\python -m pip install -U pip
.\.venv_google310\Scripts\python -m pip install google-cloud-texttospeech
```

### 3) 先列出可用音色

```powershell
.\.venv_google310\Scripts\python scripts/google_tts_from_chunks.py `
  --backend client `
  --language-code cmn-CN `
  --list-voices
```

### 4) 小范围试跑（第 1 章前 2 段）

```powershell
.\.venv_google310\Scripts\python scripts/google_tts_from_chunks.py `
  --book-dir wodebooks_output/book_94814546_full_20260304 `
  --start 1 --end 1 --max-parts 2 `
  --output-root wodebooks_output/book_94814546_full_20260304/google_tts_audio_test `
  --manifest-file wodebooks_output/book_94814546_full_20260304/google_tts_manifest_test.csv `
  --backend client `
  --language-code cmn-CN `
  --voice-name cmn-CN-Chirp3-HD-Achernar `
  --audio-encoding LINEAR16 `
  --speaking-rate 1.0 --pitch 0 --volume-gain-db 0 `
  --delay 0.05
```

全量跑全部章节（保持 `LINEAR16` 方便自动拼接每章 `chapter.wav`）：

```powershell
.\.venv_google310\Scripts\python scripts/google_tts_from_chunks.py `
  --book-dir wodebooks_output/book_94814546_full_20260304 `
  --output-root wodebooks_output/book_94814546_full_20260304/google_tts_audio `
  --manifest-file wodebooks_output/book_94814546_full_20260304/google_tts_manifest.csv `
  --backend client `
  --language-code cmn-CN `
  --voice-name cmn-CN-Chirp3-HD-Achernar `
  --audio-encoding LINEAR16 `
  --speaking-rate 1.0 --pitch 0 --volume-gain-db 0
```

### 5) API Key + CLI（一次性测试）

如果你想先用 API Key 直接打 REST 接口，先在 Google Cloud 控制台创建 key，然后：

```powershell
$env:GOOGLE_TTS_API_KEY="<YOUR_API_KEY>"
```

请求并落地 MP3：

```powershell
$req = @'
{
  "input": {"text": "你好，这是 Google Cloud TTS 的测试。"},
  "voice": {"languageCode": "cmn-CN", "name": "cmn-CN-Chirp3-HD-Achernar"},
  "audioConfig": {"audioEncoding": "MP3"}
}
'@

$resp = Invoke-RestMethod `
  -Method Post `
  -Uri "https://texttospeech.googleapis.com/v1/text:synthesize?key=$env:GOOGLE_TTS_API_KEY" `
  -ContentType "application/json; charset=utf-8" `
  -Body $req

[IO.File]::WriteAllBytes("google_tts_test.mp3", [Convert]::FromBase64String($resp.audioContent))
```

如果你要在批量脚本里走 API Key，也可以改用 `--backend rest --api-key ...`。

### 6) 批量生成中文音色试听（MP3）

```powershell
.\.venv_google310\Scripts\python scripts/google_tts_voice_previews.py `
  --voice-family chirp3-hd `
  --clean-output `
  --output-dir wodebooks_output/google_tts_voice_previews_20260304_fixed
```

输出：

- `wodebooks_output/google_tts_voice_previews_20260304_fixed/*.mp3`
- `wodebooks_output/google_tts_voice_previews_20260304_fixed/manifest.csv`
- 默认建议生成 `Chirp 3: HD` 音色试听

### 7) 常见问题（Google TTS）

- 问：支持把“一整章文本”一次性传给 Google TTS 吗？
  - 当前脚本默认不这么做，设计为读取 `tts_chunks/<章节>/part_*.txt` 分块合成，再按章节汇总。
  - 原因是云端 TTS 单次请求有文本长度限制，整章直传容易超限或失败。
- 问：默认用哪种音色？
  - `--voice-name` 为空时，脚本会优先选择 `Chirp 3: HD`（当前已内置 `cmn-CN` 和 `yue-HK` 默认值）。
- 问：支持批量吗？
  - 支持。可通过 `--start/--end` 按章节范围批量，也可不传 `--end` 直接全量跑。
  - 可用 `--max-parts` 做小样本测试，再去掉限制跑全量。
- 问：如何控制最终每章一个文件？
  - `--audio-encoding LINEAR16` 时会自动合并为每章 `chapter.wav`。
  - `MP3/OGG_OPUS` 模式默认只生成分块音频文件（不做无损拼接）。

## Azure Speech TTS（API）

已新增脚本：`scripts/azure_tts_from_chunks.py`

- 输入：`tts_chunks/<章节>/part_*.txt`
- 输出：`azure_tts_audio/<章节>/part_*.wav|mp3|ogg`（RIFF PCM 会自动生成 `chapter.wav`）
- 清单：`azure_tts_manifest.csv`
- 进度：`azure_tts_progress.csv`（`DONE/PARTIAL/TODO`，用于看哪些章节已生成）

### 1) 先准备 Key + Region

在 Azure 门户创建（或使用已有）Speech 资源后，拿到：

- `KEY`（密钥）
- `REGION`（区域，例如 `eastasia`）

在 PowerShell 设置环境变量：

```powershell
$env:AZURE_TTS_KEY="<YOUR_AZURE_SPEECH_KEY>"
$env:AZURE_TTS_REGION="<YOUR_AZURE_REGION>"
```

### 2) 列出可用音色（先确认晓辰）

```powershell
python scripts/azure_tts_from_chunks.py `
  --locale zh-CN `
  --list-voices
```

常见目标音色：

- `zh-CN-XiaochenNeural`（晓辰，年轻女声）

### 3) 小范围试跑（第 1 章前 2 段）

```powershell
python scripts/azure_tts_from_chunks.py `
  --book-dir wodebooks_output/book_94814546_full_20260304 `
  --start 1 --end 1 --max-parts 2 `
  --output-root wodebooks_output/book_94814546_full_20260304/azure_tts_audio_test `
  --manifest-file wodebooks_output/book_94814546_full_20260304/azure_tts_manifest_test.csv `
  --locale zh-CN `
  --voice-name zh-CN-XiaochenNeural `
  --output-format riff-24khz-16bit-mono-pcm `
  --speaking-rate 1.0 --pitch 0 `
  --delay 0.05
```

### 4) 全量跑全部章节

```powershell
python scripts/azure_tts_from_chunks.py `
  --book-dir wodebooks_output/book_94814546_full_20260304 `
  --output-root wodebooks_output/book_94814546_full_20260304/azure_tts_audio `
  --manifest-file wodebooks_output/book_94814546_full_20260304/azure_tts_manifest.csv `
  --locale zh-CN `
  --voice-name zh-CN-XiaochenNeural `
  --output-format riff-24khz-16bit-mono-pcm `
  --speaking-rate 1.0 --pitch 0
```

### 4.1) 只跑第一章（完整章节）

```powershell
python scripts/azure_tts_from_chunks.py `
  --book-dir wodebooks_output/book_94814546_full_20260304 `
  --start 1 --end 1 `
  --output-root wodebooks_output/book_94814546_full_20260304/azure_tts_audio `
  --manifest-file wodebooks_output/book_94814546_full_20260304/azure_tts_manifest.csv `
  --progress-file wodebooks_output/book_94814546_full_20260304/azure_tts_progress.csv `
  --locale zh-CN `
  --voice-name zh-CN-XiaochenNeural `
  --output-format riff-24khz-16bit-mono-pcm
```

说明：

- `azure_tts_manifest.csv` 会保留历史已生成章节记录（后续按章节补跑不会丢失旧记录）。
- `azure_tts_progress.csv` 会基于 `tts_chunks` 全量章节更新状态，方便看“哪些已完成，哪些待生成”。

### 4.2) 目录与版本管理建议

- 推荐固定使用：`wodebooks_output/<book>/azure_tts_audio/` 作为 Azure 产物目录。
- 该目录属于可再生输出，不建议提交到 git（仓库里默认也会忽略大部分 `wodebooks_output` 产物）。
- 需要跨电脑继续生产时：只要拉代码 + 重建 `tts_chunks`，再跑 Azure 脚本即可续跑。

### 5) 可选参数（调风格）

- `--style cheerful`：仅在音色支持该风格时生效
- `--style-degree 1.2`：风格强度
- `--role YoungAdultFemale`：角色（同样依赖音色支持）

示例：

```powershell
python scripts/azure_tts_from_chunks.py `
  --book-dir wodebooks_output/book_94814546_full_20260304 `
  --start 1 --end 1 --max-parts 2 `
  --locale zh-CN `
  --voice-name zh-CN-XiaochenNeural `
  --style cheerful --style-degree 1.2 `
  --output-format audio-24khz-160kbitrate-mono-mp3
```

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
    google_tts_audio/
      001_章节名/
        part_001.wav
        part_002.wav
        chapter.wav
      ...
    azure_tts_audio/
      001_章节名/
        part_001.wav
        part_002.wav
        chapter.wav
      ...
    melo_manifest.csv
    google_tts_manifest.csv
    azure_tts_manifest.csv
    azure_tts_progress.csv
    tts_manifest.csv
    merged.txt
    index.csv
```

- `chapters/*.txt`：每章一个文件
- `merged.txt`：整本合并文本
- `index.csv`：章节序号、标题、URL、分页数、字数、文件名
