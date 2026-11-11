# 每日本地阅读回顾

```sh
.venv/bin/mcpm history --browser chrome --date yesterday
.venv/bin/mcpm history --browser safari --date 2026-11-12 --mode summary --output-dir outputs/reading
.venv/bin/mcpm history --database '/path/to/profile/History' --date today
```

默认 Chrome 的 Default profile；Safari 可能需要在系统设置中授予终端完整磁盘访问权限。不会自动更改权限。数据库路径可显式指定。先通过 SQLite backup API 获取包含已提交 WAL 的临时快照，再只查询指定自然日；源数据库使用只读连接。程序结束删除快照。

默认时区 Asia/Shanghai，可用 `--timezone` 更改。保留时间、标题、域名、URL，合并同 URL 的重复访问次数；不推算阅读时长。去除 URL 查询参数和片段，过滤常见登录、密码、认证、支付路径。规则不是完整隐私检测，标题和 URL 路径仍可能含敏感内容。

默认列表模式不用模型。summary 模式让本地 MiniCPM 按标题归类，再由程序从原始记录渲染链接。模型不能自行添加页面；无效引用会报错。输出不包含文章观点、待办或“你已经读完”的推断。每 60 条分组处理，长列表可能有重复主题。真实个人浏览记录未用于项目开发测试。

`--output-dir` 明确授权保存到该目录，否则只打印预览。按日期命名且不覆盖旧文件；同一天重试可选择另一个目录。

验收测试包括 Chrome WAL 中的已提交记录、自然日边界、去重和敏感 URL 过滤。真实模型验收使用人工创建的 SQLite 浏览记录，不代表已经验证 Safari 系统权限。

2026-11-12 实跑：使用三条合成阅读记录和一条登录记录，在本地 MiniCPM5-2B Q4_K_M 上完成主题输出；登录页被过滤，三条保留记录均有来源链接。此前 1B 曾照抄占位主题、结构不合格；现改用简短输入、2B、温度 0，并检查分组是否遗漏或重复记录。模型可能把每个标题独立分组，归纳质量仍需持续改进。
