from pathlib import Path
import tempfile
import unittest

from agent.static_report import export_report_center


class StaticReportTest(unittest.TestCase):
    def test_export_report_center_creates_index_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            (reports_dir / "20260617-text-analysis.md").write_text(
                "# Operations Text Analysis\n\n- Engine: local_model\n\n### [HIGH] Nginx upstream failure\n",
                encoding="utf-8",
            )

            html_path = export_report_center(reports_dir)

            content = html_path.read_text(encoding="utf-8")
            self.assertIn("Linux Ops Agent Report Center", content)
            self.assertIn("Operations Text Analysis", content)
            self.assertIn("local_model", content)
            self.assertIn("演示样例", content)


if __name__ == "__main__":
    unittest.main()
