# 후킹포인트 편집실 문의 라우팅 에이전트

영화·드라마 편집실 "후킹포인트"의 카카오톡 문의를 **분류 → 근거 조회 → 답변 생성 → 검증** 파이프라인으로 처리하는 RAG형 에이전트 (LangGraph). 설계 배경·평가 결과·회고는 [REPORT.md](REPORT.md)에 있다.

## 구조

```
docs/                   # 근거 문서 (카테고리별)
data/goldenset.json     # 평가셋 (문의 + 기대 도구 + 필수 사실 + 금지 표현)
prompts.py              # 분류·답변·검증 프롬프트
context.py              # 카테고리 ↔ 근거 문서 매핑, 근거 조회
agent.py                # LangGraph 파이프라인
evaluate.py             # 도구 호출 적절성(accuracy·macro F1·혼동행렬) + 답변 적절성 측정
app.py                  # Streamlit 데모
skill_server.py         # 카카오 i 오픈빌더 스킬 서버 (웹훅)
requirements.txt
REPORT.md
```

## 카테고리

| 카테고리 | 근거 문서 | 설명 |
|---|---|---|
| `intro` | `docs/intro.md` | 후킹포인트 소개 — 편집 철학, 커버 가능한 장르/형식 |
| `studio_info` | `docs/studio_info.md` | 편집실 정보 — 편집감독 프로필, 필모그래피, 인력, 위치, 협력사 |
| `work_process` | `docs/work_process.md` | 작업 방식 — 가편집·수정, 일정, 전달물, 계약, 크레딧 |
| `contact` | `docs/contact.md` | 연락 — 전화/미팅 요청, 문의 개시 |
| `unclear` | (없음) | 위 4개 중 어디에도 속하지 않음 — 근거 조회 없이 바로 넘기기 |

## 실행 방법

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...

python agent.py "편집실 위치가 어디예요?"   # 단건 실행 (분류→근거조회→답변→검증 전체)
python evaluate.py                          # 골든셋 전체 평가 (도구/답변 적절성)
streamlit run app.py                        # 데모 화면
```

기본 모델은 `gpt-4o-mini` (`ROUTER_MODEL` 환경변수로 변경 가능, 채점 모델은 `GRADER_MODEL`).

## 카카오톡 채널(오픈빌더) 연동

`skill_server.py`가 오픈빌더 스킬 서버 스펙에 맞춘 웹훅이다. 로컬에서 다음처럼 띄운다.

```bash
export OPENAI_API_KEY=sk-...
python skill_server.py   # http://localhost:5000/skill
```

파이프라인이 LLM을 최대 3번(분류→답변생성→검증) 호출해서 오픈빌더의 기본 5초 응답 제한을 넘기기 쉽다. 그래서 콜백(`useCallback`) 방식을 쓴다 — 요청이 오면 즉시 "확인 중입니다" 임시 응답을 보내고, 백그라운드 스레드에서 `run_agent()`를 돌린 뒤 완료되면 오픈빌더가 준 `callbackUrl`로 최종 답변을 POST한다. `callbackUrl`이 없는 요청(예: `curl`로 직접 테스트)은 콜백 없이 동기로 즉시 답한다. 로컬에서 `curl`과 목(mock) 콜백 서버로 두 경로 모두 확인함.

**이 리포지토리 밖에서 직접 해야 하는 것** (카카오 계정 로그인이 필요해 대신 해줄 수 없는 단계):
1. [카카오톡 채널 관리자센터](https://center-pf.kakao.com)에서 채널 개설
2. [카카오 i 오픈빌더](https://chatbot.kakao.com)에서 챗봇 생성, 1번 채널과 연동
3. 오픈빌더 "스킬" 메뉴에서 스킬 추가 → URL에 `https://<공개도메인>/skill` 등록 — 로컬 서버는 공개 URL이 없으므로 ngrok 같은 터널이나 실제 호스팅(Render/Railway/Fly.io 등)이 필요함
4. 블록(예: 폴백 블록)에서 발화를 2번 스킬에 연결
5. 오픈빌더에서 "배포" 눌러야 실제 카카오톡에서 동작함

`skill_server.py`를 실제로 세상에 노출하기 전에, 프로덕션 WSGI 서버(gunicorn 등)로 바꾸는 것도 고려할 것 — 지금은 Flask 개발 서버라 "프로덕션에 쓰지 말라"는 경고가 뜬다.
