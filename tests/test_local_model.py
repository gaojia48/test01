from pathlib import Path
import unittest

from agent.local_model import render_local_analysis, understand_operations_text
from agent.skill_loader import load_skills


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LocalModelTest(unittest.TestCase):
    def test_understands_long_operations_text_and_selects_skills(self):
        skills = load_skills(PROJECT_ROOT)
        text = """
        昨晚 23 点后用户反馈网站访问慢，部分接口返回 502。
        nginx error.log 里有 upstream timed out 和 connect() failed (111: Connection refused)。
        app.log 里同时出现 No space left on device。
        sshd 日志里还有 Failed password for invalid user admin from 203.0.113.10。
        """

        result = understand_operations_text(text, skills=skills, max_skills=4)

        self.assertEqual(result.intent, "故障诊断")
        self.assertIn("log_analyze", result.selected_skills)
        self.assertIn("network_check", result.selected_skills)
        self.assertIn("disk_check", result.selected_skills)
        self.assertGreater(result.confidence, 0.6)
        self.assertTrue(any(signal.category == "web_gateway" for signal in result.signals))

    def test_render_local_analysis_outputs_diagnosis_sections(self):
        report = render_local_analysis(
            "bind() to 0.0.0.0:80 failed (98: Address already in use)",
            analysis_type="error",
            source_name="inline",
        )

        self.assertIn("本地运维模型分析", report)
        self.assertIn("端口冲突", report)
        self.assertIn("排查顺序建议", report)


if __name__ == "__main__":
    unittest.main()
