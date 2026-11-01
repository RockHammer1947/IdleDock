import Foundation

enum LanguageChoice: String, CaseIterable, Identifiable {
    case system, chinese = "zh-Hans", traditionalChinese = "zh-Hant", english = "en"
    case japanese = "ja", korean = "ko", spanish = "es", french = "fr", german = "de", russian = "ru"
    case portuguese = "pt-BR", italian = "it"
    static var supported: [LanguageChoice] { allCases.filter { $0 != .system } }
    var id: String { rawValue }
    var title: String {
        switch self {
        case .system: return L("language.system")
        case .chinese: return L("language.chinese")
        case .english: return L("language.english")
        case .japanese: return L("language.japanese")
        case .korean: return L("language.korean")
        case .spanish: return L("language.spanish")
        case .french: return L("language.french")
        case .german: return L("language.german")
        case .russian: return L("language.russian")
        case .traditionalChinese: return L("language.traditional_chinese")
        case .portuguese: return L("language.portuguese")
        case .italian: return L("language.italian")
        }
    }
    func resolved(preferredLanguages: [String] = Locale.preferredLanguages) -> String {
        guard self == .system else { return rawValue }
        for language in preferredLanguages {
            let parts = language.replacingOccurrences(of: "_", with: "-").lowercased().split(separator: "-").map(String.init)
            let base=parts.first
            if base == "zh" {
                // Explicit script wins over region: zh-Hans-HK stays Simplified.
                if parts.contains("hans") {return "zh-Hans"}
                if parts.contains("hant") || parts.contains(where: { ["tw","hk","mo"].contains($0) }) {return "zh-Hant"}
                return "zh-Hans"
            }
            // One Portuguese catalog for now; other Portuguese regions share pt-BR.
            if base == "pt" {return "pt-BR"}
            if let choice=Self.supported.first(where: { $0.rawValue == base }) {return choice.rawValue}
        }
        return "en"
    }
}

/// Presentation preferences only. Never writes queue state or invokes the CLI.
enum L10n {
    static let preferenceKey = "queue.language"
    static var preference: LanguageChoice {
        get { LanguageChoice(rawValue: UserDefaults.standard.string(forKey: preferenceKey) ?? "system") ?? .system }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: preferenceKey) }
    }
    static var locale: Locale { Locale(identifier: preference.resolved()) }
    static var numericFieldFormat: FloatingPointFormatStyle<Double> {
        .number.precision(.fractionLength(0...2)).locale(locale)
    }
    static let catalog = LocalizationCatalog(bundle: .main)
    static func text(_ key: String, arguments: [CVarArg] = []) -> String {
        catalog.text(key, language: preference.resolved(), arguments: arguments)
    }
}

/// Explicit language bundles allow switching without mutating AppleLanguages or restarting.
struct LocalizationCatalog {
    let bundles: [String: Bundle]
    init(bundle: Bundle) {
        var result: [String: Bundle] = [:]
        for language in LanguageChoice.supported.map(\.rawValue) {
            if let path = bundle.path(forResource: language, ofType: "lproj"), let localized = Bundle(path: path) {
                result[language] = localized
            }
        }
        bundles = result
    }
    func text(_ key: String, language: String, arguments: [CVarArg] = []) -> String {
        let fallback = bundles["en"]?.localizedString(forKey: key, value: key, table: nil) ?? key
        let format = bundles[language]?.localizedString(forKey: key, value: fallback, table: nil) ?? fallback
        return arguments.isEmpty ? format : String(format: format, locale: Locale(identifier: language), arguments: arguments)
    }
}

func L(_ key: String, _ arguments: CVarArg...) -> String { L10n.text(key, arguments: arguments) }

/// Numeric displays use the same locale as translated sentences and editable fields.
func N(_ format: String, _ arguments: CVarArg...) -> String {
    String(format:format,locale:L10n.locale,arguments:arguments)
}

enum UIMessage {
    case localized(String), diagnostic(String), reading(String)
    var text: String {
        switch self {
        case .localized(let key): return L(key)
        case .diagnostic(let original): return BackendText.diagnostic(original)
        case .reading(let detail): return L("error.read", detail)
        }
    }
}

enum BackendText {
    // Legacy wire values, deliberately independent from the selected UI language.
    static let waitingIdle = "等待机器闲置"
    static let waitingWindow = "等待运行时段"
    private static let keys = ["disk", "memory", "swap", "runtime", "telemetry", "overheat", "sensor",
                               "time_format", "time_range", "smart_lost", "input_detected", "input_lost",
                               "interrupted", "stopped", "protected", "no_output", "idle_range",
                               "policy_invalid", "stop_below_warning", "job_missing"]
    static func diagnostic(_ original: String, catalog: LocalizationCatalog = L10n.catalog,
                           language: String = L10n.preference.resolved()) -> String {
        for name in keys {
            let key = "backend." + name
            if ["zh-Hans", "en"].contains(where: { catalog.text(key, language: $0) == original }) {
                return catalog.text(key, language: language)
            }
        }
        // Model errors, paths and logs may contain arbitrary user/provider text.
        return catalog.text("diagnostic.original", language: language, arguments: [original])
    }
}

/// Only the built-in TTS summary has this legacy wire format. Custom provider text is untouched.
func ttsSummary(_ summary: String) -> String? {
    let parts=summary.components(separatedBy:" · ")
    guard parts.count >= 3,parts[0].hasSuffix(" 字符"),
          let count=Int(parts[0].dropLast(3)),count >= 0 else {return nil}
    return L("job.tts_summary",count,parts[1],parts.dropFirst(2).joined(separator:" · "))
}

func videoSummary(_ summary: String) -> String? {
    let suffix=" 秒视频"
    guard summary.hasSuffix(suffix),let seconds=Double(summary.dropLast(suffix.count)),seconds.isFinite,seconds >= 0 else {return nil}
    return L("job.video_seconds",seconds)
}
