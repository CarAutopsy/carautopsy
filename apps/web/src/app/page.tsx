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

type Envelope = {
  engine_version?: unknown;
  country_pack?: unknown;
  country_pack_status?: unknown;
  generated_utc?: unknown;
  note?: unknown;
};

type Payload = {
  results: Result[];
  summary: { variants: number; bev_avg_monthly_eur: number | null; ice_avg_monthly_eur: number | null };
  envelope: Envelope;
};

const eur = (n: number | null | undefined) =>
  n === null || n === undefined
    ? "—"
    : "€" + n.toLocaleString("de-AT", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const dynamic = "force-dynamic";

function parseStrictTimestamp(value: unknown): number {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
  ) {
    return Number.NaN;
  }
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  const calendarDate = new Date(0);
  calendarDate.setUTCHours(0, 0, 0, 0);
  calendarDate.setUTCFullYear(year, month - 1, day);
  if (
    year < 1 ||
    calendarDate.getUTCFullYear() !== year ||
    calendarDate.getUTCMonth() !== month - 1 ||
    calendarDate.getUTCDate() !== day
  ) {
    return Number.NaN;
  }
  return Date.parse(value);
}

async function getPublicationIssues(data: Payload): Promise<string[]> {
  const issues: string[] = [];
  const manifestPath = path.resolve(process.cwd(), "..", "..", "country-packs", "AT", "manifest.yaml");
  const contractPath = path.resolve(process.cwd(), "..", "..", "tco-contract.json");

  let manifest: string;
  let contractRaw: string;
  try {
    [manifest, contractRaw] = await Promise.all([
      fs.readFile(manifestPath, "utf8"),
      fs.readFile(contractPath, "utf8"),
    ]);
  } catch {
    return ["The current country-pack manifest or TCO contract could not be read; published figures are hidden."];
  }

  let contract: Record<string, unknown>;
  try {
    const parsedContract: unknown = JSON.parse(contractRaw);
    if (typeof parsedContract !== "object" || parsedContract === null || Array.isArray(parsedContract)) {
      return ["The shared TCO contract is invalid; published figures are hidden."];
    }
    contract = parsedContract as Record<string, unknown>;
  } catch {
    return ["The shared TCO contract is invalid; published figures are hidden."];
  }
  const expectedEngineVersion = contract.engine_version;
  const maxAgeDays = contract.max_artifact_age_days;
  const futureSkewMinutes = contract.max_future_skew_minutes;
  if (
    typeof expectedEngineVersion !== "string" ||
    typeof maxAgeDays !== "number" || !Number.isFinite(maxAgeDays) || maxAgeDays <= 0 ||
    typeof futureSkewMinutes !== "number" || !Number.isFinite(futureSkewMinutes) || futureSkewMinutes < 0
  ) {
    return ["The shared TCO contract has invalid version or freshness settings; published figures are hidden."];
  }
  const maxDataAgeMs = maxAgeDays * 24 * 60 * 60 * 1000;
  const maxFutureSkewMs = futureSkewMinutes * 60 * 1000;

  const version = manifest.match(/^version:\s*["']?([^"'\s#]+)["']?\s*$/m)?.[1];
  const status = manifest.match(/^status:\s*([A-Za-z_-]+)\s*$/m)?.[1];
  if (!version || !status) {
    return ["The current Austrian country-pack version or status is invalid; published figures are hidden."];
  }

  if (data.envelope.engine_version !== expectedEngineVersion) {
    issues.push(
      `Artifact engine ${String(data.envelope.engine_version ?? "missing")} does not match current engine ${expectedEngineVersion}.`
    );
  }
  const currentCountryPack = `AT@${version}`;
  if (data.envelope.country_pack !== currentCountryPack) {
    issues.push(
      `Artifact country pack ${String(data.envelope.country_pack ?? "missing")} does not match current pack ${currentCountryPack}.`
    );
  }
  if (data.envelope.country_pack_status !== status) {
    issues.push("Artifact country-pack status does not match the current manifest.");
  }
  if (status !== "verified") {
    issues.push(`The current Austrian tax pack is "${status}"; legal verification is required before TCO figures can be shown.`);
  }

  const generatedUtc = data.envelope.generated_utc;
  const generatedAt = parseStrictTimestamp(generatedUtc);
  if (!Number.isFinite(generatedAt)) {
    issues.push("Artifact generation timestamp is missing or invalid.");
  } else {
    const age = Date.now() - generatedAt;
    if (age > maxDataAgeMs) {
      issues.push("Artifact is older than the seven-day freshness limit.");
    } else if (age < -maxFutureSkewMs) {
      issues.push("Artifact generation timestamp is unexpectedly in the future.");
    }
  }

  return issues;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNullableFiniteNumber(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isResult(value: unknown): value is Result {
  if (!isRecord(value)) return false;
  return (
    typeof value.variant_id === "string" &&
    isNullableString(value.make) &&
    isNullableString(value.model) &&
    isNullableString(value.variant_name) &&
    typeof value.powertrain === "string" &&
    isFiniteNumber(value.power_kw) &&
    isNullableFiniteNumber(value.co2_gkm) &&
    isNullableFiniteNumber(value.list_price_eur) &&
    isFiniteNumber(value.nova_eur) &&
    isFiniteNumber(value.motor_tax_monthly_eur) &&
    isFiniteNumber(value.energy_5y_eur) &&
    isFiniteNumber(value.maintenance_5y_eur) &&
    isFiniteNumber(value.insurance_5y_eur) &&
    isFiniteNumber(value.tyres_5y_eur) &&
    isFiniteNumber(value.inspection_5y_eur) &&
    isFiniteNumber(value.total_5y_eur) &&
    isFiniteNumber(value.monthly_eur) &&
    isNullableString(value.data_confidence)
  );
}

function isPayload(value: unknown): value is Payload {
  if (!isRecord(value) || !Array.isArray(value.results) || !value.results.every(isResult)) return false;
  if (!isRecord(value.summary) || !isRecord(value.envelope)) return false;
  const { summary, envelope } = value;
  return (
    typeof summary.variants === "number" &&
    Number.isSafeInteger(summary.variants) &&
    (summary.variants as number) >= 0 &&
    isNullableFiniteNumber(summary.bev_avg_monthly_eur) &&
    isNullableFiniteNumber(summary.ice_avg_monthly_eur) &&
    typeof envelope.engine_version === "string" &&
    typeof envelope.country_pack === "string" &&
    typeof envelope.country_pack_status === "string" &&
    typeof envelope.generated_utc === "string" &&
    (envelope.note === undefined || typeof envelope.note === "string")
  );
}

export default async function Home() {
  let data: Payload | null = null;
  let loadError = false;
  try {
    const raw = await fs.readFile(path.join(process.cwd(), "public", "data", "autopsies.json"), "utf8");
    const parsed: unknown = JSON.parse(raw);
    if (!isPayload(parsed)) {
      throw new Error("Invalid TCO publication payload");
    }
    data = parsed;
  } catch {
    loadError = true;
  }

  const publicationIssues = data ? await getPublicationIssues(data) : [];

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100 p-6 md:p-12">
      <header className="mb-10">
        <h1 className="text-4xl md:text-5xl font-bold tracking-tight">CarAutopsy</h1>
        <p className="text-neutral-400 mt-2 max-w-2xl">
          Dissect your car&apos;s true ownership cost — calculated for Austria from statutory rules, not vibes.
        </p>
      </header>

      {!data ? (
        <section role="alert" className="border border-amber-700/60 bg-amber-950/30 rounded-lg p-5 max-w-3xl">
          <h2 className="text-lg font-semibold text-amber-200">TCO figures unavailable</h2>
          <p className="text-sm text-neutral-300 mt-2">
            {loadError
              ? "The published data file is missing or invalid. No cost figures are displayed."
              : "No autopsy data has been published yet. No cost figures are displayed."}
          </p>
        </section>
      ) : publicationIssues.length > 0 ? (
        <section role="alert" className="border border-amber-700/60 bg-amber-950/30 rounded-lg p-5 max-w-3xl">
          <h2 className="text-lg font-semibold text-amber-200">Published TCO data is stale or not approved</h2>
          <p className="text-sm text-neutral-300 mt-2">
            Saved figures are hidden until the artifact matches the current engine and country pack, the tax pack is legally verified, and the data is fresh.
          </p>
          <ul className="list-disc pl-5 mt-3 space-y-1 text-sm text-amber-100">
            {publicationIssues.map((issue) => <li key={issue}>{issue}</li>)}
          </ul>
        </section>
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
              generated {String(data.envelope.generated_utc)} · {String(data.envelope.note ?? "")}
            </p>
          </footer>
        </>
      )}
    </main>
  );
}
