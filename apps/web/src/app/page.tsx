import { promises as fs } from "fs";
import path from "path";

type Result = {
  variant_id: string;
  make: string | null;
  model: string | null;
  variant_name: string | null;
  powertrain: string;
  power_kw: number;
  co2_gkm: number | null;
  list_price_eur: number | null;
  nova_eur: number;
  motor_tax_monthly_eur: number;
  energy_5y_eur: number;
  maintenance_5y_eur: number;
  insurance_5y_eur: number;
  tyres_5y_eur: number;
  inspection_5y_eur: number;
  total_5y_eur: number;
  monthly_eur: number;
  data_confidence: string | null;
};

type Payload = {
  results: Result[];
  summary: { variants: number; bev_avg_monthly_eur: number | null; ice_avg_monthly_eur: number | null };
  envelope: Record<string, unknown>;
};

const eur = (n: number | null | undefined) =>
  n === null || n === undefined
    ? "—"
    : "€" + n.toLocaleString("de-AT", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default async function Home() {
  let data: Payload | null = null;
  try {
    const raw = await fs.readFile(path.join(process.cwd(), "public", "data", "autopsies.json"), "utf8");
    data = JSON.parse(raw) as Payload;
  } catch {
    data = null;
  }

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100 p-6 md:p-12">
      <header className="mb-10">
        <h1 className="text-4xl md:text-5xl font-bold tracking-tight">CarAutopsy</h1>
        <p className="text-neutral-400 mt-2 max-w-2xl">
          Dissect your car&apos;s true ownership cost — calculated for Austria from statutory rules, not vibes.
        </p>
      </header>

      {!data ? (
        <p className="text-neutral-400">
          No autopsy data published yet. Run the “Publish TCO Results” workflow, then merge its PR.
        </p>
      ) : (
        <>
          <section className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-10">
            <div className="border border-neutral-800 rounded-lg p-4">
              <p className="text-neutral-500 text-sm">Variants dissected</p>
              <p className="text-2xl font-semibold">{data.summary.variants}</p>
            </div>
            <div className="border border-neutral-800 rounded-lg p-4">
              <p className="text-neutral-500 text-sm">BEV avg / month (5y)</p>
              <p className="text-2xl font-semibold text-emerald-400">{eur(data.summary.bev_avg_monthly_eur)}</p>
            </div>
            <div className="border border-neutral-800 rounded-lg p-4">
              <p className="text-neutral-500 text-sm">Non-BEV avg / month (5y)</p>
              <p className="text-2xl font-semibold text-red-400">{eur(data.summary.ice_avg_monthly_eur)}</p>
            </div>
          </section>

          <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {data.results.map((r) => (
              <article key={r.variant_id} className="border border-neutral-800 rounded-lg p-6 bg-neutral-900/40">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="text-xl font-semibold">
                      {r.make} {r.model} <span className="text-neutral-500">{r.variant_name}</span>
                    </h2>
                    <p className="text-sm text-neutral-500">{r.variant_id}</p>
                  </div>
                  <span
                    className={`text-xs px-2 py-1 rounded ${
                      r.powertrain === "bev" ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/15 text-red-300"
                    }`}
                  >
                    {r.powertrain}
                  </span>
                </div>

                <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                  <div className="flex justify-between"><dt className="text-neutral-500">NoVA (once)</dt><dd>{eur(r.nova_eur)}</dd></div>
                  <div className="flex justify-between"><dt className="text-neutral-500">Motor tax / mo</dt><dd>{eur(r.motor_tax_monthly_eur)}</dd></div>
                  <div className="flex justify-between"><dt className="text-neutral-500">Energy 5y</dt><dd>{eur(r.energy_5y_eur)}</dd></div>
                  <div className="flex justify-between"><dt className="text-neutral-500">Maintenance 5y</dt><dd>{eur(r.maintenance_5y_eur)}</dd></div>
                  <div className="flex justify-between"><dt className="text-neutral-500">Insurance 5y</dt><dd>{eur(r.insurance_5y_eur)}</dd></div>
                  <div className="flex justify-between"><dt className="text-neutral-500">Tyres + §57a 5y</dt><dd>{eur(r.tyres_5y_eur + r.inspection_5y_eur)}</dd></div>
                </dl>

                <div className="mt-4 pt-4 border-t border-neutral-800 flex items-end justify-between">
                  <div>
                    <p className="text-neutral-500 text-sm">5-year cost (excl. depreciation)</p>
                    <p className="text-3xl font-bold">{eur(r.total_5y_eur)}</p>
                  </div>
                  <p className="text-neutral-400 text-sm">{eur(r.monthly_eur)} / month</p>
                </div>
                <p className="mt-2 text-xs text-neutral-600">
                  data confidence: {r.data_confidence ?? "unknown"} · {r.power_kw} kW · CO₂ {r.co2_gkm ?? "—"} g/km
                </p>
              </article>
            ))}
          </section>

          <footer className="mt-12 text-xs text-neutral-600 max-w-3xl">
            <p>
              Engine {String(data.envelope.engine_version)} · country pack {String(data.envelope.country_pack)} ·
              generated {String(data.envelope.generated_utc)} · {String(data.envelope.note)}
            </p>
          </footer>
        </>
      )}
    </main>
  );
}
