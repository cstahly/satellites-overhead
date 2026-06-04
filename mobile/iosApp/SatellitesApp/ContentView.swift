import SwiftUI

struct ContentView: View {
    var body: some View {
        TabView {
            StatusView()
                .tabItem { Label("Status", systemImage: "antenna.radiowaves.left.and.right") }
            PassesView()
                .tabItem { Label("Passes", systemImage: "satellite") }
            CapturesView()
                .tabItem { Label("Captures", systemImage: "clock.arrow.circlepath") }
            EventsView()
                .tabItem { Label("Events", systemImage: "bolt.fill") }
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gear") }
        }
    }
}
