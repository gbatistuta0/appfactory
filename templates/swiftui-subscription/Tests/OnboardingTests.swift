import XCTest
@testable import __APP_NAME__

@MainActor
final class OnboardingModelTests: XCTestCase {
    func testStepCountMatchesSpecAndFunnelShape() {
        let steps = OnboardingCatalog.steps
        XCTAssertEqual(steps.count, AppSpec.onboardingScreens, "skeleton length = spec design.onboarding_screens")
        XCTAssertEqual(Set(steps.map(\.id)).count, steps.count, "step ids are unique")
        // @if quiz
        XCTAssertGreaterThanOrEqual(steps.filter { $0.kind == .question }.count, 5)
        // @endif
        // @if !quiz
        XCTAssertTrue(steps.filter { [.question, .picker].contains($0.kind) }.isEmpty, "no quiz steps")
        // @endif
        XCTAssertEqual(steps.first?.id, "welcome")
        // @if offer_paywall
        XCTAssertEqual(Array(steps.suffix(2).map(\.id)), ["paywall", "offer"])
        // @endif
        // @if !offer_paywall
        // @if hard_paywall
        XCTAssertEqual(steps.last?.id, "paywall")
        // @endif
        // @if !hard_paywall
        XCTAssertFalse(steps.contains { $0.kind == .paywall }, "no paywall step without the hard paywall")
        // @endif
        // @endif
        // @if siwa
        for kind in [StepKind.loading, .finale, .account] {
        // @endif
        // @if !siwa
        for kind in [StepKind.loading, .finale] {
        // @endif
            XCTAssertTrue(steps.contains { $0.kind == kind }, "\(kind) step present")
        }
        for step in steps where step.kind == .question {
            XCTAssertGreaterThanOrEqual(step.options.count, 2, step.id)
            XCTAssertTrue(step.id.allSatisfy { $0.isLowercase || $0 == "_" || $0.isNumber }, step.id)
        }
    }

    func testNothingIsPreselected() {
        let model = OnboardingModel()
        for step in model.steps where step.kind == .question {
            XCTAssertTrue(model.answers.selected(step.id).isEmpty, step.id)
            XCTAssertFalse(model.canContinue(step), "CTA disabled until \(step.id) is answered")
        }
        XCTAssertNil(model.answers.consentAt)
    }

    // @if quiz
    func testSingleReplacesMultiToggles() throws {
        let model = OnboardingModel()
        let single = try XCTUnwrap(model.steps.first { $0.kind == .question && !$0.multi })
        model.toggle(single.options[0].id, in: single)
        model.toggle(single.options[1].id, in: single)
        XCTAssertEqual(model.answers.selected(single.id), [single.options[1].id])
        XCTAssertTrue(model.canContinue(single))
        if let multi = model.steps.first(where: { $0.multi }) {
            model.toggle(multi.options[0].id, in: multi)
            model.toggle(multi.options[1].id, in: multi)
            XCTAssertEqual(model.answers.selected(multi.id).count, 2)
            model.toggle(multi.options[0].id, in: multi)
            XCTAssertEqual(model.answers.selected(multi.id), [multi.options[1].id])
        }
    }
    // @endif

    func testNavigationAndProgress() {
        let model = OnboardingModel()
        XCTAssertFalse(model.canGoBack)
        XCTAssertEqual(model.progress, 0, "welcome shows no header")
        model.next()
        XCTAssertTrue(model.canGoBack)
        let first = model.progress
        model.next()
        XCTAssertGreaterThan(model.progress, first)
        model.back()
        XCTAssertEqual(model.progress, first)
        // @if offer_paywall
        model.jump(to: "offer")
        XCTAssertEqual(model.step.id, "offer")
        // @endif
    }

    func testConsentGateFollowsSpec() throws {
        let model = OnboardingModel()
        let consent = try XCTUnwrap(model.steps.first { $0.id == "consent" })
        XCTAssertEqual(model.canContinue(consent), !AppSpec.consentRequired)
        model.setConsent(true)
        XCTAssertTrue(model.canContinue(consent))
        XCTAssertNotNil(model.completedAnswers().consentAt)
        XCTAssertNotNil(model.completedAnswers().completedAt)
    }

    func testAnswersPersistInProfileStore() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "tests.\(UUID().uuidString)"))
        let store = ProfileStore(defaults: defaults)
        var answers = OnboardingAnswers()
        answers.choices["goal"] = ["save_time"]
        answers.numbers["birth_year"] = 1990
        store.save(answers)
        XCTAssertEqual(ProfileStore(defaults: defaults).answers, answers)
        store.recordConsent(Date(timeIntervalSince1970: 1))
        XCTAssertNotNil(ProfileStore.storedAnswers(defaults)?.consentAt)
        store.reset()
        XCTAssertNil(ProfileStore(defaults: defaults).answers)
    }

    func testPaywallPersonalizationComesFromAnswers() throws {
        var answers = OnboardingAnswers()
        XCTAssertEqual(PaywallPersonalization(answers: answers).headline, String(localized: "Your personal plan is ready"))
        XCTAssertTrue(PaywallPersonalization(answers: answers).highlights.isEmpty, "no invented content")
        // @if quiz
        let goalStep = try XCTUnwrap(OnboardingCatalog.personalizationSteps.first)
        let option = try XCTUnwrap(OnboardingCatalog.step(goalStep)?.options.first)
        answers.choices[goalStep] = [option.id]
        let p = PaywallPersonalization(answers: answers)
        let title = String(localized: option.title)
        XCTAssertTrue(p.headline.contains(title), p.headline)
        XCTAssertEqual(p.highlights, [title])
        // @endif
        // @if !quiz
        answers.choices["anything"] = ["x"]
        XCTAssertTrue(OnboardingCatalog.personalizationSteps.isEmpty, "no quiz, nothing personalizes the paywall")
        XCTAssertTrue(PaywallPersonalization(answers: answers).highlights.isEmpty)
        // @endif
    }
}

final class UnitsTests: XCTestCase {
    func testLocaleDefault() {
        XCTAssertEqual(UnitSystem.default(for: Locale(identifier: "en_US")), .imperial)
        XCTAssertEqual(UnitSystem.default(for: Locale(identifier: "de_DE")), .metric)
        XCTAssertEqual(UnitSystem.default(for: Locale(identifier: "tr_TR")), .metric)
    }

    func testWeightPickerSnapsAndKeepsWholePounds() {
        var state = WeightPickerState(kg: 72.3, unit: .metric, rangeKg: 40...150)
        XCTAssertEqual(state.step, 0.5)
        let i = state.tickIndex
        state.tickIndex = i
        XCTAssertEqual(state.kg, 72.5, accuracy: 0.001, "metric ruler snaps to 0.5 kg")
        state.setUnit(.imperial)
        XCTAssertEqual(state.unit, .imperial)
        XCTAssertEqual(Units.lb(fromKg: state.kg), 160, accuracy: 0.001, "imperial snaps to whole pounds")
        state.tickIndex += 1
        XCTAssertEqual(Units.wholePounds(fromKg: state.kg), 161)
        state.setUnit(.metric)
        XCTAssertEqual(state.kg.truncatingRemainder(dividingBy: 0.5), 0, accuracy: 0.001)
        state.tickIndex = 10_000
        XCTAssertEqual(state.tickIndex, state.tickCount, "clamped to the range")
    }

    /// Arabic shows Arabic-Indic digits like the system; years are never grouped.
    func testPlainNumbersUseTheLocaleDigitsWithoutGrouping() {
        XCTAssertEqual(Units.plainNumber(1995, locale: Locale(identifier: "en_US")), "1995")
        XCTAssertEqual(Units.plainNumber(1995, locale: Locale(identifier: "ar_SA")), "١٩٩٥")
        XCTAssertEqual(Units.plainNumber(1995, locale: Locale(identifier: "de_DE")), "1995")
    }

    /// Thailand: the Buddhist calendar made ages ~543 years off. Age, the
    /// birth-year range and the picker round trip must match Gregorian under every calendar.
    func testBirthYearsAreCalendarIndependent() {
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(identifier: "UTC")!
        let now = utc.date(from: DateComponents(year: 2026, month: 9, day: 26))!
        let age = BirthYears.age(birthYear: 1995, month: 6, day: 15, on: now, calendar: utc)
        XCTAssertEqual(age, 31)
        XCTAssertEqual(BirthYears.range(now: now, calendar: utc).upperBound, 2026 - BirthYears.minimumAge)
        for id: Calendar.Identifier in [.buddhist, .japanese, .republicOfChina, .persian, .islamicUmmAlQura] {
            var cal = Calendar(identifier: id)
            cal.timeZone = utc.timeZone
            XCTAssertEqual(BirthYears.age(birthYear: 1995, month: 6, day: 15, on: now, calendar: cal), age, "\(id)")
            XCTAssertEqual(BirthYears.range(now: now, calendar: cal), BirthYears.range(now: now, calendar: utc), "\(id)")
            let d = BirthYears.date(year: 1995, month: 6, day: 15, calendar: cal)!
            XCTAssertTrue(BirthYears.components(of: d, calendar: cal) == (1995, 6, 15), "\(id) picker round trip")
        }
    }

    func testFormatting() {
        XCTAssertEqual(Units.formatWeight(kg: 6, in: .metric), "6\u{00A0}" + Units.weightUnitLabel(.metric))
        XCTAssertEqual(Units.snap(72.74, in: .metric), 72.5)
        XCTAssertEqual(Units.snap(159.6, in: .imperial), 160)
    }
}
