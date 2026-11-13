# 阅读日报真机验收清单

状态：2026-11-13，用户曾反馈 Chrome list “正常”；Chrome summary、Safari 授权前后与整机断网仍未验证。以下由用户在自己的终端操作。无需发送历史文件、报告正文、页面标题、域名、链接或截图，只反馈末尾的计数表。

## 准备

在项目根目录执行。模型应已按 [模型说明](models.md) 下载并启动；验收期间不下载、不注册模型。关闭待测浏览器，避免历史库独占锁定；不要为了通过验收启用 `--allow-approximate-snapshot`。

```sh
cd /Users/shishen/ai/minicpm-local-tools
.venv/bin/mcpm doctor
acceptance_day=$(date -v-1d '+%Y-%m-%d')
acceptance_run="outputs/reading-acceptance/$(date '+%Y%m%d-%H%M%S')"
```

请确认日期是准备测试的自然日；在北京时间环境通常为昨天。后续都使用这一日期，避免跨午夜改变数据范围。每次重新验收先重新生成 `acceptance_run`，已有报告不会覆盖。

## Chrome

```sh
.venv/bin/mcpm history --browser chrome --date "$acceptance_day" --mode list --output-dir "$acceptance_run/chrome-list"
time .venv/bin/mcpm history --browser chrome --date "$acceptance_day" --mode summary --format receipt --output-dir "$acceptance_run/chrome-summary"
echo "退出码：$?"
```

在本机打开生成的 Markdown 和 HTML。核对两份记录数一致、每条记录只出现一次、主题是否合理、通用标题是否单独列出。标题和脱敏链接应与 list 对应；链接参数隐藏可能影响回访，不应视为完整原链接。主题错误请只反馈数量，不发送具体内容。

## Safari 权限前后

先在当前权限状态下测试，不要撤销已有授权来制造失败：

```sh
.venv/bin/mcpm history --browser safari --date "$acceptance_day" --mode list --output-dir "$acceptance_run/safari-before"
echo "退出码：$?"
```

若提示无法读取，用户自行进入“系统设置 → 隐私与安全性 → 完全磁盘访问权限”，为实际运行命令的终端应用授权，必要时重启该应用。重启后重新执行准备中的变量赋值。

```sh
time .venv/bin/mcpm history --browser safari --date "$acceptance_day" --mode summary --format receipt --output-dir "$acceptance_run/safari-summary"
echo "退出码：$?"
```

已有权限则记录“授权前报错未测，原本已有权限”；没有记录则记录“空日期”，不能算模型 summary 路径通过。

## 整机断网

保持本地模型服务运行，由用户关闭 Wi-Fi、断开有线网络及手机共享等其他外网连接。确认外网不可用后，在同一终端执行：

```sh
.venv/bin/mcpm doctor
time .venv/bin/mcpm history --browser chrome --date "$acceptance_day" --mode summary --format receipt --output-dir "$acceptance_run/chrome-offline"
echo "退出码：$?"
```

本机检查小票可打开、内容完整；完成后恢复网络。仅关闭代理或通过进程沙箱限制网络不算整机断网。`doctor` 同时检查实验工具的模型配置：若仅 OCR／embedding 不可用，分别记下，不能直接判定文本 summary 失败。

## 只反馈这些信息

| 项目 | 成功／失败／空日期／未测 | 过滤去重后记录数 | 模型主题数／未归类记录数 | 耗时 | 退出码／错误类型 |
|---|---|---|---|---|---|
| Chrome list | | | 不适用 | | |
| Chrome summary | | | | | |
| Safari 当前权限下 list | | | 不适用 | | |
| Safari summary | | | | | |
| 整机断网 Chrome summary | | | | | |

另附：测试日期与时区、Mac 芯片和内存、Safari 是否原本已有权限、断网方式、是否发现主题误归类。模型主题数不含“标题信息不足，未归类”。当前 CLI 不展示内部拆批重试次数，统一记“不可观测”，不要把成功误记为零重试；终端有最终失败时只转述不含私人内容的错误类型。首次失败也保留，重试单列。
