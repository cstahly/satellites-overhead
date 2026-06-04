import SwiftUI
import Shared

struct EventsView: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        NavigationStack {
            Group {
                if app.events.isEmpty {
                    ContentUnavailableView("No Events", systemImage: "bolt", description: Text(app.eventsError ?? "No events yet."))
                } else {
                    List(app.events, id: \.id) { event in
                        EventRow(event: event)
                    }
                }
            }
            .navigationTitle("Events")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { Task { await app.refreshEvents() } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .refreshable { await app.refreshEvents() }
        }
    }
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
