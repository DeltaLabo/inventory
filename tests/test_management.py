import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts.github_inventory import GitHubError, read_rows, write_rows
from scripts.inventory import LOCATION_COLUMNS
from scripts.storage import removal_preview
from test_github_inventory import MemoryGitHub


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.db = MemoryGitHub()
        roster = patch("scripts.staff.load_staff", return_value=(("TEST00", "Intern"),))
        roster.start()
        self.addCleanup(roster.stop)

    def manage(self, action, target, expected=None, operation=None):
        return self.db.manage(operation or uuid4().hex, action, target, expected, "Intern", "Inventory cleanup", assistant_id="TEST00")

    def preview(self, action, target):
        return removal_preview(self.db.management_snapshot(), action, target)

    def test_empty_storage_can_be_created_without_devices_and_duplicate_bags_are_normalized(self):
        original_stock = self.db.main_files["data/locations.csv"]
        self.manage("add_box", {"location": "New box"})
        self.manage("add_bag", {"location": "New box", "sublocation": "003"})
        self.assertIn({"location": "New box", "sublocation": "3"}, self.db.storage_snapshot())
        self.assertEqual(self.db.main_files["data/locations.csv"], original_stock)
        for action, target in (("add_box", {"location": "A"}),
                               ("add_bag", {"location": "A", "sublocation": "1"}),
                               ("add_bag", {"location": "New box", "sublocation": "3"})):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, "already exists"):
                self.manage(action, target)

    def test_only_empty_boxes_and_bags_can_be_deleted_even_when_stock_is_zero(self):
        for units in ("5", "0", ""):
            self.db.main_files["data/locations.csv"] = write_rows(LOCATION_COLUMNS, [
                {"code": "ITEM0001", "location": "A", "sublocation": "01", "units": units}])
            for action, target in (("delete_box", {"location": "A"}),
                                   ("delete_bag", {"location": "A", "sublocation": "1"})):
                before = self.db.refs["main"]
                with self.subTest(units=units, action=action), self.assertRaisesRegex(ValueError, "Only empty"):
                    self.manage(action, target, self.preview(action, target))
                self.assertEqual(self.db.refs["main"], before)

    def test_device_deletion_preserves_history_receipts_tags_and_empty_storage(self):
        historical = {"data/movements.csv": "historical ledger", "data/requests/old.json": "historical receipt"}
        self.db.main_files.update(historical)
        self.db.tags["inventory-ids/ITEM0001"] = "initial"
        action, target = "delete_product", {"code": "ITEM0001"}
        expected = self.preview(action, target)
        result = self.manage(action, target, expected)
        snapshot = self.db.management_snapshot()
        self.assertEqual(snapshot["details"], [])
        self.assertEqual(snapshot["locations"], [])
        self.assertIn({"location": "A", "sublocation": "01"}, snapshot["storage"])
        for path, text in historical.items():
            self.assertEqual(self.db.main_files[path], text)
        self.assertIn("inventory-ids/ITEM0001", self.db.tags)
        receipt = json.loads(self.db.main_files[f"data/requests/{result['id']}.json"])
        self.assertEqual(receipt["before"], expected)
        self.assertEqual(receipt["submission"]["assistant_id"], "TEST00")

    def test_remove_one_device_entry_keeps_catalog_and_other_slots_and_can_then_delete_empty_bag(self):
        target = {"code": "ITEM0001", "location": "A", "sublocation": "1"}
        self.manage("delete_stock", target, self.preview("delete_stock", target))
        snapshot = self.db.management_snapshot()
        self.assertEqual(len(snapshot["details"]), 1)
        self.assertEqual([row["sublocation"] for row in snapshot["locations"]], ["02"])
        target = {"location": "A", "sublocation": "01"}
        self.manage("delete_bag", target, self.preview("delete_bag", target))
        self.assertNotIn(target, self.db.storage_snapshot())
        self.assertIn({"location": "A", "sublocation": ""}, self.db.storage_snapshot())

    def test_deleting_empty_box_removes_its_bags_and_preserves_other_boxes(self):
        self.manage("add_box", {"location": "Empty"})
        self.manage("add_bag", {"location": "Empty", "sublocation": "0"})
        target = {"location": "Empty"}
        self.manage("delete_box", target, self.preview("delete_box", target))
        self.assertEqual({row["location"] for row in self.db.storage_snapshot()}, {"A"})

    def test_concurrent_withdrawal_after_preview_prevents_device_removal(self):
        target = {"code": "ITEM0001"}
        expected = self.preview("delete_product", target)
        self.db.before_patch = lambda: self.db.withdraw(uuid4().hex, "ITEM0001", "A", "01", 1, "Intern", "Project", assistant_id="TEST00")
        with self.assertRaisesRegex(ValueError, "changed after the preview"):
            self.manage("delete_product", target, expected)
        self.assertEqual(self.db.management_snapshot()["locations"][0]["units"], "4")
        self.assertEqual(len(self.db.management_snapshot()["details"]), 1)

    def test_concurrent_addition_to_empty_box_prevents_box_removal(self):
        self.manage("add_box", {"location": "Empty"})
        target = {"location": "Empty"}
        expected = self.preview("delete_box", target)

        def add_stock():
            rows = self.db.management_snapshot()["locations"]
            rows.append({"code": "ITEM0001", "location": "Empty", "sublocation": "1", "units": "2"})
            parent = self.db.head()
            self.db.refs["main"] = self.db._commit(parent, {"data/locations.csv": write_rows(LOCATION_COLUMNS, rows)}, "Concurrent addition")

        self.db.before_patch = add_stock
        with self.assertRaisesRegex(ValueError, "changed after the preview"):
            self.manage("delete_box", target, expected)
        self.assertIn("Empty", {row["location"] for row in self.db.management_snapshot()["storage"]})

    def test_unrelated_concurrent_change_is_preserved(self):
        target = {"code": "ITEM0001"}
        expected = self.preview("delete_product", target)
        self.db.before_patch = lambda: self.manage("add_box", {"location": "Concurrent box"})
        self.manage("delete_product", target, expected)
        self.assertIn({"location": "Concurrent box", "sublocation": ""}, self.db.storage_snapshot())

    def test_uncertain_write_recovers_without_staff_access_and_changed_payload_is_rejected(self):
        operation = uuid4().hex
        target = {"code": "ITEM0001"}
        expected = self.preview("delete_product", target)
        self.db.timeout_after_patch = True
        with self.assertRaises(GitHubError):
            self.manage("delete_product", target, expected, operation)
        parent = self.db.head()
        with patch("scripts.staff.load_staff", side_effect=AssertionError("No roster needed for saved retries")):
            self.manage("delete_product", target, expected, operation)
        self.assertEqual(self.db.head(), parent)
        with self.assertRaisesRegex(ValueError, "different details"):
            self.manage("delete_product", target, {}, operation)

    def test_missing_preview_invalid_staff_and_missing_reason_never_write(self):
        target = {"code": "ITEM0001"}
        for preview in (None, {}):
            with self.assertRaisesRegex(ValueError, "preview"):
                self.manage("delete_product", target, preview)
        with self.assertRaises(ValueError):
            self.db.manage(uuid4().hex, "add_box", {"location": "New"}, None, "Wrong name", "Reason", assistant_id="TEST00")
        with self.assertRaises(ValueError):
            self.db.manage(uuid4().hex, "add_box", {"location": "New"}, None, "Intern", "", assistant_id="TEST00")
        self.assertEqual(self.db.head(), "initial")
