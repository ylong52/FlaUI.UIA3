"""选项提取：label 解析、ID 生成、互斥项识别。"""

from __future__ import annotations

import re

from bs4 import Tag

from parser.html_parser import normalize_text, text_of
from schemas.question import Option

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_UNRESOLVED_RE = re.compile(r"\{\{|\}\}|\{%|%\}|\$\{")
EXCLUSIVE_RE = re.compile(
    r"\b("
    r"none of the above|none of these|"
    r"not applicable|n/?a|"
    r"i (?:do not|don't) (?:use|own|have)|"
    r"prefer not to (?:say|answer)|"
    r"no experience|never used"
    r")\b",
    re.IGNORECASE,
)


def slugify(value: str, fallback: str) -> str:
    slug = _SLUG_RE.sub("_", value.lower()).strip("_")
    return slug or fallback


def unique_id(candidate: str, used: set[str]) -> str:
    base = candidate or "opt"
    result = base
    suffix = 2
    while result in used:
        result = f"{base}_{suffix}"
        suffix += 1
    used.add(result)
    return result


def is_exclusive_label(label: str) -> bool:
    return bool(EXCLUSIVE_RE.search(label or ""))


def has_unresolved_template(labels: list[str]) -> bool:
    return any(_UNRESOLVED_RE.search(label or "") for label in labels)


def label_for_input(inp: Tag, soup: Tag) -> str:
    aria_label = normalize_text(inp.get("aria-label"))
    if aria_label:
        return aria_label

    labelledby = inp.get("aria-labelledby")
    if labelledby:
        parts = []
        for ref in str(labelledby).split():
            target = soup.find(id=ref)
            if target is not None:
                parts.append(text_of(target))
        joined = normalize_text(" ".join(parts))
        if joined:
            return joined

    input_id = inp.get("id")
    if input_id:
        label = soup.find("label", attrs={"for": input_id})
        if label is not None:
            text = text_of(label)
            if text:
                return text

    parent_label = inp.find_parent("label")
    if parent_label is not None:
        text = text_of(parent_label)
        if text:
            return text

    # 常见结构：input + span.txt / span.label
    for sibling in list(inp.next_siblings):
        if isinstance(sibling, Tag):
            text = text_of(sibling)
            if text:
                return text
        else:
            text = normalize_text(str(sibling))
            if text:
                return text

    for sibling in list(inp.previous_siblings):
        if isinstance(sibling, Tag):
            text = text_of(sibling)
            if text:
                return text
        else:
            text = normalize_text(str(sibling))
            if text:
                return text

    return normalize_text(inp.get("value")) or normalize_text(inp.get("title"))


def extract_input_option(inp: Tag, soup: Tag, index: int) -> Option:
    label = label_for_input(inp, soup)
    raw_value = inp.get("value")
    raw_value = str(raw_value) if raw_value not in (None, "") else None

    if inp.get("id"):
        option_id = str(inp.get("id"))
    elif raw_value is not None:
        option_id = raw_value
    else:
        option_id = slugify(label, f"opt_{index + 1}")

    return Option(
        id=option_id,
        label=label or raw_value or option_id,
        value=raw_value,
        disabled=inp.has_attr("disabled"),
        exclusive=is_exclusive_label(label),
    )


def extract_select_options(select: Tag) -> list[Option]:
    options: list[Option] = []
    used: set[str] = set()
    for index, opt in enumerate(select.find_all("option")):
        label = text_of(opt)
        value = opt.get("value")
        value = str(value) if value not in (None, "") else None
        if not label and value in (None, ""):
            continue
        if value in (None, "") and (
            opt.has_attr("disabled")
            or re.search(r"please\s*(select|choose)|select\s*one|choose\s*one", label, re.IGNORECASE)
        ):
            # 占位项（Please select… / Choose one…）不作为可选项
            continue
        option_id = value or slugify(label, f"opt_{index + 1}")
        options.append(
            Option(
                id=unique_id(option_id, used),
                label=label or option_id,
                value=value,
                disabled=opt.has_attr("disabled"),
                exclusive=is_exclusive_label(label),
            )
        )
    return options


def aria_option_label(element: Tag) -> str:
    return (
        normalize_text(element.get("aria-label"))
        or text_of(element)
        or normalize_text(element.get("data-value"))
    )
