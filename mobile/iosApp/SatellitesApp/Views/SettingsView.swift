import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var app: AppState

    @State private var serverUrl = UserDefaults.standard.string(forKey: "server_url") ?? "https://sdr.sadbabyrabbit.com"
    @State private var token = UserDefaults.standard.string(forKey: "bearer_token") ?? ""
    @State private var lat = UserDefaults.standard.string(forKey: "latitude") ?? "40.42"
    @State private var lon = UserDefaults.standard.string(forKey: "longitude") ?? "-86.88"
    @State private var alt = UserDefaults.standard.string(forKey: "altitude_m") ?? "180"
    @State private var saved = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    TextField("Server URL", text: $serverUrl)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                    SecureField("Bearer Token", text: $token)
                }
                Section("Location") {
                    TextField("Latitude", text: $lat)
                        .keyboardType(.decimalPad)
                    TextField("Longitude", text: $lon)
                        .keyboardType(.decimalPad)
                    TextField("Altitude (m)", text: $alt)
                        .keyboardType(.numberPad)
                }
                Section {
                    Button("Save & Reconnect") {
                        UserDefaults.standard.set(serverUrl.trimmingCharacters(in: .init(charactersIn: "/")), forKey: "server_url")
                        UserDefaults.standard.set(token.trimmingCharacters(in: .whitespaces), forKey: "bearer_token")
                        UserDefaults.standard.set(lat, forKey: "latitude")
                        UserDefaults.standard.set(lon, forKey: "longitude")
                        UserDefaults.standard.set(alt, forKey: "altitude_m")
                        app.rebuildApi()
                        Task { await app.refreshAll() }
                        saved = true
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            .navigationTitle("Settings")
            .alert("Saved", isPresented: $saved) {
                Button("OK", role: .cancel) {}
            }
        }
    }
}
