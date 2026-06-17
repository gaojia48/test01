from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReportSummary:
    path: Path
    title: str
    engine: str
    severity: str
    excerpt: str


def export_report_center(reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    reports = _load_reports(reports_dir)
    html_path = reports_dir / "index.html"
    html_path.write_text(_render_index(reports), encoding="utf-8")
    return html_path


def _load_reports(reports_dir: Path) -> list[ReportSummary]:
    paths = sorted(
        (path for path in reports_dir.glob("*.md") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [_summarize_report(path) for path in paths[:50]]


def _summarize_report(path: Path) -> ReportSummary:
    content = path.read_text(encoding="utf-8", errors="replace")
    title = _extract_title(content) or path.name
    engine = _extract_field(content, "Engine") or _extract_field(content, "执行来源") or "unknown"
    severity = _infer_severity(content)
    excerpt = _clean_excerpt(content)
    return ReportSummary(path=path, title=title, engine=engine, severity=severity, excerpt=excerpt)


def _render_index(reports: list[ReportSummary]) -> str:
    latest = reports[0] if reports else None
    cards = "\n".join(_render_card(report, is_latest=(index == 0)) for index, report in enumerate(reports))
    latest_block = _render_latest(latest) if latest else "<section><h2>暂无报告</h2><p>运行一次分析后这里会自动更新。</p></section>"
    samples = _render_samples()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Linux Ops Agent Report Center</title>
  <style>
    :root {{ --bg: #f5f7fb; --panel: #ffffff; --text: #172033; --muted: #667085; --line: #d8dee9; --blue: #1f6feb; --red: #b42318; --amber: #b54708; --green: #067647; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }}
    header {{ padding: 28px 36px 18px; background: #0f172a; color: white; }}
    header h1 {{ margin: 0 0 8px; }}
    header p {{ margin: 0; color: #cbd5e1; }}
    main {{ padding: 24px 36px 40px; display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.6fr); gap: 22px; }}
    section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 18px; margin-bottom: 18px; }}
    h2 {{ margin: 0 0 12px; }}
    .toolbar {{ display: flex; gap: 10px; margin-bottom: 14px; }}
    input {{ width: 100%; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; font-size: 14px; }}
    .card {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; margin-bottom: 12px; background: white; }}
    .card.latest {{ border-color: var(--blue); box-shadow: 0 0 0 2px rgba(31, 111, 235, .08); }}
    .meta {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 8px 0; color: var(--muted); font-size: 13px; }}
    .badge {{ border-radius: 999px; padding: 3px 8px; background: #eef2ff; color: #3730a3; }}
    .sev-high {{ background: #fee4e2; color: var(--red); }}
    .sev-medium {{ background: #fef0c7; color: var(--amber); }}
    .sev-low {{ background: #dcfae6; color: var(--green); }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #0f172a; color: #dbeafe; padding: 16px; border-radius: 8px; max-height: 580px; overflow: auto; }}
    code {{ background: #eef2ff; padding: 2px 5px; border-radius: 4px; }}
    a {{ color: var(--blue); text-decoration: none; }}
    button {{ border: 0; background: var(--blue); color: white; border-radius: 7px; padding: 8px 12px; font-weight: 600; }}
    .sample {{ margin: 10px 0; padding: 10px; border: 1px dashed var(--line); border-radius: 8px; background: #fafcff; }}
    @media (max-width: 900px) {{ main {{ grid-template-columns: 1fr; padding: 18px; }} header {{ padding: 24px 18px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Linux Ops Agent Report Center</h1>
    <p>静态报告中心，不需要 Web 端口。复制或下载这个 HTML 文件即可展示。</p>
  </header>
  <main>
    <div>
      {latest_block}
      <section>
        <h2>历史报告</h2>
        <div class="toolbar"><input id="q" placeholder="搜索报告名、引擎、关键字..." oninput="filterCards()"></div>
        <div id="cards">{cards or '<p>暂无历史报告。</p>'}</div>
      </section>
    </div>
    <aside>
      {samples}
      <section>
        <h2>常用命令</h2>
        <p><code>python main.py --analyze-shell</code></p>
        <p><code>python main.py --export-html</code></p>
        <p><code>python main.py --skill auto_inspect</code></p>
      </section>
    </aside>
  </main>
  <script>
    function filterCards() {{
      const q = document.getElementById('q').value.toLowerCase();
      document.querySelectorAll('.card').forEach(card => {{
        card.style.display = card.innerText.toLowerCase().includes(q) ? '' : 'none';
      }});
    }}
    async function copySample(id) {{
      const text = document.getElementById(id).innerText;
      await navigator.clipboard.writeText(text);
    }}
  </script>
</body>
</html>"""


def _render_latest(report: ReportSummary) -> str:
    content = report.path.read_text(encoding="utf-8", errors="replace")
    return f"""<section>
      <h2>最新报告</h2>
      {_meta(report)}
      <pre>{html.escape(content)}</pre>
    </section>"""


def _render_card(report: ReportSummary, is_latest: bool) -> str:
    latest_class = " latest" if is_latest else ""
    return f"""<article class="card{latest_class}">
      <h3>{html.escape(report.title)}</h3>
      {_meta(report)}
      <p>{html.escape(report.excerpt)}</p>
      <p><a href="{html.escape(report.path.name)}">打开 Markdown 原文</a></p>
    </article>"""


def _meta(report: ReportSummary) -> str:
    return (
        '<div class="meta">'
        f'<span class="badge sev-{html.escape(report.severity)}">{html.escape(report.severity)}</span>'
        f'<span class="badge">{html.escape(report.engine)}</span>'
        f'<span>{html.escape(report.path.name)}</span>'
        "</div>"
    )


def _render_samples() -> str:
    sample_log = """2026-06-17 23:01:01 nginx error upstream timed out
2026-06-17 23:01:20 app ERROR CustomBusinessException: order 123 failed
2026-06-17 23:02:00 app ERROR CustomBusinessException: order 124 failed
2026-06-17 23:03:11 app ERROR No space left on device"""
    sample_cmd = "python main.py --analyze-shell"
    return f"""<section>
      <h2>演示样例</h2>
      <div class="sample"><pre id="sample-log">{html.escape(sample_log)}</pre><button onclick="copySample('sample-log')">复制日志样例</button></div>
      <div class="sample"><pre id="sample-cmd">{html.escape(sample_cmd)}</pre><button onclick="copySample('sample-cmd')">复制命令</button></div>
    </section>"""


def _extract_title(content: str) -> str:
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _extract_field(content: str, name: str) -> str:
    match = re.search(rf"^-+\s*{re.escape(name)}[:：]\s*(.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    match = re.search(rf"{re.escape(name)}[:：]\s*([^。\n]+)", content)
    return match.group(1).strip() if match else ""


def _infer_severity(content: str) -> str:
    lowered = content.lower()
    if "[high]" in lowered or "high priority" in lowered or "高危" in content:
        return "high"
    if "[medium]" in lowered or "medium priority" in lowered or "异常" in content:
        return "medium"
    return "low"


def _clean_excerpt(content: str, limit: int = 220) -> str:
    value = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    value = re.sub(r"```.*?```", "", value, flags=re.DOTALL)
    value = re.sub(r"#+\s*", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[: limit - 3] + "..."
