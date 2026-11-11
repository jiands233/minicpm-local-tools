# 用 MiniCPM 系列本地小模型做实用小工具：五个方向同类项目调研

- 调研日期：2026-11-12
- 时区：凡未另行标明的时间，均为 Asia/Shanghai（UTC+8）。GitHub 的 `pushed_at` 等带 `Z` 的时间已换算。
- 星标与最近推送：来自 GitHub REST API，查询时刻约为 2026-11-12 01:00–01:05（Asia/Shanghai）。星标会变动，此处只记录当时读到的数字。
- “最近更新”一律采用仓库的最近 **git push** 时间（`pushed_at`），不用 `updated_at`（后者会因加星等非代码活动而变动）。
- 范围：只读调研，未对任何外部仓库发 issue/PR，也未做实现。
- 链接：正文列出的主链接均在本轮用 HTTP 请求核实为可访问（最终状态码 200）。未列入已 404 的仓库（例如 `irachrist1/daylens`）。
- 受众背景：D（石珅，GitHub `jiands233`），macOS 用户，大二，希望做懂技术的 AI 产品经理。

## 如何区分事实与推测

- **事实**：来自本轮打开或请求过的仓库/文档/产品页，或 GitHub API 返回的字段。每条尽量带链接。
- **推测**：市场空档是否真能转化、MiniCPM 在某一任务上是否优于 Qwen / Apple Intelligence、一周能否做完、用户是否买单。文中用“推测”标明。
- 未实测：本轮没有在 Mac 上实际跑模型或安装这些 App，因此“Mac 上好不好用、延迟多少、OCR 准不准”一律不当作事实。

---

## MiniCPM 在 Mac 上的运行方式（带来源）

当前官方在推的主力是 **MiniCPM5**（文本，1B / 2B）和 **MiniCPM-V**（多模态，本轮文档可见 4.6 / 4.7），以及专用的 **MiniCPM-OCR 1.0**。MiniCPM4 / MiniCPM4.1 仍有历史权重（官方 README 仍列出 MLX 等格式），但新工具更合理的默认是 MiniCPM5 + 按需的 V / OCR。

### MiniCPM5（文本：改写、摘要、命令生成、每日回顾）

官方部署路由写明：Apple Silicon 笔记本上，**最省事用 Ollama，最快用 MLX**。来源：[OpenBMB/MiniCPM 部署路由 Skill](https://github.com/OpenBMB/MiniCPM/blob/main/skills/minicpm5-deploy/SKILL.md)。

| 方式 | 官方怎么说 | 来源 |
| --- | --- | --- |
| Ollama（推荐入门） | 吃与 llama.cpp 相同的 GGUF。官方 cookbook 给出 macOS 上 `brew install ollama`、用 `MiniCPM5-2B-Q4_K_M.gguf`（约 1.56 GB，官方称适合笔记本）写 Modelfile 再 `ollama create` 的步骤。也提供 OpenAI 兼容接口 `http://localhost:11434/v1`。 | [docs/deployment/ollama.md](https://github.com/OpenBMB/MiniCPM/blob/main/docs/deployment/ollama.md) |
| Ollama 官方库 | 本轮打开 [ollama.com/openbmb/minicpm5](https://ollama.com/openbmb/minicpm5)，可 `ollama run openbmb/minicpm5`。页面展示的是 **MiniCPM5-1B** 量化（`q4_K_M` 约 688 MB，上下文 128K）。**2B 仍建议按官方 cookbook 用 GGUF 自建 Modelfile**，不要默认库里已经有 2B。 | 上述 Ollama 库页面；对照官方 ollama.md |
| MLX（Apple Silicon 上官方称更快） | `pip install "mlx-lm>=0.31"`，可用预转换仓库 `openbmb/MiniCPM5-2B-MLX` 或 `openbmb/MiniCPM5-1B-MLX`，也可用 `mlx_lm.server` 开 OpenAI 兼容服务。官方提醒：`mlx-lm < 0.31` 有 eos / lm_head 问题。 | [minicpm5-deploy-mlx Skill](https://github.com/OpenBMB/MiniCPM/blob/main/skills/minicpm5-deploy-mlx/SKILL.md) |
| llama.cpp | 官方提供 GGUF（F16 / Q8_0 / Q4_K_M），cookbook 指向 `docs/deployment/llama_cpp.md`。Ollama 背后也是这一路。 | [MiniCPM README 部署表](https://github.com/OpenBMB/MiniCPM) |
| LM Studio | 官方称可用同一套 GGUF 或 MLX，带桌面 GUI 和 OpenAI server。 | 同上；`docs/deployment/lmstudio.md` |

官方还提醒：MiniCPM5-2B 默认 Think 模式采样为 `temperature=1.0, top_p=0.95`；MiniCPM5-1B 可用 `enable_thinking=false` + `temperature=0.7` 走 No-think。工具里如果要低延迟，应显式关掉思考，否则输出会变慢。来源：同一部署路由 Skill。

MiniCPM5 **不是**“只支持中英文”的模型。官方把它定位为通用端侧 LLM，并未给出 OCR 那种语言白名单。本报告只在 MiniCPM-OCR 上使用“官方只支持中英文”这一限制。

### MiniCPM-V（截图、图片理解）

- Ollama：MiniCPM-V 4.6 已进入官方库，文档写可用 `ollama run openbmb/minicpm-v4.6`（需较新的 Ollama）。来源：[OpenBMB 知识库 MiniCPM-V 4.6 Deployment](https://openbmb.cn/docs/en/guides/minicpm-v/minicpm-v-4.6/deploy)，库页 [ollama.com/openbmb/minicpm-v4.6](https://ollama.com/openbmb/minicpm-v4.6) 本轮可访问。
- llama.cpp：同一篇部署文档写明需较新版本（检索摘要称 b9049 或更新；具体版本以该文档当时写法为准）。
- MLX：社区/文档路径是 `mlx-vlm` + `mlx-community/MiniCPM-V-4.6-5bit` 一类转换权重，不是 MiniCPM5 那种官方 `mlx-lm` 文本路径。本轮未在官方 MiniCPM-V README 里把 MLX 写成与 Ollama 同等的“一等官方入口”，用时要按部署文档核对。
- MiniCPM-V 的语音能力在官方 README 里写的是 **中英双语**实时语音；这与 OCR 的“中英文文档”不是同一句话，也不能据此推断 V 的视觉 OCR 语言范围。视觉语言覆盖本轮未找到同等明确的白名单，标为未知。

### MiniCPM-OCR 1.0（扫描件 / 截图转文字或结构化结果）

官方明确：

- **主要语言是中文和英文**（Hugging Face 模型卡写 *Primary languages: Chinese and English*；仓库 README 写 *parses Chinese and English documents and PDFs*）。
- 官方列出的推理后端是 **vLLM、SGLang、llama.cpp、Ollama**，并提供 GGUF。来源：[openbmb/MiniCPM-OCR-1.0](https://huggingface.co/openbmb/MiniCPM-OCR-1.0)、[OpenBMB/MiniCPM-OCR](https://github.com/OpenBMB/MiniCPM-OCR)。
- 整页解析的完整流水线是两段：本地 PP-DocLayoutV3 做版面（官方 SDK 环境依赖 PaddlePaddle / PaddleX），再把裁块送到 OCR 推理服务。只用整页 `Text Recognition:` 可以得到纯文本，但官方写明完整版式/表格/公式需要按区域类型换提示词，并由 SDK 组装。
- 官方部署列表里 **没有 MLX**。若在 Mac 上走官方路径，应优先 llama.cpp 或 Ollama 的 GGUF，而不是假设有官方 MLX 包。

**风险（事实 + 推测）：** 完整 SDK 流水线在没有 NVIDIA GPU 的 Mac 上，版面检测要走 CPU，速度和依赖（Paddle）可能比“只丢一张图给 llama.cpp”重得多。这是推测，本轮未实测。德语等非中英文扫描件，按官方语言范围不应指望 MiniCPM-OCR 1.0。

---

## 有没有已经用 MiniCPM 做这五类事的项目？

本轮检索（GitHub 仓库搜索、Web 检索、官方 README 的相关项目列表）**没有发现**一个成熟、仍在维护、以 MiniCPM 为核心、直接对标这五个方向的成品工具。这不是“证明不存在”，只是本轮没找到。

找到的相近项：

| 项目 | 说明 | 与五个方向的关系 |
| --- | --- | --- |
| [OpenBMB/MiniCPM-Desk-Pet](https://github.com/OpenBMB/MiniCPM-Desk-Pet)（499★，最近 push 2026-08-18 15:58，AGPL-3.0） | 官方本地桌宠，由 MiniCPM5 驱动。 | 不是剪贴板 / 文件搜索 / 会议 / 浏览回顾 / CLI 助手。 |
| [OpenBMB/MiniCPM-V-Apps](https://github.com/OpenBMB/MiniCPM-V-Apps)（519★，最近 push 2026-10-29 23:10，许可证 API 为 NOASSERTION） | 官方离线多模态 App，目标是 iOS / Android / HarmonyOS。 | 不是 macOS 桌面小工具。 |
| [network-tocoder/MiniCPM5-1B-Tool-Use-case](https://github.com/network-tocoder/MiniCPM5-1B-Tool-Use-case)（36★，最近 push 2026-07-10 02:48） | 社区 demo：计算器工具调用、把自然语言转成终端命令（执行前确认）、会议笔记抽行动项。 | 与方向 3、5 主题相近，但是演示仓库，不是产品。README 对模型谱系的表述前后不一致（标题写 MiniCPM5-1B，正文又写基于 MiniCPM-o 2.6 的社区微调），其中基准数字本报告不采信。 |
| [imanoop7/Ollama-OCR](https://github.com/imanoop7/Ollama-OCR)（2789★，最近 push **2025-03-17** 11:10，MIT） | 用本地视觉模型从图片/PDF 抽文本。被 MiniCPM-V README 列为相关项目，但并非 MiniCPM 专用，且超过一年未 push。 | 与剪贴板截图 / 文档检索的 OCR 部分相邻，不能当活跃竞品。 |
| [tisfeng/Easydict#1398](https://github.com/tisfeng/Easydict/issues/1398) | 2026-11-11 17:26 由 **lottshin** 开的功能建议：让自定义 OpenAI 兼容端点出现在截图 OCR 服务列表，明文写了自托管 MiniCPM-OCR。issue 仍 open，作者表示愿意提 PR。 | 与方向 1 高度重叠。自己再给 Easydict 提同类 OCR 提案会撞车。 |

结论（事实）：MiniCPM 系列目前更像“可接入的本地模型”，而不是已经占领这五类工具入口的品牌。空档在“产品包装”，不在“没人能跑这个模型”。

---

## 方向 1：剪贴板智能处理

复制文字或截图后，用快捷键翻译、改写、抽表格 / 待办，结果回到剪贴板。

### 同类项目

| 名称与链接 | 一句话 | 本地模型 | 开源 / 付费 | GitHub ★ | 最近 push（Asia/Shanghai） |
| --- | --- | --- | --- | --- | --- |
| [Easydict](https://github.com/tisfeng/Easydict) | macOS 划词词典 / 翻译 / OCR App，服务很多，含 Ollama。 | 是，内置 Ollama，也支持苹果翻译和多家云服务。 | 开源，GPL-3.0 | 15,279 | 2026-11-11 23:25 |
| [nextai-translator](https://github.com/nextai-translator/nextai-translator)（原 openai-translator / yetone） | 划词翻译的浏览器插件 + 跨平台桌面端。 | 是，桌面端可配 Ollama；浏览器插件受跨域限制，社区讨论里建议走 OpenAI 兼容接口。 | 开源，AGPL-3.0 | 25,039 | 2026-11-02 15:48 |
| [Bob](https://bobtranslate.com)（仓库 [ripperhe/Bob](https://github.com/ripperhe/Bob)） | 很常用的 macOS 翻译 + OCR 软件，有插件生态。 | 应用本身闭源；社区插件可接 Ollama。 | 闭源付费产品；GitHub 主要是官网/文档仓库，API 未返回 SPDX | 9,758（仓库星标，不等于付费用户数） | 2025-12-30 21:26 |
| [OneClip](https://github.com/One-Clip/OneClip)（产品站 [oneclip.cloud](https://oneclip.cloud)） | 原生 macOS 剪贴板管理，带 OCR、划词翻译、截图，可接 Ollama / LM Studio。 | 是，也可接在线 AI。 | **早期源码 MIT 开源；README 写明当前正式版是商业软件**（数据库存储，功能更完整） | 548 | 2026-11-01 15:53 |
| [Clippy](https://github.com/yarasaa/Clippy) | 开源 macOS 剪贴板管理器：历史、截图编辑、OCR，以及总结 / 翻译 / 改写等 AI 动作。 | 是。README 写 macOS 26+ 默认 Apple Intelligence，也可 Ollama 或云 API。 | README 写 MIT，但 GitHub API 未返回许可证，且 `LICENSE` 文件在 `main`/`master` 的 raw 路径返回 404，**许可证未能在本轮核实** | 69 | 2026-09-08 14:38 |
| [Pebble](https://github.com/gashiartim/pebble) | 菜单栏小工具：全局快捷键把剪贴板文本交给本地 Ollama 改写，结果写回剪贴板。 | 是，只连本地 Ollama，无云回退。 | 开源，MIT | 11 | 2026-04-29 20:52 |

相邻但不作为主竞品写入上表：

- [pot-app/pot-desktop](https://github.com/pot-app/pot-desktop)：19,333★，GPL-3.0，也做划词翻译 + OCR 且支持 Ollama，但仓库已 **archived**，最近 push 2026-07-04 19:01。应视为历史项目，不宜当仍活跃的主竞品。
- [Maccy](https://github.com/p0deje/Maccy)：22,279★，MIT，最近 push 2026-10-27 03:41。剪贴板历史很强，但不是 AI 处理工具。
- Apple Intelligence 写作工具、Raycast AI：系统或商业启动器能力，不是开源 MiniCPM 产品。本轮未核其定价。

### 空档 / 差异化（事实与推测分开）

**事实：** 中文 macOS 用户的“划词翻译 / OCR”已经被 Easydict、Bob、nextai-translator 占得很满，而且 Easydict 已经能接 Ollama。更接近“快捷键改写剪贴板”的开源实现有 Pebble，但星标低、2026-04 之后未见 push。带截图 OCR + AI 的剪贴板管理有 OneClip（正式版商业）和 Clippy（开源但体量小、许可证未核实）。lottshin 已在 Easydict #1398 提出用自定义端点接 MiniCPM-OCR 做截图 OCR，不要再往同一个仓库提同类提案。

**推测中的空档：** 不是再做一款翻译器，而是做“复制截图 / 扫描件 → 结构化结果写回剪贴板”的窄工具：表格转 Markdown、截图待办提取、中英文单据字段抽取（KIE）。这比纯文本改写更吃 MiniCPM-OCR / MiniCPM-V，也和 Easydict 的“查词翻译”不完全重合。前提是诚实写出只支持中英文，并且不要承诺完整版面还原（除非接上官方 SDK 流水线）。

### 1 周最小版本

菜单栏或全局快捷键：若剪贴板是文本，用 MiniCPM5 做翻译 / 改写 / 抽待办并写回剪贴板；若是图片，调用 MiniCPM-OCR（或 MiniCPM-V）做中英文识别，纯文本或简单 Markdown 写回。不做剪贴板历史云同步，不做德语 OCR，不改 Easydict。

### MiniCPM 适配度与风险

- 文本改写 / 翻译：适配度高，MiniCPM5 + Ollama 即可；但这条路上 Qwen 等本地模型同样能用，**品牌差异小**（推测）。
- 截图结构化：适配度最高的落点，也受官方中英文限制，以及 Mac 上官方 OCR 路径是 llama.cpp/Ollama 而非 MLX。完整表格/公式需要版面模型，一周版建议只做整页文本或单区域提示词，并在 README 写清边界。
- 产品风险：和 Easydict / Bob / OneClip 功能表象接近，若讲不清“截图变结构化笔记”的卖点，会被看成又一个翻译器（推测）。

### 是否值得做

**值得做成窄工具，不值得做成通用翻译 / 剪贴板管理器。** 最强参照是 Easydict、nextai-translator、Bob；开源里最接近一周 MVP 形态的是 Pebble。若做，定位应避开 lottshin 的 Easydict 提案，专注截图 / 扫描件进剪贴板。

---

## 方向 2：本地文件夹语义搜索

用自然语言在本地文件夹里找文件，例如“上个月那份课件 PDF”。

### 同类项目

| 名称与链接 | 一句话 | 本地模型 | 开源 / 付费 | GitHub ★ | 最近 push（Asia/Shanghai） |
| --- | --- | --- | --- | --- | --- |
| [Kensaku](https://github.com/yjid/kensaku) | 跨平台本地文件启动器：搜文件名和文件内容，带 OCR，仓库描述写支持语义搜索和 MCP。 | 内容检索和 OCR 在本地。OCR 默认 PP-OCRv6，可选 Indra（多脚本，含 CJK）或 Tesseract；Intel Mac 回退 Tesseract。本轮 README **未写 Ollama / MiniCPM**。视觉搜索在 README 里标明是 beta，且尚未进入搜索结果。 | 开源，MIT；安装包尚未代码签名 | 1,640 | 2026-11-10 22:06 |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | 本地优先的文档工作区 / RAG / Agent 桌面应用，不是 Finder 式启动器。 | 是，可选 Ollama 等本地后端。 | 开源，MIT；另有官方托管/商业产品，本轮未核价 | 68,180 | 2026-11-11 07:35 |
| [Khoj](https://github.com/khoj-ai/khoj) | 可自托管的“第二大脑”：本地或网上文档问答、Agent、定时任务。 | 是，可接 Ollama 等。 | 开源，AGPL-3.0；官方也提供托管 | 38,108 | 2026-08-02 09:55（代码 push 已约 3 个月） |
| [PrivateGPT](https://github.com/zylon-ai/private-gpt) | 面向本地模型的私有 RAG / 工具 / MCP API 层，开发者框架色彩更重。 | 是，任意 OpenAI 兼容推理服务。 | 开源，Apache-2.0 | 57,633 | 2026-11-11 15:47 |
| [Magpie](https://github.com/newdee/magpie) | Spotlight 风格本地搜索：GitHub star、本地文件、图片、书签；强调不做全盘扫描、端侧运行。 | 仓库描述为 fully on-device。本轮未逐项核实其模型后端清单。 | 开源，MIT | 174 | 2026-11-09 12:28 |
| [Minna](https://github.com/impel-intelligence/Minna)（产品站 [tryminna.com](https://tryminna.com)） | macOS 本地文档搜索库 + 带引用的问答。 | 是：MLX（文档写默认 Qwen3 4B Instruct）、Ollama、Apple Intelligence，也可接云 API。 | 开源，Apache-2.0；安装要求写的是 **macOS 26.0+** | 20 | 2026-09-30 07:46 |

较小或相邻项目（不作为主推）：[Mane](https://github.com/ajagatobby/Mane-mac-app)（40★，最近 push 2026-02-03 05:12，Ollama，之后再无代码活动）、[Sift](https://github.com/richardcsuwandi/sift)（7★）。传统桌面搜索还有 Recoll、商业软件 DEVONthink，本轮未把 Recoll 的 GitHub 镜像核到有效仓库，故不编造星标。

特别说明：Kensaku 于 2026-10-24 才创建，约三周到 1,640★，是本方向里最近、最像“自然语言找文件”的新玩家。README 也写 Windows 实测更多，macOS / Linux 包由 CI 产出，欢迎更多实际使用反馈。

### 空档 / 差异化

**事实：** “和自己的文件聊天”已被 AnythingLLM、Khoj、PrivateGPT 做得很深；“在启动器里搜到文件内容”正在被 Kensaku 快速占据，且已带 CJK OCR。用 MiniCPM 再做一轮通用本地 RAG，正面竞争空间很小。

**推测中的空档：** 不是再做一个启动器，而是很窄的“中英文扫描 PDF / 课堂讲义文件夹”索引：文字层用普通提取，无文字层的页用 MiniCPM-OCR，查询理解用 MiniCPM5，结果能打开原文件并预览命中页。德语讲义按官方 OCR 语言范围做不了，若用户场景依赖德语扫描件，这个方向会先天缺一块。更省力的产品经理做法，也可能是给 Kensaku 这类工具提 MiniCPM-OCR 后端，而不是从零做启动器（这是策略建议，不是已验证的合作机会）。

### 1 周最小版本

只索引用户指定的一个文件夹；支持 PDF 文字层 + 纯文本 / Markdown；对无文字层的中英文 PDF 页调用 MiniCPM-OCR；命令行或极简窗口用自然语言返回路径和片段。不做全盘索引、不做自动整理/重命名、不做通用 Agent。

### MiniCPM 适配度与风险

- MiniCPM5 适合查询改写和短摘要；真正的“语义检索”应交给 embedding 模型（官方 MiniCPM5 不是 embedding 模型）。不要用生成模型去扫全盘。
- MiniCPM-OCR 适合中英文扫描件，但这正是和 Kensaku（PP-OCRv6 / Indra）比较质量的地方。本轮 **没有** 对比两者准确率的实测，不能宣称 MiniCPM-OCR 更好。
- 风险：索引速度、PDF 渲染、权限（文件夹访问）、以及一周内做不出可感知优于 Kensaku / Spotlight 的体验（推测）。

### 是否值得做

**作为通用产品不值得从零做；作为“扫描件文件夹”的窄演示或给现有开源启动器做后端，可以考虑。** 最强同类是 Kensaku、AnythingLLM、Khoj。

---

## 方向 3：会议 / 网课音频本地转写 + 摘要 + 行动项

### 同类项目

| 名称与链接 | 一句话 | 本地模型 | 开源 / 付费 | GitHub ★ | 最近 push（Asia/Shanghai） |
| --- | --- | --- | --- | --- | --- |
| [Meetily](https://github.com/Zackriya-Solutions/meetily)（站点 [meetily.ai](https://meetily.ai)） | Windows / macOS 隐私优先会议纪要：本机转写和说话人分离，不往会议里加 bot，可替代 Granola / Otter 一类产品。 | 转写走本机 Whisper / Parakeet；摘要可接 Ollama 等本地或自定义 API。文档：[Custom APIs & Local LLMs](https://docs.meetily.ai/integrations/custom-apis-and-local-llms) | 开源，MIT | 32,632 | 2026-11-11 18:38 |
| [ownscribe](https://github.com/paberr/ownscribe) | 本地优先的会议转写 + 摘要 CLI；macOS 14.2+ 可用系统音频采集。 | WhisperX 转写；摘要默认可下本地 Phi-4-mini，也可 Ollama / LM Studio / OpenAI 兼容服务。 | 开源，MIT | 111 | 2026-08-14 22:59 |
| [Scripta](https://github.com/thehwang/Scripta) | 原生 macOS 双通道会议转写（麦克风 + 系统音频）和本地摘要。 | 麦克风走 whisper.cpp（Metal）；系统音频走 Apple 本机语音识别；摘要走 Ollama。 | 开源，MIT | 19 | 2026-09-29 08:16 |
| [minute](https://github.com/mraza007/minute) | 离线 macOS 会议纪要：检测会议、采系统音频、转写、摘要，并可向笔记提问。 | Whisper + 本地 LLM，无云账号。 | 开源，MIT | 21 | 2026-11-11 14:31 |
| [Buzz](https://github.com/chidiwilliams/buzz) | 在个人电脑上离线转写和翻译音频，基于 Whisper。 | 本地 Whisper。本身重点是转写，不是完整“会议纪要产品”。 | 开源，MIT | 22,636 | 2026-11-09 15:32 |
| [Handy](https://github.com/cjpais/Handy) | 免费开源、可扩展的离线语音转文字应用。 | 完全离线。更偏听写/听写输入，不是会议纪要套件。 | 开源，MIT | 38,408 | 2026-11-11 18:11 |

相邻： [OpenWhispr](https://github.com/OpenWhispr/openwhispr)（11,294★，最近 push 2026-11-12 00:49）偏听写；[Vibe](https://github.com/thewh1teagle/vibe)（8,070★，最近 push 2026-10-30 08:33）偏本地转写；[Prismical](https://github.com/amicalhq/prismical)（133★）。商业侧有 MacWhisper、SuperWhisper、Granola 等，本轮未在各家官网逐项核对价格，故不写具体价目。社区 demo 见上文 `MiniCPM5-1B-Tool-Use-case` 的 `meeting_notes.py`（对已有文本抽行动项，不做转写）。

### 空档 / 差异化

**事实：** MiniCPM 系列不是语音识别模型。完整链路一定是 Whisper / Parakeet / 系统语音识别转写，再用 MiniCPM5 做摘要和行动项。这条链路 Meetily 已经以开源形式做得很大，并且官方支持 Ollama。ownscribe、Scripta、minute 也在做同一件事。再做一个通用“本地会议纪要 App”，会正面撞上 Meetily。

**推测中的空档：** 只可能出现在非常窄的场景，例如中文网课 / 课程录音 → 结构化复习笔记并写入 Obsidian，而不是对标 Zoom 会议产品。即便如此，用户也可以在 Meetily 或 ownscribe 里把摘要模型换成 MiniCPM5，不一定需要新 App。

### 1 周最小版本

CLI：输入一段本地音频（或一次系统音频录制），whisper.cpp 转写，MiniCPM5 输出摘要 + 行动项 Markdown。不做人声分离的自研、不做自动入会 bot、不做跨会议搜索。

### MiniCPM 适配度与风险

- 摘要 / 行动项：MiniCPM5 用得上，但是可替换后端，差异化弱。
- 转写质量、系统音频权限、中英混合网课识别，取决于 Whisper 而非 MiniCPM。
- 长会议超过小模型上下文时需要切分；MiniCPM5 官方支持长上下文，但本轮未实测一小时转写的摘要质量。
- 产品风险：通用市场上已经有星标上万的开源方案（事实）；个人课代表演示仍可做（推测）。

### 是否值得做

**不建议作为独立产品从零做。** 最强同类是 Meetily，其次是 ownscribe（CLI 形态最接近一周作业）和 Scripta。若只是自己用，优先在现有工具里接入 MiniCPM5。

---

## 方向 4：浏览历史 / 阅读记录的每日本地回顾

每天把读过的网页标题和摘要压成一页“今天看了什么”，数据不出本机。可与 Obsidian 习惯衔接。

### 同类项目

| 名称与链接 | 一句话 | 本地模型 | 开源 / 付费 | GitHub ★ | 最近 push（Asia/Shanghai） |
| --- | --- | --- | --- | --- | --- |
| [ActivityWatch](https://github.com/ActivityWatch/activitywatch)（站点 [activitywatch.net](https://activitywatch.net)） | 成熟的开源自动时间追踪，记录活动应用、窗口标题、浏览器页面，跨平台、本地优先。 | 核心追踪不需要模型。官方文档有用 Agent / AI 做活动摘要的示例，可走包含 Ollama 兼容端点的本地接口。来源：[ActivityWatch with agents and AI](https://docs.activitywatch.net/en/latest/examples/agents-and-ai.html) | 开源，MPL-2.0 | 19,597 | 2026-11-10 00:13 |
| [screenpipe](https://github.com/screenpipe/screenpipe)（站点 [screenpipe.com](https://screenpipe.com)） | 持续记录屏幕和音频、可搜索的“电脑历史”，常被拿来对标已退出或收缩的 Rewind / Limitless。 | 可用本地或云模型。默认本地存储；可选云和团队功能会离机。 | **source-available，非标准开源许可证**：个人非商用可用，商用需许可；正式桌面构建另有付费条款。README 写 production app 在付费墙后。 | 22,346 | 2026-11-12 00:34 |
| [Karakeep](https://github.com/karakeep-app/karakeep) | 可自托管的“把一切收藏起来”应用（链接、笔记、图片），带 AI 自动标签和全文搜索。 | 可接本地或云模型做标签等。 | 开源，AGPL-3.0 | 30,460 | 2026-11-10 15:07 |
| [Obsidian Daily Digest](https://github.com/brianruggieri/obsidian-daily-digest) | Obsidian 插件：读取浏览器历史、搜索词、git 提交、Claude Code / Codex 会话，生成 AI 日总结笔记。 | 是，支持 Ollama / LM Studio / 任意 OpenAI 兼容服务，也可只用无 AI 的活动日志；亦可选 Anthropic。 | 开源，MIT | 2 | 2026-09-24 01:06 |
| [PrivateContext](https://github.com/OpenSourceRulesz/PrivateContext)（[PyPI privatecontext 0.6.4](https://pypi.org/project/privatecontext/)） | 本地电脑日记：记活动窗口、URL、点击、空闲，写入 SQLite；可选 Ollama 把一天写成几条回顾。 | 核心日志不需要模型；摘要可选本地 Ollama（文档示例为小模型如 qwen2:1.5b）。 | 开源，MIT | 0（仓库星标）；以 PyPI 发布为准 | 2026-10-21 22:52 |
| [OpenOwl](https://github.com/ranjeethpt/openowl) | 本地优先的 Chrome 扩展，记录浏览器工作内容，可写 standup、日总结等。 | 本地存储；AI 需用户自配提供方（文档写可本地）。体量很小，最近 push 已半年。 | 开源，MIT | 3 | 2026-05-02 20:43 |

相邻：[Memex](https://github.com/WorldBrain/Memex)（4,723★，最近 push **2025-12-02** 10:31，书签/标注，已较久未 push）。本轮检索还看到有文章称 Rewind 已关停、Limitless 对新增计划收缩；这来自第三方评述，**本轮未打开这两家官方停运声明**，只作为待核实的市场背景，不当作已确认事实。

Karakeep 更像主动收藏，不是“把今天所有浏览压成一页”。ActivityWatch / screenpipe 更重，是活动采集平台。和 D 的 Obsidian 习惯最接近的现成开源是 Daily Digest，但几乎没有社区星标。

### 空档 / 差异化

**事实：** 重型“记录你的屏幕”已经被 screenpipe（源码可得但许可证受限）和 ActivityWatch（真正开源）覆盖。轻量“读浏览器 History SQLite → 本地模型写日报 → 丢进 Obsidian”的成品很少，现成插件星标极低。不需要连续录屏，一天的数据量也远小于 screenpipe。

**推测中的空档：** 这是五个方向里比较适合做作品集的切口：故事清楚（隐私、本地、每日一页）、一周能做完演示、能接到 D 已有的笔记习惯。差异化不在模型本身（MiniCPM5 在这里同样可被 Qwen 替换），而在产品约束：只读历史库、清洗敏感 URL、不上传、输出稳定的日记模板。风险是用户第二天就不想再看日报，留存难验证。

### 1 周最小版本

只读 Safari 或 Chrome 的本地 History（先复制再查，避免锁库）；按天聚合标题和域名；用 MiniCPM5 生成一页中文 Markdown（主题、关键页面、可选行动项）；写入指定文件夹或 Obsidian 仓库。不做屏幕录像、不抓页面全文（避免版权和体积）、不追踪密码框、不提供云同步。

### MiniCPM 适配度与风险

- 只需文本模型，MiniCPM5-1B/2B + Ollama 足够匹配任务形态（推测质量，事实是技术可接）。
- 浏览器历史只有标题和 URL，没有正文，摘要容易空泛或臆造 —— 必须在提示词和产品上禁止“编造没看过的内容”，最好同时输出“未总结、仅列表”模式。
- macOS 上读取 Chrome/Safari 历史涉及文件权限和库拷贝，Safari 与 Chrome 路径不同。
- 许可证与隐私：只读本机历史可以，但若以后扩展到页面正文抓取，要单独评估。

### 是否值得做

**作为作品集小工具，五个方向里最值得认真考虑之一。** 最强参照是 ActivityWatch（采集基础设施）和 screenpipe（重型记忆）；最接近目标形态但几乎无用户的是 Obsidian Daily Digest。不要去做第二个 screenpipe。

---

## 方向 5：命令行自然语言助手

用自然语言生成或解释 shell 命令，执行前确认，可离线。

### 同类项目

| 名称与链接 | 一句话 | 本地模型 | 开源 / 付费 | GitHub ★ | 最近 push（Asia/Shanghai） |
| --- | --- | --- | --- | --- | --- |
| [ShellGPT (sgpt)](https://github.com/TheR1D/shell_gpt) | 很常用的命令行 LLM 生产力工具，支持 shell 模式。 | 可通过 LiteLLM 接 Ollama（官方 Wiki 有配置说明）。 | 开源，MIT | 12,309 | 2026-07-02 14:03 |
| [aichat](https://github.com/sigoden/aichat) | 一体化 LLM CLI：聊天、REPL、RAG、工具，以及 `-e/--execute` 的 Shell Assistant，适配当前 OS 和 shell。 | 是，官方支持 Ollama 等。 | 开源，Apache-2.0 | 10,562 | 2026-02-23 19:16（之后较长时间无 push，但项目仍被广泛使用，星标在涨） |
| [llm](https://github.com/simonw/llm)（文档 [llm.datasette.io](https://llm.datasette.io)） | Simon Willison 的通用命令行 LLM 工具，插件生态很大。 | 是，可通过插件接 Ollama 等本地模型。更偏通用调用，不是“专用 nl2sh 产品”。 | 开源，Apache-2.0 | 12,752 | 2026-11-12 01:01 |
| [open-codex](https://github.com/codingmoh/open-codex) | 受 Codex 启发的开源命令行助手，可本地跑，自然语言生成 shell 命令，执行前确认。 | 是，可纯本地或 `--ollama`。 | 开源，MIT | 695 | 2026-10-21 06:06 |
| [Open Interpreter](https://github.com/openinterpreter/openinterpreter) | 能在本地写代码、操作电脑的 coding agent，能力远大于“生成一条命令”。 | 面向开放模型；具体默认模型随项目演进，本轮以仓库描述为准。 | 开源，Apache-2.0 | 68,862 | 2026-11-11 11:03 |
| [pls](https://github.com/salvy9978/pls) | 在终端用自然语言说出意图，默认走 Ollama，展示命令并请用户确认后再执行。 | 是，默认 Ollama，也可选云。 | 开源，MIT | 66 | 2026-03-26 06:55 |

相邻：[ykushch/ask](https://github.com/ykushch/ask)（55★，最近 push 2026-02-15 23:09，本地 Ollama，含解释模式和危险命令警告）；[charmbracelet/mods](https://github.com/charmbracelet/mods)（4,519★，MIT，但已 **archived**，最近 push 2026-03-09 23:06）。商业侧有 Warp AI、GitHub Copilot CLI 等，本轮未核价。社区 MiniCPM demo 见 `cli_assistant.py`（同上，演示而非产品）。

### 空档 / 差异化

**事实：** “自然语言 → shell，执行前确认，可接 Ollama”已经被 ShellGPT、aichat、open-codex、pls、ask 反复实现。Open Interpreter 则把问题做成了完整 agent。这是五个方向里开源重复建设最严重的一个。MiniCPM5 官方定位包含 coding agents 和 tool-use，技术上适合当后端，但现有工具几乎都能换模型。

**推测中的空档：** 几乎没有站得住的产品空档。唯一勉强可讲的是“默认模型就是 MiniCPM5、对中文描述 macOS 命令更顺、安装极简”，这更像发行版或配置，而不是新类别。做作品集也可以，但评委很容易问“这和 `aichat -e` 有什么不同”。

### 1 周最小版本

一个 CLI：输入中文或英文意图，调用本地 MiniCPM5，打印将要执行的命令和简短解释，默认不执行，需明确确认；拒绝明显的破坏性命令或至少强警告。不做自主多步 agent，不默认 sudo，不静默执行。

### MiniCPM 适配度与风险

- 技术适配度中等偏好：MiniCPM5 官方强调 tool-use 与代码，Ollama / MLX 都可跑。
- 安全风险高于其他方向：模型幻觉出 `rm -rf` 一类命令是已知问题，所有同类工具都靠“先确认”和部分黑名单，不能当成已解决。
- 产品风险：差异化极弱（事实：竞品密集）。

### 是否值得做

**不建议作为独立产品。** 最强同类是 ShellGPT、aichat，更完整的 agent 是 Open Interpreter。若只想在作品集里证明“会做安全的 nl2sh”，一周可以交作业，但不要指望这是主项目。

---

## 横向对比与推荐

| 方向 | 竞争强度（事实） | MiniCPM 不可替代性（推测） | 一周可演示性（推测） | 与 D 现有叙事的契合（推测） | 综合建议 |
| --- | --- | --- | --- | --- | --- |
| 1 剪贴板 | 高（Easydict / Bob / nextai-translator） | 中高（若做截图结构化，吃 OCR / V） | 高 | 中，需避开 Easydict#1398 | 可做窄工具 |
| 2 文件夹语义搜索 | 很高（AnythingLLM / Khoj / 新晋 Kensaku） | 中（仅扫描件 OCR 有故事） | 中 | 中 | 不宜做通用产品 |
| 3 会议 / 网课纪要 | 很高（Meetily 3 万★ 量级） | 低（只是摘要后端） | 中 | 中低 | 不建议从零做产品 |
| 4 每日本地阅读回顾 | 中（重型工具有，轻量日报几乎没有用户） | 低到中（文本模型可替换，产品形态清楚） | 高 | 高（隐私 + Obsidian） | 优先考虑 |
| 5 CLI 助手 | 极高 | 低 | 高 | 低（和“产品经理作品”关系弱） | 不建议当主项目 |

**整体推荐（推测，供后续一起讨论，不是已经拍板）：**

1. **优先认真评估方向 4。** 故事好讲，一周能出可演示版本，不必和 Meetily / Kensaku / Easydict 硬碰，还能接到笔记习惯。成功标准应是“每天一页、数据不出机、不编造没看过的内容”，而不是模型分数。
2. **方向 1 可以作为第二条，但必须极窄：** 剪贴板里的中英文截图 → 结构化 Markdown / 待办，而不是再做翻译器。不要参与 Easydict 上已有的 MiniCPM-OCR 提案。
3. **方向 2 只适合做成“指定扫描件文件夹的检索演示”，或考虑给现有开源启动器贡献后端，而不是新开一个 Spotlight 替代。**
4. **方向 3 和 5 不建议当主产品。** 自己用可以接现成工具；写进作品集的说服力较弱，除非有非常具体的课程场景数据（且仍受转写质量和命令安全限制）。

模型选择上的务实建议（基于官方文档，不是实测评分）：文本任务默认 **MiniCPM5-1B 或 2B + Ollama**（入门）或 **MLX**（追求速度）；看图用 **MiniCPM-V**；扫描件 / 截图文字用 **MiniCPM-OCR 1.0（llama.cpp 或 Ollama，中英文 only）**。不要在对外说明里把 MiniCPM-OCR 的语言限制套到 MiniCPM5 上，也不要承诺德语扫描件。

---

## 附录：可直接交给另一个 AI 执行的实现 plan

以下五份 plan 供 D 复制给 ChatGPT（或其他实现用 AI）使用。本轮调研只出计划，不写代码、不在本机实现。执行者应在 macOS 上完成本地、可演示的一周最小版本，并严格遵守“不做什么”。MiniCPM 的运行方式必须按下面写明的官方来源接入，不要自行改成未经验证的后端。

使用时建议把「背景」一并贴给对方，然后只贴需要做的那一份方向 plan。

### 给执行 AI 的共同背景（每份 plan 都适用）

- 用户：D，macOS（按 Apple Silicon 规划；若实际是 Intel，必须在开始时说明并改用 llama.cpp/Ollama，不要用 MLX）。
- 目标不是做平台级产品，而是一周内可演示、可讲清楚边界的本地小工具，用于学习和技术产品经理作品集。
- 模型默认本地，数据默认不出本机。不要添加云 API 作为默认定。
- MiniCPM-OCR 1.0 官方主要语言是中文和英文，不得宣称支持德语或其他未在官方文档出现的语言。
- MiniCPM5 是通用文本模型，不要写成“只支持中英文”。
- 不要向 Easydict 提交与 issue #1398 重复的 MiniCPM-OCR 提案（已有人在做）。
- 交付：可运行的最小工具、一份简短 README（中文，含安装、限制、模型来源链接）、以及 3–5 条真实演示例子的说明。不要编造评测数字。
- 安全：任何可能改动用户文件、执行 shell、删除数据的操作，必须先预览再确认；默认只在用户指定的目录里工作。

---

### Plan A · 方向 1：剪贴板智能处理（窄工具：文本改写 + 截图转结构化文本）

**目标与用户**

做一个 macOS 菜单栏或全局快捷键工具：用户复制一段文字或一张截图后按下快捷键，本地模型处理后把结果写回剪贴板，用户再普通粘贴即可。目标用户是经常处理中英文聊天记录、截图、单据和待办的个人用户（首先是 D 自己）。卖点不是“又一个划词翻译器”，而是“剪贴板里的内容变成可粘贴的结构化结果，且不出本机”。

**1 周最小版本范围**

做：

- 全局快捷键（可配置）读取当前剪贴板。
- 文本：至少三种动作——中英互译、改写得更简洁、提取待办列表。结果写回剪贴板。
- 图片：将剪贴板中的图像发给 MiniCPM-OCR 1.0（整页或单图 `Text Recognition:`），得到中英文纯文本或简单 Markdown，写回剪贴板。若时间允许，增加一个“提取待办”动作（对 OCR 文本再走 MiniCPM5，或对图片走官方 KIE 提示词，二者选一并在 README 写清）。
- 菜单栏可看到当前动作、失败原因（例如 Ollama 未启动）、以及“只支持中英文图像”的提示。
- README 写明与 Easydict / Bob 的差异，以及不做完整版面还原。

明确不做什么：

- 不做剪贴板历史管理、云同步、iCloud、多设备。
- 不做划词悬浮窗、词典、插件市场。
- 不接 Easydict、不改他人仓库。
- 不做德语或其他非中英文 OCR，不承诺表格/公式与官方完整流水线（PP-DocLayoutV3 + 分区提示词）同等质量。
- 不默认调用任何云模型。

**技术选型（必须按此，并在 README 引用源头）**

- 平台：macOS。UI 优先原生（Swift/SwiftUI）或极薄的菜单栏方案；不要上沉重的 Electron，除非一周内原生方案明显做不完，并在 README 说明原因。
- 文本模型：MiniCPM5-1B 或 2B。入门用 Ollama，来源：[官方 ollama.md](https://github.com/OpenBMB/MiniCPM/blob/main/docs/deployment/ollama.md)。可用库里的 `openbmb/minicpm5`（本轮页面为 1B）；若用 2B，按该文档用 GGUF 自建 Modelfile。若已确认是 Apple Silicon 并追求更低延迟，可用 MLX + `mlx_lm.server`，来源：[minicpm5-deploy-mlx](https://github.com/OpenBMB/MiniCPM/blob/main/skills/minicpm5-deploy-mlx/SKILL.md)，注意 `mlx-lm>=0.31`。低延迟场景应关闭 Think（1B 可用 `enable_thinking=false` 与官方建议的采样参数）。
- 图像：MiniCPM-OCR 1.0，官方后端为 llama.cpp 或 Ollama（以及 vLLM/SGLang，个人 Mac 不必上）。来源：[Hugging Face 模型卡](https://huggingface.co/openbmb/MiniCPM-OCR-1.0)、[OpenBMB/MiniCPM-OCR](https://github.com/OpenBMB/MiniCPM-OCR)。不要把官方未列入的 MLX 当成默认路径。一周版用单图识别，不强制上 PP-DocLayoutV3 完整 SDK。
- 若 OCR 服务未就绪，工具应失败得清楚，而不是 silently 改走云。

**分步任务清单**

1. 确认机器为 Apple Silicon 还是 Intel，按上面选型装好 Ollama 或 MLX，跑通 MiniCPM5 的一次本地 chat（不要编造成功）。
2. 单独跑通 MiniCPM-OCR 1.0 对一张中文截图和一张英文截图的识别；记下启动方式，写入 README。
3. 实现剪贴板读写与全局快捷键，先做“原样回写”保证快捷键可用。
4. 实现三种文本动作，输出必须是纯文本或 Markdown，便于粘贴。
5. 实现图片动作：检测剪贴板类型，走 OCR，回写文本。
6. 补失败态：服务没开、超时、非中英文字效果差时的提示（提示文案要诚实）。
7. 写 README：安装、快捷键、限制、模型与文档链接、和现有翻译 App 的差异。
8. 准备 3 个真实演示：一段中文聊天改待办、一段英文邮件改简洁中文、一张中文截图转文本。

**验收标准**

- 在未连接外网（本地模型已缓存、服务已启动）时，文本动作和中英文截图动作都能完成，结果可在别的 App 里粘贴。
- 快捷键不会在未确认时修改磁盘上的用户文件；只动剪贴板。
- README 明确写：OCR 官方语言为中英文；完整表格版式不在一周范围内。
- 演示中不出现把失败结果当成成功的情况。

**主要风险**

- 与 Easydict / Bob / OneClip 看起来像重复产品，若演示仍以“翻译”为主，作品集故事会弱。
- MiniCPM-OCR 在 Mac 上的启动和速度未在本调研中实测，可能超过“快捷键即时”的心理预期。
- 完整表格质量依赖官方两段式流水线，一周版可能会让用户失望，必须预先降承诺。
- 剪贴板可能含密码和密钥，历史存储若以后要做，必须先有过滤方案；一周版建议不落盘。

---

### Plan B · 方向 2：指定文件夹的本地语义搜索（扫描件窄范围）

**目标与用户**

做一个只针对“用户指定的一个资料文件夹”的本地检索小工具：用户用自然语言提问（例如“找出那份中文扫描的课程通知 PDF”），工具返回文件路径、页码或片段，并可以打开原文件。用户是需要在自己的课件 / 扫描件 / 笔记里查找资料、又不愿把文件上传的人。不要做 Spotlight 或 Kensaku 的全面替代品。

**1 周最小版本范围**

做：

- 用户选择一个根目录；递归索引其中的 `.pdf`、`.md`、`.txt`（可再加常见办公文本，若时间不够就先这三种）。
- PDF 有文字层则直接提取；若一页几乎无文字，则把该页渲染为图，调用 MiniCPM-OCR 1.0 识别中英文（可先限制：每个文件最多处理前 N 页，避免一周版跑爆）。
- 用本地 embedding 模型（不要用 MiniCPM5 当 embedding）建立检索索引，查询时可用 MiniCPM5 把自然语言问句改写成检索查询，并对命中片段生成一句理由。
- 提供 CLI 或极简窗口列出 Top-K 结果（路径、页码、摘录）。打开文件可用系统默认应用。
- README 写清：不是全盘搜索；德语扫描件不在支持范围；索引会花时间。

明确不做什么：

- 不做全盘扫描、不做菜单栏启动器、不做自动分类/重命名/移动文件。
- 不做通用 RAG 聊天工作区（不要做成 mini AnythingLLM）。
- 不默认索引桌面、下载目录或整个家目录。
- 不声称 OCR 精度超过 Kensaku 的 PP-OCRv6 / Indra（本轮无实测对比）。

**技术选型**

- 平台：macOS，CLI 优先（Python 或 Rust 皆可，以一周内能完成和依赖可安装为准）。界面可极简，不要把时间花在启动器动画上。
- 检索：本地 embedding + 本地向量库（例如 sqlite-vec 或同等本地方案）配合关键词检索更好；生成模型只负责查询理解和一句话解释。
- 文本生成：MiniCPM5 + Ollama 或 MLX，来源同 Plan A 的官方 ollama.md / mlx skill。
- OCR：MiniCPM-OCR 1.0 + llama.cpp 或 Ollama，来源同官方模型卡。一周版可只走整页 `Text Recognition:`，不必上完整版面 SDK。
- PDF 渲染与文字提取用成熟本地库，不要自己解析 PDF 格式。

**分步任务清单**

1. 先在一个很小的样本文件夹（含 1 个文字版 PDF、1 个中文扫描 PDF、几个 Markdown）上跑通提取。
2. 搭索引与查询的最小闭环，暂时只用文字层，确认“自然语言 ≈ 找对文件”这一步成立。
3. 为无文字层的页加上 MiniCPM-OCR；限制页数和并发，避免一次跑完全部历史扫描件。
4. 加上 MiniCPM5 的查询改写和一句话解释；解释必须基于命中摘录，禁止编造文件内容。
5. 加入进度显示和可中断的索引过程；索引数据只写在用户指定的数据目录。
6. 写 README 与 3 个查询演示（成功 2 个、扫描件 1 个）。诚实记录失败例子，如果有。

**验收标准**

- 在样本文件夹上，至少两个文字文档查询能命中正确文件。
- 至少一个中文或英文扫描 PDF（无文字层或文字层几乎为空）能被检索到，且 README 说明所用模型和页数限制。
- 不索引用户未指定的目录；不把文件上传到网络。
- 查询结果都能指向真实存在的本地路径。

**主要风险**

- Kensaku 等通用工具已能搜内容和 OCR，一周版很难在体验上胜出。
- 扫描件 OCR 慢，首次索引可能很长；若演示时临时跑全量会失败。
- 德语或其他非中英文扫描件会失败，若 D 的真实资料以这些语言为主，这个方向不成立。
- “语义搜索”若只做了关键词，应在 README 里如实写，不要夸大。

---

### Plan C · 方向 3：本地音频转写 + 摘要 + 行动项（个人课代表 / 会议 CLI）

**目标与用户**

给 D 自己（以及同类的学生 / 个人会议用户）做一个本地命令行流程：录一段或指定一个音频文件，得到转写稿，以及带行动项的 Markdown 摘要，全部留在本机。这是个人工作流，不是要对标 Meetily 的会议产品。

**1 周最小版本范围**

做：

- 输入：本地音频文件（wav/mp3/m4a 等常见格式）。若时间够，再加“从现在开始录麦克风，Ctrl+C 结束”。系统音频采集（Zoom 对面声音）列为可选，做不完可以不做，但要在 README 说明限制。
- 转写：本地 Whisper（优先 whisper.cpp 或同等可在 Apple Silicon 上跑的 Whisper 实现），输出带时间戳的文本文件。
- 摘要：用 MiniCPM5 生成中文 Markdown，固定结构：一句话概述、关键点、行动项（事项 / 负责人若能从文本判断则填写，否则写“未提及”）、未决问题。
- 长音频按块摘要再合并，避免直接把整场录音塞进一次提示。
- 输出到用户指定目录，文件名带日期。

明确不做什么：

- 不做自动检测并加入 Zoom/Meet 的 bot，不做日历集成，不做跨场次语义搜索。
- 不自研说话人分离（可用现成可选依赖，但不是一周必达）。
- 不把 MiniCPM 当成语音识别模型。
- 不宣称全面超过 Meetily / MacWhisper。

**技术选型**

- 转写：whisper.cpp 或 Mac 上其他成熟的本地 Whisper（转写质量由 Whisper 决定，不由 MiniCPM 决定）。
- 摘要：MiniCPM5-1B/2B，Ollama 或 MLX，来源同官方 MiniCPM 部署文档。长会议建议 No-think 或先短后长，避免思考链拖慢。
- 不要为了这一周去部署 MiniCPM-V 的语音能力来替代 Whisper；官方 V 的语音说明与“会议转写产品”不是同一条成熟路径，一周内风险过高。

**分步任务清单**

1. 选一段不超过 10 分钟的中文或中英混合音频作为黄金样本（真实课程或会议更好）。
2. 单独跑通本地转写，保存原文，人工看一遍错误类型（专有名词、口语）。
3. 用 MiniCPM5 对这份已知转写生成摘要和行动项，检查是否编造了转写里没有的任务。
4. 把“转写 → 切分 → 摘要 → 合并”做成一条命令。
5. 可选：麦克风录制。系统音频若权限或驱动复杂，记录为未完成项，不要强行使用来路不明的虚拟声卡教程去绕过系统安全。
6. 写 README：依赖、语言、不保证说话人、以及与 Meetily 的关系（现成产品更完整，本工具是个人流水线）。

**验收标准**

- 对样本音频，一条命令能产出转写文件和摘要文件。
- 摘要中的行动项都能在转写中找到依据；找不到的必须标“未提及”，不能虚构负责人或截止日期。
- 离线可运行（模型已在本地）。
- README 写清系统音频是否支持。

**主要风险**

- 开源会议纪要市场已被 Meetily 等占据，这个项目的产品价值有限，更像个人脚本。
- 转写错误会直接导致摘要错误，尤其是人名和作业截止日期。
- 系统音频采集在 macOS 上权限复杂，一周可能完不成“录网课对面声音”。
- 长音频的切分摘要可能重复或遗漏，需要最简单的合并规则，而不是再做一个 Agent。

---

### Plan D · 方向 4：浏览历史的每日本地回顾（推荐优先实现）

**目标与用户**

每天（或用户手动运行一次）把当天的本地浏览器历史收成一页中文日记：今天大致看了哪些主题、哪些站点、若干条值得回看的页面。数据只来自本机历史库，用 MiniCPM5 总结，输出到指定文件夹或 Obsidian 仓库。用户是在意隐私、已有笔记习惯、想回答“我今天到底看了什么”的人，首先是 D 自己。

**1 周最小版本范围**

做：

- 支持至少一种浏览器历史：Chrome 或 Safari（能两种更好，但一种加上清晰说明即可）。读取前先把数据库复制到临时文件，避免和正在运行的浏览器抢锁。
- 按自然日聚合：时间、标题、域名、URL。去掉明显敏感模式（例如登录页、重置密码页；可用简单的 URL 规则，不必做完美分类）。
- 两种输出模式：① 仅列表，不经过模型；② 用 MiniCPM5 生成结构化 Markdown（今日标题、3–6 个主题、代表页面、可选“可能的待办”——待办必须能指向具体标题，否则不写）。
- 把文件写到用户指定目录，文件名含日期，便于丢进 Obsidian。
- 可手动指定日期（昨天、某一天）。

明确不做什么：

- 不做屏幕录制、麦克风录音、键盘记录、截屏流（不要做成 screenpipe / Rewind）。
- 不抓取页面正文（一周内既有版权和体积问题，也容易把工具做重）。没有正文时，模型只能基于标题和域名，必须防止编造。
- 不做云同步、不做团队分享、不默认把数据送给任何远程 API。
- 不做跨周自动写年报级别的“人生复盘”。

**技术选型**

- 平台：macOS。实现形态优先 CLI + 一份模板化 Markdown；若有余力再加最简单的“预览后写入”。
- 数据：只读浏览器 History SQLite（Chrome 的 History，Safari 的 History.db）。先拷贝再查询。
- 模型：只需 MiniCPM5 文本。Ollama 入门或 MLX 求速度，来源：官方 [ollama.md](https://github.com/OpenBMB/MiniCPM/blob/main/docs/deployment/ollama.md) 与 [mlx skill](https://github.com/OpenBMB/MiniCPM/blob/main/skills/minicpm5-deploy-mlx/SKILL.md)。小模型即可，官方库中的 MiniCPM5-1B 可以作为默认，以降低延迟。
- 不需要 MiniCPM-OCR 或 MiniCPM-V。

**分步任务清单**

1. 定位本机 Chrome 或 Safari 历史库路径，实现“复制后查询某一天”的只读脚本，先输出原始列表。
2. 设计清洗规则（去重连续刷新、过滤敏感 URL 模式、合并同域名短访问）。把规则写进 README。
3. 实现“仅列表”Markdown 输出，保证没有模型也能用。
4. 设计严格的摘要提示词：只能使用提供的标题列表；不得发明用户没访问过的文章观点；不确定就说不确定。
5. 接入 MiniCPM5，生成模式 ②；保存原始列表和摘要，方便对照。
6. 加入日期参数和输出目录配置；避免覆盖时不留备份（至少拒绝覆盖或写到新文件）。
7. 用 D 自己某一天的真实历史做演示（注意在作品集材料里隐去可能敏感的 URL）。写 README 与隐私说明。

**验收标准**

- 浏览器开着时也能生成当天回顾（因为先复制了数据库）。
- 无模型模式一定可用；有模型模式在本地服务启动时可用。
- 抽查摘要：不出现列表里没有的页面或明显编造的“文章观点”。
- 输出是合法 Markdown，可被 Obsidian 直接打开。
- 文档写清支持哪种浏览器、数据哪些字段被读取、哪些没有（例如没有页面正文）。

**主要风险**

- 只有标题没有正文，摘要可能很空或模型会臆造——这是最大质量风险，必须用“仅列表”模式和严格提示词兜住。
- Safari / Chrome / 多 profile 路径差异，只测一种浏览器时要写清楚。
- 历史里会有隐私页面，作品集截图必须先脱敏。
- 用户可能觉得日报没用；作为作品集要靠“隐私约束和诚实输出”来讲故事，而不是靠功能数量。

---

### Plan E · 方向 5：命令行自然语言助手（仅作练习，不建议当主项目）

**目标与用户**

做一个极简、安全默认的本地 CLI：用户用中文或英文说想做什么，工具给出一条将要运行的 shell 命令和简短解释，只有在用户明确确认后才执行。面向 D 自己在 macOS 终端里查命令。若作为作品集项目，重点应展示“安全默认和可解释”，而不是“又能多一种 chat”。

**1 周最小版本范围**

做：

- 子命令或参数：`生成`、`解释`（解释用户贴过来的现成命令）、`执行前确认`。
- 把 OS、shell、当前工作目录的基本信息（不要扫描整个磁盘）作为上下文发给 MiniCPM5。
- 默认只打印命令，不执行。`--yes` 之类的自动执行开关如果做，也必须排除危险命令。
- 对明显高风险模式（删除、磁盘格式化、改权限、curl 管道进 shell 等）拒绝或强警告。不必追求完整安全模型，但要有明确规则并写进 README。
- 离线：只走本地 MiniCPM5。

明确不做什么：

- 不做多步自主 Agent，不让模型循环执行直到“任务完成”。
- 不默认 sudo，不保存用户的所有命令到云，不读取 ssh 私钥或其他密钥文件作为上下文。
- 不试图替代 aichat / ShellGPT / Open Interpreter。
- 不把“能执行任意命令”当成卖点。

**技术选型**

- 语言：Go、Rust 或 Python 均可，以发行和调用本地 OpenAI 兼容接口方便为准。
- 模型：MiniCPM5-1B/2B，Ollama（`http://localhost:11434/v1`）或 MLX server，来源同官方部署文档。命令生成建议 No-think，减少废话和延迟。
- 不要为这一周微调模型。提示词和校验比模型本身更重要。

**分步任务清单**

1. 接通本地 MiniCPM5，先只要求模型输出单一命令（有格式约束，例如只输出一个代码块）。
2. 实现解析、展示、确认、执行的交互；取消必须是默认安全选项。
3. 实现 `解释` 模式：输入现成命令，输出它会做什么、主要风险。
4. 加入高风险命令规则（黑名单 / 正则），用若干故意危险的输入做测试，确认被拦截或强警告。
5. 补充失败态：模型没开、输出不是合法命令、一次返回了多条命令时的处理（一周版可拒绝多条，要求只生成一条）。
6. 写 README：与 `aichat -e`、ShellGPT 的差异（如果几乎没有功能差异，就在 README 里承认这是练习，不要硬编卖点）。

**验收标准**

- 对 5 个常见需求（查找大文件、查占用端口、批量改后缀、查看磁盘、解释一条 `tar` 命令）能给出可理解的结果；执行只发生在确认之后。
- 至少 3 个危险输入不会被静默执行。
- 断开外网、本地服务已启动时可用。
- 不读取或打印用户的密钥文件内容。

**主要风险**

- 市场高度同质，产品意义弱。
- 模型幻觉造成的破坏性命令是真实安全风险，确认提示必须足够清楚（完整命令可见，不能一闪而过）。
- 中文意图对 macOS 命令的映射可能出错（路径、BSD 与 GNU 差异），解释模式要写明“请先读命令再执行”。

---

## 调研方法与未覆盖项

- 主要来源：GitHub REST API（星标、push 时间、许可证字段）、各仓库 README / 官方部署文档、Hugging Face 模型卡、Ollama 库页、少量产品文档（Meetily、ActivityWatch、screenpipe README）。
- 未做：安装和基准测试、Mac 真机测速、用户访谈、价格表的逐项官网核对、对 Rewind / Limitless 官方关停声明的原文核验。
- GitHub 仓库搜索 MiniCPM 相关名称时，结果以官方模型仓库和桌宠 / 移动端 App 为主，未见对标这五类的成熟第三方产品；不排除有未编入搜索词的小项目。
