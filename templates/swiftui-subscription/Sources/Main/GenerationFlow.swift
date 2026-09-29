import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

/// Core value loop placeholder: pick a photo → choose a style → generate → result.
///
/// APP-SPECIFIC EXTENSION POINT: the features stage replaces the screen with the app's own action
/// (e.g. a color analysis) but keeps the error routing (`Proxy.route`): 402 → paywall at the
/// server's placement, 429 daily cap → paywall `daily_cap` (free) or the limit message
/// (subscribers), 403 → consent screen, 503 → retry message, never a paywall.

struct GenResult: Identifiable, Hashable {
    let id = UUID()
    let url: URL
    let style: String
    /// Analysis title / summary (subscription template); nil for image generation.
    var title: String? = nil
    var summary: String? = nil
}

struct GenerationView: View {
    @State private var photoItem: PhotosPickerItem?
    @State private var photoData: Data?
    @State private var selectedStyle: String = AppConfig.generationStyles.first ?? ""
    @State private var isGenerating = false
    @State private var errorText: String?
    @State private var showInvalidMediaAlert = false
    @EnvironmentObject private var store: StoreManager
    @EnvironmentObject private var history: GenerationStore
    // @if credits
    @EnvironmentObject private var credits: CreditManager
    @State private var showTopUp = false
    // @endif

    @State private var path: [GenResult] = []
    @State private var paywallSource: PaywallSource?
    @State private var showConsent = false

    private var canGenerate: Bool { !isGenerating && photoData != nil }

    var body: some View {
        NavigationStack(path: $path) {
            ZStack {
                DS.Palette.background.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                        intro
                        inputSection
                        styleSection
                        if let errorText {
                            Text(verbatim: errorText).font(DS.Typography.caption)
                                .foregroundStyle(DS.Palette.destructive)
                                .accessibilityIdentifier("generate_error")
                        }
                    }
                    .padding(.horizontal, DS.Spacing.lg)
                    .padding(.bottom, DS.Spacing.lg)
                }
                .safeAreaInset(edge: .bottom) { generateBar }

                if isGenerating { LoadingOverlay() }
            }
            // System navigation bar (large title; Liquid Glass toolbar items on iOS 26).
            .navigationTitle(Text("Create"))
            .toolbar { toolbarItems }
            .navigationDestination(for: GenResult.self) { result in
                ResultView(result: result, onCreateAnother: { path.removeAll() })
            }
            .onAppear {
                #if DEBUG
                if LaunchOptions.showResult, path.isEmpty, let s = LaunchOptions.sampleURL {
                    path.append(GenResult(url: s, style: selectedStyle))
                }
                #endif
            }
            .fullScreenCover(item: $paywallSource) { source in
                UpgradePaywall(source: source) { paywallSource = nil }
            }
            .sheet(isPresented: $showConsent) {
                ConsentView { agreed in
                    showConsent = false
                    if agreed { Task { await generate() } }
                }
            }
            // @if credits
            .sheet(isPresented: $showTopUp) {
                TopUpSheet(onPurchased: { showTopUp = false })
                    .environmentObject(store).environmentObject(credits)
            }
            // @endif
        }
    }

    /// Trailing toolbar items (system glass on iOS 26): the credit balance and the upgrade button.
    @ToolbarContentBuilder private var toolbarItems: some ToolbarContent {
        // @if credits
        ToolbarItem(placement: .topBarTrailing) {
            Button { showTopUp = true } label: {
                Label {
                    Text(verbatim: "\(credits.credits)")
                } icon: {
                    Image(systemName: "bolt.fill")
                }
                .labelStyle(.titleAndIcon)
                .font(.system(size: 14, weight: .bold))
            }
            .accessibilityIdentifier("create_credits")
        }
        // @endif
        if !store.isSubscribed {
            ToolbarItem(placement: .topBarTrailing) {
                Button { paywallSource = .settings } label: {
                    Label("Premium", systemImage: "crown.fill")
                        .labelStyle(.titleAndIcon)
                        .font(.system(size: 14, weight: .bold))
                }
                .buttonStyle(.borderedProminent)
                .tint(DS.Palette.primary)
                .accessibilityIdentifier("create_premium")
            }
        }
    }

    private var intro: some View {
        Text("Pick a photo and let our AI do the rest.")
            .font(DS.Typography.body).foregroundStyle(DS.Palette.secondaryText)
            .accessibilityIdentifier("create_intro")
    }

    private var inputSection: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
            Text("Your photo").font(DS.Typography.headline).foregroundStyle(DS.Palette.foreground)
            PhotosPicker(selection: $photoItem, matching: .images) {
                if let photoData, let ui = UIImage(data: photoData) {
                    BoundedImage(aspect: 4.0 / 5.0, cornerRadius: DS.Radius.lg) {
                        Image(uiImage: ui).resizable().scaledToFill()
                    }
                } else {
                    ZStack {
                        RoundedRectangle(cornerRadius: DS.Radius.lg).fill(DS.Palette.surface).frame(height: 240)
                            .overlay(RoundedRectangle(cornerRadius: DS.Radius.lg)
                                .strokeBorder(style: StrokeStyle(lineWidth: 1.5, dash: [7, 5]))
                                .foregroundStyle(DS.Palette.primary.opacity(0.6)))
                        VStack(spacing: DS.Spacing.sm) {
                            ZStack {
                                Circle().fill(DS.Palette.primaryContainer).frame(width: 56, height: 56)
                                Image(systemName: "camera.fill").font(.system(size: 22)).foregroundStyle(DS.Palette.primary)
                            }
                            Text("Choose a photo").font(DS.Typography.callout).foregroundStyle(DS.Palette.foreground)
                        }
                    }
                }
            }
            .onChange(of: photoItem) { _, item in Task { await loadPhoto(item) } }
        }
        .alert("Photos only", isPresented: $showInvalidMediaAlert) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("Please choose a photo. Videos aren't supported.")
        }
    }

    private func loadPhoto(_ item: PhotosPickerItem?) async {
        guard let item else { return }
        let isImage = item.supportedContentTypes.contains { $0.conforms(to: .image) }
        guard isImage, let data = try? await item.loadTransferable(type: Data.self), UIImage(data: data) != nil else {
            photoItem = nil
            photoData = nil
            showInvalidMediaAlert = true
            return
        }
        photoData = data
    }

    private var styleSection: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
            Text("Style").font(DS.Typography.headline).foregroundStyle(DS.Palette.foreground)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: DS.Spacing.sm) {
                    ForEach(AppConfig.generationStyles, id: \.self) { style in
                        let selected = style == selectedStyle
                        Text(LocalizedStringKey(style))
                            .font(DS.Typography.callout)
                            .padding(.horizontal, DS.Spacing.md).padding(.vertical, DS.Spacing.sm)
                            .background(selected ? DS.Palette.primary : DS.Palette.surface, in: Capsule())
                            .foregroundStyle(selected ? DS.Palette.onAccent : DS.Palette.foreground)
                            .overlay(Capsule().stroke(DS.Palette.border, lineWidth: selected ? 0 : 1))
                            .onTapGesture { withAnimation(.easeOut(duration: 0.15)) { selectedStyle = style } }
                            .sensoryFeedback(.selection, trigger: selected)
                    }
                }
                .padding(.horizontal, 1)
            }
        }
    }

    private var generateBar: some View {
        Button { Task { await generate() } } label: {
            Group {
                if isGenerating { ProgressView().tint(DS.Palette.onAccent) } else { Label("Generate", systemImage: "wand.and.stars") }
            }
            .frame(maxWidth: .infinity)
        }
        // Floating control: prominent glass on iOS 26 (no material slab behind it).
        .primaryActionStyle()
        .disabled(!canGenerate)
        .opacity(canGenerate ? 1 : 0.5)
        .padding(.horizontal, DS.Spacing.md)
        .padding(.bottom, DS.Spacing.md)
        .accessibilityIdentifier("generate_cta")
    }

    private func generate() async {
        // The client never hard-gates: the server is the authority and answers with the contract's
        // error codes; only then does the UI route to a paywall / consent / message.
        // @if !supabase
        // No backend: the free allowance is counted on the device.
        guard LocalUsageGate.allows(isSubscribed: store.isSubscribed) else {
            paywallSource = .freeScanUsed
            return
        }
        // @endif
        Tracker.log(.generateStart, ["style": selectedStyle])
        let startedAt = Date()
        errorText = nil
        withAnimation { isGenerating = true }
        defer { withAnimation { isGenerating = false } }
        // @if credits
        let prompt = AppConfig.promptTemplate
            .replacingOccurrences(of: "{style}", with: selectedStyle)
            .replacingOccurrences(of: "{concept}", with: AppConfig.appConcept)
        // @endif
        do {
            // @if subscription
            guard let jpeg = photoData?.uploadJPEG() else { throw AIService.AIError.badResponse }
            let analysis = try await AIService.analyze(jpeg: jpeg, note: selectedStyle)
            let item = history.add(data: jpeg, style: analysis.title)
            Tracker.log(.generateSuccess, ["style": selectedStyle,
                                           "duration_ms": String(Int(Date().timeIntervalSince(startedAt) * 1000))])
            path.append(GenResult(url: item?.localURL ?? LaunchOptions.sampleURL ?? URL(fileURLWithPath: "/"),
                                  style: selectedStyle, title: analysis.title, summary: analysis.summary))
            // @endif
            // @if credits
            let jpeg = photoData.flatMap { UIImage(data: $0)?.jpegData(compressionQuality: 0.7) }
            let gen = try await AIService.generateImage(prompt: prompt, imageData: jpeg)
            if let b = gen.balance {
                credits.applyBalance(b)
                Tracker.log(.creditsSpent, ["amount": "1", "remaining": String(b.total), "reason": "generate"])
            }
            let item = await history.add(remoteURL: gen.imageURL, style: selectedStyle, watermark: !store.isSubscribed)
            Tracker.log(.generateSuccess, ["style": selectedStyle,
                                           "duration_ms": String(Int(Date().timeIntervalSince(startedAt) * 1000))])
            path.append(GenResult(url: item?.localURL ?? gen.imageURL, style: selectedStyle, title: nil, summary: nil))
            // @endif
            // @if !supabase
            LocalUsageGate.recordUse()
            // @endif
            photoItem = nil
            photoData = nil
        } catch AIService.AIError.api(let apiError) {
            Tracker.log(.generateFail, ["reason": Self.reason(apiError)])
            route(apiError)
        } catch {
            Tracker.log(.generateFail, ["reason": "bad_response"])
            errorText = AIService.AIError.badResponse.errorDescription
        }
    }

    private func route(_ error: Proxy.APIError) {
        switch Proxy.route(for: error, isSubscribed: store.isSubscribed) {
        case .paywall(let source):
            paywallSource = source
        case .consent:
            showConsent = true
        case .message(let message):
            if case .dailyLimit = message { Tracker.log(.limitReached, ["reason": "daily_cap"]) }
            if case .tooManyAttempts = message { Tracker.log(.limitReached, ["reason": "too_many_attempts"]) }
            errorText = Self.text(for: message)
        // @if credits
        case .topUp:
            Tracker.log(.creditsExhausted, ["subscribed": store.isSubscribed ? "1" : "0"])
            showTopUp = true
        // @endif
        }
    }

    static func reason(_ e: Proxy.APIError) -> String {
        String(String(describing: e).prefix(while: { $0 != "(" }))
    }

    static func text(for message: Proxy.Message) -> String {
        switch message {
        case .notApplicable:
            return String(localized: "This photo isn't something we can analyze. Try another one.")
        case .dailyLimit(let resets):
            if let resets {
                return String(localized: "You've reached today's limit. It resets at \(resets.formatted(date: .omitted, time: .shortened)).")
            }
            return String(localized: "You've reached today's limit. Please come back tomorrow.")
        case .tooManyAttempts:
            return String(localized: "Too many attempts. Please try again later.")
        case .retry:
            return String(localized: "We couldn't verify your subscription right now. Please try again.")
        case .generic:
            return String(localized: "We couldn't finish that right now. Please try again.")
        }
    }
}

extension PaywallSource: Identifiable {
    var id: String { rawValue }
}

private struct LoadingOverlay: View {
    var body: some View {
        ZStack {
            Color.black.opacity(0.45).ignoresSafeArea()
            VStack(spacing: DS.Spacing.lg) {
                MotionSpinner()
                Text("Working on it…")
                    .font(DS.Typography.headline).foregroundStyle(DS.Palette.foreground)
                Text("This usually takes a few seconds.")
                    .font(DS.Typography.caption).foregroundStyle(DS.Palette.secondaryText)
            }
            .padding(DS.Spacing.xl)
            .background(DS.Palette.surface, in: RoundedRectangle(cornerRadius: DS.Radius.xl))
            .shadow(color: .black.opacity(0.2), radius: 24, y: 10)
            .padding(.horizontal, DS.Spacing.xxl)
        }
    }
}

struct ResultView: View {
    let result: GenResult
    var onCreateAnother: () -> Void
    @State private var shareURL: URL?

    var body: some View {
        ZStack {
            DS.Palette.background.ignoresSafeArea()
            VStack(spacing: DS.Spacing.lg) {
                ScrollView {
                    VStack(spacing: DS.Spacing.md) {
                        Group {
                            if let title = result.title { Text(verbatim: title) } else { Text("Your result is ready") }
                        }
                        .font(DS.Typography.title).foregroundStyle(DS.Palette.foreground)
                        .multilineTextAlignment(.center)
                        .accessibilityIdentifier("result_title")
                        if let summary = result.summary {
                            Text(verbatim: summary)
                                .font(DS.Typography.body).foregroundStyle(DS.Palette.secondaryText)
                                .multilineTextAlignment(.center)
                                .padding(.horizontal, DS.Spacing.lg)
                        }
                        BoundedImage(height: 420, cornerRadius: DS.Radius.xxl) {
                            AsyncImage(url: result.url) { img in
                                img.resizable().scaledToFill()
                            } placeholder: {
                                ZStack { DS.Palette.surfaceMuted; ProgressView().tint(DS.Palette.primary) }
                            }
                        }
                        .glowShadow(0.18)
                        .padding(.horizontal, DS.Spacing.lg)
                    }
                    .padding(.vertical, DS.Spacing.lg)
                }
                HStack(spacing: DS.Spacing.md) {
                    Button {
                        Tracker.log(.createAnother, ["style": result.style])
                        onCreateAnother()
                    } label: {
                        Label("Create another", systemImage: "wand.and.stars")
                            .font(DS.Typography.callout)
                            .lineLimit(1).minimumScaleFactor(0.7)
                            .foregroundStyle(DS.Palette.primary)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, DS.Spacing.md)
                            .background(DS.Palette.primaryContainer.opacity(0.55), in: RoundedRectangle(cornerRadius: DS.Radius.md))
                    }
                    if let shareURL {
                        ShareLink(item: shareURL) {
                            Label("Share", systemImage: "square.and.arrow.up")
                                .font(DS.Typography.callout).fontWeight(.semibold)
                                .foregroundStyle(DS.Palette.onAccent)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, DS.Spacing.md)
                                .background(DS.Palette.primary, in: RoundedRectangle(cornerRadius: DS.Radius.md))
                        }
                        .simultaneousGesture(TapGesture().onEnded { Tracker.log(.resultShare, ["style": result.style]) })
                    } else {
                        ProgressView().tint(DS.Palette.primary).frame(maxWidth: .infinity)
                    }
                }
                .padding(.horizontal, DS.Spacing.lg).padding(.bottom, DS.Spacing.md)
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .task { await prepareShare() }
        .onAppear { Tracker.log(.resultView, ["style": result.style]) }
    }

    private func prepareShare() async {
        if result.url.isFileURL { shareURL = result.url; return }
        do {
            let (data, _) = try await URLSession.shared.data(from: result.url)
            let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("share-\(result.id.uuidString).jpg")
            try data.write(to: tmp)
            shareURL = tmp
        } catch {
            shareURL = result.url
        }
    }
}
