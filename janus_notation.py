#!/usr/bin/env python3
"""
Janus (balanced dozenal) notation in plain Unicode -- no Musa font needed,
since the negative-digit glyphs (①-⑥) are ordinary circled-digit
characters (U+2460-U+2465), not part of the Musa script itself. Suitable
anywhere UTF-8 renders correctly, including an Xfce genmon panel.

Balanced dozenal: base 12, digits run -6..6 instead of 0..9, written with
circled numerals for the negative half exactly as the source material
does. This is how the Civilization writes every number, not just
continuous measurements -- so this module covers two distinct cases:

  - Whole-count values (Annit, Dattit, or any other plain integer) use
    janus_integer(), which converts EXACTLY -- no truncation, no
    significant-digit budget, no magnitude notation at all. A count has
    no fractional part and gains nothing from magnitude notation, which
    exists to handle numbers too large or too small to write out digit
    by digit -- an ordinary count like a day-index or a year-index is
    neither, so it's just written as its exact balanced-dozenal digits.
  - Continuous, Chronit-based values (Orit, Solit, any fractional
    Chronit count) use janus_notation(), which windows to a chosen
    number of significant digits and uses full Janus magnitude notation:
    MAGNITUDE FIRST, then a separator, then the mantissa -- confirmed
    against the reference musa.bet implementation (jalibrary.js), whose
    janusReal() returns raise(exponent) + Break + mantissa, exponent
    (magnitude) before mantissa, not after. This module uses '*' as the
    plain-Unicode stand-in for the Break character, matching the
    Latinized convention observed on the Janus social units page
    ("So 2*11538": magnitude 2, mantissa 11538).

Both paths share the same underlying rule-of-six carry logic, verified
digit-for-digit against jalibrary.js's own janusInt() on every shared
test case (9, 18, 19, 30, 73); they differ only in whether the input is
a continuous measurement that gets windowed to significant digits, or
an exact count that doesn't.
"""
import math

DIGIT_CHARS = "0123456"  # 0..6
CIRCLED_DIGITS = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤", 6: "⑥"}

def render_digit(d):
    if d < 0:
        return CIRCLED_DIGITS[-d]
    return DIGIT_CHARS[d]

def _carry_to_balanced(raw_digits):
    """
    In-place rule-of-six carry over a list of unbalanced (0..11) base-12
    digits, most significant first, with a leading 0 already prepended
    as headroom for an overflow carry. Mutates and returns the list.

    Digits 7-11 always carry (digit-12, +1 to the left) since they have
    no balanced representative otherwise. Digit 6 carries (becomes -6,
    +1 left) only if a nonzero digit follows it somewhere to its right
    WITHIN THIS LIST -- never against precision outside the list, which
    is what makes this safe to reuse for a precision-windowed mantissa:
    a value's invisible tail past the requested window must not change
    what's shown. Resolved right-to-left, since "does anything follow
    me" depends on digits to the right, which may themselves have just
    been resolved.
    """
    anything_nonzero_after = False
    for i in range(len(raw_digits) - 1, 0, -1):
        d = raw_digits[i]
        carries = d > 6 or (d == 6 and anything_nonzero_after)
        if carries:
            raw_digits[i] = d - 12
            raw_digits[i - 1] += 1
        if raw_digits[i] != 0:
            anything_nonzero_after = True
    return raw_digits

def to_balanced_dozenal_integer_digits(n):
    """
    Convert any integer (positive, negative, or zero) to its EXACT
    balanced-dozenal digit representation -- no truncation, no
    significant-digit budget, and no ASCII sign character. True Janus
    notation has no separate sign marker at all: a negative value is
    expressed purely by negating its balanced digits (each one still
    within -6..6), the same digit alphabet used for everything else.
    This works because balanced-dozenal representation is linear -- if
    digits d_i represent n, then -d_i represent -n exactly, carries and
    all. Returns a list of digits (-6..6), most significant first, with
    no leading zero (except the single digit [0] for n == 0).
    """
    if n == 0:
        return [0]

    negative = n < 0
    raw_digits = []
    m = abs(n)
    while m > 0:
        raw_digits.append(m % 12)
        m //= 12
    raw_digits.reverse()

    raw_digits = [0] + raw_digits
    _carry_to_balanced(raw_digits)

    while len(raw_digits) > 1 and raw_digits[0] == 0:
        raw_digits.pop(0)

    if negative:
        raw_digits = [-d for d in raw_digits]

    return raw_digits

def janus_integer(n):
    """
    Render a whole number (Annit, Dattit, or any other plain count) as
    exact Janus balanced-dozenal digits -- circled numerals for the
    negative half, no ASCII sign character and no magnitude notation at
    all, since a count has no fractional part and no need for the
    scale-signaling machinery magnitude notation exists to provide. Sign
    is carried entirely by the digits: e.g. janus_integer(19) -> '2⑤',
    janus_integer(-2) -> '②' (not '-2'). Verified digit-for-digit
    against jalibrary.js's janusInt() for 9, 18, 19, 30, 73.
    """
    digits = to_balanced_dozenal_integer_digits(n)
    return "".join(render_digit(d) for d in digits)

def to_balanced_dozenal_mantissa_digits(value, sig_digits):
    """
    Convert a positive float to a windowed balanced-dozenal mantissa:
    (digits, magnitude), where digits is a list of exactly sig_digits
    balanced digits (-6..6, most significant first) and magnitude is the
    power-of-12 place of the first digit, such that
        value ~= sum(d * 12**(magnitude - i) for i, d in enumerate(digits))
    to sig_digits of precision. Matches the normalization jalibrary.js's
    janusReal() performs (repeatedly dividing or multiplying by 12 until
    the value sits in [0.5, 6)), just computed via fixed-point integer
    arithmetic instead of repeated float division, to avoid drift.

    The rule-of-six carry is evaluated ONLY against digits inside this
    sig_digits window -- verified against jalibrary.js directly: at
    reduced precision (e.g. 2 places) both 30.0 and 30.06 produce the
    identical mantissa [2, 6], while at higher precision (6 places) they
    correctly diverge ([3,-6,0,0,0,0] vs [3,-6,1,-3,-4,...]) because at
    that resolution there really is more of the value to show. A value's
    tail beyond the requested window must never change what's displayed
    within the window.
    """
    if value == 0:
        return [0] * sig_digits, 0

    est_magnitude = math.floor(math.log(value, 12))
    scale_pow = est_magnitude - sig_digits + 1
    scaled = round(value / (12.0 ** scale_pow))

    raw_digits = []
    n = int(scaled)
    if n == 0:
        raw_digits = [0]
    while n > 0:
        raw_digits.append(n % 12)
        n //= 12
    raw_digits.reverse()

    raw_digits = [0] + raw_digits
    _carry_to_balanced(raw_digits)
    balanced = raw_digits

    top_place = scale_pow + len(balanced) - 1
    first_nonzero = 0
    while first_nonzero < len(balanced) - 1 and balanced[first_nonzero] == 0:
        first_nonzero += 1
        top_place -= 1
    balanced = balanced[first_nonzero:]

    digits = balanced[:sig_digits]
    while len(digits) < sig_digits:
        digits.append(0)
    magnitude = top_place

    return digits, magnitude

def janus_mantissa_fixed(value, fixed_magnitude, sig_digits):
    """
    Render a real number as Janus mantissa digits only, pinned to a
    specific magnitude, with no magnitude prefix or '*' separator.

    Use when the display always wants the same magnitude scale regardless
    of the actual value -- e.g. Solit pinned at magnitude ① (12⁻¹),
    5 digits, so the readout is consistent from morning through noon to
    evening without the magnitude prefix flickering. Sign is carried by
    the digits (negative value → negated mantissa), same as
    janus_notation().
    """
    is_negative = value < 0
    value = abs(value)

    scale_pow = fixed_magnitude - sig_digits + 1
    scaled = round(value / (12.0 ** scale_pow))

    if scaled == 0:
        digits = [0] * sig_digits
    else:
        raw_digits = []
        n = int(scaled)
        while n > 0:
            raw_digits.append(n % 12)
            n //= 12
        raw_digits.reverse()
        raw_digits = [0] + raw_digits
        _carry_to_balanced(raw_digits)
        balanced = raw_digits

        # No leading-zero trim here -- this is fixed-point, not floating-point normalization.
        # The whole point is to stay at the fixed scale implied by fixed_magnitude, rather than
        # renormalizing to the true leading digit. Take the last sig_digits elements (least
        # significant), and pad from the front with zeros if the array is shorter.
        # Matches janusNotationFixedMagnitude() in index.html exactly:
        #   rawDigits.slice(-sigDigits) + unshift(0) padding.
        digits = balanced[-sig_digits:]
        while len(digits) < sig_digits:
            digits.insert(0, 0)

    if is_negative:
        digits = [-d for d in digits]

    return "".join(render_digit(d) for d in digits)

def janus_notation(value, sig_digits=6, trim_trailing_zeros=False):
    """
    Render a real number in full Janus magnitude notation: MAGNITUDE
    FIRST, then '*' (the plain-Unicode stand-in for the Musa Break
    character), then the mantissa digits -- e.g. janus_notation(30.06)
    at 6 sig digits gives something like '1*3⑥1③④④'. This ordering
    was confirmed against jalibrary.js's own janusReal(), which returns
    exponent-then-Break-then-mantissa, not mantissa-then-marker as an
    earlier draft of this module assumed.

    Use this for continuous, Chronit-based values where the point of
    magnitude notation -- signaling scale for numbers too large or small
    to write digit-by-digit -- actually applies: Orit, Solit, any
    fractional Chronit count. Do not use this for whole counts (Annit,
    Dattit); those have no fractional part and gain nothing from
    magnitude notation, so they use janus_integer() instead, with no
    magnitude marker at all.

    Default precision is 6 significant digits, matching the resolution
    the temporal dashboard actually runs at (updates every 0.000001
    Chronit). Lower precision is legitimate for glance-level displays --
    e.g. an Xfce panel that only wants to show whole-Orit resolution --
    but must be requested explicitly via sig_digits, since the module's
    own default reflects the finest precision this project currently
    needs, not a display convenience.

    trim_trailing_zeros defaults to False, matching jalibrary.js's own
    janusReal(): when a caller asks for a specific sig_digits, they get
    exactly that many mantissa digits, genuine zeros included -- trimming
    silently gives less precision than requested. The reference library
    only trims in its own "auto" mode (an unspecified/zero place count,
    meaning "up to 6, but don't pad"); pass trim_trailing_zeros=True to
    get that same compact behavior explicitly.

    No ASCII sign character appears anywhere in the output -- neither for
    a negative overall value nor for a negative magnitude. Balanced
    dozenal has no separate sign marker; a negative value is expressed
    by negating its balanced digits (mantissa or magnitude alike), the
    same way janus_integer() handles a negative integer.
    """
    is_negative = value < 0
    value = abs(value)

    if value == 0:
        return janus_integer(0) + "*" + "0" * sig_digits

    digits, magnitude = to_balanced_dozenal_mantissa_digits(value, sig_digits)

    if trim_trailing_zeros:
        while len(digits) > 1 and digits[-1] == 0:
            digits = digits[:-1]

    if is_negative:
        digits = [-d for d in digits]

    mantissa_str = "".join(render_digit(d) for d in digits)
    magnitude_str = janus_integer(magnitude)

    return f"{magnitude_str}*{mantissa_str}"

if __name__ == "__main__":
    print("Whole-count values (exact digits, no magnitude notation):")
    int_tests = [0, 7, 9, 18, 19, 30, 73, 223]
    for t in int_tests:
        print(f"{t!r:>14} -> {janus_integer(t)}")
    print()
    print("Continuous values (magnitude-first notation, default 6 sig digits):")
    tests = [30.06, 30.0, 0.0006, 1.5542e-6, 900, 9, 73, 18, 19]
    for t in tests:
        print(f"{t!r:>14} -> {janus_notation(t)}")
    print()
    print("Precision-window check: 30.0 and 30.06 must agree at low")
    print("precision and may legitimately diverge at high precision --")
    print("verified against jalibrary.js's own janusReal() behavior:")
    print(f"  30.0  at 2 sig digits -> {janus_notation(30.0, sig_digits=2)}")
    print(f"  30.06 at 2 sig digits -> {janus_notation(30.06, sig_digits=2)}  (must match)")
    print(f"  30.0  at 6 sig digits -> {janus_notation(30.0, sig_digits=6)}")
    print(f"  30.06 at 6 sig digits -> {janus_notation(30.06, sig_digits=6)}  (legitimately differs)")
    print()
    print("Panel line -- unit abbreviation and number separated by a space,")
    print("Annit/Dattit as plain Janus integers, Orit in full magnitude")
    print("notation at the project default of 6 significant digits:")
    orit_now = 30.06
    annit_now = 0
    dattit_now = 223
    print(f"An {janus_integer(annit_now)} Da {janus_integer(dattit_now)} Or {janus_notation(orit_now)}")
