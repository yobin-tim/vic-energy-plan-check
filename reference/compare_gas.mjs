// Checks the page's gas pricing (index.html, "9. Gas") against reference/rank_gas.py. Both
// price the same downloaded gas plans for the same usage, so every plan's cost should agree.
// Usage (from the project folder), with the same usage as the Python run:
//   node reference/compare_gas.mjs people=2 reference/allplans-gas-multinet private/gas.json
//   node reference/compare_gas.mjs bills=2026-06-01:2026-07-31:9800,... <plans folder> <python output.json>
// Prints only differences and counts; it writes nothing. Exit code 1 if any cost is off by $1+.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const [usage, plansDir, pythonPath] = process.argv.slice(2);
if (!pythonPath) {
  console.error("Usage: node reference/compare_gas.mjs <people=N | bills=from:to:MJ,...> <plans folder> <python output.json>");
  process.exit(2);
}

// Run the page's <script id="engine"> block on its own, exactly as the browser would.
const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const src = html.match(/<script id="engine">([\s\S]*?)<\/script>/)[1];
vm.runInThisContext(`${src}\nglobalThis.engine = { gasSample, gasFromBills, priceAllGas };`);
const { gasSample, gasFromBills, priceAllGas } = globalThis.engine;

const use = usage.startsWith("people=") ? gasSample(Number(usage.slice(7)))
  : gasFromBills(usage.slice(6).split(",").map(b => { const [from, to, mj] = b.split(":"); return { from, to, mj: Number(mj) }; }));
const plans = fs.readdirSync(plansDir).filter(f => f.endsWith(".json"))
  .map(f => JSON.parse(fs.readFileSync(path.join(plansDir, f), "utf8")).data);
const { rows, skipped } = priceAllGas(plans, use);

const py = new Map(JSON.parse(fs.readFileSync(pythonPath, "utf8")).map(r => [r.id, r]));
const js = new Map(rows.map(r => [r.id, r]));
console.log(`Usage ${Math.round(use.yearMj).toLocaleString("en-AU")} MJ a year${use.split ? " (everyday and heating fitted)" : ""}`);
console.log(`Plans: ${plans.length} read, ${rows.length} priced by JS, ${skipped} skipped; ${py.size} priced by Python`);
const onlyJs = [...js.keys()].filter(id => !py.has(id));
const onlyPy = [...py.keys()].filter(id => !js.has(id));
if (onlyJs.length) console.log("Priced only by JS:", onlyJs.join(", "));
if (onlyPy.length) console.log("Priced only by Python:", onlyPy.join(", "));

let worst = 0, over = 0, credits = 0;
for (const [id, p] of py) {
  const j = js.get(id);
  if (!j) continue;
  const d = Math.abs(j.cost - p.cost);
  worst = Math.max(worst, d);
  if (d >= 1) { over++; console.log(`COST  ${id} ${p.retailer} | ${p.name}: Python ${p.cost.toFixed(2)}, JS ${j.cost.toFixed(2)}`); }
  if (j.credit !== p.credit) { credits++; console.log(`CREDIT ${id} ${p.retailer} | ${p.name}: Python $${p.credit}, JS $${j.credit}`); }
}
console.log(`Largest cost difference: $${worst.toFixed(6)}; plans off by $1 or more: ${over}; credit differences: ${credits}`);
process.exit(over || credits || onlyJs.length || onlyPy.length ? 1 : 0);
