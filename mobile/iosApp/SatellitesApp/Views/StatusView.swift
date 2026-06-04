import SwiftUI
import Shared

struct StatusView: View {
    @EnvironmentObject private var app: AppState
    @Binding var selectedTab: Int
    @State private var showScanSheet = false
    @State private var now = Date()
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var nextPass: Pass? { app.passes.first }

    // Passes that are currently in progress
    var overhead: [(pass: Pass, el: Double, az: Double)] {
        app.passes.compactMap { pass in
            guard let aos = iso(pass.aos), let los = iso(pass.los),
                  now >= aos, now <= los else { return nil }
            let elapsed = now.timeIntervalSince(aos)
            let track = pass.track as? [TrackPoint] ?? []
            let idx = min(max(0, Int(elapsed / Double(pass.trackStepSeconds))), track.count - 1)
            let tp = track.isEmpty ? nil : track[idx]
            return (pass, tp?.el ?? 0, tp?.az ?? 0)
        }
    }

    var body: some View {
        NavigationStack {
            Group {
                if let status = app.status {
                    List {
                        // Overhead satellites
                        Section("Overhead now") {
                            if overhead.isEmpty {
                                Text("No satellites overhead")
                                    .foregroundStyle(.secondary)
                                    .italic()
                            } else {
                                ForEach(overhead, id: \.pass.aos) { item in
                                    HStack {
                                        Text(item.pass.name).bold()
                                        Spacer()
                                        Text(String(format: "%.0f°", item.el))
                                            .foregroundStyle(item.el >= 30 ? .green : .yellow)
                                            .bold()
                                        Text(cardinal(item.az))
                                            .foregroundStyle(.secondary)
                                            .font(.caption)
                                            .frame(width: 28, alignment: .leading)
                                    }
                                }
                            }
                        }

                        // Scheduler state
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
                            if !status.live, let p = nextPass {
                                Button {
                                    selectedTab = 1
                                } label: {
                                    HStack {
                                        Text(countdownText(to: p.aos))
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                        Spacer()
                                        Text(p.name).foregroundStyle(.primary)
                                        Image(systemName: "chevron.right")
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                                .buttonStyle(.plain)
                            }
                        }

                        // Running job
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

                        // Queue
                        Section {
                            Button {
                                selectedTab = 2
                            } label: {
                                HStack {
                                    Text("Pending queue").foregroundStyle(.primary)
                                    Spacer()
                                    Text("\(status.queueCount)")
                                        .foregroundStyle(status.queueCount > 0 ? .orange : Color(white: 0.45))
                                        .bold()
                                    Image(systemName: "chevron.right")
                                        .font(.caption).foregroundStyle(Color(white: 0.45))
                                }
                            }
                            .buttonStyle(.plain)
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
                    Button { Task { await app.refreshAll() } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .refreshable { await app.refreshAll() }
            .onReceive(timer) { now = $0 }
            .sheet(isPresented: $showScanSheet) {
                ScanNowSheet().presentationDetents([.medium])
            }
        }
    }

    private func iso(_ s: String) -> Date? {
        ISO8601DateFormatter().date(from: s)
    }

    private func countdownText(to aosISO: String) -> String {
        guard let d = iso(aosISO) else { return "" }
        let diff = d.timeIntervalSince(now)
        if diff < 0 { return "In progress" }
        let h = Int(diff) / 3600; let m = (Int(diff) % 3600) / 60; let s = Int(diff) % 60
        if h > 0 { return "in \(h)h \(m)m" }
        if m > 0 { return "in \(m)m \(s)s" }
        return "in \(s)s"
    }

    private func cardinal(_ az: Double) -> String {
        let dirs = ["N","NE","E","SE","S","SW","W","NW","N"]
        return dirs[Int((az + 22.5) / 45) % 8]
    }
}

// MARK: - Scan Now Sheet

private struct ScanNowSheet: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var selectedRuleId = ""
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
                            ForEach(activeRules, id: \.id) { r in
                                Text(r.name).tag(r.id)
                            }
                        }
                        .pickerStyle(.inline).labelsHidden()
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
            .navigationTitle("Scan Now").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Queue") {
                        let dur = Int32(durationText) ?? 300
                        if useCustom, let n = Int32(customNorad) {
                            Task { await app.triggerScan(norad: n, name: customName.isEmpty ? "NORAD \(n)" : customName, durationS: dur) }
                        } else if let rule = activeRules.first(where: { $0.id == selectedRuleId }) ?? activeRules.first {
                            Task { await app.triggerScan(norad: Int32(rule.norad), name: rule.name, durationS: dur) }
                        }
                        dismiss()
                    }
                }
            }
            .onAppear { if selectedRuleId.isEmpty { selectedRuleId = activeRules.first?.id ?? "" } }
        }
    }
}
