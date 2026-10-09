# REFERENCE ENGINE FOR GAS (9 Oct 2026). The page's gas pricing (index.html, "9. Gas") is
# checked against this by reference/compare_gas.mjs. Written separately from the page's code.
# Usage (from the project folder):
#   python3 reference/rank_gas.py people=2 reference/allplans-gas-multinet private/gas.json
#   python3 reference/rank_gas.py bills=2026-06-01:2026-07-31:9800,2026-12-01:2027-01-31:2500 <plans folder> <out.json>
# A bill is from:to:MJ, both dates included, as bills print them.
#
# Conventions (checked 9 Oct 2026 on all 1,021 Victorian residential gas plans):
#   - Prices are dollars per MJ and daily charges in dollars, both excluding GST (x 1.1).
#   - Every plan is SINGLE_RATE: one price per MJ in each season, in blocks, no time of day.
#   - Blocks are per day (P1D) or per two months (P2M, AGL). A block over a longer period is
#     shared out per day: 3,000 MJ per two months is 3,000 / (365 / 6) MJ a day.
#   - Seasons are date ranges (MM-DD), some wrapping the year end; a day outside them all
#     takes the first season (as for electricity).
#   - Percentage discounts are assumed earned: % of bill on usage and daily charges, % of use
#     on usage. Recurring membership fees are added. Sign-up credits are read from the text.
import json, glob, os, re, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gas_months import months_table

USAGE, PLANS = sys.argv[1], sys.argv[2]
OUT = sys.argv[3] if len(sys.argv) > 3 else "gas.json"

# ---- 1. A year of daily use, 365 days from 1 January (no 29 February) -----------------------
MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
DAYS = [(m, d) for m in range(12) for d in range(1, MONTH_DAYS[m] + 1)]      # (month index, day)
MMDD = [f"{m + 1:02d}-{d:02d}" for m, d in DAYS]
TABLE = months_table()

def average_home(people):
    # MJ on each day: the month's gas spread evenly over its days.
    return [TABLE[people][m] / MONTH_DAYS[m] for m, _ in DAYS]

def bill_days(start, end):
    # Day-of-year index of every day of a bill, both ends included; 29 Feb counts as 28 Feb.
    out, d = [], start
    while d <= end:
        day = 28 if (d.month, d.day) == (2, 29) else d.day
        out.append(MMDD.index(f"{d.month:02d}-{day:02d}"))
        d += dt.timedelta(days=1)
    return out

def from_bills(bills):
    # Everyday use (the same every day) plus heating (the average home's use above its lowest
    # day). Two bills that differ enough in heating fix both parts; otherwise the average
    # home's year is scaled to fit. Same rule and thresholds as the page.
    shape = average_home(2)
    low, high = min(shape), max(shape)
    sums = []
    for start, end, mj in bills:
        idx = bill_days(start, end)
        sums.append((len(idx), sum(shape[i] for i in idx), sum(shape[i] - low for i in idx), mj))
    if len(sums) == 2:
        (da, ta, ha, ma), (db, tb, hb, mb) = sums
        if abs(ha / da - hb / db) >= 0.25 * (high - low):
            det = da * hb - db * ha
            base = (ma * hb - mb * ha) / det
            heat = (da * mb - db * ma) / det
            if base >= 0 and heat >= 0:
                return [base + heat * (x - low) for x in shape], True
    k = sum(s[3] for s in sums) / sum(s[1] for s in sums)
    return [k * x for x in shape], False

if USAGE.startswith("people="):
    use, split = average_home(int(USAGE[7:])), None
else:
    bills = []
    for b in USAGE[6:].split(","):
        s, e, mj = b.split(":")
        bills.append((dt.date.fromisoformat(s), dt.date.fromisoformat(e), float(mj)))
    use, split = from_bills(bills)

# ---- 2. Pricing --------------------------------------------------------------------------
def in_season(tp, mmdd):
    s, e = tp.get("startDate", "01-01"), tp.get("endDate", "12-31")
    return s <= mmdd <= e if s <= e else (mmdd >= s or mmdd <= e)

PERIOD_DAYS = {"D": 1, "M": 365 / 12, "Y": 365}
def per_day_blocks(sr):
    # [(lo, hi, price)] in MJ a day, or None for a period the page does not know.
    m = re.fullmatch(r"P(\d+)([DMY])", sr.get("period") or "P1D")
    if not m: return None
    days = int(m.group(1)) * PERIOD_DAYS[m.group(2)]
    out, lo = [], 0.0
    for b in sr["rates"]:
        hi = lo + float(b["volume"]) / days if b.get("volume") else float("inf")
        out.append((lo, hi, float(b["unitPrice"])))
        lo = hi
    return out

def block_cost(blocks, mj):
    return sum(max(0.0, min(mj, hi) - lo) * p for lo, hi, p in blocks)

PER_YEAR = {"DAILY": 365, "WEEKLY": 52, "MONTHLY": 12, "BIANNUAL": 2}
def yearly_fees(c):
    # As reference/rank_plans.py: membership fees count; GreenPower daily charges too.
    total = 0.0
    for x in c.get("fees", []):
        d = x.get("description") or ""
        amount = float(x.get("amount") or 0)
        if x.get("type") == "MEMBERSHIP" or re.search(r"annual\s+membership", d, re.I):
            total += amount * PER_YEAR.get(x.get("term"), 1)
        elif "GreenPower" in d and re.search(r"daily\s+charge", d, re.I):
            total += amount * 365
    return total

def price(c):
    tps = c.get("tariffPeriod") or []
    if not tps or any(tp.get("rateBlockUType") != "singleRate" or not tp.get("singleRate") for tp in tps):
        return None
    blocks = [per_day_blocks(tp["singleRate"]) for tp in tps]
    if any(b is None for b in blocks): return None
    usage = supply = 0.0
    for i, mmdd in enumerate(MMDD):
        si = next((k for k, tp in enumerate(tps) if in_season(tp, mmdd)), 0)
        supply += float(tps[si].get("dailySupplyCharge") or 0)
        usage += block_cost(blocks[si], use[i])
    usage *= 1.1; supply *= 1.1
    pct_bill = sum(float(x["percentOfBill"]["rate"]) for x in c.get("discounts", []) if x.get("methodUType") == "percentOfBill")
    pct_use = sum(float(x["percentOfUse"]["rate"]) for x in c.get("discounts", []) if x.get("methodUType") == "percentOfUse")
    return usage + supply - (pct_bill * (usage + supply) + pct_use * usage) + yearly_fees(c)

# Sign-up credits: the same reading as reference/rank_plans.py.
CREDIT_RES = [re.compile(r"\$\s?(\d{2,4})(?:\.\d\d)?\s*(?:\([^)]*\)\s*)?(?:[\w-]+\s){0,4}?(?:credit|bonus|reward|gift|e-?gift|card|cash)", re.I),
              re.compile(r"credit of \$\s?(\d{2,4})", re.I)]
NOT_A_CREDIT = re.compile(r"\brefer|guarantee", re.I)
def signup_credit(c):
    amount = 0
    for i in c.get("incentives", []):
        if NOT_A_CREDIT.search(f'{i.get("displayName") or ""} {i.get("description") or ""}'):
            continue
        t = " ".join("" if i.get(k) is None else str(i.get(k)) for k in ("displayName", "description", "eligibility"))
        for rx in CREDIT_RES:
            for v in rx.findall(t):
                amount = max(amount, int(v))
    for x in c.get("discounts", []):
        if x["methodUType"] != "fixedAmount" or re.search(r"\brefer", f'{x.get("displayName")} {x.get("description")}', re.I):
            continue
        amount = max(amount, float((x.get("fixedAmount") or {}).get("amount") or 0))
    return amount

# ---- 3. Every plan --------------------------------------------------------------------------
rows, skipped = [], 0
for f in sorted(glob.glob(f"{PLANS}/*.json")):
    j = json.load(open(f)); p = j["data"]; c = p.get("gasContract") or {}
    cost = price(c)
    if cost is None:
        skipped += 1; continue
    rows.append(dict(id=p["planId"], retailer=p.get("brandName", j.get("brandName")), name=p["displayName"],
                     cost=cost, credit=signup_credit(c)))
print(f"usage {sum(use):,.0f} MJ a year{'' if split is None else ', everyday and heating parts fitted' if split else ', average home scaled'}; "
      f"priced {len(rows)} plans, skipped {skipped}")
json.dump(rows, open(OUT, "w"), indent=1)
for i, r in enumerate(sorted(rows, key=lambda r: r["cost"])[:5], 1):
    print(f"{i}. ${r['cost']:7.0f}  {r['retailer']:<18.18} {r['name'][:50]}")
