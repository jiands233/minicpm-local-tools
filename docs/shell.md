# 自然语言命令助手

```sh
.venv/bin/mcpm shell suggest '查找当前目录里大于100MB的文件'
.venv/bin/mcpm shell suggest '查看8080端口由哪个进程占用'
.venv/bin/mcpm shell suggest '把当前目录的txt后缀批量改为md，保留文件内容'
.venv/bin/mcpm shell suggest '查看磁盘剩余空间'
.venv/bin/mcpm shell explain 'tar -czf archive.tar.gz notes'
.venv/bin/mcpm shell run 'df -h'
```

生成模式只发送 OS、zsh、当前目录字符串和用户需求，不扫描文件、不执行模型命令。模型须返回一条命令及解释。多行、格式错误和没有解释的返回会失败，不能视为成功。命令语法与行为仍需你核对，尤其 BSD/GNU 参数差异。

`--execute` 或 `shell run` 才进入执行流程，并要求交互终端中输入 `EXECUTE`；回车取消。无 `--yes`，不接受管道确认。执行使用参数数组和固定系统二进制路径，不调用 shell，30 秒超时。支持 pwd/ls/df/du/lsof/whoami/uname/sw_vers/date 的有限只读调用；组合符、重定向、命令替换、通配符、删除/权限命令、常见凭据路径会被拒绝。

批量重命名等写入命令可以生成预览，但 MVP 不在程序内执行。这个白名单不等于任意命令沙箱，也不保证输出不含隐私。它是一个单次命令学习工具，不是自主 Agent。自动测试覆盖危险命令拒绝和无终端不能执行；真实模型的命令建议另做人工核对。

2026-11-12 实跑：2B 对大文件查询给出 `find . -type f -size +100M`，端口查询给出 `lsof -i :8080`，剩余空间给出 `df -h .`；批量改后缀初次错误地追加 `.txt.md`，提示改进后使用 `${1%.txt}.md`。但仍漏掉防覆盖参数，工具另行给出确定性覆盖风险提示并拒绝在程序内执行。`tar` 解释能说明打包和 gzip，但风险解释有泛化问题，不能当作专家审查。

真实 PTY 测试：`shell run 'pwd'` 在输入 `EXECUTE` 后输出项目路径；第二次按回车取消，没有执行。危险输入拒绝由自动测试覆盖。这些是演示样本，不是通用命令正确率评测。
