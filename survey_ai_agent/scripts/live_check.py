"""本地联调脚本：向运行中的服务提交测试问卷。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8790"
    task_id = sys.argv[2] if len(sys.argv) > 2 else "live-check-task"
    html = (ROOT / "tests" / "fixtures" / "survey.html").read_text(encoding="utf-8")
    payload = {
        "task_id": task_id,
        "page_id": "page-1",
        "html": html,
        "respondent_profile": {
            "age": 29,
            "country": "CN",
            "products": ["Pumps"],
            "years": 5,
        },
    }

    with httpx.Client(timeout=60) as client:
        health = client.get(f"{base_url}/healthz")
        print("healthz", health.status_code, json.dumps(health.json(), ensure_ascii=False))

        response = client.post(f"{base_url}/api/v1/agent/analyze", json=payload)
        print("analyze", response.status_code)
        data = response.json()
        if response.status_code != 200:
            print(json.dumps(data, ensure_ascii=False))
            return 1

        print("status:", data["status"], "answers:", len(data["answers"]))
        for answer in data["answers"]:
            print(
                " ",
                answer["question_id"],
                answer["status"],
                answer["selected_options"],
                answer["answer_text"],
                answer["source"],
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
