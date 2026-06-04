import SwiftUI
import Shared

struct SkyPlotView: View {
    let pass: Pass
    // track is a NSArray of TrackPoint from Kotlin
    let track: [AnyObject]

    var body: some View {
        Canvas { ctx, size in
            let cx = size.width / 2
            let cy = size.height / 2
            let r = min(cx, cy) - 20

            // Elevation rings (90°=center, 0°=edge)
            for el in stride(from: 0.0, through: 90.0, by: 30.0) {
                let ringR = r * (1.0 - el / 90.0)
                let rect = CGRect(x: cx - ringR, y: cy - ringR, width: ringR * 2, height: ringR * 2)
                var ring = Path(ellipseIn: rect)
                ctx.stroke(ring, with: .color(el == 0 ? .white.opacity(0.5) : .white.opacity(0.2)), lineWidth: el == 0 ? 1.5 : 1)
                // Label
                if el > 0 {
                    ctx.draw(Text("\(Int(el))°").font(.system(size: 9)).foregroundStyle(.secondary),
                             at: CGPoint(x: cx + 4, y: cy - ringR + 2))
                }
            }

            // N/S/E/W labels
            let labels: [(String, Double)] = [("N", 0), ("E", 90), ("S", 180), ("W", 270)]
            for (label, az) in labels {
                let rad = (az - 90) * .pi / 180
                let px = cx + (r + 12) * cos(rad)
                let py = cy + (r + 12) * sin(rad)
                ctx.draw(Text(label).font(.caption2.bold()).foregroundStyle(.secondary),
                         at: CGPoint(x: px, y: py))
            }

            // Cross-hairs
            ctx.stroke(Path { p in
                p.move(to: CGPoint(x: cx, y: cy - r))
                p.addLine(to: CGPoint(x: cx, y: cy + r))
                p.move(to: CGPoint(x: cx - r, y: cy))
                p.addLine(to: CGPoint(x: cx + r, y: cy))
            }, with: .color(.white.opacity(0.1)), lineWidth: 0.5)

            // Track arc
            let points = track.compactMap { $0 as? TrackPoint }
            guard points.count > 1 else { return }

            var arcPath = Path()
            var first = true
            for pt in points {
                let pos = azElToXY(az: pt.az, el: pt.el, cx: cx, cy: cy, r: r)
                if first { arcPath.move(to: pos); first = false }
                else { arcPath.addLine(to: pos) }
            }
            ctx.stroke(arcPath, with: .color(.green.opacity(0.85)), style: StrokeStyle(lineWidth: 2.5, lineCap: .round, lineJoin: .round))

            // AOS dot (green)
            if let first = points.first {
                let p = azElToXY(az: first.az, el: first.el, cx: cx, cy: cy, r: r)
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - 4, y: p.y - 4, width: 8, height: 8)), with: .color(.green))
                ctx.draw(Text("AOS").font(.system(size: 8)).foregroundStyle(.green), at: CGPoint(x: p.x + 8, y: p.y))
            }
            // LOS dot (orange)
            if let last = points.last {
                let p = azElToXY(az: last.az, el: last.el, cx: cx, cy: cy, r: r)
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - 4, y: p.y - 4, width: 8, height: 8)), with: .color(.orange))
                ctx.draw(Text("LOS").font(.system(size: 8)).foregroundStyle(.orange), at: CGPoint(x: p.x + 8, y: p.y))
            }
            // Peak dot (white)
            if let peak = points.max(by: { $0.el < $1.el }) {
                let p = azElToXY(az: peak.az, el: peak.el, cx: cx, cy: cy, r: r)
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - 5, y: p.y - 5, width: 10, height: 10)), with: .color(.white))
                ctx.draw(Text(String(format: "%.0f°", peak.el)).font(.system(size: 8).bold()).foregroundStyle(.white),
                         at: CGPoint(x: p.x + 10, y: p.y))
            }
        }
        .background(Color(white: 0.07))
        .clipShape(Circle())
        .overlay(Circle().stroke(Color.white.opacity(0.2), lineWidth: 1))
    }

    private func azElToXY(az: Double, el: Double, cx: CGFloat, cy: CGFloat, r: CGFloat) -> CGPoint {
        // az: 0=N, 90=E, clockwise. el: 0=horizon, 90=zenith
        let dist = r * (1.0 - el / 90.0)
        let rad = (az - 90.0) * .pi / 180.0
        return CGPoint(x: cx + dist * cos(rad), y: cy + dist * sin(rad))
    }
}
