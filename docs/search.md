# 本地文件夹搜索 MVP

只读取你在命令里指定的资料文件夹，支持 UTF-8 `.md` / `.txt` 和 `.pdf`。默认建立本地 embedding 语义索引；查询默认结合向量相似度和关键词匹配。MiniCPM5 可以改写查询或解释摘录，但不充当 embedding 模型。

## 安装和运行

```sh
uv sync --extra pdf
# 配置已经启动的本地 OpenAI 兼容 embedding 服务。
export MINICPM_EMBED_URL=http://127.0.0.1:11434/v1
export MINICPM_EMBED_MODEL=bge-m3
# 扫描 PDF 另外需要已经启动的 MiniCPM-OCR 服务。
export MINICPM_OCR_URL=http://127.0.0.1:11434/v1
export MINICPM_OCR_MODEL=minicpm-ocr

.venv/bin/mcpm search index ./examples/search-corpus --index ./.data/search.sqlite
.venv/bin/mcpm search query '海洋哺乳动物' --index ./.data/search.sqlite
.venv/bin/mcpm search query '矩阵求逆的笔记' --index ./.data/search.sqlite --rewrite --explain
.venv/bin/mcpm search query '课程作业截止日期' --index ./.data/search.sqlite --open 1
```

`--open 1` 用 macOS 默认应用打开第一个结果的原文件。结果同时显示 PDF 页码（打开应用时不保证跳转到该页）、原始摘录、评分和文字来源。`--explain` 让 MiniCPM 从摘录中选择一句原文依据，只有逐字匹配原文的引用才显示；其余输出显示“无法确认相关性”。选中原文也不保证相关，仍须核对。`--rewrite` 只接受简短单行，格式不合格时保留原始查询并显示提示。

尚未安装模型时，先使用明确标注的关键词模式检验文件流程：

```sh
.venv/bin/mcpm search index ./examples/search-corpus --index ./.data/keyword.sqlite --mode keyword --no-ocr
.venv/bin/mcpm search query '鲸鱼' --index ./.data/keyword.sqlite
.venv/bin/mcpm search query '矩阵' --index ./.data/keyword.sqlite
```

关键词模式不等于语义检索；只支持词汇重叠，中文多字查询使用相邻双字匹配，单字查询也能匹配文中的该字。它不会自动升级成语义索引。准备好 embedding 服务后，使用 `--mode semantic --replace` 重建；查询时更换 embedding 模型或服务地址也必须切回原配置或完整重建。即使不同服务使用同名模型、向量维度相同，其向量也未必可比较。旧索引没有记录服务地址时仍可查询，但会提示无法验证；`--mode keyword` 不依赖 embedding 服务。索引只在提取和 embedding 全部成功后替换旧版本；失败或 Ctrl+C 保留旧索引。

`--mode keyword --no-ocr` 构建或增量更新、以及不带 `--rewrite` / `--explain` 的关键词查询，不初始化模型客户端；即使模型地址或超时配置错误，也能用于纯文本/已有文字层 PDF 的离线检索。语义索引、启用 OCR 的索引、查询改写或解释仍会检查模型配置；`--no-ocr` 会跳过无文字层页面。

## 更新已有索引

```sh
.venv/bin/mcpm search index ./examples/search-corpus --index ./.data/search.sqlite --replace --incremental
```

`--incremental` 需要同时指定 `--replace`，并使用原索引相同的目录与索引选项。设置兼容时，更新会复用状态未变化的文件的已有摘录和向量，只对新增或发生变化的文件重新提取和 embedding，删除的文件不会留在新索引；输出中的 `reused_files` 是复用的文件数。每次更新仍会完整遍历指定目录，并在临时数据库全部构建成功后替换旧索引；处理失败时原索引保留。`--replace` 不加 `--incremental` 始终完整重建。

复用要求索引模式、页数上限、OCR 开关与模型及其服务地址、embedding 模型及其服务地址、提取实现版本一致；设置改变、旧索引缺少相应记录或没有文件状态时会提示并完整重建。服务地址只保存 SHA-256 指纹用于比较，不保存或输出明文地址；哈希并不是秘密存储。语义和混合查询也会检查已记录的服务地址；即使 `localhost` 和 `127.0.0.1` 指向同一服务，地址不同也会拒绝查询。同一地址、同名模型的底层权重变化无法检测，此时请用不带 `--incremental` 的 `--replace` 完整重建。

语义或混合查询在可选查询改写之前先检查 embedding 模型与服务是否兼容；若不兼容，不会先把查询发送给改写模型。关键词查询不依赖 embedding 身份，即使使用 `--rewrite`，仍仅调用改写所需的文本模型。

文件状态比较使用设备、inode、大小与时间戳，并非文件内容哈希，状态一致只意味着没有检测到变化。发布前程序会再次检查已处理文件，但不能把整个目录作为事务快照；构建期间新增或改名的文件可能尚未纳入，请避免同时更改目录，之后如有更改再更新索引。索引还是会在本机保存原文和路径，使用时应保护索引文件。

2026-11-12 本机实测：用本地 BGE-M3 对三个合成文本文件建索引，再修改、删除、新增各一个文件；增量更新复用一个未变文件，仅对新增和修改的文件各调用一次 embedding，删除文件不再出现在索引中，并用后续查询确认保留文件可检索。查询本身另有一次 embedding 请求；这个小样本不代表大目录性能。

进一步对照：使用本地 MiniCPM-OCR 和 BGE-M3，对合成扫描 PDF、文字 PDF、多片段长文本及其他文本建立索引；增、改、删文件后分别执行增量更新和完整重建。一次运行中两份索引均含 5 个文件、7 个片段、1 个 OCR 页，增量复用 3 个文件；原文、页码、来源和向量逐项相同，三个中英文查询的结果排序和摘录一致。临时材料运行后删除。这是单次合成样本结果，不保证其他文档 OCR 一致或不同运行一定产生完全相同的向量。

## PDF、范围和限制

- 每个 PDF 默认只处理前 20 页，通过 `--max-pages N` 调整，最大 500 页。
- 文字层少于 20 个非空白字符时，按扫描页渲染图片并顺序调用 `MiniCPM-OCR`。图片最长边限制 2500 像素，无 OCR 并发。`--no-ocr` 会保留已有的短文字层，仅跳过完全无文字层的页面；OCR 服务返回空白或请求出错时中止构建。
- OCR 只面向中英文，不保证德语、表格版式和公式重建；不是官方 PP-DocLayoutV3 完整版面流水线。来源：[MiniCPM-OCR 官方仓库](https://github.com/OpenBMB/MiniCPM-OCR)。
- PDF 提取和渲染依赖 `pypdfium2`，渲染图片依赖 Pillow。损坏 PDF 或 OCR/embedding 失败会中止本次构建，避免把残缺索引报告成成功。
- 不跟随符号链接，不读取隐藏文件或隐藏目录；不允许直接指定整个家目录或磁盘根目录。每个文件限制 100 MiB。 发现无法读取的子目录时会中止并提示检查权限；不会把缺漏的结果报告为索引成功，重建时保留原索引。
- 索引包含原文片段、文件绝对路径和 embedding，保存在显式 `--index` 路径。临时 OCR 图片位于系统临时目录，调用后删除。共享索引前请检查隐私。
- 查询过滤已删除或移到目录外的文件；新建索引会记录文件状态，查询时显示“来源已变化”“未检测到来源变化”或“来源状态未知”；JSON 的 `source_changed` 为 `true`、`false` 或 `null`。旧版无状态的索引为未知，内容变化需要手动 `--replace`。当前没有文件监听、自动增量索引、全盘搜索或跨设备同步。
- 向量使用 SQLite JSON 存储和 Python 余弦计算，适合小型文件夹，查询复杂度与片段数量成正比。没有宣称超过专用向量数据库或既有搜索产品。
- 语义评分不是正确率或置信度；语义检索可能返回不相关的 Top-K。以可打开的来源与摘录为准。
- 终端展示的路径、摘录、模型解释、索引进度及相关文件错误会转义 C0/C1 控制字符和 U+202A–U+202E、U+2066–U+2069 双向控制符；摘录和解释中的换行、制表符保留。JSON 输出转义这些字符但解析后保留原始内容，`--open` 使用原始路径。这不是针对其他 Unicode 字符的完整欺骗防护。

## 已执行的验证（2026-11-12，Apple Silicon）

真实 Ollama 服务监听 `127.0.0.1:11434`。Embedding 使用 `gpustack/bge-m3-GGUF` 的 `bge-m3-Q4_K_M.gguf`，输出 1024 维向量；OCR 使用本地 `minicpm-ocr`。全部输入都是本项目编写的合成示例，未读取用户私人文件。

| 查询 | 已观测首条结果 | 首条评分 | 第二条评分 |
| --- | --- | --- | --- |
| 海洋中呼吸空气的动物 | `marine.md` | 0.646 | 0.179 |
| 求逆的数学学习资料 | `algebra.txt` | 0.539 | 0.308 |
| 什么时候交数学作业 | `scan-notice.pdf`，第 1 页，来源 OCR | 0.589 | 0.236 |
| 海洋里的蓝鲸吃什么 | `text-marine.pdf`，第 1 页，来源文字层 | 0.472 | 0.197 |

扫描页没有文字层。MiniCPM-OCR 实际识别出的内容包含“请在周五下午三点前提交矩阵求逆作业。”“负责人：张老师。”以及对应英文截止时间。这些内容与生成图片一致。一次构建 2 个 PDF、提取 2 段（其中 1 页 OCR）并完成后两个查询共约 5.44 秒；这是本机单次观测，不是性能基准或真实文档准确率评测。

可复现命令（输出索引若已经存在，确认后加 `--replace`；示例生成器拒绝覆盖文件）：

```sh
.venv/bin/python examples/search_make_fixtures.py .local/search-fixtures
.venv/bin/mcpm search index examples/search-corpus --index .local/search-semantic.sqlite --no-ocr
.venv/bin/mcpm search query '海洋中呼吸空气的动物' --index .local/search-semantic.sqlite --top-k 1 --json
.venv/bin/mcpm search query '求逆的数学学习资料' --index .local/search-semantic.sqlite --top-k 1
.venv/bin/mcpm search index .local/search-fixtures --index .local/search-ocr-semantic.sqlite --max-pages 1
.venv/bin/mcpm search query '什么时候交数学作业' --index .local/search-ocr-semantic.sqlite --top-k 1
.venv/bin/mcpm search query '海洋里的蓝鲸吃什么' --index .local/search-ocr-semantic.sqlite --top-k 1
```

本次 BGE 权重来源为 [GPUStack 转换仓库固定版本](https://huggingface.co/gpustack/bge-m3-GGUF/tree/2d48f1737679ad900d5c26c5aad5410e9c70fdca)，是 BAAI/bge-m3 的 GGUF 转换，不是 MiniCPM 模型。下载文件大小 `437778496` 字节，已按仓库 LFS 信息验证 SHA256：

```text
6d39681b26c61279ac1f82db35a04a05009e94c415b51c858ff571489a82fc06
```

本机使用的 Modelfile 内容：

```text
FROM ./bge-m3-Q4_K_M.gguf
PARAMETER num_ctx 8192
```

通过 `ollama create bge-m3 -f Modelfile.bge-m3` 导入，使用同一模型建立索引和查询。该量化模型的实际效果与 Ollama 官方库同名模型不保证完全一致；复现评分请使用相同权重。模型安装后，搜索流程仅调用 loopback 服务，不访问远程模型接口。

第一次使用 MiniCPM5-1B 的自由文本“改写 + 解释”时，模型返回冗长且无依据的拒绝说明。基于这个实际失败，已把解释改成可核验的原文引用，并对改写增加格式检查；这两项属于可选增强，不影响已经验证的 embedding + OCR 检索流程。

修改后实际运行以下命令，仍命中扫描通知第 1 页，并返回通过逐字检查的依据：“请在周五下午三点前提交矩阵求逆作业。”

```sh
.venv/bin/mcpm search query '什么时候交数学作业' --index .local/search-ocr-semantic.sqlite --top-k 1 --rewrite --explain --json
```

## 自动化验证边界

`tests/test_search.py` 使用确定性的 fake embedding/OCR 客户端验证排序、模型一致性、批次限制、页码、扫描页分支、符号链接边界、索引失败回滚和临时文件清理；它不能证明真实 MiniCPM OCR 准确率或 embedding 检索质量。

`examples/search-corpus` 中两个文本文件与生成的扫描 PDF 是专门编写的演示资料，不是用户真实课程数据。真实模型结果见上表；自动化单元测试不替代这些实际调用。复杂排版、低清扫描、长文档和用户真实资料尚未评测。

### 重建时保护现有文件

`--replace` 只用于重建本工具、同一根目录的现有索引；程序会先检查 SQLite 结构、版本和根目录，拒绝覆盖普通文件、其他数据库、损坏文件、符号链接，以及有 WAL / 日志的数据库。已有 v1 索引可继续重建；新建索引带有应用标识。构建完成后程序再次检查目标，发现路径、设备、inode、大小或修改时间已改变时中止并保留目标；原来不存在的目标使用独占创建，避免覆盖构建时新出现的文件。

系统没有提供这里使用的跨进程原子“校验后替换”操作：对已存在索引，最后一次检查与替换之间仍有极小的竞态。不要同时让其他进程修改或替换同一索引；关闭其他使用者后再重建。验证使用临时目录，覆盖了普通文件、其他数据库、损坏数据库、旧版索引、不同根目录、符号链接、日志和构建过程中目标发生变化。另用本地 BGE-M3 对合成文档完成索引、重建和查询；没有读取个人文档。

首次创建索引优先用硬链接原子发布；如果硬链接不可用（例如目标文件系统不支持或拒绝该操作），会提示并回退到独占创建和流式复制，仍拒绝覆盖已有文件。回退时文件在复制期间可见，请勿同时访问或修改；普通异常或 Ctrl+C 会尽力清理本次创建的半成品。如果无法确认目标身份则不会冒险删除，并会提示可能残留空文件。强制终止、系统崩溃或清理失败也可能留下不完整索引，需检查并自行移走。这个兼容路径通过模拟不支持硬链接、并发目标出现和中断测试；在 macOS 新建的隔离 exFAT 磁盘映像上，也验证了首次创建、关键词查询和增量更新。该单次测试不代表所有磁盘或异常场景。

### 短文字层 PDF 修复

此前 `--no-ocr` 会直接跳过文字不足 20 字符的 PDF 页面，即使页面本身是包含短标题或日期的有效文本。现保留这些文字；OCR 服务返回空白或报错仍中止构建，避免隐藏故障。已对 `Exam May 10` 合成 PDF 实测本地 BGE-M3 语义索引与检索，返回第 1 页的文字层；单元测试同时覆盖无文字层的空白页。

补充回归：默认模型客户端通常已拒绝空响应，但替代 OCR 客户端返回空白时，原 PDF 提取流程仍可能静默跳过该页并发布不完整索引。现在提取层也会拒绝空白或非文字结果。合成 PDF 与替代客户端测试验证了错误、临时图片清理和原索引保留；这不是 OCR 质量评测。

### 无法读取的子目录

此前目录遍历会静默跳过无权限的子目录，导致索引缺少文件却报告成功，甚至覆盖已有完整索引。现在遍历出错时中止构建，临时索引会清理，旧索引保持不变；处理后请检查目录访问权限并重试。已在合成目录以 mode 000 复现，并分别验证首次构建和重建场景。

### 索引来源状态

索引记录文件设备、inode、大小、修改时间和状态变更时间；重新查询时检查这些元数据。若不同，结果仍展示建索引时的旧摘录，但显式标为可能过期，请重建后再据此判断。即使没有匹配结果，也会在标准错误提示已变化或状态未知的文件数；`--json` 的标准输出仍是合法 JSON。旧版索引没有记录这些信息，显示来源状态未知。元数据相同只代表未检测到变化，不能证明内容绝对没有改变。索引单个文件前后状态变化会中止构建并保留原索引；这不代替对持续并发写入的快照保证。

索引时为空的文本文件，或使用 `--no-ocr` 时没有文字层的 PDF，可能不产生任何摘录；如果这些已记录的文件后来有变化，查询时也会提示需要更新。已索引文件被删除、重命名、移出范围或无法访问时，查询会跳过旧摘录并在标准错误只提示文件数，不输出这些旧内容。重命名后的新路径及新增文件仍需手动更新索引，工具不会自动扫描新文件。旧索引缺少文件状态时无法知道无摘录的文件是否曾存在。
