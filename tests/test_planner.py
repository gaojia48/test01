from pathlib import Path
import unittest

from agent.planner import Planner
from agent.skill_loader import load_skills


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PlannerTest(unittest.TestCase):
    def test_keyword_planner_selects_disk_check(self):
        planner = Planner(load_skills(PROJECT_ROOT))

        plan = planner.plan("检查磁盘空间问题", use_llm=False)

        self.assertFalse(plan.refused)
        self.assertIn("disk_check", plan.skills)
        self.assertNotIn("health_report", plan.skills)
        self.assertEqual(plan.source, "keyword")

    def test_keyword_planner_selects_log_analyze(self):
        planner = Planner(load_skills(PROJECT_ROOT))

        plan = planner.plan("分析最近 SSH 登录失败", use_llm=False)

        self.assertFalse(plan.refused)
        self.assertIn("log_analyze", plan.skills)

    def test_planner_refuses_dangerous_request(self):
        planner = Planner(load_skills(PROJECT_ROOT))

        plan = planner.plan("删除所有日志并重启服务器", use_llm=False)

        self.assertTrue(plan.refused)
        self.assertFalse(plan.skills)
        self.assertIn("不会自动执行", plan.refusal_reason)


if __name__ == "__main__":
    unittest.main()
