import Foundation

/// API base URL.
/// Resolution order: process env `TRIPPY_API_BASE_URL` → in-app override (Today › Server)
/// → Info.plist `TRIPPY_API_BASE_URL` (set per build in project.yml) → `defaultBaseURL`,
/// which is a server on the same machine (the simulator with `docker compose up`).
enum APIConfig {
    static let defaultBaseURL = "http://localhost:8000"
    static let overrideKey = "TrippyAPIBaseURLOverride"

    static var baseURL: String {
        if let env = ProcessInfo.processInfo.environment["TRIPPY_API_BASE_URL"]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !env.isEmpty {
            return stripTrailingSlash(env)
        }
        if let override = overrideURL {
            return override
        }
        return bundledBaseURL
    }

    /// The URL the app uses when no override is set (Info.plist, else `defaultBaseURL`).
    static var bundledBaseURL: String {
        if let plist = Bundle.main.object(forInfoDictionaryKey: "TRIPPY_API_BASE_URL") as? String {
            let trimmed = plist.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty {
                return stripTrailingSlash(trimmed)
            }
        }
        return defaultBaseURL
    }

    static var overrideURL: String? {
        guard let raw = UserDefaults.standard.string(forKey: overrideKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty else { return nil }
        return stripTrailingSlash(raw)
    }

    /// Saves an override, or clears it when `value` is nil, empty, or the bundled URL.
    static func setOverride(_ value: String?) {
        let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if trimmed.isEmpty || stripTrailingSlash(trimmed) == bundledBaseURL {
            UserDefaults.standard.removeObject(forKey: overrideKey)
        } else {
            UserDefaults.standard.set(stripTrailingSlash(trimmed), forKey: overrideKey)
        }
    }

    /// Accepts "host:port" and adds http:// when the scheme is missing.
    static func normalize(_ input: String) -> String? {
        var s = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !s.isEmpty else { return nil }
        if !s.contains("://") { s = "http://" + s }
        guard let url = URL(string: s), let scheme = url.scheme, ["http", "https"].contains(scheme),
              url.host != nil else { return nil }
        return stripTrailingSlash(s)
    }

    static func url(_ path: String) -> URL? {
        let normalized = path.hasPrefix("/") ? path : "/" + path
        return URL(string: baseURL + normalized)
    }

    private static func stripTrailingSlash(_ value: String) -> String {
        var v = value
        while v.hasSuffix("/") { v = String(v.dropLast()) }
        return v
    }
}
