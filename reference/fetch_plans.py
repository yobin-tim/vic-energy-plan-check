# REFERENCE (Python prototype, 7 Oct 2026). Run from this folder; writes to ./allplans/.
# Fetch every brand's current residential electricity plans on the United Energy network
# from each retailer's public CDR endpoint (no login), then each plan's full detail.
import json, subprocess, os, concurrent.futures as cf
brands = json.load(open("retailer_sources.json"))["data"]
def get(url, xv="1"):
    out = subprocess.run(["curl", "-s", "-m", "60", "-H", f"x-v: {xv}", "-H", "x-min-v: 1", url],
                         capture_output=True, text=True).stdout
    try: return json.loads(out)
    except Exception: return None
def plans_for(b):
    base = b["publicBaseUri"].rstrip("/") + "/cds-au/v1/energy/plans"
    ids, page = [], 1
    while True:
        d = get(f"{base}?fuelType=ELECTRICITY&effective=CURRENT&page-size=1000&page={page}")
        if not d or "data" not in d: return b["brandName"], base, None
        for p in d["data"]["plans"]:
            if "United Energy" in (p.get("geography") or {}).get("distributors", []) \
               and p.get("customerType", "RESIDENTIAL") == "RESIDENTIAL":
                ids.append(p["planId"])
        if page >= d["meta"].get("totalPages", 1): break
        page += 1
    return b["brandName"], base, ids
with cf.ThreadPoolExecutor(12) as ex: res = list(ex.map(plans_for, brands))
jobs = []
for name, base, ids in res:
    print(f"{name:35s} {'FAILED' if ids is None else len(ids)}")
    for pid in ids or []: jobs.append((name, base, pid))
def detail(j):
    name, base, pid = j
    path = f"allplans/{pid.replace('/','_')}.json"
    if os.path.exists(path): return
    d = get(f"{base}/{pid}", xv="3")
    if d: json.dump({"brandName": name, **d}, open(path, "w"))
with cf.ThreadPoolExecutor(16) as ex: list(ex.map(detail, jobs))
print("plans:", len(jobs), "saved:", len(os.listdir("allplans")))
