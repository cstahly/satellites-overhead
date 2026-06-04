import SwiftUI
import Shared

struct StatusView: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        NavigationStack {
            Group {
                if let status = app.status {
                    List {
                        Section {
                            HStack {
                                Circle()
                                    .fill(status.live ? Color.green : Color.gray)
                                    .frame(width: 10, height: 10)
                                Text(status.state.uppercased())
                                    .font(.headline)
                            }
                            Text(status.message)
                                .foregroundStyle(.secondary)
                        }

                        Section("Scheduler") {
                            LabeledContent("Queue", value: "\(status.queueCount)")
                            LabeledContent("Age", value: "\(Int(status.statusAgeSeconds))s")
                            LabeledContent("Updated", value: status.updatedAt.shortTime)
                        }

                        if let job = status.currentJob {
                            Section("Current Job") {
                                LabeledContent("Label", value: job.label)
                                if let freq = job.frequencyHz {
                                    LabeledContent("Frequency", value: String(format: "%.3f MHz", freq.doubleValue / 1e6))
                                }
                                if let dur = job.durationSeconds {
                                    LabeledContent("Duration", value: "\(dur.int32Value)s")
                                }
                                if let lna = job.lnaGain {
                                    let vga = job.vgaGain?.int32Value ?? 0
                                    let amp = job.amp?.int32Value ?? 0
                                    LabeledContent("Gains", value: "LNA=\(lna.int32Value) VGA=\(vga) AMP=\(amp)")
                                }
                                if let t = job.fireTime {
                                    LabeledContent("Fire time", value: t.shortTime)
                                }
                            }
                        }
                    }
                } else if app.isLoadingStatus {
                    ProgressView()
                } else {
                    ContentUnavailableView("No Status", systemImage: "antenna.radiowaves.left.and.right.slash", description: Text(app.statusError ?? "Check server settings."))
                }
            }
            .navigationTitle("Scheduler")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { Task { await app.refreshStatus() } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .refreshable { await app.refreshStatus() }
        }
    }
}
