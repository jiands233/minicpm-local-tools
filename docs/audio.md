# 音频转写与纪要

输入一个本地音频文件，一条命令得到带时间戳的转写稿和中文纪要。转写由 MLX Whisper 执行，MiniCPM5 只负责整理文本。定位是个人课程 / 会议流水线；Meetily 等现成产品功能更完整。

## 安装与使用

Apple Silicon macOS：

```sh
uv sync --extra audio
```

必须先准备一个**本地 MLX Whisper 模型目录**，内含 `config.json` 和 `weights.safetensors` 或 `weights.npz`。推理时不会从 Hugging Face 下载模型。可以把已经下载的 Hugging Face `snapshots/<revision>` 目录传入。目录名或 `refs/main` 文件存在不代表权重完整。

```sh
.venv/bin/mcpm audio /path/to/lesson.m4a \
  --whisper-model /path/to/whisper-model \
  --language zh --output-dir ./local-output/audio
```

音频解码优先使用 macOS 自带 `afconvert`，其次使用 PATH 中的 `ffmpeg`。都不可用时仅接受 16 kHz 单声道 16-bit PCM WAV。不采集麦克风或系统音频，不做说话人分离。

文本摘要沿用工具集的本地模型配置。只转写、不需要 MiniCPM 服务：

```sh
.venv/bin/mcpm audio /path/to/lesson.wav \
  --whisper-model /path/to/whisper-model --no-summary \
  --output-dir ./local-output/audio
```

每次输出到一个新的 `YYYY-MM-DD-audio-<随机后缀>` 子目录，生成 `transcript.txt`、`transcript.json`、`summary.md`（未启用摘要时没有最后一项）。已有文件不会被覆盖。目录默认以当前用户私有权限创建。若摘要服务失败，转写会保留，终端返回失败并打印重试指令。

## 重用转写与可复现示例

JSON 结构是 `{"segments":[{"start":0,"end":3.5,"text":"原文"}]}`，时间单位为秒。按开始时间排序，不能为空。无需重新运行 Whisper：

```sh
.venv/bin/mcpm audio --transcript-json examples/audio-transcript.json \
  --output-dir ./local-output/audio --no-summary

# 摘要模型运行后，同一份输入生成纪要
.venv/bin/mcpm audio --transcript-json examples/audio-transcript.json \
  --output-dir ./local-output/audio
```

仓库中的 JSON 是明确标注的**手写测试夹具**，不是对真实课程的识别结果。三种演示路径是音频完整处理、仅转写、重用 JSON 整理；是否已完成真实模型验收，以根目录验证记录为准。

## 输出依据与限制

纪要包含一句话概述、关键点、行动项和未决问题。长转写按 `--chunk-chars`（默认 5000 个字符）分块，同时限制每块原文请求 JSON 的 UTF-8 编码不超过 3600 字节、最多 24 条来源，避免许多短句时来源 ID 和 JSON 结构占满上下文。字节上限是保守估算而非分词器，不保证任意模型和更小上下文均能容纳；模型输出达到长度上限仍会报错，转写保留。每块分别做“概述 / 关键点 / 问题”和“待办提取”两次短模型调用，再按顺序合并并去重，不做跨块的自由改写。 分块数量增多会增加调用次数和等待时间。拆开待办提取，是因为真实测试中模型在同时整理四类信息时漏掉了明确的英文任务。单个超长片段被拆分后保留原来的整段时间范围，不假装拥有更精确的时间戳。

转写先按句子 / 分句拆成带 ID 的原文片段。模型选择关键点、行动项和问题的来源 ID，程序再从本地恢复逐字原文，避免小模型抄错、翻译或修改引用。关键点、问题和行动项字段必须各自存在且为数组；只有模型明确给出空数组，程序才会将该分类的模型结果视为空；字段缺失或类型错误会中止摘要并保留转写，不会静默冒充空分类。未知 ID 丢弃并记录数量；如果任一块没有有效引用，整次摘要返回失败并保留转写，避免前几块成功而后续块被静默遗漏。对于确实没有可归类内容的片段，该保守规则也可能拒绝生成整份纪要，需核对转写后重试。关键点、行动项和问题都显示被选中的原文，不采用模型扩写的任务。负责人、截止时间必须出现在该条引用原文中，否则显示“未识别（可能遗漏）”；这些字段均标注为模型判断，须核对。若姓名候选与时间短语重叠，保留时间之前的姓名原文，防止把“小王明天下午”中的“明”算进姓名。明显以“是否 / should we”等开头的问题不列待办；已经完成且没有未来任务提示的分句也不列待办。这些是保守规则，会漏掉一些复杂表达。

这只能验证引用存在，无法证明模型正确理解了任务含义。模型仍可能把已完成的事误判为待办，转写也可能误认人名和日期。摘要明确标为待核对的模型草稿；概述是模型归纳，其他部分为模型挑选的原文摘录，应对照保留的转写和录音。不同块之间不推断隐含负责人；未识别不代表原文没有明确指派。

2026-11-12：针对两组共 24 条手写中英文短句比较当前提示词和带角色区分示例的候选提示词。本机模型使用当前提示词时把“明天给小王发报告”的接收人小王误标为负责人；字面包含校验无法发现角色错误。带示例的候选修正了该句，但在另一组中仍有误归属和明确负责人的遗漏，因此未更改默认提示词。为避免把这些提取结果呈现成已核实事实，每条行动项的负责人、截止时间标注“模型判断，待核对”；未识别字段显示“可能遗漏”。这是有限的文本测试，不代表真实录音或一般场景的准确率。

### 负责人复核实验

`examples/audio-owner-eval.json` 包含 32 条虚构中英文短句（人工标注 24 条任务、8 条非任务；负责人为 null 表示未明确写出执行者）。实验使用当前摘要流程，随后对每条被选中的行动项单独询问同一本地模型谁是执行者；“双方一致”仅在两次均给出同一非空原文时保留该负责人。它不会改变默认摘要流程，可使用已运行的本地模型复现：

```sh
.venv/bin/python script/evaluate_audio_owners.py --output .local/validation/owner-eval-new.json
```

输出路径必须不存在；结果仅包含这些虚构样本、统计和运行时间。2026-11-12 本机 `minicpm5-2b` 一次运行中，24 条预期任务全部被选中，8 条非任务未选中；这是当前小样本的任务分类结果。以下负责人统计**仅涵盖被选中的 24 条预期任务**，“正确留空”不是对任务分类准确性的统计：

| 方案 | 负责人正确 | 负责人错误 | 明确负责人遗漏 | 无明确负责人时正确留空 |
| --- | ---: | ---: | ---: | ---: |
| 现有摘要 | 13 | 8 | 1 | 2 |
| 独立逐条复核 | 11 | 5 | 1 | 7 |
| 两次一致才保留 | 9 | 2 | 6 | 7 |

基线分两块、4 次摘要请求约 13.9 秒，逐条复核额外 24 次请求约 5.2 秒，均为本机单次测量；没有复核请求或格式失败。两次一致减少了本样本误归属，但仍有错误、遗漏增加且多次调用，因此未作为默认修复。遇到请求或格式失败，实验将复核结果视作未知，不当成一致。全部输出保存在本机忽略目录 `.local/validation/audio-owner-eval-32-final-20261112.json`；真实录音、跨片段指派和不同模型均未覆盖。

2026-11-12：使用本地模型对手写的 `examples/audio-transcript.json` 再次生成纪要，格式检查通过，但模型把“负责人和截止时间还没有确定”误选为待办，也未识别“小王”作为另一条待办的负责人。这个样本并非真实录音，结果存于本机忽略目录 `.local/validation/audio-schema/`；引用有效不等于分类或字段正确。

随后增加了范围很窄的检查：单独陈述负责人、人选或截止时间尚未确定的短句不当成明确待办；“需要确定负责人”这样的明确任务及包含其他内容的长句不受此规则过滤。相同手写夹具调用本机模型重测，该状态句不再列为行动项，两个原有任务仍保留；但负责人字段仍未识别“小王”，未决问题也仍有误分类。原文中出现名字不必然代表其为执行者，因此没有通过规则猜测负责人。此次输出在 `.local/validation/audio-undecided/`，只是单一合成文本样本，不能证明通用准确率。

音频和转写可能很大，默认会将整段解码后的音频加载到内存；建议先用不超过十分钟的样本。所有输出只写入指定目录，不上传音频或转写，无云端回退。

对于较长音频，可显式按秒数分段，避免一次把整段 PCM 加载为浮点数组：

```sh
.venv/bin/mcpm audio /path/to/lesson.m4a --whisper-model .local/whisper-tiny \
  --language zh --audio-chunk-seconds 300 --output-dir outputs/audio
```

默认不分段，保持原有转写行为。此选项仅接受至少 30 秒的整数，不能与 `--transcript-json` 同用；它不同于控制摘要文本分块的 `--chunk-chars`。分段模式会先将完整音频转换成私有临时 WAV，再逐段加载和调用 Whisper，输出时间戳偏移回原音频。临时 WAV 占用的磁盘空间仍随长度增长（16 kHz 单声道 16-bit 约每小时 110 MiB），并非流式解码；Whisper 模型和推理本身仍需要内存。转换器解码超过 10 分钟会停止，可手动分割音频后重试。正常结束和异常时临时目录会清理；强制结束或系统崩溃可能残留。

分段没有重叠，切点可能截断词句或让片段缺少上下文；指定 `--language` 可避免各段独立自动识别语言。任何一段转写失败或时间戳大幅超出该段实际时长时，整次失败，不把已有片段当作完整结果写出。实测 Whisper 有时将末尾时间预测到实际片段外：对于最多 0.1 秒的结束时间越界，工具提示并截到实际片段末尾；起点越界或超出超过 0.1 秒会报错。合并时间戳依然是模型估计，须与原音频核对。

可选在分段命令中加入 `--audio-silence-cut`，尝试在固定切点前两秒内找连续 0.3 秒的低能量窗口，并在该窗口中间切分；没有满足绝对强度和相对周围强度阈值的窗口时仍在固定点切分。每个音频采样连续且只处理一次，无重叠、无基于猜测的文本去重；除最后余段外，各段长度可能比指定长度短最多约两秒。低能量不是语音活动检测，不保证找到的是说话停顿，低音量语音、噪声、音乐或辅音仍可能造成误判；不启用该选项时保留固定分段。该选项必须与 `--audio-chunk-seconds` 一起用于音频，不能用于已有转写 JSON。

2026-11-12，固定与静音优先切分各一次比较：从公开 JFK 演说取原音频第 40–85 秒，同一本机 tiny 模型在 30 秒固定边界将参考中的 “revolutionary beliefs” 识成 “revolutionaries” 接 “believe”；静音优先选中约 29.15 秒位置，识别为 “Revolutionary Belief”。两者其他词仍有错误；该单人英语样本不是会议质量评测，不证明其他切点必然改善。原音频与参考来源见下方真实英语人声记录，输出位于本机忽略目录 `.local/validation/silence-cut-eval-_9xy4akw/`。

2026-11-12：将公开 JFK 演说样本重复拼成 40.0076875 秒，在本机使用 tiny、30 秒分段、无摘要实测。首次严格检查拒绝第 1 段的 28.08–30.08 秒末句，未发布转写；加入上述有限末尾修正后，重跑成功并提示截断，第二段时间戳以 30 秒为起点，输出末尾不超过音频总时长。这是人工拼接的单人短录音，不证明长会议完整性或分段边界准确率；英文识别本身仍有原样本已记录的错误。

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

### 较多短句的上下文与分块检查（2026-11-12）

合成转写包含 600 次相同的“小王明天交报告。”，共 4800 字符，单个 Whisper 时间范围为 0–600 秒。此前默认按字符分块会让 600 个来源 ID 和 JSON 字段一起送入请求，服务报告 11434 tokens，超过 8192 上下文并返回 HTTP 400；转写保留。新的限制把它分成 25 块，在本机 MiniCPM5-2B 上完成 50 次模型请求，产生可对照原文的待办及原始 0–600 秒时间范围，约用时 5 分 21 秒（单次、重复文本，不是性能基准或真实会议质量测试）。

该测试的多块概述出现了重复句，现仅对完全相同的概述做稳定去重，不让模型自由合并或推断；这是事后根据输出做的代码调整，已使用单元测试验证，未重跑整段。仅当原文、完整起止时间和（行动项的）负责人、截止时间都相同时才合并重复引用；不同结束时间或不同指派会分别保留。完全同一转写段中出现多次相同文字时，Whisper 没有提供分句位置或独立时间戳，本工具仍可能合并这些无法区分的重复项；请以完整转写为准。这份重复样本不能证明真实长会议摘要完整、准确或能识别所有任务。

### 真实中文人声小样本（2026-11-12）

使用 [Ming-3.0-asr 固定版本示例及归属说明](https://github.com/inclusionAI/Ming-3.0-asr/blob/6141e8c552815db724d8df0f72c9d865c547a1ea/examples/cases/README.md)提供的 Common Voice 15 普通话录音 `common_voice_zh-CN_22099416`：该项目标注其来源为 Mozilla Common Voice，许可为 CC0。音频为 5.904 秒单人朗读，不是自然会议或课堂；未尝试识别说话人身份。该示例项目提供的参考文本为“漓江和湘江有秦代开凿的灵渠沟通”。这里是对比其提供的参考文本，并非对录音逐字人工听审。样本及输出仅存本机忽略目录 `.local/validation/human-speech/zh-commonvoice.KuiCD3WR/`，不纳入仓库。

同一音频在本机分别使用 MLX Whisper tiny 和 large-v3-turbo，指定 `--language zh --no-summary`：

| 模型 | 此次转写 | 与参考文本对照 |
| --- | --- | --- |
| tiny | 李江和鄉江有情帶開找的零局溝通 | 地名和“秦代开凿的灵渠”等多处识别错误；繁体仅是书写形式，不自动算错。 |
| large-v3-turbo | 离江和湘江有琴代开凿的灵渠沟通 | “漓江”识别为“离江”，“秦代”识别为“琴代”，其余字面与参考一致。 |

这只是单条短朗读，不可据此推断中文会议、口音、长音频或整体准确率；大模型仍会误识同音字。此次仅验收转写，未测试摘要、行动项或语义归属。源 WAV 为 48 kHz 单声道 PCM，SHA256 `978e46a482b8b2f3a2eb1ad1d5ee61b9eb0e3668e2627ec1b49d809a12bf21da`；工具实际通过本机解码器转换音频后推理。

可复现 tiny 的方法（显式下载小音频，不下载模型，每次新建目录）：

```sh
(
set -eu
mkdir -p .local/validation/human-speech
sample_dir="$(mktemp -d .local/validation/human-speech/zh-commonvoice.XXXXXXXX)"
curl -fL https://raw.githubusercontent.com/inclusionAI/Ming-3.0-asr/6141e8c552815db724d8df0f72c9d865c547a1ea/examples/cases/audio/chinese_common_voice.wav -o "$sample_dir/chinese.wav"
shasum -a 256 "$sample_dir/chinese.wav"
.venv/bin/mcpm audio "$sample_dir/chinese.wav" --whisper-model .local/whisper-tiny --language zh --no-summary --output-dir "$sample_dir/tiny"
)
```

将 `--whisper-model` 改为事先准备好的 large-v3-turbo 本地目录可对照该模型；权重取得与校验说明见下方真实人声模型对比部分。模型、下载音频和输出均不进入 Git。

### 真实英语人声小样本（2026-11-12）

为补充合成语音测试，另用肯尼迪 1961 年就职演说的公开历史录音，截取音频 **40–60 秒**作单说话人英语样本。这是真实人声演讲，不是课程或会议录音。来源：[Wikimedia Commons 文件页](https://commons.wikimedia.org/wiki/File:JFK_inaugural_address.ogg)将此录音标为美国联邦政府作品及 Public Domain Mark 1.0，并列 John F. Kennedy Presidential Library & Museum 为来源；不同司法辖区的权利状况应另行核实。对照参考是[美国国家档案馆的演讲文本](https://www.archives.gov/milestone-documents/president-john-f-kennedys-inaugural-address)。仓库不包含录音，下载的文件和输出均留在 `.local/`。

本机使用 MLX Whisper tiny（`.local/whisper-tiny`）与 MiniCPM5-2B、英语识别，一次命令产生转写与纪要，退出 0，时间戳覆盖截取的 0–20 秒（相对于片段，不是原始录音时间）。录音源 5.7 MiB，源文件 SHA256 `a257580da6eda796ed1c703e545865005753f7cb20cc042e0db3c44de82274fc`；转换后片段 SHA256 `d7f78b7cd0184b86d7e6dd6ed1c40e40f0b516e50006e2b10b47ef85dd7c2d3d`。本机结果在 `.local/validation/human-speech/output/2026-11-12-audio-ge1y58po/`，仅作为一次验证，不进入 Git。

**质量未通过逐字核对**：转写把原文中的 “solemn oath” / “forbears” 分别误识为 “Solomon” / “four bears”，还把 “mortal hands” 误识为 “moral hands”；“The world is very different now” 被保留。纪要引用的关键点继承了错误转写，并对截断片段做出含糊概述；没有列出行动项。引用能对应转写不代表对应录音真实内容。单次 20 秒、公开演说、单说话人测试不能证明真实课堂或会议的质量，更不能据此计算可靠的整体准确率。

可复现的摘取及调用（会显式下载原始音频；需按项目模型文档准备依赖和权重）：

```sh
(
set -eu
mkdir -p .local/validation/human-speech
sample_dir="$(mktemp -d .local/validation/human-speech/run.XXXXXXXX)"
curl -fL https://upload.wikimedia.org/wikipedia/commons/d/d5/JFK_inaugural_address.ogg -o "$sample_dir/jfk-commons.ogg"
afconvert -f WAVE -d LEI16@16000 -c 1 "$sample_dir/jfk-commons.ogg" "$sample_dir/jfk-commons-full.wav"
.venv/bin/python - "$sample_dir" <<'PY'
import sys
import wave
from pathlib import Path
folder = Path(sys.argv[1])
with wave.open(str(folder / 'jfk-commons-full.wav'), 'rb') as source:
    source.setpos(40 * source.getframerate())
    frames = source.readframes(20 * source.getframerate())
    with wave.open(str(folder / 'jfk-commons-excerpt.wav'), 'wb') as target:
        target.setparams(source.getparams())
        target.writeframes(frames)
PY
.venv/bin/mcpm audio "$sample_dir/jfk-commons-excerpt.wav" --whisper-model .local/whisper-tiny --language en --output-dir "$sample_dir/output"
printf '样本目录：%s\n' "$sample_dir"
)
```

每次运行用 `mktemp -d` 创建独立目录，保留既有样本；失败后也保留新目录供排查。完整演说转换后的临时 WAV 约 26 MiB。仍需用经授权的中文真实说话人、多人及更长音频做独立验收。

### 真实人声的 Whisper 模型选择对照（2026-11-12）

在同一台 Apple Silicon Mac、同一段上面的 20 秒 JFK 英语演说片段、同一 CLI `--language en --no-summary` 设置下，分别单次运行本地多语言 MLX Whisper tiny、base 和 small。**这些调用只验证转写，没有运行 MiniCPM 摘要**；各输出均使用独立目录，时间戳相对片段开始。

| 本地模型 | 权重大小 | 单次 CLI 墙钟时间 | 与国家档案馆文本对照的观察 |
| --- | ---: | ---: | --- |
| tiny | 约 71 MiB | 0.85 秒 | 将 oath 一词附近误识为 “Solomon”，将 “forbears” 误写为 “four bears”，并将 “mortal” 误写为 “moral”。 |
| base | 约 137 MiB | 1.81 秒 | 正确识别 “forebears”（与参考中的 “forbears” 属不同拼写）及 “mortal”，但 oath 一词附近仍误为 “solomoth”。 |
| small | 约 459 MiB | 1.58 秒 | 正确识别 “forebears” 与 “mortal”，但 oath 附近误为 “Solomon”，并误写前面的 “our” 为 “are”。 |

耗时包含 CLI 启动和音频解码；每个模型只运行一次，无法比较冷启动、性能或普遍准确率。这个短片段是单人英语历史演说，录音音质、口音与真实课程会议不同。三个模型都仍有实质错误；base/small 在这几个词上改善，不能保证在中文、嘈杂音频、多人或其他样本上更好。纪要以转写为输入，错误仍会传入摘要，重要任务、时间与人名应听录音核对。以上对照的来源与限制见上一节，参考原稿的版权及本地模型的许可由其发布方说明；样本和转写不提交到仓库。

对照用的 base/small 是可选手动下载的社区转换权重，**不在本项目 `script/models.json` 的固定安装清单里，也不是预装或默认模型**。下载来源及当前校验值如下（`config.json` SHA256 是按该固定版本文件实算，模型权重 SHA256 是该版本 Hugging Face LFS 元数据与实际文件校验值）：

| 模型 | 固定版本及来源 | `config.json` SHA256 | `weights.npz` SHA256 |
| --- | --- | --- | --- |
| base | [mlx-community/whisper-base-mlx @ 1e3e249](https://huggingface.co/mlx-community/whisper-base-mlx/tree/1e3e249fb8d01c655324bd6841b1deadffd6d04c) | `737220a6d958b3ad48e78f840fa991556266983c84ea2ca40e413389c62e4c2f` | `2f57d5f3ef473054c638961f90716f4ee415e8108de81313eccb2c5fd62eff0b` |
| small | [mlx-community/whisper-small-mlx @ 45f3915](https://huggingface.co/mlx-community/whisper-small-mlx/tree/45f3915923c7a79a5a5b5a7d909d39aeb0e5630e) | `e8f58e638208af66d5d5d67801259dc7a12d199e971967a9f9d33a8e3635668e` | `55b6674c9b339702d486e2b1573839a66f8ec8f821ed2886993ef717a86b09f5` |

例如，以下命令在项目根目录**新建独立目录**下载 base，验证两个文件后才用它运行先前样本；先将 `sample_audio` 设为上一节输出的样本路径，或你自行指定的音频路径。下载失败或校验失败会停止，已创建的目录会保留以供检查，不覆盖已有模型：

```sh
(
set -eu
sample_audio="/absolute/path/to/jfk-commons-excerpt.wav"  # 改为上一节输出的实际路径
mkdir -p .local
model_dir="$(mktemp -d "$PWD/.local/whisper-base.XXXXXXXX")"
model_url="https://huggingface.co/mlx-community/whisper-base-mlx/resolve/1e3e249fb8d01c655324bd6841b1deadffd6d04c"
curl -fsSL "$model_url/config.json" -o "$model_dir/config.json"
curl -fsSL "$model_url/weights.npz" -o "$model_dir/weights.npz"
(cd "$model_dir" && printf '%s  %s\n' \
  737220a6d958b3ad48e78f840fa991556266983c84ea2ca40e413389c62e4c2f config.json \
  2f57d5f3ef473054c638961f90716f4ee415e8108de81313eccb2c5fd62eff0b weights.npz | shasum -a 256 -c -)
.venv/bin/mcpm audio "$sample_audio" \
  --whisper-model "$model_dir" --language en --output-dir .local/validation/human-speech/base-recheck --no-summary
printf '已校验模型目录：%s\n' "$model_dir"
)
```

若要运行 small，请使用表中固定版本及两个 SHA256 执行同样校验，并显式传入其本地路径。切换模型后请重新检查实际音频，不要把本节输出当作质量担保。项目仍保留较小的 tiny 演示配置；模型选择应按你的语言、准确性、运行时长和磁盘空间自行评估。

### large-v3-turbo 对同一段真实人声的验证（2026-11-12）

在同一 Apple Silicon 16 GB Mac、同一个 JFK 20 秒片段上，额外运行一次社区 MLX 转换的多语言 `whisper-large-v3-turbo`，命令仍使用 `--language en --no-summary`，**没有运行 MiniCPM 摘要**。权重约 1.50 GiB；对于此前对照的几个词，本次正确识别了 “solemn oath”、 “forebears”（与参考 “forbears” 为不同拼写）和 “mortal”。先前 tiny/base/small 在这些词上各有误识，详见上表。时间戳相对截取片段，末段止于约 19.96 秒。

`/usr/bin/time -l` 测得本次命令墙钟时间约 3.09 秒、maximum resident set size 约 0.98 GiB、peak memory footprint 约 2.28 GiB。这是一次运行，包含模型加载与音频解码，机器可能同时有其他程序运行；指标不构成严格性能对比，也不能推出其他机器的内存需求。**单一英文历史演说片段结果不能证明中文、嘈杂音频、多人或真实会议质量**；转写和后续摘要仍需对照录音。项目保留 tiny 作为演示配置，不自动下载或切换更大的模型。

这次权重来自 [mlx-community/whisper-large-v3-turbo 固定版本 a4aaeec](https://huggingface.co/mlx-community/whisper-large-v3-turbo/tree/a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb)，不在本项目的固定安装清单内。`weights.safetensors` 字节数为 `1613977612`，SHA256 为 `951ed3fc1203e6a62467abb2144a96ce7eafca8fa77e3704fdb8635ff3e7f8a6`（与该固定版本的 Hugging Face LFS 元数据一致）；`config.json` SHA256 为 `b34fc29e4e11e0a25e812775dd67f4dd16fc2c8eb43d28ae25ff7d660ecb6379`，并与对应 Git blob SHA1 `6ac9a52a28f70a2e5681c250a470eca6e9c8cc3e` 核对。来源页面未明确列出该转换仓库的许可标识；使用前请核查原模型和转换权重各自条款，不因为本项目 MIT 许可证就推定其授权范围。

如果自行复现，下例创建全新目录，先校验再用**你已准备好的**音频，不覆盖现有权重；下载约 1.61 GB：

```sh
(
set -eu
sample_audio="/absolute/path/to/jfk-commons-excerpt.wav"  # 改为上文生成的实际路径
mkdir -p .local .local/validation/human-speech
model_dir="$(mktemp -d "$PWD/.local/whisper-turbo.XXXXXXXX")"
run_dir="$(mktemp -d "$PWD/.local/validation/human-speech/turbo.XXXXXXXX")"
model_url="https://huggingface.co/mlx-community/whisper-large-v3-turbo/resolve/a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"
curl -fsSL "$model_url/config.json" -o "$model_dir/config.json"
curl -fsSL "$model_url/weights.safetensors" -o "$model_dir/weights.safetensors"
(cd "$model_dir" && printf '%s  %s\n' \
  b34fc29e4e11e0a25e812775dd67f4dd16fc2c8eb43d28ae25ff7d660ecb6379 config.json \
  951ed3fc1203e6a62467abb2144a96ce7eafca8fa77e3704fdb8635ff3e7f8a6 weights.safetensors | shasum -a 256 -c -)
/usr/bin/time -l .venv/bin/mcpm audio "$sample_audio" \
  --whisper-model "$model_dir" --language en --output-dir "$run_dir" --no-summary
printf '模型目录：%s\n结果目录：%s\n' "$model_dir" "$run_dir"
)
```

本机本次原始结果存于 `.local/validation/human-speech/turbo-eval.3tG0GedM/`，模型存于 `.local/whisper-turbo.fzKzRgya/`，都被 Git 忽略；检查完后可自行保留或清理。下载和校验失败时新建目录会保留供排查，脚本不会覆盖已有模型或录音。
