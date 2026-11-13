"""Tests of the current schema contract, not source truth or runtime gates."""
import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


class HiveSchemaContractTests(unittest.TestCase):
    """Exercise structural constraints declared by the repository vehicle schema."""
    @classmethod
    def setUpClass(cls):
        """Load and validate the actual schema with explicit format checking."""
        schema = json.loads((ROOT / 'schemas/vehicle-variant.schema.json').read_text(encoding='utf-8'))
        Draft7Validator.check_schema(schema)
        cls.validator = Draft7Validator(schema, format_checker=FormatChecker())

    def setUp(self):
        """Create a minimal valid sparse vehicle record for each test."""
        self.record = {
            'schema_version': '1.0.0',
            'variant_id': 'test.synthetic',
            'status': 'draft',
            'identity': {'make': 'Synthetic', 'model': 'Test'},
            'provenance': {'confidence': 'low', 'reviewed_by': None, 'sources': []},
        }

    def assert_valid(self, record):
        """Assert that the supplied record satisfies the repository schema."""
        errors = list(self.validator.iter_errors(record))
        self.assertEqual(errors, [], [error.message for error in errors])

    def assert_invalid(self, record):
        """Assert that the supplied record violates at least one schema rule."""
        self.assertTrue(list(self.validator.iter_errors(record)))

    def test_sparse_record_is_structurally_valid_not_verified(self):
        """Show that schema validity permits a sparse record without proving facts."""
        self.assert_valid(self.record)

    def test_required_root_fields(self):
        """Reject records missing any required root-level property."""
        for key in ('schema_version', 'variant_id', 'status', 'identity', 'provenance'):
            with self.subTest(key=key):
                record = copy.deepcopy(self.record)
                del record[key]
                self.assert_invalid(record)

    def test_brand_cannot_replace_make(self):
        """Require identity.make rather than accepting a brand-only identity."""
        self.record['identity'] = {'brand': 'Synthetic'}
        self.assert_invalid(self.record)

    def test_empty_make_is_invalid(self):
        """Reject an empty make string."""
        self.record['identity']['make'] = ''
        self.assert_invalid(self.record)

    def test_offers_requires_array(self):
        """Reject an offers object where the schema requires an array."""
        self.record['offers'] = {'list_price_minor': 123}
        self.assert_invalid(self.record)

    def test_empty_offers_array_is_valid(self):
        """Accept an empty offers array under the current schema."""
        self.record['offers'] = []
        self.assert_valid(self.record)

    def test_source_url_string_is_invalid(self):
        """Reject URL strings where provenance sources must be objects."""
        self.record['provenance']['sources'] = ['https://example.invalid/source']
        self.assert_invalid(self.record)

    def test_source_object_is_structurally_valid(self):
        """Accept a source object with a URL under the current schema."""
        self.record['provenance']['sources'] = [{'url': 'https://example.invalid/source'}]
        self.assert_valid(self.record)

    def test_source_url_is_not_required_by_current_schema(self):
        """Record that the current schema does not require source URLs."""
        self.record['provenance']['sources'] = [{}]
        self.assert_valid(self.record)

    def test_claim_evidence_span_contract(self):
        self.record["provenance"]["claim_evidence"] = [{
            "claim_path": "performance.power_w",
            "source_id": "oem-1",
            "locator": "document",
            "quote": "Peak power is 110000 W.",
        }]
        self.assert_valid(self.record)
        del self.record["provenance"]["claim_evidence"][0]["quote"]
        self.assert_invalid(self.record)

    def test_claim_evidence_can_reference_offer_price_fields(self):
        """Accept claim paths for externally sourced offer and price values."""
        self.record["offers"] = [{
            "list_price_minor": 3499000,
            "purchase_price_excl_vat_eur": 2800.0,
        }]
        self.record["provenance"]["claim_evidence"] = [
            {
                "claim_path": "offers[0].list_price_minor",
                "source_id": "dealer-1",
                "locator": "offer page",
                "quote": "List price EUR 34,990",
            },
            {
                "claim_path": "offers[0].purchase_price_excl_vat_eur",
                "source_id": "dealer-1",
                "locator": "offer page",
                "quote": "Purchase price excluding VAT EUR 2,800",
            },
        ]
        self.assert_valid(self.record)

    def test_claim_evidence_binding_count_is_bounded(self):
        self.record["provenance"]["claim_evidence"] = [{
            "claim_path": f"performance.value_{index}",
            "source_id": "oem-1",
            "locator": "document",
            "quote": "source span",
        } for index in range(201)]
        self.assert_invalid(self.record)

    def test_confidence_enum(self):
        """Enforce the declared provenance confidence enumeration."""
        for confidence in ('low', 'medium', 'high', 'official'):
            with self.subTest(confidence=confidence):
                self.record['provenance']['confidence'] = confidence
                self.assert_valid(self.record)
        self.record['provenance']['confidence'] = 'verified'
        self.assert_invalid(self.record)

    def test_negative_power_is_invalid(self):
        """Reject negative numeric engine power."""
        self.record['performance'] = {'power_w': -1}
        self.assert_invalid(self.record)

    def test_boolean_power_is_invalid(self):
        """Reject booleans where a numeric power value is expected."""
        self.record['performance'] = {'power_w': True}
        self.assert_invalid(self.record)

    def test_negative_mass_is_invalid(self):
        """Reject negative vehicle mass."""
        self.record['dimensions'] = {'own_weight_kg': -1}
        self.assert_invalid(self.record)

    def test_fractional_minor_units_are_invalid(self):
        """Reject fractional values for integer monetary minor units."""
        self.record['offers'] = [{'list_price_minor': 123.5}]
        self.assert_invalid(self.record)

    def test_integer_minor_units_are_valid(self):
        """Accept integer values for monetary minor units."""
        self.record['offers'] = [{'list_price_minor': 123}]
        self.assert_valid(self.record)

    def test_date_format_checking_rejects_invalid_dates(self):
        """Reject malformed and impossible calendar dates with FormatChecker."""
        for value in ('not-a-date', '2025-02-29', '2026-13-01', '2026-11-11T00:00:00Z'):
            with self.subTest(value=value):
                self.record['registration'] = {'first_registration_date': value}
                self.assert_invalid(self.record)

    def test_date_and_null_are_valid(self):
        """Accept valid calendar dates and null for an unknown date."""
        for value in ('2024-02-29', '2026-11-11', None):
            with self.subTest(value=value):
                self.record['registration'] = {'first_registration_date': value}
                self.assert_valid(self.record)

    def test_unknown_numeric_values_can_be_null(self):
        """Accept null for unknown numeric specifications."""
        self.record['performance'] = {'power_w': None, 'electric_motor_continuous_power_w': None}
        self.record['dimensions'] = {'own_weight_kg': None}
        self.record['emissions'] = {'co2_wltp_gpkm': None}
        self.assert_valid(self.record)


if __name__ == '__main__':
    unittest.main()
