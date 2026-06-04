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
                    .navigationDestination(item: $selectedPass) { PassDetailView(pass: $0) }
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
        HStack(alignment: .center, spacing: 10) {
            // Elevation pill — left
            elevationPill

            // Pass info — fills remaining space, taps to navigate
            VStack(alignment: .leading, spacing: 3) {
                Text(pass.name)
                    .font(.headline)
                    .lineLimit(1)
                Text("AOS \(pass.aos.shortTime)  ·  \(pass.durationSeconds / 60)m \(pass.durationSeconds % 60)s")
                    .font(.caption).foregroundStyle(.secondary)
                Text("Az \(Int(pass.aosAzimuth))°→\(Int(pass.maxAzimuth))°→\(Int(pass.losAzimuth))°")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .onTapGesture { onTap() }

            // Tracking toggle — right
            Button { onToggleTracking() } label: {
                Image(systemName: isTracked
                      ? "antenna.radiowaves.left.and.right"
                      : "antenna.radiowaves.left.and.right.slash")
                    .foregroundStyle(isTracked ? .green : Color(white: 0.35))
                    .font(.system(size: 17))
                    .frame(width: 36, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .padding(.vertical, 2)
    }

    private var elevationPill: some View {
        Text(String(format: "%.0f°", pass.maxElevation))
            .font(.caption.bold())
            .foregroundStyle(.black)
            .padding(.horizontal, 7)
            .padding(.vertical, 4)
            .background(pillColor.cornerRadius(6))
            .frame(width: 46)
    }

    private var pillColor: Color {
        switch pass.maxElevation {
        case 45...: return Color(red: 0.2, green: 0.85, blue: 0.4)   // green
        case 20...: return Color(red: 0.85, green: 0.75, blue: 0.1)  // yellow
        default:    return Color(red: 0.55, green: 0.55, blue: 0.6)  // gray
        }
    }
}

extension Pass: Identifiable {
    public var id: String { aos }
}

extension AppState {
    func isTracked(_ pass: Pass) -> Bool {
        rules.contains { $0.norad == pass.norad && $0.enabled }
    }
}
