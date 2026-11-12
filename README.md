# MiniCPM 本地阅读日报

把浏览历史整理成可核对的本地阅读日报。macOS 上读取 Chrome 或 Safari 的访问记录，可用本地 MiniCPM5-2B 按标题和域名归类，输出 Markdown。

- **来源可核对**：程序渲染原始标题和脱敏链接；模型只给记录分组。编号遗漏、重复或不存在时会重试，最终失败则拒绝输出摘要。脱敏链接可能无法返回原页面。
- **不推断阅读内容**：不读取网页正文，不推断是否读完或用户观点；常见的通用标题归入“标题信息不足，未归类”，其他主题仍是模型判断，需要人工核对。
- **本地处理**：客户端只连接 loopback 模型地址，不使用代理、重定向或云端回退。敏感页面过滤是规则匹配，不能保证排除所有私人内容；自定义本地服务也需自行确认不转发数据。

| 步骤 | 负责 |
|---|---|
| 读取历史快照、过滤、去重和渲染记录 | 程序 |
| 按编号、标题和域名归类 | 本地 MiniCPM5-2B |
| 通用标题兜底，检查编号完整、无重复和越界 | 程序；不保证主题语义正确 |

## 快速试用

安装基础依赖后，可先查看无需模型的虚构样例：

```sh
uv sync
.venv/bin/mcpm history --demo
```

也可以生成可点击的小票 HTML：

```sh
.venv/bin/mcpm history --demo --format receipt --output-dir outputs/receipt-demo
.venv/bin/mcpm history --demo --format receipt-share --output-dir outputs/receipt-demo
```

分享小票只保留计数与主题名，主题仍需核对。用浏览器打开输出文件即可查看；[详细说明](docs/history.md)包含真实历史用法。

样例中的主题是预录的一次本地模型输出，保留了它把 Python 与海洋记录合并的错误，供核对。查看自己的昨天 Chrome 记录时，运行：

```sh
.venv/bin/mcpm history --browser chrome --date yesterday
```

默认不调用模型、不保存文件。历史库被独占锁定时请先关闭浏览器；内容可能含个人信息，请先检查再分享。安装与模型配置见下文；[阅读日报说明](docs/history.md)包含 Safari、权限及输出细节。

## 安装

要求 Apple Silicon macOS、Python 3.11+、`uv` 和 `curl`。原生菜单栏还需要 Xcode Command Line Tools。尚未下载项目时，先克隆仓库：

```sh
git clone https://github.com/jiands233/minicpm-local-tools.git
cd minicpm-local-tools
```

在项目根目录安装 Python 依赖：

```sh
uv sync --extra dev --extra pdf --extra audio
.venv/bin/mcpm --help
```

命令示例统一使用项目 `.venv`，避免 `uv run` 未带 extra 时移除已经安装的可选依赖。文本与浏览历史模式只需基础依赖；PDF 需要 `pdf`，音频需要 `audio`。

首次下载模型之前，可用示例文件验证不调用模型的关键词搜索：

```sh
.venv/bin/mcpm search index examples/search-corpus --index .local/offline-demo.sqlite --mode keyword --no-ocr
.venv/bin/mcpm search query '鲸' --index .local/offline-demo.sqlite --mode keyword
```

索引默认拒绝覆盖；如果该路径已存在，查询它或选择一个新路径。

## 本地模型

新克隆的仓库没有运行时和模型，需要先手动下载并校验。推荐模型约 3.79 GB，运行时约 186 MB，注册和运行还需要额外磁盘空间。模型及运行时保存在被 Git 忽略的 `.local/`：

```sh
.venv/bin/python script/setup_models.py download runtime
.venv/bin/python script/setup_models.py install-runtime
.venv/bin/python script/setup_models.py download text-2b ocr embedding whisper-tiny
.venv/bin/python script/setup_models.py check text-2b ocr embedding whisper-tiny runtime
```

默认地址是 `http://127.0.0.1:11434/v1`。如果 11434 已有 Ollama 服务，先确认该服务及模型存储的归属：注册会在目标服务创建或更新上述模型名称，客户端环境变量不能更改已运行服务的存储目录。

在一个终端启动服务并保持运行：

```sh
./script/serve_models.sh
```

在另一个终端进入项目目录，注册文本、OCR 和 embedding 模型并检查：

```sh
.venv/bin/python script/setup_models.py register text-2b ocr embedding
.venv/bin/mcpm doctor
```

[模型配置](docs/models.md)说明固定版本、磁盘空间和安装失败处理。允许分别配置文本、OCR、embedding 服务，但地址只接受 loopback。本工具禁用 HTTP 环境代理和跳转，不做远程回退。自定义的本地服务也应关闭云转发；项目启动脚本设置 `OLLAMA_NO_CLOUD=1`。

## 其他实验

这些入口保留供本地试验，尚不是独立安装包。音频会议待办质量未达标，需逐条核对；OCR 仅面向中英文，搜索只覆盖指定目录，命令助手只允许有限的只读执行。

| 实验 | 入口 | 说明 |
|---|---|---|
| [剪贴板](docs/clipboard.md) | `mcpm clipboard` | 文本处理和中英文图片 OCR；物理快捷键及系统图片剪贴板完整链路仍待验收 |
| [文件夹搜索](docs/search.md) | `mcpm search` | 指定目录的关键词及语义检索；扫描 PDF 支持 OCR |
| [音频](docs/audio.md) | `mcpm audio` | 本地转写和纪要；会议待办质量未达标，仅供试验 |
| [命令助手](docs/shell.md) | `mcpm shell` | 生成和解释建议；仅交互确认后执行有限的只读命令 |

以下命令展示现有入口：

```sh
# 1. 明确输入预览，不改剪贴板；真实剪贴板使用 --apply
.venv/bin/mcpm clipboard todos --text '小王明天下午提交实验报告。'
./script/build_and_run.sh

# 2. 样本文件夹语义搜索
.venv/bin/mcpm search index examples/search-corpus --index .local/demo.sqlite
.venv/bin/mcpm search query '海洋中呼吸空气的动物' --index .local/demo.sqlite
# 文件变化后，复用设置兼容且未变化的文件（不自动监听）
.venv/bin/mcpm search index examples/search-corpus --index .local/demo.sqlite --replace --incremental

# 3. 本地录音 -> 转写 + 纪要（需已下载 Whisper 权重）
.venv/bin/mcpm audio /path/to/recording.m4a --whisper-model .local/whisper-tiny --output-dir outputs/audio
# 只需要转写时，不调用摘要模型
.venv/bin/mcpm audio /path/to/recording.m4a --whisper-model .local/whisper-tiny --no-summary --output-dir outputs/audio
# 较长音频可选分段转写；切分边界可能截断语句
.venv/bin/mcpm audio /path/to/recording.m4a --whisper-model .local/whisper-tiny --audio-chunk-seconds 300 --output-dir outputs/audio
# 可再加 --audio-silence-cut 尝试在附近低能量处切分，效果仍需核对
# 无音频时，也可以试用明确标注为合成的演示转写
.venv/bin/mcpm audio --transcript-json examples/audio-transcript.json --output-dir outputs/audio

# 4. 默认仅预览访问列表；summary 才调用模型
.venv/bin/mcpm history --date yesterday
.venv/bin/mcpm history --date yesterday --mode summary --output-dir outputs/reading

# 5. 默认不执行；仅生成可检查的建议
.venv/bin/mcpm shell suggest '查看当前磁盘使用情况'
.venv/bin/mcpm shell explain 'tar -czf archive.tar.gz notes'
.venv/bin/mcpm shell run 'df -h'
```

阅读回顾默认只接受一致的 SQLite 备份；浏览器独占锁定时需关闭浏览器，或明确选择带未提交数据风险的近似快照（见[说明](docs/history.md)）。

输出目录由你指定，默认拒绝覆盖（音频每次新建子目录）。搜索重建需要 `--replace`。剪贴板只在推理成功且内容没有被其他应用改动时回写。命令执行要求交互终端输入 `EXECUTE`，没有自动确认参数。

示例使用的 Whisper tiny 适合体验流程，但中文人名、地点和长录音可能识别错误。其他本地 Whisper 权重的使用与测试限制见[音频说明](docs/audio.md)。

普通输出写入失败或被中断时会尽力清理本次创建的不完整文件；清理前会检查文件身份，但检查与删除之间仍有极小竞态。强制结束进程、系统崩溃或无法确认文件身份时，半成品仍可能残留，请检查后处理。

[项目范围](docs/ROADMAP.md)和[迭代记录](docs/PROGRESS.md)记录后续方向与验证状态。

## 验证与边界

```sh
.venv/bin/pytest -q
.venv/bin/ruff check src tests script
./script/build_and_run.sh --build-only
macos/.build/release/MiniCPMClipboard --self-test
```

GitHub Actions 在 Ubuntu 和 macOS 的 Python 3.11/3.12 环境运行 Ruff 与单元测试，macOS 的 Python 3.12 任务额外构建 Swift 应用；CI 不下载模型，也不测试 GUI 或真实推理。

单元测试使用 fake 模型验证失败处理和数据边界；自动化真实模型回归使用合成样本，另对公开人声样本做过有限验证。Chrome 只读验证曾读取真实历史，但未输出或保存页面详情、也未发送给模型；验证记录详见文档。小模型仍可能漏项、误译或生成错误解释，输出需核对；有引用也不等于语义已经正确。

仍待验收的场景包括真实物理快捷键、系统图片剪贴板完整链路、Safari 历史访问授权，以及整机物理断网下的运行。公开多人情景会议已做过一次测试，但音频待办质量尚未通过；详细结果见[音频说明](docs/audio.md)。

OCR 只面向中英文整页/单图纯文本，不含 PP-DocLayoutV3 完整表格/公式版面恢复；搜索不是全盘搜索；音频没有系统音频录制与说话人分离；历史不抓网页正文；命令助手不是自动执行 Agent。

## 许可证

项目代码采用 [MIT License](LICENSE)。第三方依赖、模型权重和资料各自遵循其原有许可证，详见其官方来源。
