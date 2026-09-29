import Foundation

/// Birth years and ages, always in the GREGORIAN calendar. `Calendar.current` follows the device
/// region, not only its language: Thailand defaults to the Buddhist calendar (year 2569, not 2026),
/// Japan can use the Japanese era. Mixing that live year with a stored Gregorian birth year gave
/// Thai users an age in the hundreds (their calorie goal clamped to the floor), a birth-year
/// wheel ending at 2553, and a birthday picker that silently corrupted the stored year.
enum BirthYears {
    static let oldest = 1940
    static let minimumAge = 13

    /// A Gregorian calendar in `calendar`'s time zone (so "today" is the user's day).
    static func gregorian(like calendar: Calendar = .current) -> Calendar {
        var g = Calendar(identifier: .gregorian)
        g.timeZone = calendar.timeZone
        return g
    }

    /// The birth-year wheel: `oldest` … this Gregorian year − `minimumAge`.
    static func range(now: Date = Date(), calendar: Calendar = .current) -> ClosedRange<Int> {
        oldest...(gregorian(like: calendar).component(.year, from: now) - minimumAge)
    }

    /// Whole years on `date` for someone born in Gregorian `year` (month/day optional: without them
    /// the birthday counts as passed at the start of the year).
    static func age(birthYear year: Int, month: Int = 1, day: Int = 1, on date: Date = Date(),
                    calendar: Calendar = .current) -> Int {
        let now = gregorian(like: calendar).dateComponents([.year, .month, .day], from: date)
        guard let y = now.year, let m = now.month, let d = now.day else { return 0 }
        var age = y - year
        if m < month || (m == month && d < day) { age -= 1 }
        return max(0, age)
    }

    /// A Date from a stored Gregorian birthday (for a DatePicker), and back.
    static func date(year: Int, month: Int = 1, day: Int = 1, calendar: Calendar = .current) -> Date? {
        gregorian(like: calendar).date(from: DateComponents(year: year, month: month, day: day))
    }

    static func components(of date: Date, calendar: Calendar = .current) -> (year: Int, month: Int, day: Int) {
        let c = gregorian(like: calendar).dateComponents([.year, .month, .day], from: date)
        return (c.year ?? 1995, c.month ?? 1, c.day ?? 1)
    }
}
