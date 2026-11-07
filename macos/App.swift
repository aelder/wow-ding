import AppKit
import SwiftUI
import ServiceManagement

@MainActor
final class Model: ObservableObject {
    @Published var path = ""
    @Published var secret = ""
    @Published var message = ""
    @Published var busy = false
    @Published var config: Settings?
    @Published var login = SMAppService.mainApp.status
    private var task: Task<Void, Never>?

    func load() {
        do {
            try FileManager.default.createDirectory(at: Settings.root, withIntermediateDirectories: true,
                                                   attributes: [.posixPermissions: 0o700])
            if FileManager.default.fileExists(atPath: Settings.location.path) {
                let saved = try JSONDecoder().decode(Settings.self, from: Data(contentsOf: Settings.location))
                config = saved
                path = saved.game.path
                start(saved, hook: try Vault.read(saved.channel))
            } else {
                path = (try? Addon.game(at: "/Applications/World of Warcraft").path) ?? ""
            }
        } catch { message = Self.describe(error) }
    }

    private static func describe(_ error: Error) -> String {
        if let error = error as? DingError { return error.localizedDescription }
        if error is URLError { return "Could not reach Discord. Check your connection and retry." }
        return "Could not read or save the setup. Check access to the game folder and Application Support."
    }

    private func start(_ saved: Settings, hook: Webhook) {
        let watcher = Watcher(game: saved.game, historyFile: saved.historyFile) { try await hook.post($0) }
        task = Task { [weak self] in
            await watcher.run { status in self?.message = status }
        }
    }

    private func stop() async {
        task?.cancel()
        await task?.value
        task = nil
    }

    func connect() async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        let old = config
        do {
            let game = try Addon.game(at: path)
            let text = secret.trimmingCharacters(in: .whitespacesAndNewlines)
            let hook: Webhook
            if text.isEmpty, let old { hook = try Vault.read(old.channel) }
            else { hook = try Webhook(text) }
            let channel = try await hook.channel()
            guard let source = Bundle.main.resourceURL?.appendingPathComponent("Ding") else {
                throw DingError("The app is missing its addon. Download WoW Ding again.")
            }
            let sameGame = game == old?.game
            let files = try Addon.install(in: game, from: source, previous: sameGame ? old?.files ?? [:] : [:])
            let history = sameGame && channel == old?.channel ? old?.history : nil
            let next = Settings(game: game, channel: channel, history: history ?? UUID(), files: files)
            if history == nil { _ = try History.open(next.historyFile) }
            try Vault.save(hook, account: channel)
            try JSONEncoder().encode(next).write(to: Settings.location, options: .atomic)
            await stop()
            config = next
            path = game.path
            secret = ""
            start(next, hook: hook)
            if let old {
                if old.channel != channel { try Vault.remove(old.channel) }
                if !sameGame { try Addon.remove(old) }
            }
        } catch { message = Self.describe(error) }
    }

    func disconnect() async {
        guard !busy, let config else { return }
        busy = true
        defer { busy = false }
        await stop()
        do {
            if [.enabled, .requiresApproval].contains(SMAppService.mainApp.status) {
                try await SMAppService.mainApp.unregister()
            }
            login = SMAppService.mainApp.status
            try Addon.remove(config)
            try Vault.remove(config.channel)
            try FileManager.default.removeItem(at: Settings.location)
            self.config = nil
            secret = ""
            message = "Disconnected."
        } catch { message = Self.describe(error) }
    }

    func changeLogin(_ enable: Bool) async {
        guard !busy else { return }
        busy = true
        defer { busy = false; login = SMAppService.mainApp.status }
        do {
            if enable { try SMAppService.mainApp.register() }
            else { try await SMAppService.mainApp.unregister() }
        } catch {
            message = "Could not change the login item. Move the app to Applications and check Login Items in System Settings."
        }
    }
}

struct Setup: View {
    @ObservedObject var model: Model
    @State private var confirmRemoval = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("WoW Ding").font(.title.bold())
            Text("Post your character’s name and level to Discord. Screenshots stay on this Mac.")
            VStack(alignment: .leading, spacing: 5) {
                Text("WoW Forever folder").font(.headline)
                HStack {
                    TextField("World of Warcraft or _forever_", text: $model.path)
                    Button("Browse…") {
                        let panel = NSOpenPanel()
                        panel.canChooseDirectories = true
                        panel.canChooseFiles = false
                        panel.allowsMultipleSelection = false
                        if panel.runModal() == .OK, let url = panel.url { model.path = url.path }
                    }
                }
            }
            VStack(alignment: .leading, spacing: 5) {
                Text("Discord channel webhook").font(.headline)
                SecureField(model.config == nil ? "Paste webhook URL" : "Leave blank to keep the saved webhook",
                            text: $model.secret)
                Text("In Discord, open Edit Channel → Integrations → Webhooks to copy the URL.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            if model.config != nil {
                Text("In WoW Forever, enter /reload and then /ding ping to test delivery.")
                Toggle("Open at login", isOn: Binding(get: { [.enabled, .requiresApproval].contains(model.login) },
                                                     set: { value in Task { await model.changeLogin(value) } }))
                if model.login == .requiresApproval {
                    Button("Approve in Login Items…") { SMAppService.openSystemSettingsLoginItems() }
                }
            }
            if !model.message.isEmpty {
                Text(model.message).font(.callout).textSelection(.enabled)
            }
            HStack {
                if model.config != nil {
                    Button("Disconnect…") { confirmRemoval = true }
                }
                Spacer()
                Button(model.busy ? "Working…" : "Install addon and connect") { Task { await model.connect() } }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(24).frame(width: 490).disabled(model.busy)
        .alert("Disconnect WoW Ding?", isPresented: $confirmRemoval) {
            Button("Cancel", role: .cancel) {}
            Button("Disconnect", role: .destructive) { Task { await model.disconnect() } }
        } message: {
            Text("This stops the watcher and removes its login item, saved webhook, and unmodified addon files.")
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let model = Model()
    private var status: NSStatusItem?
    private var window: NSWindow?
    private var lockFile: Int32 = -1

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            try FileManager.default.createDirectory(at: Settings.root, withIntermediateDirectories: true,
                                                   attributes: [.posixPermissions: 0o700])
        } catch { showFatal("Could not create the WoW Ding folder in Application Support."); return }
        lockFile = open(Settings.root.appendingPathComponent("watch.lock").path, O_CREAT | O_RDWR, 0o600)
        guard lockFile >= 0 else { showFatal("Could not open the WoW Ding watcher lock."); return }
        guard flock(lockFile, LOCK_EX | LOCK_NB) == 0 else {
            NSApp.terminate(nil)
            return
        }
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        status = item
        item.button?.image = NSImage(systemSymbolName: "bell.fill", accessibilityDescription: "WoW Ding")
        item.button?.toolTip = "WoW Ding"
        let menu = NSMenu()
        menu.addItem(withTitle: "WoW Ding Settings…", action: #selector(showSettings), keyEquivalent: ",").target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit WoW Ding", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.menu = menu
        // A menu-bar app needs an Edit menu for keyboard shortcuts in its text fields.
        let main = NSMenu(), edit = NSMenu(title: "Edit")
        let editItem = main.addItem(withTitle: "Edit", action: nil, keyEquivalent: "")
        editItem.submenu = edit
        for (title, selector, shortcut) in [("Cut", "cut:", "x"), ("Copy", "copy:", "c"),
                                             ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: NSSelectorFromString(selector), keyEquivalent: shortcut)
        }
        NSApp.mainMenu = main
        model.load()
        if model.config == nil || !model.message.isEmpty { showSettings() }
    }

    private func showFatal(_ text: String) {
        let alert = NSAlert()
        alert.messageText = text
        alert.runModal()
        NSApp.terminate(nil)
    }

    @objc func showSettings() {
        if window == nil {
            let controller = NSHostingController(rootView: Setup(model: model))
            let panel = NSWindow(contentViewController: controller)
            panel.title = "WoW Ding"
            panel.styleMask = [.titled, .closable, .miniaturizable]
            panel.isReleasedWhenClosed = false
            panel.center()
            window = panel
        }
        model.login = SMAppService.mainApp.status
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showSettings()
        return true
    }
}

@main
struct MacApp {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        withExtendedLifetime(delegate) { app.run() }
    }
}
