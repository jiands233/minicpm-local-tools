# MiniCPM 本地阅读日报 · 投稿草稿

草稿，未提交、未发布。核对日期：2026-11-18（Asia/Shanghai）。最新已推送提交 `0229d67`，工作区含阅读小票排版升级与“今日概览”校准。Chrome 真实 summary 与小票已完成本机计数验证；Safari 非空日期 summary、整机断网（用户暂跳过）以及最终演示素材尚缺，不能称为已完成投稿包。

结构参考 [OpenBMB 官方项目案例投稿说明](https://openbmb.cn/docs/community/minicpm)。

## 1. 名称与简介

**MiniCPM 本地阅读日报（minicpm-local-tools）**：把本机浏览记录整理成可核对的主题日报与阅读小票。

面向想回顾当天访问内容的 macOS 用户。读取用户指定日期的 Chrome／Safari 历史，输出原始标题、脱敏链接和访问次数；可用本地 MiniCPM5-2B 按标题与域名分主题。提供 Markdown、本地 HTML 详单和省略页面明细的分享 HTML。

它整理的是浏览记录，不抓网页正文、不逐页生成摘要，不推断阅读时长、读完程度或用户观点。HTML 可直接本地打开，无需启动网站；分享版主题仍可能透露个人兴趣，需要自行检查。

## 2. 模型与场景

主线只使用 **MiniCPM5-2B Q4_K_M**，通过本地 Ollama 服务进行主题归类。MiniCPM-OCR 1.0 用于仓库的剪贴板／扫描文档实验，不参与阅读日报，也不作为本主线使用 OCR 的证据。

| 环节 | 负责方 |
|---|---|
| 只读历史快照、自然日过滤、URL 规则过滤、同一原始 URL 去重 | 程序 |
| 通用标题进入“标题信息不足，未归类” | 程序 |
| 根据编号、标题、域名分组和命名；详单可选根据抽样非通用标题归纳“今日概览” | 本地 MiniCPM5-2B |
| 校验分组全覆盖、无重复、不越界（必要时拆批重试）；校验概览引用属于抽样记录 | 程序 |
| 从原始记录生成标题、脱敏链接与小票 | 程序 |

客户端限制 loopback 地址、禁用代理与重定向，没有云回退。不能由此证明任意用户自建本地服务不会转发数据；规则过滤也不能保证清除所有隐私。

## 3. 实现过程

分组时模型只接收过滤后的编号、标题和域名，概览仅接收最多 45 条抽样的非通用标题（不含域名），均不接收完整 URL 或正文。分组校验持续失败时停止，不发布半份日报，用户可改用 list 导出原始列表；概览校验失败时保留已通过校验的详单并提示。编号正确只能证明记录存在或完整，不能证明语义正确。

零模型 demo 复用真实历史读取和渲染流程，使用明确虚构的记录与真实模型运行预录的主题和概览，顶部标注来源并执行同等编号校验。本地详单保留页面记录与可点击的概览引用；分享版单独生成，源码不含页面标题、域名、URL 和概览，仅保留日期、计数与主题。

## 4. 结果与效果（仅列有证据项）

| 类型与日期 | 可复现结果 | 命令与证据 |
|---|---|---|
| 合成 demo，2026-11-12／2026-11-18 | 19 个虚构页面，过滤后 18 条记录；其中 2 条通用标题归入未归类。预录分组误将 Python 与海洋内容合并，原样保留；小票详单预录概览基于 16 条非通用标题归纳 4 条内容方向 | `.venv/bin/mcpm history --demo`、`--demo --format receipt`；[样例报告](../examples/reading-demo/sample-report.md)、[PROGRESS 记录](PROGRESS.md) |
| 合成真实模型验收，2026-11-18 | 单独 history 验收通过；登录过滤、查询参数脱敏、重复访问、WAL 读取和模型编号校验断言通过，不代表真实用户分类质量 | `.venv/bin/python script/verify_mvp.py --output-dir .local/acceptance --only history`；本机 `.local/acceptance/mvp-33dsyt13/report.json` |
| 合成概览提示词对照，2026-11-18 | 5 组合成样本对照：初始提示词出现逐字照抄前三条单页标题及穿插样本 JSON 解析失败；仅提交非通用标题的归纳提示词在 5 组样本均通过校验，但混合样本仍漏引 1 条同类记录 | [阅读日报说明](history.md)，本机 `.local/validation/overview-prompts-20261118.json` |
| 合成参数对照，2026-11-13 | 12 次请求均返回非空且未截断；文本两种不带 `reasoning_effort=none` 的组合出现 reasoning，其余未观察到。OCR 无参数基线亦无 reasoning，不能判定参数被识别 | `.venv/bin/python script/check_thinking.py`；[环境、模型与完整对照](models.md)，本机 `.local/acceptance/thinking-gr57kasc/report.json` |
| 自动化测试（非真实用户效果），2026-11-18 | 工作区本地 `pytest` 405 项通过、无跳过；上一版 `1ef3081` 远端四个 CI 环境成功（Ubuntu Python 3.11 为 384 通过、离线 demo 通过） | `.venv/bin/pytest -q -ra`；[CI #20](https://github.com/jiands233/minicpm-local-tools/actions/runs/43208079159) |
| 真实浏览器本机验收，2026-11-17 | 关闭 Chrome 后对 2026-11-16 真实历史一致快照执行 list 与 summary 成功：过滤去重后 334 条，71 个模型主题、2 条标题信息不足，耗时约 95 秒，HTML 含 334 个链接；运行中 Chrome 首次因数据库锁定按预期拒绝；Safari 当前权限下 list 成功但筛选后 0 条；整机断网暂跳过 | [PROGRESS 记录](PROGRESS.md)、[真机验收清单](reading-acceptance.md)；未记录私人标题、域名或 URL，主题语义仍需人工核对 |

历史失败同样保留：长标题批次曾因模型引用不存在编号被拒绝；此前合成验收曾因默认端口服务未运行失败。新验证没有消除这些限制，不能声称分类总是正确或无需本地服务配置。去掉查询参数后的链接也可能无法回到原页面。

## 5. 成果与复现

[GitHub 仓库](https://github.com/jiands233/minicpm-local-tools) · [安装与模型](models.md) · [使用说明](history.md) · [MIT License](../LICENSE)。模型及第三方资料另遵循各自许可证。

安装依赖后执行（首次安装依赖需要网络或已有缓存）：

```sh
.venv/bin/mcpm history --demo
.venv/bin/mcpm history --demo --format receipt --output-dir outputs/submission-demo
.venv/bin/mcpm history --demo --format receipt-share --output-dir outputs/submission-demo
```

demo 本身不调模型、不访问网络。后两条生成独立文件，重复运行时需换目录，避免覆盖既有结果。真实模型对同一合成库的运行方式见 [history.md](history.md)。

| 投稿检查项 | 状态 |
|---|---|
| 仓库、MIT、安装说明、demo | 已有；上一版 CI 已验证 demo |
| CI 徽章 | README 已补，指向现有工作流；上表为固定提交证据 |
| 15–20 秒视频、主视觉图 | 待前端风格更新后用合成数据制作；现有录屏分镜见 [素材说明](assets/README.md) |
| 真实验收 | Chrome 真实历史 list／summary 已记计数；Safari 非空日期与整机断网仍待补测 |
| 表单、X | 未提交、未发布 |

## S2 规则核对与赛道建议

2026-11-13 已从 [官方 S2 专题页](https://openbmb.cn/spark-program)实际引用的 [页面资源](https://openbmb.cn/assets/js/SparkProgramPage-DOOq4KhC.js)核对中文活动文案；静态 HTML 只有概要，以下不是沿用旧交接文档的公开转述。

- 第一阶段页面日期为 **2026-11-02 至 2026-12-13**；页面未给出具体截止时刻和时区。
- 页面分为基础共创与进阶挑战；英文对应 Open Build Track、On-Device Agent Challenge。
- 本季列出 MiniCPM-OCR 1.0 / Jev、MiniCPM-V4.7，并提示使用系列其他模型的项目可在登记表选择“日常赛道”。
- **本主线采用 MiniCPM5-2B，因此建议按日常赛道准备**，这是依据页面规则与现有实现的判断；不把现有阅读日报包装成使用 OCR/V4.7 的进阶 Agent 项目，也不为参赛自动扩充功能。

提交前仍需用户确认：官方登记表是否仍有日常赛道选项、MiniCPM5-2B 的具体填法，以及 S2 第一阶段日期是否适用于日常赛道、截止时刻与时区。尚未进入或提交表单；确认前不写成“已满足 S2 参赛资格”。通用案例征集页的长期开放说明与 S2 的阶段日期应分别看待。

## X 帖草稿（未发布）

> 做了个 macOS 本地阅读日报：把浏览记录整理成主题列表和一张阅读小票。@OpenBMB MiniCPM5-2B 负责分主题，标题和脱敏链接由程序生成；常见“首页”等标题单独列为未归类。主题仍可能分错，需要核对。
>
> 不抓网页正文。不下载模型也能看虚构演示：`mcpm history --demo`
>
> https://github.com/jiands233/minicpm-local-tools

发布时附合成样例视频，保留“虚构记录、预录主题”说明。素材完成后检查实际帖文字数，必要时拆为主帖与演示说明；不填不存在的视频链接。
