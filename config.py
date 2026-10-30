"""비밀 값과 설정 (공고 4.1절).

오픈라우터 키, DB 주소, 관리자 비밀번호는 코드에 적지 않는다.
- 내 컴퓨터에서 돌릴 때: streamlit_app.py 와 같은 폴더의 .env 파일
- 배포한 앱에서     : Streamlit Secrets

이 파일은 값을 절대 화면이나 로그에 출력하지 않는다.
있는지 없는지만 알려 주는 secret_status() 를 쓴다.
"""

from __future__ import annotations

import os

try:  # 내 컴퓨터에서 돌릴 때만 .env 를 읽는다. 배포에는 .env 가 없다.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


def get_secret(name: str, default: str | None = None) -> str | None:
    """Streamlit Secrets -> 환경 변수(.env) 차례로 찾는다."""
    try:
        import streamlit as st

        if name in st.secrets:
            value = str(st.secrets[name]).strip()
            if value:
                return value
    except Exception:
        pass
    value = os.environ.get(name)
    return value.strip() if value else default


# 오픈라우터 텍스트 생성 모델 3개 (공고 4.3절).
# 무료 모델은 이름이 :free 로 끝난다. 무료 모델로 자동 연결하는 라우터
# (openrouter/free)는 쓰지 않는다 — 다음 모델로 넘기는 처리를 직접 만든다.
# Secrets 에 MODEL_1 / MODEL_2 / MODEL_3 을 넣으면 코드를 고치지 않고 바꿀 수 있다.
DEFAULT_MODELS = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-26b-a4b-it:free",
    "thinkingmachines/inkling-small:free",
)


def models() -> tuple[str, str, str]:
    picked = []
    for i in range(3):
        picked.append(get_secret(f"MODEL_{i + 1}") or DEFAULT_MODELS[i])
    return tuple(picked)  # type: ignore[return-value]


# 공고 3장 "AI 응답이 늦을 때"의 어려운 해결:
# 모델마다 120초의 전체 대기 시간을 재서 끊고 다음 모델로 넘어간다.
MODEL_TIMEOUT_SEC = 120

# 공고 6.3절 18번: AI 배정이 10분을 넘으면 감점. 세 모델을 다 써도 6분이지만
# 만약을 위해 전체에도 한도를 둔다.
TOTAL_ASSIGN_BUDGET_SEC = 400

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def secret_status() -> dict[str, bool]:
    """관리자 화면에 "있음 / 없음"만 보여 주기 위한 것. 값은 돌려주지 않는다."""
    return {
        "OPENROUTER_API_KEY": bool(get_secret("OPENROUTER_API_KEY")),
        "DATABASE_URL": bool(get_secret("DATABASE_URL")),
        "ADMIN_PASSWORD": bool(get_secret("ADMIN_PASSWORD")),
    }
