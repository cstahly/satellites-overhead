import Foundation
import Shared

private let defaultLat = 40.42
private let defaultLon = -86.88
private let defaultAlt = 180.0

@MainActor
final class AppState: ObservableObject {
    @Published var status: SchedulerStatus?
    @Published var passes: [Pass] = []
    @Published var captures: [Capture] = []
    @Published var rules: [Rule] = []
    @Published var overhead: [OverheadSat] = []
    @Published var events: [SdrEvent] = []
    @Published var statusError: String?
    @Published var passesError: String?
    @Published var capturesError: String?
    @Published var rulesError: String?
    @Published var eventsError: String?
    @Published var isLoadingStatus = false
    @Published var isLoadingPasses = false
    @Published var scanResult: String?

    private(set) var api: SatellitesApi

    init() {
        let url = UserDefaults.standard.string(forKey: "server_url") ?? "https://sdr.sadbabyrabbit.com"
        let token = UserDefaults.standard.string(forKey: "bearer_token") ?? ""
        api = SatellitesApi(baseUrl: url, token: token)
        Task { await refreshAll() }
    }

    func rebuildApi() {
        api.close()
        let url = UserDefaults.standard.string(forKey: "server_url") ?? "https://sdr.sadbabyrabbit.com"
        let token = UserDefaults.standard.string(forKey: "bearer_token") ?? ""
        api = SatellitesApi(baseUrl: url, token: token)
    }

    func refreshStatus() async {
        isLoadingStatus = true
        do {
            status = try await api.getStatus()
            statusError = nil
        } catch { statusError = error.localizedDescription }
        isLoadingStatus = false
    }

    func refreshPasses(hours: Int32 = 24) async {
        isLoadingPasses = true
        let lat = UserDefaults.standard.double(forKey: "latitude").nonZero ?? defaultLat
        let lon = UserDefaults.standard.double(forKey: "longitude").nonZero ?? defaultLon
        let alt = UserDefaults.standard.double(forKey: "altitude_m").nonZero ?? defaultAlt
        // All-sats prediction is too slow; use rule norads
        let ruleNorads = rules.isEmpty ? [59051] : Array(Set(rules.map { $0.norad }))
        var all: [Pass] = []
        for norad in ruleNorads {
            if let result = try? await api.getPasses(norad: Int32(norad), hours: hours, minEl: 10.0, lat: lat, lon: lon, altM: alt) {
                all += result as? [Pass] ?? []
            }
        }
        passes = all.sorted { $0.aos < $1.aos }
        passesError = all.isEmpty ? (rules.isEmpty ? "No rules configured." : nil) : nil
        isLoadingPasses = false
    }

    func refreshOverhead() async {
        let lat = UserDefaults.standard.double(forKey: "latitude").nonZero ?? defaultLat
        let lon = UserDefaults.standard.double(forKey: "longitude").nonZero ?? defaultLon
        let alt = UserDefaults.standard.double(forKey: "altitude_m").nonZero ?? defaultAlt
        do {
            let result = try await api.getOverhead(lat: lat, lon: lon, altM: alt, minEl: 0.0)
            overhead = result as? [OverheadSat] ?? []
        } catch {
            overhead = []
        }
    }

    func refreshCaptures(norad: Int32 = -1) async {
        do {
            let result = try await api.getCaptures(norad: norad, limit: 50)
            captures = result as? [Capture] ?? []
            capturesError = nil
        } catch { capturesError = error.localizedDescription }
    }

    func refreshRules() async {
        do {
            let result = try await api.getRules()
            rules = result as? [Rule] ?? []
            rulesError = nil
        } catch { rulesError = error.localizedDescription }
    }

    func setRuleEnabled(_ ruleId: String, enabled: Bool) async {
        do {
            try await api.setRuleEnabled(ruleId: ruleId, enabled: enabled)
            await refreshRules()
        } catch { rulesError = error.localizedDescription }
    }

    func triggerScan(norad: Int32, name: String, durationS: Int32 = 300) async {
        do {
            let req = ScanNowRequest(norad: norad, name: name, durationSeconds: durationS, maxElevation: nil)
            try await api.triggerScanNow(request: req)
            scanResult = "Queued \(name) (\(durationS)s)"
            await refreshStatus()
        } catch { scanResult = "Error: \(error.localizedDescription)" }
    }

    func refreshEvents() async {
        do {
            let result = try await api.getEvents(after: nil, limit: 50)
            let incoming = result as? [SdrEvent] ?? []
            let merged = (incoming + events).uniqued(by: \.id).prefix(100)
            events = Array(merged)
            eventsError = nil
        } catch { eventsError = error.localizedDescription }
    }

    func refreshAll() async {
        // Rules must load before passes (passes uses rule norads)
        await refreshRules()
        await withTaskGroup(of: Void.self) { group in
            group.addTask { await self.refreshStatus() }
            group.addTask { await self.refreshPasses() }
            group.addTask { await self.refreshCaptures() }
            group.addTask { await self.refreshEvents() }
            group.addTask { await self.refreshOverhead() }
        }
    }
}

private extension Double {
    var nonZero: Double? { self == 0 ? nil : self }
}

private extension Sequence {
    func uniqued<T: Hashable>(by keyPath: KeyPath<Element, T>) -> [Element] {
        var seen = Set<T>()
        return filter { seen.insert($0[keyPath: keyPath]).inserted }
    }
}
