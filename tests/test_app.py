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

    def test_app_opens_with_all_stock_and_no_image_requests(self):
        with patch("requests.head") as head:
            app = self.open_app()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.selectbox[0].value, "Todos")
            data = app.dataframe[0].value
            self.assertIn("AOO90SER", data["Código"].tolist())
            self.assertEqual(len(data[data["Código"].eq("SRD5VDCS")]), 2)
            head.assert_not_called()

    def test_punctuation_and_empty_search_results_render(self):
        app = self.open_app()
        app.text_input[0].set_value("10k(").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.info), 1)
        app.text_input[0].set_value("srd5vdcs").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.dataframe[0].value), 2)
        app.selectbox[0].select("sensor").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.info), 1)

    def test_missing_images_are_optional_and_network_failures_are_handled(self):
        import requests

        with patch("requests.head", side_effect=requests.Timeout):
            app = self.open_app()
            app.text_input[0].set_value("WASHSETS").run()
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
            app.text_input(key="addition_field_description").set_value("Sensor nuevo")
            app.text_input(key="addition_field_type").set_value("sensor")
            app.text_input(key="addition_field_subtype").set_value("light")
            app.text_input(key="addition_field_location").set_value("A")
            app.text_input(key="addition_field_sublocation").set_value("01")
            app.text_input(key="addition_field_person").set_value("Intern")
            app.text_input(key="addition_field_password").set_value("test-take")
            app.button[0].click().run()
            propose.assert_not_called()
            self.assertEqual(app.error[0].value, "Contraseña incorrecta.")
            app.text_input(key="addition_field_password").set_value("test-add")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            propose.assert_called_once()
            self.assertIn("Solicitud enviada", app.success[0].value)
            with self.assertRaises(KeyError):
                app.session_state["addition_field_password"]

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


if __name__ == "__main__":
    unittest.main()
