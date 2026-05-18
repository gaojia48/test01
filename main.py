from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent.config import load_config
from agent.executor import SkillExecutor, UnsafeSkillError
from agent.llm_client import DeepSeekClient
from agent.planner import Planner
from agent.report import create_report
from agent.skill_loader import load_skills


PROJECT_ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Linux 运维诊断 Agent Skills 系统")
    parser.add_argument("request", nargs="?", help="自然语言运维问题，例如：检查磁盘空间问题")
    parser.add_argument("--list-skills", action="store_true", help="列出可用 skills")
    parser.add_argument("--skill", help="直接执行指定 skill")
    parser.add_argument("--report", choices=["daily"], help="生成固定巡检报告")
    parser.add_argument("--no-llm", action="store_true", help="禁用 DeepSeek，使用本地关键词模式")
    return parser


def list_skills(skills) -> None:
    for skill in skills.values():
        print(f"- {skill.name}: {skill.description} [{skill.risk_level}]")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(PROJECT_ROOT)
    skills = load_skills(PROJECT_ROOT)

    if args.list_skills:
        list_skills(skills)
        return 0

    user_request = args.request or ""
    selected_names: tuple[str, ...]
    plan = None
    use_llm = not args.no_llm
    llm_client = DeepSeekClient(config.deepseek)

    if args.skill:
        if args.skill not in skills:
            print(f"Unknown skill: {args.skill}", file=sys.stderr)
            return 2
        from agent.planner import Plan

        selected_names = (args.skill,)
        plan = Plan(skills=selected_names, reason="用户指定 skill", source="manual")
        user_request = user_request or f"执行 {args.skill}"
    elif args.report == "daily":
        from agent.planner import Plan

        selected_names = ("health_report",)
        plan = Plan(skills=selected_names, reason="用户请求每日巡检报告", source="manual")
        user_request = user_request or "生成今日服务器巡检报告"
    else:
        if not user_request:
            print("Please provide a request, --skill, --report daily, or --list-skills.", file=sys.stderr)
            return 2
        planner = Planner(
            skills,
            llm_client=llm_client,
            max_skills=config.agent.max_skills_per_request,
        )
        plan = planner.plan(user_request, use_llm=use_llm)
        if plan.refused:
            print(f"拒绝执行：{plan.refusal_reason}")
            return 1
        selected_names = plan.skills

    selected_skills = [skills[name] for name in selected_names if name in skills]
    if not selected_skills:
        print("No executable skills were selected.", file=sys.stderr)
        return 1

    print(f"请求：{user_request}")
    print(f"选择方式：{plan.source}")
    print(f"选择原因：{plan.reason}")
    print(f"执行 skills：{', '.join(skill.name for skill in selected_skills)}")
    print()

    executor = SkillExecutor(PROJECT_ROOT, config.execution)
    results = []
    for skill in selected_skills:
        try:
            result = executor.run(skill)
        except UnsafeSkillError as exc:
            print(f"[{skill.name}] refused: {exc}", file=sys.stderr)
            continue
        results.append(result)
        status = "OK" if result.ok else "FAILED"
        print(f"[{skill.name}] {status} exit={result.exit_code} duration={result.duration_seconds:.2f}s")
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)

    if not results:
        print("No skill results were produced.", file=sys.stderr)
        return 1

    report_path = create_report(
        user_request=user_request,
        plan=plan,
        selected_skills=selected_skills,
        results=results,
        reports_dir=config.execution.reports_dir,
        llm_client=llm_client,
        use_llm=use_llm,
    )

    print()
    print(f"报告已生成：{report_path}")
    print(report_path.read_text(encoding="utf-8")[:4000])
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
