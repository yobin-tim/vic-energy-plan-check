# REFERENCE (8 Oct 2026). Builds the page's SAMPLE_SHAPES table: when in the day and year an
# average home on each Victorian network uses power from the grid.
# Source: AEMO's Victorian disaggregated 5-minute load data (one row per day, network and
# customer class), published by the Essential Services Commission with its 2026-27 Victorian
# Default Offer review. Download the workbook from the ESC's review page, then run:
#   python3 sample_shapes.py <workbook.xlsx> > shapes.js
# Needs openpyxl. Prints yearly totals to stderr as a check.
#
# For each network: residential grid use (LOAD rows, kWh) in 2024 and 2025, averaged into one
# day of 48 half hours (on standard time, as in usage files) for each month and for weekdays
# and weekends: 24 rows. Each row is stored in parts of 10,000, with its level (that row's
# daily use relative to the network's average day, 1000 = average).
import sys, collections, datetime as dt, openpyxl

# AEMO's network codes, and the names the page uses.
NETWORKS = [("United Energy", "UNITED"), ("CitiPower", "CITIPP"), ("Powercor", "POWCP"),
            ("Jemena", "SOLARISP"), ("AusNet Services", "EASTERN")]

# 1. Read every year sheet; keep each network's residential grid use per day.
wb = openpyxl.load_workbook(sys.argv[1], read_only=True, data_only=True)
days = collections.defaultdict(dict)          # network code -> {date: 288 five-minute kWh}
for ws in wb.worksheets:
    rows = ws.iter_rows(values_only=True)
    next(rows)                                # header
    for r in rows:
        if r[0] is None: continue
        if r[1] == "LOAD" and r[3] == "RESIDENTIAL":
            days[str(r[2])][r[0].date() if hasattr(r[0], "date") else r[0]] = [v or 0 for v in r[4:]]

# 2. Average day per (month, weekend?) per network, then the compact table.
out = ["const SAMPLE_SHAPES = {"]
for name, code in NETWORKS:
    groups = collections.defaultdict(list)
    for d, v in days[code].items():
        if d.year not in (2024, 2025): continue
        groups[(d.month, 1 if d.weekday() >= 5 else 0)].append([sum(v[i * 6:(i + 1) * 6]) for i in range(48)])
    avg = {g: [sum(x[i] for x in rows) / len(rows) for i in range(48)] for g, rows in groups.items()}
    overall = sum(sum(v) * len(groups[g]) for g, v in avg.items()) / sum(len(r) for r in groups.values())
    shape, level = [], []
    for m in range(1, 13):
        for t in (0, 1):
            v = avg[(m, t)]; tot = sum(v)
            ints = [round(x / tot * 10000) for x in v]
            ints[ints.index(max(ints))] += 10000 - sum(ints)      # each row sums to exactly 10000
            shape.append(ints); level.append(round(tot / overall * 1000))
    print(f"{name}: {sum(len(r) for r in groups.values())} days, "
          f"{sum(sum(v) for d, v in days[code].items() if d.year == 2025) / 1e9:.2f} TWh in 2025", file=sys.stderr)
    out.append(f'  "{name}": {{ level: [{",".join(map(str, level))}],')
    out.append("    shape: [")
    for i, r in enumerate(shape):
        out.append(f'      [{",".join(map(str, r))}]' + ("] }," if i == 23 else ","))
out.append("};")
print("\n".join(out))
