import AppKit
import SwiftUI
import Combine
import UniformTypeIdentifiers

struct QueueEstimate: Decodable { var seconds: Double?; var low: Double?; var high: Double?; var samples: Int; var basis: String }
struct QueueJob: Decodable, Identifiable {
    var id: String; var title: String; var status: String; var profile: String
    var width: Int?; var height: Int?; var seconds: Double?; var estimate: QueueEstimate
    var provider: String?; var provider_label: String?; var output_kind: String?; var summary: String?; var phase: String?
    var stop_requested: Bool?
    var output: String?; var error: String?; var log: String?; var elapsed: Double?; var progress: Double?
}
struct WindowRule: Decodable { var start: String; var end: String; var timezone: String }
struct SafetyPolicy: Codable {
    var cpu_warn_c: Double; var gpu_warn_c: Double; var stop_c: Double; var hold_seconds: Double
    var hysteresis_c: Double; var stale_seconds: Double
    var stop_on_overheat: Bool; var require_telemetry: Bool; var sound: Bool
    var min_disk_gib: Double; var min_available_gib: Double; var max_swap_growth_gib: Double; var max_runtime_hours: Double
    var wall_multiplier: Double; var wall_overhead_w: Double; var price_per_kwh: Double
}
struct ThermalAlert: Decodable { var sequence: Int?; var level: String? }
struct MachineTelemetry: Decodable {
    var cpu_c: Double?; var gpu_c: Double?; var chip_w: Double?; var wall_w_estimate: Double?
    var cpu_percent:Double?; var gpu_percent:Double?; var ram_used_gib:Double?; var ram_total_gib:Double?
    var chip_wh: Double?; var wall_wh: Double?; var coverage_s: Double?; var age_seconds: Double
    var stale: Bool; var level: String?
}
struct SmartState: Decodable {var idle_seconds: Double?; var remaining_seconds: Double?; var ready: Bool; var reason: String}
struct SafetyPause: Decodable {var reason:String}
struct QueueSettings: Decodable {var safety_latch:SafetyPause?;var smart_idle_minutes: Int; var safety: SafetyPolicy; var thermal_alert: ThermalAlert; var mode: String; var window: WindowRule; var idle_minutes: Int; var require_idle: Bool; var stop_at_end: Bool }
struct QueueSnapshot: Decodable {
    var smart: SmartState
    var total_jobs: Int; var telemetry: MachineTelemetry; var energy_remaining_kwh: Double?; var energy_cost_estimate: Double?
    var settings: QueueSettings; var counts: [String:Int]; var jobs: [QueueJob]; var active: QueueJob?
    var estimate_seconds: Double; var estimate_low: Double; var estimate_high: Double; var unknown_estimates: Int; var worker_alive: Bool; var reason: String
}
struct AppConfig: Decodable { var root: String; var python: String; var preview: String? }

func duration(_ seconds: Double?) -> String {
    guard let s = seconds else { return L("duration.unknown") }
    if s<=0 {return L("duration.zero")}
    let minutes = max(1, Int(ceil(s / 60)))
    return minutes >= 60 ? L("duration.hours", minutes / 60, minutes % 60) : L("duration.minutes", minutes)
}
func label(_ status: String) -> String {
    ["queued":L("status.queued"), "running":L("status.running"), "completed":L("status.completed"), "failed":L("status.failed"), "cancelled":L("status.cancelled"), "cancel_requested":L("status.stopping")][status] ?? status
}

@MainActor final class QueueModel: ObservableObject {
    @Published var data: QueueSnapshot?
    @Published var cpuUsage:Double?
    private let cpuSampler=SystemCPUSampler()
    @Published var error: UIMessage?
    @Published var busy = false
    @Published var compact = UserDefaults.standard.bool(forKey:"queue.compact")
    @Published var pinned = UserDefaults.standard.object(forKey:"queue.pinned") as? Bool ?? true
    @Published private(set) var language = L10n.preference
    var onLocalizationChange: (() -> Void)?
    private var localeObserver: NSObjectProtocol?
    func setLanguage(_ choice: LanguageChoice) {
        L10n.preference = choice
        language = choice
        onLocalizationChange?()
    }
    var onWindowPreferences: (() -> Void)?
    var isPreview: Bool {config.preview != nil}
    func toggleCompact() {compact.toggle();UserDefaults.standard.set(compact,forKey:"queue.compact");onWindowPreferences?()}
    func togglePinned() {pinned.toggle();UserDefaults.standard.set(pinned,forKey:"queue.pinned");onWindowPreferences?()}
    let config: AppConfig
    var timer: Timer?
    var onRefresh: (() -> Void)?
    private var fetching = false
    private var readError = false
    private var lastAlertSequence: Int?
    private var lastSound = Date.distantPast
    private let io = DispatchQueue(label: "local.h3queue.cli", qos: .utility)
    init(config: AppConfig) {
        self.config=config
        localeObserver=NotificationCenter.default.addObserver(forName:NSLocale.currentLocaleDidChangeNotification,object:nil,queue:.main) { [weak self] _ in
            Task { @MainActor in
                guard let self,self.language == .system else {return}
                self.objectWillChange.send();self.onLocalizationChange?()
            }
        }
    }
    deinit {if let localeObserver {NotificationCenter.default.removeObserver(localeObserver)}}
    func run(_ args: [String], completion: @escaping (Data?, UIMessage?) -> Void) {
        let config=self.config
        if let preview=config.preview {
            guard ["status","init"].contains(args.first ?? "") else {completion(nil,.localized("error.preview"));return}
            do {completion(try Data(contentsOf:URL(fileURLWithPath:preview)),nil)} catch {completion(nil,.diagnostic(error.localizedDescription))}
            return
        }
        io.async {
            let process=Process(); process.executableURL=URL(fileURLWithPath: config.python)
            process.currentDirectoryURL=URL(fileURLWithPath: config.root)
            process.arguments=["-m","h3queue.cli"]+args
            let output=Pipe();process.standardOutput=output;process.standardError=FileHandle.nullDevice
            do {
                try process.run()
                let bytes=output.fileHandleForReading.readDataToEndOfFile();process.waitUntilExit()
                let jsonError=(try? JSONSerialization.jsonObject(with:bytes)) as? [String:Any]
                let detail=jsonError?["error"] as? String ?? String(data:bytes,encoding:.utf8)
                let err:UIMessage?=process.terminationStatus == 0 ? nil : detail.map(UIMessage.diagnostic) ?? .localized("error.operation")
                DispatchQueue.main.async { completion(bytes,err) }
            } catch { DispatchQueue.main.async { completion(nil,.diagnostic(error.localizedDescription)) } }
        }
    }
    func refresh() {
        guard !fetching else {return};fetching=true
        if !isPreview {cpuUsage=cpuSampler.sample()}
        run(["status"]) { bytes,err in
            self.fetching=false
            if let err { self.error=err;self.readError=true;return }
            guard let bytes else {return}
            do {
                let next=try JSONDecoder().decode(QueueSnapshot.self,from:bytes)
                if self.isPreview {self.cpuUsage=next.telemetry.stale ? nil : usagePercent(next.telemetry.cpu_percent)}
                let sequence=next.settings.thermal_alert.sequence
                let alarm=next.telemetry.stale || ["warning","critical"].contains(next.telemetry.level ?? "")
                if alarm && !self.isPreview && next.settings.safety.sound && (sequence != self.lastAlertSequence || self.data?.telemetry.stale == false && next.telemetry.stale) && Date().timeIntervalSince(self.lastSound)>60 {
                    NSSound.beep();self.lastSound=Date()
                }
                if self.readError {self.error=nil;self.readError=false}
                self.lastAlertSequence=sequence;self.data=next;self.onRefresh?()
            }
            catch { self.error = .reading(error.localizedDescription);self.readError=true }
        }
    }
    func action(_ args:[String]) {
        guard !busy else {return}
        busy=true;error=nil;readError=false
        run(args) { _,err in self.busy=false;self.error=err;self.refresh() }
    }
    func start() {
        action(["init"])
        timer=Timer.scheduledTimer(withTimeInterval:3,repeats:true) { _ in Task { @MainActor in self.refresh() } }
    }
}

struct ScheduleView: View {
    @ObservedObject var model: QueueModel
    @Environment(\.dismiss) var dismiss
    @State var start: String
    @State var end: String
    @State var idle: Int
    @State var requireIdle: Bool
    @State var stopAtEnd: Bool
    @State var timezone: String
    @State private var saving=false
    @State private var error:UIMessage?
    var body: some View {
        VStack(alignment:.leading,spacing:18) {
            Text(L("schedule.title")).font(.title2.weight(.semibold))
            HStack { Text(L("schedule.window"));TextField("00:00",text:$start).frame(width:70);Text(L("schedule.to"));TextField("07:00",text:$end).frame(width:70) }
            TextField(L("schedule.timezone"),text:$timezone)
            Toggle(L("schedule.require_idle"),isOn:$requireIdle).fixedSize(horizontal:false,vertical:true)
            Stepper(L("schedule.idle", idle),value:$idle,in:0...120,step:5).disabled(!requireIdle)
            Toggle(L("schedule.stop_at_end"),isOn:$stopAtEnd).fixedSize(horizontal:false,vertical:true)
            Text(L("schedule.stop_help"))
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
            if let error {Text(error.text).font(.caption).foregroundStyle(.red)}
            HStack {
                Button(L("action.cancel")) { dismiss() };Spacer()
                Button(saving ? L("action.saving") : L("schedule.save")) {
                    var args=["schedule","--start",start,"--end",end,"--timezone",timezone,"--idle-minutes",String(idle)]
                    if !requireIdle {args.append("--no-idle")};if !stopAtEnd {args.append("--finish-current")}
                    saving=true
                    model.run(args) {_,err in
                        saving=false
                        if let err {error=err} else {model.refresh();dismiss()}
                    }
                }.buttonStyle(.borderedProminent)
            }
            Text(L("schedule.save_help")).font(.caption).foregroundStyle(.secondary)
        }.padding(24).frame(width:410)
    }
}

func metric(_ value: Double?, _ suffix: String) -> String {
    value.map {N("%.1f",$0)+suffix} ?? L("metric.pending")
}
struct SafetyView: View {
    @ObservedObject var model: QueueModel
    @Environment(\.dismiss) var dismiss
    @State var policy: SafetyPolicy
    @State private var saving=false
    @State private var saveError: UIMessage?
    func field(_ label:String,_ binding:Binding<Double>,_ unit:String) -> some View {
        HStack(alignment:.firstTextBaseline) {Text(label).fixedSize(horizontal:false,vertical:true);Spacer();TextField("",value:binding,format:L10n.numericFieldFormat).multilineTextAlignment(.trailing).frame(width:75);Text(unit).foregroundStyle(.secondary).frame(width:65,alignment:.leading)}
    }
    var body: some View {
        VStack(alignment:.leading,spacing:14) {
            Text(L("safety.title")).font(.title2.weight(.semibold))
            VStack(spacing:8) {
                field(L("safety.cpu_warning"),$policy.cpu_warn_c,"°C")
                field(L("safety.gpu_warning"),$policy.gpu_warn_c,"°C")
                field(L("safety.stop_threshold"),$policy.stop_c,"°C")
                field(L("safety.hold_threshold"),$policy.hold_seconds,L("unit.seconds"))
            }
            Toggle(L("safety.sound"),isOn:$policy.sound).fixedSize(horizontal:false,vertical:true)
            Toggle(L("safety.overheat_toggle"),isOn:$policy.stop_on_overheat).fixedSize(horizontal:false,vertical:true)
            Toggle(L("safety.telemetry_toggle"),isOn:$policy.require_telemetry).fixedSize(horizontal:false,vertical:true)
            Text(L("safety.explanation", Int(policy.hysteresis_c))).font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal:false,vertical:true)
            Divider()
            DisclosureGroup(L("safety.resources")) {
                ScrollView { VStack(spacing:8) {
                    field(L("safety.hysteresis"),$policy.hysteresis_c,"°C")
                    field(L("safety.stale_wait"),$policy.stale_seconds,L("unit.seconds"))
                    field(L("safety.disk"),$policy.min_disk_gib,"GiB")
                    field(L("safety.memory"),$policy.min_available_gib,"GiB")
                    field(L("safety.swap"),$policy.max_swap_growth_gib,"GiB")
                    field(L("safety.runtime"),$policy.max_runtime_hours,L("unit.hours"))
                    field(L("safety.multiplier"),$policy.wall_multiplier,L("unit.multiplier"))
                    field(L("safety.overhead"),$policy.wall_overhead_w,"W")
                    field(L("safety.price"),$policy.price_per_kwh,L("unit.price"))
                    Text(L("safety.energy_help")).font(.caption).foregroundStyle(.secondary)
                }.padding(.top,8) }.frame(maxHeight:260)
            }
            if let saveError {Text(saveError.text).font(.caption).foregroundStyle(.red).lineLimit(3)}
            HStack {
                Button(L("action.cancel")){dismiss()};Spacer()
                Button(saving ? L("action.saving") : L("action.save")) {
                    guard let bytes=try? JSONEncoder().encode(policy),let values=try? JSONSerialization.jsonObject(with:bytes) as? [String:Any] else {return}
                    var args=["safety"]
                    for key in values.keys.sorted() {
                        guard let value=try? JSONSerialization.data(withJSONObject:values[key]!,options:.fragmentsAllowed),let text=String(data:value,encoding:.utf8) else {continue}
                        args += ["--set",key+"="+text]
                    }
                    saving=true
                    model.run(args) {_,error in
                        saving=false
                        if let error {saveError=error} else {model.refresh();dismiss()}
                    }
                }.buttonStyle(.borderedProminent).disabled(saving)
            }
        }.padding(24).frame(width:440)
    }
}

func idleLabel(_ seconds: Double?) -> String {
    guard let seconds else {return L("smart.unavailable")}
    let n=max(0,Int(seconds))
    return L("smart.idle_elapsed", n / 60, n % 60)
}
func smartDetail(_ state: SmartState) -> String {
    guard state.idle_seconds != nil,let remaining=state.remaining_seconds else {return L("smart.unavailable_detail")}
    return state.ready ? L("smart.ready_detail") : L("smart.wait_detail",max(1,Int(ceil(remaining/60))))
}
func modeLabel(_ mode:String?) -> String {
    ["paused":L("state.paused"),"auto":L("mode.scheduled"),"smart":L("mode.smart_short"),"manual":L("mode.manual")][mode ?? "paused"] ?? L("state.paused")
}
struct SmartModeView: View {
    @ObservedObject var model: QueueModel
    @Environment(\.dismiss) var dismiss
    @State var minutes: Int
    @State private var saving=false
    @State private var error:UIMessage?
    var body: some View {
        VStack(alignment:.leading,spacing:18) {
            Label(L("smart.title"),systemImage:"moon.zzz.fill").font(.title2.weight(.semibold))
            Text(L("smart.intro")).foregroundStyle(.secondary)
            Stepper(L("smart.start_after", minutes),value:$minutes,in:1...240)
            HStack {ForEach([5,10,15,30,60],id:\.self) { n in Button(L("smart.preset", n)){minutes=n} }}
            Text(L("smart.stop_help")).font(.callout).foregroundStyle(.secondary)
            Text(L("smart.safety_help")).font(.caption).foregroundStyle(.secondary)
            if let error {Text(error.text).font(.caption).foregroundStyle(.red)}
            HStack {
                Button(L("action.cancel")){dismiss()};Spacer()
                Button(saving ? L("action.saving") : L("action.save")) {
                    saving=true
                    model.run(["smart-config","--idle-minutes",String(minutes)]) {_,err in
                        saving=false
                        if let err {error=err} else {model.refresh();dismiss()}
                    }
                }.buttonStyle(.borderedProminent).disabled(saving)
            }
            Text(L("smart.save_help")).font(.caption).foregroundStyle(.secondary)
        }.padding(24).frame(width:420)
    }
}
@MainActor final class Delegate: NSObject,NSApplicationDelegate {
    var item:NSStatusItem!;var panel:NSPanel!;var model:QueueModel!
    private var roomyCompact=false
    func applicationDidFinishLaunching(_ notification:Notification) {
        guard let url=Bundle.main.url(forResource:"config",withExtension:"json"),let bytes=try? Data(contentsOf:url),let config=try? JSONDecoder().decode(AppConfig.self,from:bytes) else { NSApp.terminate(nil);return }
        model=QueueModel(config:config)
        item=NSStatusBar.system.statusItem(withLength:NSStatusItem.variableLength)
        item.button?.image=NSImage(systemSymbolName:"film.stack",accessibilityDescription:L("app.title"))
        item.button?.imagePosition = .imageLeft
        panel=NSPanel(contentRect:NSRect(x:0,y:0,width:400,height:640),styleMask:[.titled,.closable,.resizable,.fullSizeContentView,.nonactivatingPanel],backing:.buffered,defer:false)
        panel.title=model.isPreview ? L("app.preview_title") : L("app.title");panel.titlebarAppearsTransparent=true;panel.titleVisibility = .hidden
        panel.appearance=NSAppearance(named:.darkAqua)
        panel.isFloatingPanel=true;panel.level = .floating;panel.hidesOnDeactivate=false
        panel.collectionBehavior=[.canJoinAllSpaces,.fullScreenAuxiliary];panel.isReleasedWhenClosed=false
        panel.contentView=NSHostingView(rootView:QueueView(model:model))
        model.onWindowPreferences={ [weak self] in self?.applyWindowPreferences() }
        model.onLocalizationChange={ [weak self] in self?.localizeApp() }
        localizeApp()
        applyWindowPreferences()
        if !panel.setFrameUsingName("H3QueuePanelLemon") {panel.center()}
        panel.setFrameAutosaveName("H3QueuePanelLemon");panel.orderFrontRegardless()
        model.onRefresh={ [weak self] in
            guard let self,let data=self.model.data else{return}
            let warning=data.telemetry.stale || ["warning","critical"].contains(data.telemetry.level ?? "")
            let needsRoom=warning || !data.worker_alive || data.settings.safety_latch != nil
            if needsRoom != self.roomyCompact {self.roomyCompact=needsRoom;if self.model.compact {self.applyWindowPreferences()}}
            self.item.button?.contentTintColor=warning ? .systemOrange : nil
            self.item.button?.title=(warning ? " ⚠" : "")+L("menubar.status", data.active == nil ? (data.settings.mode == "smart" ? L("state.waiting_idle") : data.settings.mode == "paused" ? L("state.paused") : L("status.queued")) : L("status.running"))
        }
        model.start()
    }
    func localizeApp() {
        panel.title=model.isPreview ? L("app.preview_title") : L("app.title")
        item.button?.image=NSImage(systemSymbolName:"film.stack",accessibilityDescription:L("app.title"))
        let menu=NSMenu();menu.autoenablesItems=false
        menu.addItem(withTitle:L("menubar.toggle"),action:#selector(toggle),keyEquivalent:"")
        let stopItem=menu.addItem(withTitle:L("menubar.stop"),action:#selector(stop),keyEquivalent:"")
        stopItem.isEnabled = !model.isPreview
        menu.addItem(.separator())
        let languages=NSMenu()
        for choice in LanguageChoice.allCases {
            let entry=languages.addItem(withTitle:choice.title,action:#selector(changeLanguage(_:)),keyEquivalent:"")
            entry.representedObject=choice.rawValue;entry.target=self
            entry.state=model.language == choice ? .on : .off
        }
        menu.addItem(withTitle:L("language.menu"),action:nil,keyEquivalent:"").submenu=languages
        menu.addItem(.separator())
        menu.addItem(withTitle:L("menubar.quit"),action:#selector(quit),keyEquivalent:"q")
        for entry in menu.items {entry.target=self};item.menu=menu
        item.button?.title=L("tab.queue")
        model.onRefresh?()
    }
    @objc func changeLanguage(_ sender:NSMenuItem) {
        guard let raw=sender.representedObject as? String,let choice=LanguageChoice(rawValue:raw) else {return}
        model.setLanguage(choice)
    }
    func applyWindowPreferences() {
        panel.level=model.pinned ? .floating : .normal
        panel.isFloatingPanel=model.pinned
        panel.minSize=NSSize(width:380,height:model.compact ? 510 : 600)
        var frame=panel.frame
        let height:CGFloat=model.compact ? (roomyCompact ? 590 : 520) : 640
        frame.origin.y += frame.height-height;frame.size.height=height
        panel.setFrame(frame,display:true,animate:false)
    }
    @objc func toggle() {if panel.isVisible {panel.orderOut(nil)} else {panel.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)}}
    @objc func stop() {model.action(["stop"])}
    @objc func quit() {NSApp.terminate(nil)}
}
#if !LOCALIZATION_TESTS
@main struct Entry {
    @MainActor static func main() {
        let app=NSApplication.shared
        app.setActivationPolicy(.accessory)
        let delegate=Delegate();app.delegate=delegate;app.run()
    }
}
#endif
