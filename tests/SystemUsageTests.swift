import Foundation

@main struct SystemUsageTests {
    static func main() {
        var cpu=CPULoadAccumulator()
        precondition(cpu.sample([100,50,200,0],at:0)==nil, "First sample must not imply zero usage")
        precondition(cpu.sample([120,60,270,0],at:3)==30, "Use delta busy ticks across all cores")
        precondition(cpu.sample([120,60,270,0],at:6)==nil, "Unchanged counters are unknown")
        precondition(cpu.sample([140,60,270,0],at:9)==100, "Fully busy interval")
        precondition(cpu.sample([140,60,300,0],at:12)==0, "Fully idle interval")
        precondition(cpu.sample([200,80,320,0],at:40)==nil, "Discard stale interval after sleep")
        precondition(cpu.sample(nil,at:43)==nil)
        precondition(cpu.sample([210,80,330,0],at:46)==nil, "Failure resets baseline")
        var rollover=CPULoadAccumulator()
        _=rollover.sample([UInt32.max-4,0,UInt32.max-4,0],at:0)
        precondition(rollover.sample([5,0,5,0],at:3)==50, "Handle 32-bit counter rollover")
        precondition(memoryUsagePercent(used:48,total:96)==50)
        precondition(memoryUsagePercent(used:nil,total:96)==nil)
        precondition(memoryUsagePercent(used:1,total:0)==nil)
        precondition(memoryUsagePercent(used:97,total:96)==nil)
        precondition(usagePercent(.nan)==nil && usagePercent(-1)==nil && usagePercent(101)==nil)
        let live=SystemCPUSampler()
        precondition(live.sample()==nil)
        // Host counters may be unchanged over one 100ms interval. Keep nil's
        // meaning intact and wait for a fresh sample within a bounded window.
        let deadline=ProcessInfo.processInfo.systemUptime+2
        var reading:Double?
        repeat {
            Thread.sleep(forTimeInterval:0.1)
            reading=live.sample()
        } while reading == nil && ProcessInfo.processInfo.systemUptime<deadline
        guard let value=reading,(0...100).contains(value) else {fatalError("Host CPU sample unavailable")}
        print("System usage checks passed; live CPU sample: \(value)%")
    }
}
