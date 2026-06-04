import SwiftUI
import Shared

struct PassesView: View {
    @EnvironmentObject private var app: AppState
    @State private var scanTarget: Pass?

    var body: some View {
        NavigationStack {
            Group {
                if app.passes.isEmpty && app.isLoadingPasses {
                    ProgressView()
                } else if app.passes.isEmpty {
                    ContentUnavailableView("No Passes", systemImage: "dot.radiowaves.up.forward",
                        description: Text(app.passesError ?? "No passes in the next 24 hours."))
                } else {
                    List(app.passes, id: \.aos) { pass in
                        PassRow(pass: pass) {
                            scanTarget = pass
                        }
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
            .alert(item: $scanTarget) { pass in
                Alert(
                    title: Text("Scan \(pass.name)?"),
                    message: Text("Queue a \(pass.durationSeconds)s capture starting now."),
                    primaryButton: .default(Text("Queue")) {
                        Task { await app.triggerScan(norad: Int32(pass.norad), name: pass.name, durationS: Int32(pass.durationSeconds)) }
                    },
                    secondaryButton: .cancel()
                )
            }
        }
    }
}

private struct PassRow: View {
    let pass: Pass
    let onScan: () -> Void

    var body: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(pass.name).font(.headline)
                    Spacer()
                    Text(String(format: "%.0f°", pass.maxElevation))
                        .font(.headline)
                        .foregroundStyle(elevationColor)
                }
                Text("AOS \(pass.aos.shortTime)  •  \(pass.durationSeconds / 60)m \(pass.durationSeconds % 60)s")
                    .font(.caption).foregroundStyle(.secondary)
                Text("Az \(Int(pass.aosAzimuth))° → \(Int(pass.maxAzimuth))° → \(Int(pass.losAzimuth))°")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Button {
                onScan()
            } label: {
                Image(systemName: "dot.radiowaves.up.forward")
                    .foregroundStyle(.green)
                    .padding(.leading, 8)
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

extension Pass: Identifiable {
    public var id: String { aos }
}
