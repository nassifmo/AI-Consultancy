"""Test the local interface and its restricted upload format."""

from io import BytesIO
import json
from pathlib import Path
import stat
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from streamlit.testing.v1 import AppTest

from app import unpack_exports
from evaluator.analysis import analyze_exports


ROOT = Path(__file__).resolve().parents[1]


def zip_bytes(entries):
    body = BytesIO()
    with ZipFile(body, mode="w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return body.getvalue()


class InterfaceTests(unittest.TestCase):
    def test_evaluation_review_rerun_and_download(self):
        app = AppTest.from_file(ROOT / "app.py", default_timeout=12).run()
        self.assertFalse(app.exception)
        app.selectbox[0].select("S32 · Wrong container with human recovery")
        next(button for button in app.button if button.label == "Run evaluation").click().run()
        self.assertFalse(app.exception)
        self.assertEqual([tab.label for tab in app.tabs],
                         ["Data readiness", "Comparison", "Upgrade value", "Enquiry evidence", "Costs and settings"])
        values = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(values.get("Initial critical failure"), "Yes")
        self.assertEqual(values.get("Human recovery"), "Verified")
        self.assertEqual(values.get("Service outcome"), "Resolved")
        app.number_input[0].set_value(8)
        next(button for button in app.button if button.label == "Run evaluation").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("8 days of comparison follow-up" in message.value for message in app.caption))
        next(button for button in app.button if button.label == "Prepare downloads").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("download_button")), 4)

    def test_upgrade_view_uses_the_selected_business_outcome_and_assumed_value(self):
        app = AppTest.from_file(ROOT / "app.py", default_timeout=25).run()
        app.number_input[1].set_value(200)
        next(button for button in app.button if button.label == "Run evaluation").click().run()
        self.assertFalse(app.exception)
        threshold = "Break-even value per extra success"
        self.assertEqual(next(metric.value for metric in app.metric if metric.label == threshold), "9.73 USD")
        self.assertTrue(any("Agree on the critical failure limit" in item.value for item in app.markdown))
        app.number_input(key="decision_critical_limit").set_value(1.0).run()
        self.assertTrue(any("Review failures and retest" in item.value for item in app.markdown))
        app.selectbox(key="upgrade_priority").select("verified_resolution").run()
        self.assertFalse(app.exception)
        self.assertEqual(next(metric.value for metric in app.metric if metric.label == threshold), "24.35 USD")
        app.number_input(key="upgrade_value_verified_resolution_USD").set_value(25.0).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("unknown outcomes leave" in warning.value for warning in app.warning))

    def test_upload_only_materializes_recognized_exports_in_a_temporary_folder(self):
        body = zip_bytes((
            ("exports/export_metadata.json", "{}"),
            ("exports/enquiries.csv", "enquiry_id\nE1\n"),
        ))
        with unpack_exports(body) as path:
            self.assertEqual(path.name, "exports")
            self.assertEqual({file.name for file in path.iterdir()}, {"export_metadata.json", "enquiries.csv"})
        self.assertFalse(path.exists())

    def test_zipped_exports_are_analyzed_with_the_same_provenance(self):
        source = ROOT / "datagen" / "datasets" / "scenarios" / "S32" / "exports"
        body = zip_bytes((f"exports/{path.name}", path.read_bytes()) for path in sorted(source.iterdir()))
        policy = json.loads((ROOT / "evaluator" / "policy.json").read_text(encoding="utf-8"))
        direct = analyze_exports(source, policy)
        with unpack_exports(body) as path:
            uploaded = analyze_exports(path, policy)
        self.assertEqual(uploaded, direct)

    def test_upload_rejects_paths_answers_links_and_excessive_expansion(self):
        common = (("exports/export_metadata.json", "{}"), ("exports/enquiries.csv", "id\n"))
        for filename in ("../outside", "exports/../cases.csv", "ground_truth/answers.json"):
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError), unpack_exports(zip_bytes((*common, (filename, "{}")))):
                    self.fail("Unsafe ZIP was accepted")
        backslash = zip_bytes((*common, ("exports/cases.csv", "{}"))).replace(b"exports/cases.csv", b"exports\\cases.csv")
        with self.assertRaises(ValueError), unpack_exports(backslash):
            self.fail("A backslash in the stored path was accepted")
        link = ZipInfo("exports/cases.csv")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ValueError), unpack_exports(zip_bytes((*common, (link, "elsewhere")))):
            self.fail("ZIP link was accepted")
        with patch("app.MAX_EXPANSION", 1), self.assertRaises(ValueError), unpack_exports(zip_bytes(common)):
            self.fail("Oversized ZIP was accepted")


if __name__ == "__main__":
    unittest.main()
