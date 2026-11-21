"""Offline unit tests for the attributed EEA adapters (STEP 2)."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_eea_with_adapters import (
    CO2_DIVISOR,
    DEFAULT_STATUTORY_RULES,
    DERIVED_FROM,
    IDENTITY_QUALITY_CURATION,
    IDENTITY_QUALITY_OK,
    NEDC_REJECTION,
    PROPOSALS_ROOT,
    attach_price,
    build_proposal,
    derive_fuel_consumption,
    evaluate_identity_quality,
    evaluate_statutory,
    field_coverage,
    is_wltp_era,
    load_statutory_rules,
    map_row,
    proposal_path,
    read_rows,
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
        import validate_eea_with_adapters as adapter_module

        sample = ROOT / "docs" / "data-sources" / "sample" / "eea_at_2017_sample.tsv"
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "proposals"
            with self.assertRaisesRegex(ValueError, "only be written"):
                run_validation(sample, dataset_year=2017, price_source=None,
                               output_dir=out, with_taxes=False)

            # Isolate the artifact directory: tests must never read or write the
            # committed docs/data-sources/proposals/ tree.
            with patch.object(adapter_module, "PROPOSALS_ROOT", out):
                report = run_validation(sample, dataset_year=2017, price_source=None,
                                        output_dir=out, with_taxes=False)
                self.assertEqual(report["sampled"], 20)
                self.assertFalse(report["wltp_era"])
                self.assertEqual(report["rejected"], 20)
                self.assertEqual(report["artifacts_written"], 0)
                self.assertEqual(report["rejection_reasons"], {NEDC_REJECTION: 20})
                self.assertEqual(report["catalog_variants_written"], 0)

                diagnostic = run_validation(sample, dataset_year=2017, price_source=None,
                                            output_dir=out, with_taxes=False,
                                            include_rejected=True)
                self.assertEqual(diagnostic["artifacts_written"], 20)
                artifacts = sorted(out.glob("*.json"))
                self.assertEqual(len(artifacts), 20)
                for artifact in artifacts:
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


class StatutoryGateTests(unittest.TestCase):
    """Verified, in-period statutory outcomes only; no invented rates."""

    @classmethod
    def setUpClass(cls):
        cls.rules = load_statutory_rules(DEFAULT_STATUTORY_RULES)
        sample = ROOT / "docs" / "data-sources" / "sample" / "eea_at_2018_wltp_sample.tsv"
        cls.bev_row = next(row for row in read_rows(sample) if row["Ft"].strip().upper() == "ELECTRIC")
        cls.bev = map_row(cls.bev_row, 2018, None)

    def test_bev_2018_receives_both_verified_exemptions(self):
        result = evaluate_statutory(self.bev, self.rules, date(2018, 1, 1))
        self.assertTrue(result["verified"])
        self.assertEqual(result["findings"], [])
        self.assertTrue(result["nova"]["exemption"])
        self.assertEqual(result["nova"]["rate_eur"], 0)
        self.assertEqual(result["nova"]["outcome"], "verified statutory exemption")
        self.assertTrue(result["motor_tax"]["exemption"])
        self.assertEqual(result["motor_tax"]["rate_eur_per_month"], 0)
        self.assertIn("BGBl. I Nr. 7/2025", result["motor_tax"]["legal_basis"])

    def test_ice_uses_non_electric_schedule(self):
        row = dict(self.bev_row)
        row["Ft"] = "DIESEL"
        row["Ewltp (g/km)"] = "150"
        ice = map_row(row, 2018, None)
        result = evaluate_statutory(ice, self.rules, date(2018, 1, 1))
        self.assertTrue(result["verified"])
        self.assertFalse(result["nova"]["exemption"])
        self.assertFalse(result["motor_tax"]["exemption"])
        self.assertEqual(result["motor_tax"]["outcome"], "verified non-electric M1 schedule")
        self.assertIn(2018, result["taxes"]["nova"]["annual_rules"])
        self.assertIn("ice", result["taxes"]["motorbezogene_versicherungssteuer"]["annual_rules"][2018])

    def test_bev_on_or_after_2025_04_01_is_not_exempt(self):
        result = evaluate_statutory(self.bev, self.rules, date(2025, 4, 1))
        self.assertFalse(result["verified"])
        self.assertTrue(any("motorbezogene_versicherungssteuer" in item for item in result["findings"]))

    def test_record_outside_all_rule_periods_is_rejected(self):
        row = dict(self.bev_row)
        row["Ft"] = "PETROL"
        row["Ewltp (g/km)"] = "140"
        record = map_row(row, 2021, None)
        result = evaluate_statutory(record, self.rules, date(2021, 1, 1))
        self.assertFalse(result["verified"])
        self.assertEqual(len(result["findings"]), 2)
        self.assertTrue(all("STATUTORY_RULE_UNAVAILABLE" in item for item in result["findings"]))

    def test_missing_statutory_data_is_an_explicit_rejection(self):
        empty = {"schema_version": 1, "jurisdiction": "AT", "rules": []}
        result = evaluate_statutory(self.bev, empty, date(2018, 1, 1))
        self.assertFalse(result["verified"])
        self.assertEqual(len(result["findings"]), 2)
        self.assertTrue(all("STATUTORY_RULE_UNAVAILABLE" in item for item in result["findings"]))

    def test_rules_file_metadata_is_complete(self):
        for rule in self.rules["rules"]:
            for field in ("tax", "powertrain", "applicable_from", "applicable_to",
                          "exemption", "legal_basis", "source_url", "publisher", "retrieved"):
                self.assertIn(field, rule)


class IdentityQualityTests(unittest.TestCase):
    """Pre-ingestion curation marker for non-consumer-facing EEA identities."""

    def setUp(self):
        self.record = map_row(ROW, 2018, None)

    def test_make_equals_model_is_flagged(self):
        self.record["identity"]["model"] = self.record["identity"]["make"]
        result = evaluate_identity_quality(self.record)
        self.assertEqual(result["identity_quality"], IDENTITY_QUALITY_CURATION)
        self.assertTrue(any("model equals make" in reason for reason in result["reasons"]))
        self.assertIn("model equals make", result["curation_reason"])

    def test_missing_model_is_flagged(self):
        self.record["identity"]["model"] = ""
        result = evaluate_identity_quality(self.record)
        self.assertEqual(result["identity_quality"], IDENTITY_QUALITY_CURATION)
        self.assertIn("model is missing", result["reasons"])

    def test_non_descriptive_variant_code_is_flagged(self):
        self.record["identity"]["variant_name"] = "A02"
        result = evaluate_identity_quality(self.record)
        self.assertEqual(result["identity_quality"], IDENTITY_QUALITY_CURATION)
        self.assertTrue(any("non-descriptive" in reason for reason in result["reasons"]))
        self.assertIn("A02", result["curation_reason"])

    def test_type_approval_signature_is_flagged(self):
        self.record["identity"]["variant_name"] = "E1*2001/116*0220*46"
        result = evaluate_identity_quality(self.record)
        self.assertEqual(result["identity_quality"], IDENTITY_QUALITY_CURATION)
        self.assertTrue(any("non-descriptive" in reason for reason in result["reasons"]))

    def test_differentiated_identity_passes_without_curation(self):
        # ROW maps to make=VOLKSWAGEN, model=VOLKSWAGEN, VW, variant=KOMBI.
        result = evaluate_identity_quality(self.record)
        self.assertEqual(result["identity_quality"], IDENTITY_QUALITY_OK)
        self.assertIsNone(result["curation_reason"])
        self.assertEqual(result["reasons"], [])

    def test_build_proposal_carries_markers_without_touching_source_fields(self):
        self.record["identity"]["model"] = self.record["identity"]["make"]
        self.record["identity"]["variant_name"] = "A02"
        source_before = copy.deepcopy(self.record["source_fields"])
        provenance_before = copy.deepcopy(self.record["provenance"])
        proposal = build_proposal(
            self.record, year=2018, findings=[], dataset_year=2018
        )
        self.assertEqual(proposal["identity_quality"], IDENTITY_QUALITY_CURATION)
        self.assertIn("model equals make", proposal["curation_reason"])
        self.assertEqual(proposal["variant"]["source_fields"], source_before)
        self.assertEqual(proposal["variant"]["provenance"], provenance_before)

    def test_canonical_artifact_is_marked_and_every_fact_preserved(self):
        path = PROPOSALS_ROOT / "nissan.nissan.a02.2018.2887803.json"
        proposal = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(proposal["identity_quality"], IDENTITY_QUALITY_CURATION)
        self.assertIn("NISSAN", proposal["curation_reason"])
        self.assertIn("A02", proposal["curation_reason"])
        self.assertIn("model equals make", proposal["curation_reason"])
        self.assertFalse(proposal["catalog_written"])
        self.assertTrue(proposal["requires_owner_approval"])
        self.assertTrue(proposal["gate"]["passed"])
        self.assertEqual(proposal["deduplication_role"], "canonical")
        self.assertIsNone(proposal["duplicate_of"])
        variant = proposal["variant"]
        self.assertEqual(variant["source_fields"]["record_id"], "2887803")
        self.assertEqual(variant["source_fields"]["make"], "NISSAN")
        self.assertEqual(variant["source_fields"]["model"], "NISSAN")
        self.assertEqual(variant["source_fields"]["variant"], "A02")
        self.assertEqual(variant["source_fields"]["co2_g_per_km"], 0.0)
        self.assertEqual(variant["source_fields"]["powertrain"], "bev")
        self.assertEqual(variant["provenance"]["sources"][0]["record_id"], "2887803")
        self.assertTrue(proposal["statutory"]["verified"])
        self.assertTrue(proposal["price"]["price_pending"])
        self.assertIsNone(proposal["price"]["purchase_price_excl_vat_eur"])

    def test_run_reports_curation_without_catalog_writes(self):
        import validate_eea_with_adapters as adapter_module

        sample = ROOT / "docs" / "data-sources" / "sample" / "eea_at_2018_wltp_sample.tsv"
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "proposals"
            with patch.object(adapter_module, "PROPOSALS_ROOT", out):
                report = run_validation(
                    sample, dataset_year=2018, price_source=None,
                    output_dir=out, with_taxes=True,
                )
            self.assertEqual(report["catalog_variants_written"], 0)
            self.assertEqual(report["artifacts_written"], 9)
            self.assertEqual(report["identity_curation_required_count"], 9)
            artifacts = sorted(out.glob("*.json"))
            self.assertEqual(len(artifacts), 9)
            for artifact in artifacts:
                data = json.loads(artifact.read_text(encoding="utf-8"))
                self.assertEqual(data["identity_quality"], IDENTITY_QUALITY_CURATION)
                self.assertFalse(data["catalog_written"])


if __name__ == "__main__":
    unittest.main()
