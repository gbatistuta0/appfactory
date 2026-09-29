import Foundation

/// Display units. Everything is stored in metric (kg, cm); the unit system only changes what the
/// pickers and labels show.
enum UnitSystem: String, Codable, CaseIterable {
    case metric
    case imperial

    /// Imperial for locales that measure bodies in pounds and inches (US, Liberia, Myanmar —
    /// the regions Foundation reports as `.us`); metric everywhere else.
    static func `default`(for locale: Locale = .current) -> UnitSystem {
        locale.measurementSystem == .us ? .imperial : .metric
    }
}

enum Units {
    static let kgPerLb = 0.45359237
    static let cmPerInch = 2.54

    static func lb(fromKg kg: Double) -> Double { kg / kgPerLb }
    static func kg(fromLb lb: Double) -> Double { lb * kgPerLb }
    static func inches(fromCm cm: Double) -> Double { cm / cmPerInch }
    static func cm(fromInches inches: Double) -> Double { inches * cmPerInch }

    /// Weight in the user's unit (kg or lb).
    static func weightValue(kg: Double, in system: UnitSystem) -> Double {
        system == .metric ? kg : lb(fromKg: kg)
    }

    static func kg(fromDisplayValue value: Double, in system: UnitSystem) -> Double {
        system == .metric ? value : kg(fromLb: value)
    }

    /// Ruler tick for weight: 0.5 kg or 1 lb.
    static func weightStep(_ system: UnitSystem) -> Double { system == .metric ? 0.5 : 1 }

    /// Snaps a display value to the unit's ruler tick (0.5 kg / whole lb).
    static func snap(_ value: Double, in system: UnitSystem) -> Double {
        let step = weightStep(system)
        return (value / step).rounded() * step
    }

    /// Imperial pickers keep whole pounds so the wheel does not drift through metric rounding
    /// (159 lb → kg → back must stay 159 lb).
    static func wholePounds(fromKg kg: Double) -> Int { Int(lb(fromKg: kg).rounded()) }

    static func weightUnitLabel(_ system: UnitSystem) -> String {
        system == .metric ? String(localized: "kg", comment: "Kilogram unit") : String(localized: "lb", comment: "Pound unit")
    }

    /// "6 kg" / "13 lb" — whole numbers when the value is whole, otherwise one decimal. The number
    /// and unit are joined by a no-break space so a title never wraps between them.
    static func formatWeight(kg: Double, in system: UnitSystem, alwaysDecimal: Bool = false) -> String {
        let v = weightValue(kg: kg, in: system)
        return formatNumber(v, alwaysDecimal: alwaysDecimal) + "\u{00A0}" + weightUnitLabel(system)
    }

    /// A whole number in the user's digits without grouping — years, day numbers, picker values:
    /// "1995" in English, "١٩٩٥" in Arabic (the app shows Arabic-Indic digits there, like the system).
    /// Not `String(value)` (always Western digits) and not `.dateTime.day()` (CJK appends 日/일, which
    /// overflowed a fixed-size day ring).
    static func plainNumber(_ value: Int, locale: Locale = .current) -> String {
        value.formatted(.number.grouping(.never).locale(locale))
    }

    static func formatNumber(_ value: Double, alwaysDecimal: Bool = false) -> String {
        let rounded = (value * 10).rounded() / 10
        let whole = rounded == rounded.rounded()
        let digits = alwaysDecimal || !whole ? 1 : 0
        return rounded.formatted(.number.precision(.fractionLength(digits)))
    }
}
