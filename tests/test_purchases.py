import csv
from copy import deepcopy
from io import StringIO
import unittest
from uuid import uuid4

from scripts.github_inventory import GitHubError, PURCHASE_COLUMNS, read_rows
from scripts.purchases import quotation_csv
from test_github_inventory import MemoryGitHub


class PurchaseTests(unittest.TestCase):
    def setUp(self):
        self.db = MemoryGitHub()
        self.request_id = uuid4().hex
        self.values = dict(description="Sensor", quantity=2, project="Robot", person="Intern",
                           link="https://www.amazon.com/dp/EXAMPLE?variant=2", manufacturer="Acme", model="Two-channel", notes="5 V")

    def submit(self, **changes):
        return self.db.request_purchase(self.request_id, **(self.values | changes))

    def rows(self):
        return read_rows(self.db.main_files["data/purchase_requests.csv"], PURCHASE_COLUMNS)[1]

    def test_request_persists_all_details_without_changing_stock(self):
        before = deepcopy(self.db.main_files)
        self.assertEqual(self.submit(), self.request_id)
        row = self.rows()[0]
        for key, value in self.values.items():
            self.assertEqual(row[key], str(value))
        self.assertTrue(row["timestamp"].endswith("+00:00"))
        for name, text in before.items():
            self.assertEqual(self.db.main_files[name], text)
        self.assertEqual(self.db.purchase_snapshot(), self.rows())
        self.assertEqual(self.db.prs, {})

    def test_required_fields_and_invalid_links_never_write(self):
        for changes in ({"description": ""}, {"project": " "}, {"person": ""}, {"quantity": 0},
                        {"quantity": 1.5}, {"link": ""}, {"link": "amazon.com/item"},
                        {"link": "javascript:alert(1)"}, {"link": "file:///tmp/item"},
                        {"link": "https://user:password@store.com/item"},
                        {"link": "https://store.com/item with spaces"},
                        {"link": "https://store.com:bad/item"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.submit(**changes)
        self.assertEqual(self.db.refs["main"], "initial")

    def test_same_request_recovers_after_uncertain_write_without_duplication(self):
        self.db.timeout_after_patch = True
        with self.assertRaises(GitHubError):
            self.submit()
        head = self.db.refs["main"]
        self.assertEqual(self.submit(), self.request_id)
        self.assertEqual(self.db.refs["main"], head)
        self.assertEqual(len(self.rows()), 1)
        with self.assertRaisesRegex(ValueError, "different details"):
            self.submit(quantity=3)

    def test_concurrent_requests_preserve_both_projects(self):
        other_id = uuid4().hex
        self.db.before_patch = lambda: self.db.request_purchase(other_id, **(self.values | {"project": "Weather station", "quantity": 4}))
        self.submit()
        rows = self.rows()
        self.assertEqual([row["id"] for row in rows], [other_id, self.request_id])
        self.assertEqual([row["project"] for row in rows], ["Weather station", "Robot"])
        self.assertEqual([row["quantity"] for row in rows], ["4", "2"])
        self.assertEqual(rows[0]["link"], rows[1]["link"])

    def test_full_export_preserves_projects_links_and_requesters_and_escapes_formulas(self):
        self.submit(description='=HYPERLINK("https://example.com")')
        data = quotation_csv(self.rows())
        rows = list(csv.DictReader(StringIO(data.decode("utf-8-sig"))))
        self.assertEqual(rows[0]["Project"], "Robot")
        self.assertEqual(rows[0]["Requested by"], "Intern")
        self.assertEqual(rows[0]["Product link"], self.values["link"])
        self.assertEqual(rows[0]["Quantity"], "2")
        self.assertTrue(rows[0]["Description"].startswith("'="))
        self.assertEqual(len(list(csv.reader(StringIO(quotation_csv([]).decode("utf-8-sig"))))), 1)

    def test_missing_purchase_file_is_an_empty_list(self):
        self.assertEqual(self.db.purchase_snapshot(), [])
