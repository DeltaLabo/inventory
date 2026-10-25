import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts.assistants import AssistantDirectoryError, _load_assistants, parse_assistants, directory_settings
from scripts.github_inventory import GitHubError, MOVEMENT_COLUMNS, read_rows, write_rows
from test_github_inventory import MemoryGitHub


class AssistantTests(unittest.TestCase):
    def test_directory_configuration_uses_assistants_not_the_former_administration_settings(self):
        with patch.dict(os.environ, {"ASSISTANTS_TOKEN": "test-read-only", "ASSISTANTS_REPOSITORY": "DeltaLabo/assistants",
                                   "ASSISTANTS_BRANCH": "main", "ADMINISTRATION_REPOSITORY": "DeltaLabo/administration"}), \
             patch("scripts.assistants.st.secrets", {}):
            self.assertEqual(directory_settings(), ("test-read-only", "DeltaLabo/assistants", "main"))

    def test_directory_keeps_only_names_and_ids_and_preserves_accents(self):
        result = parse_assistants("\ufeffid,nombre,cuenta,e-mail\nB00,Zoé Example,PRIVATE-ACCOUNT,private@example.com\nA00,Álex Sample,OTHER-ACCOUNT,other@example.com\n")
        self.assertEqual(set(result), {("B00", "Zoé Example"), ("A00", "Álex Sample")})
        self.assertNotIn("ACCOUNT", repr(result))
        self.assertNotIn("@", repr(result))

    def test_invalid_or_ambiguous_directories_are_rejected(self):
        for text in ("id,name\nA00,Example\n", "id,nombre\n", "id,nombre\nA00,\n", "id,nombre\nA00,Example\nA00,Other\n"):
            with self.subTest(text=text), self.assertRaises(AssistantDirectoryError):
                parse_assistants(text)

    def test_private_directory_uses_authenticated_api_and_does_not_cache_other_fields(self):
        _load_assistants.clear()
        self.addCleanup(_load_assistants.clear)
        with patch("scripts.github_inventory.GitHubInventory") as factory:
            client = factory.return_value
            client.head.return_value = "snapshot-sha"
            client.read_file.return_value = "id,nombre,cuenta\nTEST00,Intern,PRIVATE-ACCOUNT\n"
            self.assertEqual(_load_assistants("private-test-token", "DeltaLabo/assistants", "main"), (("TEST00", "Intern"),))
            factory.assert_called_once_with("private-test-token", "DeltaLabo/assistants", "main")
            client.read_file.assert_called_once_with("data/input/assistants.csv", "snapshot-sha")

    def test_unavailable_private_directory_has_actionable_error_without_secret(self):
        _load_assistants.clear()
        self.addCleanup(_load_assistants.clear)
        with patch("scripts.github_inventory.GitHubInventory.head", side_effect=GitHubError("private-token")):
            with self.assertRaises(AssistantDirectoryError) as error:
                _load_assistants("private-token", "DeltaLabo/assistants", "main")
            self.assertNotIn("private-token", str(error.exception))
        with self.assertRaisesRegex(AssistantDirectoryError, "ASSISTANTS_TOKEN"):
            _load_assistants("", "DeltaLabo/assistants", "main")

    def test_withdrawal_rejects_unknown_ids_and_mismatched_names_before_writing(self):
        db = MemoryGitHub()
        with patch("scripts.assistants.load_assistants", return_value=(("TEST00", "Intern"),)):
            for code, name in ((None, "Intern"), ("UNKNOWN", "Intern"), ("TEST00", "Wrong name")):
                with self.subTest(code=code, name=name), self.assertRaises(AssistantDirectoryError):
                    db.withdraw(uuid4().hex, "ITEM0001", "A", "01", 1, name, "Robot", assistant_id=code)
        self.assertEqual(db.refs["main"], "initial")

    def test_edit_requires_a_registered_id_and_name_and_recovers_saved_retries(self):
        db = MemoryGitHub()
        original = db.snapshot()[0].iloc[0].to_dict()
        updated = {"description": "Verified board"}
        operation = uuid4().hex
        with patch("scripts.assistants.load_assistants", return_value=(("TEST00", "Intern"),)):
            for code, name in ((None, "Intern"), ("UNKNOWN", "Intern"), ("TEST00", "Wrong name")):
                with self.subTest(code=code), self.assertRaises(AssistantDirectoryError):
                    db.edit(operation, "ITEM0001", original, updated, name, "Checked", assistant_id=code)
            self.assertEqual(db.refs["main"], "initial")
            result = db.edit(operation, "ITEM0001", original, updated, "Intern", "Checked", assistant_id="TEST00")
        parent = db.refs["main"]
        with patch("scripts.assistants.load_assistants", side_effect=AssertionError("Saved retries must not need directory access")):
            self.assertEqual(db.edit(operation, "ITEM0001", original, updated, "Intern", "Checked", assistant_id="TEST00"), result)
        self.assertEqual(db.refs["main"], parent)

    def test_old_history_keeps_its_names_and_new_records_add_assistant_ids(self):
        db = MemoryGitHub()
        old = dict.fromkeys(MOVEMENT_COLUMNS, "") | {"id": uuid4().hex, "person": "Old initials", "quantity": "1"}
        db.main_files["data/movements.csv"] = write_rows(MOVEMENT_COLUMNS, [old])
        operation = uuid4().hex
        with patch("scripts.assistants.load_assistants", return_value=(("TEST00", "Intern"),)):
            db.withdraw(operation, "ITEM0001", "A", "01", 1, "Intern", "Robot", assistant_id="TEST00")
        rows = db.withdrawal_snapshot()
        self.assertEqual({key: rows[0][key] for key in old}, old)
        self.assertEqual(rows[0]["assistant_id"], "")
        self.assertEqual(rows[1]["assistant_id"], "TEST00")
        with patch("scripts.assistants.load_assistants", side_effect=AssertionError("Saved retries must not need directory access")):
            self.assertEqual(db.withdraw(operation, "ITEM0001", "A", "01", 1, "Intern", "Robot", assistant_id="TEST00"), 4)
