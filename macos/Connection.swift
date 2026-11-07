import Foundation
import Security

struct Webhook {
    let url: URL

    init(_ input: String) throws {
        guard input.range(of: #"\Ahttps://discord\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+\z"#,
                          options: .regularExpression) != nil, let url = URL(string: input) else {
            throw DingError("Paste a Discord channel webhook URL from discord.com.")
        }
        self.url = url
    }

    private final class NoRedirect: NSObject, URLSessionTaskDelegate {
        func urlSession(_ session: URLSession, task: URLSessionTask,
                        willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                        completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
    }
    private static let session = URLSession(configuration: .ephemeral, delegate: NoRedirect(), delegateQueue: nil)

    func channel(session: URLSession = Webhook.session) async throws -> String {
        let (data, reply) = try await session.data(for: URLRequest(url: url, timeoutInterval: 12))
        guard (reply as? HTTPURLResponse)?.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let id = json["channel_id"] as? String, !id.isEmpty,
              id.utf8.allSatisfy({ (48...57).contains($0) }) else {
            throw DingError("Discord could not verify the webhook. Check the URL and try again.")
        }
        return id
    }

    enum Result: Equatable { case accepted, retry(TimeInterval), rejected(Int) }

    func post(_ event: DingEvent, session: URLSession = Webhook.session) async throws -> Result {
        var request = URLRequest(url: url.appending(queryItems: [URLQueryItem(name: "wait", value: "true")]),
                                 timeoutInterval: 12)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "content": event.message, "allowed_mentions": ["parse": [String]()]
        ])
        let (data, reply) = try await session.data(for: request)
        let http = reply as? HTTPURLResponse
        switch http?.statusCode ?? 0 {
        case 200..<300: return .accepted
        case 429:
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            let header = Double(http?.value(forHTTPHeaderField: "Retry-After") ?? "") ?? 0
            let body = Double(String(describing: json?["retry_after"] ?? "")) ?? 0
            return .retry([header, body, 0].filter(\.isFinite).max() ?? 0)
        case 408, 500...599: return .retry(0)
        case let code: return .rejected(code)
        }
    }
}

enum Vault {
    private static func query(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "org.wow-ding.mac.webhook", kSecAttrAccount as String: account]
    }

    static func read(_ account: String) throws -> Webhook {
        var request = query(account)
        request[kSecReturnData as String] = true
        var value: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &value)
        guard status == errSecSuccess, let data = value as? Data,
              let text = String(data: data, encoding: .utf8) else {
            throw DingError("Unlock your login Keychain or paste the channel webhook again.")
        }
        return try Webhook(text)
    }

    static func save(_ hook: Webhook, account: String) throws {
        let request = query(account)
        let data = Data(hook.url.absoluteString.utf8)
        var status = SecItemUpdate(request as CFDictionary, [kSecValueData: data] as CFDictionary)
        if status == errSecItemNotFound {
            var item = request
            item[kSecValueData as String] = data
            item[kSecAttrLabel as String] = "WoW Ding Discord webhook"
            status = SecItemAdd(item as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw DingError("Could not save the webhook to your login Keychain.") }
    }

    static func remove(_ account: String) throws {
        let status = SecItemDelete(query(account) as CFDictionary)
        guard [errSecSuccess, errSecItemNotFound].contains(status) else {
            throw DingError("Could not remove the saved webhook from Keychain.")
        }
    }
}
