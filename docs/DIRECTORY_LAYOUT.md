# 项目目录说明（当前约定）

更新时间：2026-03-05

这份文档用于解决“目录太多、看不清该用哪个”的问题。  
重点结论：后续以 **Azure TTS** 作为主流程，优先看 `azure_tts_*` 相关目录与清单。

## 1) 主流程目录（核心）

根目录：

- `scripts/azure_tts_from_chunks.py`：Azure 批量合成脚本（主脚本）
- `wodebooks_output/book_94814546_full_20260304/`：本书全量数据目录

本书目录下的关键内容：

- `chapters/`：抓取后的原始分章文本（来源真值）
- `tts_chapters/`：TTS 清洗后的按章文本
- `tts_chunks/`：按分块切好的文本（API 实际输入）
- `azure_tts_audio/`：Azure 正式合成产物（按章节子目录）
- `azure_tts_manifest.csv`：Azure 产物清单（章节级记录）
- `azure_tts_progress.csv`：Azure 进度清单（`DONE/PARTIAL/TODO`）

## 2) Azure 相关文件怎么理解

- `azure_tts_audio/<章节>/part_*.wav`：该章节的分块音频
- `azure_tts_audio/<章节>/chapter.wav`：该章节合并后音频
- `azure_tts_manifest.csv`：记录“已生成章节”的元数据
- `azure_tts_progress.csv`：按全书统计每章状态，迁移设备后优先看这个

建议顺序：

1. 先看 `azure_tts_progress.csv`，确认哪些 `TODO`。
2. 再按章节范围运行 Azure 脚本（`--start/--end`）。
3. 跑完后再次查看 `azure_tts_progress.csv` 是否转为 `DONE`。

## 3) 现有测试目录（非主流程）

以下目录主要用于历史测试或对比，不是当前主流程必需：

- `azure_tts_audio_test/`
- `azure_tts_manifest_test.csv`
- `google_tts_audio/`
- `google_tts_audio_test_client/`
- `google_tts_audio_test_rest/`
- `melo_wav*`
- `gptsovits_wav*`

它们可以保留，但日常生产时可忽略。

## 4) 版本管理约定（已调整）

为便于换设备继续生产，以下 Azure 产物/进度现在纳入 git：

- `wodebooks_output/book_94814546_full_20260304/azure_tts_audio/**`
- `wodebooks_output/book_94814546_full_20260304/azure_tts_audio_test/**`
- `wodebooks_output/book_94814546_full_20260304/azure_tts_manifest.csv`
- `wodebooks_output/book_94814546_full_20260304/azure_tts_manifest_test.csv`
- `wodebooks_output/book_94814546_full_20260304/azure_tts_progress.csv`

敏感信息仍不入库：

- `google-credentials/`
- `*.sa-key.json`
- 任何 API key / secret 文件

## 5) 换设备后的最短操作

1. `git pull`
2. 配置 Azure 环境变量：`AZURE_TTS_KEY`、`AZURE_TTS_REGION`
3. 打开 `azure_tts_progress.csv` 查看 `TODO` 章节
4. 执行脚本续跑：

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
