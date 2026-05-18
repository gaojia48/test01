#!/usr/bin/env python3
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
    parser.add_argument("request", nargs="*", help="自然语言运维问题，例如：检查磁盘空间问题")
    parser.add_argument("--interactive", "-i", action="store_true", help="进入交互模式，连续输入运维问题")
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
    if args.interactive:
        return interactive_main(use_llm=not args.no_llm)

    config = load_config(PROJECT_ROOT)
    skills = load_skills(PROJECT_ROOT)

    if args.list_skills:
        list_skills(skills)
        return 0

    user_request = " ".join(args.request).strip()
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
        if use_llm and plan.source != "deepseek":
            if llm_client.last_error:
                print(f"DeepSeek 未启用，已回退本地模式：{llm_client.last_error}")
            elif not llm_client.available:
                print("DeepSeek 未启用，已回退本地模式：没有读取到 DEEPSEEK_API_KEY")
        if plan.refused:
            print(f"拒绝执行：{plan.refusal_reason}")
            return 1
        selected_names = plan.skills

    selected_skills = [skills[name] for name in selected_names if name in skills]
    if not selected_skills:
        print(f"请求：{user_request}")
        print(f"选择方式：{plan.source}")
        print(f"选择原因：{plan.reason}")
        print("执行 skills：无")
        if plan.answer:
            print()
            print(plan.answer)
        else:
            print()
            print("没有匹配到明确的 Linux 运维 skill，因此没有执行任何脚本。")
            if use_llm and llm_client.last_error:
                print(f"DeepSeek 普通回答不可用：{llm_client.last_error}")
        return 0

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


def interactive_main(use_llm: bool = True) -> int:
    print("Linux Ops Agent 交互模式")
    print("直接输入问题，例如：检查磁盘空间问题")
    print("输入 list 查看 skills，输入 daily 生成巡检报告，输入 exit 退出。")
    print()

    while True:
        try:
            text = input("ops> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not text:
            continue
        if text in {"exit", "quit", "退出", "q"}:
            return 0
        if text in {"list", "skills", "技能"}:
            code = main(["--list-skills"])
        elif text in {"daily", "report", "巡检", "报告"}:
            args = ["--report", "daily"]
            if not use_llm:
                args.append("--no-llm")
            code = main(args)
        else:
            args = [text]
            if not use_llm:
                args.append("--no-llm")
            code = main(args)

        print(f"\n本次执行完成，退出码：{code}\n")


if __name__ == "__main__":
    raise SystemExit(main())
