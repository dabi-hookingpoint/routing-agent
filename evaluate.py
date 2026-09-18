"""골든셋으로 두 지표를 측정한다.

1. 도구 호출 적절성 — 예측 카테고리(=조회한 근거 문서)가 expected_tool과 정확히 일치하면 1점.
   accuracy, macro F1, 혼동행렬(confusion matrix)을 계산한다.
2. 답변 적절성 — required_facts를 전부 담고 forbidden_facts를 하나도 어기지 않으면 1점.
   표현이 아니라 사실 단위로 보도록 LLM 채점기를 쓰고, 채점기 자체는 모범/오답 예시로 먼저 검증한다.

사용법:
    export OPENAI_API_KEY=sk-...
    python evaluate.py
"""

import json
import os
from collections import defaultdict
from pathlib import Path

from openai import OpenAI

from agent import run_agent
from prompts import CATEGORIES

HERE = Path(__file__).parent
GRADER_MODEL = os.environ.get("GRADER_MODEL", "gpt-4o-mini")

_client = OpenAI()

GRADER_SYSTEM_PROMPT = """당신은 채점자입니다. "답변"이 "반드시 담아야 할 사실" 목록을 의미상 전부 포함하는지,
"말하면 안 되는 것" 목록 중 하나라도 등장하는지 판정하세요. 표현이 달라도 같은 사실이면 포함된 것으로 봅니다.

missing_required/present_forbidden에는 **입력으로 받은 목록의 항목을 그대로(원문 그대로)** 넣으세요.
목록에 없는 새로운 문장을 만들어 넣지 마세요 — 목록에 있는 항목 중 해당하는 것만 골라서 반환합니다.

반드시 아래 JSON 형식으로만 답하세요.

```json
{"missing_required": ["빠진 사실", "..."], "present_forbidden": ["등장한 금지 표현", "..."]}
```
"""


def grade_answer(answer: str, required_facts: list, forbidden_facts: list) -> dict:
    if not required_facts and not forbidden_facts:
        return {"missing_required": [], "present_forbidden": [], "score": 1}

    user = (
        f"반드시 담아야 할 사실: {json.dumps(required_facts, ensure_ascii=False)}\n"
        f"말하면 안 되는 것: {json.dumps(forbidden_facts, ensure_ascii=False)}\n"
        f"답변: {answer}"
    )
    response = _client.chat.completions.create(
        model=GRADER_MODEL,
        max_tokens=300,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": GRADER_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    )
    try:
        parsed = json.loads(response.choices[0].message.content.strip())
    except json.JSONDecodeError:
        parsed = {"missing_required": required_facts, "present_forbidden": ["채점 파싱 실패"]}

    # 기계적 안전장치: 채점기가 원래 목록에 없는 문장을 지어내 반환하면 버린다
    # (LLM judge가 이 목록 밖의 내용을 임의로 만들어내는 경우가 실제로 관찰됨).
    parsed["missing_required"] = [f for f in parsed.get("missing_required", []) if f in required_facts]
    parsed["present_forbidden"] = [f for f in parsed.get("present_forbidden", []) if f in forbidden_facts]

    parsed["score"] = 0 if (parsed["missing_required"] or parsed["present_forbidden"]) else 1
    return parsed


def sanity_check_grader() -> None:
    """채점기를 모범 답안/오답으로 먼저 검증한다 (실제 케이스 채점 전에 실행)."""
    required = ["서울 강서구"]
    forbidden = ["강남구"]

    good = grade_answer("네, 후킹포인트는 서울 강서구에 위치해 있습니다.", required, forbidden)
    bad_missing = grade_answer("편집실 위치는 확인 후 안내드리겠습니다.", required, forbidden)
    bad_forbidden = grade_answer("네, 강남구에 위치해 있습니다.", required, forbidden)

    assert good["score"] == 1, f"모범 답안이 0점 처리됨: {good}"
    assert bad_missing["score"] == 0, f"필수 사실 누락 답안이 1점 처리됨: {bad_missing}"
    assert bad_forbidden["score"] == 0, f"금지 표현 포함 답안이 1점 처리됨: {bad_forbidden}"
    print("채점기 자체 검증 통과 (모범 답안 1점 / 누락·오답 0점)\n")


def macro_f1(confusion: dict, categories: list) -> tuple:
    f1_per_category = {}
    for c in categories:
        tp = confusion[c][c]
        fp = sum(confusion[o][c] for o in categories if o != c)
        fn = sum(confusion[c][o] for o in categories if o != c)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        f1_per_category[c] = f1
    return sum(f1_per_category.values()) / len(categories), f1_per_category


def main():
    sanity_check_grader()

    data = json.loads(HERE.joinpath("data", "goldenset.json").read_text(encoding="utf-8"))
    cases = data["cases"]

    confusion = defaultdict(lambda: defaultdict(int))
    tool_correct = 0
    answer_correct = 0
    per_case_results = []

    for case in cases:
        expected_tool = case["expected_tool"]
        state = run_agent(case["text"])
        predicted_tool = state["category"]
        confusion[expected_tool][predicted_tool] += 1

        tool_ok = predicted_tool == expected_tool
        if tool_ok:
            tool_correct += 1

        grade = grade_answer(state["final_answer"], case["required_facts"], case["forbidden_facts"])
        # unclear 케이스는 실제로 넘기기(handoff)를 했는지도 답변 적절성에 포함시킨다.
        if expected_tool == "unclear" and not state["handoff"]:
            grade["score"] = 0
            grade.setdefault("missing_required", []).append("(넘기기를 하지 않고 답변을 생성함)")

        if grade["score"] == 1:
            answer_correct += 1

        per_case_results.append(
            {
                "id": case["id"],
                "text": case["text"],
                "expected_tool": expected_tool,
                "predicted_tool": predicted_tool,
                "tool_ok": tool_ok,
                "handoff": state["handoff"],
                "final_answer": state["final_answer"],
                "answer_ok": grade["score"] == 1,
                "missing_required": grade.get("missing_required", []),
                "present_forbidden": grade.get("present_forbidden", []),
                "note": case.get("note", ""),
            }
        )

        tag = "OK " if tool_ok and grade["score"] == 1 else "FAIL"
        print(f"[{tag}] {case['id']:18s} tool={predicted_tool:12s} (expected {expected_tool:12s}) "
              f"answer_ok={grade['score'] == 1}")

    total = len(cases)
    macro, f1_per_category = macro_f1(confusion, CATEGORIES)

    print("\n" + "=" * 60)
    print(f"도구 호출 적절성 (accuracy): {tool_correct}/{total} ({tool_correct / total:.1%})")
    print(f"도구 호출 적절성 (macro F1): {macro:.3f}")
    print("카테고리별 F1:")
    for c, f1 in f1_per_category.items():
        print(f"  {c:12s}: {f1:.3f}")

    print("\n혼동행렬 (행=정답, 열=예측):")
    header = "정답\\예측".ljust(14) + "".join(c[:8].rjust(10) for c in CATEGORIES)
    print(header)
    for c in CATEGORIES:
        row = c.ljust(14) + "".join(str(confusion[c][o]).rjust(10) for o in CATEGORIES)
        print(row)

    print(f"\n답변 적절성: {answer_correct}/{total} ({answer_correct / total:.1%})")

    failures = [r for r in per_case_results if not (r["tool_ok"] and r["answer_ok"])]
    if failures:
        print(f"\n실패 케이스 ({len(failures)}건):")
        for f in failures:
            print(f"  - [{f['id']}] \"{f['text']}\"")
            if not f["tool_ok"]:
                print(f"      도구 불일치: expected={f['expected_tool']} -> predicted={f['predicted_tool']}")
            if not f["answer_ok"]:
                print(f"      답변 문제: missing={f['missing_required']} forbidden_hit={f['present_forbidden']}")

    HERE.joinpath("data", "goldenset_results.json").write_text(
        json.dumps(
            {
                "tool_accuracy": tool_correct / total,
                "tool_macro_f1": macro,
                "tool_f1_per_category": f1_per_category,
                "confusion_matrix": {c: dict(confusion[c]) for c in CATEGORIES},
                "answer_accuracy": answer_correct / total,
                "cases": per_case_results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\n상세 결과를 data/goldenset_results.json 에 저장했습니다.")


if __name__ == "__main__":
    main()
