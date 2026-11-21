"use client";

import { useMemo, useState } from "react";
import { eur, powertrainLabel, type Envelope, type Payload, type Result } from "../lib/types";

type SortKey = "monthly" | "total" | "name";
type PowertrainFilter = "all" | "bev" | "other";

type Props = {
  results: Result[];
  summary: Payload["summary"];
  envelope: Envelope;
};

function breakdown(result: Result) {
  const motorTax5y = result.motor_tax_monthly_eur * 12 * 5;
  return [
    { label: "Energy (5y)", value: result.energy_5y_eur, tone: "emerald" },
    { label: "Insurance (5y)", value: result.insurance_5y_eur, tone: "sky" },
    { label: "Maintenance (5y)", value: result.maintenance_5y_eur, tone: "amber" },
    { label: "Tyres + §57a (5y)", value: result.tyres_5y_eur + result.inspection_5y_eur, tone: "violet" },
    { label: "Motor tax (5y)", value: motorTax5y, tone: "rose" },
    { label: "NoVA (once)", value: result.nova_eur, tone: "yellow" },
  ];
}

const toneClass: Record<string, string> = {
  emerald: "bg-emerald-400",
  sky: "bg-sky-400",
  amber: "bg-amber-400",
  violet: "bg-violet-400",
  rose: "bg-rose-400",
  yellow: "bg-yellow-400",
};

export default function Explorer({ results, summary, envelope }: Props) {
  const [query, setQuery] = useState("");
  const [powertrain, setPowertrain] = useState<PowertrainFilter>("all");
  const [sort, setSort] = useState<SortKey>("monthly");
  const [selectedId, setSelectedId] = useState<string>(results[0]?.variant_id ?? "");

  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const filtered = results.filter((result) => {
      const matchesText =
        needle === "" ||
        [result.make, result.model, result.variant_name, result.variant_id, result.powertrain]
          .filter((value): value is string => typeof value === "string")
          .some((value) => value.toLocaleLowerCase().includes(needle));
      const matchesPowertrain =
        powertrain === "all" ||
        (powertrain === "bev" ? result.powertrain === "bev" : result.powertrain !== "bev");
      return matchesText && matchesPowertrain;
    });
    return [...filtered].sort((a, b) => {
      if (sort === "name") {
        return `${a.make ?? ""} ${a.model ?? ""}`.localeCompare(`${b.make ?? ""} ${b.model ?? ""}`);
      }
      if (sort === "total") return b.total_5y_eur - a.total_5y_eur;
      return a.monthly_eur - b.monthly_eur;
    });
  }, [results, query, powertrain, sort]);

  const selected =
    visible.find((result) => result.variant_id === selectedId) ?? visible[0] ?? null;
  const rows = selected ? breakdown(selected) : [];
  const maxValue = Math.max(...rows.map((row) => row.value), 1);

  return (
    <>
      <section className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-8" aria-label="Publication summary">
        <div className="ca-stat">
          <p className="ca-stat-label">Variants dissected</p>
          <p className="ca-stat-value">{summary.variants}</p>
        </div>
        <div className="ca-stat">
          <p className="ca-stat-label">BEV avg / month (5y)</p>
          <p className="ca-stat-value text-emerald-300">{eur(summary.bev_avg_monthly_eur)}</p>
        </div>
        <div className="ca-stat">
          <p className="ca-stat-label">Non-BEV avg / month (5y)</p>
          <p className="ca-stat-value text-rose-300">{eur(summary.ice_avg_monthly_eur)}</p>
        </div>
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] gap-6 items-start">
        <div className="ca-card p-4">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-neutral-400 mb-3">
            Vehicle catalog
          </h2>
          <label className="block text-xs text-neutral-400 mb-1" htmlFor="ca-search">
            Search make, model or variant
          </label>
          <input
            id="ca-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="e.g. Model 3, Tesla, BEV"
            className="ca-input"
          />
          <div className="grid grid-cols-2 gap-2 mt-3">
            <label className="block text-xs text-neutral-400" htmlFor="ca-filter">
              Powertrain
              <select
                id="ca-filter"
                value={powertrain}
                onChange={(event) => setPowertrain(event.target.value as PowertrainFilter)}
                className="ca-input mt-1"
              >
                <option value="all">All</option>
                <option value="bev">Battery electric</option>
                <option value="other">Combustion / hybrid</option>
              </select>
            </label>
            <label className="block text-xs text-neutral-400" htmlFor="ca-sort">
              Sort by
              <select
                id="ca-sort"
                value={sort}
                onChange={(event) => setSort(event.target.value as SortKey)}
                className="ca-input mt-1"
              >
                <option value="monthly">Lowest monthly</option>
                <option value="total">Highest 5y cost</option>
                <option value="name">Name</option>
              </select>
            </label>
          </div>
          <p className="text-xs text-neutral-500 mt-3" aria-live="polite">
            {visible.length} of {results.length} variants
          </p>
          <ul className="mt-3 space-y-2 max-h-[32rem] overflow-y-auto pr-1" aria-label="Vehicle variants">
            {visible.map((result) => (
              <li key={result.variant_id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(result.variant_id)}
                  aria-pressed={selected?.variant_id === result.variant_id}
                  className={`ca-variant ${
                    selected?.variant_id === result.variant_id ? "ca-variant-active" : ""
                  }`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="font-medium text-sm">
                      {result.make} {result.model}
                    </span>
                    <span className="text-emerald-300 font-semibold text-sm whitespace-nowrap">
                      {eur(result.monthly_eur)}/mo
                    </span>
                  </span>
                  <span className="flex items-center justify-between gap-2 mt-1 text-xs text-neutral-500">
                    <span>{result.variant_name ?? result.powertrain}</span>
                    <span>{powertrainLabel(result.powertrain)}</span>
                  </span>
                </button>
              </li>
            ))}
            {visible.length === 0 && (
              <li className="text-sm text-neutral-500 py-4">No variants match these filters.</li>
            )}
          </ul>
        </div>

        <div className="ca-card p-5 md:p-7">
          {selected ? (
            <>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="ca-eyebrow">Ownership autopsy</p>
                  <h2 className="text-2xl md:text-3xl font-semibold mt-1">
                    {selected.make} {selected.model}{" "}
                    <span className="text-neutral-500">{selected.variant_name}</span>
                  </h2>
                  <p className="text-xs text-neutral-500 mt-1">{selected.variant_id}</p>
                </div>
                <span className="ca-badge">{powertrainLabel(selected.powertrain)}</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-6">
                <div className="ca-hero ca-hero-primary">
                  <p className="ca-stat-label">True monthly cost</p>
                  <p className="text-4xl font-bold mt-1">{eur(selected.monthly_eur)}</p>
                  <p className="text-xs text-neutral-400 mt-1">5-year horizon · 15,000 km/year</p>
                </div>
                <div className="ca-hero">
                  <p className="ca-stat-label">5-year total</p>
                  <p className="text-4xl font-semibold mt-1">{eur(selected.total_5y_eur)}</p>
                  <p className="text-xs text-neutral-400 mt-1">Operating + statutory costs</p>
                </div>
              </div>

              <h3 className="text-sm font-semibold uppercase tracking-widest text-neutral-400 mt-8 mb-4">
                Where the money goes
              </h3>
              <ul className="space-y-3">
                {rows.map((row) => (
                  <li key={row.label}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-neutral-300">{row.label}</span>
                      <span className="tabular-nums">{eur(row.value)}</span>
                    </div>
                    <div className="ca-bar" role="img" aria-label={`${row.label}: ${eur(row.value)}`}>
                      <div
                        className={`ca-bar-fill ${toneClass[row.tone]}`}
                        style={{ width: `${Math.max(2, (row.value / maxValue) * 100)}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>

              <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-8 pt-6 border-t border-neutral-800 text-sm">
                <div>
                  <dt className="ca-stat-label">Power</dt>
                  <dd className="mt-1">{selected.power_kw} kW</dd>
                </div>
                <div>
                  <dt className="ca-stat-label">CO₂</dt>
                  <dd className="mt-1">{selected.co2_gkm ?? "—"} g/km</dd>
                </div>
                <div>
                  <dt className="ca-stat-label">List price</dt>
                  <dd className="mt-1">{eur(selected.list_price_eur)}</dd>
                </div>
                <div>
                  <dt className="ca-stat-label">Data confidence</dt>
                  <dd className="mt-1 capitalize">{selected.data_confidence ?? "unknown"}</dd>
                </div>
              </dl>
            </>
          ) : (
            <p className="text-neutral-400">Select a vehicle to see its cost breakdown.</p>
          )}
        </div>
      </section>

      <section className="ca-card mt-8 p-5 md:p-7" aria-labelledby="ca-trust-heading">
        <h2 id="ca-trust-heading" className="text-lg font-semibold">
          Why these numbers are traceable
        </h2>
        <p className="text-sm text-neutral-400 mt-2 max-w-3xl">
          Every published figure is attested to the exact catalog inputs, statutory rule pack and source
          revision that produced it. If any input changes, the publication gate withholds the figures until
          a new attested artifact is produced — no silent updates.
        </p>
        <dl className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-5 text-sm">
          <div>
            <dt className="ca-stat-label">Engine</dt>
            <dd className="mt-1 font-mono text-xs">{String(envelope.engine_version ?? "—")}</dd>
          </div>
          <div>
            <dt className="ca-stat-label">Country pack</dt>
            <dd className="mt-1 font-mono text-xs">{String(envelope.country_pack ?? "—")}</dd>
          </div>
          <div>
            <dt className="ca-stat-label">Generated (UTC)</dt>
            <dd className="mt-1 font-mono text-xs break-all">
              {String(envelope.generated_utc ?? "—")}
            </dd>
          </div>
        </dl>
        {typeof envelope.note === "string" && (
          <p className="text-xs text-neutral-500 mt-4">{envelope.note}</p>
        )}
      </section>
    </>
  );
}
