import Foundation
import Darwin

func usagePercent(_ value:Double?)->Double? {
    guard let value,value.isFinite,(0...100).contains(value) else {return nil}
    return value
}

func memoryUsagePercent(used:Double?,total:Double?)->Double? {
    guard let used,let total,used.isFinite,total.isFinite,total>0 else {return nil}
    return usagePercent(used/total*100)
}

// Delta of all CPU ticks: 100% means all logical cores are busy, not one core.
struct CPULoadAccumulator {
    private var previous:[UInt32]?
    private var sampledAt:TimeInterval?
    mutating func sample(_ ticks:[UInt32]?,at now:TimeInterval)->Double? {
        guard let ticks,ticks.count==4 else {previous=nil;sampledAt=nil;return nil}
        defer {previous=ticks;sampledAt=now}
        guard let previous,let sampledAt,now>sampledAt,now-sampledAt<=15 else {return nil}
        let delta=zip(ticks,previous).map {UInt64($0 &- $1)}
        let total=delta.reduce(0,+)
        guard total>0 else {return nil}
        return usagePercent(Double(total-delta[Int(CPU_STATE_IDLE)])/Double(total)*100)
    }
}

final class SystemCPUSampler {
    private var load=CPULoadAccumulator()
    func sample()->Double? {
        var info=host_cpu_load_info_data_t()
        var count=mach_msg_type_number_t(MemoryLayout<host_cpu_load_info_data_t>.size/MemoryLayout<integer_t>.size)
        let host=mach_host_self()
        defer {mach_port_deallocate(mach_task_self_,host)}
        let result=withUnsafeMutablePointer(to:&info) {pointer in
            pointer.withMemoryRebound(to:integer_t.self,capacity:Int(count)) {
                host_statistics(host,HOST_CPU_LOAD_INFO,$0,&count)
            }
        }
        let ticks=result == KERN_SUCCESS ? [info.cpu_ticks.0,info.cpu_ticks.1,info.cpu_ticks.2,info.cpu_ticks.3] : nil
        return load.sample(ticks,at:ProcessInfo.processInfo.systemUptime)
    }
}
