# 音频转写与纪要

输入一个本地音频文件，一条命令得到带时间戳的转写稿和中文纪要。转写由 MLX Whisper 执行，MiniCPM5 只负责整理文本。定位是个人课程 / 会议流水线；Meetily 等现成产品功能更完整。

## 安装与使用

Apple Silicon macOS：

```sh
uv sync --extra audio
```

必须先准备一个**本地 MLX Whisper 模型目录**，内含 `config.json` 和 `weights.safetensors` 或 `weights.npz`。推理时不会从 Hugging Face 下载模型。可以把已经下载的 Hugging Face `snapshots/<revision>` 目录传入。目录名或 `refs/main` 文件存在不代表权重完整。

```sh
uv run mcpm audio /path/to/lesson.m4a \
  --whisper-model /path/to/whisper-model \
  --language zh --output-dir ./local-output/audio
```

音频解码优先使用 macOS 自带 `afconvert`，其次使用 PATH 中的 `ffmpeg`。都不可用时仅接受 16 kHz 单声道 16-bit PCM WAV。不采集麦克风或系统音频，不做说话人分离。

文本摘要沿用工具集的本地模型配置。只转写、不需要 MiniCPM 服务：

```sh
uv run mcpm audio /path/to/lesson.wav \
  --whisper-model /path/to/whisper-model --no-summary \
  --output-dir ./local-output/audio
```

每次输出到一个新的 `YYYY-MM-DD-audio-<随机后缀>` 子目录，生成 `transcript.txt`、`transcript.json`、`summary.md`（未启用摘要时没有最后一项）。已有文件不会被覆盖。目录默认以当前用户私有权限创建。若摘要服务失败，转写会保留，终端返回失败并打印重试指令。

## 重用转写与可复现示例

JSON 结构是 `{"segments":[{"start":0,"end":3.5,"text":"原文"}]}`，时间单位为秒。按开始时间排序，不能为空。无需重新运行 Whisper：

```sh
uv run mcpm audio --transcript-json examples/audio-transcript.json \
  --output-dir ./local-output/audio --no-summary

# 摘要模型运行后，同一份输入生成纪要
uv run mcpm audio --transcript-json examples/audio-transcript.json \
  --output-dir ./local-output/audio
```

仓库中的 JSON 是明确标注的**手写测试夹具**，不是对真实课程的识别结果。三种演示路径是音频完整处理、仅转写、重用 JSON 整理；是否已完成真实模型验收，以根目录验证记录为准。

## 输出依据与限制

纪要包含一句话概述、关键点、行动项和未决问题。长转写按 `--chunk-chars`（默认 5000 个字符）分块整理。每块分别做“概述 / 关键点 / 问题”和“待办提取”两次短模型调用，再按顺序合并并去重，不做跨块的自由改写。拆开待办提取，是因为真实测试中模型在同时整理四类信息时漏掉了明确的英文任务。单个超长片段被拆分后保留原来的整段时间范围，不假装拥有更精确的时间戳。

转写先按句子 / 分句拆成带 ID 的原文片段。模型选择关键点、行动项和问题的来源 ID，程序再从本地恢复逐字原文，避免小模型抄错、翻译或修改引用。未知 ID 丢弃并记录数量；如果没有任何有效引用，整次摘要返回失败，保留转写，不把空白模板当成成功。关键点、行动项和问题都显示被选中的原文，不采用模型扩写的任务。负责人、截止时间必须出现在该条引用原文中，否则显示“未提及”。若姓名候选与时间短语重叠，保留时间之前的姓名原文，防止把“小王明天下午”中的“明”算进姓名。明显以“是否 / should we”等开头的问题不列待办；已经完成且没有未来任务提示的分句也不列待办。这些是保守规则，会漏掉一些复杂表达。

这只能验证引用存在，无法证明模型正确理解了任务含义。模型仍可能把已完成的事误判为待办，转写也可能误认人名和日期。摘要明确标为待核对的模型草稿；概述是模型归纳，其他部分为模型挑选的原文摘录，应对照保留的转写和录音。不同块之间不推断隐含负责人，宁可写“未提及”。

音频和转写可能很大，当前会在内存中解码整段音频；建议先用不超过十分钟的样本。所有输出只写入指定目录，不上传音频或转写，无云端回退。

技术来源：[MLX Whisper 官方说明](https://github.com/ml-explore/mlx-examples/tree/main/whisper)、[MiniCPM 官方部署](https://github.com/OpenBMB/MiniCPM/blob/main/docs/deployment/ollama.md)。

## 本机实测记录（2026-11-12）

在当前 Apple Silicon 机器上下载 `mlx-community/whisper-tiny` 的 MLX 权重到 `.local/whisper-tiny`（约 71 MB）。通过 macOS `say` 合成 14 秒中文音频，再由真实 MLX Whisper 本地转写；不是用测试替身模拟转写。

输入口播：“今天讨论课程实验报告。数据清洗已经完成。小王明天下午提交实验报告。参考文献还需要整理。是否增加对照实验，下次再讨论。”

实际输出为繁体中文，保留了“小王明天下午提交實驗報告”，并把“还需要整理”识别为“還是要整理”。说明短样本流程可运行，**不代表真实课堂或会议准确率**。时间戳为整个片段 `00:00:00.000 → 00:00:13.920`，没有精细到每句话。

本地生成文件位于 `.local/validation/audio/`，不纳入 Git。可按上面的命令重新验证；不要把合成口播称为真实用户会议材料。完整摘要使用 MiniCPM5-2B 的本地 Ollama 服务通过，见下文。

英文 WAV 样本也通过真实转写：输入 “Today we reviewed the project. Data cleaning is complete. Alice will send the first report tomorrow. We still need to organize references. We will discuss the extra experiment next week.”，实际输出保留全部五句，并分别生成时间段（末尾约 10.88 秒）。同样为合成音频，仅证明该样本流程。

可复现的完整中文合成音频演示脚本（会调用 macOS `say` 和本地摘要服务）：

```sh
sh examples/audio_demo.sh /absolute/path/to/whisper-model
```

每次生成独立目录，避免覆盖之前的样本。脚本本身不会下载模型。

### MiniCPM 摘要实测

同一份中文口播，`MINICPM_MODEL=minicpm5-2b` 的完整命令生成了转写和纪要，正确提取“小王明天下午提交實驗報告”，负责人“小王”、截止“明天下午”；“參考文獻還是要整理”的负责人、时间均为“未提及”。已经完成的数据清洗没有列为待办。记录：`.local/validation/audio/2026-11-12-audio-q5jz_mcb/summary.md`。

这一次样本中，模型还把文献整理同时列为未决问题，分类仍需核对。此前的 1B 测试出现过重复模板、误判完成状态和把所有片段归为待办，**不建议用该 1B 配置作为可靠纪要的默认值**；此次 2B 样本结果更合适，但不是通用准确率保证。

最终版本（2B、温度 0、按原文 ID 选择、独立待办提取）又做了中英文完整重跑：

- 中文：`.local/validation/audio/2026-11-12-audio-d33w2yd5/summary.md`。保留报告和文献两项待办，负责人小王正确，疑问句未当成待办；日期字段只抽出“明天”，原文待办仍完整保留“明天下午”，因此时间细节请以引用为准。
- 英文：`.local/validation/audio/2026-11-12-audio-d3ueyrrm/summary.md`。三项未来任务均被保留，Alice / tomorrow、未提及 / 未提及、未提及 / next week 均有原文依据。数据清洗已完成没有列为待办。

仍需人工核对：概述可能遗漏细节，关键点不保证穷尽，时间字段可能只提取原文时间的一部分，尚未完成的工作可能同时被归入未决问题。测试使用明确标注的合成输入，尚无真实课堂长录音、嘈杂音频或多人场景的质量证据。

### 逗号称呼与任务的出处（2026-11-12）

发现合成转写“小王，明天提交报告。”以前被逗号拆成两个引用片段：任务片段没有“小王”，即便负责人在原句中明确出现，校验也只能显示“未提及”。现在对同一转写段中形如“小王，”“张三，”“李老师，”或“具体英文名,”的短称呼，将它与紧随的分句保持为一个原文片段；开始、结束时间沿用原转写段，不伪造更细时间戳。负责人仍须由模型输出并在引用中逐字出现，程序不会根据这一规则自动指定负责人。没有说话人分离，不跨转写段拼接，以免把两个说话人的话误归属；未匹配的称呼、跨段称呼和语义上的指派仍需人工核对。

本机 MiniCPM5-2B 以合成转写测试了“小王，明天提交实验报告。”和“小李，周五检查参考文献。”，均保留完整原文，分别输出对应负责人和时间，已完成的数据清洗没有被列为待办。结果保存在 `.local/validation/vocative/`，这只证明该样本的输出，并非真实会议准确率评估；转写错误、模型误判和人名歧义仍可能导致归属错误。
