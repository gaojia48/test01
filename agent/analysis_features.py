from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorCluster:
    signature: str
    count: int
    examples: tuple[str, ...]


@dataclass(frozen=True)
class TimelineEvent:
    timestamp: str
    severity: str
    message: str


ERROR_HINTS = (
    r"\berror\b",
    r"\bexception\b",
    r"\bfailed\b",
    r"\bfailure\b",
    r"\bcritical\b",
    r"\bpanic\b",
    r"\bfatal\b",
    r"traceback",
    r"[A-Za-z]+Error:",
    r"[A-Za-z]+Exception:",
    r"报错",
    r"异常",
    r"失败",
)

TIMESTAMP_PATTERNS = (
    re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)"),
    re.compile(r"(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})"),
    re.compile(r"(?P<ts>\d{2}:\d{2}:\d{2})"),
)


def cluster_unknown_errors(text: str, known_evidence: set[str] | None = None, limit: int = 8) -> tuple[ErrorCluster, ...]:
    known = known_evidence or set()
    buckets: dict[str, list[str]] = defaultdict(list)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line in known:
            continue
        if not _looks_error_like(line):
            continue
        signature = _normalize_signature(line)
        if signature:
            buckets[signature].append(line)

    clusters = [
        ErrorCluster(signature=signature, count=len(examples), examples=tuple(examples[:3]))
        for signature, examples in buckets.items()
    ]
    clusters.sort(key=lambda item: (item.count, len(item.signature)), reverse=True)
    return tuple(clusters[:limit])


def extract_timeline_events(text: str, limit: int = 20) -> tuple[TimelineEvent, ...]:
    events: list[TimelineEvent] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        timestamp = _extract_timestamp(line)
        if not timestamp:
            continue
        severity = _infer_severity(line)
        events.append(TimelineEvent(timestamp=timestamp, severity=severity, message=_clip(line, 220)))
    return tuple(events[:limit])


def render_error_clusters(clusters: tuple[ErrorCluster, ...]) -> str:
    lines = ["## 未知错误聚类\n\n"]
    if not clusters:
        lines.append("没有发现需要单独聚类的未知错误模式。\n")
        return "".join(lines)

    for index, cluster in enumerate(clusters, start=1):
        lines.append(f"### 模式 {index}，出现 {cluster.count} 次\n\n")
        lines.append(f"归一化特征：`{cluster.signature}`\n\n")
        lines.append("样例：\n")
        for example in cluster.examples:
            lines.append(f"- `{_clip(example, 220)}`\n")
        lines.append("\n")
    return "".join(lines)


def render_timeline(events: tuple[TimelineEvent, ...]) -> str:
    lines = ["## 故障时间线\n\n"]
    if not events:
        lines.append("没有识别到明确时间戳，无法重建时间线。\n")
        return "".join(lines)

    for event in events:
        lines.append(f"- `{event.timestamp}` [{event.severity}] {_clip(event.message, 220)}\n")
    return "".join(lines)


def _looks_error_like(line: str) -> bool:
    return any(re.search(pattern, line, re.IGNORECASE) for pattern in ERROR_HINTS)


def _normalize_signature(line: str) -> str:
    value = line.lower()
    value = re.sub(r"\d{4}-\d{2}-\d{2}[ t]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?", "<time>", value)
    value = re.sub(r"[a-z][a-z][a-z]\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}", "<time>", value)
    value = re.sub(r"\b\d{2}:\d{2}:\d{2}\b", "<time>", value)
    value = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "<ip>", value)
    value = re.sub(r"\b\d+\b", "<num>", value)
    value = re.sub(r"/[a-zA-Z0-9_./-]+", "<path>", value)
    value = re.sub(r"0x[0-9a-f]+", "<hex>", value)
    value = re.sub(r"\s+", " ", value).strip()
    return _clip(value, 180)


def _extract_timestamp(line: str) -> str:
    for pattern in TIMESTAMP_PATTERNS:
        match = pattern.search(line)
        if match:
            return match.group("ts")
    return ""


def _infer_severity(line: str) -> str:
    lowered = line.lower()
    if any(word in lowered for word in ("critical", "fatal", "panic", "oom", "killed process", "no space left")):
        return "high"
    if any(word in lowered for word in ("error", "failed", "exception", "timeout", "refused")):
        return "medium"
    if any(word in lowered for word in ("warn", "warning")):
        return "low"
    return "info"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."
