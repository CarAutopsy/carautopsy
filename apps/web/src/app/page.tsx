import { promises as fs } from "node:fs";
import path from "node:path";
import Explorer from "../components/Explorer";
import type { Payload, Result } from "../lib/types";

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
    <div className="min-h-screen">
      <header className="ca-hero-band">
        <div className="mx-auto max-w-6xl px-6 md:px-10 py-14 md:py-20">
          <p className="ca-eyebrow">Austria · statutory TCO</p>
          <h1 className="text-4xl md:text-6xl font-bold tracking-tight mt-3">
            Dissect your car&apos;s <span className="ca-accent">true cost</span>.
          </h1>
          <p className="text-neutral-300 mt-4 max-w-2xl text-base md:text-lg">
            Transparent, attested ownership costs built from statutory tax rules — not estimates dressed up as facts.
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 md:px-10 py-10 md:py-14">
        {!data ? (
          <section role="alert" className="ca-card ca-alert p-6 max-w-3xl">
            <p className="ca-eyebrow">Publication held</p>
            <h2 className="text-xl font-semibold text-amber-200 mt-2">TCO figures unavailable</h2>
            <p className="text-sm text-neutral-300 mt-3">
              {loadError
                ? "The published data file is missing or invalid. No cost figures are displayed."
                : "No autopsy data has been published yet. No cost figures are displayed."}
            </p>
          </section>
        ) : publicationIssues.length > 0 ? (
          <section role="alert" className="ca-card ca-alert p-6 md:p-8 max-w-4xl">
            <p className="ca-eyebrow">Fail-closed publication guard</p>
            <h2 className="text-2xl font-semibold text-amber-200 mt-2">
              Figures withheld until the attestation matches
            </h2>
            <p className="text-sm text-neutral-300 mt-3 max-w-2xl">
              Saved figures are hidden until the artifact matches the current engine and country pack, the tax
              pack is legally verified, and the data is fresh. This is intentional: stale or unapproved numbers
              are never shown as current.
            </p>
            <ul className="list-disc pl-5 mt-4 space-y-2 text-sm text-amber-100">
              {publicationIssues.map((issue) => <li key={issue}>{issue}</li>)}
            </ul>
            <p className="text-xs text-neutral-500 mt-5">
              Saved artifact: engine {String(data.envelope.engine_version ?? "—")} · pack{" "}
              {String(data.envelope.country_pack ?? "—")} · generated{" "}
              {String(data.envelope.generated_utc ?? "—")}
            </p>
          </section>
        ) : (
          <Explorer results={data.results} summary={data.summary} envelope={data.envelope} />
        )}
      </main>

      <footer className="border-t border-neutral-800/80 mt-10">
        <div className="mx-auto max-w-6xl px-6 md:px-10 py-8 text-xs text-neutral-500 flex flex-wrap gap-x-6 gap-y-2">
          <span>CarAutopsy · transparent ownership economics</span>
          <span>No live vehicle data is collected by this page.</span>
        </div>
      </footer>
    </div>
  );
}
