import AppKit
import Carbon

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}
func emit(_ object: [String: Any]) {
    do { FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: object)); print("") }
    catch { fail("无法序列化剪贴板数据。") }
}
// Account for both sequential requests in image-todos, plus startup/clipboard time.
// Very large valid settings leave the process to the client's own I/O timeouts.
func watchdogSeconds(_ value: String?, action: String) -> Double? {
    guard let text = value else { return (action == "image-todos" ? 2 : 1) * 180.0 + 60.0 }
    guard let timeout = Double(text), timeout.isFinite, timeout > 0 else { return 60.0 }
    let total = timeout * (action == "image-todos" ? 2 : 1) + 60.0
    guard total.isFinite, total < 9_000_000 else { return nil }
    return total
}
// Older bridges run their private self-test instead of starting the app when
// they receive the accompanying fallback flags from the Python client.
if CommandLine.arguments.contains("--bridge-version") {
    emit(["bridge_version": 2]); exit(0)
}
if CommandLine.arguments.contains("--self-test-timeouts") {
    guard watchdogSeconds(nil, action: "ocr") == 240,
          watchdogSeconds("300", action: "ocr") == 360,
          watchdogSeconds("300", action: "image-todos") == 660,
          watchdogSeconds("5", action: "image-todos") == 70,
          watchdogSeconds("nan", action: "ocr") == 60,
          watchdogSeconds("1e300", action: "ocr") == nil else { fail("Timeout calculation failed") }
    emit(["ok": true, "checks": ["default", "long custom", "sequential requests", "short custom", "invalid", "very large"]]); exit(0)
}
func snapshot(_ board: NSPasteboard, text: Bool = true, image: Bool = true) throws -> [String: Any] {
    let count = board.changeCount
    var result: [String: Any] = ["change_count": count]
    if text, let value = board.string(forType: .string) { result["text"] = value }
    if image {
        var png = board.data(forType: .png)
        if png == nil, let tiff = board.data(forType: .tiff), let bitmap = NSBitmapImageRep(data: tiff) {
            png = bitmap.representation(using: .png, properties: [:])
        }
        if let data = png {
            guard data.count <= 20 * 1024 * 1024 else { throw BridgeError.message("截图超过 20 MB，请缩小图片。") }
            result["image_png"] = data.base64EncodedString()
        }
    }
    guard board.changeCount == count else { throw BridgeError.message("读取时剪贴板发生变化，请重试。") }
    return result
}
enum BridgeError: Error { case message(String) }
func replace(_ board: NSPasteboard, expected: Int, text: String) throws {
    guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw BridgeError.message("结果为空，剪贴板未修改。") }
    guard board.changeCount == expected else { throw BridgeError.message("处理期间你复制了新内容；为保留新内容，本次未写回。") }
    board.clearContents()
    guard board.setString(text, forType: .string) else { throw BridgeError.message("剪贴板写入失败。") }
}
if CommandLine.arguments.contains(where: { ["--snapshot", "--snapshot-text", "--snapshot-image"].contains($0) }) {
    let text = !CommandLine.arguments.contains("--snapshot-image")
    let image = !CommandLine.arguments.contains("--snapshot-text")
    do { emit(try snapshot(.general, text: text, image: image)); exit(0) }
    catch BridgeError.message(let text) { fail(text) }
    catch { fail("读取剪贴板失败。") }
}
if let index = CommandLine.arguments.firstIndex(of: "--replace") {
    guard index + 1 < CommandLine.arguments.count, let count = Int(CommandLine.arguments[index + 1]),
          let text = String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8) else { fail("写回参数无效。") }
    do { try replace(.general, expected: count, text: text); emit(["ok": true]); exit(0) }
    catch BridgeError.message(let text) { fail(text) }
    catch { fail("写回剪贴板失败。") }
}
if CommandLine.arguments.contains("--self-test") {
    let board = NSPasteboard.withUniqueName()
    defer { board.releaseGlobally() }
    board.setString("私有测试文本", forType: .string)
    do {
        let first = try snapshot(board)
        guard first["text"] as? String == "私有测试文本" else { fail("snapshot failed") }
        try replace(board, expected: board.changeCount, text: "转换结果")
        guard board.string(forType: .string) == "转换结果" else { fail("replace failed") }
        let previous = board.changeCount
        board.clearContents(); board.setString("新内容", forType: .string)
        do { try replace(board, expected: previous, text: "不应写入"); fail("conflict not detected") }
        catch BridgeError.message { }
        guard board.string(forType: .string) == "新内容" else { fail("conflict changed clipboard") }
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 2, pixelsHigh: 2,
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        board.clearContents(); board.setData(bitmap.representation(using: .png, properties: [:])!, forType: .png)
        guard (try snapshot(board))["image_png"] is String else { fail("image snapshot failed") }
        board.clearContents()
        board.setString("混合内容", forType: .string)
        board.setData(Data(count: 20 * 1024 * 1024 + 1), forType: .png)
        let textOnly = try snapshot(board, image: false)
        guard textOnly["text"] as? String == "混合内容", textOnly["image_png"] == nil else { fail("text-only snapshot failed") }
        do { _ = try snapshot(board, text: false); fail("oversized image was accepted") }
        catch BridgeError.message { }
        board.clearContents()
        board.setString("混合内容", forType: .string)
        board.setData(bitmap.representation(using: .png, properties: [:])!, forType: .png)
        let imageOnly = try snapshot(board, text: false)
        guard imageOnly["image_png"] is String, imageOnly["text"] == nil else { fail("image-only snapshot failed") }
        emit(["ok": true, "checks": ["text snapshot", "text replacement", "change conflict", "PNG snapshot", "mixed content by action", "oversized image isolation"], "uses_general_clipboard": false]); exit(0)
    } catch { fail("Native pasteboard self-test failed: \(error)") }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var item: NSStatusItem!
    var status: NSMenuItem!
    var hotkey: EventHotKeyRef?
    var handler: EventHandlerRef?
    var busy = false
    var activeProcess: Process?
    var panel: NSWindow?
    var panelStatus: NSTextField?
    var panelShortcut: NSTextField?
    var shortcutProbeButton: NSButton?
    var panelButtons: [NSButton] = []
    var statusMessage = "就绪 · 请先复制文字或截图"
    var shortcutError: String?
    var shortcutProbeArmed = false
    let testingHotkey = CommandLine.arguments.contains("--self-test-hotkey")
    var hotkeyTriggers = 0
    var current = UserDefaults.standard.string(forKey: "action") ?? "todos"
    let actions = [("translate", "翻译"), ("rewrite", "简洁改写"), ("todos", "提取待办"), ("ocr", "截图转文字"), ("image-todos", "截图提取待办")]
    let shortcutLabels = ["⌃⌥C", "⌘⇧C", "⌘⌥C"]
    var shortcut: Int { max(0, min(UserDefaults.standard.integer(forKey: "shortcut"), shortcutLabels.count - 1)) }
    var root: URL {
        if let path = ProcessInfo.processInfo.environment["MINICPM_PROJECT_ROOT"] { return URL(fileURLWithPath: path) }
        if let url = Bundle.main.url(forResource: "project-root", withExtension: "txt"),
           let path = try? String(contentsOf: url, encoding: .utf8) { return URL(fileURLWithPath: path.trimmingCharacters(in: .whitespacesAndNewlines)) }
        return URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        if !actions.contains(where: { $0.0 == current }) { current = "todos" }
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "CPM"
        makeMenu()
        var type = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let installCode = InstallEventHandler(GetApplicationEventTarget(), { _, _, context in
            guard let context else { return OSStatus(eventNotHandledErr) }
            let app = Unmanaged<AppDelegate>.fromOpaque(context).takeUnretainedValue()
            DispatchQueue.main.async { app.receiveHotkey() }
            return noErr
        }, 1, &type, Unmanaged.passUnretained(self).toOpaque(), &handler)
        if reportHandlerInstallation(installCode, installed: handler != nil) {
            registerShortcut()
        }
        if !testingHotkey { openPanel() }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openPanel()
        return true
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func makePanel() {
        guard panel == nil else { return }
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 520, height: 620),
                              styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "MiniCPM 剪贴板"
        window.isReleasedWhenClosed = false
        window.center()
        let content = NSView()
        window.contentView = content
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -28),
            stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 26),
        ])
        let title = NSTextField(labelWithString: "复制，处理，再粘贴")
        title.font = .systemFont(ofSize: 24, weight: .semibold)
        stack.addArrangedSubview(title)
        let instruction = NSTextField(wrappingLabelWithString: "先复制文字或中英文截图，再选择下面的动作。处理成功后，结果写回剪贴板，可到其他应用粘贴。")
        instruction.font = .systemFont(ofSize: 13)
        instruction.textColor = .secondaryLabelColor
        stack.addArrangedSubview(instruction)
        instruction.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        let descriptions = ["翻成中文或英文", "保留原意，去掉冗余", "整理明确的任务", "识别中英文文字", "识别文字，再整理任务"]
        for (index, action) in actions.enumerated() {
            let row = NSStackView()
            row.orientation = .horizontal
            row.spacing = 16
            let button = NSButton(title: action.1, target: self, action: #selector(panelAction(_:)))
            button.tag = index
            button.bezelStyle = .rounded
            button.controlSize = .large
            button.setAccessibilityLabel(action.1)
            button.widthAnchor.constraint(equalToConstant: 150).isActive = true
            row.addArrangedSubview(button)
            let detail = NSTextField(labelWithString: descriptions[index])
            detail.textColor = .secondaryLabelColor
            detail.font = .systemFont(ofSize: 12)
            row.addArrangedSubview(detail)
            stack.addArrangedSubview(row)
            panelButtons.append(button)
        }
        let divider = NSBox()
        divider.boxType = .separator
        stack.addArrangedSubview(divider)
        divider.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        let statusLabel = NSTextField(wrappingLabelWithString: statusMessage)
        statusLabel.font = .systemFont(ofSize: 13, weight: .medium)
        statusLabel.setAccessibilityIdentifier("processing-status")
        stack.addArrangedSubview(statusLabel)
        statusLabel.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        panelStatus = statusLabel
        let shortcutLabel = NSTextField(wrappingLabelWithString: "")
        shortcutLabel.textColor = .secondaryLabelColor
        shortcutLabel.font = .systemFont(ofSize: 12)
        stack.addArrangedSubview(shortcutLabel)
        shortcutLabel.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        panelShortcut = shortcutLabel
        let probe = NSButton(title: "测试快捷键（不读取剪贴板）", target: self, action: #selector(toggleShortcutProbe(_:)))
        probe.bezelStyle = .rounded
        probe.setAccessibilityIdentifier("shortcut-probe")
        stack.addArrangedSubview(probe)
        shortcutProbeButton = probe
        let footer = NSTextField(wrappingLabelWithString: "本机处理，不保存剪贴板历史。关闭窗口后，菜单栏 CPM 和快捷键仍可使用。")
        footer.font = .systemFont(ofSize: 11)
        footer.textColor = .secondaryLabelColor
        stack.addArrangedSubview(footer)
        footer.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        panel = window
        updatePanel()
    }
    @objc func openPanel() {
        makePanel()
        panel?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    func updatePanel() {
        panelStatus?.stringValue = displayedStatus
        let name = actions.first(where: { $0.0 == current })?.1 ?? "提取待办"
        let language = UserDefaults.standard.string(forKey: "language") ?? "中文"
        panelShortcut?.stringValue = "快捷键 \(shortcutLabels[shortcut]) · 当前动作：\(name) · 翻译目标：\(language)\n可从菜单栏 CPM 调整快捷键和翻译目标。"
        for button in panelButtons { button.isEnabled = !busy }
        shortcutProbeButton?.isEnabled = !busy
        shortcutProbeButton?.title = shortcutProbeArmed ? "取消快捷键测试" : "测试快捷键（不读取剪贴板）"
    }
    var displayedStatus: String {
        guard let shortcutError else { return statusMessage }
        return "\(statusMessage) · \(shortcutError)"
    }
    func setStatus(_ message: String) {
        statusMessage = message
        status?.title = displayedStatus
        updatePanel()
    }
    func setShortcutError(_ message: String?) {
        shortcutError = message
        status?.title = displayedStatus
        updatePanel()
    }
    @discardableResult func reportHandlerInstallation(_ code: OSStatus, installed: Bool) -> Bool {
        guard code == noErr && installed else {
            setShortcutError("快捷键事件处理不可用，请重启应用（\(code)）")
            return false
        }
        return true
    }
    func reportShortcutRegistration(_ code: OSStatus, registered: Bool) {
        if code == noErr && registered { setShortcutError(nil) }
        else { setShortcutError("快捷键注册失败，请换一个组合（\(code)）") }
    }
    // The armed probe consumes exactly one hotkey event without invoking the
    // action, subprocess, or system pasteboard. It can be cancelled in-panel.
    @objc func toggleShortcutProbe(_ sender: Any?) {
        guard !busy else { return }
        if shortcutProbeArmed {
            shortcutProbeArmed = false
            setStatus("已取消快捷键测试。")
        } else if hotkey == nil || handler == nil || shortcutError != nil {
            setStatus("快捷键未成功注册，请先检查快捷键状态。")
        } else {
            shortcutProbeArmed = true
            setStatus("等待快捷键 \(shortcutLabels[shortcut]) · 本次不会读取剪贴板")
        }
    }
    func receiveHotkey() {
        if shortcutProbeArmed {
            shortcutProbeArmed = false
            setStatus("已收到快捷键 · 测试未读取剪贴板，可继续正常使用")
        } else if testingHotkey {
            hotkeyTriggers += 1
        } else {
            runAction(current)
        }
    }
    @objc func panelAction(_ sender: NSButton) {
        guard !busy, actions.indices.contains(sender.tag) else { return }
        chooseAction(actions[sender.tag].0)
    }
    func chooseAction(_ action: String) {
        guard !busy, actions.contains(where: { $0.0 == action }) else { return }
        shortcutProbeArmed = false
        current = action
        UserDefaults.standard.set(action, forKey: "action")
        makeMenu()
        runAction(action)
    }
    func makeMenu() {
        let menu = NSMenu()
        menu.autoenablesItems = false
        let panelItem = NSMenuItem(title: "打开工具面板", action: #selector(openPanel), keyEquivalent: "")
        panelItem.target = self
        menu.addItem(panelItem)
        status = NSMenuItem(title: displayedStatus, action: nil, keyEquivalent: "")
        status.isEnabled = false
        menu.addItem(status)
        menu.addItem(NSMenuItem.separator())
        for (action, title) in actions {
            let entry = NSMenuItem(title: title, action: #selector(selectAction(_:)), keyEquivalent: "")
            entry.target = self; entry.representedObject = action
            entry.state = action == current ? .on : .off; entry.isEnabled = !busy; menu.addItem(entry)
        }
        let language = UserDefaults.standard.string(forKey: "language") ?? "中文"
        let translation = NSMenuItem(title: "翻译目标：\(language)", action: nil, keyEquivalent: "")
        let languages = NSMenu()
        for value in ["中文", "English"] {
            let entry = NSMenuItem(title: value, action: #selector(setLanguage(_:)), keyEquivalent: "")
            entry.target = self; entry.representedObject = value; entry.state = value == language ? .on : .off
            languages.addItem(entry)
        }
        translation.submenu = languages; menu.addItem(translation)
        let shortcutMenu = NSMenuItem(title: "快捷键：\(shortcutLabels[shortcut])", action: nil, keyEquivalent: "")
        let bindings = NSMenu()
        for (index, title) in shortcutLabels.enumerated() {
            let entry = NSMenuItem(title: title, action: #selector(setShortcut(_:)), keyEquivalent: "")
            entry.target = self; entry.tag = index; entry.state = index == shortcut ? .on : .off; bindings.addItem(entry)
        }
        shortcutMenu.submenu = bindings; menu.addItem(shortcutMenu)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "图片 OCR 仅支持中英文 · 不还原完整版式", action: nil, keyEquivalent: ""))
        let help = NSMenuItem(title: "使用说明", action: #selector(openHelp), keyEquivalent: "")
        help.target = self; menu.addItem(help)
        menu.addItem(NSMenuItem(title: "退出", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        item.menu = menu
        updatePanel()
    }
    func registerShortcut() {
        if let hotkey { UnregisterEventHotKey(hotkey); self.hotkey = nil }
        guard handler != nil else {
            setShortcutError("快捷键事件处理不可用，请重启应用。")
            return
        }
        let modifiers: [UInt32] = [UInt32(controlKey | optionKey), UInt32(cmdKey | shiftKey), UInt32(cmdKey | optionKey)]
        let code = RegisterEventHotKey(UInt32(testingHotkey ? kVK_F19 : kVK_ANSI_C), testingHotkey ? UInt32(controlKey | cmdKey) : modifiers[shortcut], EventHotKeyID(signature: 0x4D43504D, id: 1), GetApplicationEventTarget(), 0, &hotkey)
        reportShortcutRegistration(code, registered: hotkey != nil)
    }
    @objc func setShortcut(_ sender: NSMenuItem) {
        guard shortcutLabels.indices.contains(sender.tag) else { return }
        if shortcutProbeArmed {
            shortcutProbeArmed = false
            setStatus("快捷键已更改，测试已取消。")
        }
        UserDefaults.standard.set(sender.tag, forKey: "shortcut"); makeMenu(); registerShortcut()
    }
    @objc func setLanguage(_ sender: NSMenuItem) {
        guard let language = sender.representedObject as? String, ["中文", "English"].contains(language) else { return }
        UserDefaults.standard.set(language, forKey: "language"); makeMenu()
    }
    @objc func selectAction(_ sender: NSMenuItem) {
        guard let action = sender.representedObject as? String else { return }
        chooseAction(action)
    }
    @objc func openHelp() { NSWorkspace.shared.open(root.appendingPathComponent("docs/clipboard.md")) }
    func runAction(_ action: String) {
        guard !busy else { NSSound.beep(); return }
        let python = root.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { showError("请先在项目目录运行 uv sync 安装 Python 工具集。"); return }
        busy = true
        item.button?.title = "CPM…"
        setStatus("正在处理：\(actions.first(where: { $0.0 == action })?.1 ?? action)")
        makeMenu()
        let project = root
        let language = UserDefaults.standard.string(forKey: "language") ?? "中文"
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.executableURL = python
            process.arguments = ["-m", "minicpm_tools", "clipboard", action, "--language", language, "--apply"]
            process.currentDirectoryURL = project
            var environment = ProcessInfo.processInfo.environment
            if let configURL = Bundle.main.url(forResource: "model-config", withExtension: "json"),
               let data = try? Data(contentsOf: configURL),
               let config = (try? JSONSerialization.jsonObject(with: data)) as? [String: String] {
                for (key, value) in config { environment[key] = value }
            }
            environment["MINICPM_CLIPBOARD_BRIDGE"] = Bundle.main.executablePath
            process.environment = environment
            let pipe = Pipe(); process.standardOutput = pipe; process.standardError = pipe
            do {
                try process.run()
                DispatchQueue.main.async { self.activeProcess = process }
                if let seconds = watchdogSeconds(environment["MINICPM_TIMEOUT"], action: action) {
                    DispatchQueue.global().asyncAfter(deadline: .now() + seconds) {
                        if process.isRunning { process.terminate() }
                    }
                }
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                let message = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                DispatchQueue.main.async {
                    self.activeProcess = nil; self.busy = false; self.item.button?.title = "CPM"
                    self.makeMenu()
                    if process.terminationStatus == 0 { self.setStatus("完成 · 结果已写回剪贴板，可到其他应用粘贴") }
                    else { self.showError(message.isEmpty ? "处理失败或超时，剪贴板未主动写回。" : message) }
                }
            } catch {
                DispatchQueue.main.async { self.busy = false; self.item.button?.title = "CPM"; self.makeMenu(); self.showError("无法启动本地工具：\(error.localizedDescription)") }
            }
        }
    }
    func showError(_ message: String) {
        setStatus("失败 · \(message.prefix(120))")
        let alert = NSAlert(); alert.messageText = "剪贴板处理未完成"; alert.informativeText = message
        alert.addButton(withTitle: "知道了"); NSApp.activate(ignoringOtherApps: true); alert.runModal()
    }
    func applicationWillTerminate(_ notification: Notification) {
        if let activeProcess, activeProcess.isRunning { activeProcess.terminate() }
        if let hotkey { UnregisterEventHotKey(hotkey) }
        if let handler { RemoveEventHandler(handler) }
    }
}
// Tests the same status transition methods as production without registering a
// hotkey, touching the system pasteboard, or creating an app/window instance.
if CommandLine.arguments.contains("--self-test-shortcut-status") {
    let state = AppDelegate()
    state.setStatus("失败 · 模型不可用")
    state.reportShortcutRegistration(-1, registered: false)
    guard state.displayedStatus.contains("模型不可用"), state.displayedStatus.contains("注册失败") else { fail("registration failure hid model failure") }
    state.reportShortcutRegistration(noErr, registered: true)
    guard state.displayedStatus == "失败 · 模型不可用" else { fail("registration success did not preserve model failure") }
    state.setStatus("正在处理：截图转文字")
    state.reportShortcutRegistration(-2, registered: false)
    state.reportShortcutRegistration(noErr, registered: true)
    guard state.displayedStatus == "正在处理：截图转文字" else { fail("registration success hid in-progress status") }
    guard !state.reportHandlerInstallation(-3, installed: false), state.displayedStatus.contains("事件处理不可用") else { fail("handler installation failure not shown") }
    guard state.reportHandlerInstallation(noErr, installed: true) else { fail("valid handler rejected") }
    state.reportShortcutRegistration(noErr, registered: true)
    guard state.shortcutError == nil, state.displayedStatus == "正在处理：截图转文字" else { fail("handler recovery did not preserve in-progress status") }
    state.toggleShortcutProbe(nil)
    guard !state.shortcutProbeArmed, state.statusMessage.contains("未成功注册") else { fail("probe accepted unregistered shortcut") }
    emit(["ok": true, "checks": ["registration failure and recovery", "model error preserved", "in-progress status preserved", "handler failure and recovery", "unregistered shortcut probe rejected"], "uses_general_clipboard": false]); exit(0)
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
if CommandLine.arguments.contains("--self-test-hotkey") {
    delegate.applicationDidFinishLaunching(Notification(name: NSApplication.didFinishLaunchingNotification))
    guard delegate.hotkey != nil, delegate.handler != nil else { fail("Hotkey registration failed") }
    let menu = delegate.item.menu!
    guard menu.items.filter({ $0.representedObject is String }).count == 5 else { fail("Action menu missing entries") }
    delegate.makePanel() // Builds controls without showing a window or reading the pasteboard.
    guard let probe = delegate.shortcutProbeButton, let content = delegate.panel?.contentView,
          probe.title.contains("测试快捷键") else { fail("Shortcut probe button missing") }
    content.layoutSubtreeIfNeeded()
    let probeFrame = probe.convert(probe.bounds, to: content)
    guard probeFrame.width > 0, probeFrame.height > 0,
          probeFrame.minX >= content.bounds.minX, probeFrame.maxX <= content.bounds.maxX,
          probeFrame.minY >= content.bounds.minY, probeFrame.maxY <= content.bounds.maxY
    else { fail("Shortcut probe is outside the panel: \(probeFrame) / \(content.bounds)") }
    var event: EventRef?
    guard CreateEvent(nil, OSType(kEventClassKeyboard), UInt32(kEventHotKeyPressed), GetCurrentEventTime(), EventAttributes(0), &event) == noErr,
          let event else { fail("Cannot create internal hotkey event") }
    var identifier = EventHotKeyID(signature: 0x4D43504D, id: 1)
    SetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), MemoryLayout<EventHotKeyID>.size, &identifier)
    probe.performClick(nil)
    guard delegate.shortcutProbeArmed, probe.title == "取消快捷键测试" else { fail("Cannot arm shortcut probe") }
    guard SendEventToEventTarget(event, GetApplicationEventTarget()) == noErr else { fail("Cannot dispatch internal hotkey event") }
    let probeDeadline = Date().addingTimeInterval(1)
    while delegate.shortcutProbeArmed && Date() < probeDeadline { RunLoop.main.run(until: Date().addingTimeInterval(0.02)) }
    guard !delegate.shortcutProbeArmed, delegate.hotkeyTriggers == 0,
          delegate.statusMessage.contains("已收到快捷键"), probe.title.contains("测试快捷键") else { fail("Shortcut probe did not consume the event") }
    probe.performClick(nil)
    probe.performClick(nil)
    guard !delegate.shortcutProbeArmed, delegate.statusMessage.contains("已取消") else { fail("Shortcut probe did not cancel") }
    guard SendEventToEventTarget(event, GetApplicationEventTarget()) == noErr else { fail("Cannot dispatch second internal hotkey event") }
    let deadline = Date().addingTimeInterval(1)
    while delegate.hotkeyTriggers == 0 && Date() < deadline { RunLoop.main.run(until: Date().addingTimeInterval(0.02)) }
    delegate.applicationWillTerminate(Notification(name: NSApplication.willTerminateNotification))
    guard delegate.hotkeyTriggers == 1 else { fail("Hotkey handler did not run") }
    emit(["ok": true, "checks": ["five menu actions", "Carbon registration", "probe inside panel", "probe consumes event", "probe cancellation", "internal hotkey event dispatch"], "physical_keystroke_tested": false, "uses_general_clipboard": false])
    exit(0)
}
application.run()
