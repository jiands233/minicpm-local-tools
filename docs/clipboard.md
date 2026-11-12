# 剪贴板：复制内容 → 本地处理 → 粘贴结果

原生 macOS 菜单栏小工具，支持翻译、简洁改写、待办提取、中英文截图 OCR，以及 OCR 后提取待办。它聚焦把截图或文字变成可粘贴内容，不做 Easydict / Bob 那样的词典、划词翻译或剪贴板历史管理。

## 启动

先按项目 README 安装 Python 环境并启动本地文本 / OCR 服务，然后在项目根目录运行：

```sh
./script/build_and_run.sh
```

构建脚本会把当时的 `MINICPM_BASE_URL`、`MINICPM_MODEL`、OCR / embedding 地址与名称、超时配置存入生成的 App 资源（不进入 Git）。调整这些环境变量后需重新运行脚本，确保菜单 App 使用同一配置。

启动后会打开“MiniCPM 剪贴板”工具面板，展示五个动作、当前状态、快捷键和翻译目标。打开面板不会读取剪贴板或调用模型。点击动作按钮才处理当前剪贴板，成功后可到其他应用粘贴；处理中动作按钮暂时禁用，避免重复提交。

关闭面板后，菜单栏 `CPM` 和全局快捷键继续运行。点击菜单中的“打开工具面板”或重新打开 App 可找回面板。菜单中点击某个动作会立即处理当前剪贴板，并记住它；默认全局快捷键 **Control + Option + C** 执行当前动作，初始动作为“提取待办”。快捷键菜单可切换为 Command + Shift + C 或 Command + Option + C；占用时会显示失败。翻译目标可以切换中文 / English。快捷键通过 Carbon 注册，不依赖键盘监听或辅助功能权限。

处理时显示 `CPM…`，完成后可直接粘贴。模型不可用、超时、内容类型不符时显示原因。 App 的进程超时按 `MINICPM_TIMEOUT` 配置计算：一次请求加 60 秒宽限，截图提取待办需要 OCR 与文本两次请求，允许两倍请求超时加 60 秒；超大配置使用客户端自身的 I/O 超时。处理期间复制了新内容，会拒绝写回并保留新内容。不会自动把处理后的内容粘贴到前台应用。

桥接器只读取当前动作需要的剪贴板类型：文字动作不提取或编码图片，图片动作不读取文字。混合内容中的大图片因此不会阻止文字处理；图片动作仍受 20 MB 限制。更新代码后请重新构建原生程序，使桥接器和 Python 命令保持一致。

Python 调用桥接器前会通过不访问系统剪贴板的协议探测检查版本；旧桥接器或探测失败时会提示重新构建，避免旧程序把新参数当作启动图形界面。2026-11-12 用更新前的本机二进制验证了旧版提示，重新编译后新版探测和独立剪贴板自测通过。

仅构建（不启动菜单程序）：`./script/build_and_run.sh --build-only`。构建产物在 `macos/dist/MiniCPMClipboard.app`，不提交到 Git。App 记录此项目的绝对路径，移动项目后需重新构建。运行入口还支持 `--verify`、`--debug`、`--logs`、`--telemetry`。

## CLI

以下以模块入口说明，项目安装后也可使用统一命令入口：

```sh
# 默认预览，不改剪贴板
.venv/bin/python -m minicpm_tools clipboard todos
# 明确写回（菜单栏操作等价于 --apply）
.venv/bin/python -m minicpm_tools clipboard rewrite --apply
# 文本与图片文件输入不会改动系统剪贴板
.venv/bin/python -m minicpm_tools clipboard translate --language English --text '明天下午请提交报告。'
.venv/bin/python -m minicpm_tools clipboard todos --text '小王明天提交报告，小李周五检查引用。'
.venv/bin/python -m minicpm_tools clipboard rewrite --stdin
.venv/bin/python -m minicpm_tools clipboard ocr --image /absolute/path/screenshot.png
.venv/bin/python -m minicpm_tools clipboard image-todos --apply
```

`--text`、`--file`、`--stdin`、`--image` 互斥，且不能与 `--apply` 同用。默认 CLI 图片动作会读取剪贴板 PNG / TIFF；复制文件图标不等价于复制图片内容。文本输入硬上限为 24,000 字符，桥接图片最多 20 MB；具体模型的上下文可能更小，遇上下文超限请缩短或分段。

## 模型与边界

- 文本使用共享配置的本地 MiniCPM 服务。[MiniCPM 官方 Ollama 部署](https://github.com/OpenBMB/MiniCPM/blob/main/docs/deployment/ollama.md)，[Apple Silicon MLX 部署](https://github.com/OpenBMB/MiniCPM/blob/main/skills/minicpm5-deploy-mlx/SKILL.md)。
- OCR 通过共享客户端连接 MiniCPM-OCR，本项目不回退到云服务。官方主要语言是中文和英文；整图识别不承诺完整版面、表格、公式还原。见 [官方模型卡](https://huggingface.co/openbmb/MiniCPM-OCR-1.0) 与 [官方仓库](https://github.com/OpenBMB/MiniCPM-OCR)。
- `image-todos` 先 OCR 再由文本模型提取待办，不使用未验证的图像字段抽取提示词。
- 不记录剪贴板历史。截图推理需要短暂的 0600 权限临时 PNG，完成或异常后删除。程序崩溃或被强制结束时，系统临时目录可能残留文件；未实现崩溃恢复清理。
- [NSPasteboard changeCount](https://developer.apple.com/documentation/appkit/nspasteboard/changecount) 在原生写回前再核对；系统没有跨进程原子“比较并替换”接口，极小竞态窗口仍存在。
- 本地模型仍可能翻译错误、遗漏待办；重要内容需对照原文。菜单动作直接更新剪贴板，但不修改原文件。

## 验证与演示

自动化测试使用假的模型响应验证分流、失败保护、临时文件删除和写回版本参数，不代表真实模型效果。原生测试在独立命名的 NSPasteboard 上验证文本读写、PNG 读取与冲突拒绝，不接触系统剪贴板：

```sh
macos/.build/release/MiniCPMClipboard --self-test
macos/.build/release/MiniCPMClipboard --self-test-hotkey
.venv/bin/python -m unittest discover -s tests -p test_clipboard.py
```

`--self-test-hotkey` 验证五个菜单动作、Carbon 全局快捷键注册和应用内事件分发；不发送实际键盘输入，不读取或写入系统剪贴板，因此不等同于真实键盘端到端验证。

2026-11-12：原生私有剪贴板自测增加混合文字与图片、超大图片隔离检查；文字读取在同一剪贴板含超大 PNG 数据时成功，图片读取仍拒绝超限。测试没有读取或修改系统剪贴板。

真实模型演示应运行三个案例并检查内容：中文聊天提取待办、英文邮件翻译为中文、中文截图 OCR。模型真实可用性与产物以主 README / 验证记录为准；上述命令是操作示例，不是已完成的模型质量评测。

### 2026-11-12 本机验证记录

在 Apple Silicon 上通过 CLI 调用本地 `minicpm5-2b`（temperature=0）完成以下三个人工编写样例，均退出 0。它们是实际模型输出，不是测试替身；样例不来自用户私有剪贴板，不能据此推断整体准确率。

| 动作 | 输入 | 实际输出与检查 |
| --- | --- | --- |
| 待办 | 小王明天下午提交课程报告，小李周五检查参考文献。我们今天只是讨论了旅游，还没有安排出行。 | 只列出小王、小李的两项任务，未把旅游闲聊加入待办；负责人和时间保留。 |
| 翻译 | Hi team, please send the updated project report by Friday. Thank you. | 大家好，请于周五前发送更新后的项目报告。谢谢。 |
| 改写 | 我想跟大家说一下，我们需要在明天上午十点之前把这个已经讨论过的项目报告提交到课程平台上。 | 我们需要在明天上午十点前提交已讨论的项目报告到课程平台上。 |

原始运行记录保存在本机 `outputs/clipboard/cli-evidence-final.json`（被 Git 忽略）。此前的 1B 与高随机性运行曾漏掉任务、把闲聊列为任务、丢失提交地点；因此当前提示词使用单独的系统指令，并为文字处理固定 temperature=0。2B 默认模型与低随机性减少了这三个样例的问题，仍需人工核对新输入。

Swift release 构建、`.app` 启动存活、7 个 Python 合约测试、原生私有剪贴板测试、Carbon 注册和内部事件分发测试均已通过。CUA 对无窗口菜单栏 App 的访问超时，**菜单视觉表现和物理快捷键端到端尚未验证**。没有为测试修改用户当前剪贴板。截图 OCR 的真实模型样例见项目主验证记录。

独立图片 OCR 实跑：合成中文图片“实验课程通知 / 请在周五下午三点前提交报告。”与合成英文图片“Course notice / Please submit the report by Friday at 3 PM.”均由本地 MiniCPM-OCR 正确识别，原始图片和返回文字保存于 `.local/validation/ocr-zh.*`、`ocr-en.*`。这是单图文字识别验证，不是复杂版面或准确率评测。

### 第二轮原生入口改进

为避免首次启动只出现不易发现的菜单图标，增加了原生工具面板，五个按钮沿用菜单栏的处理流程。状态和当前快捷键会同步显示；关闭窗口不会退出菜单栏程序。未知的旧动作设置回到“提取待办”，越界快捷键设置被限制在合法范围，防止坏配置导致启动崩溃。构建与原生桥接/事件测试已通过；本轮 UI 截图与真实按键验收以项目总验证记录为准。

本轮补充 UI 验证：在原生面板点击“提取待办”，对 TextEdit 内的合成文本执行复制、处理并粘贴回 TextEdit，输出了两条预期待办。测试使用了系统剪贴板。自动化模拟 Control + Option + C 时未观察到处理，物理键盘触发和菜单栏实际操作仍待验证；不能以内部事件测试代替。

本地服务地址配置需要是带合法端口的 `localhost` 或 loopback IP，`MINICPM_TIMEOUT` 必须是有限正数；配置错误时会显示说明，不会输出地址中的凭据或 Python traceback。

## 手动验收：图片与物理快捷键

这些步骤需要真实键盘操作，当前尚未完成物理快捷键验收。**测试会替换系统剪贴板，程序不会自动恢复原有内容或全部富文本、图片格式**；开始前请先把需要保留的内容自行保存到合适的位置。

1. 启动本地模型服务，用 `.venv/bin/mcpm doctor` 检查文本和 OCR 模型，再运行 `./script/build_and_run.sh` 打开面板。
2. 在 TextEdit 等应用写入合成样本“课程通知：周五下午三点提交报告。”。按 **Control + Command + Shift + 4**，框选这行文字，复制截图到剪贴板（不要只在 Finder 复制图片文件图标）。
3. 在面板点“截图转文字”，等待状态变为完成；回到 TextEdit 按 Command + V，核对是否粘贴了正确文字。这一步验证面板按钮及系统图片剪贴板流程。
4. 再次按上述截屏组合复制同一图片，切回另一个应用；**实际按键盘**输入面板显示的快捷键（默认 Control + Option + C），等待面板状态完成，再到 TextEdit 按 Command + V 核对。这一步单独验证全局快捷键。
5. 如果状态提示快捷键注册失败，可在菜单栏 `CPM` 更换预设组合再试；如仍失败，记录状态信息，不要将内部事件测试视作实际键盘已通过。测试完成后剪贴板仍是处理结果。

快捷键事件处理与注册错误会单独显示；换到可注册的组合后，旧快捷键错误会消失，但模型失败或处理中状态会保留。可用 `macos/.build/release/MiniCPMClipboard --self-test-shortcut-status` 验证这些状态转换；该测试不触及系统剪贴板，也不测试真实按键。
