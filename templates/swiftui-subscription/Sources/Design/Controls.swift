import SwiftUI

// Onboarding / paywall controls, (option cards, wheel, ruler, switch) onto the
// template's DS tokens. Every control ticks a selection haptic and is VoiceOver-adjustable.

// MARK: - Option card (question screens)

struct OptionCard: View {
    let title: LocalizedStringResource
    var subtitle: LocalizedStringResource? = nil
    var icon: String? = nil
    let selected: Bool
    var identifier: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                if let icon {
                    Image(systemName: icon)
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(selected ? DS.Palette.onAccent : DS.Palette.primary)
                        .frame(width: 40, height: 40)
                        .background(Circle().fill(selected ? DS.Palette.primary : DS.Palette.primaryContainer.opacity(0.5)))
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(DS.Palette.foreground)
                    if let subtitle {
                        Text(subtitle)
                            .font(.system(size: 13))
                            .foregroundStyle(DS.Palette.secondaryText)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                CheckCircle(selected: selected)
            }
            .padding(.vertical, 12)
            .padding(.leading, icon == nil ? 20 : 12)
            .padding(.trailing, 16)
            .frame(maxWidth: .infinity, minHeight: 64, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: DS.Radius.lg, style: .continuous)
                .fill(selected ? DS.Palette.primaryContainer.opacity(0.45) : DS.Palette.surface))
            .overlay(RoundedRectangle(cornerRadius: DS.Radius.lg, style: .continuous)
                .strokeBorder(selected ? DS.Palette.primary : DS.Palette.border, lineWidth: 2))
            .scaleEffect(selected ? 1.02 : 1)
            .animation(.spring(response: 0.3, dampingFraction: 0.7), value: selected)
            .contentShape(RoundedRectangle(cornerRadius: DS.Radius.lg))
        }
        .buttonStyle(.plain)
        .sensoryFeedback(.selection, trigger: selected)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityIdentifier(identifier)
    }
}

/// The selection circle at the end of an option card.
struct CheckCircle: View {
    let selected: Bool

    var body: some View {
        ZStack {
            Circle().fill(selected ? DS.Palette.primary : Color.clear)
            Circle().strokeBorder(selected ? DS.Palette.primary : DS.Palette.border, lineWidth: 2)
            Image(systemName: "checkmark")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(DS.Palette.onAccent)
                .scaleEffect(selected ? 1 : 0)
                .opacity(selected ? 1 : 0)
        }
        .frame(width: 26, height: 26)
        .animation(.spring(response: 0.3, dampingFraction: 0.7), value: selected)
    }
}

// MARK: - Wheel picker

/// Scroll wheel with 44pt rows, a highlight capsule in the middle and faded edges. Snaps per row
/// and ticks a selection haptic on every detent. VoiceOver: adjustable.
struct WheelPicker: View {
    let items: [String]
    @Binding var selection: Int
    var label: LocalizedStringResource? = nil
    var identifier: String

    private let rowHeight: CGFloat = 44
    private let height: CGFloat = 220
    @State private var scrolledID: Int?

    var body: some View {
        VStack(spacing: 10) {
            if let label {
                Text(label)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(DS.Palette.secondaryText)
                    .frame(maxWidth: .infinity)
            }
            ZStack {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(DS.Palette.surface)
                    .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .strokeBorder(DS.Palette.border, lineWidth: 1.5))
                    .frame(height: rowHeight)

                ScrollView(.vertical, showsIndicators: false) {
                    LazyVStack(spacing: 0) {
                        ForEach(items.indices, id: \.self) { i in
                            row(i)
                                .id(i)
                                .onTapGesture { withAnimation(.easeOut(duration: 0.25)) { scrolledID = i } }
                        }
                    }
                    .scrollTargetLayout()
                }
                .contentMargins(.vertical, (height - rowHeight) / 2, for: .scrollContent)
                .scrollTargetBehavior(.viewAligned)
                .scrollPosition(id: $scrolledID, anchor: .center)
                .mask(LinearGradient(stops: [.init(color: .clear, location: 0), .init(color: .black, location: 0.32),
                                             .init(color: .black, location: 0.68), .init(color: .clear, location: 1)],
                                     startPoint: .top, endPoint: .bottom))
            }
            .frame(height: height)
        }
        .onAppear { scrolledID = selection }
        .onChange(of: scrolledID) { _, new in
            if let new, new != selection, items.indices.contains(new) { selection = new }
        }
        .onChange(of: selection) { _, new in
            if scrolledID != new { withAnimation(.easeOut(duration: 0.25)) { scrolledID = new } }
        }
        .sensoryFeedback(.selection, trigger: selection)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label.map { Text($0) } ?? Text(verbatim: ""))
        .accessibilityValue(Text(verbatim: items.indices.contains(selection) ? items[selection] : ""))
        .accessibilityAdjustableAction { direction in
            switch direction {
            case .increment: selection = min(items.count - 1, selection + 1)
            case .decrement: selection = max(0, selection - 1)
            @unknown default: break
            }
        }
        .accessibilityIdentifier(identifier)
    }

    private func row(_ i: Int) -> some View {
        let d = abs(i - selection)
        return Text(verbatim: items[i])
            .font(.system(size: d == 0 ? 23 : 18, weight: d == 0 ? .heavy : .medium))
            .monospacedDigit()
            .foregroundStyle(d == 0 ? DS.Palette.foreground : DS.Palette.secondaryText)
            .opacity(d == 0 ? 1 : (d == 1 ? 0.75 : 0.45))
            .lineLimit(1)
            .minimumScaleFactor(0.6)
            .frame(maxWidth: .infinity)
            .frame(height: rowHeight)
            .contentShape(Rectangle())
            .animation(.easeOut(duration: 0.15), value: selection)
    }
}

// MARK: - Horizontal ruler

/// Tick ruler: 12pt per tick, major tick every 10 with a label, center indicator.
struct RulerPicker: View {
    /// Number of ticks − 1 (the index range is 0...count).
    let count: Int
    @Binding var index: Int
    /// Medium tick every n ticks; major = every 10.
    var midEvery = 5
    /// Label for a major tick index.
    let label: (Int) -> String
    var identifier: String
    var accessibilityValue: String

    private let spacing: CGFloat = 12
    @State private var scrolledID: Int?

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .top) {
                ScrollView(.horizontal, showsIndicators: false) {
                    LazyHStack(alignment: .top, spacing: 0) {
                        ForEach(0...count, id: \.self) { k in
                            tick(k).id(k)
                        }
                    }
                    .scrollTargetLayout()
                }
                .contentMargins(.horizontal, geo.size.width / 2 - spacing / 2, for: .scrollContent)
                .scrollTargetBehavior(.viewAligned(limitBehavior: .never))
                .scrollPosition(id: $scrolledID, anchor: .center)
                .mask(LinearGradient(stops: [.init(color: .clear, location: 0), .init(color: .black, location: 0.25),
                                             .init(color: .black, location: 0.75), .init(color: .clear, location: 1)],
                                     startPoint: .leading, endPoint: .trailing))

                Capsule()
                    .fill(DS.Palette.primary)
                    .frame(width: 4, height: 72)
                    .background(Capsule().fill(DS.Palette.primary.opacity(0.18)).padding(-4))
                    .offset(y: -6)
                    .allowsHitTesting(false)
            }
        }
        .frame(height: 120)
        .onAppear { scrolledID = index }
        .onChange(of: scrolledID) { _, new in
            if let new, new != index { index = min(count, max(0, new)) }
        }
        .onChange(of: index) { _, new in
            if scrolledID != new { withAnimation(.easeOut(duration: 0.25)) { scrolledID = new } }
        }
        .sensoryFeedback(.selection, trigger: index)
        .accessibilityElement(children: .ignore)
        .accessibilityValue(Text(verbatim: accessibilityValue))
        .accessibilityAdjustableAction { direction in
            switch direction {
            case .increment: index = min(count, index + 1)
            case .decrement: index = max(0, index - 1)
            @unknown default: break
            }
        }
        .accessibilityIdentifier(identifier)
    }

    private func tick(_ k: Int) -> some View {
        let major = k % 10 == 0, mid = k % midEvery == 0
        return VStack(spacing: 8) {
            RoundedRectangle(cornerRadius: 1)
                .fill(major ? DS.Palette.foreground : DS.Palette.border)
                .frame(width: 2, height: major ? 56 : (mid ? 36 : 24))
            Text(verbatim: major ? label(k) : " ")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(DS.Palette.secondaryText)
                .fixedSize()
                .frame(width: spacing)
        }
        .frame(width: spacing, height: 110, alignment: .top)
    }
}

// MARK: - Switch

struct DesignSwitch: View {
    @Binding var isOn: Bool
    let label: LocalizedStringResource
    var identifier: String

    var body: some View {
        Button { isOn.toggle() } label: {
            Capsule()
                .fill(isOn ? DS.Palette.primary : DS.Palette.border)
                .frame(width: 56, height: 34)
                .overlay(alignment: .leading) {
                    Circle()
                        .fill(Color.white)
                        .frame(width: 28, height: 28)
                        .shadow(color: .black.opacity(0.2), radius: 3, y: 2)
                        .offset(x: 3 + (isOn ? 22 : 0))
                        .animation(.spring(response: 0.3, dampingFraction: 0.6), value: isOn)
                }
                .animation(.easeInOut(duration: 0.25), value: isOn)
        }
        .buttonStyle(.plain)
        .sensoryFeedback(.selection, trigger: isOn)
        .accessibilityRepresentation { Toggle(isOn: $isOn) { Text(label) } }
        .accessibilityIdentifier(identifier)
    }
}

// MARK: - Unit toggle + weight picker

/// Imperial / Metric segmented control.
struct UnitToggle: View {
    @Binding var system: UnitSystem

    var body: some View {
        HStack(spacing: 4) {
            segment(.metric, "Metric")
            segment(.imperial, "Imperial")
        }
        .padding(4)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(DS.Palette.surfaceMuted))
    }

    private func segment(_ value: UnitSystem, _ title: LocalizedStringResource) -> some View {
        let on = system == value
        return Button { withAnimation(.easeInOut(duration: 0.25)) { system = value } } label: {
            Text(title)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(on ? DS.Palette.foreground : DS.Palette.secondaryText)
                .frame(maxWidth: .infinity)
                .frame(height: 42)
                .background(RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(on ? DS.Palette.surface : Color.clear)
                    .shadow(color: on ? .black.opacity(0.1) : .clear, radius: 6, y: 4))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .sensoryFeedback(.selection, trigger: on)
        .accessibilityAddTraits(on ? .isSelected : [])
        .accessibilityIdentifier("unit_\(value.rawValue)")
    }
}

/// The state behind a weight picker. Stored value is kg; the imperial display keeps a whole-pound
/// state so switching units never drifts; the ruler snaps to 0.5 kg / 1 lb.
struct WeightPickerState: Equatable {
    var kg: Double
    var unit: UnitSystem
    var rangeKg: ClosedRange<Double>

    /// Ruler ticks in the current unit.
    var displayRange: ClosedRange<Double> {
        let lo = Units.snap(Units.weightValue(kg: rangeKg.lowerBound, in: unit), in: unit)
        let hi = Units.snap(Units.weightValue(kg: rangeKg.upperBound, in: unit), in: unit)
        return lo...hi
    }
    var step: Double { Units.weightStep(unit) }
    var tickCount: Int { Int(((displayRange.upperBound - displayRange.lowerBound) / step).rounded()) }

    var tickIndex: Int {
        get {
            let display = unit == .metric ? Units.snap(kg, in: .metric) : Double(Units.wholePounds(fromKg: kg))
            return min(tickCount, max(0, Int(((display - displayRange.lowerBound) / step).rounded())))
        }
        set {
            let display = displayRange.lowerBound + Double(min(tickCount, max(0, newValue))) * step
            kg = Units.kg(fromDisplayValue: display, in: unit)
        }
    }

    /// Switching units keeps the same body weight, snapped to the new ruler's tick.
    mutating func setUnit(_ new: UnitSystem) {
        guard new != unit else { return }
        let display = Units.snap(Units.weightValue(kg: kg, in: new), in: new)
        unit = new
        kg = Units.kg(fromDisplayValue: display, in: new)
    }

    var label: String { Units.formatWeight(kg: kg, in: unit) }
}

/// Weight ruler with the kg/lb toggle built in (every weight picker gets it).
struct WeightPicker: View {
    @Binding var state: WeightPickerState
    var identifier: String

    var body: some View {
        VStack(spacing: 18) {
            UnitToggle(system: Binding(get: { state.unit }, set: { state.setUnit($0) }))
            Text(verbatim: state.label)
                .font(.system(size: 44, weight: .heavy, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(DS.Palette.foreground)
                .contentTransition(.numericText())
                .accessibilityIdentifier("\(identifier)_value")
            RulerPicker(count: state.tickCount, index: $state.tickIndex, midEvery: state.unit == .metric ? 2 : 5,
                        label: { k in
                            Units.formatNumber(state.displayRange.lowerBound + Double(k) * state.step)
                        },
                        identifier: identifier, accessibilityValue: state.label)
                .id(state.unit)
        }
    }
}

// MARK: - Onboarding header + CTA

/// Back chevron + thin progress bar.
struct OnboardingHeader: View {
    let progress: Double
    let canGoBack: Bool
    let onBack: () -> Void

    var body: some View {
        HStack(spacing: 14) {
            Button(action: onBack) {
                Image(systemName: "chevron.left")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(DS.Palette.foreground)
                    .frame(width: 24, height: 24)
            }
            // A glass circle on iOS 26 (system control), a filled circle before.
            .glassCircleButton()
            .opacity(canGoBack ? 1 : 0)
            .disabled(!canGoBack)
            .accessibilityLabel(Text("Back"))
            .accessibilityIdentifier("onb_back")

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(DS.Palette.border)
                    Capsule().fill(DS.Palette.primary)
                        .frame(width: max(6, geo.size.width * progress))
                        .animation(.easeInOut(duration: 0.35), value: progress)
                }
            }
            .frame(height: 6)
            .accessibilityElement()
            .accessibilityLabel(Text("Progress"))
            .accessibilityValue(Text(verbatim: "\(Int(progress * 100))%"))
        }
        .padding(.horizontal, DS.Spacing.lg)
        .padding(.top, DS.Spacing.sm)
    }
}

/// Pinned primary CTA used by every onboarding step.
struct CTAButton: View {
    let title: LocalizedStringResource
    var enabled = true
    var identifier = "onb_cta"
    let action: () -> Void

    var body: some View {
        Button(action: action) { Text(title) }
            .buttonStyle(.primary)
            .disabled(!enabled)
            .opacity(enabled ? 1 : 0.45)
            .animation(.easeInOut(duration: 0.2), value: enabled)
            .accessibilityIdentifier(identifier)
            .padding(.horizontal, DS.Spacing.lg)
            .padding(.bottom, DS.Spacing.md)
    }
}
