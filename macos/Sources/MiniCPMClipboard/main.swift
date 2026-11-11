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
func snapshot(_ board: NSPasteboard) throws -> [String: Any] {
    let count = board.changeCount
    var result: [String: Any] = ["change_count": count]
    if let text = board.string(forType: .string) { result["text"] = text }
    var png = board.data(forType: .png)
    if png == nil, let tiff = board.data(forType: .tiff), let bitmap = NSBitmapImageRep(data: tiff) {
        png = bitmap.representation(using: .png, properties: [:])
    }
    if let data = png {
        guard data.count <= 20 * 1024 * 1024 else { throw BridgeError.message("截图超过 20 MB，请缩小图片。") }
        result["image_png"] = data.base64EncodedString()
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
if CommandLine.arguments.contains("--snapshot") {
    do { emit(try snapshot(.general)); exit(0) }
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
        emit(["ok": true, "checks": ["text snapshot", "text replacement", "change conflict", "PNG snapshot"], "uses_general_clipboard": false]); exit(0)
    } catch { fail("Native pasteboard self-test failed: \(error)") }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var item: NSStatusItem!
    var status: NSMenuItem!
    var hotkey: EventHotKeyRef?
    var handler: EventHandlerRef?
    var busy = false
    var activeProcess: Process?
    let testingHotkey = CommandLine.arguments.contains("--self-test-hotkey")
    var hotkeyTriggers = 0
    var current = UserDefaults.standard.string(forKey: "action") ?? "todos"
    let actions = [("translate", "翻译"), ("rewrite", "简洁改写"), ("todos", "提取待办"), ("ocr", "截图转文字"), ("image-todos", "截图提取待办")]
    let shortcutLabels = ["⌃⌥C", "⌘⇧C", "⌘⌥C"]
    var shortcut: Int { UserDefaults.standard.integer(forKey: "shortcut") }
    var root: URL {
        if let path = ProcessInfo.processInfo.environment["MINICPM_PROJECT_ROOT"] { return URL(fileURLWithPath: path) }
        if let url = Bundle.main.url(forResource: "project-root", withExtension: "txt"),
           let path = try? String(contentsOf: url, encoding: .utf8) { return URL(fileURLWithPath: path.trimmingCharacters(in: .whitespacesAndNewlines)) }
        return URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "CPM"
        makeMenu()
        var type = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, context in
            guard let context else { return OSStatus(eventNotHandledErr) }
            let app = Unmanaged<AppDelegate>.fromOpaque(context).takeUnretainedValue()
            DispatchQueue.main.async {
                if app.testingHotkey { app.hotkeyTriggers += 1 }
                else { app.runAction(app.current) }
            }
            return noErr
        }, 1, &type, Unmanaged.passUnretained(self).toOpaque(), &handler)
        registerShortcut()
    }
    func makeMenu() {
        let menu = NSMenu()
        status = NSMenuItem(title: "就绪 · 当前动作：\(actions.first(where: { $0.0 == current })?.1 ?? current)", action: nil, keyEquivalent: "")
        menu.addItem(status)
        menu.addItem(NSMenuItem.separator())
        for (action, title) in actions {
            let entry = NSMenuItem(title: title, action: #selector(selectAction(_:)), keyEquivalent: "")
            entry.target = self; entry.representedObject = action
            entry.state = action == current ? .on : .off; menu.addItem(entry)
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
        let shortcutMenu = NSMenuItem(title: "快捷键：\(shortcutLabels[min(shortcut, 2)])", action: nil, keyEquivalent: "")
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
    }
    func registerShortcut() {
        if let hotkey { UnregisterEventHotKey(hotkey) }
        let modifiers: [UInt32] = [UInt32(controlKey | optionKey), UInt32(cmdKey | shiftKey), UInt32(cmdKey | optionKey)]
        let code = RegisterEventHotKey(UInt32(testingHotkey ? kVK_F19 : kVK_ANSI_C), testingHotkey ? UInt32(controlKey | cmdKey) : modifiers[min(shortcut, 2)], EventHotKeyID(signature: 0x4D43504D, id: 1), GetApplicationEventTarget(), 0, &hotkey)
        if code != noErr { status.title = "快捷键已被占用，请换一个组合（\(code)）" }
    }
    @objc func setShortcut(_ sender: NSMenuItem) {
        UserDefaults.standard.set(sender.tag, forKey: "shortcut"); makeMenu(); registerShortcut()
    }
    @objc func setLanguage(_ sender: NSMenuItem) {
        UserDefaults.standard.set(sender.representedObject as? String, forKey: "language"); makeMenu()
    }
    @objc func selectAction(_ sender: NSMenuItem) {
        guard let action = sender.representedObject as? String else { return }
        current = action; UserDefaults.standard.set(action, forKey: "action"); makeMenu(); runAction(action)
    }
    @objc func openHelp() { NSWorkspace.shared.open(root.appendingPathComponent("docs/clipboard.md")) }
    func runAction(_ action: String) {
        guard !busy else { NSSound.beep(); return }
        let python = root.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { showError("请先在项目目录运行 uv sync 安装 Python 工具集。"); return }
        busy = true; item.button?.title = "CPM…"; status.title = "正在处理：\(action)"
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
                DispatchQueue.global().asyncAfter(deadline: .now() + 180) { if process.isRunning { process.terminate() } }
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                let message = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                DispatchQueue.main.async {
                    self.activeProcess = nil; self.busy = false; self.item.button?.title = "CPM"
                    if process.terminationStatus == 0 { self.status.title = "完成 · 可粘贴结果" }
                    else { self.showError(message.isEmpty ? "处理失败或超时，剪贴板未主动写回。" : message) }
                }
            } catch {
                DispatchQueue.main.async { self.busy = false; self.item.button?.title = "CPM"; self.showError("无法启动本地工具：\(error.localizedDescription)") }
            }
        }
    }
    func showError(_ message: String) {
        status.title = "失败 · \(message.prefix(70))"
        let alert = NSAlert(); alert.messageText = "剪贴板处理未完成"; alert.informativeText = message
        alert.addButton(withTitle: "知道了"); NSApp.activate(ignoringOtherApps: true); alert.runModal()
    }
    func applicationWillTerminate(_ notification: Notification) {
        if let activeProcess, activeProcess.isRunning { activeProcess.terminate() }
        if let hotkey { UnregisterEventHotKey(hotkey) }
        if let handler { RemoveEventHandler(handler) }
    }
}
let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
if CommandLine.arguments.contains("--self-test-hotkey") {
    delegate.applicationDidFinishLaunching(Notification(name: NSApplication.didFinishLaunchingNotification))
    guard delegate.hotkey != nil, delegate.handler != nil else { fail("Hotkey registration failed") }
    let menu = delegate.item.menu!
    guard menu.items.filter({ $0.representedObject is String }).count == 5 else { fail("Action menu missing entries") }
    var event: EventRef?
    guard CreateEvent(nil, OSType(kEventClassKeyboard), UInt32(kEventHotKeyPressed), GetCurrentEventTime(), EventAttributes(0), &event) == noErr,
          let event else { fail("Cannot create internal hotkey event") }
    var identifier = EventHotKeyID(signature: 0x4D43504D, id: 1)
    SetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), MemoryLayout<EventHotKeyID>.size, &identifier)
    guard SendEventToEventTarget(event, GetApplicationEventTarget()) == noErr else { fail("Cannot dispatch internal hotkey event") }
    let deadline = Date().addingTimeInterval(1)
    while delegate.hotkeyTriggers == 0 && Date() < deadline { RunLoop.main.run(until: Date().addingTimeInterval(0.02)) }
    delegate.applicationWillTerminate(Notification(name: NSApplication.willTerminateNotification))
    guard delegate.hotkeyTriggers == 1 else { fail("Hotkey handler did not run") }
    emit(["ok": true, "checks": ["five menu actions", "Carbon registration", "internal hotkey event dispatch"], "physical_keystroke_tested": false, "uses_general_clipboard": false])
    exit(0)
}
application.run()
