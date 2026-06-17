import unittest

from agent.text_analysis import analyze_text, render_analysis_markdown


class TextAnalysisTest(unittest.TestCase):
    def test_local_analysis_detects_common_log_errors(self):
        text = """
        nginx error: connect() failed (111: Connection refused) while connecting to upstream
        app error: No space left on device
        sshd: Failed password for invalid user admin from 10.0.0.8
        """

        analysis = analyze_text(text, analysis_type="log", use_llm=False)

        titles = {finding.title for finding in analysis.findings}
        self.assertIn("Disk space pressure", titles)
        self.assertIn("Service dependency is unavailable", titles)
        self.assertIn("Authentication failures", titles)
        self.assertFalse(analysis.used_llm)
        self.assertEqual(analysis.engine, "local_model")

    def test_render_analysis_markdown_contains_evidence(self):
        analysis = analyze_text("bind() to 0.0.0.0:80 failed (98: Address already in use)", use_llm=False)

        markdown = render_analysis_markdown(analysis)

        self.assertIn("端口冲突", markdown)
        self.assertIn("Address already in use", markdown)

    def test_report_contains_timeline_and_unknown_clusters(self):
        text = """
        2026-06-17 23:01:01 app ERROR CustomBusinessException: order 123 failed
        2026-06-17 23:01:02 app ERROR CustomBusinessException: order 124 failed
        """

        markdown = render_analysis_markdown(analyze_text(text, analysis_type="log", use_llm=False))

        self.assertIn("故障时间线", markdown)
        self.assertIn("未知错误聚类", markdown)


if __name__ == "__main__":
    unittest.main()
