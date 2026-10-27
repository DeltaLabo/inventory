import base64
from copy import deepcopy
from datetime import datetime
import json
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import requests

from scripts.github_inventory import (
    Conflict, GitHubError, GitHubInventory, MOVEMENT_COLUMNS, new_product_code, read_rows, write_rows,
)
from scripts.inventory import DETAIL_COLUMNS, LOCATION_COLUMNS


class MemoryGitHub(GitHubInventory):
    """A fake Git object store; no test accesses a real repository."""

    def __init__(self):
        super().__init__("test-only-token")
        detail = dict.fromkeys(DETAIL_COLUMNS, "") | {
            "code": "ITEM0001", "type": "board", "subtype": "dev", "description": "Test board",
        }
        self.files = {
            "data/details.csv": write_rows(DETAIL_COLUMNS, [detail]),
            "data/locations.csv": write_rows(LOCATION_COLUMNS, [
                dict(zip(LOCATION_COLUMNS, ["ITEM0001", "A", "01", "5"])),
                dict(zip(LOCATION_COLUMNS, ["ITEM0001", "A", "02", "3"])),
            ]),
        }
        self.commits = {"initial": {"files": deepcopy(self.files), "parent": None}}
        self.refs = {"main": "initial"}
        self.tags = {}
        self.trees = {}
        self.serial = 0
        self.before_patch = None
        self.timeout_after_patch = False

    @property
    def main_files(self):
        return self.commits[self.refs["main"]]["files"]

    def _request(self, method, path, *, payload=None, params=None, optional=False):
        self.serial += 1
        if method == "GET" and path.startswith("/git/ref/heads/"):
            branch = path.removeprefix("/git/ref/heads/")
            if optional and branch not in self.refs:
                return None
            return {"object": {"sha": self.refs[branch]}}
        if method == "GET" and path.startswith("/git/ref/tags/"):
            tag = path.removeprefix("/git/ref/tags/")
            if optional and tag not in self.tags:
                return None
            return {"object": {"sha": self.tags[tag]}}
        if method == "GET" and path.startswith("/contents/"):
            text = self.commits[params["ref"]]["files"].get(path.removeprefix("/contents/"))
            if text is None and optional:
                return None
            return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}
        if method == "GET" and path.startswith("/git/commits/"):
            return {"tree": {"sha": path.removeprefix("/git/commits/")}}
        if method == "POST" and path == "/git/trees":
            key = f"tree-{self.serial}"
            files = deepcopy(self.commits[payload["base_tree"]]["files"])
            files.update({entry["path"]: entry["content"] for entry in payload["tree"]})
            self.trees[key] = files
            return {"sha": key}
        if method == "POST" and path == "/git/commits":
            key = f"commit-{self.serial}"
            self.commits[key] = {"files": self.trees[payload["tree"]], "parent": payload["parents"][0]}
            return {"sha": key}
        if method == "POST" and path == "/git/refs":
            if payload["ref"].startswith("refs/tags/"):
                tag = payload["ref"].removeprefix("refs/tags/")
                if tag in self.tags:
                    raise Conflict("tag exists")
                self.tags[tag] = payload["sha"]
                return {}
        if method == "PATCH" and path.startswith("/git/refs/heads/"):
            if self.before_patch:
                callback, self.before_patch = self.before_patch, None
                callback()
            branch = path.removeprefix("/git/refs/heads/")
            if payload["force"] or self.commits[payload["sha"]]["parent"] != self.refs[branch]:
                raise Conflict("stale commit")
            self.refs[branch] = payload["sha"]
            if self.timeout_after_patch:
                self.timeout_after_patch = False
                raise GitHubError("response lost")
            return {}
        raise AssertionError(f"Unexpected request: {method} {path}")


class GitHubInventoryTests(unittest.TestCase):
    def setUp(self):
        self.db = MemoryGitHub()
        self.request_id = uuid4().hex
        roster = patch("scripts.staff.load_staff", return_value=(("TEST00", "Intern"), ("OTHER00", "Other intern")))
        roster.start()
        self.addCleanup(roster.stop)

    def stock(self):
        return read_rows(self.db.main_files["data/locations.csv"], LOCATION_COLUMNS)[1]

    def test_legacy_withdrawal_uses_available_not_lifetime_units_and_normalizes_schema(self):
        self.db.main_files["data/locations.csv"] = "code,location,sublocation,units,available\nITEM0001,A,01,10,3\nITEM0001,A,02,8,0\n"
        with self.assertRaisesRegex(ValueError, "Only 3"):
            self.withdraw(4)
        self.assertEqual(self.withdraw(2), 1)
        self.assertEqual([row["units"] for row in self.stock()], ["1", "0"])
        self.assertEqual(self.db.main_files["data/locations.csv"].splitlines()[0], "code,location,sublocation,units")
        self.assertEqual(self.history()[0]["available_after"], "1")

    def test_legacy_restock_adds_to_remaining_units_only(self):
        self.db.main_files["data/locations.csv"] = "code,location,sublocation,units,available\nITEM0001,A,01,10,3\n"
        self.add("ITEM0001")
        files = self.db.main_files
        self.assertEqual(read_rows(files["data/locations.csv"], LOCATION_COLUMNS)[1][0]["units"], "5")
        self.assertEqual(files["data/locations.csv"].splitlines()[0], "code,location,sublocation,units")
        self.assertEqual(self.stock()[0]["units"], "5")

    def test_old_edit_form_cannot_apply_lifetime_units_as_current_stock(self):
        original = self.stock()[0] | {"available": "3"}
        with self.assertRaisesRegex(ValueError, "stock format changed"):
            self.edit({}, original, {"units": 8})
        self.assertEqual(self.db.refs["main"], "initial")

    def history(self):
        return read_rows(self.db.main_files["data/movements.csv"], MOVEMENT_COLUMNS)[1]

    def withdraw(self, quantity=2, request_id=None, person="Intern"):
        return self.db.withdraw(request_id or self.request_id, "ITEM0001", "A", "01", quantity, person, "Test project",
                                assistant_id="TEST00" if person == "Intern" else "OTHER00")

    def test_withdrawal_updates_only_selected_location_and_commits_history_together(self):
        self.assertEqual(self.withdraw(), 3)
        self.assertEqual([row["units"] for row in self.stock()], ["3", "3"])
        self.assertNotIn("available", self.stock()[0])
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.history()[0]["quantity"], "2")
        self.assertEqual(self.history()[0]["sublocation"], "01")
        self.assertEqual(self.history()[0]["assistant_id"], "TEST00")
        self.assertTrue(self.history()[0]["timestamp"].endswith("+00:00"))
        self.assertNotIn("data/movements.csv", self.db.commits["initial"]["files"])

    def test_overdraw_and_invalid_quantity_never_write(self):
        for quantity in (6, 0, -1, 1.5, True):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                self.withdraw(quantity)
        self.assertEqual(self.db.refs["main"], "initial")
        self.assertEqual(len(self.db.commits), 1)

    def test_repeated_submission_does_not_withdraw_twice(self):
        self.assertEqual(self.withdraw(), 3)
        parent = self.db.refs["main"]
        self.assertEqual(self.withdraw(), 3)
        self.assertEqual(self.db.refs["main"], parent)
        self.assertEqual(len(self.history()), 1)
        with self.assertRaisesRegex(ValueError, "different details"):
            self.withdraw(1)

    def test_timeout_after_saved_change_recovers_without_double_withdrawal(self):
        self.db.timeout_after_patch = True
        with self.assertRaises(GitHubError):
            self.withdraw()
        self.assertEqual(self.withdraw(), 3)
        self.assertEqual(len(self.history()), 1)

    def test_concurrent_withdrawals_preserve_both_records_and_balances(self):
        self.db.before_patch = lambda: self.withdraw(2, uuid4().hex, "Other intern")
        self.assertEqual(self.withdraw(), 1)
        self.assertEqual([row["quantity"] for row in self.history()], ["2", "2"])
        self.assertEqual(self.stock()[0]["units"], "1")

    def test_concurrent_change_rechecks_available_stock(self):
        self.db.before_patch = lambda: self.withdraw(4, uuid4().hex, "Other intern")
        with self.assertRaisesRegex(ValueError, "Only 1"):
            self.withdraw()
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.stock()[0]["units"], "1")

    def test_ambiguous_products_and_duplicate_locations_are_rejected(self):
        original = self.db.main_files["data/details.csv"]
        columns, rows = read_rows(original, DETAIL_COLUMNS)
        self.db.main_files["data/details.csv"] = write_rows(columns, rows + rows)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.withdraw()
        self.db.main_files["data/details.csv"] = original
        columns, rows = read_rows(self.db.main_files["data/locations.csv"], LOCATION_COLUMNS)
        self.db.main_files["data/locations.csv"] = write_rows(columns, rows + [rows[0]])
        with self.assertRaisesRegex(ValueError, "duplicated"):
            self.withdraw()
        self.assertEqual(len(self.db.commits), 1)

    def add(self, existing_code=None, request_id=None, quantity=2):
        return self.db.add(
            request_id or self.request_id, {"description": "A new sensor", "type": "sensor", "subtype": "light"},
            quantity, "A" if existing_code else "B", "01" if existing_code else "02", "Intern", existing_code=existing_code,
        )

    def edit(self, updated=None, original_stock=None, updated_stock=None):
        original = read_rows(self.db.commits["initial"]["files"]["data/details.csv"], DETAIL_COLUMNS)[1][0]
        return self.db.edit(self.request_id, "ITEM0001", original,
                            {"description": "Corrected board"} if updated is None else updated,
                            "Intern", "Verified label", original_stock, updated_stock, assistant_id="TEST00")

    def test_new_product_is_saved_atomically_without_pr_or_branch(self):
        before = deepcopy(self.db.main_files)
        result = self.add()
        code = result["code"]
        self.assertRegex(code, r"^[A-Z]{4}[0-9]{4}$")
        self.assertIn("inventory-ids/" + code, self.db.tags)
        self.assertEqual(list(self.db.refs), ["main"])
        details = read_rows(self.db.main_files["data/details.csv"], DETAIL_COLUMNS)[1]
        self.assertEqual(details[-1]["code"], code)
        self.assertEqual(self.stock()[-1]["code"], code)
        self.assertEqual(self.stock()[-1]["units"], "2")
        receipt = json.loads(self.db.main_files[f"data/requests/{self.request_id}.json"])
        self.assertEqual(receipt["status"], "applied")
        self.assertEqual(receipt["submission"]["person"], "Intern")
        parent = self.db.commits[self.db.refs["main"]]["parent"]
        self.assertEqual(self.db.commits[parent]["files"], before)

    def test_restock_reuses_id_and_only_increases_selected_location(self):
        catalog = self.db.main_files["data/details.csv"]
        self.add("ITEM0001")
        self.assertEqual(self.db.main_files["data/details.csv"], catalog)
        self.assertEqual([row["units"] for row in self.stock()], ["7", "3"])
        self.assertEqual(self.db.tags, {})

    def test_restock_does_not_create_a_different_location(self):
        with self.assertRaisesRegex(ValueError, "product box or bag changed"):
            self.db.add(self.request_id, {}, 2, "B", "99", "Intern", existing_code="ITEM0001")
        self.assertEqual(self.db.refs["main"], "initial")

    def test_code_uses_registration_month_year_and_retries_catalog_collision(self):
        with patch("scripts.github_inventory.secrets.choice", side_effect=list("AAAABBBB")):
            self.assertEqual(new_product_code({"AAAA1026"}, datetime(2026, 10, 22)), "BBBB1026")
        with patch("scripts.github_inventory.secrets.choice", return_value="C"):
            self.assertEqual(new_product_code(set(), datetime(2026, 11, 1)), "CCCC1126")

    def test_reserved_ids_are_not_reused(self):
        self.db.tags["inventory-ids/AAAA1026"] = "initial"
        with patch("scripts.github_inventory.new_product_code", side_effect=["AAAA1026", "BBBB1026"]):
            result = self.add()
        self.assertEqual(result["code"], "BBBB1026")
        self.assertIn("inventory-ids/BBBB1026", self.db.tags)

    def test_addition_timeout_recovers_same_record_without_double_stock_or_new_id(self):
        self.db.timeout_after_patch = True
        with self.assertRaises(GitHubError):
            self.add()
        parent = self.db.refs["main"]
        result = self.add()
        self.assertEqual(self.db.refs["main"], parent)
        self.assertEqual(len(self.stock()), 3)
        self.assertEqual(len(self.db.tags), 1)
        self.assertEqual(self.add(), result)
        with self.assertRaisesRegex(ValueError, "different details"):
            self.add(quantity=3)

    def test_concurrent_additions_accumulate_without_lost_updates(self):
        self.db.before_patch = lambda: self.add("ITEM0001", uuid4().hex)
        self.add("ITEM0001")
        self.assertEqual(self.stock()[0]["units"], "9")

    def test_addition_preserves_concurrent_withdrawal(self):
        self.db.before_patch = lambda: self.withdraw(2, uuid4().hex)
        self.add("ITEM0001")
        self.assertEqual(self.stock()[0]["units"], "5")
        self.assertEqual(len(self.history()), 1)

    def test_edit_preserves_id_and_writes_only_changed_fields_and_receipt(self):
        locations = self.db.main_files["data/locations.csv"]
        self.edit()
        row = read_rows(self.db.main_files["data/details.csv"], DETAIL_COLUMNS)[1][0]
        self.assertEqual((row["code"], row["description"]), ("ITEM0001", "Corrected board"))
        self.assertEqual(self.db.main_files["data/locations.csv"], locations)
        receipt = json.loads(self.db.main_files[f"data/requests/{self.request_id}.json"])
        self.assertEqual(receipt["request"]["product_changes"]["description"]["before"], "Test board")
        self.assertEqual(receipt["request"]["reason"], "Verified label")
        self.assertEqual(receipt["request"]["assistant_id"], "TEST00")

    def test_edit_quantity_and_location_preserves_other_location(self):
        original = self.stock()[0].copy()
        second = self.stock()[1].copy()
        self.edit({}, original, {"location": "B", "units": 3})
        self.assertEqual((self.stock()[0]["location"], self.stock()[0]["units"]), ("B", "3"))
        self.assertEqual(self.stock()[1], second)
        self.assertNotIn("data/movements.csv", self.db.main_files)

    def test_edit_rejects_changed_id_invalid_units_collision_and_noop(self):
        original = self.stock()[0].copy()
        for item, stock, values in [
            ({"code": "OTHER000"}, None, None), ({}, original, {"units": 1.5}),
            ({}, original, {"units": -1}), ({}, original, {"sublocation": "02"}), ({}, None, None),
        ]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.edit(item, stock, values)
        self.assertEqual(self.db.refs["main"], "initial")

    def test_edit_rejects_stale_balance_instead_of_overwriting_withdrawal(self):
        original = self.stock()[0].copy()
        self.withdraw(2, uuid4().hex)
        with self.assertRaisesRegex(ValueError, "Stock changed"):
            self.edit({}, original, {"units": 4})
        self.assertEqual(self.stock()[0]["units"], "3")

    def test_location_edit_preserves_unchanged_units_after_concurrent_withdrawal(self):
        original = self.stock()[0].copy()
        self.db.before_patch = lambda: self.withdraw(2, uuid4().hex)
        self.edit({}, original, {"location": "B", "units": 5})
        self.assertEqual((self.stock()[0]["location"], self.stock()[0]["units"]), ("B", "3"))

    def test_quantity_edit_rechecks_after_a_concurrent_withdrawal(self):
        original = self.stock()[0].copy()
        self.db.before_patch = lambda: self.withdraw(2, uuid4().hex)
        with self.assertRaisesRegex(ValueError, "Stock changed"):
            self.edit({}, original, {"units": 4})
        self.assertEqual(self.stock()[0]["units"], "3")

    def test_edit_timeout_recovers_same_saved_change(self):
        self.db.timeout_after_patch = True
        with self.assertRaises(GitHubError):
            self.edit()
        parent = self.db.refs["main"]
        result = self.edit()
        self.assertEqual(self.edit(), result)
        self.assertEqual(self.db.refs["main"], parent)

    def test_old_request_ids_are_not_reapplied(self):
        self.db.main_files[f"data/requests/{self.request_id}.json"] = json.dumps({"id": self.request_id, "code": "ITEM0001", "quantity": 2})
        with self.assertRaisesRegex(ValueError, "older request"):
            self.add("ITEM0001")
        self.assertEqual(self.stock()[0]["units"], "5")

    def test_api_errors_do_not_expose_response_or_token(self):
        db = GitHubInventory("private-token")
        response = Mock(status_code=403, text="private-token")
        with patch("requests.request", return_value=response) as call:
            with self.assertRaises(GitHubError) as error:
                db.head()
            self.assertNotIn("private-token", str(error.exception))
            self.assertEqual(call.call_args.kwargs["timeout"], (5, 20))
        with patch("requests.request", side_effect=requests.Timeout("private-token")):
            with self.assertRaises(GitHubError) as error:
                db.head()
            self.assertNotIn("private-token", str(error.exception))


if __name__ == "__main__":
    unittest.main()
