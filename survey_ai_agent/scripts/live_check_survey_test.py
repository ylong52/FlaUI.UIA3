"""联调：用 survey-test 原始 HTML + demo_profile 调用真实 Agent。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8790"
    task_id = sys.argv[2] if len(sys.argv) > 2 else "survey-test-live"

    html = (ROOT / "tests" / "fixtures" / "survey-test-raw.html").read_text(
        encoding="utf-8"
    )
    profile = json.loads((ROOT / "demo_profile.json").read_text(encoding="utf-8"))
    payload = {
        "task_id": task_id,
        "page_id": "full-page",
        "html": html,
        "respondent_profile": profile,
        "options": {"page_adapter": "survey_test"},
    }

    with httpx.Client(timeout=180) as client:
        response = client.post(f"{base_url}/api/v1/agent/analyze", json=payload)
        print("HTTP", response.status_code)
        data = response.json()
        if response.status_code != 200:
            print(json.dumps(data, ensure_ascii=False))
            return 1

        print(
            "status:",
            data["status"],
            "answers:",
            len(data["answers"]),
            "tokens:",
            data["usage"]["total_tokens"],
        )
        for answer in data["answers"]:
            print(
                answer["question_id"],
                answer["status"],
                answer["source"],
                answer["selected_options"],
                answer["answer_text"],
                answer["matrix_selections"],
                answer["ranking"],
                answer["numeric_value"],
                answer["notes"],
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
