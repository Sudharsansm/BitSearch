"""
Lightweight prompt-injection detection for content crawled from the web.

**What this is**: a pattern-based scanner that flags text likely to
contain instructions aimed at an LLM (e.g. "ignore previous instructions
and...", "SYSTEM:", fake tool-call syntax). This is a *signal*, not a
filter — it does not remove or rewrite content.

**What this is not**: a guarantee of safety. Prompt injection is an open
research problem; no pattern-matcher catches everything, and determined
attackers can obfuscate instructions in ways this won't detect. Treat
``SecurityReport.flagged=True`` as "review this before feeding it
directly to an LLM with elevated privileges", not as "this content is
dangerous" or "unflagged content is safe".

Typical usage — an agent calling :func:`bie.extract.extract` or
:func:`bie.websearch` should check ``result.security.flagged`` before
passing crawled text into a prompt that also has access to tools,
credentials, or the ability to take actions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Each pattern targets a category of common prompt-injection phrasing
# found in adversarial web content. Patterns are intentionally broad —
# expect some false positives on legitimate text that merely discusses
# these topics (e.g. an article *about* prompt injection).
_PATTERNS: dict[str, re.Pattern] = {
    "instruction_override": re.compile(
        r"\b(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above|the\s+above)\s+"
        r"(instructions?|prompts?|rules?|context)\b",
        re.I,
    ),
    "role_injection": re.compile(
        r"^\s*(system|assistant|developer)\s*:",
        re.I | re.M,
    ),
    "fake_tool_call": re.compile(
        r"(<\s*(tool_call|function_call|antml:invoke)\b|"
        r"\bcall\s+the\s+\w+\s+(tool|function)\b)",
        re.I,
    ),
    "exfiltration_request": re.compile(
        r"\b(reveal|print|output|send|leak)\s+(your\s+)?"
        r"(system\s+prompt|api\s+key|credentials?|secrets?|instructions?)\b",
        re.I,
    ),
    "do_anything_now": re.compile(
        r"\b(jailbreak|dan\s+mode|do\s+anything\s+now|developer\s+mode\s+enabled)\b",
        re.I,
    ),
    "hidden_instruction_markup": re.compile(
        r"<!--.*?(ignore|system|instruction).*?-->",
        re.I | re.S,
    ),
}


@dataclass
class SecurityFinding:
    """A single pattern match within scanned text."""

    category: str
    excerpt: str


@dataclass
class SecurityReport:
    """Result of :func:`scan_for_prompt_injection`.

    Attributes:
        flagged: True if one or more suspicious patterns were found.
        findings: List of :class:`SecurityFinding` describing each match.
    """

    flagged: bool = False
    findings: list[SecurityFinding] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.flagged

    def __str__(self) -> str:  # pragma: no cover - convenience only
        if not self.flagged:
            return "<SecurityReport flagged=False>"
        cats = ", ".join(sorted({f.category for f in self.findings}))
        return f"<SecurityReport flagged=True categories=[{cats}] count={len(self.findings)}>"


_EXCERPT_RADIUS = 60


def scan_for_prompt_injection(text: str, max_findings: int = 10) -> SecurityReport:
    """Scan ``text`` for patterns commonly associated with prompt
    injection attacks embedded in web content.

    This is a best-effort heuristic scan (see module docstring for
    caveats). It does not modify ``text`` — callers decide how to handle
    flagged content (e.g. warn the user, exclude from an agent's
    high-privilege context, or simply log it).

    Args:
        text: Plain text to scan (e.g. extracted page content).
        max_findings: Stop after this many matches (across all categories).

    Returns:
        A :class:`SecurityReport`.
    """
    findings: list[SecurityFinding] = []

    for category, pattern in _PATTERNS.items():
        for match in pattern.finditer(text):
            start = max(0, match.start() - _EXCERPT_RADIUS)
            end = min(len(text), match.end() + _EXCERPT_RADIUS)
            excerpt = text[start:end].strip()
            findings.append(SecurityFinding(category=category, excerpt=excerpt))
            if len(findings) >= max_findings:
                break
        if len(findings) >= max_findings:
            break

    return SecurityReport(flagged=bool(findings), findings=findings)
