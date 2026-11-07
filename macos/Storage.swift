import Foundation
import CryptoKit

struct Settings: Codable {
    let game: URL
    let channel: String
    let history: UUID
    let files: [String: String]

    static var root: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("WoW Ding", isDirectory: true)
    }
    static var location: URL { root.appendingPathComponent("settings.json") }
    var historyFile: URL { Self.root.appendingPathComponent(history.uuidString + ".json") }
}

enum Addon {
    static let names = ["Ding.toc", "Ding.lua"]
    private static let fm = FileManager.default

    static func game(at path: String) throws -> URL {
        let parent = URL(fileURLWithPath: NSString(string: path).expandingTildeInPath, isDirectory: true)
        for candidate in [parent, parent.appendingPathComponent("_forever_", isDirectory: true)] {
            let folder = candidate.standardizedFileURL.resolvingSymlinksInPath()
            guard folder.lastPathComponent == "_forever_" else { continue }
            // Battle.net can give different product builds different app bundle names.
            let children = try? fm.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)
            if children?.contains(where: { $0.pathExtension.lowercased() == "app" &&
                $0.lastPathComponent.lowercased().hasPrefix("world of warcraft") &&
                Bundle(url: $0)?.executableURL != nil }) == true { return folder }
        }
        throw DingError("Choose the _forever_ folder containing the World of Warcraft app, or its parent.")
    }

    static func child(_ relative: String, in game: URL) throws -> URL {
        var url = game
        for component in relative.split(separator: "/") {
            url.appendPathComponent(String(component))
            if (try? fm.destinationOfSymbolicLink(atPath: url.path)) != nil {
                throw DingError("Choose a game installation with local addon and screenshot folders.")
            }
        }
        return url
    }

    private static func hash(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func install(in game: URL, from source: URL, previous: [String: String]) throws -> [String: String] {
        let folder = try child("Interface/AddOns/Ding", in: game)
        let shots = try child("Screenshots", in: game)
        var payload = [(URL, Data)](), hashes = [String: String]()
        for name in names {
            let target = try child("Interface/AddOns/Ding/" + name, in: game)
            let data = try Data(contentsOf: source.appendingPathComponent(name))
            if fm.fileExists(atPath: target.path) {
                let existing = try Data(contentsOf: target)
                guard existing == data || previous[name] == hash(existing) else {
                    throw DingError("Ding already contains edited files. Back up and move its addon folder, then retry.")
                }
            }
            hashes[name] = hash(data)
            payload.append((target, data))
        }
        try fm.createDirectory(at: shots, withIntermediateDirectories: true)
        try fm.createDirectory(at: folder, withIntermediateDirectories: true)
        for (target, data) in payload { try data.write(to: target, options: .atomic) }
        return hashes
    }

    static func remove(_ config: Settings) throws {
        guard config.game.lastPathComponent == "_forever_" else { return }
        for name in names {
            let path = try child("Interface/AddOns/Ding/" + name, in: config.game)
            if fm.fileExists(atPath: path.path), try hash(Data(contentsOf: path)) == config.files[name] {
                try fm.removeItem(at: path)
            }
        }
        let folder = try child("Interface/AddOns/Ding", in: config.game)
        if fm.fileExists(atPath: folder.path), try fm.contentsOfDirectory(atPath: folder.path).isEmpty {
            try fm.removeItem(at: folder)
        }
    }
}

struct History: Codable {
    var since = Date()
    var sent = Set<String>()
    var pending = [DingEvent]()
    var due = Date.distantPast
    var attempts = 0

    static func open(_ url: URL) throws -> Self {
        if FileManager.default.fileExists(atPath: url.path) {
            return try JSONDecoder().decode(Self.self, from: Data(contentsOf: url))
        }
        let fresh = Self()
        try fresh.save(url)
        return fresh
    }

    func save(_ url: URL) throws {
        try JSONEncoder().encode(self).write(to: url, options: .atomic)
    }
}

enum ScanError: Error { case folderUnavailable }

struct Scanner {
    private struct Stamp: Equatable {
        let size: Int
        let modified: Date
    }
    private var observed = [URL: Stamp]()
    private var done = Set<URL>()
    private var retry = [URL: Date]()

    mutating func scan(folder: URL, since: Date, accept: (DingEvent) throws -> Void) throws {
        let keys: Set<URLResourceKey> = [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey, .contentModificationDateKey]
        let files: [URL]
        do {
            files = try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: Array(keys),
                                                               options: [.skipsHiddenFiles])
        } catch { throw ScanError.folderUnavailable }
        var current = [URL: Stamp]()
        for url in files where ["jpg", "jpeg", "png", "tga"].contains(url.pathExtension.lowercased()) {
            guard let info = try? url.resourceValues(forKeys: keys), info.isRegularFile == true,
                  info.isSymbolicLink == false, let size = info.fileSize, (1...256_000_000).contains(size),
                  let modified = info.contentModificationDate, modified >= since else { continue }
            let stamp = Stamp(size: size, modified: modified)
            current[url] = stamp
            guard observed[url] == stamp else {
                done.remove(url)
                retry.removeValue(forKey: url)
                continue
            }
            guard !done.contains(url), retry[url] ?? .distantPast <= Date() else { continue }
            let event: DingEvent?
            do { event = try Marker.decode(url) }
            catch { retry[url] = Date().addingTimeInterval(60); continue }
            var updated = url
            updated.removeAllCachedResourceValues()
            guard let after = try? updated.resourceValues(forKeys: keys),
                  after.fileSize == size, after.contentModificationDate == modified else { continue }
            if let event, event.kind != 0x11 { try accept(event) }
            done.insert(url)
        }
        observed = current
        done.formIntersection(current.keys)
        retry = retry.filter { current[$0.key] != nil }
    }
}

actor Watcher {
    private let game: URL
    private let historyFile: URL
    private let send: (DingEvent) async throws -> Webhook.Result

    init(game: URL, historyFile: URL, send: @escaping (DingEvent) async throws -> Webhook.Result) {
        self.game = game
        self.historyFile = historyFile
        self.send = send
    }

    func run(report: @escaping @MainActor (String) -> Void) async {
        var scanner = Scanner()
        do {
            var history = try History.open(historyFile)
            var lastStatus = "Watching for level-ups."
            var reported: String?
            while !Task.isCancelled {
                var folderUnavailable = false
                do {
                    let folder = try Addon.child("Screenshots", in: game)
                    try scanner.scan(folder: folder, since: history.since) { event in
                        guard !history.sent.contains(event.id),
                              !history.pending.contains(where: { $0.id == event.id }) else { return }
                        history.pending.append(event)
                        try history.save(historyFile)
                    }
                } catch ScanError.folderUnavailable {
                    folderUnavailable = true
                }
                if let event = history.pending.first, Date() >= history.due, !Task.isCancelled {
                    let result: Webhook.Result
                    do { result = try await send(event) }
                    catch { result = .retry(0) }
                    switch result {
                    case .accepted:
                        history.sent.insert(event.id)
                        history.pending.removeFirst()
                        history.attempts = 0
                        history.due = .distantPast
                        lastStatus = "Discord accepted: " + event.message
                    case .retry(let delay):
                        history.attempts = min(history.attempts + 1, 9)
                        history.due = Date().addingTimeInterval(max(delay, min(300, pow(2, Double(history.attempts)))))
                        lastStatus = "Waiting to retry Discord delivery."
                    case .rejected(let code):
                        await report("Discord returned HTTP \(code). Check the webhook and reconnect.")
                        return
                    }
                    try history.save(historyFile)
                }
                let status = folderUnavailable ? "Waiting for access to the Screenshots folder." : lastStatus
                if status != reported { await report(status); reported = status }
                try await Task.sleep(nanoseconds: 1_000_000_000)
            }
        } catch is CancellationError {
            return
        } catch {
            await report("Watcher stopped. Check access to the game folder and local history, then reconnect.")
        }
    }
}
