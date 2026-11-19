"""Test the normal company preparation journey and bounded archive handling."""

from io import BytesIO
import json
from pathlib import Path
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
            self.assertTrue(any("Mapping preview" in message.value for message in app.markdown))
            next(button for button in app.button if button.label == "Save and use prepared files").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key="shipment_source").value, "Prepared company files")
            next(button for button in app.button if button.label == "Run evaluation").click().run()
            self.assertFalse(app.exception)
            values = {card.label: card.value for card in app.metric}
            self.assertEqual(values["Service outcome"], "Resolved")
            self.assertEqual(values["Human recovery"], "Verified")
            self.assertEqual(values["Initial critical failure"], "Yes")
            analysis = app.session_state["shipment_analysis"][0]
            self.assertIn("readiness_assessment", analysis)
            self.assertEqual(len(analysis["readiness_assessment"]["capabilities"]), 7)
            self.assertEqual(analysis["episodes"][0]["exclusion_reasons"], ["missing_or_invalid_root", "missing_or_invalid_assignment"])
            self.assertTrue(list(Path(directory).glob("import-*/profile.json")))

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


if __name__ == "__main__":
    unittest.main()
