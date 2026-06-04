import SwiftUI
import Shared

struct PassesView: View {
    @EnvironmentObject private var app: AppState
    @State private var selectedPass: Pass?

    var body: some View {
        NavigationStack {
            Group {
                if app.passes.isEmpty && app.isLoadingPasses {
                    ProgressView()
                } else if app.passes.isEmpty {
                    ContentUnavailableView("No Passes", systemImage: "dot.radiowaves.up.forward",
                        description: Text(app.passesError ?? "No passes in the next 24 hours."))
                } else {
                    List(app.passes) { pass in
                        PassRow(pass: pass, isTracked: app.isTracked(pass)) {
                            selectedPass = pass
                        } onToggleTracking: {
                            if let rule = app.rules.first(where: { $0.norad == pass.norad }) {
                                Task { await app.setRuleEnabled(rule.id, enabled: !rule.enabled) }
                            }
                        }
                    }
                    .navigationDestination(item: $selectedPass) { pass in
                        PassDetailView(pass: pass)
                    }
                }
            }
            .navigationTitle("Upcoming Passes")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { Task { await app.refreshPasses() } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .refreshable { await app.refreshPasses() }
        }
    }
}

private struct PassRow: View {
    let pass: Pass
    let isTracked: Bool
    let onTap: () -> Void
    let onToggleTracking: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            // Main content — tapping navigates to detail
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(pass.name).font(.headline)
                    Spacer()
                    Text(String(format: "%.0f°", pass.maxElevation))
                        .font(.headline.bold())
                        .foregroundStyle(elevationColor)
                }
                Text("AOS \(pass.aos.shortTime)  •  \(pass.durationSeconds / 60)m \(pass.durationSeconds % 60)s")
                    .font(.caption).foregroundStyle(.secondary)
                Text("Az \(Int(pass.aosAzimuth))° → \(Int(pass.maxAzimuth))° → \(Int(pass.losAzimuth))°")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .contentShape(Rectangle())
            .onTapGesture { onTap() }

            // Tracking toggle — separate tap target
            Button {
                onToggleTracking()
            } label: {
                Image(systemName: isTracked ? "antenna.radiowaves.left.and.right" : "antenna.radiowaves.left.and.right.slash")
                    .foregroundStyle(isTracked ? .green : Color(white: 0.4))
                    .font(.system(size: 18))
                    .frame(width: 36, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .padding(.vertical, 2)
    }

    private var elevationColor: Color {
        switch pass.maxElevation {
        case 60...: return .green
        case 30...: return Color(red: 0.6, green: 0.9, blue: 0.3)
        default: return .secondary
        }
    }
}

extension AppState {
    func isTracked(_ pass: Pass) -> Bool {
        rules.contains { $0.norad == pass.norad && $0.enabled }
    }
}
