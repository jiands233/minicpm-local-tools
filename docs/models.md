# 本地模型与可复现安装

本项目在 Apple Silicon macOS 上使用 Ollama `0.40.16`，文本默认 `minicpm5-2b`（MiniCPM5-2B Q4_K_M）；OCR 使用 MiniCPM-OCR 1.0 Q8_0 和 F16 projector；检索使用 BGE-M3 Q4_K_M；音频转写使用本地 MLX Whisper tiny。OCR 权重是普通 `MiniCPM-OCR-1.0-gguf`，没有使用 DSpark。

安装需要联网下载，正常推理只连接 `127.0.0.1:11434`，音频转写直接读取本地权重。没有云 API key、登录、自动云回退。模型下载是你手动执行的独立命令，运行工具不会暗中下载。

## 新机器安装

要求 Apple Silicon macOS、Python 3.11+（推荐通过 uv 使用 3.12）、curl。以下命令在项目根目录执行。先按 README 安装项目依赖：

```sh
uv sync --extra pdf --extra audio --extra dev

# 下载并校验固定版本 Ollama（186 MB）；无需安装到 /Applications 或系统路径。
.venv/bin/python script/setup_models.py download runtime
.venv/bin/python script/setup_models.py install-runtime

# 推荐的四种模型组件，总下载约 3.79 GB，另需运行时及 Ollama 导入空间。
.venv/bin/python script/setup_models.py download text-2b ocr embedding whisper-tiny
.venv/bin/python script/setup_models.py check text-2b ocr embedding whisper-tiny runtime
```

在一个终端启动服务并保持运行：

```sh
bash script/serve_models.sh
```

在另一个终端注册已校验的 GGUF：

```sh
.venv/bin/python script/setup_models.py register text-2b ocr embedding
.venv/bin/mcpm doctor
```

`register` 只读取已下载、校验通过的本地文件，并在本地 Ollama 中创建/更新这里列出的模型名称。它不修改个人 Ollama 配置，不注册系统后台服务；`serve_models.sh` 将模型存储定向到本项目 `.local/models`。如 11434 已有你自己的 Ollama 服务，先确认该服务的模型存储归属再注册；CLI 的客户端环境变量无法改变一个已经运行的服务的存储目录。

Whisper 不注册到 Ollama，运行音频命令时传 `--whisper-model .local/whisper-tiny`，完整命令见 [audio.md](audio.md)。tiny 是便于验证流水线的小模型，不能据此推断长中文课程录音的转写质量。

可选的 MiniCPM5-1B 下载约 688 MB：

```sh
.venv/bin/python script/setup_models.py download text-1b
.venv/bin/python script/setup_models.py register text-1b
MINICPM_MODEL=openbmb/minicpm5 .venv/bin/mcpm doctor
```

实测中 1B 的结构化输出和指令遵循不够稳定，所以默认采用 2B。两者都使用 GGUF 内置的 Jinja chat template；安装器不加入手写模板。应用请求关闭思考并使用温度 0，仍需对输出进行校验。升级权重或运行时后必须重新验证，不能沿用本次结果。

## 清单和验证方式

[script/models.json](../script/models.json) 是已审阅并随 Git 保存的清单，包含每个文件的：

- 固定 Hugging Face 仓库 revision（40 位提交 SHA），下载不会跟随 `main`。
- 文件字节数、SHA256、本地目标路径。
- 非 LFS 的 Whisper `config.json` 还记录 API 返回的 Git blob SHA1，用于核对其来源。
- Ollama Darwin 发行包的固定版本 URL、GitHub release API 返回的 SHA256。

权重 SHA256 取自 Hugging Face API 对该固定 revision 返回的 LFS `oid`；Whisper 配置的 SHA256 来自读取该版本配置内容后计算，并与 API 的 Git blob SHA1 一起校验。已验证当前本地的全部 8 个文件与清单一致，包括 1B、2B、OCR、projector、BGE、Whisper 的两个文件和运行时归档。

```sh
# 只检查本地文件，不联网，不启动模型。
.venv/bin/python script/setup_models.py check
```

下载先写同目录临时文件，检查字节数和 SHA256 后才以同目录硬链接独占发布到目标路径。若下载期间目标被其他进程创建，安装器会停止并保留该文件，不会将它覆盖。中断或校验失败会删除未完成文件；已有正确文件直接复用，已有损坏文件报错且不覆盖。先把报错文件移走，再显式重试。curl 不输出重定向头、完整下载错误或带签名的 CDN URL，清单中没有凭据。

`install-runtime` 不隐式下载。它先校验归档，再使用 Python tarfile 的 data filter 拒绝路径穿越、越界链接和特殊文件。已有 Ollama 可执行文件必须与已验证归档中的对应文件逐字节一致才会复用，不依赖可能显示服务端版本的 `ollama --version`，不覆盖不同或损坏的二进制。下载权重、导入副本、临时渲染和安装归档都在 `.local/` 中并由 Git 忽略；空间不足时不要把这些文件提交进仓库。

## 已固定的来源

| 组件 ID | Ollama 名称 / 用法 | 来源 |
| --- | --- | --- |
| `text-2b` | `minicpm5-2b`（默认） | [OpenBMB MiniCPM5-2B-GGUF](https://huggingface.co/openbmb/MiniCPM5-2B-GGUF/tree/8ad02b786ab81e33d465e1c80562640c55ab2877) |
| `text-1b` | `openbmb/minicpm5`（可选） | [OpenBMB MiniCPM5-1B-GGUF](https://huggingface.co/openbmb/MiniCPM5-1B-GGUF/tree/5385560dd3e232bcc3577fd9442c332cad2facbd) |
| `ocr` | `minicpm-ocr`，模型和 projector 必须一起下载 | [OpenBMB MiniCPM-OCR-1.0-gguf](https://huggingface.co/openbmb/MiniCPM-OCR-1.0-gguf/tree/0133ad8db635210441a55dcf421e25bfb9915142) |
| `embedding` | `bge-m3`，1024 维 | [GPUStack 的 BGE-M3 GGUF 转换](https://huggingface.co/gpustack/bge-m3-GGUF/tree/2d48f1737679ad900d5c26c5aad5410e9c70fdca) |
| `whisper-tiny` | `.local/whisper-tiny`，MLX 直接加载 | [MLX Community Whisper tiny](https://huggingface.co/mlx-community/whisper-tiny/tree/78c52ab98ca87f570bc57ad852e15ef7060f9f76) |
| `runtime` | `.local/runtime/ollama` | [Ollama v0.40.16 release](https://github.com/ollama/ollama/releases/tag/v0.40.16) |

MiniCPM 部署方式参考 [OpenBMB Ollama 文档](https://github.com/OpenBMB/MiniCPM/blob/main/docs/deployment/ollama.md)。OCR 一张图的识别不等于完整 PP-DocLayoutV3 版面解析；本项目没有安装完整官方 SDK，支持范围见 [search.md](search.md) 和 [clipboard.md](clipboard.md)。
