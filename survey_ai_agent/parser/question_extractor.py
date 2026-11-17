"""从 HTML 中提取题目、题型与选项。

不能只看标签名：会结合控件语义、选项结构、题干文字与题目容器来判断；
无法可靠判断时返回 unknown / 标记 needs_review。
"""

from __future__ import annotations

import hashlib
import json
import re

from bs4 import Tag

from parser.html_parser import (
    contains_control,
    find_preceding_text,
    find_question_container,
    is_hidden,
    normalize_text,
    parse_html,
    text_of,
)
from parser.option_extractor import (
    aria_option_label,
    extract_input_option,
    extract_select_options,
    has_unresolved_template,
    slugify,
    unique_id,
)
from schemas.question import (
    MatrixRow,
    MatrixSpec,
    NumericSpec,
    Option,
    Question,
    QuestionType,
)

SKIP_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image", "file", "password"}
AGE_LABEL_RE = re.compile(
    r"^(?:(?:under|below|over|above)\s*)?\d{1,2}\s*(?:[-–—]\s*\d{1,2}\s*)?\+?$",
    re.IGNORECASE,
)
COUNTRY_LABELS = {
    "united states", "usa", "us", "canada", "united kingdom", "uk", "germany",
    "france", "australia", "japan", "china", "india", "brazil", "mexico",
    "spain", "italy", "netherlands", "other",
}
GENDER_LABELS = {"male", "female", "non-binary", "nonbinary", "other", "prefer not to say"}
PERSONAL_RE = re.compile(
    r"\b("
    r"age|how old|country|reside|gender|sex|income|salary|earn|"
    r"employ|occupation|job|industry|department|education|degree|"
    r"marital|married|household|children|kids|zip|postal|ethnicity|race|"
    r"your name|full name|first name|last name|email|phone|"
    r"purchas|buy|bought|use|used|work with|experience|devices"
    r")\b",
    re.IGNORECASE,
)
GENERIC_TEXT = {
    "please type your answer…",
    "please type your answer...",
    "please select…",
    "please select...",
    "your answer",
}
ARIA_ROLES = {
    "radiogroup", "radio", "checkbox", "combobox", "slider",
    "spinbutton", "textbox", "listbox",
}


def extract_questions(html: str, max_questions: int = 500) -> list[Question]:
    soup = parse_html(html)
    consumed: set[int] = set()
    questions: list[Question] = []
    used_qids: set[str] = set()

    for node in soup.find_all(True):
        if len(questions) >= max_questions:
            break
        if id(node) in consumed:
            continue

        if node.name == "table" and node.find("input", attrs={"type": "radio"}):
            q = _extract_matrix(node, soup, questions, used_qids)
            if q is not None:
                questions.append(q)
            for child in node.find_all(True):
                consumed.add(id(child))
            continue

        if node.name in {"ul", "ol"} and _looks_like_ranking(node):
            q = _extract_ranking(node, soup, questions, used_qids)
            if q is not None:
                questions.append(q)
            for child in node.find_all(True):
                consumed.add(id(child))
            continue

        if node.name == "select":
            consumed.add(id(node))
            q = _extract_select(node, soup, questions, used_qids)
            if q is not None:
                questions.append(q)
            continue

        if node.name == "textarea":
            consumed.add(id(node))
            q = _extract_text_like(node, soup, questions, used_qids, QuestionType.text)
            if q is not None:
                questions.append(q)
            continue

        if node.name == "input":
            input_type = (node.get("type") or "text").lower()
            if input_type in SKIP_INPUT_TYPES:
                continue
            if input_type == "range":
                consumed.add(id(node))
                q = _extract_rating(node, soup, questions, used_qids)
                if q is not None:
                    questions.append(q)
                continue
            if input_type in {"radio", "checkbox"}:
                group = _collect_group(node, soup, input_type)
                if not group:
                    continue
                qtype = (
                    QuestionType.single_choice
                    if input_type == "radio"
                    else QuestionType.multi_choice
                )
                q = _extract_choice(group, qtype, soup, questions, used_qids)
                for item in group:
                    consumed.add(id(item))
                if q is not None:
                    questions.append(q)
                continue

            consumed.add(id(node))
            numeric = input_type == "number" or (
                (node.get("inputmode") or "").lower() in {"numeric", "decimal"}
            )
            q = _extract_text_like(
                node,
                soup,
                questions,
                used_qids,
                QuestionType.number if numeric else QuestionType.text,
            )
            if q is not None:
                questions.append(q)
            continue

        role = (node.get("role") or "").lower()
        if role in ARIA_ROLES and not contains_control(node):
            q = _extract_aria_question(node, soup, questions, used_qids)
            if q is not None:
                questions.append(q)
                consumed.add(id(node))
                for child in node.find_all(True):
                    consumed.add(id(child))

    return questions


# ---------------------------------------------------------------- choices


def _collect_group(first: Tag, soup: Tag, input_type: str) -> list[Tag]:
    container = find_question_container(first)
    scope = container or soup
    name = first.get("name")
    if name:
        return list(
            scope.find_all("input", attrs={"type": input_type, "name": name})
        )
    inputs = list(scope.find_all("input", attrs={"type": input_type}))
    if input_type == "radio" and len(inputs) > 12:
        return [first]
    return inputs or [first]


def _extract_choice(
    group: list[Tag],
    qtype: QuestionType,
    soup: Tag,
    existing: list[Question],
    used_qids: set[str],
) -> Question | None:
    if not group:
        return None
    container = find_question_container(group[0])
    question_id = _make_qid(container, group[0].get("name"), len(existing), used_qids)
    text, text_unavailable = _resolve_text(container, group, soup)

    used_option_ids: set[str] = set()
    options: list[Option] = []
    for index, inp in enumerate(group):
        option = extract_input_option(inp, soup, index)
        option.id = unique_id(option.id, used_option_ids)
        options.append(option)

    if not options:
        return None

    inferred = _infer_topic(options)
    required = _is_required(container, group, text)
    min_selections, max_selections = _selection_limits(text, qtype, required)
    depends_on, depends_value, hint, hidden = _conditional(container or group[0])

    question = Question(
        question_id=question_id,
        text=text,
        question_type=qtype,
        required=required,
        options=options,
        min_selections=min_selections,
        max_selections=max_selections,
        depends_on=depends_on,
        depends_value=depends_value,
        conditional_hint=hint,
        requires_personal_fact=_is_personal(text, inferred),
        text_unavailable=text_unavailable,
        options_unresolved=has_unresolved_template([o.label for o in options]),
        inferred_topic=inferred,
        hidden=hidden,
        raw={
            "name": group[0].get("name"),
            "input_ids": [inp.get("id") for inp in group if inp.get("id")],
            "control": "input",
            "input_type": group[0].get("type"),
        },
    )
    question.fingerprint = _fingerprint(question)
    return question


# ---------------------------------------------------------------- select / text / rating


def _extract_select(
    node: Tag,
    soup: Tag,
    existing: list[Question],
    used_qids: set[str],
) -> Question | None:
    options = extract_select_options(node)
    if not options:
        return None
    container = find_question_container(node)
    text, text_unavailable = _resolve_text(container, [node], soup)
    multiple = node.has_attr("multiple")
    qtype = QuestionType.multi_choice if multiple else QuestionType.dropdown
    required = _is_required(container, [node], text)
    min_selections, max_selections = _selection_limits(text, qtype, required)
    inferred = _infer_topic(options)
    depends_on, depends_value, hint, hidden = _conditional(container or node)

    question = Question(
        question_id=_make_qid(container, node.get("name"), len(existing), used_qids),
        text=text,
        question_type=qtype,
        required=required,
        options=options,
        min_selections=min_selections,
        max_selections=max_selections,
        depends_on=depends_on,
        depends_value=depends_value,
        conditional_hint=hint,
        requires_personal_fact=_is_personal(text, inferred),
        text_unavailable=text_unavailable,
        options_unresolved=has_unresolved_template([o.label for o in options]),
        inferred_topic=inferred,
        hidden=hidden,
        raw={
            "name": node.get("name"),
            "control": "select",
            "multiple": multiple,
        },
    )
    question.fingerprint = _fingerprint(question)
    return question


def _extract_text_like(
    node: Tag,
    soup: Tag,
    existing: list[Question],
    used_qids: set[str],
    qtype: QuestionType,
) -> Question | None:
    container = find_question_container(node)
    text, text_unavailable = _resolve_text(container, [node], soup)

    numeric = None
    if qtype == QuestionType.number:
        numeric = NumericSpec(
            min=_float_attr(node, "min"),
            max=_float_attr(node, "max"),
            step=_float_attr(node, "step"),
        )

    depends_on, depends_value, hint, hidden = _conditional(container or node)
    question = Question(
        question_id=_make_qid(container, node.get("name"), len(existing), used_qids),
        text=text,
        question_type=qtype,
        required=_is_required(container, [node], text),
        numeric=numeric,
        depends_on=depends_on,
        depends_value=depends_value,
        conditional_hint=hint,
        requires_personal_fact=_is_personal(text, None),
        text_unavailable=text_unavailable,
        hidden=hidden,
        raw={
            "name": node.get("name"),
            "id": node.get("id"),
            "control": node.name,
            "input_type": node.get("type"),
        },
    )
    question.fingerprint = _fingerprint(question)
    return question


def _extract_rating(
    node: Tag,
    soup: Tag,
    existing: list[Question],
    used_qids: set[str],
) -> Question | None:
    container = find_question_container(node)
    text, text_unavailable = _resolve_text(container, [node], soup)
    depends_on, depends_value, hint, hidden = _conditional(container or node)
    question = Question(
        question_id=_make_qid(container, node.get("name"), len(existing), used_qids),
        text=text,
        question_type=QuestionType.rating,
        required=_is_required(container, [node], text),
        numeric=NumericSpec(
            min=_float_attr(node, "min", 0.0),
            max=_float_attr(node, "max", 100.0),
            step=_float_attr(node, "step", 1.0),
        ),
        depends_on=depends_on,
        depends_value=depends_value,
        conditional_hint=hint,
        requires_personal_fact=False,
        text_unavailable=text_unavailable,
        hidden=hidden,
        raw={"name": node.get("name"), "control": "range"},
    )
    question.fingerprint = _fingerprint(question)
    return question


# ---------------------------------------------------------------- matrix / ranking


def _extract_matrix(
    table: Tag,
    soup: Tag,
    existing: list[Question],
    used_qids: set[str],
) -> Question | None:
    container = find_question_container(table) or table
    text, text_unavailable = _resolve_text(container, [table], soup)

    header_cells: list[Tag] = []
    thead = table.find("thead")
    if thead is not None:
        header_cells = list(thead.find_all("th"))
    if not header_cells:
        first_row = table.find("tr")
        if first_row is not None:
            header_cells = list(first_row.find_all(["th", "td"]))

    column_labels = [text_of(cell) for cell in header_cells[1:]]

    body = table.find("tbody") or table
    rows: list[MatrixRow] = []
    used_row_ids: set[str] = set()
    row_cells: list[list[Tag]] = []
    for index, tr in enumerate(body.find_all("tr")):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        row_label = text_of(cells[0])
        if not row_label:
            continue
        rows.append(
            MatrixRow(
                id=unique_id(slugify(row_label, f"row_{index + 1}"), used_row_ids),
                label=row_label,
            )
        )
        row_cells.append(cells)

    if not rows:
        return None

    if not column_labels:
        max_columns = max(len(cells) - 1 for cells in row_cells)
        column_labels = [f"Column {i + 1}" for i in range(max_columns)]

    columns: list[Option] = []
    used_col_ids: set[str] = set()
    for index, label in enumerate(column_labels):
        value = None
        for cells in row_cells:
            if index + 1 >= len(cells):
                continue
            inp = cells[index + 1].find("input")
            if inp is not None and inp.get("value"):
                value = str(inp.get("value"))
                break
        column_id = value or slugify(label, f"col_{index + 1}")
        columns.append(
            Option(
                id=unique_id(column_id, used_col_ids),
                label=label or column_id,
                value=value,
            )
        )

    depends_on, depends_value, hint, hidden = _conditional(container)
    required = "all rows" in text.lower() or _is_required(container, [table], text)
    question = Question(
        question_id=_make_qid(container, table.get("id"), len(existing), used_qids),
        text=text,
        question_type=QuestionType.matrix,
        required=required,
        options=columns,
        matrix=MatrixSpec(rows=rows, columns=columns),
        depends_on=depends_on,
        depends_value=depends_value,
        conditional_hint=hint,
        requires_personal_fact=True,
        text_unavailable=text_unavailable,
        options_unresolved=has_unresolved_template([c.label for c in columns]),
        hidden=hidden,
        raw={
            "control": "matrix",
            "table_id": table.get("id"),
            "row_count": len(rows),
            "column_count": len(columns),
            "row_labels": [row.label for row in rows],
            "column_labels": [column.label for column in columns],
        },
    )
    question.fingerprint = _fingerprint(question)
    return question


def _looks_like_ranking(node: Tag) -> bool:
    items = node.find_all("li", recursive=False) or node.find_all("li")
    if len(items) < 2:
        return False
    classes = " ".join(node.get("class") or []).lower()
    item_classes = " ".join(
        " ".join(item.get("class") or []) for item in items
    ).lower()
    if any(
        token in classes
        for token in ("menu", "nav", "tab", "breadcrumb", "pagination", "carousel", "steps")
    ):
        return False
    marker = classes + " " + item_classes
    return (
        any(token in marker for token in ("rank", "sort", "order", "draggable", "drag"))
        or any(item.has_attr("draggable") or item.has_attr("data-factor") for item in items)
    )


def _extract_ranking(
    node: Tag,
    soup: Tag,
    existing: list[Question],
    used_qids: set[str],
) -> Question | None:
    items = node.find_all("li", recursive=False) or node.find_all("li")
    if len(items) < 2:
        return None

    container = find_question_container(node) or node
    text, text_unavailable = _resolve_text(container, [node], soup)

    used_ids: set[str] = set()
    options: list[Option] = []
    for index, item in enumerate(items):
        label = text_of(item)
        label = re.sub(r"^[\s⋮≡▾▸•\-]+", "", label)
        label = re.sub(r"^\d+\s*", "", label)
        label = normalize_text(label)
        if not label:
            continue
        raw_id = item.get("data-factor") or item.get("id")
        option_id = str(raw_id) if raw_id else slugify(label, f"rank_{index + 1}")
        options.append(Option(id=unique_id(option_id, used_ids), label=label))

    if len(options) < 2:
        return None

    depends_on, depends_value, hint, hidden = _conditional(container)
    question = Question(
        question_id=_make_qid(container, node.get("id"), len(existing), used_qids),
        text=text,
        question_type=QuestionType.ranking,
        required=True,
        options=options,
        min_selections=len(options),
        max_selections=len(options),
        depends_on=depends_on,
        depends_value=depends_value,
        conditional_hint=hint,
        requires_personal_fact=False,
        text_unavailable=text_unavailable,
        hidden=hidden,
        raw={"control": "ranking", "list_id": node.get("id")},
    )
    question.fingerprint = _fingerprint(question)
    return question


# ---------------------------------------------------------------- ARIA custom widgets


def _extract_aria_question(
    node: Tag,
    soup: Tag,
    existing: list[Question],
    used_qids: set[str],
) -> Question | None:
    role = (node.get("role") or "").lower()
    container = find_question_container(node) or node

    if role in {"radiogroup", "listbox"}:
        choices = node.find_all(attrs={"role": "radio"}) or node.find_all(
            attrs={"role": "option"}
        )
        if len(choices) < 1:
            return None
        return _aria_choice(choices, container, soup, existing, used_qids,
                            QuestionType.single_choice)

    if role == "radio":
        parent = node.find_parent(attrs={"role": "radiogroup"})
        choices = (
            parent.find_all(attrs={"role": "radio"})
            if parent is not None
            else node.find_all(attrs={"role": "radio"}) or [node]
        )
        return _aria_choice(choices, container, soup, existing, used_qids,
                            QuestionType.single_choice)

    if role == "checkbox":
        choices = node.find_all(attrs={"role": "checkbox"})
        if len(choices) < 2:
            choices = [node]
        return _aria_choice(choices, container, soup, existing, used_qids,
                            QuestionType.multi_choice)

    if role == "combobox":
        options = node.find_all(attrs={"role": "option"})
        if not options:
            text, text_unavailable = _resolve_text(container, [node], soup)
            return Question(
                question_id=_make_qid(container, node.get("id"), len(existing), used_qids),
                text=text,
                question_type=QuestionType.unknown,
                required=_is_required(container, [node], text),
                text_unavailable=text_unavailable,
                raw={"control": "aria-combobox", "dynamic_options": True},
            )
        opts = [
            Option(
                id=str(o.get("data-value") or o.get("id") or slugify(
                    aria_option_label(o), f"opt_{i + 1}"
                )),
                label=aria_option_label(o),
            )
            for i, o in enumerate(options)
        ]
        text, text_unavailable = _resolve_text(container, [node], soup)
        q = Question(
            question_id=_make_qid(container, node.get("id"), len(existing), used_qids),
            text=text,
            question_type=QuestionType.dropdown,
            required=_is_required(container, [node], text),
            options=opts,
            text_unavailable=text_unavailable,
            raw={"control": "aria-combobox"},
        )
        q.fingerprint = _fingerprint(q)
        return q

    if role == "slider":
        text, text_unavailable = _resolve_text(container, [node], soup)
        q = Question(
            question_id=_make_qid(container, node.get("id"), len(existing), used_qids),
            text=text,
            question_type=QuestionType.rating,
            required=_is_required(container, [node], text),
            numeric=NumericSpec(
                min=_float_attr(node, "aria-valuemin", 0.0),
                max=_float_attr(node, "aria-valuemax", 100.0),
            ),
            text_unavailable=text_unavailable,
            raw={"control": "aria-slider"},
        )
        q.fingerprint = _fingerprint(q)
        return q

    if role == "spinbutton":
        return _extract_text_like(node, soup, existing, used_qids, QuestionType.number)

    if role == "textbox":
        return _extract_text_like(node, soup, existing, used_qids, QuestionType.text)

    return None


def _aria_choice(
    choices: list[Tag],
    container: Tag,
    soup: Tag,
    existing: list[Question],
    used_qids: set[str],
    qtype: QuestionType,
) -> Question | None:
    text, text_unavailable = _resolve_text(container, choices, soup)
    used_ids: set[str] = set()
    options: list[Option] = []
    for index, choice in enumerate(choices):
        label = aria_option_label(choice)
        raw_id = choice.get("data-value") or choice.get("id") or choice.get("aria-posinset")
        option_id = str(raw_id) if raw_id else slugify(label, f"opt_{index + 1}")
        options.append(
            Option(
                id=unique_id(option_id, used_ids),
                label=label or option_id,
                exclusive="none of the above" in label.lower(),
            )
        )
    if not options:
        return None
    inferred = _infer_topic(options)
    required = _is_required(container, choices, text)
    min_selections, max_selections = _selection_limits(text, qtype, required)
    depends_on, depends_value, hint, hidden = _conditional(container)
    question = Question(
        question_id=_make_qid(container, choices[0].get("id"), len(existing), used_qids),
        text=text,
        question_type=qtype,
        required=required,
        options=options,
        min_selections=min_selections,
        max_selections=max_selections,
        depends_on=depends_on,
        depends_value=depends_value,
        conditional_hint=hint,
        requires_personal_fact=_is_personal(text, inferred),
        text_unavailable=text_unavailable,
        options_unresolved=has_unresolved_template([o.label for o in options]),
        inferred_topic=inferred,
        hidden=hidden,
        raw={"control": f"aria-{qtype.value}", "role": choices[0].get("role")},
    )
    question.fingerprint = _fingerprint(question)
    return question


# ---------------------------------------------------------------- shared helpers


def _make_qid(
    container: Tag | None,
    fallback_name: str | None,
    index: int,
    used_qids: set[str],
) -> str:
    raw = None
    if container is not None:
        raw = (
            container.get("data-question-id")
            or container.get("data-question")
            or container.get("id")
        )
    raw = raw or fallback_name or f"Q{index + 1}"
    candidate = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(raw)).strip("_") or f"Q{index + 1}"
    candidate = candidate[:128]
    if candidate not in used_qids:
        used_qids.add(candidate)
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in used_qids:
        suffix += 1
    final = f"{candidate}_{suffix}"[:128]
    used_qids.add(final)
    return final


def _resolve_text(
    container: Tag | None,
    controls: list[Tag],
    soup: Tag,
) -> tuple[str, bool]:
    text_unavailable = False
    image_title = False

    if container is not None:
        for attribute in ("data-question-text", "data-label", "data-title"):
            value = container.get(attribute)
            if value:
                return _clean_question_text(str(value)), False

    if controls:
        labelledby = controls[0].get("aria-labelledby")
        if labelledby:
            parts = []
            for ref in str(labelledby).split():
                target = soup.find(id=ref)
                if target is not None:
                    parts.append(text_of(target))
            joined = normalize_text(" ".join(parts))
            if joined:
                return _clean_question_text(joined), False

    if container is not None:
        title_selectors = (
            ".qtitle", ".question-title", ".qtext", ".question-text",
            ".qsub", "legend", "h1", "h2", "h3", "h4", "h5", "h6",
        )
        for selector in title_selectors:
            element = container.select_one(selector)
            if element is None:
                continue
            if element.find("img") is not None and not normalize_text(element.get_text()):
                text_unavailable = True
                image_title = True
                continue
            candidate = _clean_question_text(normalize_text(element.get_text(" ")))
            if candidate and not _is_generic_text(candidate):
                return candidate, text_unavailable

        if image_title:
            # 题干被替换成图片（无 alt），不能把选项文本误当成题干。
            return "", True

        for element in container.find_all(["p", "label", "div", "span"], limit=60):
            if contains_control(element) or _inside_option_label(element):
                continue
            if element.find("img") is not None and not normalize_text(element.get_text()):
                text_unavailable = True
                continue
            candidate = _clean_question_text(normalize_text(element.get_text(" ")))
            if candidate and not _is_generic_text(candidate):
                return candidate, text_unavailable

        preceding = find_preceding_text(container)
        if preceding:
            candidate = _clean_question_text(preceding)
            if candidate and not _is_generic_text(candidate):
                return candidate, text_unavailable

    for control in controls:
        header = normalize_text(control.get("aria-label"))
        if header:
            return _clean_question_text(header), text_unavailable

    return "", text_unavailable


def _inside_option_label(element: Tag) -> bool:
    parent = element.find_parent("label")
    return parent is not None and parent.find(["input", "select", "textarea"]) is not None


def _clean_question_text(value: str) -> str:
    text = normalize_text(value, limit=1200)
    text = re.sub(r"^\s*\d+[.)]\s*", "", text)
    text = re.sub(r"\s*\*+\s*$", "", text)
    return normalize_text(text)


def _is_generic_text(text: str) -> bool:
    normalized = text.strip().lower().rstrip("….")
    return normalized in {value.rstrip("….") for value in GENERIC_TEXT}


def _is_required(container: Tag | None, controls: list[Tag], text: str) -> bool:
    for control in controls:
        if control.has_attr("required"):
            return True
        if (control.get("aria-required") or "").lower() == "true":
            return True
    if text.rstrip().endswith("*"):
        return True
    if container is not None:
        for element in container.find_all(True, limit=80):
            classes = element.get("class") or []
            if any(str(cls).lower() == "req" for cls in classes):
                return True
    return False


def _selection_limits(
    text: str,
    qtype: QuestionType,
    required: bool,
) -> tuple[int | None, int | None]:
    if qtype not in {QuestionType.multi_choice, QuestionType.dropdown}:
        return None, None

    lower = text.lower()
    min_selections: int | None = None
    max_selections: int | None = None

    match = re.search(
        r"(?:select|choose)\s+(?:up to|at most|maximum of)\s+(\d+)", lower
    )
    if match:
        max_selections = int(match.group(1))
    match = re.search(
        r"(?:select|choose)\s+(?:at least|minimum of)\s+(\d+)", lower
    )
    if match:
        min_selections = int(match.group(1))
    match = re.search(r"(?:select|choose)\s+exactly\s+(\d+)", lower)
    if match:
        min_selections = max_selections = int(match.group(1))

    if "all that apply" in lower and min_selections is None:
        min_selections = 1
    if required and min_selections is None and qtype == QuestionType.multi_choice:
        min_selections = 1
    return min_selections, max_selections


def _detect_topic_from_text(text: str) -> str | None:
    lower = text.lower()
    if re.search(r"how old|your age|\bage\b", lower):
        return "age"
    if re.search(r"country|reside", lower):
        return "country"
    if re.search(r"gender|\bsex\b", lower):
        return "gender"
    if re.search(r"industry", lower):
        return "industry"
    if re.search(r"department", lower):
        return "department"
    return None


def _infer_topic(options: list[Option]) -> str | None:
    labels = [normalize_text(option.label).lower() for option in options if option.label]
    if len(labels) < 2:
        return None

    if len(labels) >= 3 and all(re.fullmatch(r"\d{1,3}", label) for label in labels):
        numbers = [int(label) for label in labels]
        return "rating" if max(numbers) <= 100 else None

    age_matches = sum(1 for label in labels if AGE_LABEL_RE.match(label))
    if age_matches >= 2:
        return "age"

    if sum(1 for label in labels if label in GENDER_LABELS) >= 2:
        return "gender"

    if sum(1 for label in labels if label in COUNTRY_LABELS) >= 3:
        return "country"

    return None


def _is_personal(text: str, inferred_topic: str | None) -> bool:
    if inferred_topic in {"age", "country", "gender"}:
        return True
    topic = _detect_topic_from_text(text)
    if topic is not None:
        return True
    return bool(PERSONAL_RE.search(text or ""))


def _conditional(element: Tag) -> tuple[str | None, str | None, str | None, bool]:
    depends_on: str | None = None
    depends_value: str | None = None
    hint: str | None = None
    node: Tag | None = element
    while isinstance(node, Tag) and node.name not in {"body", "html"}:
        if depends_on is None and node.get("data-depends-on"):
            depends_on = normalize_text(node.get("data-depends-on"))
        if depends_value is None and node.get("data-depends-value") is not None:
            depends_value = normalize_text(str(node.get("data-depends-value"))) or None
        for attribute in ("data-show-if", "data-condition", "v-if", "v-show"):
            if hint is None and node.get(attribute):
                hint = normalize_text(str(node.get(attribute)))
        node = node.parent
    return depends_on, depends_value, hint, is_hidden(element)


def _float_attr(element: Tag, name: str, default: float | None = None) -> float | None:
    value = element.get(name)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_fingerprint(question: Question) -> str:
    return _fingerprint(question)


def _fingerprint(question: Question) -> str:
    payload = {
        "text": normalize_text(question.text).lower(),
        "type": question.question_type.value,
        "options": sorted(
            normalize_text(option.label).lower() for option in question.options
        ),
        "matrix": (
            {
                "rows": [row.label.lower() for row in question.matrix.rows],
                "columns": [column.label.lower() for column in question.matrix.columns],
            }
            if question.matrix
            else None
        ),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
