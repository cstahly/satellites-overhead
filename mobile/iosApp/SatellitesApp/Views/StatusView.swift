import SwiftUI
import Shared

struct StatusView: View {
    @EnvironmentObject private var app: AppState
    @Binding var selectedTab: Int
    @State private var showScanSheet = false
    @State private var now = Date()
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var nextPass: Pass? { app.passes.first }

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
                            Text(status.message).foregroundStyle(.secondary)
                        }

                        Section("Scheduler") {
                            Button { selectedTab = 1 } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("Next capture pending").foregroundStyle(.primary)
                                        if let p = nextPass {
                                            Text(countdownText(to: p.aos))
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    Spacer()
                                    if let p = nextPass {
                                        Text(String(format: "%.0f°", p.maxElevation))
                                            .foregroundStyle(p.maxElevation >= 60 ? .green : .secondary)
                                            .bold()
                                    } else {
                                        Text("None").foregroundStyle(.secondary)
                                    }
                                    Image(systemName: "chevron.right")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            Button { selectedTab = 2 } label: {
                                HStack {
                                    Text("Pending queue").foregroundStyle(.primary)
                                    Spacer()
                                    Text("\(status.queueCount)")
                                        .foregroundStyle(status.queueCount > 0 ? .orange : .secondary)
                                        .bold()
                                    Image(systemName: "chevron.right")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            LabeledContent("Updated", value: status.updatedAt.shortTime)
                        }

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
                            }
                        }

                        Section {
                            Button { showScanSheet = true } label: {
                                Label("Scan now…", systemImage: "dot.radiowaves.up.forward")
                                    .foregroundStyle(.green)
                            }
                        }
                    }
                } else if app.isLoadingStatus {
                    ProgressView()
                } else {
                    ContentUnavailableView("No Status",
                        systemImage: "antenna.radiowaves.left.and.right.slash",
                        description: Text(app.statusError ?? "Check Settings."))
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
            .onReceive(timer) { now = $0 }
            .sheet(isPresented: $showScanSheet) {
                ScanNowSheet()
                    .presentationDetents([.medium])
            }
        }
    }

    private func countdownText(to aosISO: String) -> String {
        guard let aosDate = ISO8601DateFormatter().date(from: aosISO) else { return aosISO.shortTime }
        let diff = aosDate.timeIntervalSince(now)
        if diff < 0 { return "In progress" }
        let h = Int(diff) / 3600
        let m = (Int(diff) % 3600) / 60
        let s = Int(diff) % 60
        if h > 0 { return "in \(h)h \(m)m" }
        if m > 0 { return "in \(m)m \(s)s" }
        return "in \(s)s"
    }
}

// MARK: - Scan Now Sheet

private struct ScanNowSheet: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var selectedRuleId: String = ""
    @State private var customNorad = ""
    @State private var customName = ""
    @State private var durationText = "300"
    @State private var useCustom = false

    private var activeRules: [Rule] { app.rules.filter { $0.enabled } }

    var body: some View {
        NavigationStack {
            Form {
                if !activeRules.isEmpty {
                    Section("Active rules") {
                        Picker("Target", selection: $selectedRuleId) {
                            ForEach(activeRules, id: \.id) { rule in
                                Text(rule.name).tag(rule.id)
                            }
                        }
                        .pickerStyle(.inline)
                        .labelsHidden()
                    }
                }

                Section("Or enter manually") {
                    Toggle("Custom NORAD", isOn: $useCustom)
                    if useCustom {
                        TextField("NORAD ID", text: $customNorad).keyboardType(.numberPad)
                        TextField("Name", text: $customName)
                    }
                }

                Section("Duration") {
                    HStack {
                        TextField("Seconds", text: $durationText).keyboardType(.numberPad)
                        Text("seconds").foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("Scan Now")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Queue") {
                        let dur = Int32(durationText) ?? 300
                        if useCustom, let norad = Int32(customNorad) {
                            Task { await app.triggerScan(norad: norad, name: customName.isEmpty ? "NORAD \(norad)" : customName, durationS: dur) }
                        } else if let rule = activeRules.first(where: { $0.id == selectedRuleId }) ?? activeRules.first {
                            Task { await app.triggerScan(norad: Int32(rule.norad), name: rule.name, durationS: dur) }
                        }
                        dismiss()
                    }
                }
            }
            .onAppear {
                if selectedRuleId.isEmpty, let first = activeRules.first {
                    selectedRuleId = first.id
                }
            }
        }
    }
}
