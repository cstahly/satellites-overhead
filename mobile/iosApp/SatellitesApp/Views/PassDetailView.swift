import SwiftUI
import MapKit
import Shared

struct PassDetailView: View {
    let pass: Pass
    @EnvironmentObject private var app: AppState
    @State private var showScanAlert = false

    private var track: [AnyObject] { pass.track as [AnyObject] }

    private var groundTrackCoords: [CLLocationCoordinate2D] {
        (pass.track as? [TrackPoint] ?? pass.track.compactMap { $0 as? TrackPoint })
            .map { CLLocationCoordinate2D(latitude: $0.subLat, longitude: $0.subLon) }
    }

    private var observerCoord: CLLocationCoordinate2D {
        CLLocationCoordinate2D(
            latitude: UserDefaults.standard.double(forKey: "latitude").nonZero ?? 40.42,
            longitude: UserDefaults.standard.double(forKey: "longitude").nonZero ?? -86.88
        )
    }

    private var mapRegion: MKCoordinateRegion {
        guard !groundTrackCoords.isEmpty else {
            return MKCoordinateRegion(center: observerCoord, span: MKCoordinateSpan(latitudeDelta: 30, longitudeDelta: 30))
        }
        let lats = groundTrackCoords.map { $0.latitude }
        let lons = groundTrackCoords.map { $0.longitude }
        let center = CLLocationCoordinate2D(
            latitude: (lats.min()! + lats.max()!) / 2,
            longitude: (lons.min()! + lons.max()!) / 2
        )
        let span = MKCoordinateSpan(
            latitudeDelta: max(10, (lats.max()! - lats.min()!) * 1.3),
            longitudeDelta: max(10, (lons.max()! - lons.min()!) * 1.3)
        )
        return MKCoordinateRegion(center: center, span: span)
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                // Sky plot
                VStack(alignment: .leading, spacing: 6) {
                    Text("Sky Track").font(.caption).foregroundStyle(.secondary).padding(.horizontal)
                    SkyPlotView(pass: pass, track: track)
                        .aspectRatio(1, contentMode: .fit)
                        .padding(.horizontal)
                }

                // Ground track map
                VStack(alignment: .leading, spacing: 6) {
                    Text("Ground Track").font(.caption).foregroundStyle(.secondary).padding(.horizontal)
                    Map(initialPosition: .region(mapRegion)) {
                        if !groundTrackCoords.isEmpty {
                            MapPolyline(coordinates: groundTrackCoords)
                                .stroke(.green, lineWidth: 2)
                            // AOS/LOS markers
                            if let first = groundTrackCoords.first {
                                Annotation("AOS", coordinate: first, anchor: .bottom) {
                                    Circle().fill(.green).frame(width: 8)
                                }
                            }
                            if let last = groundTrackCoords.last {
                                Annotation("LOS", coordinate: last, anchor: .bottom) {
                                    Circle().fill(.orange).frame(width: 8)
                                }
                            }
                        }
                        Annotation("Observer", coordinate: observerCoord, anchor: .bottom) {
                            Image(systemName: "antenna.radiowaves.left.and.right")
                                .font(.title2)
                                .foregroundStyle(.white)
                                .background(Circle().fill(.black.opacity(0.6)).padding(-4))
                        }
                    }
                    .frame(height: 260)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .padding(.horizontal)
                }

                // Pass details
                GroupBox {
                    Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                        GridRow {
                            Text("AOS").foregroundStyle(.secondary)
                            Text(pass.aos.shortTime)
                        }
                        GridRow {
                            Text("LOS").foregroundStyle(.secondary)
                            Text(pass.los.shortTime)
                        }
                        GridRow {
                            Text("Duration").foregroundStyle(.secondary)
                            Text("\(pass.durationSeconds / 60)m \(pass.durationSeconds % 60)s")
                        }
                        GridRow {
                            Text("Peak el.").foregroundStyle(.secondary)
                            Text(String(format: "%.1f°", pass.maxElevation))
                                .foregroundStyle(pass.maxElevation >= 60 ? .green : .primary)
                        }
                        GridRow {
                            Text("Azimuth").foregroundStyle(.secondary)
                            Text("\(Int(pass.aosAzimuth))° → \(Int(pass.maxAzimuth))° → \(Int(pass.losAzimuth))°")
                        }
                    }
                    .font(.subheadline)
                }
                .padding(.horizontal)

                Button {
                    showScanAlert = true
                } label: {
                    Label("Queue Capture", systemImage: "dot.radiowaves.up.forward")
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 4)
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)
                .padding(.horizontal)
                .padding(.bottom)
            }
            .padding(.top, 8)
        }
        .navigationTitle(pass.name)
        .navigationBarTitleDisplayMode(.inline)
        .alert("Scan \(pass.name)?", isPresented: $showScanAlert) {
            Button("Queue") {
                Task { await app.triggerScan(norad: Int32(pass.norad), name: pass.name, durationS: Int32(pass.durationSeconds)) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Queue a \(pass.durationSeconds / 60)m \(pass.durationSeconds % 60)s capture.")
        }
    }
}

private extension Double {
    var nonZero: Double? { self == 0 ? nil : self }
}
