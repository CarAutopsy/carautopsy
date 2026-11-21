"""Offline unit tests for the attributed EEA adapters (STEP 2)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_eea_with_adapters import (  # noqa: E402
    CO2_DIVISOR,
    DERIVED_FROM,
    NEDC_REJECTION,
    PROPOSALS_ROOT,
    attach_price,
    build_proposal,
    derive_fuel_consumption,
    field_coverage,
    is_wltp_era,
    map_row,
    proposal_path,
    run_validation,
)


ROW = {
    "ID": "110900", "MS": "AT", "Mh": "VOLKSWAGEN", "Mk": "VOLKSWAGEN, VW",
    "Ve": "KOMBI", "Ct": "M1", "m (kg)": "2001", "Mt": "", "Enedc (g/km)": "164",
    "Ewltp (g/km)": "", "Ft": "DIESEL", "ep (KW)": "110", "TAN": "E1*2001/116*0220*46",
    "z (Wh/km)": "",
}


class AdapterUnitTests(unittest.TestCase):
    def test_wltp_year_filter(self):
        for year in (2018, 2020, 2026):
            self.assertTrue(is_wltp_era(year))
        for year in (2016, 2017, 2027, None, True, "2019"):
            self.assertFalse(is_wltp_era(year))

    def test_co2_conversion_petrol_and_diesel(self):
        diesel = derive_fuel_consumption(265, "ice_diesel")
        self.assertEqual(diesel["value"], 10.0)
        petrol = derive_fuel_consumption(232, "ice_petrol")
        self.assertEqual(petrol["value"], 10.0)
        for item in (diesel, petrol):
            self.assertTrue(item["derived"])
            self.assertFalse(item["measured"])
            self.assertEqual(item["derived_from"], DERIVED_FROM)
            self.assertIn("conversion_formula", item)
        self.assertIsNone(derive_fuel_consumption(200, "bev"))
        self.assertIsNone(derive_fuel_consumption("bad", "ice_petrol"))
        self.assertEqual(CO2_DIVISOR, {"ice_petrol": 23.2, "ice_diesel": 26.5})

    def test_price_pending_when_no_source(self):
        price = attach_price("eea-1", None)
        self.assertIsNone(price["purchase_price_excl_vat_eur"])
        self.assertTrue(price["price_pending"])
        priced = attach_price("eea-1", {"eea-1": {
            "price_excl_vat_eur": 25000, "source": "OEM MSRP", "url": "https://example.invalid/msrp"
        }})
        self.assertEqual(priced["purchase_price_excl_vat_eur"], 25000)
        self.assertFalse(priced["price_pending"])
        self.assertEqual(priced["price_source"], "OEM MSRP")

    def test_mapping_marks_derived_and_pending(self):
        record = map_row(ROW, 2017, None)
        fuel = record["extensions"]["fuel_consumption_l_100km"]
        self.assertTrue(fuel["derived"])
        self.assertEqual(fuel["real_world"], round(164 / 26.5, 3))
        self.assertTrue(record["price_pending"])
        self.assertEqual(record["provenance"]["sources"][0]["license"], "CC BY 4.0")
        self.assertEqual(record["source_fields"]["record_id"], "110900")

    def test_proposal_provenance_and_rejection(self):
        record = map_row(ROW, 2017, None)
        proposal = build_proposal(
            record, year=2017, findings=[NEDC_REJECTION], dataset_year=2017
        )
        self.assertEqual(proposal["status"], "rejected")
        self.assertFalse(proposal["gate"]["passed"])
        self.assertFalse(proposal["catalog_written"])
        self.assertTrue(proposal["requires_owner_approval"])
        prov = proposal["provenance"]
        for field in ("source_name", "source_url", "license", "dataset_year", "extraction_date", "record_id"):
            self.assertIn(field, prov)
        self.assertEqual(
            proposal["derived_fields"]["fuel_consumption_l_per_100km"]["derived_from"],
            DERIVED_FROM,
        )
        self.assertEqual(proposal_path(record, 2017).parent, PROPOSALS_ROOT)

    def test_coverage_counts_price_pending(self):
        records = [map_row(ROW, 2017, None)]
        coverage = field_coverage(records)
        self.assertEqual(coverage["offers.price_or_pending"], 100.0)
        self.assertEqual(coverage["extensions.fuel_consumption_l_100km.real_world"], 100.0)
        self.assertEqual(coverage["identity.powertrain"], 100.0)


class AdapterIntegrationTests(unittest.TestCase):
    def test_run_writes_only_rejected_proposals_to_docs(self):
        sample = ROOT / "docs" / "data-sources" / "sample" / "eea_at_2017_sample.tsv"
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "proposals"
            with self.assertRaisesRegex(ValueError, "only be written"):
                run_validation(sample, dataset_year=2017, price_source=None,
                               output_dir=out, with_taxes=False)
            out = PROPOSALS_ROOT
            report = run_validation(sample, dataset_year=2017, price_source=None,
                                    output_dir=out, with_taxes=False)
            self.assertEqual(report["sampled"], 20)
            self.assertFalse(report["wltp_era"])
            self.assertEqual(report["rejected"], 20)
            self.assertEqual(report["artifacts_written"], 0)
            self.assertEqual(report["rejection_reasons"], {NEDC_REJECTION: 20})
            self.assertEqual(report["catalog_variants_written"], 0)

            # Diagnostic mode still records rejected proposals when requested.
            diagnostic = run_validation(sample, dataset_year=2017, price_source=None,
                                        output_dir=out, with_taxes=False,
                                        include_rejected=True)
            self.assertEqual(diagnostic["artifacts_written"], 20)
        artifacts = list(out.glob("*.json"))
        self.assertGreaterEqual(len(artifacts), 20)
        for artifact in artifacts[:3]:
            data = json.loads(artifact.read_text(encoding="utf-8"))
            self.assertFalse(data["catalog_written"])
            self.assertEqual(data["gate"]["findings"], [NEDC_REJECTION])

    def test_no_catalog_files_were_modified(self):
        status = PROPOSALS_ROOT.parents[2] / "catalog" / "variants"
        self.assertTrue(status.is_dir())
        self.assertEqual(
            {p.name for p in status.glob("*.json")},
            {
                "fiat.500e.hatch.42kwh.json",
                "kia.ev3.my25.long-range-rwd.json",
                "renault.5.etech.52kwh-150.json",
                "tesla.model-3.highland.rwd-60.json",
                "tesla.model-y.juniper.rwd-60.json",
                "vw.tiguan.2026.tdi-150.json",
            },
        )


if __name__ == "__main__":
    unittest.main()
