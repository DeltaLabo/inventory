from copy import deepcopy
import unittest
from unittest.mock import patch
from uuid import uuid4

import pandas as pd

from github_inventory import MOVEMENT_COLUMNS, write_rows
from test_github_inventory import MemoryGitHub
from withdrawal_history import history_frame, product_totals, project_rows


class WithdrawalHistoryTests(unittest.TestCase):
    def setUp(self):
        self.db = MemoryGitHub()
        self.details, _ = self.db.snapshot()
        roster = patch("assistants.load_assistants", return_value=(("TEST00", "Intern"),))
        roster.start()
        self.addCleanup(roster.stop)

    def withdraw(self, project, quantity=1):
        return self.db.withdraw(uuid4().hex, "ITEM0001", "A", "01", quantity, "Intern", project, assistant_id="TEST00")

    def test_history_is_separate_and_grouped_by_project_and_product(self):
        self.withdraw("Robot", 2)
        self.withdraw("Weather station")
        self.withdraw("Robot")
        before = deepcopy(self.db.main_files)
        frame = history_frame(self.db.withdrawal_snapshot(), self.details)
        self.assertEqual(len(frame), 3)
        self.assertEqual(frame["description"].tolist(), ["Test board"] * 3)
        self.assertEqual(product_totals(frame)["Total withdrawn"].tolist(), [3, 1])
        selected = project_rows(frame, "Robot")
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected["quantity"].sum(), 3)
        self.assertEqual(len(project_rows(frame)), 3)
        self.assertTrue(project_rows(frame, "Missing").empty)
        self.assertEqual(self.db.main_files, before)

    def test_missing_projects_and_products_are_preserved_without_multiplying_movements(self):
        row = dict.fromkeys(MOVEMENT_COLUMNS, "") | {
            "id": uuid4().hex, "code": "OLD_CODE", "quantity": "2", "timestamp": "2026-01-01T12:00:00+00:00",
        }
        self.db.main_files["movements.csv"] = write_rows(MOVEMENT_COLUMNS, [row])
        duplicate_details = pd.concat([self.details, self.details], ignore_index=True)
        frame = history_frame(self.db.withdrawal_snapshot(), duplicate_details)
        self.assertEqual(len(frame), 1)
        self.assertEqual(len(project_rows(frame, "")), 1)
        self.assertEqual(frame.iloc[0]["code"], "OLD_CODE")
        self.assertEqual(frame.iloc[0]["description"], "")
        self.assertEqual(product_totals(frame).iloc[0]["Total withdrawn"], 2)
        self.assertEqual(self.db.withdrawal_snapshot()[0], row)

    def test_new_withdrawals_require_project_without_changing_stock(self):
        with self.assertRaisesRegex(ValueError, "Project:"):
            self.withdraw(" ")
        self.assertEqual(self.db.refs["main"], "initial")

    def test_legacy_retry_without_project_recovers_existing_receipt(self):
        operation = uuid4().hex
        row = dict.fromkeys(MOVEMENT_COLUMNS, "") | {
            "id": operation, "code": "ITEM0001", "location": "A", "sublocation": "01",
            "quantity": "2", "person": "Intern", "available_after": "3",
        }
        self.db.main_files["movements.csv"] = write_rows(MOVEMENT_COLUMNS, [row])
        self.assertEqual(self.db.withdraw(operation, "ITEM0001", "A", "01", 2, "Intern"), 3)
        self.assertEqual(self.db.refs["main"], "initial")

    def test_missing_history_is_empty_and_invalid_quantities_are_not_silently_dropped(self):
        self.assertEqual(self.db.withdrawal_snapshot(), [])
        self.assertTrue(history_frame([], self.details).empty)
        with self.assertRaises(ValueError):
            history_frame([dict.fromkeys(MOVEMENT_COLUMNS, "") | {"quantity": "unknown"}], self.details)
