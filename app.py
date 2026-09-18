"""후킹포인트 편집실 문의 라우팅 데모 (Streamlit).

답변만 보여주는 게 아니라, 어떤 카테고리(도구)로 라우팅됐는지·
어떤 근거 문서를 썼는지·검증(그라운딩) 결과까지 함께 보여준다 —
"왜 이 답이 나왔는지"를 사람이 바로 확인할 수 있게 하는 게 목적.
"""

import streamlit as st

from agent import run_agent

st.set_page_config(page_title="후킹포인트 문의 라우팅 데모", page_icon="🎬")

CATEGORY_LABEL = {
    "intro": "후킹포인트 소개",
    "studio_info": "편집실 정보",
    "work_process": "작업 방식",
    "contact": "연락",
    "unclear": "분류 불가 (넘기기)",
}

st.title("🎬 후킹포인트 편집실 문의 데모")
st.caption("카카오톡 문의를 흉내낸 라우팅 에이전트 — 분류 → 근거 조회 → 답변 생성 → 검증")

if "history" not in st.session_state:
    st.session_state.history = []

for turn in st.session_state.history:
    with st.chat_message("user"):
        st.write(turn["text"])
    with st.chat_message("assistant"):
        st.write(turn["final_answer"])
        badge = "🔀 넘김" if turn["handoff"] else "✅ 자동 응답"
        st.caption(f"{badge} · 카테고리: **{CATEGORY_LABEL.get(turn['category'], turn['category'])}** ({turn['reason']})")
        with st.expander("근거 · 검증 결과 보기"):
            if turn["evidence"]:
                st.markdown("**조회한 근거 문서**")
                st.text(turn["evidence"])
            else:
                st.markdown("_근거 문서를 조회하지 않음 (unclear → 바로 넘기기)_")
            if turn["verification"] is not None:
                st.markdown("**검증(그라운딩 체크) 결과**")
                st.json(turn["verification"])

text = st.chat_input("문의를 입력해보세요 (예: 편집실 위치가 어디예요?)")
if text:
    with st.spinner("분류 → 근거 조회 → 답변 생성 → 검증 중..."):
        result = run_agent(text)
    st.session_state.history.append(result)
    st.rerun()
