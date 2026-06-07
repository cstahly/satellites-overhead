import SwiftUI
import Shared

struct EventsView: View {
    @EnvironmentObject private var app: AppState
    @State private var mode: DiagnosticsMode = .events

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Picker("Diagnostics", selection: $mode) {
                    Text("Events").tag(DiagnosticsMode.events)
                    Text("Logs").tag(DiagnosticsMode.logs)
                }
                .pickerStyle(.segmented)
                .padding([.horizontal, .top])

                Group {
                    if mode == .events {
                        eventsList
                    } else {
                        logsList
                    }
                }
            }
            .navigationTitle("Diagnostics")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { Task { await refreshVisible() } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .refreshable { await refreshVisible() }
        }
    }

    private var eventsList: some View {
        Group {
            if app.events.isEmpty {
                ContentUnavailableView("No Events", systemImage: "bolt", description: Text(app.eventsError ?? "No events yet."))
            } else {
                List(app.events, id: \.id) { event in
                    EventRow(event: event)
                }
            }
        }
    }

    private var logsList: some View {
        Group {
            if app.isLoadingLogs && app.logs == nil {
                ProgressView()
            } else if let logs = app.logs {
                LogSnapshotView(logs: logs)
            } else {
                ContentUnavailableView("No Logs", systemImage: "doc.text.magnifyingglass", description: Text(app.logsError ?? "No log snapshot loaded."))
            }
        }
    }

    private func refreshVisible() async {
        if mode == .events {
            await app.refreshEvents()
        } else {
            await app.refreshLogs()
        }
    }
}

private enum DiagnosticsMode: Hashable {
    case events
    case logs
}

private struct EventRow: View {
    let event: SdrEvent

    var body: some View {
        HStack(alignment: .top) {
            Circle()
                .fill(eventColor)
                .frame(width: 8, height: 8)
                .padding(.top, 5)
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text(event.type)
                        .font(.caption)
                        .fontWeight(.semibold)
                        .foregroundStyle(eventColor)
                    Spacer()
                    Text(event.timestamp.shortTime)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                if let source = event.source {
                    Text(source)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var eventColor: Color {
        if event.type.hasPrefix("capture.") { return .blue }
        if event.type.hasPrefix("scheduler.") { return .green }
        if event.type.hasPrefix("monitor.") { return .orange }
        return .primary
    }
}

private struct LogSnapshotView: View {
    let logs: SchedulerLogs

    private var schedulerTail: [String] { logs.schedulerTail as? [String] ?? [] }
    private var satdumpTail: [String] { logs.satdumpTail as? [String] ?? [] }
    private var signalTail: [String] { logs.signalTail as? [String] ?? [] }

    var body: some View {
        List {
            Section("Paths") {
                LogPathRow(title: "Scheduler", path: logs.schedulerLogPath)
                if let satdump = logs.satdumpLogPath {
                    LogPathRow(title: "SatDump", path: satdump)
                }
            }
            if !signalTail.isEmpty {
                Section("Signal") {
                    ForEach(signalTail.indices, id: \.self) { idx in
                        Text(signalTail[idx])
                            .font(.caption.monospaced())
                            .foregroundStyle(signalTail[idx].contains("SYNCED") ? .green : .secondary)
                            .textSelection(.enabled)
                    }
                }
            }
            if !satdumpTail.isEmpty {
                Section("SatDump Tail") {
                    ForEach(satdumpTail.indices, id: \.self) { idx in
                        Text(satdumpTail[idx])
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                    }
                }
            }
            Section("Scheduler Tail") {
                if schedulerTail.isEmpty {
                    Text("No scheduler log lines.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(schedulerTail.indices, id: \.self) { idx in
                        Text(schedulerTail[idx])
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                    }
                }
            }
        }
    }
}

private struct LogPathRow: View {
    let title: String
    let path: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(path)
                .font(.caption.monospaced())
                .textSelection(.enabled)
        }
    }
}
