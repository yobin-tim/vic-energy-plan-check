# Builds the weekly price copy that the page loads first: every current residential
# electricity plan on each Victorian network, and every gas plan on each Victorian gas network
# (since 9 Oct 2026), with its full detail, from the government's public plan list (no login).
# Run by the scheduled GitHub job in .github/workflows/, or by hand from the project folder:
#   python3 reference/snapshot.py <output folder>
# Writes <output folder>/<network>.json for electricity and gas-<network>.json for gas, in the
# same form the page keeps in its own cache:
#   {"savedAt": <ms since 1970>, "network": ..., "fuel": "ELECTRICITY" or "GAS", "plans": [...]}.
# Exits with an error, writing nothing, if any list or plan fails to download: the job then
# fails and the site keeps last week's copy, which the page stops using once it is 8 days old.
# Standard library only.
import json, os, re, sys, time, urllib.request, urllib.error, urllib.parse, concurrent.futures as cf

MIRROR = "https://cdr.energymadeeasy.gov.au/"
HERE = os.path.dirname(os.path.abspath(__file__))
# For each fuel: the page's names for the networks and the feed's (as NETWORKS and
# GAS_NETWORKS in index.html), the plan detail that holds the prices, and the file name prefix.
FUELS = {
    "ELECTRICITY": ({"United Energy": "United Energy", "CitiPower": "Citipower", "Powercor": "Powercor",
                     "Jemena": "Jemena", "AusNet Services": "AusNet Services (electricity)"}, "electricityContract", ""),
    "GAS": ({"Multinet": "Multinet", "Australian Gas Networks": "Australian Gas Networks",
             "AusNet Services": "AusNet Services (gas)"}, "gasContract", "gas-"),
}
# The retailer list is the page's own, so the copy and a live download cover the same retailers.
page = open(os.path.join(HERE, "..", "index.html"), encoding="utf-8").read()
RETAILERS = re.findall(r'"([a-z0-9-]+)"', re.search(r"const RETAILERS = \[(.*?)\];", page, re.S).group(1))
for networks, _, _ in FUELS.values():
    for name, feed in networks.items():
        assert f'feed: "{feed}"' in page, f"index.html no longer names {name} as {feed}"

def slug(name):
    # File name for a network, as the page builds it: "AusNet Services" -> "ausnet-services".
    return re.sub(r"[^a-z]+", "-", name.lower()).strip("-")

def get(url, version):
    # One JSON reply, with three tries (the page does the same); None if it never arrives.
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"x-v": version, "x-min-v": "1",
                                                       "User-Agent": "vic-energy-plan-check weekly copy"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
        except Exception:
            pass
        time.sleep(0.8 * (attempt + 1))
    return None

def plan_list(fuel, retailer):
    # This retailer's current residential plans of one fuel on any Victorian network:
    # {planId: network}.
    found, page_no = {}, 1
    feeds = {feed.lower(): name for name, feed in FUELS[fuel][0].items()}
    while True:
        d = get(f"{MIRROR}{retailer}/cds-au/v1/energy/plans?fuelType={fuel}&effective=CURRENT"
                f"&page-size=1000&page={page_no}", "1")
        if not d or not isinstance((d.get("data") or {}).get("plans"), list):
            return retailer, None                       # a failed list
        for p in d["data"]["plans"]:
            if (p.get("customerType") or "RESIDENTIAL") != "RESIDENTIAL": continue
            for dist in (p.get("geography") or {}).get("distributors", []):
                if str(dist).lower() in feeds: found[p["planId"]] = feeds[str(dist).lower()]
        if page_no >= ((d.get("meta") or {}).get("totalPages") or 1): return retailer, found
        page_no += 1

def fuel_copy(fuel):
    # Every plan of one fuel, by network: {network: [plan detail, ...]}. Exits with an error
    # if any list or detail fails.
    networks, contract, _ = FUELS[fuel]
    # 1. Every retailer's list, once (a list covers all networks).
    # A plan listed by two retailers' lists (one brand under two names) is fetched once.
    plans, failed = {}, []
    with cf.ThreadPoolExecutor(8) as ex:
        for retailer, found in ex.map(lambda r: plan_list(fuel, r), RETAILERS):
            if found is None: failed.append(retailer); continue
            for pid, net in found.items(): plans.setdefault(pid, (retailer, pid, net))
    if failed: sys.exit(f"{fuel}: lists failed for: {', '.join(failed)}. Nothing written.")
    jobs = list(plans.values())
    # 2. Each plan's detail (the prices are only there).
    def detail(job):
        retailer, pid, net = job
        d = get(f"{MIRROR}{retailer}/cds-au/v1/energy/plans/{urllib.parse.quote(pid, safe='')}", "3")
        return net, pid, (d or {}).get("data")
    by_net, missing = {name: [] for name in networks}, []
    with cf.ThreadPoolExecutor(8) as ex:
        for net, pid, data in ex.map(detail, jobs):
            if data and data.get(contract): by_net[net].append(data)
            else: missing.append(pid)
    if missing: sys.exit(f"{fuel}: {len(missing)} plan details failed (first: {missing[0]}). Nothing written.")
    return by_net, len(jobs)

def main(out):
    t0 = time.time()
    # Both fuels are downloaded before anything is written, so a failure leaves no half copy.
    copies = {fuel: fuel_copy(fuel) for fuel in FUELS}
    # One file per fuel and network, plans in a fixed order so a week with no changes gives
    # the same file.
    os.makedirs(out, exist_ok=True)
    saved_at = int(time.time() * 1000)
    for fuel, (by_net, n) in copies.items():
        for name, plans in by_net.items():
            plans.sort(key=lambda p: p["planId"])
            with open(os.path.join(out, FUELS[fuel][2] + slug(name) + ".json"), "w", encoding="utf-8") as f:
                json.dump({"savedAt": saved_at, "network": name, "fuel": fuel, "plans": plans}, f, separators=(",", ":"))
            print(f"{fuel:11s} {name:23s} {len(plans):4d} plans")
        print(f"{fuel:11s} {len(RETAILERS)} retailers, {n} plans")
    print(f"{time.time() - t0:.0f} s")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "prices")
