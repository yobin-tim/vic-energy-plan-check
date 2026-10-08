// Checks the JavaScript pricing engine in index.html against the Python reference output.
// Both price the same downloaded plan files, so every plan's cost should agree within $1.
// Usage (from the project folder):
//   node reference/compare_engine.mjs <meter.csv> reference/allplans <python output.json>
// Prints only differences and counts; it writes nothing. Exit code 1 if any cost is off by $1+.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const [meterPath, plansDir, pythonPath] = process.argv.slice(2);
if (!pythonPath) {
  console.error("Usage: node reference/compare_engine.mjs <meter.csv> <plans folder> <python output.json>");
  process.exit(2);
}

// Run the page's <script id="engine"> block on its own, exactly as the browser would.
const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const src = html.match(/<script id="engine">([\s\S]*?)<\/script>/)[1];
// Main context, not a vm sandbox: a sandbox makes every Math/Number lookup slow (15x here).
vm.runInThisContext(`${src}\nglobalThis.engine = { parseMeter, priceAll };`);
const { parseMeter, priceAll } = globalThis.engine;

const meter = parseMeter(fs.readFileSync(meterPath, "utf8"));
const plans = fs.readdirSync(plansDir).filter(f => f.endsWith(".json"))
  .map(f => JSON.parse(fs.readFileSync(path.join(plansDir, f), "utf8")).data);
const t0 = performance.now();
const { rows, skipped } = priceAll(plans, meter);
const ms = performance.now() - t0;

const py = new Map(JSON.parse(fs.readFileSync(pythonPath, "utf8"))
  .filter(r => r.id !== "manual")                  // the Python's hand-entered example offer
  .map(r => [r.id, r]));
const js = new Map(rows.map(r => [r.id, r]));

const day = ms => new Date(ms).toISOString().slice(0, 10);
console.log(`Window ${day(meter.first)} to ${day(meter.last)}: ${meter.days.length} days with data`);
console.log(`Plans: ${plans.length} read, ${rows.length} priced by JS, ${skipped} skipped; ${py.size} priced by Python`);
console.log(`Pricing took ${Math.round(ms)} ms`);

const onlyJs = [...js.keys()].filter(id => !py.has(id));
const onlyPy = [...py.keys()].filter(id => !js.has(id));
if (onlyJs.length) console.log("Priced only by JS:", onlyJs.join(", "));
if (onlyPy.length) console.log("Priced only by Python:", onlyPy.join(", "));

let worst = 0, over = 0;
const creditDiffs = [];
for (const [id, p] of py) {
  const j = js.get(id);
  if (!j) continue;
  const d = Math.abs(j.cost - p.cost);
  worst = Math.max(worst, d);
  if (d >= 1) { over++; console.log(`COST  ${id} ${p.retailer} | ${p.name}: Python ${p.cost.toFixed(2)}, JS ${j.cost.toFixed(2)}`); }
  if (j.credit !== p.credit) creditDiffs.push(`${id} ${p.retailer} | ${p.name}: Python $${p.credit}, JS $${j.credit}`);
}
console.log(`Largest cost difference: $${worst.toFixed(6)}; plans off by $1 or more: ${over}`);
console.log(`Sign-up credit differences: ${creditDiffs.length}`);
creditDiffs.forEach(x => console.log("CREDIT", x));
process.exit(over || onlyJs.length || onlyPy.length ? 1 : 0);
