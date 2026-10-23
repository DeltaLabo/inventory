import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Install requirements.txt to check the UI")
class AppTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "token": "", "repository": "DeltaLabo/inventory", "branch": "main",
            "add_password": "", "withdraw_password": "",
        }
        config_patch = patch("forms.settings", return_value=self.config)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        network_patch = patch("requests.request", side_effect=AssertionError("Tests must not access GitHub"))
        network_patch.start()
        self.addCleanup(network_patch.stop)

    def open_app(self):
        from streamlit.testing.v1 import AppTest

        return AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()

    def code_for(self, previous_code):
        from inventory import load_data

        details, _ = load_data(Path(__file__).resolve().parents[1])
        return details.loc[details["previous_code"].eq(previous_code), "code"].item()

    def test_app_opens_with_all_stock_and_no_image_requests(self):
        with patch("requests.head") as head:
            app = self.open_app()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.selectbox[0].value, "Todos")
            data = app.dataframe[0].value
            self.assertIn(self.code_for("AOO90SER"), data["Código"].tolist())
            relays = data[data["Código"].isin(["GPQM1026", "SINW1026"])]
            self.assertEqual(len(relays), 2)
            self.assertEqual(relays["Caja"].tolist(), ["A", "A"])
            self.assertEqual(relays["Bolsa"].tolist(), ["12", "12"])
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

    def test_missing_images_are_optional_and_network_failures_are_handled(self):
        import requests

        with patch("requests.head", side_effect=requests.Timeout):
            app = self.open_app()
            app.text_input[0].set_value("GPQM1026").run()
            app.checkbox[0].check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("sin imagen" in caption.value for caption in app.caption))

    def configure_forms(self):
        from inventory import load_data

        self.config.update(token="test-only-token", add_password="test-add", withdraw_password="test-take")
        snapshot_patch = patch("github_inventory.GitHubInventory.snapshot", return_value=load_data(Path(__file__).resolve().parents[1]))
        snapshot_patch.start()
        self.addCleanup(snapshot_patch.stop)

    def test_no_secrets_leaves_public_search_open_and_forms_disabled(self):
        app = self.open_app()
        app.radio[0].set_value("Ingresar").run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("no está habilitado" in message.value for message in app.info))
        self.assertEqual(len(app.text_input), 0)
        app.radio[0].set_value("Consultar").run()
        self.assertEqual(len(app.dataframe), 1)

    def test_addition_requires_its_password_and_does_not_ask_for_code(self):
        self.configure_forms()
        with patch("github_inventory.GitHubInventory.propose_addition", return_value="https://github.com/DeltaLabo/inventory/pull/123") as propose:
            app = self.open_app()
            app.radio[0].set_value("Ingresar").run()
            self.assertEqual(len(app.exception), 0)
            self.assertFalse(any("Código" in text.label for text in app.text_input))
            manufacturer = app.selectbox(key="addition_field_manufacturer")
            self.assertTrue(manufacturer.proto.accept_new_options)
            self.assertIsNone(manufacturer.value)
            self.assertIn("SONGLE", manufacturer.options)
            self.assertEqual(len(manufacturer.options), len({value.casefold() for value in manufacturer.options}))
            app.selectbox(key="addition_field_type_choice").select("sensor").run()
            app.selectbox(key="addition_field_subtype_choice").select("Crear nuevo…").run()
            app.text_input(key="addition_field_new_subtype").set_value("light").run()
            box = app.selectbox(key="addition_field_location")
            self.assertTrue(box.proto.accept_new_options)
            self.assertIn("A", box.options)
            self.assertNotIn("", box.options)
            box.select("A").run()
            app.number_input(key="addition_field_sublocation").set_value(1).run()
            app.selectbox(key="addition_field_manufacturer").select("SONGLE")
            app.text_input(key="addition_field_description").set_value("Sensor nuevo")
            app.text_input(key="addition_field_person").set_value("Intern")
            app.text_input(key="addition_field_password").set_value("test-take")
            app.button[0].click().run()
            propose.assert_not_called()
            self.assertEqual(app.error[0].value, "Contraseña incorrecta.")
            app.text_input(key="addition_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            propose.assert_called_once()
            self.assertEqual(propose.call_args.args[1]["manufacturer"], "SONGLE")
            self.assertEqual(propose.call_args.args[3], "A")
            self.assertIn("Solicitud enviada", app.success[0].value)
            with self.assertRaises(KeyError):
                app.session_state["addition_field_password"]

    def test_addition_can_create_type_and_subtype_and_resets_subtype_when_type_changes(self):
        self.configure_forms()
        with patch("github_inventory.GitHubInventory.propose_addition", return_value="https://github.com/DeltaLabo/inventory/pull/125") as propose:
            app = self.open_app()
            app.radio[0].set_value("Ingresar").run()
            self.assertTrue(app.selectbox(key="addition_field_subtype_choice").disabled)
            app.selectbox(key="addition_field_type_choice").select("actuator").run()
            self.assertIn("servo", app.selectbox(key="addition_field_subtype_choice").options)
            app.selectbox(key="addition_field_subtype_choice").select("servo").run()
            app.selectbox(key="addition_field_type_choice").select("Crear nuevo…").run()
            app.text_input(key="addition_field_new_type").set_value("Medición óptica").run()
            self.assertIsNone(app.selectbox(key="addition_field_subtype_choice").value)
            self.assertNotIn("servo", app.selectbox(key="addition_field_subtype_choice").options)
            app.selectbox(key="addition_field_subtype_choice").select("Crear nuevo…").run()
            app.text_input(key="addition_field_new_subtype").set_value("Fotómetros").run()
            app.selectbox(key="addition_field_location").select("A").run()
            app.number_input(key="addition_field_sublocation").set_value(1).run()
            app.text_input(key="addition_field_description").set_value("Fotómetro de prueba")
            app.text_input(key="addition_field_person").set_value("Intern")
            app.text_input(key="addition_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            propose.assert_called_once()
            self.assertEqual(propose.call_args.args[1]["type"], "Medición óptica")
            self.assertEqual(propose.call_args.args[1]["subtype"], "Fotómetros")

    def test_compartment_warning_is_per_box_nonblocking_and_clears_for_unused_number(self):
        self.configure_forms()
        with patch("github_inventory.GitHubInventory.propose_addition", return_value="https://github.com/DeltaLabo/inventory/pull/126") as propose:
            app = self.open_app()
            app.radio[0].set_value("Ingresar").run()
            app.selectbox(key="addition_field_type_choice").select("actuator").run()
            app.selectbox(key="addition_field_subtype_choice").select("servo").run()
            app.selectbox(key="addition_field_location").select("A").run()
            app.number_input(key="addition_field_sublocation").set_value(999).run()
            self.assertEqual(len(app.warning), 0)
            app.number_input(key="addition_field_sublocation").set_value(12).run()
            self.assertEqual(len(app.warning), 1)
            self.assertIn("Podés continuar", app.warning[0].value)
            app.selectbox(key="addition_field_location").select("S").run()
            self.assertEqual(len(app.warning), 0)
            app.selectbox(key="addition_field_location").select("A").run()
            self.assertEqual(len(app.warning), 1)
            self.assertFalse(app.button[0].disabled)
            app.text_input(key="addition_field_description").set_value("Otro producto en la misma bolsa")
            app.text_input(key="addition_field_person").set_value("Intern")
            app.text_input(key="addition_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            propose.assert_called_once()
            self.assertEqual(propose.call_args.args[3:5], ("A", "12"))

    def test_restock_uses_assigned_box_and_bag_without_asking_again(self):
        self.configure_forms()
        with patch("github_inventory.GitHubInventory.propose_addition", return_value="https://github.com/DeltaLabo/inventory/pull/127") as propose:
            app = self.open_app()
            app.radio[0].set_value("Ingresar").run()
            app.radio[1].set_value("Más unidades de un producto existente").run()
            app.selectbox[0].select(self.code_for("DCACTMOT")).run()
            self.assertEqual(len(app.exception), 0)
            self.assertFalse(any(select.key == "addition_field_location" for select in app.selectbox))
            self.assertFalse(any(number.key == "addition_field_sublocation" for number in app.number_input))
            self.assertTrue(any("caja A, bolsa 1" in caption.value for caption in app.caption))
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
        with patch("github_inventory.GitHubInventory.withdraw", return_value=3) as withdraw:
            app = self.open_app()
            app.radio[0].set_value("Retirar").run()
            self.assertEqual(len(app.exception), 0)
            app.text_input(key="withdrawal_field_person").set_value("Intern")
            app.text_input(key="withdrawal_field_password").set_value("wrong")
            app.button[0].click().run()
            withdraw.assert_not_called()
            app.text_input(key="withdrawal_field_password").set_value("test-take")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("Disponible después del retiro: 3", app.success[0].value)
            app.run()
            withdraw.assert_called_once()
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.text_input(key="withdrawal_field_password").value, "")

    def test_remote_read_failure_keeps_local_search_available_and_disables_writes(self):
        from github_inventory import GitHubError

        self.config.update(token="unavailable-token", add_password="test-add")
        with patch("github_inventory.GitHubInventory.snapshot", side_effect=GitHubError("offline")):
            app = self.open_app()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.dataframe), 1)
            self.assertEqual(len(app.warning), 1)
            app.radio[0].set_value("Ingresar").run()
            self.assertEqual(len(app.text_input), 0)

    def test_edit_is_separate_prefilled_and_uses_addition_password(self):
        self.configure_forms()
        with patch("github_inventory.GitHubInventory.propose_edit", return_value="https://github.com/DeltaLabo/inventory/pull/124") as edit:
            app = self.open_app()
            self.assertEqual(app.radio[0].options, ["Consultar", "Ingresar", "Editar", "Retirar"])
            app.radio[0].set_value("Editar").run()
            self.assertEqual(len(app.exception), 0)
            before = app.text_input(key="edit_field_description").value
            self.assertTrue(before)
            app.text_input(key="edit_field_description").set_value(before + " corregido")
            app.text_input(key="edit_field_person").set_value("Intern")
            app.text_input(key="edit_field_reason").set_value("Etiqueta verificada")
            app.text_input(key="edit_field_password").set_value("test-take")
            app.button[0].click().run()
            edit.assert_not_called()
            app.text_input(key="edit_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            edit.assert_called_once()
            args = edit.call_args.args
            self.assertEqual(args[2]["description"], before)
            self.assertEqual(args[3]["description"], before + " corregido")
            self.assertIn("Solicitud enviada", app.success[0].value)
            app.run()
            edit.assert_called_once()
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.text_input(key="edit_field_password").value, "")

    def test_edit_optional_stock_is_prefilled_and_can_be_submitted_for_review(self):
        self.configure_forms()
        with patch("github_inventory.GitHubInventory.propose_edit", return_value="https://github.com/DeltaLabo/inventory/pull/124") as edit:
            app = self.open_app()
            app.radio[0].set_value("Editar").run()
            app.selectbox[0].select(self.code_for("DCACTMOT")).run()
            app.checkbox[0].check().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.text_input(key="edit_field_location").value, "A")
            self.assertEqual(app.number_input(key="edit_field_available").value, 10)
            app.number_input(key="edit_field_available").set_value(9)
            app.text_input(key="edit_field_person").set_value("Intern")
            app.text_input(key="edit_field_reason").set_value("Conteo físico")
            app.text_input(key="edit_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            args = edit.call_args.args
            self.assertEqual(args[6]["available"], "10")
            self.assertEqual(args[7]["available"], 9)

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
