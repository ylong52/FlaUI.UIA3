"""解析任意 HTML，打印识别出的题目概览（调试用）。

用法：
    .venv\\Scripts\\python.exe scripts/inspect_page.py path\\to\\page.html
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.question_extractor import extract_questions  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: inspect_page.py <html-file>")
        return 2

    html = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    questions = extract_questions(html)
    print(f"questions: {len(questions)}")
    for question in questions:
        option_ids = [option.id for option in question.options]
        print(
            f"- {question.question_id} [{question.question_type.value}] "
            f"required={question.required} "
            f"text={question.text[:70]!r} "
            f"options={option_ids[:6]}"
            + (" ..." if len(option_ids) > 6 else "")
            + (" text_unavailable" if question.text_unavailable else "")
            + (" options_unresolved" if question.options_unresolved else "")
            + (f" depends_on={question.depends_on}" if question.depends_on else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
