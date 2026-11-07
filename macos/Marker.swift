import Foundation
import CoreGraphics
import ImageIO

struct DingEvent: Codable, Equatable {
    let id: String
    let level: Int
    let name: String?
    let kind: UInt8

    var message: String {
        if kind == 0x22, let name { return "Test ding! \(name) is level \(level) in WoW." }
        if let name { return "Ding! \(name) reached level \(level) in WoW." }
        return "Ding! Reached level \(level) in WoW."
    }
}

struct DingError: LocalizedError {
    let errorDescription: String?
    init(_ message: String) { errorDescription = message }
}

enum Marker {
    static func decode(_ file: URL) throws -> DingEvent? {
        guard let source = CGImageSourceCreateWithURL(file as CFURL, nil),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int else {
            throw DingError("Waiting for a complete screenshot.")
        }
        let cell = Double(height) / 96
        guard cell >= 4, Double(width) >= 9 * cell, width <= 40_000_000 / height else { return nil }
        guard let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
              CGImageSourceGetStatusAtIndex(source, 0) == .statusComplete else {
            throw DingError("Waiting for a complete screenshot.")
        }
        let w = min(width, Int((49 * cell).rounded())), h = Int((12 * cell).rounded())
        guard let corner = image.cropping(to: CGRect(x: 0, y: 0, width: w, height: h)),
              let context = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
                                      bytesPerRow: w, space: CGColorSpaceCreateDeviceGray(),
                                      bitmapInfo: CGImageAlphaInfo.none.rawValue),
              let pixels = context.data?.assumingMemoryBound(to: UInt8.self) else {
            throw DingError("Could not read the screenshot pixels.")
        }
        context.draw(corner, in: CGRect(x: 0, y: 0, width: w, height: h))
        var bytes = [UInt8]()
        var length = 11
        while bytes.count < length {
            let block = bytes.count / 11, row = bytes.count % 11
            guard Double(9 + block * 8) * cell <= Double(w) + 0.5 else { return nil }
            var byte: UInt8 = 0
            for column in (8 * block)..<(8 * block + 8) {
                // At least five of nine interior samples must agree, as in marker.py.
                var dark = 0, light = 0
                for dy in [0.35, 0.5, 0.65] {
                    for dx in [0.35, 0.5, 0.65] {
                        let x = Int((Double(1 + column) + dx) * cell)
                        let y = Int((Double(1 + row) + dy) * cell)
                        let pixel = pixels[y * w + x]
                        if pixel <= 65 { dark += 1 }
                        if pixel >= 190 { light += 1 }
                    }
                }
                guard dark >= 5 || light >= 5 else { return nil }
                byte = byte << 1 | (light >= 5 ? 1 : 0)
            }
            bytes.append(byte)
            switch bytes.count {
            case 1 where byte != 0xd6, 2 where byte != 0x39: return nil
            case 3 where ![0x10, 0x11, 0x20, 0x22].contains(byte): return nil
            case 11 where bytes[2] >= 0x20:
                guard (1...48).contains(byte) else { return nil }
                length = 12 + Int(byte)
            default: break
            }
        }
        var crc: UInt8 = 0
        for byte in bytes.dropLast() {
            crc ^= byte
            for _ in 0..<8 { crc = (crc << 1) ^ (crc & 0x80 == 0 ? 0 : 7) }
        }
        guard bytes[3] > 0, crc == bytes.last else { return nil }
        var name: String?
        if bytes[2] >= 0x20 {
            guard let value = String(bytes: bytes[11..<(length - 1)], encoding: .utf8) else { return nil }
            let letters: Set<Unicode.GeneralCategory> = [.lowercaseLetter, .uppercaseLetter, .titlecaseLetter,
                                                         .modifierLetter, .otherLetter]
            let categories = value.unicodeScalars.map { $0.properties.generalCategory }
            guard let first = categories.first, letters.contains(first),
                  categories.allSatisfy({ letters.contains($0) || $0 == .nonspacingMark || $0 == .spacingMark })
            else { return nil }
            name = value
        }
        return DingEvent(id: bytes[2..<10].map { String(format: "%02x", $0) }.joined(),
                         level: Int(bytes[3]), name: name, kind: bytes[2])
    }
}
