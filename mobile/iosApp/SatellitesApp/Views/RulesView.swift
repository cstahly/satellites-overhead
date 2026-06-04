import SwiftUI
import Shared

struct RulesView: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        NavigationStack {
            Group {
                if app.rules.isEmpty {
                    ContentUnavailableView("No Rules", systemImage: "calendar.badge.clock",
                        description: Text(app.rulesError ?? "No recurring capture rules."))
                } else {
                    List(app.rules, id: \.id) { rule in
                        RuleRow(rule: rule) { enabled in
                            Task { await app.setRuleEnabled(rule.id, enabled: enabled) }
                        }
                    }
                }
            }
            .navigationTitle("Rules")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { Task { await app.refreshRules() } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .refreshable { await app.refreshRules() }
        }
    }
}

private struct RuleRow: View {
    let rule: Rule
    let onToggle: (Bool) -> Void
    @State private var isEnabled: Bool

    init(rule: Rule, onToggle: @escaping (Bool) -> Void) {
        self.rule = rule
        self.onToggle = onToggle
        _isEnabled = State(initialValue: rule.enabled)
    }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                Text(rule.name).font(.headline)
                if let profile = rule.profile {
                    Text(profile).font(.caption).foregroundStyle(.secondary)
                }
                if let freq = rule.frequencyHz {
                    Text(String(format: "%.3f MHz", freq.doubleValue / 1e6))
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let minEl = rule.minPeakElevation {
                    Text("Min elevation: \(Int(minEl.doubleValue))°")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer()
            Toggle("", isOn: $isEnabled)
                .labelsHidden()
                .onChange(of: isEnabled) { _, newVal in onToggle(newVal) }
        }
        .padding(.vertical, 2)
    }
}
