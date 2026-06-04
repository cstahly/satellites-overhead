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
                                    LabeledContent("Frequency", value: String(format: "%.3f MHz", freq / 1e6))
                                }
                                if let dur = job.durationSeconds {
                                    LabeledContent("Duration", value: "\(dur)s")
                                }
                                if let lna = job.lnaGain {
                                    LabeledContent("Gains", value: "LNA=\(lna) VGA=\(job.vgaGain ?? 0) AMP=\(job.amp ?? 0)")
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
