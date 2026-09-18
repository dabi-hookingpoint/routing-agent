"""카테고리 → 근거 문서 매핑, 그리고 카테고리별 근거 조립.

매핑표 (카테고리가 늘어나면 여기와 prompts.py의 카테고리 정의를 함께 고친다):

| 카테고리      | 근거 문서              |
|---------------|------------------------|
| intro         | docs/intro.md          |
| studio_info   | docs/studio_info.md    |
| work_process  | docs/work_process.md   |
| contact       | docs/contact.md        |
| unclear       | (없음 — 근거 조회 없이 넘기기) |
"""

from pathlib import Path
from typing import Optional

DOCS_DIR = Path(__file__).parent / "docs"

CATEGORY_DOCS = {
    "intro": DOCS_DIR / "intro.md",
    "studio_info": DOCS_DIR / "studio_info.md",
    "work_process": DOCS_DIR / "work_process.md",
    "contact": DOCS_DIR / "contact.md",
    "unclear": None,
}


def get_evidence(category: str) -> Optional[str]:
    """카테고리에 해당하는 근거 문서 전체 텍스트를 반환한다. unclear는 None."""
    path = CATEGORY_DOCS.get(category)
    if path is None:
        return None
    return path.read_text(encoding="utf-8")
