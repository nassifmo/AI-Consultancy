"""Test the normal company preparation journey and bounded archive handling."""

from io import BytesIO
import json
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from streamlit.testing.v1 import AppTest

from intake_ui import EXAMPLE, unpack_company_files


ROOT = Path(__file__).resolve().parents[1]


class IntakeTests(unittest.TestCase):
    def test_preview_publish_and_evaluate_sample_extract(self):
        with TemporaryDirectory() as directory, patch("intake_ui.IMPORTS", Path(directory)):
            app = AppTest.from_file(ROOT / "app.py", default_timeout=20).run()
            next(button for button in app.button if button.label == "Preview synthetic company extract").click().run()
            self.assertFalse(app.exception)
            self.assertEqual([tab.label for tab in app.tabs], ["Files received", "Mapping preview", "Review issues", "Approval"])
            approve = next(button for button in app.button if button.label == "Approve for evaluation")
            self.assertTrue(approve.proto.disabled)
            self.assertNotIn("Approved company files", app.selectbox(key="shipment_source").options)
            next(item for item in app.text_input if item.label == "Reviewer name").set_value("Synthetic reviewer")
            next(item for item in app.text_area if item.label == "Review basis and unresolved evidence").set_value(
                "Reviewed source rows and left unsupported cost and assignment unavailable.")
            next(item for item in app.checkbox if item.label.startswith("I reviewed the mapping")).check()
            app.run()
            next(button for button in app.button if button.label == "Approve for evaluation").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key="shipment_source").value, "Approved company files")
            next(button for button in app.button if button.label == "Run evaluation").click().run()
            self.assertFalse(app.exception)
            values = {card.label: card.value for card in app.metric}
            self.assertEqual(values["Service outcome"], "Resolved")
            self.assertEqual(values["Human recovery"], "Verified")
            self.assertEqual(values["Initial AI critical failure"], "Yes")
            analysis = app.session_state["shipment_analysis"][0]
            self.assertIn("readiness_assessment", analysis)
            self.assertEqual(len(analysis["readiness_assessment"]["capabilities"]), 7)
            self.assertEqual(analysis["episodes"][0]["exclusion_reasons"], ["missing_or_invalid_root", "missing_or_invalid_assignment"])
            self.assertTrue(list(Path(directory).glob("import-*/profile.json")))
            self.assertEqual(analysis["run_provenance"]["intake_approval"]["reviewer"], "Synthetic reviewer")
            self.assertTrue(list(Path(directory).glob("approved-*/exports/intake_approval.json")))

    def test_mapping_archive_accepts_missing_source_and_rejects_unlisted_files(self):
        profile = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
        filename = next(iter(profile["tables"].values()))["file"]
        payload = BytesIO()
        with ZipFile(payload, "w") as archive:
            archive.writestr("source/" + filename, b"id\n1\n")
        with unpack_company_files(payload.getvalue(), profile) as source:
            self.assertEqual([file.name for file in source.iterdir()], [filename])
        for name in ("../outside.csv", "ground_truth/expected.json", "source/secret.json", filename + "/"):
            with self.subTest(name=name):
                payload = BytesIO()
                with ZipFile(payload, "w") as archive:
                    archive.writestr(name, b"{}")
                with self.assertRaises(ValueError), unpack_company_files(payload.getvalue(), profile):
                    self.fail("Unexpected source file was accepted.")

    def test_suggestion_trial_keeps_approved_inputs_unchanged_until_review(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            example = copytree(EXAMPLE, root / "example")
            file = example / "source" / "bookings.csv"
            file.write_bytes(file.read_bytes().replace(b"external_booking_ref,", b"Ship_Ref,", 1))
            with patch("intake_ui.IMPORTS", root / "imports"), patch("intake_ui.EXAMPLE", example):
                app = AppTest.from_file(ROOT / "app.py", default_timeout=20).run()
                next(button for button in app.button if button.label == "Preview synthetic company extract").click().run()
                self.assertFalse(app.exception)
                review = app.session_state["company_review"]
                original_version = review["profile"]["profile_version"]
                self.assertEqual(review["prepared"]["exports"]["shipments.csv"][0]["booking_ref"], "")
                self.assertTrue(any("Ship_Ref" in label for item in app.selectbox
                                    if item.label == "Suggested source field" for label in item.options))
                next(button for button in app.button if button.label == "Record suggestion decision").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["company_review"]["profile"], review["profile"])
                trial = app.session_state["company_mapping_trial"]
                self.assertTrue(trial["prepared"]["exports"]["shipments.csv"][0]["booking_ref"])
                self.assertTrue(next(button for button in app.button if button.label == "Approve for evaluation").proto.disabled)
                next(item for item in app.text_input if item.label == "Evidence for the revised mapping").set_value(
                    "Ship Ref matched the tracking extract and booking records.")
                app.run()
                next(button for button in app.button if button.label == "Apply reviewed mapping").click().run()
                self.assertFalse(app.exception)
                revised = app.session_state["company_review"]
                self.assertNotEqual(revised["profile"]["profile_version"], original_version)
                self.assertEqual(revised["decisions"][0]["decision"], "accepted")
                self.assertEqual(revised["decisions"][0]["source_path"], "Ship_Ref")
                self.assertNotIn("Approved company files", app.selectbox(key="shipment_source").options)


if __name__ == "__main__":
    unittest.main()
