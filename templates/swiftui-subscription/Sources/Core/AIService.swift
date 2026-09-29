import Foundation
import UIKit

/// AI calls go only through the app's Edge Functions. The app holds no AI provider key. The
/// server gates usage (free allowance, subscription, daily caps, consent) and answers with the
/// contract's error codes, which `Proxy` maps to `Proxy.APIError`.
enum AIService {
    enum AIError: LocalizedError, Equatable {
        case api(Proxy.APIError)
        case badResponse
        var errorDescription: String? { String(localized: "We couldn't finish that right now. Please try again.") }
    }

    // @if subscription
    /// `POST /functions/v1/analyze` result (backend CONTRACT §2). `result` is app-specific
    /// (`supabase/functions/_shared/analysis.ts` AnalysisResult); the features stage extends it.
    struct Analysis: Equatable {
        let analysisID: Int
        let title: String
        let summary: String
        let tags: [String]
        let confidence: Double

        init?(json: [String: Any]) {
            guard let result = json["result"] as? [String: Any], let title = result["title"] as? String else { return nil }
            analysisID = json["analysis_id"] as? Int ?? 0
            self.title = title
            summary = result["summary"] as? String ?? ""
            tags = result["tags"] as? [String] ?? []
            confidence = result["confidence"] as? Double ?? 0
        }
    }

    /// Photo analysis. The JPEG is re-encoded on device (≤ 1024 px long edge, quality ~0.7), so
    /// EXIF location data never leaves the phone.
    static func analyze(jpeg: Data, note: String? = nil) async throws -> Analysis {
        var body: [String: Any] = ["mode": "photo", "image": ["data": jpeg.base64EncodedString()],
                                   "locale": AppConfig.appLanguage]
        if let note, !note.isEmpty { body["note"] = String(note.prefix(280)) }
        let obj: [String: Any]
        do {
            obj = try await Proxy.post("analyze", body: body, timeout: 60)
        } catch let e as Proxy.APIError {
            throw AIError.api(e)
        }
        guard let analysis = Analysis(json: obj) else { throw AIError.badResponse }
        return analysis
    }
    // @endif

    // @if credits
    struct Generation {
        let imageURL: URL
        let balance: CreditManager.Balance?
    }

    /// Credits mode (legacy ai-proxy): image generation, one credit per success.
    static func generateImage(prompt: String, imageData: Data? = nil) async throws -> Generation {
        var payload: [String: Any] = ["action": "image", "prompt": prompt]
        if let imageData {
            let uri = "data:image/jpeg;base64,\(imageData.base64EncodedString())"
            payload["image_urls"] = [uri]
            payload["image_url"] = uri
        }
        let obj: [String: Any]
        do {
            obj = try await Proxy.post(AppConfig.aiFunction, body: payload, timeout: 120)
        } catch let e as Proxy.APIError {
            throw AIError.api(e)
        }
        guard let result = obj["result"] as? [String: Any],
              let images = result["images"] as? [[String: Any]],
              let urlStr = images.first?["url"] as? String,
              let url = URL(string: urlStr)
        else { throw AIError.badResponse }
        let balance = (obj["balance"] as? [String: Any]).flatMap(CreditManager.Balance.init(json:))
        return Generation(imageURL: url, balance: balance)
    }
    // @endif
}

extension Data {
    /// Downscaled JPEG for upload (long edge ≤ 1024 px, quality 0.7, no EXIF).
    func uploadJPEG(maxEdge: CGFloat = 1024) -> Data? {
        guard let image = UIImage(data: self) else { return nil }
        let scale = Swift.min(1, maxEdge / Swift.max(image.size.width, image.size.height))
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let resized = UIGraphicsImageRenderer(size: size).image { _ in image.draw(in: CGRect(origin: .zero, size: size)) }
        return resized.jpegData(compressionQuality: 0.7)
    }
}
