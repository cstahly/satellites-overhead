import Foundation

extension String {
    // "2026-06-04T15:21:00Z" → "15:21:00"
    var shortTime: String { components(separatedBy: "T").last?.replacingOccurrences(of: "Z", with: "") ?? self }
    // "2026-06-04T15:21:00Z" → "Jun 4 15:21"
    var shortDateTime: String {
        let parts = components(separatedBy: "T")
        guard parts.count == 2 else { return self }
        let date = parts[0].components(separatedBy: "-")
        let time = parts[1].replacingOccurrences(of: "Z", with: "").prefix(5)
        let months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        let month = Int(date.count > 1 ? date[1] : "0").flatMap { months[safe: $0] } ?? ""
        let day = date.count > 2 ? date[2] : ""
        return "\(month) \(day) \(time)"
    }
}

private extension Array {
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}
