import Foundation

@main struct LocalizationTests {
    @MainActor static func main() throws {
        precondition(Bundle.main.bundleIdentifier == "local.queue-mac-h3.localization-tests", "Use the isolated test bundle")
        let defaults=UserDefaults.standard
        let old=defaults.object(forKey:L10n.preferenceKey)
        defer {
            if let old {defaults.set(old,forKey:L10n.preferenceKey)} else {defaults.removeObject(forKey:L10n.preferenceKey)}
        }
        precondition(LanguageChoice.system.resolved(preferredLanguages:["zh-CN","en-US"]) == "zh-Hans")
        precondition(LanguageChoice.system.resolved(preferredLanguages:["zh-Hant-TW"]) == "zh-Hant")
        precondition(LanguageChoice.system.resolved(preferredLanguages:["en-GB","zh-CN"]) == "en")
        precondition(LanguageChoice.system.resolved(preferredLanguages:["nl-NL","zh_CN"]) == "zh-Hans")
        precondition(LanguageChoice.system.resolved(preferredLanguages:["nl-NL"]) == "en")
        for (preference,expected) in [("ja-JP","ja"),("ko-KR","ko"),("es-MX","es"),("fr-CA","fr"),("de-AT","de"),("ru_RU","ru"),
                                      ("zh-TW","zh-Hant"),("zh-HK","zh-Hant"),("zh_MO","zh-Hant"),("zh-Hans-HK","zh-Hans"),
                                      ("zh-Hant-CN","zh-Hant"),("zh-SG","zh-Hans"),("zh","zh-Hans"),
                                      ("pt-BR","pt-BR"),("pt-PT","pt-BR"),("pt","pt-BR"),("it-IT","it")] {
            precondition(LanguageChoice.system.resolved(preferredLanguages:[preference,"en-US"]) == expected)
            precondition(LanguageChoice.system.resolved(preferredLanguages:["nl-NL",preference,"zh-CN"]) == expected)
        }
        precondition(LanguageChoice.system.resolved(preferredLanguages:["en-US","ja-JP"]) == "en")
        precondition(LanguageChoice.system.resolved(preferredLanguages:[]) == "en")
        precondition(LanguageChoice.english.resolved(preferredLanguages:["zh-CN"]) == "en")
        defaults.set("invalid",forKey:L10n.preferenceKey)
        precondition(L10n.preference == .system)

        let catalog=L10n.catalog
        let languages=LanguageChoice.supported.map(\.rawValue)
        precondition(Set(languages) == Set(Bundle.main.localizations), "Registry and bundled languages must match")
        precondition(catalog.bundles.count == languages.count)
        for language in languages {
            let url=catalog.bundles[language]!.url(forResource:"Localizable",withExtension:"strings")!
            let values=try PropertyListSerialization.propertyList(from:Data(contentsOf:url),format:nil) as! [String:String]
            precondition(!values.isEmpty)
            for (key,value) in values {
                precondition(catalog.text(key,language:language)==value,"Bundled resource mismatch: \(key)")
                let pattern="%(?:[0-9]+\\$)?[0-9.]*[@df]"
                let expression=try NSRegularExpression(pattern:pattern)
                let matches=expression.matches(in:value,range:NSRange(value.startIndex...,in:value))
                let args:[CVarArg]=matches.map {match in
                    let spec=(value as NSString).substring(with:match.range)
                    if spec.hasSuffix("@") {return "sample"}
                    if spec.hasSuffix("f") {return Double(1.5)}
                    return Int(2)
                }
                let formatted=catalog.text(key,language:language,arguments:args)
                precondition(!formatted.isEmpty && !formatted.contains("%@") && !formatted.contains("%d"),"Format failure: \(language):\(key)")
            }
        }
        precondition(catalog.text("tab.queue",language:"nl") == "Queue", "Unknown languages fall back to English")
        precondition(catalog.text("missing.key",language:"zh-Hans") == "missing.key")
        precondition(catalog.text("duration.hours",language:"en",arguments:[1,2]) == "1 hr 2 min")
        precondition(catalog.text("duration.hours",language:"zh-Hans",arguments:[1,2]) == "1小时2分")
        precondition(catalog.text("queue.completed",language:"en",arguments:[2,7]) == "Completed 2 / 7")
        precondition(BackendText.diagnostic("温度达到停止阈值",catalog:catalog,language:"en") == "Temperature reached the stop threshold.")
        let original="provider: 自定义路径 /tmp/test%job — code 7"
        precondition(BackendText.diagnostic(original,catalog:catalog,language:"en") == "Original diagnostic: "+original)

        let root=URL(fileURLWithPath:CommandLine.arguments[1])
        let fixture=root.appendingPathComponent("docs/images/preview-status.json")
        let bytes=try Data(contentsOf:fixture)
        let snapshot=try JSONDecoder().decode(QueueSnapshot.self,from:bytes)
        let model=QueueModel(config:AppConfig(root:"/nonexistent/localization-test",python:"/usr/bin/false",preview:fixture.path))
        model.data=snapshot
        var refreshes=0,changes=0
        model.onRefresh={refreshes += 1};model.onLocalizationChange={changes += 1}
        let failure=UIMessage.localized("error.preview")
        let choices=LanguageChoice.allCases + [.chinese,.english]
        for choice in choices {
            model.setLanguage(choice)
            precondition(model.language == choice && L10n.preference == choice)
            precondition(defaults.string(forKey:L10n.preferenceKey) == choice.rawValue)
            precondition(model.data?.settings.mode == snapshot.settings.mode)
            precondition(model.data?.active?.id == snapshot.active?.id && model.data?.counts == snapshot.counts)
            precondition(!model.busy && model.error == nil && model.timer == nil && refreshes == 0)
            precondition(BackendText.diagnostic("温度达到停止阈值") == L("backend.overheat"))
            precondition(UIMessage.localized("error.preview").text == L("error.preview"))
            precondition(!choice.title.isEmpty)
            precondition(L("app.title") == "IdleDock", "Brand must be stable across languages")
            if [LanguageChoice.spanish,.french,.german,.russian,.portuguese,.italian].contains(choice) {
                precondition(N("%.1f",1.5).contains(","), "Decimal comma expected for \(choice.rawValue)")
                let entered=L10n.numericFieldFormat.format(1.25)
                precondition(entered.contains(","))
                let parsed=try L10n.numericFieldFormat.parseStrategy.parse(entered)
                precondition(parsed == 1.25, "Localized settings must remain numeric")
            }
            for job in model.data!.jobs {precondition(job.title == snapshot.jobs.first{$0.id == job.id}!.title)}
        }
        precondition(changes == choices.count)
        precondition(failure.text == "Queue actions are disabled in preview mode.")
        precondition(RunMode.smart.title == "Idle" && label("queued") == "Queued")
        precondition(duration(0) == "0 min" && duration(3601) == "1 hr 1 min")
        precondition(ttsSummary("128 字符 · zh · my-voice") == "128 characters · zh · my-voice")
        precondition(ttsSummary("My custom summary") == nil)
        precondition(videoSummary("8.7 秒视频") == "8.7 sec video")
        precondition(videoSummary("custom video summary") == nil)
        precondition(smartDetail(SmartState(idle_seconds:nil,remaining_seconds:nil,ready:false,reason:"")) == L("smart.unavailable_detail"))
        precondition(smartDetail(SmartState(idle_seconds:10,remaining_seconds:61,ready:false,reason:"")) == "Starts after 2 more min of inactivity.")
        precondition(smartDetail(SmartState(idle_seconds:600,remaining_seconds:0,ready:true,reason:"")) == L("smart.ready_detail"))
        for job in model.data!.jobs {
            precondition(job.title == snapshot.jobs.first{$0.id == job.id}!.title, "User titles must never be translated")
            if job.provider == "h3" || job.provider == "tts" {precondition(!job.context.contains("秒视频") && !job.context.contains("字符"))}
        }
        var refused=false
        model.run(["start"]) {_,error in refused=error?.text == L("error.preview")}
        precondition(refused && model.data?.settings.mode == snapshot.settings.mode)
        let unchanged=try Data(contentsOf:fixture)
        precondition(unchanged == bytes)
        print("Localization checks passed: bundles, fallback, formats, live switching, unchanged queue state, preview write refusal")
    }
}
