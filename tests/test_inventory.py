import tempfile
import unittest
from pathlib import Path

import pandas as pd

from inventory import (
    DETAIL_COLUMNS, LOCATION_COLUMNS, build_inventory, filter_inventory,
    load_data, validate_data,
    parse_data,
)


def catalog(*rows):
    return pd.DataFrame([
        dict.fromkeys(DETAIL_COLUMNS, "") | row for row in rows
    ], columns=DETAIL_COLUMNS)


def stock(*rows):
    return pd.DataFrame(rows, columns=LOCATION_COLUMNS)


class InventoryTests(unittest.TestCase):
    def test_legacy_stock_uses_available_balance_including_zero_and_unknown(self):
        details = catalog({"code": "ITEM0001"}).to_csv(index=False)
        old = "code,location,sublocation,units,available\nITEM0001,A,01,10,3\nITEM0001,A,02,5,0\nITEM0001,A,03,7,\n"
        _, locations = parse_data(details, old)
        self.assertEqual(locations["units"].tolist(), ["3", "0", ""])
        self.assertEqual(locations["sublocation"].tolist(), ["01", "02", "03"])
        self.assertNotIn("available", locations.columns)
        issues = validate_data(catalog({"code": "ITEM0001"}), locations)
        self.assertTrue(any("invalid quantities" in issue for issue in issues))

    def test_duplicate_products_do_not_multiply_stock(self):
        details = catalog(
            {"code": "RELAY000", "description": "two relays"},
            {"code": "RELAY000", "description": "four relays"},
        )
        locations = stock(["RELAY000", "A", "12", "4"], ["RELAY000", "A", "13", "2"])
        result = build_inventory(details, locations)
        self.assertEqual(len(result), 2)
        self.assertEqual(result.units.astype(int).sum(), 6)
        self.assertTrue(result.description.str.contains("two relays / four relays", regex=False).all())
        self.assertTrue(result.status.str.contains("ambiguous").all())

    def test_unmatched_stock_is_visible_and_missing_stock_stays_unknown(self):
        result = build_inventory(catalog({"code": "KNOWN000"}), stock(["ORPHAN00", "A", "01", "2"]))
        orphan = result[result.code.eq("ORPHAN00")].iloc[0]
        known = result[result.code.eq("KNOWN000")].iloc[0]
        self.assertEqual(orphan.units, "2")
        self.assertEqual(orphan.type, "Unclassified")
        self.assertEqual(known.units, "")
        self.assertIn("unknown", known.status)

    def test_search_is_global_literal_and_case_insensitive(self):
        result = build_inventory(catalog(
            {"code": "BOARD000", "type": "board", "subtype": "dev", "description": "10k( [2.2]", "model": "S3"},
            {"code": "SENSOR00", "type": "sensor", "subtype": "light", "manufacturer": "Adafruit"},
        ), stock())
        for term in ("[", "10k(", "2.2", "s3", " board000 "):
            self.assertEqual(filter_inventory(result, term).code.tolist(), ["BOARD000"])
        self.assertEqual(filter_inventory(result, "ADAFRUIT").code.tolist(), ["SENSOR00"])
        self.assertTrue(filter_inventory(result, "[", "sensor").empty)
        self.assertTrue(filter_inventory(result, "[", "unknown type").empty)

    def test_search_empty_results_does_not_raise(self):
        result = build_inventory(catalog(), stock())
        self.assertTrue(filter_inventory(result, "[").empty)

    def test_validation_reports_duplicates_missing_references_and_invalid_stock(self):
        details = catalog({"code": "DUP00000", "info": "Provisional count: pending"}, {"code": "DUP00000"}, {"code": "ONLYCAT0"})
        locations = stock(
            ["DUP00000", "A", "01", "1"],
            ["DUP00000", "A", "01", "-1"],
            ["ORPHAN00", "A", "02", "1.5"],
            ["BAD00000", "", "", "NaN"],
        )
        issues = "\n".join(validate_data(details, locations))
        for expected in ("Duplicate catalog code", "ONLYCAT0", "ORPHAN00", "invalid quantities", "duplicate box and bag", "missing description", "missing code, box"):
            self.assertIn(expected, issues)
        self.assertIn("provisional count", issues)

    def test_load_preserves_codes_and_zero_padded_locations_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog({"code": " 001.0000 ", "description": " text "}).to_csv(root / "details.csv", index=False)
            stock(["001.0000", "A", "01", "1"]).to_csv(root / "locations.csv", index=False)
            before = {path.name: path.read_bytes() for path in root.iterdir()}
            details, locations = load_data(root)
            self.assertEqual(details.iloc[0].code, "001.0000")
            self.assertEqual(details.iloc[0].description, "text")
            self.assertEqual(locations.iloc[0].sublocation, "01")
            self.assertEqual(before, {path.name: path.read_bytes() for path in root.iterdir()})

    def test_missing_columns_raise_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "details.csv").write_text("code\nITEM0000\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "details.csv: missing columns"):
                load_data(tmp)

    def test_legacy_provisional_notes_still_raise_english_warning(self):
        details = catalog({"code": "TEST1026", "info": "Conteo provisional: 2 unidades"})
        issues = validate_data(details, stock())
        self.assertIn("TEST1026: provisional count; verify quantities with a physical count and update the record note.", issues)


if __name__ == "__main__":
    unittest.main()
