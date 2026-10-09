# REFERENCE (8 Oct 2026). Run from this folder. Builds the page's postcode table: which
# Victorian electricity networks serve each postcode, as the plans themselves say.
# Every plan lists its network (geography.distributors) and that network's postcodes
# (geography.includedPostcodes); all plans on one network carry the same list. Reads each
# retailer's public plan list (no login) and prints a compact table for index.html.
#   python3 postcode_networks.py         electricity: NETWORK_POSTCODES
#   python3 postcode_networks.py gas     gas: GAS_POSTCODES (9 Oct 2026). Gas plans on one
#                                        network list only their price zone's postcodes, so
#                                        the network's postcodes are the union of its plans'.
import json, subprocess, sys, collections, concurrent.futures as cf

GAS = sys.argv[1:] == ["gas"]
# The Victorian networks, as the feed names them, and the names the page shows. "AGN Murray
# Valley (NSW)" is left out: it reaches one Victorian postcode (3644) from New South Wales.
NETWORKS = ({"Australian Gas Networks": "Australian Gas Networks", "AusNet Services (gas)": "AusNet Services",
             "Multinet": "Multinet"} if GAS else
            {"United Energy": "United Energy", "Citipower": "CitiPower", "Powercor": "Powercor",
             "Jemena": "Jemena", "AusNet Services (electricity)": "AusNet Services"})
brands = json.load(open("retailer_sources.json"))["data"]

def get(url):
    out = subprocess.run(["curl", "-s", "-m", "60", "-H", "x-v: 1", url], capture_output=True, text=True).stdout
    try: return json.loads(out)
    except Exception: return None

def postcodes_for(b):
    # For one retailer: the postcodes each Victorian network's residential plans list.
    base = b["publicBaseUri"].rstrip("/") + "/cds-au/v1/energy/plans"
    found, page = collections.defaultdict(set), 1
    while True:
        d = get(f"{base}?fuelType={'GAS' if GAS else 'ELECTRICITY'}&effective=CURRENT&page-size=1000&page={page}")
        if not d or "data" not in d: return found
        for p in d["data"]["plans"]:
            if p.get("customerType", "RESIDENTIAL") != "RESIDENTIAL": continue
            g = p.get("geography") or {}
            for dist in g.get("distributors", []):
                if dist in NETWORKS: found[dist].update(g.get("includedPostcodes", []))
        if page >= d["meta"].get("totalPages", 1): return found
        page += 1

with cf.ThreadPoolExecutor(12) as ex: results = list(ex.map(postcodes_for, brands))
by_net = collections.defaultdict(set)
for found in results:
    for dist, pcs in found.items(): by_net[dist] |= pcs
# Homes have postcodes starting with 3. Victoria's 8xxx postcodes are post-office boxes (ENGIE's
# gas plans list 8002, 8008 and 8012, 9 Oct 2026); they are dropped, and anything else stops it.
boxes = sorted({pc for dist in NETWORKS for pc in by_net[dist] if pc.startswith("8")})
for dist in NETWORKS: by_net[dist] -= set(boxes)
if boxes: print(f"Dropped {len(boxes)} post-office-box postcodes: {' '.join(boxes)}")
for dist in NETWORKS: print(f"{NETWORKS[dist]:16s} {len(by_net[dist])} postcodes")

# Postcode -> networks, written as one string per network of the last three digits of each
# postcode (all start with 3), to keep the page small.
pc_nets = collections.defaultdict(list)
for dist in NETWORKS:
    for pc in by_net[dist]: pc_nets[pc].append(NETWORKS[dist])
shared = sorted(pc for pc, n in pc_nets.items() if len(n) > 1)
print(f"{len(pc_nets)} postcodes in all; {len(shared)} on two or more networks; "
      f"{sum(len(n) > 2 for n in pc_nets.values())} on three or more")
assert all(pc.startswith("3") and len(pc) == 4 for pc in pc_nets), "a postcode outside Victoria"
print(f"const {'GAS_POSTCODES' if GAS else 'NETWORK_POSTCODES'} = {{")
for dist in NETWORKS:
    print(f'  "{NETWORKS[dist]}": "{" ".join(sorted(pc[1:] for pc in by_net[dist]))}",')
print("};")
