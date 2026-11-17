"""HTML 预处理与通用 DOM 工具。"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

_WS_RE = re.compile(r"\s+")
_HIDDEN_CLASS_RE = re.compile(
    r"(?:^|[\s_-])(?:hidden|d-none|is-hidden|invisible)(?:$|[\s_-])",
    re.IGNORECASE,
)

SKIP_TAGS = ("script", "style", "noscript", "template", "svg")


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def normalize_text(value: str | None, limit: int | None = None) -> str:
    if value is None:
        return ""
    text = _WS_RE.sub(" ", str(value)).strip()
    if limit is not None and len(text) > limit:
        return text[:limit]
    return text


def text_of(element: Tag | None, limit: int | None = None) -> str:
    if element is None:
        return ""
    for bad in element.find_all(SKIP_TAGS):
        bad.decompose()
    return normalize_text(element.get_text(" "), limit)


def is_hidden(element: Tag | None) -> bool:
    """沿祖先链判断元素在捕获时是否隐藏（不执行 JS）。"""
    node: Tag | None = element
    while isinstance(node, Tag):
        if node.has_attr("hidden"):
            return True
        if (node.get("aria-hidden") or "").lower() == "true":
            return True
        style = (node.get("style") or "").lower().replace(" ", "")
        if "display:none" in style or "visibility:hidden" in style:
            return True
        if (node.get("v-show") or "").strip().lower() == "false":
            return True
        classes = " ".join(node.get("class") or [])
        if _HIDDEN_CLASS_RE.search(classes):
            return True
        node = node.parent
    return False


def find_question_container(element: Tag) -> Tag | None:
    """向上寻找题目容器；找不到时退回直接父节点。"""
    node: Tag | None = element.parent
    while isinstance(node, Tag) and node.name not in {"body", "html", "main", "form"}:
        if node.has_attr("data-question-id") or node.has_attr("data-question"):
            return node
        classes = " ".join(node.get("class") or []).lower()
        if any(
            token in classes
            for token in (
                "question",
                "qblock",
                "question-block",
                "form-group",
                "form-item",
            )
        ):
            return node
        node = node.parent
    return element.parent if isinstance(element.parent, Tag) else None


def find_preceding_text(element: Tag, limit: int = 300) -> str:
    """向前找最近的文本节点，用于题干兜底。"""
    node: Tag | None = element
    hops = 0
    while isinstance(node, Tag) and hops < 6:
        sibling = node.previous_sibling
        while sibling is not None:
            if isinstance(sibling, Tag):
                candidate = text_of(sibling, limit)
                if candidate:
                    return candidate
            else:
                candidate = normalize_text(str(sibling), limit)
                if candidate:
                    return candidate
            sibling = sibling.previous_sibling
        node = node.parent
        hops += 1
    return ""


def contains_control(element: Tag) -> bool:
    return bool(
        element.find(["input", "select", "textarea"])
        or element.find(attrs={"contenteditable": "true"})
    )
