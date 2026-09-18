# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A RAG-style agent (LangGraph) that answers inbound 편집실(video editing studio, "후킹포인트"/Hooking Point) inquiries — modeled on KakaoTalk-style messages — by classifying into one of five categories, retrieving only that category's source doc, generating a grounded answer, and verifying it before returning it. If classification is `unclear`, or verification finds the answer isn't grounded in the retrieved doc, it hands off to a fixed "a human will follow up" message instead of guessing. Design rationale, mapping table, eval design, and results are in `REPORT.md` — read that before making changes, since several prompt rules exist specifically to fix bugs found during evaluation (see its §4 iteration log).

## Commands

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...

python agent.py "편집실 위치가 어디예요?"   # run the full pipeline on one message
python evaluate.py                          # run data/goldenset.json, print + save metrics
streamlit run app.py                        # interactive demo
```

Model is selected via `ROUTER_MODEL` (default `gpt-4o-mini`), the answer-grading model in `evaluate.py` via `GRADER_MODEL` (default `gpt-4o-mini`).

`evaluate.py` *is* the test suite — there is no other test framework. It measures two separate things: tool-call correctness (did `classify` pick the category matching `expected_tool`? — accuracy, macro F1, confusion matrix) and answer correctness (does the final answer contain every `required_facts` entry and none of `forbidden_facts`, judged by an LLM grader). It runs `sanity_check_grader()` first to catch a broken grader before trusting its verdicts on real cases.

## Architecture

- `docs/*.md` are the source-of-truth content per category (real business content — editor profile, filmography, staff, location, partner companies, per-genre process, contact copy). Edit these, not a prompt, when the underlying facts change.
- `context.py` holds `CATEGORY_DOCS`, the category → doc mapping, and `get_evidence(category)`. `unclear` maps to `None` — no retrieval happens for it, by design.
- `prompts.py` holds three prompts (classify / answer / verify) plus `CLASSIFY_FEWSHOT_EXAMPLES`. Those few-shot examples are deliberately disjoint from `data/goldenset.json`'s cases — don't add goldenset phrasing here, it would contaminate the eval.
- `agent.py` wires everything into a LangGraph `StateGraph` (`AgentState`: text → category/reason → evidence → draft_answer → verification → final_answer/handoff). Two separate conditional edges matter: `route_after_classify` (skip retrieval entirely and go straight to `handoff` when category is `unclear` — classification-time bail-out) and `route_after_verify` (send a grounded answer to `finalize`, an ungrounded one to `handoff` — a *second*, independent safety net after generation). Both routes converge on the same `handoff` node, which returns the fixed `HANDOFF_MESSAGE`. `run_agent(text)` is the one pure function everything else (evaluate.py, app.py, a future 오픈빌더 webhook) should call — don't reimplement the graph invocation elsewhere.
- `evaluate.py`'s grader mechanically discards any `missing_required`/`present_forbidden` item the LLM judge returns that isn't verbatim in the case's own lists — this was added after observing the judge occasionally inventing text not in the input (see REPORT.md §4). Keep this filter; it's not optional cleanup.
- `app.py` (Streamlit) calls `run_agent()` per turn and displays category/reason, the raw evidence doc, and the verification JSON in an expander — the point is making "why this answer" inspectable, not just showing the answer.
- `skill_server.py` is the 오픈빌더 (Kakao i Open Builder) skill-server webhook, tested locally against both its code paths: synchronous (no `callbackUrl` in the request — used when curl-testing directly) and the callback path (`useCallback: true` + a background thread that POSTs the final answer to `callbackUrl` once `run_agent()` finishes, needed because the 3-LLM-call pipeline can exceed 오픈빌더's 5s skill timeout). Getting an actual KakaoTalk channel wired to this server requires Kakao account actions (channel creation, Open Builder setup, exposing this server's URL publicly) that have to happen outside this repo — see README.md's checklist.

## Extending

- New/edge cases go in `data/goldenset.json`, balanced across categories; give `required_facts`/`forbidden_facts` that are literal facts (or plausible-sounding wrong facts) from `docs/*.md`, not paraphrases you invent.
- If a category's real-world content changes, edit `docs/*.md` — `prompts.py`'s category descriptions are deliberately kept high-level/example-based so they don't need to change when a filmography credit or a partner company is added.
- If accuracy regresses, fix `prompts.py` (rules or few-shot examples) or add a route/node in `agent.py`, not by special-casing in `evaluate.py` or `app.py`.
