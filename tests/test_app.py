import importlib.util
from contextlib import chdir
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Install requirements.txt to check the UI")
class AppTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "token": "", "repository": "DeltaLabo/inventory", "branch": "main",
            "add_password": "", "withdraw_password": "",
        }
        config_patch = patch("scripts.forms.settings", return_value=self.config)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        network_patch = patch("requests.request", side_effect=AssertionError("Tests must not access GitHub"))
        network_patch.start()
        self.addCleanup(network_patch.stop)
        roster_patch = patch("scripts.assistants.load_assistants", return_value=(("TEST00", "Intern"), ("OTHER00", "Other intern")))
        roster_patch.start()
        self.addCleanup(roster_patch.stop)

    def open_app(self):
        from streamlit.testing.v1 import AppTest

        return AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()

    def code_for(self, previous_code):
        from scripts.inventory import load_data

        details, _ = load_data(Path(__file__).resolve().parents[1] / "data")
        return details.loc[details["previous_code"].eq(previous_code), "code"].item()

    def test_app_opens_with_all_stock_and_no_image_requests(self):
        with patch("requests.head") as head:
            app = self.open_app()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.selectbox[0].value, "All")
            data = app.dataframe[0].value
            self.assertIn("Units", data.columns)
            self.assertNotIn("Available", data.columns)
            self.assertNotIn("Recorded units", data.columns)
            self.assertIn(self.code_for("AOO90SER"), data["Code"].tolist())
            relays = data[data["Code"].isin(["GPQM1026", "SINW1026"])]
            self.assertEqual(len(relays), 2)
            self.assertEqual(relays["Box"].tolist(), ["A", "A"])
            self.assertEqual(relays["Bag"].tolist(), ["12", "12"])
            head.assert_not_called()

    def test_punctuation_and_empty_search_results_render(self):
        app = self.open_app()
        app.text_input[0].set_value("10k(").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.info), 1)
        app.text_input[0].set_value("srd-05-vdc-sl-c").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.dataframe[0].value), 2)
        app.selectbox[0].select("sensor").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.info), 1)

    def test_browse_combines_text_categories_box_and_bag_and_clears_them_together(self):
        from test_inventory import catalog, stock

        details = catalog(
            {"code": "ITEM0001", "type": "board", "subtype": "dev", "description": "Target board"},
            {"code": "ITEM0002", "type": "board", "subtype": "dev", "description": "Other board"},
            {"code": "ITEM0003", "type": "board", "subtype": "io", "description": "Interface"},
            {"code": "ITEM0004", "type": "sensor", "subtype": "light", "description": "Light"},
        )
        locations = stock(["ITEM0001", "A", "01", "2"], ["ITEM0002", "B", "1", "3"],
                          ["ITEM0003", "A", "2", "4"], ["ITEM0004", "B", "03", "1"])
        with patch("scripts.inventory.load_data", return_value=(details, locations)):
            app = self.open_app()
            app.selectbox(key="browse_box").set_value("A").run()
            self.assertEqual(len(app.dataframe[0].value), 2)
            self.assertEqual(app.selectbox(key="browse_bag").options, ["All bags", "1", "2"])
            app.selectbox(key="browse_bag").set_value("1").run()
            app.selectbox(key="browse_type").set_value("board").run()
            app.selectbox(key="browse_subtype").set_value("dev").run()
            app.text_input(key="browse_search").set_value("target").run()
            self.assertEqual(app.dataframe[0].value["Code"].tolist(), ["ITEM0001"])
            self.assertEqual(app.dataframe[0].value["Bag"].tolist(), ["01"])
            app.selectbox(key="browse_box").set_value("B").run()
            self.assertEqual(len(app.dataframe), 0)
            self.assertTrue(any(message.value == "No matches found." for message in app.info))
            self.assertEqual(app.selectbox(key="browse_subtype").value, "dev")
            app.text_input(key="browse_search").set_value("board").run()
            self.assertEqual(app.dataframe[0].value["Code"].tolist(), ["ITEM0002"])
            app.selectbox(key="browse_type").set_value("sensor").run()
            self.assertEqual(app.selectbox(key="browse_subtype").value, "All")
            app.selectbox(key="browse_bag").set_value("3").run()
            app.selectbox(key="browse_box").set_value("A").run()
            self.assertIsNone(app.selectbox(key="browse_bag").value)
            next(button for button in app.button if button.label == "Clear filters").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.dataframe[0].value), 4)
            self.assertEqual(app.text_input(key="browse_search").value, "")
            self.assertEqual(app.selectbox(key="browse_type").value, "All")
            self.assertIsNone(app.selectbox(key="browse_box").value)

    def test_local_data_and_branding_load_outside_the_repository_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
            Path("details.csv").write_text("unrelated file", encoding="utf-8")
            app = self.open_app()
            self.assertEqual(len(app.exception), 0)
            self.assertIn(self.code_for("AOO90SER"), app.dataframe[0].value["Code"].tolist())
            app.radio[0].set_value("Purchases").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.error), 0)
            app.radio[0].set_value("History").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.error), 0)
            self.assertEqual(Path("details.csv").read_text(encoding="utf-8"), "unrelated file")

    def test_missing_images_are_optional_and_network_failures_are_handled(self):
        import requests

        with patch("requests.head", side_effect=requests.Timeout):
            app = self.open_app()
            app.text_input[0].set_value("GPQM1026").run()
            app.checkbox[0].check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("no image" in caption.value for caption in app.caption))

    def configure_forms(self):
        from scripts.inventory import load_data

        self.config.update(token="test-only-token", add_password="test-add", withdraw_password="test-take")
        snapshot_patch = patch("scripts.github_inventory.GitHubInventory.snapshot", return_value=load_data(Path(__file__).resolve().parents[1] / "data"))
        snapshot_patch.start()
        self.addCleanup(snapshot_patch.stop)

    def test_no_secrets_leaves_public_search_open_and_forms_disabled(self):
        app = self.open_app()
        app.radio[0].set_value("Add").run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("are not enabled" in message.value for message in app.info))
        self.assertEqual(len(app.text_input), 0)
        app.radio[0].set_value("Browse").run()
        self.assertEqual(len(app.dataframe), 1)

    def test_purchase_uses_withdrawal_password_and_refreshes_full_list(self):
        self.configure_forms()
        row = {"id": "existing", "timestamp": "2026-10-22T12:00:00+00:00", "description": "Existing request",
               "manufacturer": "", "model": "", "quantity": "1", "project": "Another project", "person": "Other intern",
               "link": "https://example.com/item", "notes": ""}
        with patch("scripts.github_inventory.GitHubInventory.purchase_snapshot", return_value=[row]), \
             patch("scripts.github_inventory.GitHubInventory.request_purchase", return_value="saved") as submit:
            app = self.open_app()
            app.radio[0].set_value("Purchases").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.dataframe[0].value["Project"].tolist(), ["Another project"])
            app.text_input(key="purchase_field_description").set_value("New sensor")
            app.text_input(key="purchase_field_project").set_value("Robot")
            app.text_input(key="purchase_field_person").set_value("Intern")
            app.text_input(key="purchase_field_link").set_value("https://example.com/sensor")
            app.text_input(key="purchase_field_password").set_value("test-add")
            next(button for button in app.button if button.label == "Add purchase request").click().run()
            submit.assert_not_called()
            self.assertEqual(app.error[0].value, "Incorrect password.")
            app.text_input(key="purchase_field_password").set_value("test-take")
            next(button for button in app.button if button.label == "Add purchase request").click().run()
            self.assertEqual(len(app.exception), 0)
            submit.assert_called_once()
            self.assertEqual(submit.call_args.args[3:6], ("Robot", "Intern", "https://example.com/sensor"))
            self.assertTrue(any("Purchase request recorded" in message.value for message in app.success))
            with self.assertRaises(KeyError):
                app.session_state["purchase_field_password"]

    def test_public_purchase_list_is_available_without_secrets_but_submission_is_disabled(self):
        app = self.open_app()
        app.radio[0].set_value("Purchases").run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("not enabled" in message.value for message in app.info))
        self.assertEqual(len(app.text_input), 0)
        self.assertEqual(len(app.get("download_button")), 1)

    def test_purchase_read_failure_disables_form(self):
        from scripts.github_inventory import GitHubError

        self.configure_forms()
        with patch("scripts.github_inventory.GitHubInventory.purchase_snapshot", side_effect=GitHubError("offline")):
            from scripts.purchases import live_purchases
            live_purchases.clear()
            app = self.open_app()
            app.radio[0].set_value("Purchases").run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("Could not load the purchase list" in message.value for message in app.error))
            self.assertEqual(len(app.text_input), 0)
            live_purchases.clear()

    def test_history_filters_projects_and_displays_totals_without_a_password(self):
        self.configure_forms()
        self.config["withdraw_password"] = ""
        from scripts.withdrawal_history import live_withdrawals
        live_withdrawals.clear()
        self.addCleanup(live_withdrawals.clear)
        rows = [dict(id=str(index), timestamp="2026-10-22T12:00:00+00:00",
                     code="GPQM1026", location="A", sublocation="12", quantity=str(quantity),
                     available_after="0", person="Intern", project=project)
                for index, (project, quantity) in enumerate((("Robot", 2), ("Robot", 1), ("Station", 4), ("", 1)))]
        with patch("scripts.github_inventory.GitHubInventory.withdrawal_snapshot", return_value=rows):
            app = self.open_app()
            app.radio[0].set_value("History").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.dataframe[1].value), 4)
            self.assertEqual(len(app.text_input), 0)
            app.selectbox[0].set_value("Robot").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.dataframe[0].value["Total withdrawn"].tolist(), [3])
            self.assertEqual(app.dataframe[1].value["Project"].tolist(), ["Robot", "Robot"])
            self.assertEqual(len(app.get("download_button")), 1)
            app.selectbox[0].set_value("").run()
            self.assertEqual(len(app.dataframe[1].value), 1)

    def test_history_without_token_displays_empty_local_snapshot_and_download(self):
        app = self.open_app()
        app.radio[0].set_value("History").run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("local withdrawal-history snapshot" in message.value for message in app.info))
        self.assertEqual(len(app.text_input), 0)
        self.assertEqual(len(app.get("download_button")), 1)

    def test_history_read_failure_does_not_show_an_empty_report(self):
        from scripts.github_inventory import GitHubError

        self.configure_forms()
        with patch("scripts.github_inventory.GitHubInventory.withdrawal_snapshot", side_effect=GitHubError("offline")):
            from scripts.withdrawal_history import live_withdrawals
            live_withdrawals.clear()
            app = self.open_app()
            app.radio[0].set_value("History").run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("Could not load withdrawal history" in message.value for message in app.error))
            self.assertEqual(len(app.dataframe), 0)
            self.assertEqual(len(app.get("download_button")), 0)
            live_withdrawals.clear()

    def test_addition_requires_its_password_and_does_not_ask_for_code(self):
        self.configure_forms()
        with patch("scripts.github_inventory.GitHubInventory.add", return_value={"id": "test-operation", "code": "TEST1026"}) as propose:
            app = self.open_app()
            app.radio[0].set_value("Add").run()
            self.assertEqual(len(app.exception), 0)
            self.assertFalse(any("Code" in text.label for text in app.text_input))
            manufacturer = app.selectbox(key="addition_field_manufacturer")
            self.assertTrue(manufacturer.proto.accept_new_options)
            self.assertIsNone(manufacturer.value)
            self.assertIn("SONGLE", manufacturer.options)
            self.assertEqual(len(manufacturer.options), len({value.casefold() for value in manufacturer.options}))
            app.selectbox(key="addition_field_type_choice").select("sensor").run()
            app.selectbox(key="addition_field_subtype_choice").select("Create new…").run()
            app.text_input(key="addition_field_new_subtype").set_value("light").run()
            box = app.selectbox(key="addition_field_location")
            self.assertTrue(box.proto.accept_new_options)
            self.assertIn("A", box.options)
            self.assertNotIn("", box.options)
            box.select("A").run()
            app.number_input(key="addition_field_sublocation").set_value(1).run()
            app.selectbox(key="addition_field_manufacturer").select("SONGLE")
            app.text_input(key="addition_field_description").set_value("New sensor")
            app.text_input(key="addition_field_person").set_value("Intern")
            app.text_input(key="addition_field_password").set_value("test-take")
            app.button[0].click().run()
            propose.assert_not_called()
            self.assertEqual(app.error[0].value, "Incorrect password.")
            app.text_input(key="addition_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            propose.assert_called_once()
            self.assertEqual(propose.call_args.args[1]["manufacturer"], "SONGLE")
            self.assertEqual(propose.call_args.args[3], "A")
            self.assertIn("Addition saved", app.success[0].value)
            with self.assertRaises(KeyError):
                app.session_state["addition_field_password"]

    def test_direct_add_and_edit_update_browse_immediately_without_pr_links(self):
        from test_github_inventory import MemoryGitHub

        db = MemoryGitHub()
        self.config.update(token="test-direct-ui", add_password="test-add", withdraw_password="test-take")
        with patch("scripts.github_inventory.GitHubInventory.snapshot", side_effect=db.snapshot), \
             patch("scripts.github_inventory.GitHubInventory.add", side_effect=db.add), \
             patch("scripts.github_inventory.GitHubInventory.edit", side_effect=db.edit):
            app = self.open_app()
            app.radio[0].set_value("Add").run()
            app.radio[1].set_value("Restock an existing product").run()
            app.number_input(key="addition_field_quantity").set_value(2)
            app.text_input(key="addition_field_person").set_value("Tester")
            app.text_input(key="addition_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("Addition saved", app.success[0].value)
            self.assertEqual(len(app.get("link_button")), 0)
            app.radio[0].set_value("Browse").run()
            self.assertEqual(app.dataframe[0].value["Units"].tolist(), ["7", "3"])
            app.radio[0].set_value("Edit").run()
            app.text_input(key="edit_field_description").set_value("Corrected board")
            app.text_input(key="edit_field_person").set_value("Tester")
            app.text_input(key="edit_field_reason").set_value("Corrected name")
            app.text_input(key="edit_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("Changes saved", app.success[0].value)
            app.radio[0].set_value("Browse").run()
            self.assertEqual(set(app.dataframe[0].value["Description"]), {"Corrected board"})
            self.assertEqual(app.dataframe[0].value["Units"].tolist(), ["7", "3"])
        self.assertEqual(list(db.refs), ["main"])

    def test_addition_can_create_type_and_subtype_and_resets_subtype_when_type_changes(self):
        self.configure_forms()
        with patch("scripts.github_inventory.GitHubInventory.add", return_value={"id": "test-operation", "code": "TEST1026"}) as propose:
            app = self.open_app()
            app.radio[0].set_value("Add").run()
            self.assertTrue(app.selectbox(key="addition_field_subtype_choice").disabled)
            app.selectbox(key="addition_field_type_choice").select("actuator").run()
            self.assertIn("servo", app.selectbox(key="addition_field_subtype_choice").options)
            app.selectbox(key="addition_field_subtype_choice").select("servo").run()
            app.selectbox(key="addition_field_type_choice").select("Create new…").run()
            app.text_input(key="addition_field_new_type").set_value("Optical measurement").run()
            self.assertIsNone(app.selectbox(key="addition_field_subtype_choice").value)
            self.assertNotIn("servo", app.selectbox(key="addition_field_subtype_choice").options)
            app.selectbox(key="addition_field_subtype_choice").select("Create new…").run()
            app.text_input(key="addition_field_new_subtype").set_value("Photometers").run()
            app.selectbox(key="addition_field_location").select("A").run()
            app.number_input(key="addition_field_sublocation").set_value(1).run()
            app.text_input(key="addition_field_description").set_value("Test photometer")
            app.text_input(key="addition_field_person").set_value("Intern")
            app.text_input(key="addition_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            propose.assert_called_once()
            self.assertEqual(propose.call_args.args[1]["type"], "Optical measurement")
            self.assertEqual(propose.call_args.args[1]["subtype"], "Photometers")

    def test_compartment_warning_is_per_box_nonblocking_and_clears_for_unused_number(self):
        self.configure_forms()
        with patch("scripts.github_inventory.GitHubInventory.add", return_value={"id": "test-operation", "code": "TEST1026"}) as propose:
            app = self.open_app()
            app.radio[0].set_value("Add").run()
            app.selectbox(key="addition_field_type_choice").select("actuator").run()
            app.selectbox(key="addition_field_subtype_choice").select("servo").run()
            app.selectbox(key="addition_field_location").select("A").run()
            app.number_input(key="addition_field_sublocation").set_value(999).run()
            self.assertEqual(len(app.warning), 0)
            app.number_input(key="addition_field_sublocation").set_value(12).run()
            self.assertEqual(len(app.warning), 1)
            self.assertIn("You can continue", app.warning[0].value)
            app.selectbox(key="addition_field_location").select("S").run()
            self.assertEqual(len(app.warning), 0)
            app.selectbox(key="addition_field_location").select("A").run()
            self.assertEqual(len(app.warning), 1)
            self.assertFalse(app.button[0].disabled)
            app.text_input(key="addition_field_description").set_value("Another product in the same bag")
            app.text_input(key="addition_field_person").set_value("Intern")
            app.text_input(key="addition_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            propose.assert_called_once()
            self.assertEqual(propose.call_args.args[3:5], ("A", "12"))

    def test_restock_uses_assigned_box_and_bag_without_asking_again(self):
        self.configure_forms()
        with patch("scripts.github_inventory.GitHubInventory.add", return_value={"id": "test-operation", "code": "TEST1026"}) as propose:
            app = self.open_app()
            app.radio[0].set_value("Add").run()
            app.radio[1].set_value("Restock an existing product").run()
            app.selectbox[0].select(self.code_for("DCACTMOT")).run()
            self.assertEqual(len(app.exception), 0)
            self.assertFalse(any(select.key == "addition_field_location" for select in app.selectbox))
            self.assertFalse(any(number.key == "addition_field_sublocation" for number in app.number_input))
            self.assertTrue(any("box A, bag 1" in caption.value for caption in app.caption))
            app.number_input(key="addition_field_quantity").set_value(2)
            app.text_input(key="addition_field_person").set_value("Intern")
            app.text_input(key="addition_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            propose.assert_called_once()
            self.assertEqual(propose.call_args.args[2:5], (2, "A", "1"))
            self.assertEqual(propose.call_args.args[7], self.code_for("DCACTMOT"))

    def test_withdrawal_requires_password_and_shows_receipt_without_resubmitting(self):
        self.configure_forms()
        with patch("scripts.github_inventory.GitHubInventory.withdraw", return_value=3) as withdraw:
            app = self.open_app()
            app.radio[0].set_value("Withdraw").run()
            self.assertEqual(len(app.exception), 0)
            person = app.selectbox(key="withdrawal_field_person")
            self.assertIsNone(person.value)
            self.assertFalse(person.proto.accept_new_options)
            person.set_value("TEST00")
            app.text_input(key="withdrawal_field_password").set_value("wrong")
            next(button for button in app.button if button.label == "Record withdrawal").click().run()
            withdraw.assert_not_called()
            app.text_input(key="withdrawal_field_password").set_value("test-take")
            next(button for button in app.button if button.label == "Record withdrawal").click().run()
            withdraw.assert_not_called()
            self.assertIn("Project:", app.error[0].value)
            app.text_input(key="withdrawal_field_project").set_value("Robot")
            next(button for button in app.button if button.label == "Record withdrawal").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("Remaining after this withdrawal: 3", app.success[0].value)
            app.run()
            withdraw.assert_called_once()
            self.assertEqual(withdraw.call_args.kwargs["assistant_id"], "TEST00")
            self.assertEqual(withdraw.call_args.args[5], "Intern")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.text_input(key="withdrawal_field_password").value, "")

    def test_remote_read_failure_keeps_local_search_available_and_disables_writes(self):
        from scripts.github_inventory import GitHubError

        self.config.update(token="unavailable-token", add_password="test-add")
        with patch("scripts.github_inventory.GitHubInventory.snapshot", side_effect=GitHubError("offline")):
            app = self.open_app()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.dataframe), 1)
            self.assertEqual(len(app.warning), 1)
            app.radio[0].set_value("Add").run()
            self.assertEqual(len(app.text_input), 0)

    def test_edit_is_separate_prefilled_and_uses_addition_password(self):
        self.configure_forms()
        with patch("scripts.github_inventory.GitHubInventory.edit", return_value={"id": "test-operation", "code": "TEST1026"}) as edit:
            app = self.open_app()
            self.assertEqual(app.radio[0].options, ["Browse", "Add", "Edit", "Withdraw", "Purchases", "History"])
            app.radio[0].set_value("Edit").run()
            self.assertEqual(len(app.exception), 0)
            before = app.text_input(key="edit_field_description").value
            self.assertTrue(before)
            app.text_input(key="edit_field_description").set_value(before + " corrected")
            app.text_input(key="edit_field_person").set_value("Intern")
            app.text_input(key="edit_field_reason").set_value("Verified label")
            app.text_input(key="edit_field_password").set_value("test-take")
            app.button[0].click().run()
            edit.assert_not_called()
            app.text_input(key="edit_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            edit.assert_called_once()
            args = edit.call_args.args
            self.assertEqual(args[2]["description"], before)
            self.assertEqual(args[3]["description"], before + " corrected")
            self.assertIn("Changes saved", app.success[0].value)
            app.run()
            edit.assert_called_once()
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.text_input(key="edit_field_password").value, "")

    def test_edit_product_switch_replaces_browser_fields_and_preserves_same_product_draft(self):
        from scripts.inventory import load_data

        self.configure_forms()
        details, _ = load_data(Path(__file__).resolve().parents[1] / "data")
        with patch("scripts.github_inventory.GitHubInventory.edit", return_value={"id": "test-operation", "code": "TEST1026"}) as edit:
            app = self.open_app()
            app.radio[0].set_value("Edit").run()
            first = app.selectbox(key="edit_product_choice").value
            app.text_input(key="edit_field_description").set_value("First product draft")
            app.button[0].click().run()
            app.text_input(key="edit_field_person").set_value("Previous recorder")
            app.text_input(key="edit_field_reason").set_value("Previous reason")
            app.text_input(key="edit_field_password").set_value("test-add")
            code = self.code_for("DCACTMOT")
            app.selectbox(key="edit_product_choice").select(code).run()
            expected = details.loc[details["code"].eq(code)].iloc[0].to_dict()
            for name in ("description", "type", "subtype", "manufacturer", "model", "value", "package", "info"):
                field = app.text_input(key=f"edit_field_{name}")
                self.assertEqual(field.value, expected[name])
                # AppTest accepts new defaults even when a real browser retains
                # its keyed field. Check the explicit browser update as well.
                self.assertTrue(field.proto.set_value)
                self.assertEqual(field.proto.value, expected[name])
            for name in ("person", "reason", "password"):
                self.assertEqual(app.text_input(key=f"edit_field_{name}").value, "")
            app.text_input(key="edit_field_description").set_value("Corrected motor description")
            app.button[0].click().run()
            app.run()
            self.assertEqual(app.text_input(key="edit_field_description").value, "Corrected motor description")
            self.assertEqual(app.session_state["edit_original_item"], expected)
            app.selectbox(key="edit_product_choice").select(first).run()
            self.assertEqual(app.text_input(key="edit_field_description").value,
                             details.loc[details["code"].eq(first), "description"].item())
            app.selectbox(key="edit_product_choice").select(code).run()
            app.text_input(key="edit_field_description").set_value("Verified motor")
            app.text_input(key="edit_field_person").set_value("Intern")
            app.text_input(key="edit_field_reason").set_value("Verified label")
            app.text_input(key="edit_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(edit.call_args.args[1], code)
            self.assertEqual(edit.call_args.args[2], expected)
            self.assertEqual(edit.call_args.args[3]["description"], "Verified motor")

    def test_edit_optional_stock_is_prefilled_and_saved_immediately(self):
        self.configure_forms()
        with patch("scripts.github_inventory.GitHubInventory.edit", return_value={"id": "test-operation", "code": "TEST1026"}) as edit:
            app = self.open_app()
            app.radio[0].set_value("Edit").run()
            app.selectbox(key="edit_product_choice").select(self.code_for("DCACTMOT")).run()
            app.checkbox[0].check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.text_input(key="edit_field_location").value, "A")
            self.assertEqual(app.number_input(key="edit_field_units").value, 10)
            self.assertEqual(len(app.number_input), 1)
            app.number_input(key="edit_field_units").set_value(9)
            app.text_input(key="edit_field_person").set_value("Intern")
            app.text_input(key="edit_field_reason").set_value("Physical count")
            app.text_input(key="edit_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            args = edit.call_args.args
            self.assertEqual(args[6]["units"], "10")
            self.assertEqual(args[7]["units"], 9)
            self.assertNotIn("available", args[7])

    def test_edit_finds_shared_bag_and_submits_the_selected_products_stock(self):
        self.configure_forms()
        with patch("scripts.github_inventory.GitHubInventory.edit", return_value={"id": "test-operation", "code": "TEST1026"}) as edit:
            app = self.open_app()
            app.radio[0].set_value("Edit").run()
            app.selectbox(key="edit_filter_box").set_value("A").run()
            app.selectbox(key="edit_filter_bag").set_value("12").run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn(app.selectbox(key="edit_product_choice").value, {"GPQM1026", "SINW1026"})
            table = app.dataframe[0].value
            self.assertEqual(len(table), 2)
            self.assertEqual(set(table["Box"]), {"A"})
            self.assertEqual(set(table["Bag"]), {"12"})
            self.assertTrue(app.checkbox(key="edit_correct_stock").value)
            app.selectbox(key="edit_product_choice").set_value("SINW1026").run()
            self.assertEqual(app.text_input(key="edit_field_location").value, "A")
            self.assertEqual(app.text_input(key="edit_field_sublocation").value, "12")
            app.number_input(key="edit_field_units").set_value(3)
            app.text_input(key="edit_field_person").set_value("Tester")
            app.text_input(key="edit_field_reason").set_value("Physical count")
            app.text_input(key="edit_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(edit.call_args.args[1], "SINW1026")
            self.assertEqual(edit.call_args.args[6]["sublocation"], "12")
            self.assertEqual(edit.call_args.args[7]["units"], 3)

    def test_edit_box_filter_switches_stock_slot_without_carrying_previous_form_edits(self):
        import pandas as pd
        from scripts.inventory import load_data

        self.configure_forms()
        self.config["token"] = "test-edit-multiple-slots"
        details, locations = load_data(Path(__file__).resolve().parents[1] / "data")
        code = self.code_for("DCACTMOT")
        locations = pd.concat([locations, pd.DataFrame([{
            "code": code, "location": "TESTBOX", "sublocation": "01", "units": "7",
        }])], ignore_index=True)
        with patch("scripts.github_inventory.GitHubInventory.snapshot", return_value=(details, locations)):
            app = self.open_app()
            app.radio[0].set_value("Edit").run()
            app.selectbox(key="edit_filter_box").set_value("A").run()
            app.selectbox(key="edit_product_choice").set_value(code).run()
            app.number_input(key="edit_field_units").set_value(99).run()
            app.selectbox(key="edit_filter_box").set_value("TESTBOX").run()
            app.selectbox(key="edit_filter_bag").set_value("1").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.selectbox(key="edit_product_choice").value, code)
            self.assertEqual(app.text_input(key="edit_field_location").value, "TESTBOX")
            self.assertEqual(app.text_input(key="edit_field_sublocation").value, "01")
            self.assertEqual(app.number_input(key="edit_field_units").value, 7)
            self.assertEqual(app.selectbox(key="edit_stock_choice").value, ("TESTBOX", "01"))

    def test_edit_can_find_bag_across_boxes_and_clear_filters_for_unassigned_products(self):
        self.configure_forms()
        app = self.open_app()
        app.radio[0].set_value("Edit").run()
        app.selectbox(key="edit_filter_bag").set_value("12").run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(app.dataframe[0].value["Bag"].map(lambda value: int(value) == 12).all())
        app.selectbox(key="edit_filter_bag").set_value(None).run()
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(app.checkbox(key="edit_correct_stock").value)
        self.assertEqual(len(app.dataframe), 0)

    def test_migrated_product_finds_legacy_photo_and_remains_searchable_by_old_code(self):
        from unittest.mock import Mock

        def photo(url, **kwargs):
            return Mock(status_code=200 if url.endswith("/WASHSETS.png") else 404)

        with patch("requests.head", side_effect=photo) as head:
            app = self.open_app()
            app.text_input[0].set_value("WASHSETS").run()
            self.assertEqual(len(app.dataframe[0].value), 1)
            app.checkbox[0].check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any(call.args[0].endswith("/WASHSETS.png") for call in head.call_args_list))


if __name__ == "__main__":
    unittest.main()
