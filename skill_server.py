"""카카오 i 오픈빌더 스킬 서버 웹훅.

오픈빌더 "스킬" 등록 화면에 이 서버의 https://<도메인>/skill 을 등록하면,
사용자 발화가 이 엔드포인트로 POST되고 run_agent()의 최종 답변을
오픈빌더 스킬 응답 포맷(SimpleText)으로 돌려준다.

에이전트 파이프라인(분류→근거조회→답변생성→검증)은 LLM을 최대 3번 호출해서
오픈빌더의 기본 5초 응답 제한을 넘기기 쉽다. 그래서 콜백(useCallback) 방식을 쓴다.
1. 요청이 오면 곧바로 "확인 중" 임시 응답 + useCallback:true 를 보낸다.
2. 백그라운드 스레드에서 run_agent()를 실행하고, 끝나면 콜백 URL로 최종 답변을 POST한다.
   (오픈빌더는 콜백을 최대 1분까지 기다려준다.)

callbackUrl이 없는 요청(curl로 직접 테스트하는 경우 등)은 콜백 없이 동기로 바로 답변한다.
"""

import threading

import requests
from flask import Flask, jsonify, request

from agent import run_agent

app = Flask(__name__)

CATEGORY_QUICK_REPLIES = [
    {"label": "후킹포인트 소개", "action": "message", "messageText": "후킹포인트는 어떤 편집실이에요?"},
    {"label": "편집실 정보", "action": "message", "messageText": "필모그래피 좀 보여주실 수 있을까요"},
    {"label": "작업 방식", "action": "message", "messageText": "가편집은 몇 회차까지 봐주시나요?"},
    {"label": "연락", "action": "message", "messageText": "문의는 어디로 드리면 되나요?"},
]


def simple_text_response(text: str, with_quick_replies: bool = True) -> dict:
    template = {"outputs": [{"simpleText": {"text": text}}]}
    if with_quick_replies:
        template["quickReplies"] = CATEGORY_QUICK_REPLIES
    return {"version": "2.0", "template": template}


def _run_and_callback(utterance: str, callback_url: str) -> None:
    result = run_agent(utterance)
    payload = simple_text_response(result["final_answer"])
    try:
        requests.post(callback_url, json=payload, timeout=10)
    except requests.RequestException as exc:
        print(f"콜백 전송 실패: {exc}")


@app.route("/skill", methods=["POST"])
def skill():
    # silent=True: 본문이 비어있거나 JSON이 아니어도 예외 대신 None을 반환한다
    # (오픈빌더의 스킬 테스트 기능 등이 이런 요청을 보내는 경우가 있었음).
    body = request.get_json(silent=True) or {}
    utterance = body.get("userRequest", {}).get("utterance", "")
    callback_url = body.get("userRequest", {}).get("callbackUrl")

    if not callback_url:
        result = run_agent(utterance)
        return jsonify(simple_text_response(result["final_answer"]))

    threading.Thread(target=_run_and_callback, args=(utterance, callback_url), daemon=True).start()
    return jsonify(
        {
            "version": "2.0",
            "useCallback": True,
            "data": {"text": "문의 확인 중입니다. 잠시만 기다려주세요..."},
        }
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(port=5000)
