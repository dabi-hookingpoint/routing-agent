"""분류 → 근거 조회 → 답변 생성 → 검증 파이프라인 (LangGraph).

카테고리를 고르는 일(classify)과, 확신이 없을 때 넘기는 판단(unclear 라우팅,
그리고 검증 실패 시 넘기기)을 서로 다른 노드/엣지로 분리해뒀다.
"""

import json
import os
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph
from openai import OpenAI

from context import get_evidence
from prompts import ANSWER_SYSTEM_PROMPT, CATEGORIES, CLASSIFY_SYSTEM_PROMPT, VERIFY_SYSTEM_PROMPT

MODEL = os.environ.get("ROUTER_MODEL", "gpt-4o-mini")
HANDOFF_MESSAGE = (
    "문의 주신 내용은 제가 바로 답변드리기 어려워, 담당자가 확인 후 순차적으로 안내드리겠습니다. "
    "감사합니다.\nhooking.point@gmail.com"
)

_client = OpenAI()


class AgentState(TypedDict):
    text: str
    category: str
    reason: str
    evidence: Optional[str]
    draft_answer: Optional[str]
    verification: Optional[dict]
    final_answer: str
    handoff: bool


def _chat_json(system: str, user: str) -> dict:
    response = _client.chat.completions.create(
        model=MODEL,
        max_tokens=400,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    raw = response.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def classify_node(state: AgentState) -> dict:
    parsed = _chat_json(CLASSIFY_SYSTEM_PROMPT, state["text"])
    category = parsed.get("category")
    if category not in CATEGORIES:
        category = "unclear"
    return {"category": category, "reason": parsed.get("reason", "")}


def retrieve_node(state: AgentState) -> dict:
    return {"evidence": get_evidence(state["category"])}


def generate_node(state: AgentState) -> dict:
    response = _client.chat.completions.create(
        model=MODEL,
        max_tokens=400,
        messages=[
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"근거:\n{state['evidence']}\n\n문의: {state['text']}",
            },
        ],
    )
    return {"draft_answer": response.choices[0].message.content.strip()}


def verify_node(state: AgentState) -> dict:
    parsed = _chat_json(
        VERIFY_SYSTEM_PROMPT,
        f"근거:\n{state['evidence']}\n\n답변:\n{state['draft_answer']}",
    )
    if "grounded" not in parsed:
        parsed = {"grounded": False, "unsupported_claims": ["검증 응답 파싱 실패"]}
    return {"verification": parsed}


def finalize_node(state: AgentState) -> dict:
    return {"final_answer": state["draft_answer"], "handoff": False}


def handoff_node(state: AgentState) -> dict:
    return {"final_answer": HANDOFF_MESSAGE, "handoff": True}


def route_after_classify(state: AgentState) -> str:
    return "handoff" if state["category"] == "unclear" else "retrieve"


def route_after_verify(state: AgentState) -> str:
    return "finalize" if state["verification"].get("grounded") else "handoff"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("classify", classify_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_node("verify", verify_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("handoff", handoff_node)

    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify", route_after_classify, {"handoff": "handoff", "retrieve": "retrieve"}
    )
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges(
        "verify", route_after_verify, {"finalize": "finalize", "handoff": "handoff"}
    )
    graph.add_edge("finalize", END)
    graph.add_edge("handoff", END)
    return graph.compile()


GRAPH = build_graph()


def run_agent(text: str) -> AgentState:
    """텍스트 한 건을 파이프라인에 통과시켜 최종 상태를 반환한다."""
    initial: AgentState = {
        "text": text,
        "category": "",
        "reason": "",
        "evidence": None,
        "draft_answer": None,
        "verification": None,
        "final_answer": "",
        "handoff": False,
    }
    return GRAPH.invoke(initial)


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or "편집실 위치가 어디예요?"
    result = run_agent(text)
    print(json.dumps(result, ensure_ascii=False, indent=2))
