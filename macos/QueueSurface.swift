import AppKit
import SwiftUI

private let accent = Color(red:0.20,green:0.62,blue:1.0)
private let lemon = Color(red:1.0,green:0.78,blue:0.18)
private let panelBackground = Color(red:0.145,green:0.15,blue:0.19)
private let queueFooterColor = Color(red:0.19,green:0.195,blue:0.24)

private struct QuietActionStyle:ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration:Configuration)->some View {
        configuration.label.font(.system(size:12,weight:.medium)).padding(.horizontal,12).padding(.vertical,7)
            .foregroundStyle(enabled ? Color.white : Color.secondary)
            .background(Color.white.opacity(configuration.isPressed ? 0.14 : 0.065),in:RoundedRectangle(cornerRadius:5))
            .overlay(RoundedRectangle(cornerRadius:5).strokeBorder(Color.white.opacity(0.08)))
    }
}

enum RunMode: String, CaseIterable, Identifiable {
    case manual, smart, auto
    var id:String {rawValue}
    var title:String {switch self {case .manual:return L("mode.manual");case .smart:return L("mode.smart");case .auto:return L("mode.scheduled")}}
    var command:String {self == .manual ? "start" : rawValue}
    var startTitle:String {switch self {case .manual:return L("mode.start_manual");case .smart:return L("mode.start_smart");case .auto:return L("mode.start_scheduled")}}
    func detail(_ s:QueueSettings) -> String {
        switch self {
        case .manual:return L("mode.manual_detail")
        case .smart:return L("mode.smart_detail", s.smart_idle_minutes)
        case .auto:return s.require_idle ? L("mode.schedule_idle_detail",s.window.start,s.window.end,s.idle_minutes) : L("mode.schedule_detail",s.window.start,s.window.end)
        }
    }
}

extension QueueJob {
    var shortTitle:String {let parts=title.components(separatedBy:" · ");return parts.count>=3 ? parts[1] : title}
    var context:String {
        let parts=title.components(separatedBy:" · ")
        if parts.count>=3,let t=Double(parts.last!.replacingOccurrences(of:"s",with:"")) {
            return parts[0]+L("job.timestamp", Int(t)/60,Int(t)%60)
        }
        if provider == nil || provider == "h3",let seconds {return L("job.video_seconds",seconds)}
        if provider == nil || provider == "h3",let summary,let localized=videoSummary(summary) {return localized}
        if provider == "tts",let summary,let localized=ttsSummary(summary) {return localized}
        return summary ?? seconds.map {L("job.video_seconds", $0)} ?? (provider_label ?? L("job.local"))
    }
    var artifactIcon:String {output_kind == "audio" ? "waveform" : output_kind == "video" || provider == nil ? "film" : "doc"}
    var previewTitle:String {output_kind == "audio" ? L("job.preview_audio") : output_kind == "video" || provider == nil ? L("job.preview_video") : L("job.open_artifact")}
    var phaseTitle:String { ["waiting_resource":L("phase.waiting_resource"),"preparing":L("phase.preparing"),"restoring":L("phase.restoring")][phase ?? ""] ?? L("job.elapsed", duration(elapsed)) }
    var modelName:String {["native20":L("model.native20"),"lightx3":L("model.lightx3"),"tf3":L("model.tf3")][profile] ?? profile}
}
extension QueueSnapshot {
    var stopping:Bool {active?.stop_requested == true || active?.status == "cancel_requested"}
    var warning:Bool {telemetry.stale || ["warning","critical"].contains(telemetry.level ?? "")}
    var stateTitle:String {
        if !worker_alive {return L("state.worker_unavailable")}
        if stopping {return L("state.stopping")}
        if active?.phase == "waiting_resource" {return L("state.waiting_resource")}
        if active != nil {return settings.mode == "paused" ? L("state.pause_after") : L("state.running")}
        if settings.safety_latch != nil {return L("state.protected")}
        if settings.mode == "paused" {return L("state.paused")}
        return settings.mode == "smart" ? L("state.waiting_idle") : settings.mode == "auto" ? L("schedule.title") : L("state.waiting_jobs")
    }
    var stateColor:Color {
        if settings.safety_latch != nil || telemetry.level == "critical" {return .red}
        if !worker_alive || warning {return .orange}
        if stopping || settings.mode == "paused" {return .secondary}
        return accent
    }
}

struct TaskActions: View {
    @ObservedObject var model:QueueModel
    let job:QueueJob
    var body:some View {
        if let output=job.output {
            Button(job.previewTitle,systemImage:job.artifactIcon) {NSWorkspace.shared.open(URL(fileURLWithPath:output))}
            Button(L("action.reveal"),systemImage:"folder") {model.action(["reveal",job.id])}
        }
        if job.status == "queued" {Button(L("action.prioritize"),systemImage:"arrow.up.to.line") {model.action(["prioritize",job.id])}}
        if ["failed","cancelled"].contains(job.status) {Button(L("action.retry"),systemImage:"arrow.clockwise") {model.action(["retry",job.id])}}
        if let log=job.log {Button(L("action.logs"),systemImage:"doc.text") {NSWorkspace.shared.open(URL(fileURLWithPath:log))}}
        Button(L("action.copy_id"),systemImage:"doc.on.doc") {NSPasteboard.general.clearContents();NSPasteboard.general.setString(job.id,forType:.string)}
        if ["queued","running"].contains(job.status) {Divider();Button(L("action.cancel_job"),role:.destructive) {model.action(["cancel",job.id])}}
    }
}
struct TaskRow: View {
    @ObservedObject var model:QueueModel
    let job:QueueJob
    @State private var hover=false
    var body:some View {
        HStack(spacing:12) {
            Image(systemName:job.status == "completed" ? "checkmark.circle" : job.status == "failed" ? "exclamationmark.circle" : job.artifactIcon)
                .foregroundStyle(job.status == "completed" ? accent : job.status == "failed" ? Color.orange : Color.secondary)
            VStack(alignment:.leading,spacing:5) {
                Text(job.shortTitle).font(.system(size:13,weight:.medium)).lineLimit(1).help(job.title)
                Text(job.context).font(.system(size:12)).foregroundStyle(.secondary).lineLimit(1)
                if let error=job.error {Text(BackendText.diagnostic(error)).font(.caption).foregroundStyle(.orange).lineLimit(2).help(error)}
            }
            Spacer(minLength:4)
            if job.status == "completed",let output=job.output {
                Button {NSWorkspace.shared.open(URL(fileURLWithPath:output))} label:{Image(systemName:"play.circle")}
                    .buttonStyle(.plain).font(.system(size:19)).help(job.previewTitle).accessibilityLabel(L("accessibility.preview", job.shortTitle))
            } else {
                Text(job.status == "queued" ? job.estimate.seconds.map {L("estimate.approx", duration($0))} ?? L("estimate.unknown") : label(job.status)).font(.system(size:12)).foregroundStyle(.secondary)
            }
            Menu {TaskActions(model:model,job:job)} label:{Image(systemName:"ellipsis").frame(width:24,height:26)}
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().help(L("action.manage")).accessibilityLabel(L("accessibility.manage", job.shortTitle))
        }.padding(.horizontal,2).padding(.vertical,9)
            .background(hover ? Color.primary.opacity(0.05) : .clear,in:RoundedRectangle(cornerRadius:8))
            .onHover {hover=$0}.contextMenu {TaskActions(model:model,job:job)}
    }
}

struct CurrentTask: View {
    @ObservedObject var model:QueueModel
    let d:QueueSnapshot
    let selected:RunMode
    var body:some View {
        VStack(alignment:.leading,spacing:10) {
            if let job=d.active {
                HStack {
                    Text(L("job.current")).font(.system(size:12,weight:.medium)).foregroundStyle(.secondary)
                    Spacer()
                    Menu {TaskActions(model:model,job:job)} label:{Image(systemName:"ellipsis").frame(width:24,height:20)}
                        .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().accessibilityLabel(L("job.actions"))
                }
                VStack(alignment:.leading,spacing:5) {
                    Text(job.shortTitle).font(.system(size:19,weight:.semibold)).lineLimit(2).help(job.title)
                    Text((job.provider == nil || job.provider == "h3") ? job.context+"  /  "+job.modelName : job.context).font(.system(size:12)).foregroundStyle(.secondary)
                }
                VStack(alignment:.leading,spacing:8) {
                    if let progress=job.progress {ProgressView(value:progress).tint(accent)}
                    HStack {
                        if job.progress == nil {ProgressView().controlSize(.small).scaleEffect(0.75).frame(width:14,height:14)}
                        Text(d.stopping ? L("job.releasing") : job.phaseTitle).monospacedDigit()
                        Spacer()
                        if let progress=job.progress {Text(N("%.0f%%",progress*100)).monospacedDigit()}
                        else {Text(job.estimate.seconds.map {L("estimate.task", duration($0))} ?? L("estimate.unknown")).help(duration(job.estimate.low)+" - "+duration(job.estimate.high))}
                    }.font(.system(size:12)).foregroundStyle(.secondary)
                }
                HStack(spacing:14) {
                    if d.stopping {
                        Text(L("job.requeue_after_stop")).font(.caption).foregroundStyle(.secondary)
                    } else {
                        Button(d.settings.mode == "paused" ? L("action.resume") : L("state.pause_after")) {model.action([d.settings.mode == "paused" ? selected.command : "pause"])}
                            .buttonStyle(QuietActionStyle())
                            .help(d.settings.mode == "paused" ? L("action.resume_help") : L("action.pause_help"))
                        Spacer()
                        Button(L("action.stop"),systemImage:"stop.fill") {model.action(["stop"])}
                            .buttonStyle(.plain).foregroundStyle(.red).help(L("action.stop_help"))
                    }
                }.controlSize(.regular).disabled(model.busy || model.isPreview)
            } else {
                HStack(alignment:.top,spacing:13) {
                    Image(systemName:d.settings.safety_latch != nil ? "shield.lefthalf.filled.trianglebadge.exclamationmark" : d.counts["queued",default:0]>0 ? (d.settings.mode == "smart" ? "moon.zzz" : "pause.circle") : (d.total_jobs==0 ? "plus.rectangle.on.rectangle" : "checkmark.circle"))
                        .font(.system(size:27,weight:.light)).foregroundStyle(d.stateColor)
                    VStack(alignment:.leading,spacing:6) {
                        Text(idleTitle).font(.system(size:20,weight:.semibold))
                        Text(idleDetail).font(.system(size:13)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
                    }
                    Spacer(minLength:0)
                }
            }
        }.frame(maxWidth:.infinity,alignment:.leading)
    }
    var idleTitle:String {
        if d.settings.safety_latch != nil {return L("idle.protected")}
        if d.counts["queued",default:0]==0 {return d.counts["failed",default:0]>0 ? L("idle.needs_attention") : d.total_jobs==0 ? L("idle.first_job") : d.counts["completed",default:0]==d.total_jobs ? L("idle.completed") : L("idle.none_waiting")}
        if d.settings.mode == "smart" {return d.smart.ready ? L("idle.ready") : L("idle.waiting")}
        if d.settings.mode == "auto" {return d.reason == BackendText.waitingIdle ? L("idle.waiting") : d.reason == BackendText.waitingWindow ? L("idle.window") : L("idle.starting")}
        return L("idle.queue_ready")
    }
    var idleDetail:String {
        if d.settings.safety_latch != nil {return L("idle.protection_help")}
        if d.counts["queued",default:0]==0 {return d.counts["failed",default:0]>0 ? L("idle.failure_help") : d.total_jobs==0 ? L("idle.import_help") : L("idle.outputs_help")}
        if d.settings.mode == "smart" {return smartDetail(d.smart)}
        if d.settings.mode == "auto" {return L("idle.schedule", d.settings.window.start, d.settings.window.end)}
        return L("idle.queued", d.counts["queued",default:0])
    }
}

struct ModeControl: View {
    @ObservedObject var model:QueueModel
    let d:QueueSnapshot
    @Binding var selection:String
    let configure:()->Void
    var chosen:RunMode {RunMode(rawValue:selection) ?? .manual}
    var differs:Bool {d.settings.mode != "paused" && d.settings.mode != selection}
    var body:some View {
        VStack(alignment:.leading,spacing:9) {
            HStack {
                Text(L("mode.title")).font(.system(size:12,weight:.medium)).foregroundStyle(.secondary)
                Spacer()
                if chosen != .manual {Button(L("action.settings_more"),action:configure).buttonStyle(.plain).font(.system(size:12)).foregroundStyle(accent)}
            }
            Picker(L("mode.title"),selection:$selection) {
                ForEach(RunMode.allCases) {m in Text(m.title).tag(m.rawValue)}
            }.pickerStyle(.segmented).labelsHidden().disabled(model.busy)
            Text(chosen.detail(d.settings)).font(.system(size:12)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
            if differs {
                HStack {
                    Button(L("action.apply_mode", chosen.title)) {model.action([chosen.command])}.buttonStyle(.borderedProminent).disabled(model.isPreview)
                    Button(L("mode.keep")) {selection=d.settings.mode}.buttonStyle(.plain).foregroundStyle(.secondary)
                }.disabled(model.busy)
                Text(L("mode.not_applied")).font(.caption).foregroundStyle(.secondary)
            } else if d.active == nil {
                HStack {
                    if d.settings.mode == "paused" {
                        Button {model.action([chosen.command])} label:{Label(chosen.startTitle,systemImage:chosen == .manual ? "play.fill" : "power")}
                            .buttonStyle(.borderedProminent).disabled(chosen == .manual && d.counts["queued",default:0]==0)
                    } else {
                        Button(L("action.pause_waiting"),systemImage:"pause.fill") {model.action(["pause"])}.buttonStyle(.bordered)
                    }
                    Spacer()
                    if d.settings.mode == "smart" {Text(idleLabel(d.smart.idle_seconds)).font(.caption).foregroundStyle(.secondary).monospacedDigit()}
                }.disabled(model.busy || model.isPreview)
            }
        }.tint(accent)
    }
}

struct UsageRing:View {
    let title:String
    let value:Double?
    let detail:String
    let color:Color
    let explanation:String
    var body:some View {
        VStack(spacing:5) {
            ZStack {
                Circle().stroke(Color.primary.opacity(0.07),lineWidth:5)
                if let percent=usagePercent(value) {
                    Circle().trim(from:0,to:percent/100)
                        .stroke(color,style:StrokeStyle(lineWidth:5,lineCap:.round))
                        .rotationEffect(.degrees(-90))
                    Text(N("%.0f%%",percent)).font(.system(size:17,weight:.semibold)).monospacedDigit()
                } else {Text("—").font(.system(size:19)).foregroundStyle(.secondary)}
            }.frame(width:54,height:54).padding(3)
            Text(title).font(.system(size:12,weight:.medium))
            Text(detail).font(.system(size:11)).monospacedDigit().foregroundStyle(.secondary).lineLimit(1)
        }.frame(maxWidth:.infinity).help(explanation)
            .accessibilityElement(children:.ignore)
            .accessibilityLabel(L("accessibility.usage", title))
            .accessibilityValue(L("accessibility.measurement",usagePercent(value).map{N("%.0f%%",$0)} ?? L("metric.pending"),detail))
    }
}

struct HealthDetails:View {
    let d:QueueSnapshot
    let openSettings:()->Void
    func row(_ name:String,_ value:String)->some View {HStack {Text(name).foregroundStyle(.secondary);Spacer();Text(value).monospacedDigit()}.font(.system(size:12))}
    var body:some View {
        VStack(alignment:.leading,spacing:13) {
            HStack {Text(L("health.title")).font(.headline);Spacer();Button(L("health.protection_settings"),action:openSettings).buttonStyle(.plain).foregroundStyle(accent)}
            row(L("health.temperatures"),d.telemetry.stale ? L("metric.unavailable") : metric(d.telemetry.cpu_c,"°C")+" / "+metric(d.telemetry.gpu_c,"°C"))
            row(L("health.chip_power"),d.telemetry.stale ? L("metric.unavailable") : metric(d.telemetry.chip_w," W"))
            Divider()
            row(L("health.chip_energy"),metric(d.telemetry.chip_wh," Wh"))
            row(L("health.system_energy"),metric(d.telemetry.wall_wh," Wh"))
            row(L("energy.remaining_long"),d.energy_remaining_kwh.map{L("energy.kwh_long", $0)} ?? L("energy.waiting_power"))
            row(L("energy.cost"),d.energy_cost_estimate.map{N("¥%.2f",$0)} ?? L("energy.waiting_power"))
            Divider()
            row(L("health.thresholds"),N("%.0f / %.0f°C",d.settings.safety.cpu_warn_c,d.settings.safety.gpu_warn_c))
            row(L("safety.overheat"),L("safety.stop_detail", d.settings.safety.stop_c,d.settings.safety.hold_seconds))
            Text(L("health.explanation")).font(.system(size:12)).foregroundStyle(.secondary)
        }.padding(18).frame(width:340)
    }
}

struct QueueView:View {
    @ObservedObject var model:QueueModel
    @AppStorage("queue.selectedMode") private var selection="manual"
    @State private var page="queue"
    @State private var filter="queued"
    @State private var showSafety=false
    @State private var showSchedule=false
    @State private var showSmart=false
    @State private var showMode=false
    var filters:[(String,String)] {[("queued",L("status.queued")),("completed",L("filter.completed")),("failed",L("status.failed")),("cancelled",L("status.cancelled")),("all",L("filter.all"))]}
    var body:some View {
        VStack(spacing:0) {
            header
            Divider()
            if let d=model.data {
                if !d.worker_alive || d.warning || d.settings.safety_latch != nil {alert(d).padding(.horizontal,16).padding(.top,10)}
                if let error=model.error {
                    HStack(alignment:.top) {
                        Image(systemName:"exclamationmark.circle");Text(error.text).lineLimit(3);Spacer()
                        Button {model.error=nil} label:{Image(systemName:"xmark")}.buttonStyle(.plain).accessibilityLabel(L("error.dismiss"))
                    }.font(.system(size:12)).foregroundStyle(.red).padding(10)
                }
                healthStrip(d).padding(.horizontal,18).padding(.vertical,14)
                Divider().padding(.horizontal,16)
                if page == "queue" {
                    VStack(spacing:12) {
                        CurrentTask(model:model,d:d,selected:RunMode(rawValue:selection) ?? .manual)
                        if d.active == nil {
                            ModeControl(model:model,d:d,selection:$selection,configure:configureMode)
                        }
                        if !model.compact {queueList(d)} else {
                            Spacer(minLength:0)
                            queueSummary(d)
                        }
                    }.padding(16).frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.top)
                } else {
                    ScrollView {systemContent(d).padding(16)}.frame(maxHeight:.infinity)
                }
                footer(d)
            } else {
                VStack(spacing:12) {
                    ProgressView();Text(model.error?.text ?? L("queue.loading")).foregroundStyle(.secondary)
                    if model.error != nil {Button(L("action.try_again")){model.refresh()}}
                }.frame(maxWidth:.infinity,maxHeight:.infinity)
            }
        }.frame(minWidth:380,minHeight:model.compact ? 490 : 570)
            .background(panelBackground).tint(accent).preferredColorScheme(.dark)
            .environment(\.locale,L10n.locale)
            .onAppear {if let mode=model.data?.settings.mode,mode != "paused" {selection=mode}}
            .onChange(of:model.data?.settings.mode) {_,mode in if let mode,mode != "paused" {selection=mode}}
            .sheet(isPresented:$showSafety) {if let s=model.data?.settings.safety {SafetyView(model:model,policy:s)}}
            .sheet(isPresented:$showSmart) {if let s=model.data?.settings {SmartModeView(model:model,minutes:s.smart_idle_minutes)}}
            .sheet(isPresented:$showSchedule) {if let s=model.data?.settings {ScheduleView(model:model,start:s.window.start,end:s.window.end,idle:s.idle_minutes,requireIdle:s.require_idle,stopAtEnd:s.stop_at_end,timezone:s.window.timezone)}}
    }
    func configureMode() {
        showMode=false
        if selection == "smart" {showSmart=true} else {showSchedule=true}
    }
    var header:some View {
        HStack(alignment:.bottom,spacing:22) {
            ForEach([("queue",L("tab.queue")),("system",L("tab.system"))],id:\.0) {key,title in
                Button {page=key} label:{
                    VStack(spacing:11) {
                        Text(title).font(.system(size:13,weight:page==key ? .semibold : .regular))
                            .foregroundStyle(page==key ? Color.white : Color.secondary)
                        Rectangle().fill(page==key ? lemon : .clear).frame(height:2)
                    }.fixedSize(horizontal:true,vertical:false)
                }.buttonStyle(.plain).accessibilityLabel(L("accessibility.tab", title)).accessibilityAddTraits(page==key ? .isSelected : [])
            }
            Spacer()
            if let d=model.data {
                HStack(spacing:5) {Circle().fill(d.stateColor).frame(width:5,height:5);Text(d.stateTitle)}
                    .font(.system(size:11)).foregroundStyle(.secondary).padding(.bottom,13)
            }
        }.padding(.horizontal,22).padding(.top,24)
    }
    func footer(_ d:QueueSnapshot)->some View {
        HStack(spacing:12) {
            Menu {
                Picker(L("language.menu"),selection:Binding(get:{model.language},set:model.setLanguage)) {
                    ForEach(LanguageChoice.allCases) {choice in Text(choice.title).tag(choice)}
                }
                Divider()
                Button(L("menu.protection"),systemImage:"shield"){showSafety=true}
                Button(L("menu.idle"),systemImage:"moon.zzz"){showSmart=true}
                Button(L("menu.schedule"),systemImage:"clock"){showSchedule=true}
                Divider()
                Button(L("action.refresh"),systemImage:"arrow.clockwise"){model.refresh()}
                Button(L("action.import_more"),systemImage:"plus"){importTask()}.disabled(model.isPreview)
            } label:{Image(systemName:"gearshape.fill").frame(width:24,height:26)}
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().accessibilityLabel(L("action.settings"))
            Spacer(minLength:0)
            Button {showMode.toggle()} label:{
                HStack(spacing:6) {
                    Image(systemName:d.settings.mode == "smart" ? "moon.zzz" : d.settings.mode == "auto" ? "clock" : "slider.horizontal.3")
                    Text(d.settings.mode == "paused" ? L("mode.title") : L("mode.running", RunMode(rawValue:d.settings.mode)?.title ?? L("mode.manual")))
                    Image(systemName:"chevron.up").font(.system(size:8))
                }.font(.system(size:12,weight:.medium)).foregroundStyle(.white)
                    .padding(.horizontal,12).padding(.vertical,7).background(panelBackground,in:RoundedRectangle(cornerRadius:4))
            }.buttonStyle(.plain).accessibilityLabel(L("mode.adjust"))
                .popover(isPresented:$showMode,arrowEdge:.bottom) {
                    ModeControl(model:model,d:d,selection:$selection,configure:configureMode).padding(18).frame(width:330).preferredColorScheme(.dark)
                }
            Spacer(minLength:0)
            Button {model.togglePinned()} label:{Image(systemName:model.pinned ? "pin.fill" : "pin").frame(width:24,height:26).foregroundStyle(model.pinned ? lemon : Color.secondary)}
                .help(model.pinned ? L("window.unpin") : L("window.pin")).accessibilityLabel(model.pinned ? L("window.unpin") : L("window.pin"))
            Button {model.toggleCompact()} label:{Image(systemName:model.compact ? "rectangle.expand.vertical" : "rectangle.compress.vertical").frame(width:24,height:26)}
                .help(model.compact ? L("window.expand") : L("window.compact")).accessibilityLabel(model.compact ? L("window.expand") : L("window.compact"))
        }.buttonStyle(.plain).foregroundStyle(.secondary).padding(.horizontal,16).frame(height:46).background(queueFooterColor)
    }
    func alert(_ d:QueueSnapshot)->some View {
        HStack(alignment:.top,spacing:8) {
            Image(systemName:"exclamationmark.triangle.fill")
            Text(!d.worker_alive ? L("alert.worker") : d.telemetry.stale ? (d.settings.safety.require_telemetry ? L("alert.telemetry") : L("alert.telemetry_disabled")) : d.settings.safety_latch.map{BackendText.diagnostic($0.reason)} ?? L("alert.warning")).fixedSize(horizontal:false,vertical:true)
            Spacer(minLength:0)
            Button(d.worker_alive ? L("action.view") : L("action.connect")) {if d.worker_alive {showSafety=true} else {model.action(["init"])}}.buttonStyle(.plain)
        }.font(.system(size:12)).foregroundStyle(d.stateColor).padding(10).background(d.stateColor.opacity(0.10),in:RoundedRectangle(cornerRadius:6))
    }
    func queueSummary(_ d:QueueSnapshot)->some View {
        HStack {
            Text(L("queue.completed", d.counts["completed",default:0], d.total_jobs))
            Spacer()
            Text(d.total_jobs==0 ? L("queue.empty") : d.counts["queued",default:0]==0 && d.active==nil ? L("queue.none_waiting") : d.unknown_estimates>0 ? L("estimate.partial") : L("estimate.remaining", duration(d.estimate_seconds)))
                .help(L("estimate.range", duration(d.estimate_low),duration(d.estimate_high)))
        }.font(.system(size:11)).foregroundStyle(.secondary)
    }
    func queueList(_ d:QueueSnapshot)->some View {
        let jobs=d.jobs.filter{$0.id != d.active?.id && (filter == "all" || $0.status == filter)}
        return VStack(alignment:.leading,spacing:7) {
            Divider().padding(.bottom,3)
            HStack {
                Picker(L("filter.title"),selection:$filter) {ForEach(filters,id:\.0) {key,title in Text("\(title) \(key == "all" ? d.total_jobs : d.counts[key,default:0])").tag(key)}}
                    .pickerStyle(.menu).labelsHidden().fixedSize().controlSize(.small)
                Spacer()
                Button {importTask()} label:{Label(L("action.import"),systemImage:"plus")}.buttonStyle(.plain).font(.system(size:11)).foregroundStyle(accent).help(L("action.import_help")).disabled(model.isPreview)
            }
            ScrollView {
                if jobs.isEmpty {
                    VStack(spacing:6) {
                        Text(emptyTitle(d)).font(.system(size:13,weight:.medium))
                        Text(emptyDetail(d)).font(.system(size:12)).multilineTextAlignment(.center)
                    }.foregroundStyle(.secondary).frame(maxWidth:.infinity).padding(.vertical,22)
                } else {
                    LazyVStack(spacing:0) {ForEach(jobs) {job in TaskRow(model:model,job:job)}}
                }
            }.frame(maxWidth:.infinity,maxHeight:.infinity)
            queueSummary(d)
        }.frame(maxHeight:.infinity)
    }
    func emptyTitle(_ d:QueueSnapshot)->String {
        if d.total_jobs>200 && d.counts[filter,default:0]>0 {return L("empty.not_loaded")}
        return ["queued":L("empty.queued"),"completed":L("empty.completed"),"failed":L("empty.failed"),"cancelled":L("empty.cancelled"),"all":L("empty.all")][filter] ?? L("queue.empty")
    }
    func emptyDetail(_ d:QueueSnapshot)->String {
        if d.total_jobs>200 && d.counts[filter,default:0]>0 {return L("empty.limit")}
        return filter == "completed" ? L("empty.completed_help") : filter == "queued" ? (d.active == nil ? L("empty.import_help") : L("empty.active_help")) : L("empty.filter_help")
    }
    func healthStrip(_ d:QueueSnapshot)->some View {
        let t=d.telemetry
        let memory=t.stale ? nil : memoryUsagePercent(used:t.ram_used_gib,total:t.ram_total_gib)
        let memoryDetail=memory != nil ? N("%.1f / %.0f GiB",t.ram_used_gib!,t.ram_total_gib!) : (t.stale ? L("metric.lost") : L("metric.pending"))
        return HStack(alignment:.top,spacing:8) {
            UsageRing(title:"CPU",value:model.cpuUsage,detail:t.stale ? L("metric.temperature_lost") : metric(t.cpu_c,"°C"),color:accent,explanation:L("metric.cpu_help"))
            UsageRing(title:"GPU",value:t.stale ? nil : t.gpu_percent,detail:t.stale ? L("metric.lost") : metric(t.gpu_c,"°C"),color:Color(red:0.16,green:0.80,blue:0.66),explanation:L("metric.gpu_help"))
            UsageRing(title:L("metric.memory"),value:memory,detail:memoryDetail,color:lemon,explanation:L("metric.memory_help"))
        }
    }
    func systemRow(_ title:String,_ value:String,icon:String)->some View {
        HStack(spacing:9) {
            Image(systemName:icon).frame(width:16).foregroundStyle(.secondary)
            Text(title).foregroundStyle(.secondary)
            Spacer()
            Text(value).fontWeight(.medium).monospacedDigit()
        }.font(.system(size:12))
    }
    func protectionTile(_ title:String,icon:String,value:String,detail:String,enabled:Bool=true)->some View {
        Button {showSafety=true} label:{
            VStack(alignment:.leading,spacing:9) {
                Label(title,systemImage:icon).font(.system(size:11)).foregroundStyle(.secondary)
                HStack(alignment:.firstTextBaseline) {
                    Text(value).font(.system(size:16,weight:.semibold)).monospacedDigit()
                    Spacer(minLength:0)
                    Text(detail).font(.system(size:10)).foregroundStyle(enabled ? Color.secondary : lemon)
                }
            }.padding(11).frame(maxWidth:.infinity,alignment:.leading)
                .overlay(RoundedRectangle(cornerRadius:5).strokeBorder(Color.white.opacity(0.10)))
        }.buttonStyle(.plain).help(L("safety.open"))
    }
    func systemContent(_ d:QueueSnapshot)->some View {
        VStack(alignment:.leading,spacing:12) {
            HStack {Text(L("energy.title")).font(.system(size:12,weight:.semibold));Spacer();Text(L("metric.interval")).font(.system(size:10)).foregroundStyle(.secondary)}
            systemRow(L("energy.chip_power"),d.telemetry.stale ? L("metric.pending") : metric(d.telemetry.chip_w," W"),icon:"bolt")
            systemRow(L("energy.totals"),metric(d.telemetry.chip_wh," Wh")+" / "+metric(d.telemetry.wall_wh," Wh"),icon:"chart.bar")
            systemRow(L("energy.remaining"),d.energy_remaining_kwh.map{L("energy.kwh", $0)} ?? L("energy.waiting"),icon:"hourglass")
            systemRow(L("energy.cost"),d.energy_cost_estimate.map{N("¥%.2f",$0)} ?? L("energy.waiting"),icon:"yensign.circle")
            Divider()
            HStack {Label(L("safety.heading"),systemImage:"shield.lefthalf.filled").font(.system(size:12,weight:.semibold));Spacer();Button(L("action.settings_more")){showSafety=true}.buttonStyle(.plain).font(.system(size:11)).foregroundStyle(accent)}
            LazyVGrid(columns:[GridItem(.flexible()),GridItem(.flexible())],spacing:8) {
                protectionTile(L("safety.cpu"),icon:"cpu",value:N("%.0f°C",d.settings.safety.cpu_warn_c),detail:L("safety.hold", d.settings.safety.hold_seconds))
                protectionTile(L("safety.gpu"),icon:"square.stack.3d.up",value:N("%.0f°C",d.settings.safety.gpu_warn_c),detail:L("safety.hold", d.settings.safety.hold_seconds))
                protectionTile(L("safety.overheat"),icon:"thermometer.high",value:N("%.0f°C",d.settings.safety.stop_c),detail:d.settings.safety.stop_on_overheat ? L("safety.enabled") : L("safety.disabled"),enabled:d.settings.safety.stop_on_overheat)
                protectionTile(L("safety.monitoring"),icon:"sensor",value:L("safety.seconds", d.settings.safety.stale_seconds),detail:d.settings.safety.require_telemetry ? L("safety.enabled") : L("safety.disabled"),enabled:d.settings.safety.require_telemetry)
            }
            Text(L("energy.explanation")).font(.system(size:11)).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true)
        }
    }
    func importTask() {
        let panel=NSOpenPanel();panel.allowedContentTypes=[.json];panel.canChooseDirectories=false
        panel.title=L("action.import_more");panel.prompt=L("action.import");panel.message=L("action.import_help")
        if panel.runModal() == .OK,let url=panel.url {
            let value=(try? Data(contentsOf:url)).flatMap {try? JSONSerialization.jsonObject(with:$0)} as? [String:Any]
            if value?["jobs"] != nil {model.action(["enqueue-batch",url.path])}
            else {model.action(["enqueue",url.path,"--title",url.deletingPathExtension().lastPathComponent])}
        }
    }
}
