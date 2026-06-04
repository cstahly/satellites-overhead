import SwiftUI
import Shared

struct CapturesView: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        NavigationStack {
            Group {
                if app.captures.isEmpty {
                    ContentUnavailableView("No Captures", systemImage: "clock.arrow.circlepath", description: Text(app.capturesError ?? "No captures yet."))
                } else {
                    List(app.captures, id: \.id) { capture in
                        CaptureRow(capture: capture)
                    }
                }
            }
            .navigationTitle("Captures")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { Task { await app.refreshCaptures() } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .refreshable { await app.refreshCaptures() }
        }
    }
}

private struct CaptureRow: View {
    let capture: Capture

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(capture.name)
                    .font(.headline)
                Spacer()
                if let bytes = capture.sizeBytes {
                    Text(formatBytes(bytes.int64Value))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            if let t = capture.startedAt {
                Text(t.shortDateTime)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let profile = capture.profile {
                Text(profile)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let freq = capture.frequencyHz {
                let freqMhz = freq.doubleValue / 1e6
                let lna = capture.lnaGain?.int32Value ?? 0
                let vga = capture.vgaGain?.int32Value ?? 0
                Text(String(format: "%.3f MHz  •  LNA=\(lna) VGA=\(vga)", freqMhz))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
    }

    private func formatBytes(_ bytes: Int64) -> String {
        switch bytes {
        case 1_000_000_000...: return String(format: "%.1f GB", Double(bytes) / 1e9)
        case 1_000_000...:     return String(format: "%.1f MB", Double(bytes) / 1e6)
        case 1_000...:         return String(format: "%.1f KB", Double(bytes) / 1e3)
        default:               return "\(bytes) B"
        }
    }
}
