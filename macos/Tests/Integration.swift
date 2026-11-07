import Foundation

func check(_ condition: Bool, _ message: String) throws {
    if !condition { throw DingError(message) }
}

final class MockDiscord: URLProtocol, @unchecked Sendable {
    static var reply: (URLRequest) throws -> (Int, [String: String], Data) = { _ in
        throw DingError("Unexpected request.")
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, headers, data) = try Self.reply(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: headers)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }
    override func stopLoading() {}
}

@main
struct Integration {
    static let fm = FileManager.default

    static func main() async throws {
        let folder = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true).resolvingSymlinksInPath().standardizedFileURL
        let source = URL(fileURLWithPath: "Ding", isDirectory: true)
        let manifest = try JSONDecoder().decode([String: DingEvent?].self,
                                  from: Data(contentsOf: folder.appendingPathComponent("fixtures.json")))
        for (name, expected) in manifest {
            try check(try Marker.decode(folder.appendingPathComponent(name)) == expected, "Decoder mismatch for " + name)
        }
        print("Native decoder matches the Python decoder for all Lua captures and ordinary images.")
        let game = folder.appendingPathComponent("_forever_", isDirectory: true)
        let client = game.appendingPathComponent("World of Warcraft.app/Contents")
        try fm.createDirectory(at: client.appendingPathComponent("MacOS"), withIntermediateDirectories: true)
        let plist = try PropertyListSerialization.data(fromPropertyList: ["CFBundleExecutable": "Wow"],
                                                        format: .xml, options: 0)
        try plist.write(to: client.appendingPathComponent("Info.plist"))
        try Data().write(to: client.appendingPathComponent("MacOS/Wow"))
        try check(try Addon.game(at: folder.path).path == game.path, "Game discovery failed.")
        let hashes = try Addon.install(in: game, from: source, previous: [:])
        let config = Settings(game: game, channel: "1", history: UUID(), files: hashes)
        let installed = game.appendingPathComponent("Interface/AddOns/Ding/Ding.lua")
        let edited = Data("player changes".utf8)
        try edited.write(to: installed)
        do {
            _ = try Addon.install(in: game, from: source, previous: hashes)
            throw NSError(domain: "Overwrote edited addon", code: 1)
        } catch is DingError {}
        try Addon.remove(config)
        try check(try Data(contentsOf: installed) == edited, "Removal overwrote edited addon.")
        try check(!fm.fileExists(atPath: installed.deletingLastPathComponent().appendingPathComponent("Ding.toc").path),
                  "Removal left managed addon file.")
        let escape = game.appendingPathComponent("Redirect")
        try fm.createSymbolicLink(at: escape, withDestinationURL: folder)
        do {
            _ = try Addon.child("Redirect/missing/Ding.lua", in: game)
            throw NSError(domain: "Followed symlink through missing directory", code: 1)
        } catch is DingError {}
        let event = try Marker.decode(folder.appendingPathComponent("real.jpg"))!
        let hook = try Webhook("https://discord.com/api/webhooks/12/test-only")
        if ProcessInfo.processInfo.environment["WOWDING_TEST_KEYCHAIN"] == "1" {
            let account = "test-" + UUID().uuidString
            defer { try? Vault.remove(account) }
            try Vault.save(hook, account: account)
            try check(try Vault.read(account).url == hook.url, "Temporary Keychain credential round trip failed.")
            try Vault.remove(account)
            print("Temporary Keychain credential save, read and removal passed.")
        }
        let cfg = URLSessionConfiguration.ephemeral
        cfg.protocolClasses = [MockDiscord.self]
        let session = URLSession(configuration: cfg)
        MockDiscord.reply = { req in
            try check(req.httpMethod == "GET", "Channel verification should use GET.")
            return (200, [:], Data(#"{"channel_id":"42"}"#.utf8))
        }
        try check(try await hook.channel(session: session) == "42", "Channel verification failed.")
        MockDiscord.reply = { req in
            try check(req.httpMethod == "POST" && req.url?.query == "wait=true", "Incorrect Discord request.")
            let body: Data
            if let stream = req.httpBodyStream {
                stream.open()
                defer { stream.close() }
                var data = Data()
                var buffer = [UInt8](repeating: 0, count: 1024)
                while true {
                    let count = stream.read(&buffer, maxLength: buffer.count)
                    if count == 0 { break }
                    guard count > 0 else { throw DingError("Could not read mock request body.") }
                    data.append(contentsOf: buffer.prefix(count))
                }
                body = data
            } else { body = req.httpBody ?? Data() }
            let json = try JSONSerialization.jsonObject(with: body) as? [String: Any]
            try check(json?.count == 2 && json?["content"] as? String == "Ding! Élara reached level 25 in WoW.",
                      "Unexpected message payload.")
            try check((json?["allowed_mentions"] as? [String: [String]])?["parse"] == [], "Mentions enabled.")
            return (429, ["Retry-After": "2"], Data(#"{"retry_after":4.5}"#.utf8))
        }
        try check(try await hook.post(event, session: session) == .retry(4.5), "Rate-limit handling failed.")
        for (status, expected) in [(200, Webhook.Result.accepted), (403, .rejected(403)), (502, .retry(0))] {
            MockDiscord.reply = { _ in (status, [:], Data()) }
            try check(try await hook.post(event, session: session) == expected, "Wrong handling for \(status).")
        }
        print("Addon installation, edited-file protection and Discord request checks passed.")

        let shots = game.appendingPathComponent("Screenshots")
        let historyFile = folder.appendingPathComponent("history.json")
        let initial = try History.open(historyFile)
        for (name, target) in [("ping.png", "one.png"), ("ping.png", "duplicate.png"),
                               ("local.tga", "diagnostic.tga"), ("real.jpg", "old.jpg")] {
            let file = shots.appendingPathComponent(target)
            try fm.copyItem(at: folder.appendingPathComponent(name), to: file)
            let date = initial.since.addingTimeInterval(target == "old.jpg" ? -2 : 1)
            try fm.setAttributes([.modificationDate: date], ofItemAtPath: file.path)
        }
        let first = Watcher(game: game, historyFile: historyFile) { _ in .retry(4) }
        let before = Task { await first.run { _ in } }
        try await waitUntil { try History.open(historyFile).attempts == 1 }
        before.cancel()
        await before.value
        let pending = try History.open(historyFile)
        try check(pending.pending.count == 1 && pending.pending[0].kind == 0x22, "Unexpected queued events.")
        let second = Watcher(game: game, historyFile: historyFile) { _ in
            Date() >= pending.due ? .accepted : .rejected(400)
        }
        let after = Task { await second.run { _ in } }
        try await waitUntil { try History.open(historyFile).sent.count == 1 }
        after.cancel()
        await after.value
        try check(try History.open(historyFile).pending.isEmpty, "Delivered item still queued.")
        print("Watcher cutoff, duplicate capture, diagnostic suppression, persisted retry and restart checks passed.")
    }

    static func waitUntil(_ ready: () throws -> Bool) async throws {
        for _ in 0..<100 {
            if try ready() { return }
            try await Task.sleep(nanoseconds: 100_000_000)
        }
        throw DingError("Timed out waiting for watcher state.")
    }
}
