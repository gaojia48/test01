from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from agent.config import AppConfig
from agent.llm_client import DeepSeekClient
from agent.skill_loader import Skill
from agent.text_analysis import analyze_text, write_analysis_report


ANALYSIS_TYPES = ("auto", "log", "command", "config", "incident", "error")


def run_web_app(
    host: str,
    port: int,
    config: AppConfig,
    llm_client: DeepSeekClient,
    skills: dict[str, Skill],
) -> None:
    handler = _make_handler(config, llm_client, skills)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Web UI running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


def _make_handler(config: AppConfig, llm_client: DeepSeekClient, skills: dict[str, Skill]):
    class OpsRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/reports/"):
                self._serve_report()
                return
            self._send_html(_render_home(config.execution.reports_dir))

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            form = parse_qs(body)
            text = form.get("text", [""])[0]
            analysis_type = form.get("analysis_type", ["auto"])[0]
            engine = form.get("engine", ["local"])[0]
            if analysis_type not in ANALYSIS_TYPES:
                analysis_type = "auto"
            use_llm = engine == "deepseek"

            if not text.strip():
                self._send_html(_render_home(config.execution.reports_dir, error="请输入要分析的文本。"))
                return

            analysis = analyze_text(
                text,
                analysis_type=analysis_type,
                source_name="web",
                llm_client=llm_client,
                use_llm=use_llm,
                skills=skills,
            )
            report_path = write_analysis_report(analysis, config.execution.reports_dir)
            self._send_html(_render_home(config.execution.reports_dir, report_path=report_path, report=report_path.read_text(encoding="utf-8")))

        def _serve_report(self) -> None:
            name = Path(self.path.removeprefix("/reports/")).name
            path = config.execution.reports_dir / name
            if not path.exists() or not path.is_file():
                self.send_error(404)
                return
            self._send_html(_page("Report", f"<pre>{html.escape(path.read_text(encoding='utf-8', errors='replace'))}</pre>"))

        def _send_html(self, content: str) -> None:
            encoded = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args) -> None:
            return

    return OpsRequestHandler


def _render_home(reports_dir: Path, report_path: Path | None = None, report: str = "", error: str = "") -> str:
    recent = _recent_reports(reports_dir)
    options = "\n".join(f'<option value="{item}">{item}</option>' for item in ANALYSIS_TYPES)
    report_block = ""
    if report_path and report:
        report_block = (
            f"<h2>分析结果</h2><p>报告已生成：<code>{html.escape(str(report_path))}</code></p>"
            f"<pre>{html.escape(report)}</pre>"
        )
    error_block = f'<p class="error">{html.escape(error)}</p>' if error else ""
    recent_items = "".join(
        f'<li><a href="/reports/{html.escape(path.name)}">{html.escape(path.name)}</a></li>' for path in recent
    ) or "<li>暂无报告</li>"
    body = f"""
    <h1>Linux Ops Agent</h1>
    <section>
      <h2>文本 / 日志 / 命令输出分析</h2>
      {error_block}
      <form method="post">
        <div class="row">
          <label>分析类型
            <select name="analysis_type">{options}</select>
          </label>
          <label>分析引擎
            <select name="engine">
              <option value="local">本地运维模型</option>
              <option value="deepseek">DeepSeek 云端增强</option>
            </select>
          </label>
        </div>
        <textarea name="text" placeholder="粘贴日志、命令输出、报错、配置片段或事故记录"></textarea>
        <button type="submit">开始分析</button>
      </form>
    </section>
    {report_block}
    <section>
      <h2>最近报告</h2>
      <ul>{recent_items}</ul>
    </section>
    """
    return _page("Linux Ops Agent", body)


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; background: #f6f8fb; color: #172033; }}
    h1 {{ margin-top: 0; }}
    section {{ background: white; border: 1px solid #d8dee9; border-radius: 8px; padding: 20px; margin: 18px 0; }}
    textarea {{ width: 100%; min-height: 260px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 14px; margin: 12px 0; }}
    button {{ background: #1f6feb; color: white; border: 0; border-radius: 6px; padding: 10px 16px; font-weight: 600; }}
    select {{ margin-left: 8px; margin-right: 20px; padding: 6px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #0f172a; color: #dbeafe; padding: 16px; border-radius: 8px; }}
    code {{ background: #eef2ff; padding: 2px 5px; border-radius: 4px; }}
    .row {{ display: flex; gap: 16px; flex-wrap: wrap; }}
    .error {{ color: #b42318; font-weight: 600; }}
  </style>
</head>
<body>{body}</body>
</html>"""


def _recent_reports(reports_dir: Path, limit: int = 10) -> list[Path]:
    if not reports_dir.exists():
        return []
    reports = [path for path in reports_dir.glob("*.md") if path.is_file()]
    return sorted(reports, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
