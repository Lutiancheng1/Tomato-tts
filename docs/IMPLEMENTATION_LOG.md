# 实现记录（2026-03-04）

## 目标

1. 将当前目录 5 张番茄小说长截图提取为文本。  
2. 尽量提高 OCR 精度，并过滤章节字数/更新时间等噪声。  
3. 产出可直接用于 TTS 配音的视频口播文本。  
4. 给出可执行的 TTS 选型建议。

## 已完成事项

### 1) 项目初始化与仓库绑定

- 已在目录初始化 git 仓库。
- 已设置远程仓库：
  - `origin = https://github.com/Lutiancheng1/Tomato-tts.git`

### 2) OCR 脚本落地

新增脚本：

- `scripts/ocr_tomato.py`

关键能力：

- 自动发现输入目录中的图片文件（`png/jpg/jpeg/webp/bmp`）。
- OCR 引擎支持：
  - `vision`：macOS Vision OCR（本次实测中文识别更好）
  - `tesseract`：离线可移植
  - `auto`：优先 vision，失败回退 tesseract
- 清洗规则：
  - 过滤 `本章字数/字效/更新时间/日期/下一章/目录/番茄小说` 等信息
  - 过滤短碎片噪声（如 `日：`、`滴。`、`下-`、`过。`）
  - 行内规范化（如 `系統 -> 系统`、`bug -> BUG`、异常省略号修复）
- 输出文件：
  - `raw/*.txt`
  - `clean/*.txt`
  - `merged_for_tts.txt`
  - `merged_with_markers.txt`
  - `review_flags.txt`

### 3) OCR 结果产出

已生成目录：

- `ocr_results_vision/`

核心结果：

- `ocr_results_vision/merged_for_tts.txt`（TTS 输入主文件）
- `ocr_results_vision/clean/*.txt`（逐图校对）
- `ocr_results_vision/review_flags.txt`（可疑行）

## 为什么选 Vision 作为主引擎

同一张样图对比中，`vision` 的中文可读性明显高于 `tesseract`：

- 人名、对话、标点恢复更稳定
- 英文乱码片段更少
- 对长截图和轻度模糊表现更好

## 当前已知限制

1. 原图模糊、截图压缩会导致不可逆错字。  
2. 个别句子可能存在断行或上下文缺字，仍需人工快速校对。  
3. `review_flags.txt` 受规则敏感度影响，建议与 `clean` 目录联合检查。

## 推荐 TTS 方案

按你的“小说转语音用于剪辑视频”场景，推荐优先级如下：

### A. 中文落地优先（性价比/可用性）

- 腾讯云 TTS
- 火山引擎语音合成
- 阿里云智能语音

适合：中文音色、国内网络与延迟、成本可控。

### B. 情感演绎优先

- ElevenLabs

适合：更强情绪表现、角色化配音。

### C. API 工程集成优先

- OpenAI TTS
- Azure Speech
- Google Cloud Text-to-Speech

适合：文档完善、开发体验好、易接入自动化流水线。

## 推荐的生产流程

1. OCR：运行 `ocr_tomato.py` 生成 `clean + merged_for_tts`。  
2. 快速校对：优先检查 `review_flags.txt`，再抽样校对 `clean/*.txt`。  
3. 切分文本：按段落/句号切成 50~200 字短段，便于后期对齐视频。  
4. TTS 合成：批量生成音频片段（建议 `wav/mp3` + 保留片段编号）。  
5. 剪辑：导入视频轨，按片段编号快速对齐；必要时调语速/停顿。  

## 后续可继续做的事

1. 增加“自动分段 + 批量 TTS 合成”脚本。  
2. 增加“多引擎结果对齐投票”以进一步提高 OCR 可靠性。  
3. 输出 SRT 字幕（时间轴后续可结合 TTS 回传时长自动生成）。
