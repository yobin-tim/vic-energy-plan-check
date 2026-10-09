# REFERENCE ENGINE (Python prototype, 7 Oct 2026). The web app ports this logic to JavaScript.
# Ranks every current United Energy residential plan (public CDR feed) against one meter file
# for a fixed 365-day window, with and without sign-up credits.
# Usage: python3 rank_plans.py <meter.csv> <plans folder> [output.json]
#
# Conventions (checked 7 Oct 2026):
#   - CDR usage and supply rates exclude GST -> multiply by 1.1. Feed-in rates are GST-free.
#   - CDR time windows are in local Melbourne time; the meter file is in AEST (no daylight
#     saving), so each interval is converted to local time before it is matched to a band.
#     Plans whose contract timeZone is "AEST" (ENGIE, Origin, Dodo, OVO: "billed in AEST")
#     are matched on standard time instead (8 Oct 2026).
#   - Tiered blocks with period P1D reset every day (e.g. "first 15 kWh/day at X, then Y").
#   - Percentage discounts (guaranteed and pay-on-time) are assumed to be earned and apply
#     to usage + supply, not to the solar credit.
#   - Recurring membership and GreenPower fees are added (see yearly_fees).
#   - Plans needing a controlled-load circuit or charging on peak demand are skipped:
#     this meter has neither a controlled-load channel nor a demand tariff.
import json, glob, re, sys, datetime as dt
from zoneinfo import ZoneInfo

METER = sys.argv[1]
PLANS = sys.argv[2]           # folder of plan-detail JSON files
START, END = dt.date(2025, 10, 6), dt.date(2026, 10, 6)
DOW = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# ---- 1. Load meter data and collapse 5-minute readings into 30-minute slots ----------
raw, ch = {}, None
for line in open(METER):
    r = line.strip().split(",")
    if r[0] == "200":
        ch, n = r[3], 1440 // int(r[8])
    elif r[0] == "300":
        raw[(ch, r[1])] = [float(x) for x in r[2:2 + n]]
step = n // 48
mel, aest = ZoneInfo("Australia/Melbourne"), dt.timezone(dt.timedelta(hours=10))
days = []      # one entry per day: (local weekday per slot, local minute-of-day per slot, imp[48], exp[48],
               #   local date per slot, standard-time weekday per slot, standard-time minute per slot)
d = START
while d < END:
    k = d.strftime("%Y%m%d")
    if ("E1", k) in raw:
        E, B = raw[("E1", k)], raw[("B1", k)]
        imp = [sum(E[i * step:(i + 1) * step]) for i in range(48)]
        exp = [sum(B[i * step:(i + 1) * step]) for i in range(48)]
        loc = [(dt.datetime.combine(d, dt.time(), aest) + dt.timedelta(minutes=30 * i)).astimezone(mel) for i in range(48)]
        days.append(([DOW[t.weekday()] for t in loc], [t.hour * 60 + t.minute for t in loc], imp, exp,
                     [t.strftime("%m-%d") for t in loc], [DOW[d.weekday()]] * 48, [30 * i for i in range(48)]))
    d += dt.timedelta(days=1)
SCALE = (END - START).days / len(days)     # annualise over the one missing day
NDAYS = (END - START).days

# ---- 2. Helpers to read plan structures -----------------------------------------------
def mins(hhmm):
    # "15:00", "9:00" or "1500" to minutes after midnight
    h, m = hhmm.split(":")[:2] if ":" in hhmm else (hhmm[:2], hhmm[2:4])
    return int(h) * 60 + int(m)

def in_window(w, dow, minute):
    # A window covers [start, end); "00:00" as an end means midnight; may wrap past midnight.
    if dow not in w.get("days", DOW):
        return False
    s, e = mins(w["startTime"]), mins(w["endTime"])
    if e == 0: e = 1440
    return s <= minute < e if s < e else (minute >= s or minute < e)

def in_season(tp, mmdd):
    s, e = tp.get("startDate", "01-01"), tp.get("endDate", "12-31")
    return s <= mmdd <= e if s <= e else (mmdd >= s or mmdd <= e)

def block_volume(v):
    # A few plans state a daily cap 365 times too big ("first 3,650 kWh a day" for a 10 kWh
    # cap). Such caps are yearly totals, so they are read as cap / 365 a day (8 Oct 2026).
    n = float(v)
    return n / 365 if n >= 5 * 365 and n % 365 == 0 else n

def tier_cost(blocks, kwh_so_far, kwh):
    # Daily volume blocks: block k covers cumulative kWh [lo_k, hi_k). Charge the slice of
    # [kwh_so_far, kwh_so_far + kwh) that falls inside each block at that block's price.
    cost, lo = 0.0, 0.0
    a, b = kwh_so_far, kwh_so_far + kwh
    for blk in blocks:
        hi = lo + block_volume(blk["volume"]) if blk.get("volume") else float("inf")
        cost += max(0.0, min(b, hi) - max(a, lo)) * float(blk["unitPrice"])
        lo = hi
    return cost

def price(c):
    """Annual cost (incl. GST) of plan contract c, or None if it cannot be priced."""
    tps = c["tariffPeriod"]
    if any(tp.get("rateBlockUType") not in ("singleRate", "timeOfUseRates") for tp in tps):
        return None
    usage = supply = fit = rebate = 0.0
    fits = c.get("solarFeedInTariff", [])
    std = (c.get("timeZone") or "AEST") == "AEST"   # standard time all year (the default if absent)
    for dows, mns, imp, exp, mmdd, sdows, smns in days:
        if std: dows, mns = sdows, smns
        tp = next((t for t in tps if in_season(t, mmdd[24])), tps[0])
        supply += float(tp.get("dailySupplyCharge", 0) or 0)
        used = {}                                   # kWh used today per band (for daily tiers)
        for i in range(48):
            if tp["rateBlockUType"] == "singleRate":
                band, blocks = "single", tp["singleRate"]["rates"]
            else:
                band = next((j for j, r in enumerate(tp["timeOfUseRates"])
                             if any(in_window(w, dows[i], mns[i]) for w in r["timeOfUse"])), None)
                if band is None: return None         # a gap in the plan's windows
                blocks = tp["timeOfUseRates"][band]["rates"]
            usage += tier_cost(blocks, used.get(band, 0.0), imp[i])
            used[band] = used.get(band, 0.0) + imp[i]
        # Solar credit for the day
        if fits:
            s = fits[0]
            if s["tariffUType"] == "singleTariff":
                fit += tier_cost(s["singleTariff"]["rates"], 0.0, sum(exp))
            else:
                fused = {}
                for i in range(48):
                    j = next((j for j, r in enumerate(s["timeVaryingTariffs"])
                              if any(in_window(w, dows[i], mns[i]) for w in r.get("timeVariations", []))), None)
                    if j is None: continue
                    fit += tier_cost(s["timeVaryingTariffs"][j]["rates"], fused.get(j, 0.0), exp[i])
                    fused[j] = fused.get(j, 0.0) + exp[i]
        # Daytime usage rebates described only in text (e.g. "Credit of 13.15c/kWh ... 11am and 4pm")
        for x in c.get("discounts", []):
            if x["methodUType"] == "percentOfUse":
                m = re.search(r"([\d.]+)c/kWh.*?(\d{1,2})\s*(am|pm)\s*(?:-|and|to)\s*(\d{1,2})\s*(am|pm)", x["description"])
                if m:
                    h1 = int(m.group(2)) % 12 + (12 if m.group(3) == "pm" else 0)
                    h2 = int(m.group(4)) % 12 + (12 if m.group(5) == "pm" else 0)
                    rebate += sum(imp[i] for i in range(48) if h1 * 60 <= mns[i] < h2 * 60) * float(m.group(1)) / 100
    usage, supply, fit, rebate = usage * 1.1 * SCALE, supply * 1.1 * SCALE, fit * SCALE, rebate * SCALE
    pct_bill = sum(float(x["percentOfBill"]["rate"]) for x in c.get("discounts", []) if x["methodUType"] == "percentOfBill")
    pct_use = sum(float(x["percentOfUse"]["rate"]) for x in c.get("discounts", [])
                  if x["methodUType"] == "percentOfUse" and not re.search(r"c/kWh", x["description"]))
    disc = pct_bill * (usage + supply) + pct_use * usage + rebate
    return usage + supply - disc - fit + yearly_fees(c)

# Recurring fees that everyone on the plan pays (added 7 Oct 2026). Fee amounts include GST
# (checked against the text of Amber's and ENGIE's fees). Paper-bill, payment, connection
# and exit fees are avoidable or one-off, so they are not counted. Tango's "type 3-4
# metering charge (if applicable)" is not counted: Victorian smart meters are type 5,
# run by the network (Victoria's metering order; checked 8 Oct 2026).
PER_YEAR = {"DAILY": 365, "WEEKLY": 52, "MONTHLY": 12, "BIANNUAL": 2}
def yearly_fees(c):
    total = 0.0
    for x in c.get("fees", []):
        d = x.get("description") or ""
        amount = float(x.get("amount") or 0)
        if x.get("type") == "MEMBERSHIP" or re.search(r"annual\s+membership", d, re.I):
            total += amount * PER_YEAR.get(x.get("term"), 1)   # FIXED and ANNUAL: once a year
        elif "GreenPower" in d and re.search(r"daily\s+charge", d, re.I):
            total += amount * 365                               # GreenPower plans: every day
    return total

# Sign-up credits, read from each incentive on its own (kept identical in index.html):
# referral rewards and guarantees are skipped; "$150 sign up credit", "$175 (inc GST) credit",
# "$100 Prepaid Visa Card" and "credit of $150" count; so do one-off fixed-amount discounts
# that are not referral offers. The largest counts, to avoid double counting.
CREDIT_RES = [re.compile(r"\$\s?(\d{2,4})(?:\.\d\d)?\s*(?:\([^)]*\)\s*)?(?:[\w-]+\s){0,4}?(?:credit|bonus|reward|gift|e-?gift|card|cash)", re.I),
              re.compile(r"credit of \$\s?(\d{2,4})", re.I)]
NOT_A_CREDIT = re.compile(r"\brefer|guarantee", re.I)
def signup_credit(c):
    amount, txt = 0, ""
    for i in c.get("incentives", []):
        if NOT_A_CREDIT.search(f'{i.get("displayName") or ""} {i.get("description") or ""}'):
            continue
        t = " ".join("" if i.get(k) is None else str(i.get(k)) for k in ("displayName", "description", "eligibility"))
        for rx in CREDIT_RES:
            for v in rx.findall(t):
                if int(v) > amount:
                    amount, txt = int(v), i.get("description") or i.get("displayName") or ""
    for x in c.get("discounts", []):
        if x["methodUType"] != "fixedAmount" or re.search(r"\brefer", f'{x.get("displayName")} {x.get("description")}', re.I):
            continue
        a = float((x.get("fixedAmount") or {}).get("amount") or 0)
        if a > amount:
            amount, txt = a, x.get("description") or x.get("displayName") or ""
    return amount, txt

# ---- 3. Price every plan --------------------------------------------------------------
rows, skipped = [], 0
for f in glob.glob(f"{PLANS}/*.json"):
    j = json.load(open(f)); p = j["data"]; c = p.get("electricityContract", {})
    if "CONT_LOAD" in c.get("pricingModel", ""):
        skipped += 1; continue
    cost = price(c)
    if cost is None:
        skipped += 1; continue
    credit, txt = signup_credit(c)
    rows.append(dict(retailer=p.get("brandName", j["brandName"]), name=p["displayName"], id=p["planId"],
                     type=p["type"], cost=cost, credit=credit, incentive=txt[:220],
                     elig=" | ".join(str(e.get("description", e.get("type", ""))) for e in p.get("eligibility", []) if e)[:160]))

# Example of a manually entered offer (one not in the public feed). Made-up rates, incl. GST:
# daily charge 100c, 32c from 3pm to 9pm, 20c other times, 1c solar credit, $150 credit.
def manual_offer():
    total = 0.0
    for dows, mns, imp, exp, *_ in days:
        total += 1.00 + sum(e * (0.32 if 900 <= m < 1260 else 0.20) for e, m in zip(imp, mns)) - 0.01 * sum(exp)
    return total * SCALE
rows.append(dict(retailer="Example", name="Manual offer (made-up example)", id="manual", type="MARKET",
                 cost=manual_offer(), credit=150, incentive="$150 sign-up credit", elig="example only"))

print(f"priced {len(rows)} plans, skipped {skipped} (controlled load, demand charges or unreadable)")
json.dump(rows, open(sys.argv[3] if len(sys.argv) > 3 else "ranked.json", "w"), indent=1)
for label, key in (("ONGOING (no credits)", lambda r: r["cost"]), ("FIRST YEAR (cost minus sign-up credit)", lambda r: r["cost"] - r["credit"])):
    print(f"\n=== {label} ===")
    for i, r in enumerate(sorted(rows, key=key)[:15], 1):
        print(f"{i:2d}. ${r['cost']:7.0f}  credit ${r['credit']:3.0f}  -> ${r['cost']-r['credit']:6.0f}  {r['retailer']:<16.16} {r['name'][:45]:<45} {r['type'][:3]} {r['id']}")
    ss = next(i for i, r in enumerate(sorted(rows, key=key), 1) if r["id"] == "manual")
    print(f"   Manual offer rank: {ss} of {len(rows)}")
