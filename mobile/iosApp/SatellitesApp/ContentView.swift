import SwiftUI

struct ContentView: View {
    @State private var selectedTab = 0

    var body: some View {
        TabView(selection: $selectedTab) {
            StatusView(selectedTab: $selectedTab)
                .tabItem { Label("Status", systemImage: "antenna.radiowaves.left.and.right") }
                .tag(0)
            PassesView()
                .tabItem { Label("Passes", systemImage: "dot.radiowaves.up.forward") }
                .tag(1)
            CapturesView()
                .tabItem { Label("Captures", systemImage: "clock.arrow.circlepath") }
                .tag(2)
            RulesView()
                .tabItem { Label("Rules", systemImage: "calendar.badge.clock") }
                .tag(3)
            EventsView()
                .tabItem { Label("Events", systemImage: "bolt.fill") }
                .tag(4)
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gear") }
                .tag(5)
        }
        .tint(.green)
    }
}
