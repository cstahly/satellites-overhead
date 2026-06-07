import SwiftUI
import Shared

struct CapturesView: View {
    @EnvironmentObject private var app: AppState
    @State private var selectedCapture: Capture?

    var body: some View {
        NavigationStack {
            Group {
                if app.captures.isEmpty {
                    ContentUnavailableView("No Captures", systemImage: "clock.arrow.circlepath", description: Text(app.capturesError ?? "No captures yet."))
                } else {
                    List(app.captures, id: \.id) { capture in
                        CaptureRow(capture: capture)
                            .contentShape(Rectangle())
                            .onTapGesture { selectedCapture = capture }
                    }
                    .navigationDestination(item: $selectedCapture) { CaptureDetailView(capture: $0) }
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
                HStack(spacing: 6) {
                    Text(profile)
                    if capture.reportPath != nil {
                        Label("report", systemImage: "doc.text")
                    }
                    if let success = capture.success?.boolValue {
                        Text(success ? "ok" : "failed")
                            .foregroundStyle(success ? .green : .red)
                    }
                }
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

private struct CaptureDetailView: View {
    @EnvironmentObject private var app: AppState
    let capture: Capture
    @State private var report: String?
    @State private var reportError: String?
    @State private var isLoadingReport = false

    var body: some View {
        List {
            Section("Capture") {
                LabeledContent("Satellite", value: capture.name)
                LabeledContent("NORAD", value: "\(capture.norad)")
                if let started = capture.startedAt {
                    LabeledContent("Started", value: started.shortDateTime)
                }
                if let ended = capture.endedAt {
                    LabeledContent("Ended", value: ended.shortDateTime)
                }
                if let profile = capture.profile {
                    LabeledContent("Profile", value: profile)
                }
                if let freq = capture.frequencyHz {
                    LabeledContent("Frequency", value: String(format: "%.3f MHz", freq.doubleValue / 1e6))
                }
                if let success = capture.success?.boolValue {
                    LabeledContent("Result", value: success ? "Success" : "Failed")
                }
                if let error = capture.error, !error.isEmpty {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }

            Section("Output") {
                if let size = capture.sizeBytes {
                    LabeledContent("Size", value: formatBytes(size.int64Value))
                }
                if let cadu = capture.caduBytes {
                    LabeledContent("CADU", value: formatBytes(cadu.int64Value))
                }
                if let output = capture.output {
                    Text(output)
                        .font(.caption.monospaced())
                        .textSelection(.enabled)
                }
            }

            Section("Diagnostic Report") {
                if isLoadingReport {
                    ProgressView()
                } else if let report {
                    Text(report)
                        .font(.caption.monospaced())
                        .textSelection(.enabled)
                } else if let reportError {
                    Text(reportError)
                        .foregroundStyle(.secondary)
                } else if capture.reportPath == nil {
                    Text("No diagnostic report recorded for this capture.")
                        .foregroundStyle(.secondary)
                } else {
                    Button("Load Report") {
                        Task { await loadReport() }
                    }
                }
            }
        }
        .navigationTitle(capture.name)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if capture.reportPath != nil && report == nil && reportError == nil {
                await loadReport()
            }
        }
    }

    private func loadReport() async {
        isLoadingReport = true
        defer { isLoadingReport = false }
        do {
            report = try await app.captureReport(for: capture.id)
            reportError = nil
        } catch {
            reportError = error.localizedDescription
        }
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

extension Capture: Identifiable {}
