export type Result = {
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

export type Envelope = {
  engine_version?: unknown;
  country_pack?: unknown;
  country_pack_status?: unknown;
  generated_utc?: unknown;
  note?: unknown;
};

export type Payload = {
  results: Result[];
  summary: {
    variants: number;
    bev_avg_monthly_eur: number | null;
    ice_avg_monthly_eur: number | null;
  };
  envelope: Envelope;
};

export function eur(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `€${value.toLocaleString("de-AT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function powertrainLabel(powertrain: string): string {
  const labels: Record<string, string> = {
    bev: "Battery electric",
    ice_petrol: "Petrol",
    ice_diesel: "Diesel",
    hev: "Hybrid",
    phev: "Plug-in hybrid",
  };
  return labels[powertrain] ?? powertrain;
}
