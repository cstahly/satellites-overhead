import SwiftUI
import Shared

struct StatusView: View {
    @EnvironmentObject private var app: AppState
    @Binding var selectedTab: Int
    @State private var showScanAlert = false
    @State private var scanDuration = "300"

    var body: some View {
        NavigationStack {
            Group {
                if let status = app.status {
                    List {
                        Section {
                            HStack(spacing: 10) {
                                Circle()
                                    .fill(status.live ? Color.green : Color(white: 0.35))
                                    .frame(width: 10, height: 10)
                                Text(status.state.uppercased())
                                    .font(.headline)
                                    .foregroundStyle(status.live ? .green : .primary)
                            }
                            Text(status.message)
                                .foregroundStyle(.secondary)
                        }

                        Section("Scheduler") {
                            Button {
                                selectedTab = 1  // go to Passes
                            } label: {
                                HStack {
                                    Text("Upcoming passes").foregroundStyle(.primary)
                                    Spacer()
                                    Text("\(app.passes.count)")
                                        .foregroundStyle(.green)
                                        .bold()
                                    Image(systemName: "chevron.right")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            Button {
                                selectedTab = 2  // go to Captures
                            } label: {
                                HStack {
                                    Text("Pending queue").foregroundStyle(.primary)
                                    Spacer()
                                    Text("\(status.queueCount)")
                                        .foregroundStyle(status.queueCount > 0 ? .orange : .secondary)
                                        .bold()
                                    Image(systemName: "chevron.right")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            LabeledContent("Updated", value: status.updatedAt.shortTime)
                            LabeledContent("Age", value: "\(Int(status.statusAgeSeconds))s")
                        }

                        // Only show current job when something is actually running
                        if status.live, let job = status.currentJob {
                            Section("Running") {
                                LabeledContent("Label", value: job.label)
                                if let freq = job.frequencyHz {
                                    LabeledContent("Frequency", value: String(format: "%.3f MHz", freq.doubleValue / 1e6))
                                }
                                if let dur = job.durationSeconds {
                                    LabeledContent("Duration", value: "\(dur.int32Value)s")
                                }
                                if let lna = job.lnaGain {
                                    LabeledContent("Gains", value: "LNA=\(lna.int32Value) VGA=\(job.vgaGain?.int32Value ?? 0) AMP=\(job.amp?.int32Value ?? 0)")
                                }
                                if let t = job.fireTime {
                                    LabeledContent("Fire time", value: t.shortTime)
                                }
                            }
                        }

                        Section {
                            Button(role: .none) {
                                showScanAlert = true
                            } label: {
                                Label("Scan now…", systemImage: "dot.radiowaves.up.forward")
                                    .foregroundStyle(.green)
                            }
                        }
                    }
                } else if app.isLoadingStatus {
                    ProgressView()
                } else {
                    ContentUnavailableView(
                        "No Status",
                        systemImage: "antenna.radiowaves.left.and.right.slash",
                        description: Text(app.statusError ?? "Check Settings.")
                    )
                }
            }
            .navigationTitle("Satellites")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { Task { await app.refreshStatus() } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .refreshable { await app.refreshAll() }
            .alert("Scan METEOR-M2 4", isPresented: $showScanAlert) {
                TextField("Duration (s)", text: $scanDuration)
                    .keyboardType(.numberPad)
                Button("Queue") {
                    let dur = Int32(scanDuration) ?? 300
                    Task { await app.triggerScan(norad: 59051, name: "METEOR-M2 4", durationS: dur) }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Queue an immediate capture.")
            }
        }
    }
}
