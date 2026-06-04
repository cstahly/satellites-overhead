import SwiftUI
import Shared

struct StatusView: View {
    @EnvironmentObject private var app: AppState
    @Binding var selectedTab: Int
    @State private var showScanSheet = false
    @State private var now = Date()
    @State private var selectedOverheadSat: OverheadSat?
    private let ticker = Timer.publish(every: 1, on: .main, in: .common).autoconnect()
    private let overheadTimer = Timer.publish(every: 30, on: .main, in: .common).autoconnect()

    var nextPass: Pass? { app.passes.first }

    var body: some View {
        NavigationStack {
            Group {
                if let status = app.status {
                    List {
                        // Sky plot
                        Section {
                            OverheadSkyPlot(sats: app.overhead, selected: $selectedOverheadSat)
                                .aspectRatio(1, contentMode: .fit)
                                .listRowInsets(EdgeInsets())
                                .listRowBackground(Color.clear)
                        }

                        // Capture running / next pass
                        Section {
                            HStack(spacing: 10) {
                                Circle()
                                    .fill(status.live ? Color.green : Color(white: 0.35))
                                    .frame(width: 10, height: 10)
                                Text(status.state.uppercased())
                                    .font(.headline)
                                    .foregroundStyle(status.live ? .green : .primary)
                            }

                            if status.live, let job = status.currentJob {
                                // Running capture summary
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(job.label)
                                        .font(.subheadline.bold())
                                    if let freq = job.frequencyHz {
                                        Text(String(format: "%.3f MHz  ·  LNA=\(job.lnaGain?.int32Value ?? 0) VGA=\(job.vgaGain?.int32Value ?? 0)",
                                                    freq.doubleValue / 1e6))
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                    if let remaining = captureRemaining(job: job) {
                                        HStack {
                                            Image(systemName: "timer").foregroundStyle(.green)
                                            Text(remaining + " remaining")
                                                .font(.caption.bold())
                                                .foregroundStyle(.green)
                                        }
                                    }
                                }
                                Button {
                                    selectedTab = 2   // Captures tab
                                } label: {
                                    HStack {
                                        Text("View captures")
                                            .foregroundStyle(.primary)
                                        Spacer()
                                        Image(systemName: "chevron.right")
                                            .font(.caption).foregroundStyle(Color(white: 0.4))
                                    }
                                }
                                .buttonStyle(.plain)
                            } else {
                                // Idle — show next pass countdown
                                Text(status.message).foregroundStyle(.secondary)
                                if let p = nextPass {
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
                        }

                        Section {
                            Button { showScanSheet = true } label: {
                                Label("Scan now…", systemImage: "dot.radiowaves.up.forward")
                                    .foregroundStyle(.green)
                            }
                        }
                    }
                    .sheet(item: $selectedOverheadSat) { sat in
                        OverheadSatSheet(sat: sat)
                            .presentationDetents([.fraction(0.35)])
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
                await app.refreshAll()
                await app.refreshOverhead()
            }
            .onReceive(ticker) { now = $0 }
            .onReceive(overheadTimer) { _ in Task { await app.refreshOverhead() } }
            .sheet(isPresented: $showScanSheet) {
                ScanNowSheet().presentationDetents([.medium])
            }
        }
    }

    private func captureRemaining(job: CurrentJob) -> String? {
        guard let fireISO = job.fireTime,
              let dur = job.durationSeconds else { return nil }
        let fmt = ISO8601DateFormatter()
        fmt.formatOptions = [.withInternetDateTime]
        guard let fireDate = fmt.date(from: fireISO) else { return nil }
        let end = fireDate.addingTimeInterval(Double(dur.int32Value))
        let diff = end.timeIntervalSince(now)
        guard diff > 0 else { return nil }
        let m = Int(diff) / 60; let s = Int(diff) % 60
        return "\(m)m \(s)s"
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

// MARK: - Overhead satellite detail sheet

private struct OverheadSatSheet: View {
    let sat: OverheadSat
    var body: some View {
        VStack(spacing: 16) {
            Text(sat.name)
                .font(.title2.bold())
                .padding(.top, 20)
            Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 8) {
                GridRow {
                    Label("Elevation", systemImage: "arrow.up.right")
                    Text(String(format: "%.1f°", sat.el))
                        .foregroundStyle(sat.el > 45 ? .green : sat.el > 20 ? .yellow : .primary)
                        .bold()
                }
                GridRow {
                    Label("Azimuth", systemImage: "arrow.clockwise")
                    Text(String(format: "%.0f°  %@", sat.az, cardinal(sat.az)))
                }
                GridRow {
                    Label("Range", systemImage: "ruler")
                    Text(String(format: "%.0f km", sat.rangeKm))
                }
            }
            .font(.subheadline)
            Text("NORAD \(sat.norad)")
                .font(.caption).foregroundStyle(.secondary)
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    private func cardinal(_ az: Double) -> String {
        ["N","NE","E","SE","S","SW","W","NW","N"][Int((az + 22.5) / 45) % 8]
    }
}

// MARK: - Sky Plot

struct OverheadSkyPlot: View {
    let sats: [OverheadSat]
    @Binding var selected: OverheadSat?
    // Store computed positions for hit testing
    @State private var plotSize: CGSize = .zero
    @State private var positions: [(sat: OverheadSat, pt: CGPoint)] = []

    var body: some View {
        Canvas { ctx, size in
            plotSize = size
            let cx = size.width / 2, cy = size.height / 2
            let r = min(cx, cy) - 24

            // Background fill
            ctx.fill(Path(ellipseIn: CGRect(x: cx-r-16, y: cy-r-16, width: (r+16)*2, height: (r+16)*2)),
                     with: .color(Color(red: 0.07, green: 0.09, blue: 0.15)))

            // Rings
            for el in stride(from: 0.0, through: 60.0, by: 30.0) {
                let rr = r * (1 - el / 90)
                ctx.stroke(Path(ellipseIn: CGRect(x: cx-rr, y: cy-rr, width: rr*2, height: rr*2)),
                           with: .color(Color(red: 0.18, green: 0.23, blue: 0.38)),
                           lineWidth: el == 0 ? 1.5 : 0.75)
            }

            // Cross hairs
            ctx.stroke(Path { p in
                p.move(to: CGPoint(x: cx, y: cy-r)); p.addLine(to: CGPoint(x: cx, y: cy+r))
                p.move(to: CGPoint(x: cx-r, y: cy)); p.addLine(to: CGPoint(x: cx+r, y: cy))
            }, with: .color(Color(red: 0.18, green: 0.23, blue: 0.38)), lineWidth: 0.5)

            // Compass
            let dirs: [(String, Double)] = [("N",0),("E",90),("S",180),("W",270)]
            for (label, az) in dirs {
                let rad = (az - 90) * .pi / 180
                ctx.draw(Text(label).font(.caption2.bold()).foregroundStyle(Color(white: 0.45)),
                         at: CGPoint(x: cx + (r+14)*cos(rad), y: cy + (r+14)*sin(rad)))
            }

            // Satellite dots
            var pts: [(sat: OverheadSat, pt: CGPoint)] = []
            let showLabels = sats.count <= 60
            for sat in sats {
                let dist = r * (1 - sat.el / 90)
                let rad = (sat.az - 90) * .pi / 180
                let x = cx + dist * cos(rad)
                let y = cy + dist * sin(rad)
                let pt = CGPoint(x: x, y: y)
                pts.append((sat, pt))

                let brightness = 0.35 + 0.65 * (sat.el / 90)
                let isSelected = selected?.norad == sat.norad
                let color = isSelected
                    ? Color(red: 0.3, green: 1.0, blue: 0.5, opacity: 1)
                    : Color(red: 0.35, green: 0.82, blue: 1.0, opacity: brightness)
                let dotR: CGFloat = isSelected ? 6 : (sat.el > 60 ? 5 : 4)
                ctx.fill(Path(ellipseIn: CGRect(x: x-dotR, y: y-dotR, width: dotR*2, height: dotR*2)),
                         with: .color(color))

                if showLabels || isSelected {
                    let opacity = isSelected ? 1.0 : (0.4 + 0.6 * (sat.el / 90))
                    ctx.draw(
                        Text(sat.name.prefix(16))
                            .font(.system(size: 10))
                            .foregroundStyle(Color(white: 0.85, opacity: opacity)),
                        at: CGPoint(x: x + 8, y: y + 3)
                    )
                }
            }
            positions = pts

            // Count
            ctx.draw(Text("\(sats.count) overhead").font(.caption2).foregroundStyle(Color(white: 0.4)),
                     at: CGPoint(x: cx, y: cy + r + 22))
        }
        .contentShape(Rectangle())
        .onTapGesture { location in
            // Find nearest satellite within 24pt
            guard !positions.isEmpty else { return }
            let nearest = positions.min { a, b in
                distance(a.pt, location) < distance(b.pt, location)
            }
            if let nearest, distance(nearest.pt, location) < 24 {
                selected = nearest.sat
            } else {
                selected = nil
            }
        }
        .padding(8)
    }

    private func distance(_ a: CGPoint, _ b: CGPoint) -> CGFloat {
        sqrt(pow(a.x - b.x, 2) + pow(a.y - b.y, 2))
    }
}

extension OverheadSat: Identifiable {
    public var id: Int { norad }
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
