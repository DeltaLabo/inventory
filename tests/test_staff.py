import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts.staff import StaffDirectoryError, _load_staff, parse_staff, directory_settings
from scripts.github_inventory import GitHubError, MOVEMENT_COLUMNS, read_rows, write_rows
from test_github_inventory import MemoryGitHub


class AssistantTests(unittest.TestCase):
    def test_staff_settings_override_legacy_directory_settings(self):
        with patch.dict(os.environ, {"STAFF_TOKEN": "new-read-only", "STAFF_REPOSITORY": "DeltaLabo/staff",
                                    "STAFF_BRANCH": "main", "ASSISTANTS_TOKEN": "old-test",
                                    "ASSISTANTS_REPOSITORY": "DeltaLabo/assistants"}), \
             patch("scripts.staff.st.secrets", {}):
            self.assertEqual(directory_settings(), ("new-read-only", "DeltaLabo/staff", "main"))

    def test_directory_uses_pinned_legacy_fallback_only_when_staff_csv_is_absent(self):
        _load_staff.clear()
        self.addCleanup(_load_staff.clear)
        with patch("scripts.github_inventory.GitHubInventory") as factory:
            client = factory.return_value
            client.head.return_value = "pinned"
            client.read_file.side_effect = [None, "id,nombre\nTEST00,Test Intern\n"]
            self.assertEqual(_load_staff("test-only", "DeltaLabo/assistants", "main"), (("TEST00", "Test Intern"),))
            self.assertEqual([call.args for call in client.read_file.call_args_list],
                             [("data/input/staff.csv", "pinned"), ("data/input/assistants.csv", "pinned")])

    def test_legacy_directory_configuration_follows_the_renamed_repository(self):
        with patch.dict(os.environ, {"ASSISTANTS_TOKEN": "test-read-only", "ASSISTANTS_REPOSITORY": "DeltaLabo/assistants",
                                   "ASSISTANTS_BRANCH": "main", "ADMINISTRATION_REPOSITORY": "DeltaLabo/administration"}), \
             patch("scripts.staff.st.secrets", {}):
            self.assertEqual(directory_settings(), ("test-read-only", "DeltaLabo/staff", "main"))

    def test_repository_rename_handles_new_settings_and_preserves_custom_repositories(self):
        for repository, expected in ((" DeltaLabo/Assistants ", "DeltaLabo/staff"),
                                     ("OtherOrg/assistants", "OtherOrg/assistants"),
                                     ("DeltaLabo/custom-staff", "DeltaLabo/custom-staff")):
            with self.subTest(repository=repository), \
                 patch.dict(os.environ, {"STAFF_TOKEN": "test-only", "STAFF_REPOSITORY": repository,
                                         "STAFF_BRANCH": "directory"}, clear=True), \
                 patch("scripts.staff.st.secrets", {}):
                self.assertEqual(directory_settings(), ("test-only", expected, "directory"))

    def test_legacy_streamlit_secrets_follow_the_renamed_repository(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("scripts.staff.st.secrets", {"ASSISTANTS_TOKEN": "test-only",
                                               "ASSISTANTS_REPOSITORY": "DeltaLabo/assistants"}):
            self.assertEqual(directory_settings(), ("test-only", "DeltaLabo/staff", "main"))

    def test_directory_keeps_only_names_and_ids_and_preserves_accents(self):
        result = parse_staff("\ufeffid,nombre,cuenta,e-mail\nB00,Zoé Example,PRIVATE-ACCOUNT,private@example.com\nA00,Álex Sample,OTHER-ACCOUNT,other@example.com\n")
        self.assertEqual(set(result), {("B00", "Zoé Example"), ("A00", "Álex Sample")})
        self.assertNotIn("ACCOUNT", repr(result))
        self.assertNotIn("@", repr(result))

    def test_invalid_or_ambiguous_directories_are_rejected(self):
        for text in ("id,name\nA00,Example\n", "id,nombre\n", "id,nombre\nA00,\n", "id,nombre\nA00,Example\nA00,Other\n"):
            with self.subTest(text=text), self.assertRaises(StaffDirectoryError):
                parse_staff(text)

    def test_private_directory_uses_authenticated_api_and_does_not_cache_other_fields(self):
        _load_staff.clear()
        self.addCleanup(_load_staff.clear)
        with patch("scripts.github_inventory.GitHubInventory") as factory:
            client = factory.return_value
            client.head.return_value = "snapshot-sha"
            client.read_file.return_value = "id,nombre,cuenta\nTEST00,Intern,PRIVATE-ACCOUNT\n"
            self.assertEqual(_load_staff("private-test-token", "DeltaLabo/assistants", "main"), (("TEST00", "Intern"),))
            factory.assert_called_once_with("private-test-token", "DeltaLabo/assistants", "main")
            client.read_file.assert_called_once_with("data/input/staff.csv", "snapshot-sha", optional=True)

    def test_unavailable_private_directory_has_actionable_error_without_secret(self):
        _load_staff.clear()
        self.addCleanup(_load_staff.clear)
        with patch("scripts.github_inventory.GitHubInventory.head", side_effect=GitHubError("private-token")):
            with self.assertRaises(StaffDirectoryError) as error:
                _load_staff("private-token", "DeltaLabo/assistants", "main")
            self.assertNotIn("private-token", str(error.exception))
        with self.assertRaisesRegex(StaffDirectoryError, "STAFF_TOKEN"):
            _load_staff("", "DeltaLabo/assistants", "main")

    def test_withdrawal_rejects_unknown_ids_and_mismatched_names_before_writing(self):
        db = MemoryGitHub()
        with patch("scripts.staff.load_staff", return_value=(("TEST00", "Intern"),)):
            for code, name in ((None, "Intern"), ("UNKNOWN", "Intern"), ("TEST00", "Wrong name")):
                with self.subTest(code=code, name=name), self.assertRaises(StaffDirectoryError):
                    db.withdraw(uuid4().hex, "ITEM0001", "A", "01", 1, name, "Robot", assistant_id=code)
        self.assertEqual(db.refs["main"], "initial")

    def test_edit_requires_a_registered_id_and_name_and_recovers_saved_retries(self):
        db = MemoryGitHub()
        original = db.snapshot()[0].iloc[0].to_dict()
        updated = {"description": "Verified board"}
        operation = uuid4().hex
        with patch("scripts.staff.load_staff", return_value=(("TEST00", "Intern"),)):
            for code, name in ((None, "Intern"), ("UNKNOWN", "Intern"), ("TEST00", "Wrong name")):
                with self.subTest(code=code), self.assertRaises(StaffDirectoryError):
                    db.edit(operation, "ITEM0001", original, updated, name, "Checked", assistant_id=code)
            self.assertEqual(db.refs["main"], "initial")
            result = db.edit(operation, "ITEM0001", original, updated, "Intern", "Checked", assistant_id="TEST00")
        parent = db.refs["main"]
        with patch("scripts.staff.load_staff", side_effect=AssertionError("Saved retries must not need directory access")):
            self.assertEqual(db.edit(operation, "ITEM0001", original, updated, "Intern", "Checked", assistant_id="TEST00"), result)
        self.assertEqual(db.refs["main"], parent)

    def test_old_history_keeps_its_names_and_new_records_add_assistant_ids(self):
        db = MemoryGitHub()
        old = dict.fromkeys(MOVEMENT_COLUMNS, "") | {"id": uuid4().hex, "person": "Old initials", "quantity": "1"}
        db.main_files["data/movements.csv"] = write_rows(MOVEMENT_COLUMNS, [old])
        operation = uuid4().hex
        with patch("scripts.staff.load_staff", return_value=(("TEST00", "Intern"),)):
            db.withdraw(operation, "ITEM0001", "A", "01", 1, "Intern", "Robot", assistant_id="TEST00")
        rows = db.withdrawal_snapshot()
        self.assertEqual({key: rows[0][key] for key in old}, old)
        self.assertEqual(rows[0]["assistant_id"], "")
        self.assertEqual(rows[1]["assistant_id"], "TEST00")
        with patch("scripts.staff.load_staff", side_effect=AssertionError("Saved retries must not need directory access")):
            self.assertEqual(db.withdraw(operation, "ITEM0001", "A", "01", 1, "Intern", "Robot", assistant_id="TEST00"), 4)
