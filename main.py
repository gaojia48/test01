#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import sys
from pathlib import Path

from agent.config import load_config
from agent.executor import SkillExecutor, UnsafeSkillError
from agent.llm_client import DeepSeekClient
from agent.planner import Planner
from agent.report import create_report
from agent.skill_loader import load_skills
from agent.static_report import export_report_center
from agent.text_analysis import analyze_text, write_analysis_report
from agent.web_app import run_web_app


PROJECT_ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Linux 运维诊断 Agent Skills 系统")
    parser.add_argument("request", nargs="*", help="自然语言运维问题，例如：检查磁盘空间问题")
    parser.add_argument("--interactive", "-i", action="store_true", help="进入交互模式，连续输入运维问题")
    parser.add_argument("--list-skills", action="store_true", help="列出可用 skills")
    parser.add_argument("--skill", help="直接执行指定 skill")
    parser.add_argument("--report", choices=["daily"], help="生成固定巡检报告")
    parser.add_argument("--analyze-file", type=Path, help="分析日志、命令输出、配置片段或事故记录文件")
    parser.add_argument("--analyze-stdin", action="store_true", help="从标准输入读取大量运维文本并分析")
    parser.add_argument("--analyze-text", help="直接分析一段运维文本")
    parser.add_argument("--analyze-shell", action="store_true", help="进入分析模式 Shell，粘贴多行文本后输入 END 开始分析")
    parser.add_argument("--web", action="store_true", help="启动 Web 页面，用于粘贴文本分析和查看报告")
    parser.add_argument("--web-host", default="127.0.0.1", help="Web 监听地址，服务器演示可用 0.0.0.0")
    parser.add_argument("--web-port", type=int, default=8000, help="Web 监听端口")
    parser.add_argument("--export-html", action="store_true", help="导出静态 HTML 报告中心到 reports/index.html")
    parser.add_argument(
        "--analysis-type",
        default="auto",
        choices=["auto", "log", "command", "config", "incident", "error"],
        help="运维文本类型，用于指导 DeepSeek 或本地规则分析",
    )
    parser.add_argument("--no-llm", action="store_true", help="禁用 DeepSeek，使用本地关键词模式")
    parser.add_argument("--cloud-llm", action="store_true", help="启用 DeepSeek 云端增强；默认使用本地运维模型")
    return parser


def list_skills(skills) -> None:
    for skill in skills.values():
        print(f"- {skill.name}: {skill.description} [{skill.risk_level}]")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    use_llm = args.cloud_llm and not args.no_llm
    if args.interactive:
        return interactive_main(use_llm=use_llm)

    config = load_config(PROJECT_ROOT)
    skills = load_skills(PROJECT_ROOT)
    llm_client = DeepSeekClient(config.deepseek)

    if args.list_skills:
        list_skills(skills)
        return 0

    if args.web:
        run_web_app(args.web_host, args.web_port, config, llm_client, skills)
        return 0

    if args.export_html:
        html_path = export_report_center(config.execution.reports_dir)
        print(f"HTML 报告中心已生成：{html_path}")
        return 0

    if args.analyze_shell:
        return _analysis_shell(
            config=config,
            llm_client=llm_client,
            use_llm=use_llm,
            skills=skills,
            analysis_type=args.analysis_type,
        )

    if args.analyze_file or args.analyze_stdin or args.analyze_text:
        return _run_text_analysis(
            analyze_file=args.analyze_file,
            analyze_stdin=args.analyze_stdin,
            analyze_text_value=args.analyze_text,
            analysis_type=args.analysis_type,
            config=config,
            llm_client=llm_client,
            use_llm=use_llm,
            skills=skills,
        )

    user_request = " ".join(args.request).strip()
    selected_names: tuple[str, ...]
    plan = None

    if user_request.lower() in {"doctor", "check env", "自检", "环境检查"}:
        return _run_doctor()

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
    html_path = export_report_center(config.execution.reports_dir)
    print(f"HTML 报告中心已更新：{html_path}")
    print(report_path.read_text(encoding="utf-8")[:4000])
    return 0 if all(result.ok for result in results) else 1


def interactive_main(use_llm: bool = True) -> int:
    print("Linux Ops Agent 交互模式")
    print("直接输入问题，例如：检查磁盘空间问题")
    print("输入 help 查看命令，输入 exit 退出。")
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
        if text in {"help", "帮助", "?"}:
            _print_interactive_help()
            code = 0
        elif text in {"list", "skills", "技能"}:
            code = main(["--list-skills"])
        elif text in {"reports", "ls reports", "报告列表"}:
            code = _list_reports()
        elif text in {"last report", "last", "latest report", "最新报告", "查看最新报告"}:
            code = _show_last_report()
        elif text in {"doctor", "check env", "自检", "环境检查"}:
            code = _run_doctor()
        elif text in {"clear reports", "clean reports", "清空报告", "清除报告"}:
            code = _clear_reports()
        elif text in {"daily", "report", "巡检", "报告"}:
            args = ["--report", "daily"]
            args.append("--cloud-llm" if use_llm else "--no-llm")
            code = main(args)
        elif text in {"analysis shell", "analyze shell", "local shell"}:
            code = main(["--analyze-shell", "--no-llm"])
        elif text in {"deepseek shell", "cloud shell"}:
            code = main(["--analyze-shell", "--cloud-llm"])
        elif text.startswith("analyze "):
            args = ["--analyze-file", text.removeprefix("analyze ").strip()]
            args.append("--cloud-llm" if use_llm else "--no-llm")
            code = main(args)
        elif text.startswith("analyze-text "):
            args = ["--analyze-text", text.removeprefix("analyze-text ").strip()]
            args.append("--cloud-llm" if use_llm else "--no-llm")
            code = main(args)
        else:
            args = [text]
            args.append("--cloud-llm" if use_llm else "--no-llm")
            code = main(args)

        print(f"\n本次执行完成，退出码：{code}\n")


def _print_interactive_help() -> None:
    print("可用命令：")
    print("  list              查看 skills")
    print("  reports           查看已生成报告")
    print("  last report       查看最新报告内容")
    print("  doctor            检查运行环境和配置")
    print("  clear reports     清空 reports 目录里的报告")
    print("  daily             生成综合巡检报告")
    print("  analyze <file>    分析日志、命令输出、配置片段或事故记录文件")
    print("  analyze-text <文本> 分析一段报错、命令输出或日志文本")
    print("  analyze-shell     进入粘贴分析模式，输入 END 开始分析")
    print("  deepseek shell    进入 DeepSeek 粘贴分析模式")
    print("  exit              退出")
    print("也可以直接输入自然语言问题，例如：检查磁盘空间问题")


def _analysis_shell(
    config,
    llm_client: DeepSeekClient,
    use_llm: bool,
    skills,
    analysis_type: str = "auto",
) -> int:
    mode_name = "DeepSeek" if use_llm else "local"
    current_type = analysis_type
    print(f"Analysis shell started ({mode_name} mode).")
    print("Paste logs, command output, errors, config, or incident notes.")
    print("Type END on its own line to analyze. Type 'type log|command|config|incident|error|auto' to switch type.")
    print("Type exit to quit.")
    print()

    buffer: list[str] = []
    while True:
        try:
            line = input(f"{mode_name}:{current_type}> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        stripped = line.strip()
        if stripped in {"exit", "quit", "q"}:
            return 0
        if stripped.startswith("type "):
            requested = stripped.removeprefix("type ").strip()
            if requested in {"auto", "log", "command", "config", "incident", "error"}:
                current_type = requested
                print(f"analysis type switched to {current_type}")
            else:
                print("Unknown type. Use auto, log, command, config, incident, or error.")
            continue
        if stripped == "END":
            text = "\n".join(buffer).strip()
            buffer.clear()
            if not text:
                print("No text collected.")
                continue
            analysis = analyze_text(
                text,
                analysis_type=current_type,
                source_name="analysis-shell",
                llm_client=llm_client,
                use_llm=use_llm,
                skills=skills,
            )
            report_path = write_analysis_report(analysis, config.execution.reports_dir)
            html_path = export_report_center(config.execution.reports_dir)
            print(f"Report generated: {report_path}")
            print(f"HTML report center updated: {html_path}")
            print(report_path.read_text(encoding="utf-8")[:4000])
            print()
            continue

        buffer.append(line)


def _run_text_analysis(
    analyze_file: Path | None,
    analyze_stdin: bool,
    analyze_text_value: str | None,
    analysis_type: str,
    config,
    llm_client: DeepSeekClient,
    use_llm: bool,
    skills,
) -> int:
    selected = sum(bool(item) for item in (analyze_file, analyze_stdin, analyze_text_value))
    if selected != 1:
        print("Please provide exactly one of --analyze-file, --analyze-stdin, or --analyze-text.", file=sys.stderr)
        return 2

    source_name = "stdin"
    if analyze_file:
        source_name = str(analyze_file)
        if not analyze_file.exists() or not analyze_file.is_file():
            print(f"Analysis file not found: {analyze_file}", file=sys.stderr)
            return 2
        text = analyze_file.read_text(encoding="utf-8", errors="replace")
    elif analyze_stdin:
        text = sys.stdin.read()
    else:
        source_name = "inline text"
        text = analyze_text_value or ""

    if not text.strip():
        print("No analysis text was provided.", file=sys.stderr)
        return 2

    analysis = analyze_text(
        text,
        analysis_type=analysis_type,
        source_name=source_name,
        llm_client=llm_client,
        use_llm=use_llm,
        skills=skills,
    )
    report_path = write_analysis_report(analysis, config.execution.reports_dir)
    html_path = export_report_center(config.execution.reports_dir)
    print(f"文本分析报告已生成：{report_path}")
    print(f"HTML 报告中心已更新：{html_path}")
    print(report_path.read_text(encoding="utf-8")[:4000])
    return 0


def _list_reports() -> int:
    reports_dir = PROJECT_ROOT / "reports"
    if not reports_dir.exists():
        print("reports 目录还不存在。")
        return 0

    reports = sorted(reports_dir.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not reports:
        print("reports 目录里没有报告。")
        return 0

    for path in reports:
        size_kb = path.stat().st_size / 1024
        print(f"- {path.name} ({size_kb:.1f} KB)")
    return 0


def _show_last_report() -> int:
    report = _find_latest_report(PROJECT_ROOT / "reports")
    if not report:
        print("reports 目录里没有报告。")
        return 0

    print(f"最新报告：{report.name}")
    print()
    print(report.read_text(encoding="utf-8"))
    return 0


def _find_latest_report(reports_dir: Path) -> Path | None:
    if not reports_dir.exists():
        return None
    reports = [path for path in reports_dir.glob("*.md") if path.is_file()]
    if not reports:
        return None
    return max(reports, key=lambda path: path.stat().st_mtime)


def _run_doctor() -> int:
    print("Linux Ops Agent 环境自检")
    print()

    checks: list[tuple[str, bool, str]] = []
    checks.append(("Python 版本", sys.version_info >= (3, 10), sys.version.split()[0]))
    checks.append(("项目目录", PROJECT_ROOT.exists(), str(PROJECT_ROOT)))

    config_ok = True
    try:
        config = load_config(PROJECT_ROOT)
        checks.append(("config.yaml", True, "已加载"))
    except Exception as exc:
        config_ok = False
        config = None
        checks.append(("config.yaml", False, str(exc)))

    try:
        skills = load_skills(PROJECT_ROOT)
        checks.append(("skills 配置", True, f"{len(skills)} 个 skill"))
    except Exception as exc:
        skills = {}
        checks.append(("skills 配置", False, str(exc)))

    for module in ("openai", "dotenv", "yaml", "pytest"):
        checks.append((f"Python 依赖 {module}", importlib.util.find_spec(module) is not None, module))

    if config_ok and config:
        llm_client = DeepSeekClient(config.deepseek)
        checks.append(("DeepSeek API Key", llm_client.available, "已读取" if llm_client.available else "未读取"))
        checks.append(("DeepSeek base_url", bool(llm_client.base_url), llm_client.base_url))
        checks.append(("DeepSeek model", bool(llm_client.model), llm_client.model))

    proxy_parts = []
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        value = os.environ.get(key)
        if value:
            proxy_parts.append(f"{key}={value}")
    checks.append(("代理环境变量", True, "; ".join(proxy_parts) if proxy_parts else "未设置"))

    for command in ("bash", "df", "du", "find", "grep", "sed", "awk", "ps", "ss", "ip", "ping", "journalctl"):
        checks.append((f"Linux 命令 {command}", shutil.which(command) is not None, shutil.which(command) or "未找到"))

    scripts_dir = PROJECT_ROOT / "scripts"
    script_paths = sorted(scripts_dir.glob("*.sh"))
    checks.append(("scripts 目录", bool(script_paths), f"{len(script_paths)} 个脚本"))
    for script in script_paths:
        checks.append((f"脚本可执行 {script.name}", os.access(script, os.X_OK), str(script)))

    failed = 0
    for name, ok, detail in checks:
        mark = "OK" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{mark}] {name}: {detail}")

    print()
    if failed:
        print(f"自检完成：发现 {failed} 个问题。")
        return 1
    print("自检完成：环境看起来正常。")
    return 0


def _clear_reports() -> int:
    reports_dir = PROJECT_ROOT / "reports"
    if not reports_dir.exists():
        print("reports 目录还不存在。")
        return 0

    removed = 0
    for path in reports_dir.glob("*.md"):
        path.unlink()
        removed += 1

    test_output = reports_dir / "test-output"
    if test_output.exists():
        shutil.rmtree(test_output)

    print(f"已清除 {removed} 个报告文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
