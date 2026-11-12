# 真实模型验收脚本

脚本只使用合成文本、生成的图片、PDF、音频和浏览记录，不读取用户实际剪贴板或浏览历史，也不下载模型。命令助手的模型验收固定目标 shell 为 zsh，使非交互环境缺少 `SHELL` 时也可复现；这不等于覆盖所有 shell。需要已安装 README 中的 PDF / 音频依赖、已启动的本地模型，以及 macOS 语音工具。

```sh
.venv/bin/python script/verify_mvp.py --output-dir .local/acceptance --whisper-model .local/whisper-tiny
# 只检查选定工具时，报告会标明不是全量验收
.venv/bin/python script/verify_mvp.py --output-dir .local/acceptance --only audio
```

每次生成独立目录和 `report.json`，保存每项输入、输出和断言结果。`passed` 是目前已经记录的项目是否通过；只有 `complete: true` 且 `all_five_selected: true` 才表示本次五项都跑完。应同时查看各项 `status`；中断时报告可能只包含前几项。断言属于特定样本，不是准确率指标。脚本不测试物理快捷键、真实用户数据或操作系统完全断网，也无法验证自定义本地服务是否转发到云端。

2026-11-12 一次五项全量运行通过，合成转写强制分为两块的独立测试通过。之后增加检查的全量运行因暂停中断，最后生成的报告只有四项；恢复工作后应重新运行完整脚本。

2026-11-12 恢复后发现旧版脚本对大文件 `find` 验收漏掉了 `-exec` 写入操作，`.local/acceptance/mvp-ugrcrka0/report.json` 的 shell 结果无效。加强断言和只读请求检查后重跑，`.local/acceptance/mvp-7tenmhqu/report.json` 五项完成且通过；大文件建议为 `find . -type f -size +100M`，未执行。该结果仍只覆盖合成样本。

2026-11-12 额外完成进程级网络隔离验收：独立 Ollama 和验收脚本均在 macOS `sandbox-exec` 中限制为 loopback；正常环境可达的外网地址在该沙箱内连接被拒绝，隔离服务日志确认实际接收模型请求。五项合成样本通过，报告位于 `.local/validation/network-isolation/mvp-tlpa5mdh/report.json`。该测试不是整机物理断网，未隔离所有系统服务，不证明真实用户数据、实体快捷键或任意自定义模型服务的行为。
