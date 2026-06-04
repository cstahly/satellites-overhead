import Foundation
import Shared  // KMP XCFramework — build with: ./gradlew :shared:assembleSharedXCFramework

// Default location: Lafayette IN
private let defaultLat = 40.42
private let defaultLon = -86.88
private let defaultAlt = 180.0

@MainActor
final class AppState: ObservableObject {
    @Published var status: SchedulerStatus?
    @Published var passes: [Pass] = []
    @Published var captures: [Capture] = []
    @Published var events: [SdrEvent] = []
    @Published var statusError: String?
    @Published var passesError: String?
    @Published var capturesError: String?
    @Published var eventsError: String?
    @Published var isLoadingStatus = false
    @Published var isLoadingPasses = false

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
        } catch {
            statusError = error.localizedDescription
        }
        isLoadingStatus = false
    }

    func refreshPasses(norad: Int32 = 59051, hours: Int32 = 24) async {
        isLoadingPasses = true
        let lat = UserDefaults.standard.double(forKey: "latitude").nonZero ?? defaultLat
        let lon = UserDefaults.standard.double(forKey: "longitude").nonZero ?? defaultLon
        let alt = UserDefaults.standard.double(forKey: "altitude_m").nonZero ?? defaultAlt
        do {
            let result = try await api.getPasses(norad: norad, hours: hours, minEl: 10.0, lat: lat, lon: lon, altM: alt)
            passes = result as? [Pass] ?? []
            passesError = nil
        } catch {
            passesError = error.localizedDescription
        }
        isLoadingPasses = false
    }

    // norad: -1 means all satellites
    func refreshCaptures(norad: Int32 = -1) async {
        do {
            let result = try await api.getCaptures(norad: norad, limit: 50)
            captures = result as? [Capture] ?? []
            capturesError = nil
        } catch {
            capturesError = error.localizedDescription
        }
    }

    func refreshEvents() async {
        do {
            let result = try await api.getEvents(after: nil, limit: 50)
            let incoming = result as? [SdrEvent] ?? []
            let merged = (incoming + events).uniqued(by: \.id).prefix(100)
            events = Array(merged)
            eventsError = nil
        } catch {
            eventsError = error.localizedDescription
        }
    }

    func refreshAll() async {
        await withTaskGroup(of: Void.self) { group in
            group.addTask { await self.refreshStatus() }
            group.addTask { await self.refreshPasses() }
            group.addTask { await self.refreshCaptures() }
            group.addTask { await self.refreshEvents() }
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
