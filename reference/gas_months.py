# REFERENCE (9 Oct 2026). Builds the page's GAS_MONTHS table: how much gas an average
# Victorian home with gas uses in each month, by people in the home.
# Source: Frontier Economics for the Australian Energy Regulator, "Residential energy
# consumption benchmarks" (9 Dec 2020), Table 33, Victoria, MJ per season. Seasons as in the
# report: summer (Dec-Feb), autumn (Mar-May), winter (Jun-Aug), spring (Sep-Nov).
# Run: python3 gas_months.py > gas_months.js   (reference/rank_gas.py imports it too)
#
# The report gives four seasons only. A season's gas is not spread evenly over its months
# (May is far colder than March), so each household's four figures are joined by one smooth
# yearly curve: a constant plus a yearly and a half-yearly wave (four numbers, fitted so that
# the curve's total over each season equals the report's figure exactly). Each month then gets
# the curve's total over its days. The seasons are whole months, so the months of each season
# still add up to the report's figure (to within rounding).
import math

TABLE_33 = {1: [2484, 6178, 14375, 7377], 2: [3911, 10230, 23855, 12466], 3: [4192, 10230, 23855, 12466],
            4: [4694, 11567, 26426, 14111], 5: [6028, 14339, 33375, 17444]}
MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
MONTH = [m for m in range(12) for _ in range(MONTH_DAYS[m])]            # month of each day of the year
SEASON = [(m + 1) % 12 // 3 for m in MONTH]                           # 0 summer, 1 autumn, 2 winter, 3 spring

W = 2 * math.pi / 365
def basis(t):
    # The curve's four parts on day t (0 = 1 Jan), taken at the middle of the day.
    x = W * (t + 0.5)
    return [1.0, math.cos(x), math.sin(x), math.cos(2 * x)]

def solve(a, b):
    # Gaussian elimination with partial pivoting, for the 4 x 4 system a x = b.
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]

# Each season's total of each part, over its days.
A = [[0.0] * 4 for _ in range(4)]
for t in range(365):
    for j, v in enumerate(basis(t)):
        A[SEASON[t]][j] += v

def months_table():
    # {people: [MJ in January, February, ... December]} for an average home with gas.
    rows = {}
    for people, seasons in TABLE_33.items():
        coef = solve(A, seasons)
        curve = [sum(c * v for c, v in zip(coef, basis(t))) for t in range(365)]
        assert min(curve) > 0, "the curve dips below zero"
        months = [round(sum(curve[t] for t in range(365) if MONTH[t] == m)) for m in range(12)]
        # Check: each season's months add up to the report's figure (rounding only).
        for s in range(4):
            got = sum(months[m] for m in range(12) if (m + 1) % 12 // 3 == s)
            assert abs(got - seasons[s]) <= 2, (people, s, got, seasons[s])
        rows[people] = months
    return rows

if __name__ == "__main__":
    print("const GAS_MONTHS = {")
    for people, months in months_table().items():
        print(f"  {people}: [{', '.join(map(str, months))}],")
    print("};")
