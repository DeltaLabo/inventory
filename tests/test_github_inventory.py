import base64
from copy import deepcopy
from datetime import datetime
import json
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import requests

from github_inventory import (
    Conflict, GitHubError, GitHubInventory, MOVEMENT_COLUMNS, new_product_code, read_rows, write_rows,
)
from inventory import DETAIL_COLUMNS, LOCATION_COLUMNS


class MemoryGitHub(GitHubInventory):
    """A fake Git object store; no test accesses a real repository."""

    def __init__(self):
        super().__init__("test-only-token")
        detail = dict.fromkeys(DETAIL_COLUMNS, "") | {
            "code": "ITEM0001", "type": "board", "subtype": "dev", "description": "Test board",
        }
        self.files = {
            "details.csv": write_rows(DETAIL_COLUMNS, [detail]),
            "locations.csv": write_rows(LOCATION_COLUMNS, [
                dict(zip(LOCATION_COLUMNS, ["ITEM0001", "A", "01", "5", "5"])),
                dict(zip(LOCATION_COLUMNS, ["ITEM0001", "A", "02", "3", "3"])),
            ]),
        }
        self.commits = {"initial": {"files": deepcopy(self.files), "parent": None}}
        self.refs = {"main": "initial"}
        self.tags = {}
        self.trees = {}
        self.prs = {}
        self.serial = 0
        self.before_patch = None
        self.timeout_after_patch = False
        self.timeout_after_pr = False

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
            branch = payload["ref"].removeprefix("refs/heads/")
            if branch in self.refs:
                raise Conflict("branch exists")
            self.refs[branch] = payload["sha"]
            return {}
        if method == "GET" and path == "/pulls":
            return [self.prs[params["head"]]] if params["head"] in self.prs else []
        if method == "POST" and path == "/pulls":
            key = "DeltaLabo:" + payload["head"]
            self.prs[key] = {"html_url": f"https://github.com/DeltaLabo/inventory/pull/{len(self.prs) + 1}"}
            if self.timeout_after_pr:
                self.timeout_after_pr = False
                raise GitHubError("response lost")
            return self.prs[key]
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

    def stock(self):
        return read_rows(self.db.main_files["locations.csv"], LOCATION_COLUMNS)[1]

    def history(self):
        return read_rows(self.db.main_files["movements.csv"], MOVEMENT_COLUMNS)[1]

    def withdraw(self, quantity=2, request_id=None, person="Intern"):
        return self.db.withdraw(request_id or self.request_id, "ITEM0001", "A", "01", quantity, person)

    def test_withdrawal_updates_only_selected_location_and_commits_history_together(self):
        self.assertEqual(self.withdraw(), 3)
        self.assertEqual([row["available"] for row in self.stock()], ["3", "3"])
        self.assertEqual([row["units"] for row in self.stock()], ["5", "3"])
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.history()[0]["quantity"], "2")
        self.assertEqual(self.history()[0]["sublocation"], "01")
        self.assertTrue(self.history()[0]["timestamp"].endswith("+00:00"))
        self.assertNotIn("movements.csv", self.db.commits["initial"]["files"])

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
        with self.assertRaisesRegex(ValueError, "otros datos"):
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
        self.assertEqual(self.stock()[0]["available"], "1")

    def test_concurrent_change_rechecks_available_stock(self):
        self.db.before_patch = lambda: self.withdraw(4, uuid4().hex, "Other intern")
        with self.assertRaisesRegex(ValueError, "Solo hay 1"):
            self.withdraw()
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.stock()[0]["available"], "1")

    def test_ambiguous_products_and_duplicate_locations_are_rejected(self):
        original = self.db.main_files["details.csv"]
        columns, rows = read_rows(original, DETAIL_COLUMNS)
        self.db.main_files["details.csv"] = write_rows(columns, rows + rows)
        with self.assertRaisesRegex(ValueError, "ambiguo"):
            self.withdraw()
        self.db.main_files["details.csv"] = original
        columns, rows = read_rows(self.db.main_files["locations.csv"], LOCATION_COLUMNS)
        self.db.main_files["locations.csv"] = write_rows(columns, rows + [rows[0]])
        with self.assertRaisesRegex(ValueError, "duplicada"):
            self.withdraw()
        self.assertEqual(len(self.db.commits), 1)

    def propose(self, existing_code=None):
        return self.db.propose_addition(
            self.request_id, {"description": "A new sensor", "type": "sensor", "subtype": "light"},
            2, "B", "02", "Intern", existing_code=existing_code,
        )

    def test_new_product_gets_generated_id_and_only_changes_review_branch(self):
        before = deepcopy(self.db.main_files)
        url = self.propose()
        self.assertTrue(url.startswith("https://github.com/DeltaLabo/inventory/pull/"))
        self.assertEqual(self.db.main_files, before)
        branch = f"inventory/add-{self.request_id}"
        files = self.db.commits[self.db.refs[branch]]["files"]
        details = read_rows(files["details.csv"], DETAIL_COLUMNS)[1]
        code = details[-1]["code"]
        self.assertRegex(code, r"^[A-Z]{4}[0-9]{4}$")
        self.assertIn("inventory-ids/" + code, self.db.tags)
        self.assertEqual(read_rows(files["locations.csv"], LOCATION_COLUMNS)[1][-1]["code"], code)
        self.assertEqual(json.loads(files[f"requests/{self.request_id}.json"])["person"], "Intern")

    def test_existing_product_reuses_id_and_keeps_catalog_unchanged(self):
        self.propose("ITEM0001")
        files = self.db.commits[self.db.refs[f"inventory/add-{self.request_id}"]]["files"]
        self.assertEqual(files["details.csv"], self.db.main_files["details.csv"])
        row = read_rows(files["locations.csv"], LOCATION_COLUMNS)[1][-1]
        self.assertEqual(row["code"], "ITEM0001")
        self.assertEqual(row["available"], "2")
        self.assertEqual(self.db.tags, {})

    def test_code_uses_registration_month_year_and_retries_catalog_collision(self):
        with patch("github_inventory.secrets.choice", side_effect=list("AAAABBBB")):
            self.assertEqual(new_product_code({"AAAA1026"}, datetime(2026, 10, 22)), "BBBB1026")
        with patch("github_inventory.secrets.choice", return_value="C"):
            self.assertEqual(new_product_code(set(), datetime(2026, 11, 1)), "CCCC1126")

    def test_pending_request_codes_are_reserved_before_approval(self):
        self.db.tags["inventory-ids/AAAA1026"] = "initial"
        with patch("github_inventory.new_product_code", side_effect=["AAAA1026", "BBBB1026"]):
            self.propose()
        files = self.db.commits[self.db.refs[f"inventory/add-{self.request_id}"]]["files"]
        self.assertEqual(read_rows(files["details.csv"], DETAIL_COLUMNS)[1][-1]["code"], "BBBB1026")
        self.assertEqual(self.db.refs["main"], "initial")
        self.assertIn("inventory-ids/BBBB1026", self.db.tags)

    def test_pr_timeout_recovers_same_request(self):
        self.db.timeout_after_pr = True
        with self.assertRaises(GitHubError):
            self.propose()
        url = self.propose()
        self.assertEqual(len(self.db.prs), 1)
        self.assertEqual(self.propose(), url)
        self.assertEqual(len(self.db.commits), 2)

    def test_existing_location_addition_only_increases_review_branch_stock(self):
        self.db.propose_addition(self.request_id, {}, 2, "A", "01", "Intern", existing_code="ITEM0001")
        files = self.db.commits[self.db.refs[f"inventory/add-{self.request_id}"]]["files"]
        rows = read_rows(files["locations.csv"], LOCATION_COLUMNS)[1]
        self.assertEqual((rows[0]["units"], rows[0]["available"]), ("7", "7"))
        self.assertEqual(self.stock()[0]["available"], "5")

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

    def propose_edit(self, updated=None, original_stock=None, updated_stock=None):
        original = read_rows(self.db.commits["initial"]["files"]["details.csv"], DETAIL_COLUMNS)[1][0]
        return self.db.propose_edit(
            self.request_id, "ITEM0001", original,
            {"description": "Corrected board"} if updated is None else updated,
            "Intern", "Verified label", original_stock, updated_stock,
        )

    def edit_files(self):
        return self.db.commits[self.db.refs[f"inventory/edit-{self.request_id}"]]["files"]

    def test_edit_preserves_id_and_proposes_only_changed_catalog_fields(self):
        before = deepcopy(self.db.main_files)
        self.propose_edit()
        self.assertEqual(self.db.main_files, before)
        files = self.edit_files()
        self.assertEqual(files["locations.csv"], before["locations.csv"])
        row = read_rows(files["details.csv"], DETAIL_COLUMNS)[1][0]
        self.assertEqual((row["code"], row["description"]), ("ITEM0001", "Corrected board"))
        receipt = json.loads(files[f"requests/{self.request_id}.json"])
        self.assertEqual(receipt["product_changes"]["description"]["before"], "Test board")
        self.assertEqual(receipt["reason"], "Verified label")

    def test_edit_quantity_and_location_leaves_other_location_and_history_alone(self):
        original = self.stock()[0].copy()
        self.propose_edit({}, original, {"location": "B", "units": 4, "available": 3})
        files = self.edit_files()
        rows = read_rows(files["locations.csv"], LOCATION_COLUMNS)[1]
        self.assertEqual((rows[0]["location"], rows[0]["units"], rows[0]["available"]), ("B", "4", "3"))
        self.assertEqual(rows[1], self.stock()[1])
        self.assertNotIn("movements.csv", files)
        self.assertEqual(self.db.refs["main"], "initial")

    def test_edit_rejects_changed_id_invalid_balances_destination_collision_and_noop(self):
        original = self.stock()[0].copy()
        cases = [
            ({"code": "OTHER000"}, None, None),
            ({}, original, {"units": 1, "available": 2}),
            ({}, original, {"units": -1}),
            ({}, original, {"sublocation": "02"}),
            ({}, None, None),
        ]
        for updated, original_stock, updated_stock in cases:
            with self.subTest(updated=updated, stock=updated_stock), self.assertRaises(ValueError):
                self.propose_edit(updated, original_stock, updated_stock)
        self.assertEqual(len(self.db.commits), 1)

    def test_edit_rejects_stale_balance_instead_of_overwriting_a_withdrawal(self):
        original = self.stock()[0].copy()
        self.withdraw()
        with self.assertRaisesRegex(ValueError, "existencias cambiaron"):
            self.propose_edit({}, original, {"available": 4})
        self.assertEqual(self.stock()[0]["available"], "3")
        self.assertEqual(len(self.db.prs), 0)

    def test_edit_does_not_overwrite_unchanged_fields_from_a_stale_form(self):
        original = self.stock()[0].copy()
        self.withdraw()
        self.propose_edit({}, original, {"units": 6, "available": 5})
        row = read_rows(self.edit_files()["locations.csv"], LOCATION_COLUMNS)[1][0]
        self.assertEqual((row["units"], row["available"]), ("6", "3"))

    def test_edit_timeout_recovers_same_review_request(self):
        self.db.timeout_after_pr = True
        with self.assertRaises(GitHubError):
            self.propose_edit()
        url = self.propose_edit()
        self.assertEqual(self.propose_edit(), url)
        self.assertEqual(len(self.db.prs), 1)


if __name__ == "__main__":
    unittest.main()
