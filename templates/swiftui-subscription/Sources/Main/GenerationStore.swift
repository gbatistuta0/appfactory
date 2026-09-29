import Foundation
import UIKit

/// PERSISTENT history of generated images (Gallery).
/// Important: AI provider (fal.ai) URLs are TEMPORARY → we download the image to local disk
/// and store it; the Gallery loads from the local file (indefinite, works offline).
struct GenerationItem: Identifiable, Codable, Hashable {
    var id = UUID()
    let filename: String       // Documents/creations/<id>.jpg
    let style: String
    let date: Date

    var localURL: URL {
        GenerationStore.dir.appendingPathComponent(filename)
    }
}

@MainActor
final class GenerationStore: ObservableObject {
    @Published private(set) var items: [GenerationItem] = []
    private let key = "generation_history"

    static let dir: URL = {
        let d = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("creations", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }()

    init() {
        load()
        #if DEBUG
        if LaunchOptions.seedGallery && items.isEmpty {
            // Each style with a sample image in ITS OWN style (sample_<Style>.jpg, else sample.jpg).
            for (i, style) in AppConfig.generationStyles.enumerated() {
                guard let url = Bundle.main.url(forResource: "sample_\(style)", withExtension: "jpg")
                        ?? LaunchOptions.sampleURL,
                      let data = try? Data(contentsOf: url) else { continue }
                let fn = "seed_\(i).jpg"
                try? data.write(to: Self.dir.appendingPathComponent(fn))
                items.append(GenerationItem(filename: fn, style: style,
                                            date: Date().addingTimeInterval(Double(-i) * 3600)))
            }
        }
        #endif
    }

    /// Store local image data (e.g. the analyzed photo) and add it to history.
    @discardableResult
    func add(data: Data, style: String) -> GenerationItem? {
        let item = GenerationItem(filename: "\(UUID().uuidString).jpg", style: style, date: Date())
        guard (try? data.write(to: item.localURL)) != nil else { return nil }
        items.insert(item, at: 0)
        save()
        return item
    }

    /// Download from a remote URL, write to disk as JPEG, add to history.
    /// watermark=true (free user) → the app watermark is added to the image (premium = clean).
    @discardableResult
    func add(remoteURL: URL, style: String, watermark: Bool = false) async -> GenerationItem? {
        let id = UUID()
        let filename = "\(id.uuidString).jpg"
        do {
            let (data, _) = try await URLSession.shared.data(from: remoteURL)
            var image = UIImage(data: data)
            if watermark, let img = image { image = Self.watermarked(img) }
            let jpeg = image?.jpegData(compressionQuality: 0.92) ?? data
            try jpeg.write(to: Self.dir.appendingPathComponent(filename))
            let item = GenerationItem(id: id, filename: filename, style: style, date: Date())
            items.insert(item, at: 0)
            save()
            return item
        } catch {
            return nil
        }
    }

    /// Stamp a semi-transparent watermark in the bottom-right corner of the image.
    /// Watermark = app LOGO (left) + full app NAME (right), in the bottom-right corner.
    static func watermarked(_ image: UIImage) -> UIImage {
        let size = image.size
        let renderer = UIGraphicsImageRenderer(size: size)
        return renderer.image { ctx in
            image.draw(in: CGRect(origin: .zero, size: size))
            let text = AppConfig.appDisplayName as NSString
            let fontSize = max(size.width * 0.045, 20)
            let attrs: [NSAttributedString.Key: Any] = [
                .font: UIFont.systemFont(ofSize: fontSize, weight: .bold),
                .foregroundColor: UIColor.white.withAlphaComponent(0.92),
                .shadow: { let s = NSShadow(); s.shadowColor = UIColor.black.withAlphaComponent(0.5)
                    s.shadowBlurRadius = 4; s.shadowOffset = CGSize(width: 0, height: 1); return s }(),
            ]
            let ts = text.size(withAttributes: attrs)
            let logoSize = fontSize * 1.35
            let gap = fontSize * 0.35
            let pad = size.width * 0.04
            let rowH = max(logoSize, ts.height)
            let totalW = logoSize + gap + ts.width
            let x = size.width - totalW - pad
            let y = size.height - rowH - pad
            // Logo (rounded square)
            if let logo = UIImage(named: "AppLogo") {
                let logoRect = CGRect(x: x, y: y + (rowH - logoSize) / 2, width: logoSize, height: logoSize)
                ctx.cgContext.saveGState()
                UIBezierPath(roundedRect: logoRect, cornerRadius: logoSize * 0.22).addClip()
                logo.draw(in: logoRect)
                ctx.cgContext.restoreGState()
            }
            text.draw(at: CGPoint(x: x + logoSize + gap, y: y + (rowH - ts.height) / 2), withAttributes: attrs)
        }
    }

    /// Distinct local days with a saved result: RatingPolicy's success-day count and milestones.
    var activeDays: Int {
        Set(items.map { Calendar.current.startOfDay(for: $0.date) }).count
    }

    func remove(_ item: GenerationItem) {
        try? FileManager.default.removeItem(at: item.localURL)
        items.removeAll { $0.id == item.id }
        save()
    }

    private func load() {
        guard let data = UserDefaults.standard.data(forKey: key),
              let decoded = try? JSONDecoder().decode([GenerationItem].self, from: data) else { return }
        // keep only those whose file still exists (cleanup)
        items = decoded.filter { FileManager.default.fileExists(atPath: $0.localURL.path) }
    }

    private func save() {
        if let data = try? JSONEncoder().encode(items) {
            UserDefaults.standard.set(data, forKey: key)
        }
    }
}
