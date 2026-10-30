"""오픈라우터로 배정안을 받아 오기 (공고 2.5절 3~6항, 4.3절).

핵심 두 가지
1. 모델마다 120초의 "전체" 대기 시간을 잰다 (공고 3장 "AI 응답이 늦을 때"의 어려운 해결).
   requests 의 timeout 값은 응답이 시작될 때까지만 재는 경우가 많아, 응답이 천천히
   오면 120초를 넘길 수 있다. 그래서 호출을 다른 스레드에 맡기고 이쪽에서 시계를 재,
   120초가 지나면 기다리기를 그만두고 다음 모델로 넘어간다.
2. 1차 -> 2차 -> 3차 모델로 넘어가는 처리를 직접 만든다. 무료 모델로 자동 연결하는
   라우터(openrouter/free)는 쓰지 않는다 (공고 6.3절 14번: -2점).
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Callable, Sequence

import requests

from config import MODEL_TIMEOUT_SEC, OPENROUTER_URL, get_secret
from rules import REQUIRED_ROLES, TEAM_MAX, TEAM_MIN, Student


@dataclass
class Attempt:
    attempt_no: int
    model: str
    status: str  # 성공 / 시간 초과 / 오류 / 빈 응답 / 형식 오류 / 검사 실패
    elapsed_ms: int
    message: str = ""
    placement: dict[str, int] | None = None


def build_prompt(
    teams: dict[int, list[Student]],
    unassigned: Sequence[Student],
) -> str:
    lines: list[str] = []
    lines.append("대학교 팀 프로젝트의 팀 편성을 마무리하는 일이다.")
    lines.append("")
    lines.append("[규칙]")
    lines.append(f"1. 모든 팀의 인원은 {TEAM_MIN}명 이상 {TEAM_MAX}명 이하여야 한다. 빈 팀이 있으면 안 된다.")
    lines.append("2. 한 팀 안에 주 역할이 같은 학생이 2명 이상 있으면 안 된다.")
    lines.append(
        f"3. 모든 팀에는 '{REQUIRED_ROLES[0]}' 역할을 맡을 학생과 '{REQUIRED_ROLES[1]}' 역할을 맡을 학생이"
        " 서로 다른 사람으로 1명씩 있어야 한다."
        " 주 역할이 아니어도 보조 역할로 맡을 수 있다."
        " 한 학생이 둘 다 맡을 수는 없다."
    )
    lines.append("4. 이미 팀에 있는 학생은 절대 다른 팀으로 옮기지 않는다. 아래 '팀이 없는 학생'만 배정한다.")
    lines.append("5. 팀이 없는 학생은 한 명도 빠짐없이, 각자 정확히 한 팀에만 배정한다.")
    lines.append("")
    lines.append("[지금 팀 구성]")
    for team_no in sorted(teams):
        members = teams[team_no]
        if members:
            who = "; ".join(
                f"{m.name}(주 역할 {m.main_role}"
                + (f", 보조 역할 {', '.join(m.sub_roles)}" if m.sub_roles else "")
                + ")"
                for m in members
            )
        else:
            who = "(비어 있음)"
        lines.append(f"- 팀{team_no} ({len(members)}명): {who}")
    lines.append("")
    lines.append("[팀이 없는 학생]")
    for s in unassigned:
        subs = ", ".join(s.sub_roles) if s.sub_roles else "없음"
        lines.append(f"- 학번 {s.student_no} {s.name}: 주 역할 {s.main_role} / 보조 역할 {subs}")
    lines.append("")
    lines.append("[답하는 방법]")
    lines.append("설명이나 인사말을 쓰지 말고, 아래 꼴의 JSON 하나만 답한다.")
    lines.append('{"assignments": [{"student_no": "학번", "team": 팀번호}, ...]}')
    lines.append(
        f"team 은 1 이상 {max(teams) if teams else 1} 이하의 정수다. "
        "팀이 없는 학생 전원이 assignments 에 정확히 한 번씩 들어가야 한다."
    )
    return "\n".join(lines)


def extract_placement(text: str, valid_team_nos: set[int]) -> tuple[dict[str, int] | None, str]:
    """모델의 답에서 배정안을 꺼낸다. 코드 울타리나 앞뒤 설명이 붙어 있어도 읽어 낸다."""
    if not text or not text.strip():
        return None, "빈 응답"

    candidates: list[str] = []
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    candidates.extend(fenced)
    candidates.append(text)

    data = None
    for chunk in candidates:
        start = chunk.find("{")
        while start != -1:
            depth = 0
            for i in range(start, len(chunk)):
                if chunk[i] == "{":
                    depth += 1
                elif chunk[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(chunk[start : i + 1])
                        except json.JSONDecodeError:
                            data = None
                        break
            if data is not None:
                break
            start = chunk.find("{", start + 1)
        if data is not None:
            break

    if data is None:
        return None, "JSON 을 찾지 못함"

    rows = data.get("assignments") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return None, "assignments 목록이 없음"

    placement: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            return None, "assignments 의 항목이 사전이 아님"
        student_no = str(row.get("student_no", "")).strip()
        try:
            team_no = int(row.get("team"))
        except (TypeError, ValueError):
            return None, f"팀 번호가 정수가 아님: {row.get('team')!r}"
        if not student_no:
            return None, "학번이 비어 있음"
        if team_no not in valid_team_nos:
            return None, f"없는 팀 번호: {team_no}"
        if student_no in placement:
            return None, f"한 학생이 두 번 나옴: {student_no}"
        placement[student_no] = team_no
    return placement, ""


def _post(model: str, prompt: str, api_key: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "너는 규칙을 정확히 지키는 배정 담당자다. 반드시 JSON 하나만 답한다.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        # 추론 모델이 생각하는 데 길이 한도를 다 써서 빈 응답을 내는 일을 줄인다 (공고 4.3절)
        "max_tokens": 4000,
        "reasoning": {"effort": "low"},
    }
    response = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "team-former",
        },
        json=payload,
        timeout=(10, MODEL_TIMEOUT_SEC),
    )
    if response.status_code != 200:
        # 키 값이 섞여 나가지 않도록 본문은 앞부분만 쓴다
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    body = response.json()
    if "error" in body and body.get("error"):
        raise RuntimeError(str(body["error"])[:200])
    choices = body.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content") or ""


def call_one_model(
    attempt_no: int,
    model: str,
    prompt: str,
    valid_team_nos: set[int],
    *,
    timeout: int = MODEL_TIMEOUT_SEC,
) -> Attempt:
    """모델 하나를 부르고 120초의 전체 대기 시간을 잰다."""
    api_key = get_secret("OPENROUTER_API_KEY")
    started = time.monotonic()
    if not api_key:
        return Attempt(attempt_no, model, "오류", 0, "OPENROUTER_API_KEY 가 없음")

    # 호출마다 새 일꾼을 쓴다. 시간이 넘어 버려 둔 스레드가 다음 호출을 막지 않게 하려는 것.
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_post, model, prompt, api_key)
        try:
            text = future.result(timeout=timeout)
        except FutureTimeout:
            elapsed = int((time.monotonic() - started) * 1000)
            future.cancel()
            return Attempt(attempt_no, model, "시간 초과", elapsed, f"{timeout}초 안에 응답하지 않음")
        except Exception as exc:  # HTTP 429 등
            elapsed = int((time.monotonic() - started) * 1000)
            return Attempt(attempt_no, model, "오류", elapsed, str(exc)[:300])
    finally:
        executor.shutdown(wait=False)

    elapsed = int((time.monotonic() - started) * 1000)
    if not text.strip():
        return Attempt(attempt_no, model, "빈 응답", elapsed, "모델이 빈 응답을 냄")

    placement, problem = extract_placement(text, valid_team_nos)
    if placement is None:
        return Attempt(attempt_no, model, "형식 오류", elapsed, problem)
    return Attempt(attempt_no, model, "성공", elapsed, "", placement)


def ask_models(
    models: Sequence[str],
    prompt: str,
    valid_team_nos: set[int],
    *,
    validate: Callable[[dict[str, int]], list[str]],
    on_progress: Callable[[int, str, str], None] | None = None,
    deadline: float | None = None,
) -> tuple[dict[str, int] | None, list[Attempt]]:
    """1차 -> 2차 -> 3차 차례로 부른다. 검사를 통과한 첫 배정안을 돌려준다.

    validate : 배정안을 받아 어긋난 이유 목록을 돌려주는 함수(공고 2.5절 4항의 검사 다섯 가지).
               통과하지 못하면 그것도 실패로 보고 다음 모델로 넘어간다.
    on_progress(차수, 모델이름, 상태) : 화면에 "몇 차 모델을 기다리는 중"을 보여 주기 위한 것
                                      (공고 3장 "AI 대기 중 화면"의 어려운 해결).
    """
    attempts: list[Attempt] = []
    for i, model in enumerate(models, start=1):
        if deadline is not None and time.monotonic() > deadline:
            attempts.append(Attempt(i, model, "오류", 0, "전체 대기 시간을 넘겨 건너뜀"))
            continue
        if on_progress:
            on_progress(i, model, "요청 중")

        remaining = MODEL_TIMEOUT_SEC
        if deadline is not None:
            remaining = max(5, min(MODEL_TIMEOUT_SEC, int(deadline - time.monotonic())))
        attempt = call_one_model(i, model, prompt, valid_team_nos, timeout=remaining)

        if attempt.status == "성공" and attempt.placement is not None:
            errors = validate(attempt.placement)
            if errors:
                attempt.status = "검사 실패"
                attempt.message = "; ".join(errors)[:300]
                attempt.placement = None

        attempts.append(attempt)
        if on_progress:
            on_progress(i, model, attempt.status)
        if attempt.status == "성공" and attempt.placement is not None:
            return attempt.placement, attempts

    return None, attempts
