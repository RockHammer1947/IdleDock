# UI localization / 界面多语言

IdleDock supports 11 UI languages. Open the gear menu → **Language / 语言**, or the menu bar item's language submenu. Labels update immediately, including the menu bar, open settings, status text, help, and accessibility labels. The choice persists across restarts. Language names appear in their own language so the selector remains usable after an accidental switch.

| Language | Menu label | Resource / matching |
| --- | --- | --- |
| Simplified Chinese | 简体中文 | `zh-Hans`; explicit Hans, mainland China, Singapore, generic `zh` |
| Traditional Chinese | 繁體中文 | `zh-Hant`; explicit Hant, Taiwan, Hong Kong, Macao |
| English | English | `en`; all English regions |
| Japanese | 日本語 | `ja`; including `ja-JP` |
| Korean | 한국어 | `ko`; including `ko-KR` |
| Spanish | Español | `es`; including Spain and Latin America |
| French | Français | `fr`; including France and Canada |
| German | Deutsch | `de`; including Germany, Austria and Switzerland |
| Russian | Русский | `ru`; all Russian regions |
| Portuguese (Brazil) | Português (Brasil) | `pt-BR`; other Portuguese regions currently use this catalog too |
| Italian | Italiano | `it`; including `it-IT` |

默认跟随系统语言，也可在齿轮菜单或菜单栏中切换简体中文、繁体中文、英文、日文、韩文、西班牙文、法文、德文、俄文、葡萄牙语（巴西）、意大利语。切换立即生效并记住选择，只影响界面显示，不改变运行方式、任务内容、排队顺序或后台进程。

System mode selects the first supported language in macOS's preferred-language list. For Chinese, an explicit script takes precedence over region: `zh-Hans-HK` uses Simplified Chinese and `zh-Hant-CN` uses Traditional Chinese. Taiwan/Hong Kong/Macao without an explicit script use Traditional Chinese; other Chinese variants use Simplified Chinese. Portuguese currently maps to Brazilian Portuguese, including `pt-PT`; Italian regions map to `it`. If no supported language is found, the fallback is English. The preference is stored in this app's `UserDefaults` key `queue.language`, not in SQLite. The app does not change `AppleLanguages` or global system settings.

## Translation boundary

- UI controls, status labels, durations, H3/TTS summaries, built-in protection notices, and common validation messages are translated locally. No translation service or model is called.
- User titles, request text, profile names, provider labels, paths, and logs retain their original contents. Unknown diagnostics appear under **Original diagnostic / 原始诊断**; preserve these when reporting a problem. This is UI localization, not a translated CLI or a promise to translate every third-party model error.
- Language selection does not alter a TTS request's synthesis language, voice, or text.
- Numbers, decimal separators and numeric settings input use the selected UI locale. Values remain JSON numbers when saved; formatting never changes the stored numeric value.
- Energy remains Wh/kWh (with localized unit labels where applicable) and electricity price remains **CNY/kWh** in every language. There is no currency conversion, timezone change, or automatic price adjustment.
- System-owned file dialogs and OS error descriptions may follow macOS's own language.

## Implementation for contributors and agents

| Component | Purpose |
| --- | --- |
| [Localization.swift](../macos/Localization.swift) | Language resolution, bundle lookup, English fallback, format arguments, known backend messages |
| [English strings](../macos/Resources/en.lproj/Localizable.strings) | English catalog |
| [Chinese strings](../macos/Resources/zh-Hans.lproj/Localizable.strings) | Simplified Chinese catalog |
| [Japanese](../macos/Resources/ja.lproj/Localizable.strings), [Korean](../macos/Resources/ko.lproj/Localizable.strings) | Japanese / Korean catalogs |
| [Spanish](../macos/Resources/es.lproj/Localizable.strings), [French](../macos/Resources/fr.lproj/Localizable.strings) | Spanish / French catalogs |
| [German](../macos/Resources/de.lproj/Localizable.strings), [Russian](../macos/Resources/ru.lproj/Localizable.strings) | German / Russian catalogs |
| [Traditional Chinese](../macos/Resources/zh-Hant.lproj/Localizable.strings), [Portuguese](../macos/Resources/pt-BR.lproj/Localizable.strings), [Italian](../macos/Resources/it.lproj/Localizable.strings) | Traditional Chinese / Brazilian Portuguese / Italian catalogs |
| [QueueWidget.swift](../macos/QueueWidget.swift) | Presentation preference, AppKit menus, settings sheets |
| [QueueSurface.swift](../macos/QueueSurface.swift) | SwiftUI labels and accessibility |
| [Build script](../scripts/build-app.sh) | Validates and copies `.lproj` directories into the app |

Use stable semantic keys with `L("action.save")`. Translate complete sentences, including placeholders: `L("queue.completed", completed, total)`. Keep `%@`, `%d`, and floating-point format arguments compatible across catalogs. Do not concatenate translated sentence fragments or use a translated string as a queue command, provider ID, JSON key, or status comparison.

`QueueModel.setLanguage` changes only the UI preference and invalidates presentation. It must never call `run`, `action`, `init`, or any start/pause command. SwiftUI's locale environment refreshes controls without recreating their state; AppKit titles/menus are refreshed separately. Diagnostics remain structured in memory so existing notices can change language as well.

Backend text matching is a compatibility layer for existing JSON/SQLite records. Keep matching exact and scoped to first-party messages/summaries; never translate arbitrary user content with substring replacements. New providers should expose machine-readable status/phase identifiers and keep their original diagnostic text. For broader backend localization, introduce explicit message codes/arguments with backward compatibility rather than expanding heuristic matching.

To add a language, add its complete `.lproj/Localizable.strings` catalog and extend `LanguageChoice` with its native menu name in every catalog. The catalog bundle list and native tests derive from `LanguageChoice.supported`; the build script generates `CFBundleLocalizations` from resource directories. Their agreement is checked by native tests. Extend the matching rules for script/region variants when needed. Retain English fallback. Check the actual widget and each settings sheet; longer translations can wrap differently. Use abbreviations or count labels where plural forms would otherwise be required; do not concatenate locale-dependent inflections.

## Language scope

The initial source release targets these 11 languages. Further additions should follow user demand. Arabic would require a separate right-to-left layout and mixed-script review (paths, percentages, IDs, timelines), not just a string table. New translations need native-speaker review before claiming linguistic acceptance; automated checks verify resource/format integrity and execution isolation, not translation quality.

## Validation

```sh
python3 -m unittest discover -s tests -p 'test_localization.py' -v
./scripts/test-localization.sh
./scripts/build-app.sh
codesign --verify --deep --strict 'dist/H3 Queue.app'
```

Resource tests catch missing/duplicate keys, mismatched format arguments, untranslated UI literals, and changes to known backend protection messages. Native checks load the bundled tables, exercise fallback, durations, summaries, idle states, persistence and repeated language changes, and assert that queue mode, active job, counts, and preview data remain unchanged. They use a dedicated test bundle/preferences and do not start a worker or model.

For visual checks, follow the [isolated preview instructions](images/README.md). Check every language, especially long German/Russian labels, the Queue/System tabs, all three settings sheets, idle/empty/paused/protection states, and compact view. Build and restart only the UI; preserve the production queue and model session.
