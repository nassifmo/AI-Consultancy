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
from evaluator.claim_reader import EtaReading, ReplyClaims, StatusClaim
from evaluator.exports import TABLES


ROOT = Path(__file__).resolve().parents[1]


def zip_bytes(entries):
    body = BytesIO()
    with ZipFile(body, mode="w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return body.getvalue()


class InterfaceTests(unittest.TestCase):
    def test_local_reply_reader_shows_evidence_and_records_its_run(self):
        messages = []

        class FixtureReader:
            provider = "ollama"
            reads = 1

            def __init__(self, model, *, max_reads):
                self.model, self.max_reads = model, max_reads

            def __call__(self, text):
                messages.append(text)
                return ReplyClaims(status_claims=(StatusClaim("departed", "vessel", "The vessel has departed."),))

            def interpret_eta(self, question, reply):
                return EtaReading(intent="arrival_time", response="provided", request_quote=question,
                                  reply_quote="The current Rotterdam ETA is 16 March at 11:00 local time.")

        with patch("evaluator.claim_reader.OllamaClaimReader", FixtureReader):
            app = AppTest.from_file(ROOT / "app.py", default_timeout=12).run()
            app.selectbox[0].select("S28 · Vessel status and ETA")
            app.checkbox(key="shipment_read_claims").check()
            next(button for button in app.button if button.label == "Run evaluation").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(messages and all("The vessel has departed." in text for text in messages))
        self.assertTrue(any(heading.value == "Claims in sent replies" for heading in app.subheader))
        self.assertTrue(any("Local model calls 1 of 25 allowed" in item.value for item in app.caption))
        result, _, policy = app.session_state["shipment_analysis"]
        provenance = result["run_provenance"]["claim_extraction"]
        self.assertEqual(provenance["model"], "qwen2.5:7b-instruct")
        self.assertEqual(len(provenance["findings_sha256"]), 64)
        assessment = result["enquiries"][0]["verification"]["initial_reply"]["reply_claims"]
        self.assertEqual(assessment["findings"][0]["verdict"], "supported")
        reading = result["enquiries"][0]["verification"]["initial_reply"]["eta_interpretation"]
        self.assertEqual(reading["intent"], "arrival_time")
        self.assertIn("Rotterdam", reading["request_quote"])
        rules_only = analyze_exports(ROOT / "datagen/datasets/scenarios/S28/exports", policy)
        self.assertNotEqual(result["run_provenance"]["run_id"], rules_only["run_provenance"]["run_id"])

    def test_evaluation_review_rerun_and_download(self):
        app = AppTest.from_file(ROOT / "app.py", default_timeout=12).run()
        self.assertFalse(app.exception)
        app.selectbox[0].select("S32 · Wrong container with human recovery")
        next(button for button in app.button if button.label == "Run evaluation").click().run()
        self.assertFalse(app.exception)
        self.assertEqual([tab.label for tab in app.tabs],
                         ["Data readiness", "Comparison", "Upgrade value", "Enquiry evidence", "Costs and settings"])
        values = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(values.get("Initial AI critical failure"), "Yes")
        self.assertEqual(values.get("Human recovery"), "Verified")
        self.assertEqual(values.get("Service outcome"), "Resolved")
        self.assertTrue(any("The error still counts against the AI." in item.value for item in app.warning))
        app.number_input[0].set_value(8)
        next(button for button in app.button if button.label == "Run evaluation").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("8 days of comparison follow-up" in message.value for message in app.caption))
        next(button for button in app.button if button.label == "Prepare downloads").click().run()
        self.assertFalse(app.exception)
        downloads = [button.label for button in app.get("download_button")
                     if button.label != "Download all data issues"]
        self.assertEqual(len(downloads), 4)

    def test_upgrade_view_uses_the_selected_business_outcome_and_assumed_value(self):
        app = AppTest.from_file(ROOT / "app.py", default_timeout=25).run()
        app.number_input[1].set_value(200)
        next(button for button in app.button if button.label == "Run evaluation").click().run()
        self.assertFalse(app.exception)
        threshold = "Break-even value per extra success"
        self.assertEqual(next(metric.value for metric in app.metric if metric.label == threshold), "9.73 USD")
        self.assertTrue(any("Agree on the critical failure limit" in item.value for item in app.markdown))
        next(item for item in app.number_input if item.label == "Maximum critical failure rate (%)").set_value(1.0).run()
        self.assertTrue(any("Review failures and retest" in item.value for item in app.markdown))
        self.assertTrue(any("7 of 348 eligible enquiries" in item.value for item in app.markdown))
        self.assertTrue(any("Shipment or container mismatch · 6 enquiries" in item.value for item in app.markdown))
        self.assertTrue(any("Required escalation step missed · 1 enquiry" in item.value for item in app.markdown))
        app.selectbox(key="upgrade_priority").select("verified_resolution").run()
        self.assertFalse(app.exception)
        self.assertEqual(next(metric.value for metric in app.metric if metric.label == threshold), "24.35 USD")
        next(item for item in app.number_input if item.label.startswith("Value of one additional success")).set_value(25.0).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("unknown outcomes leave" in warning.value for warning in app.warning))
        loss_input = next(item for item in app.number_input if item.label.startswith("Assumed additional loss"))
        loss_input.set_value(1000.0).run()
        self.assertFalse(app.exception)
        metrics = {item.label: item.value for item in app.metric}
        self.assertIn("Illustrative net value per request with assumed loss", metrics)
        self.assertAlmostEqual(float(metrics["Cost change per request with assumed loss"].split()[0]),
                               float(metrics["Cost change per request"].split()[0]) + 1, places=2)

    def test_decision_value_and_approval_are_scoped_to_the_outcome(self):
        app = AppTest.from_file(ROOT / "app.py", default_timeout=25).run()
        app.number_input[1].set_value(200)
        next(button for button in app.button if button.label == "Run evaluation").click().run()

        def get_widget(widgets, label):
            return next(item for item in widgets if item.label.startswith(label))

        get_widget(app.number_input, "Value of one additional success").set_value(20.0).run()
        get_widget(app.selectbox, "Basis for the value").select("company_estimate").run()
        get_widget(app.text_input, "Source or assumption").set_value("Approved for this $20 scenario").run()
        get_widget(app.number_input, "Value of one additional success").set_value(25.0).run()
        self.assertEqual(get_widget(app.selectbox, "Basis for the value").value, "illustrative")
        self.assertFalse(any(item.label.startswith("Source or assumption") for item in app.text_input))

        get_widget(app.selectbox, "Basis for the value").select("company_estimate").run()
        get_widget(app.text_input, "Source or assumption").set_value("Approval for one-hour outcome only").run()
        get_widget(app.number_input, "Resolution time target").set_value(120).run()
        self.assertFalse(app.exception)
        self.assertIsNone(get_widget(app.number_input, "Value of one additional success").value)
        self.assertEqual(get_widget(app.selectbox, "Basis for the value").value, "illustrative")
        self.assertFalse(any(item.label.startswith("Source or assumption") for item in app.text_input))

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

    def test_unlabeled_zip_requires_the_sent_eta(self):
        source = ROOT / "datagen/datasets/scenarios/S28/exports"
        policy = json.loads((ROOT / "evaluator/policy.json").read_text(encoding="utf-8"))
        entries = {f"exports/{path.name}": path.read_bytes() for path in source.iterdir()}
        metadata = json.loads(entries["exports/export_metadata.json"])
        metadata.pop("dataset_origin")
        metadata["source_completeness"] = dict.fromkeys(TABLES, "complete")
        entries["exports/export_metadata.json"] = json.dumps(metadata)
        messages = (
            ("The vessel has departed.", "failed"),
            ("The current Rotterdam ETA is 16 March at 11:00 local time.", "resolved"),
        )
        original = entries["exports/responses.csv"]
        for message, outcome in messages:
            with self.subTest(message=message):
                entries["exports/responses.csv"] = original.replace(
                    b"The vessel has departed. The current Rotterdam ETA is 16 March at 11:00 local time.",
                    message.encode("utf-8"),
                )
                with unpack_exports(zip_bytes(entries.items())) as exports:
                    result = analyze_exports(exports, policy)
                self.assertEqual(result["data_readiness"]["dataset_origin"], "unconfirmed")
                enquiry = result["enquiries"][0]
                self.assertEqual(enquiry["outcome"]["state"], outcome)
                if outcome == "failed":
                    self.assertEqual(enquiry["criteria"]["eta_accuracy"]["status"], "unknown")
                    self.assertEqual(enquiry["criteria"]["eta_request_answered"]["status"], "unmet")

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
