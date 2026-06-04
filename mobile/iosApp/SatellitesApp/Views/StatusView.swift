import SwiftUI
import Shared

struct StatusView: View {
    @EnvironmentObject private var app: AppState
    @Binding var selectedTab: Int
    @State private var showScanSheet = false
    @State private var now = Date()
    private let timer = Timer.publish(every: 30, on: .main, in: .common).autoconnect()

    var nextPass: Pass? { app.passes.first }

    var body: some View {
        NavigationStack {
            Group {
                if let status = app.status {
                    List {
                        // Sky plot
                        Section {
                            OverheadSkyPlot(sats: app.overhead)
                                .aspectRatio(1, contentMode: .fit)
                                .listRowInsets(EdgeInsets())
                                .listRowBackground(Color.clear)
                        }

                        // Scheduler state + next pass
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
                                            .font(.caption).foregroundStyle(.secondary)
                                        Spacer()
                                        Text(p.name).foregroundStyle(.primary)
                                        Image(systemName: "chevron.right")
                                            .font(.caption).foregroundStyle(Color(white: 0.4))
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
            .refreshable {
                async let a: () = app.refreshAll()
                async let b: () = app.refreshOverhead()
                _ = await (a, b)
            }
            .onReceive(timer) { _ in Task { await app.refreshOverhead() } }
            .sheet(isPresented: $showScanSheet) {
                ScanNowSheet().presentationDetents([.medium])
            }
        }
    }

    private func countdownText(to aosISO: String) -> String {
        guard let d = ISO8601DateFormatter().date(from: aosISO) else { return "" }
        let diff = d.timeIntervalSince(now)
        if diff < 0 { return "In progress" }
        let h = Int(diff) / 3600; let m = (Int(diff) % 3600) / 60; let s = Int(diff) % 60
        if h > 0 { return "in \(h)h \(m)m" }
        if m > 0 { return "in \(m)m \(s)s" }
        return "in \(s)s"
    }
}

// MARK: - Sky Plot

private struct OverheadSkyPlot: View {
    let sats: [OverheadSat]

    var body: some View {
        Canvas { ctx, size in
            let cx = size.width / 2, cy = size.height / 2
            let r = min(cx, cy) - 24

            // Background
            ctx.fill(Path(ellipseIn: CGRect(x: cx-r-16, y: cy-r-16, width: (r+16)*2, height: (r+16)*2)),
                     with: .color(Color(white: 0.06)))

            // Elevation rings
            for el in stride(from: 0.0, through: 60.0, by: 30.0) {
                let rr = r * (1 - el / 90)
                let rect = CGRect(x: cx-rr, y: cy-rr, width: rr*2, height: rr*2)
                ctx.stroke(Path(ellipseIn: rect),
                           with: .color(Color(red: 0.16, green: 0.21, blue: 0.35)),
                           lineWidth: el == 0 ? 1.5 : 1)
            }

            // Cross hairs
            ctx.stroke(Path { p in
                p.move(to: CGPoint(x: cx, y: cy-r)); p.addLine(to: CGPoint(x: cx, y: cy+r))
                p.move(to: CGPoint(x: cx-r, y: cy)); p.addLine(to: CGPoint(x: cx+r, y: cy))
            }, with: .color(Color(red: 0.16, green: 0.21, blue: 0.35)), lineWidth: 0.5)

            // Compass labels
            let compass: [(String, Double)] = [("N",0),("E",90),("S",180),("W",270)]
            for (label, az) in compass {
                let rad = (az - 90) * .pi / 180
                let px = cx + (r + 14) * cos(rad)
                let py = cy + (r + 14) * sin(rad)
                ctx.draw(Text(label).font(.caption2.bold()).foregroundStyle(Color(white: 0.5)),
                         at: CGPoint(x: px, y: py))
            }

            // Satellite dots
            for sat in sats {
                let dist = r * (1 - sat.el / 90)
                let rad = (sat.az - 90) * .pi / 180
                let x = cx + dist * cos(rad)
                let y = cy + dist * sin(rad)
                let brightness = 0.35 + 0.65 * (sat.el / 90)
                let dotColor = Color(red: 0.35, green: 0.82, blue: 1.0, opacity: brightness)
                let dotR: CGFloat = sat.el > 60 ? 5 : 4
                ctx.fill(Path(ellipseIn: CGRect(x: x-dotR, y: y-dotR, width: dotR*2, height: dotR*2)),
                         with: .color(dotColor))
            }

            // Count label
            let countText = Text("\(sats.count) overhead")
                .font(.caption2).foregroundStyle(Color(white: 0.45))
            ctx.draw(countText, at: CGPoint(x: cx, y: cy + r + 22))
        }
        .padding(8)
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
                            ForEach(activeRules, id: \.id) { r in Text(r.name).tag(r.id) }
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
