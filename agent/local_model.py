from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from agent.skill_loader import Skill


@dataclass(frozen=True)
class LocalSignal:
    category: str
    title: str
    severity: str
    evidence: tuple[str, ...]
    recommendation: str
    skill_weights: dict[str, int]


@dataclass(frozen=True)
class LocalUnderstanding:
    intent: str
    symptoms: tuple[str, ...]
    entities: tuple[str, ...]
    signals: tuple[LocalSignal, ...]
    selected_skills: tuple[str, ...]
    reason: str
    confidence: float


@dataclass(frozen=True)
class SignalRule:
    category: str
    title: str
    severity: str
    patterns: tuple[str, ...]
    recommendation: str
    skill_weights: dict[str, int]


SIGNAL_RULES: tuple[SignalRule, ...] = (
    SignalRule(
        category="disk_pressure",
        title="磁盘或 inode 压力",
        severity="high",
        patterns=(
            r"no space left on device",
            r"\b(9[0-9]|100)%\b",
            r"disk.*full",
            r"inode",
            r"磁盘.*满",
            r"磁盘.*爆",
            r"空间不足",
            r"容量不足",
            r"日志.*(太大|爆|满)",
        ),
        recommendation="先确认 df -h 和 df -i，再定位大日志、已删除但仍被占用的文件和 logrotate 配置。",
        skill_weights={"disk_check": 5, "log_analyze": 2, "auto_inspect": 1},
    ),
    SignalRule(
        category="log_error",
        title="日志中存在错误或告警",
        severity="medium",
        patterns=(
            r"\berror\b",
            r"\bwarn(ing)?\b",
            r"\bcritical\b",
            r"\bfail(ed|ure)?\b",
            r"exception",
            r"traceback",
            r"报错",
            r"异常",
            r"错误",
            r"告警",
            r"日志",
        ),
        recommendation="按时间聚合错误，优先查看首次出现时间、高频错误和与服务状态变化相邻的日志。",
        skill_weights={"log_analyze": 5, "auto_inspect": 1},
    ),
    SignalRule(
        category="permission",
        title="权限或属主问题",
        severity="medium",
        patterns=(
            r"permission denied",
            r"operation not permitted",
            r"forbidden",
            r"\b403\b",
            r"权限",
            r"无权",
            r"拒绝访问",
        ),
        recommendation="检查文件权限、上级目录 x 权限、属主属组、服务运行用户以及 SELinux/AppArmor 状态。",
        skill_weights={"log_analyze": 3, "auto_inspect": 1},
    ),
    SignalRule(
        category="port_conflict",
        title="端口冲突或绑定失败",
        severity="high",
        patterns=(
            r"address already in use",
            r"bind\(\).*failed",
            r"cannot assign requested address",
            r"端口.*占用",
            r"端口.*冲突",
            r"port.*already",
        ),
        recommendation="用 ss -tulnp 确认端口归属，再判断是改端口、停冲突服务还是修正监听地址。",
        skill_weights={"network_check": 5, "process_check": 2, "log_analyze": 1},
    ),
    SignalRule(
        category="dependency_unavailable",
        title="上游或依赖服务不可用",
        severity="high",
        patterns=(
            r"connection refused",
            r"connect\(\).*failed",
            r"database.*refused",
            r"redis.*refused",
            r"mysql.*refused",
            r"connection reset",
            r"连接被拒绝",
            r"依赖.*不可用",
            r"数据库.*连接失败",
        ),
        recommendation="确认依赖服务是否运行、端口是否监听、地址是否正确，以及调用方到依赖之间是否可达。",
        skill_weights={"network_check": 4, "process_check": 2, "log_analyze": 3},
    ),
    SignalRule(
        category="timeout",
        title="网络或上游超时",
        severity="medium",
        patterns=(
            r"connection timed out",
            r"upstream timed out",
            r"\btimeout\b",
            r"timed out",
            r"超时",
            r"响应慢",
            r"访问慢",
            r"卡顿",
            r"延迟",
        ),
        recommendation="把 DNS、路由、防火墙、端口监听、上游响应时间和本机负载分开排查。",
        skill_weights={"network_check": 4, "process_check": 3, "log_analyze": 2},
    ),
    SignalRule(
        category="auth_failure",
        title="认证失败或 SSH 爆破迹象",
        severity="medium",
        patterns=(
            r"failed password",
            r"invalid user",
            r"authentication failure",
            r"登录失败",
            r"爆破",
            r"ssh.*失败",
            r"invalid user",
        ),
        recommendation="统计来源 IP 和失败次数，检查 SSH 策略，必要时限制来源、关闭密码登录或启用限速。",
        skill_weights={"log_analyze": 5, "network_check": 1, "auto_inspect": 1},
    ),
    SignalRule(
        category="oom",
        title="内存不足或 OOM",
        severity="high",
        patterns=(
            r"out of memory",
            r"\boom\b",
            r"killed process",
            r"cannot allocate memory",
            r"内存不足",
            r"内存溢出",
        ),
        recommendation="关联 OOM 日志、高内存进程、swap、流量峰值和最近任务，避免只凭 free 输出下结论。",
        skill_weights={"process_check": 5, "log_analyze": 3, "auto_inspect": 1},
    ),
    SignalRule(
        category="web_gateway",
        title="Web 网关或 upstream 异常",
        severity="high",
        patterns=(
            r"\b502\b",
            r"\b504\b",
            r"bad gateway",
            r"gateway timeout",
            r"upstream",
            r"nginx",
            r"网站打不开",
            r"接口超时",
        ),
        recommendation="检查 nginx error.log、upstream 端口、应用进程、依赖服务和最近发布变更。",
        skill_weights={"log_analyze": 4, "network_check": 3, "process_check": 2},
    ),
    SignalRule(
        category="cpu_load",
        title="CPU、负载或进程资源异常",
        severity="medium",
        patterns=(
            r"load average",
            r"\bcpu\b",
            r"high load",
            r"top process",
            r"cpu.*高",
            r"负载.*高",
            r"进程.*占用",
            r"卡死",
        ),
        recommendation="对比 load、CPU 使用率、进程状态和日志时间点，确认是 CPU、IO wait 还是阻塞进程。",
        skill_weights={"process_check": 5, "log_analyze": 2, "auto_inspect": 1},
    ),
    SignalRule(
        category="network",
        title="网络、DNS 或路由异常",
        severity="medium",
        patterns=(
            r"\bdns\b",
            r"network unreachable",
            r"no route to host",
            r"could not resolve host",
            r"网络",
            r"连通",
            r"解析失败",
            r"路由",
            r"ping",
        ),
        recommendation="区分 IP 连通、DNS 解析、路由、防火墙和服务端口监听。",
        skill_weights={"network_check": 5, "log_analyze": 1},
    ),
    SignalRule(
        category="full_inspection",
        title="综合巡检或系统体检需求",
        severity="low",
        patterns=(
            r"auto inspect",
            r"checkup",
            r"巡检",
            r"体检",
            r"全面检查",
            r"自动检查",
            r"健康检查",
            r"综合诊断",
        ),
        recommendation="执行自动巡检，先采集系统整体证据，再按异常项深入分析。",
        skill_weights={"auto_inspect": 6, "health_report": 3},
    ),
)


ENTITY_PATTERNS: tuple[str, ...] = (
    r"\bnginx\b",
    r"\bmysql\b",
    r"\bredis\b",
    r"\bdocker\b",
    r"\bssh[d]?\b",
    r"\bsystemd\b",
    r"\bjava\b",
    r"\bpython\b",
    r"\bnode\b",
    r"\bpostgres(?:ql)?\b",
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
    r"\b:\d{2,5}\b",
    r"/[A-Za-z0-9_./-]+",
)


def understand_operations_text(
    text: str,
    skills: dict[str, Skill] | None = None,
    max_skills: int = 3,
) -> LocalUnderstanding:
    normalized = _normalize(text)
    signals = _detect_signals(normalized)
    skill_scores = _score_skills(normalized, signals, skills or {})
    selected = tuple(name for _, name in sorted(skill_scores, reverse=True)[:max_skills])
    symptoms = tuple(signal.title for signal in signals)
    entities = _extract_entities(normalized)
    intent = _classify_intent(normalized, signals)
    confidence = _confidence(signals, selected)
    reason = _build_reason(signals, selected)
    return LocalUnderstanding(
        intent=intent,
        symptoms=symptoms,
        entities=entities,
        signals=signals,
        selected_skills=selected,
        reason=reason,
        confidence=confidence,
    )


def render_local_analysis(
    text: str,
    analysis_type: str,
    source_name: str,
    skills: dict[str, Skill] | None = None,
) -> str:
    understanding = understand_operations_text(text, skills=skills, max_skills=5)
    lines: list[str] = [
        "## 本地运维模型分析\n\n",
        f"- 来源：{source_name}\n",
        f"- 类型：{analysis_type}\n",
        f"- 判断意图：{understanding.intent}\n",
        f"- 置信度：{understanding.confidence:.2f}\n",
    ]
    if understanding.entities:
        lines.append(f"- 识别对象：{', '.join(understanding.entities[:12])}\n")
    if understanding.selected_skills:
        lines.append(f"- 建议 skills：{', '.join(understanding.selected_skills)}\n")

    lines.append("\n## 关键问题\n\n")
    if not understanding.signals:
        lines.append("本地模型没有识别到明确的高价值运维故障信号。建议补充更多日志、命令输出或报错上下文。\n")
    for signal in understanding.signals:
        lines.append(f"### [{signal.severity.upper()}] {signal.title}\n\n")
        lines.append(f"建议：{signal.recommendation}\n\n")
        lines.append("证据：\n")
        for item in signal.evidence:
            lines.append(f"- `{_clip(item, 220)}`\n")
        lines.append("\n")

    lines.append("## 排查顺序建议\n\n")
    for index, step in enumerate(_diagnosis_steps(understanding), start=1):
        lines.append(f"{index}. {step}\n")

    lines.append("\n## 风险提示\n\n")
    lines.append("- 本地模型只基于文本证据判断，不会假设输入中没有出现的系统状态。\n")
    lines.append("- 涉及删除、重启、格式化、权限批量修改等操作时，应先备份、验证影响范围并准备回滚。\n")
    return "".join(lines)


def _detect_signals(text: str) -> tuple[LocalSignal, ...]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    signals: list[LocalSignal] = []
    for rule in SIGNAL_RULES:
        evidence = _match_evidence(lines, rule.patterns)
        if evidence:
            signals.append(
                LocalSignal(
                    category=rule.category,
                    title=rule.title,
                    severity=rule.severity,
                    evidence=tuple(evidence),
                    recommendation=rule.recommendation,
                    skill_weights=rule.skill_weights,
                )
            )
    return tuple(_dedupe_signals(signals))


def _score_skills(
    text: str,
    signals: Iterable[LocalSignal],
    skills: dict[str, Skill],
) -> list[tuple[int, str]]:
    scores: dict[str, int] = {}
    lowered = text.lower()
    for signal in signals:
        for skill_name, weight in signal.skill_weights.items():
            if not skills or skill_name in skills:
                scores[skill_name] = scores.get(skill_name, 0) + weight

    for skill in skills.values():
        for keyword in skill.keywords:
            if keyword and keyword.lower() in lowered:
                scores[skill.name] = scores.get(skill.name, 0) + 2
        for token in re.split(r"\W+", skill.name.lower()):
            if token and token in lowered:
                scores[skill.name] = scores.get(skill.name, 0) + 1

    return [(score, name) for name, score in scores.items() if score > 0]


def _match_evidence(lines: list[str], patterns: tuple[str, ...]) -> list[str]:
    evidence: list[str] = []
    for line in lines:
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns):
            evidence.append(line)
        if len(evidence) >= 5:
            break
    return evidence


def _extract_entities(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for pattern in ENTITY_PATTERNS:
        found.extend(match.group(0) for match in re.finditer(pattern, text, re.IGNORECASE))
    return tuple(dict.fromkeys(item.strip() for item in found if item.strip()))


def _classify_intent(text: str, signals: tuple[LocalSignal, ...]) -> str:
    categories = {signal.category for signal in signals}
    if "full_inspection" in categories:
        return "系统自动巡检"
    if any(item in text for item in ("为什么", "原因", "定位", "排查", "分析")) or len(signals) >= 2:
        return "故障诊断"
    if "log_error" in categories:
        return "日志解读"
    if "permission" in categories:
        return "权限问题分析"
    if "port_conflict" in categories:
        return "端口问题分析"
    if signals:
        return "运维异常识别"
    return "普通文本分析"


def _confidence(signals: tuple[LocalSignal, ...], selected: tuple[str, ...]) -> float:
    if not signals:
        return 0.2
    severity_boost = sum(0.15 for signal in signals if signal.severity == "high")
    skill_boost = 0.15 if selected else 0
    return min(0.95, 0.35 + len(signals) * 0.08 + severity_boost + skill_boost)


def _build_reason(signals: tuple[LocalSignal, ...], selected: tuple[str, ...]) -> str:
    if not signals:
        return "本地模型没有识别到明确运维故障信号，因此不主动执行 skill"
    titles = "、".join(signal.title for signal in signals[:4])
    if selected:
        return f"本地模型识别到：{titles}；因此建议执行：{', '.join(selected)}"
    return f"本地模型识别到：{titles}；但没有匹配到可执行 skill"


def _diagnosis_steps(understanding: LocalUnderstanding) -> tuple[str, ...]:
    categories = {signal.category for signal in understanding.signals}
    steps: list[str] = []
    if "web_gateway" in categories:
        steps.append("先看 nginx 或网关错误日志，确认 502/504 是 upstream 不可达、超时还是应用返回异常。")
    if "dependency_unavailable" in categories:
        steps.append("检查依赖服务端口是否监听，并从调用方验证连接是否可达。")
    if "disk_pressure" in categories:
        steps.append("检查磁盘和 inode 使用率，定位增长最快的日志或大文件。")
    if "oom" in categories or "cpu_load" in categories:
        steps.append("检查高 CPU/内存进程、load average、OOM 日志和异常时间点。")
    if "port_conflict" in categories:
        steps.append("用监听端口和进程列表确认端口归属，避免盲目 kill 或重启。")
    if "permission" in categories:
        steps.append("沿着访问路径逐级检查目录权限、文件权限、属主和服务运行用户。")
    if "auth_failure" in categories:
        steps.append("统计认证失败来源 IP，判断是否为爆破扫描或配置错误。")
    if "network" in categories or "timeout" in categories:
        steps.append("区分 DNS、路由、防火墙、端口监听和上游响应慢。")
    if not steps:
        steps.append("补充更完整的日志、命令输出和故障发生时间，再重新分析。")
    return tuple(dict.fromkeys(steps))


def _dedupe_signals(signals: list[LocalSignal]) -> list[LocalSignal]:
    seen: set[str] = set()
    output: list[LocalSignal] = []
    for signal in signals:
        if signal.category in seen:
            continue
        seen.add(signal.category)
        output.append(signal)
    return output


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."
