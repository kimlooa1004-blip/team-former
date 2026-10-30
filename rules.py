"""팀 편성 규칙 엔진.

이 파일에는 DB도 Streamlit도 들어오지 않는다. 순수 함수만 둔다.
같은 함수를 앱(actions.py)과 시험(tests/test_scenarios.py)이 함께 쓰게 하여,
시험에서 통과한 규칙과 실제로 앱이 쓰는 규칙이 어긋나지 않게 한다.

공고 2.3절(팀 규칙), 2.4절(지원과 투표), 2.5절 4항(배정안 검사)을 그대로 옮긴 것이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

# 공고 2.2절: 역할은 6개
ROLES: tuple[str, ...] = (
    "기획자",
    "웹 프로그래머",
    "프론트엔드 디자이너",
    "테스터",
    "보고서 작성자",
    "발표자",
)

# 공고 2.3절 "필수 포함 역할": 모든 팀에 서로 다른 사람으로 1명씩 있어야 함
REQUIRED_ROLES: tuple[str, ...] = ("기획자", "웹 프로그래머")

TEAM_MIN = 2  # 공고 2.3절 인원: 확정한 구성에서 모든 팀은 2~4명
TEAM_MAX = 4

# result 안내의 첫 단어 (공고 2.7절)
OK = "승인"
WAIT = "대기"
REJECT = "거절"
BLOCK = "막힘"


@dataclass(frozen=True)
class Student:
    student_no: str
    name: str
    main_role: str
    sub_roles: tuple[str, ...] = ()

    @property
    def roles(self) -> tuple[str, ...]:
        """주 역할과 보조 역할을 합친 것. 필수 포함 역할을 맡을 수 있는지 따질 때 쓴다."""
        out = [self.main_role]
        for r in self.sub_roles:
            if r and r not in out:
                out.append(r)
        return tuple(out)

    def can_fill(self, role: str) -> bool:
        """공고 2.3절: 주 역할이나 보조 역할로 그 역할을 맡을 수 있는가."""
        return role in self.roles

    @property
    def label(self) -> str:
        subs = ", ".join(self.sub_roles) if self.sub_roles else "없음"
        return f"{self.name} (주 {self.main_role} / 보조 {subs})"


# ---------------------------------------------------------------------------
# 필수 포함 역할 계산
# ---------------------------------------------------------------------------


def required_filled(members: Sequence[Student]) -> int:
    """지금 팀원으로 채울 수 있는 필수 포함 역할의 최대 개수(0~2).

    공고 3장: "기획자와 웹 프로그래머는 서로 다른 학생이 맡아야 하므로,
    한 학생이 둘 다 할 수 있어도 하나로만 셈."
    그래서 단순히 "맡을 수 있는 사람이 있는가"를 세지 않고,
    서로 다른 사람에게 하나씩 짝지을 수 있는 최대 개수를 센다.
    """
    planners = [m for m in members if m.can_fill(REQUIRED_ROLES[0])]
    coders = [m for m in members if m.can_fill(REQUIRED_ROLES[1])]
    if planners and coders:
        for a in planners:
            for b in coders:
                if a.student_no != b.student_no:
                    return 2
        return 1  # 둘 다 할 수 있는 사람이 혼자만 있는 경우 -> 1개만 채운 것
    if planners or coders:
        return 1
    return 0


def required_unfilled(members: Sequence[Student]) -> int:
    """아직 채우지 못한 필수 포함 역할 수(0~2)."""
    return len(REQUIRED_ROLES) - required_filled(members)


def missing_required_roles(members: Sequence[Student]) -> list[str]:
    """어떤 필수 포함 역할이 비었는지 사람이 읽을 수 있게 돌려준다(안내문용)."""
    if required_unfilled(members) == 0:
        return []
    missing = []
    for role in REQUIRED_ROLES:
        others = [m for m in members if m.can_fill(role)]
        if not others:
            missing.append(role)
    if not missing:
        # 둘 다 할 수 있는 사람이 한 명뿐인 경우
        missing.append(f"{REQUIRED_ROLES[0]}/{REQUIRED_ROLES[1]} 가운데 1개")
    return missing


def required_seats_short(members_after: Sequence[Student]) -> bool:
    """공고 3장 "필수 포함 역할 자리 계산".

    지원자가 들어간 뒤 남는 자리 수가, 그 팀에서 아직 채우지 못한
    필수 포함 역할 수보다 적으면 True(지원을 막아야 함).
    """
    seats_left = TEAM_MAX - len(members_after)
    return seats_left < required_unfilled(members_after)


def main_role_conflict(applicant: Student, members: Sequence[Student]) -> bool:
    """공고 2.3절 주 역할 중복: 주 역할이 같은 학생이 한 팀에 2명 이상이면 안 됨."""
    return any(m.main_role == applicant.main_role for m in members)


# ---------------------------------------------------------------------------
# 지원 검사 (공고 2.4절)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    head: str  # "승인" / "대기" / "거절" / "막힘"
    reason: str = ""

    @property
    def text(self) -> str:
        return f"{self.head}: {self.reason}" if self.reason else self.head

    @property
    def accepted(self) -> bool:
        return self.head != BLOCK


def check_apply(
    applicant: Student,
    team_members: Sequence[Student],
    *,
    closed: bool,
    has_team: bool,
    has_pending: bool,
    guard_required_seats: bool = True,
) -> Decision:
    """지원 단추를 누른 순간 하는 검사. 막히면 DB에 기록하지 않는다(공고 2.4절 "막힌 지원").

    guard_required_seats=False 로 두면 3장 "필수 포함 역할을 지킬 수 없는 팀"의
    쉬운 해결(지원 단계에서 막지 않음)이 된다. 이 앱은 어려운 해결을 쓰므로 True.
    """
    if closed:
        return Decision(BLOCK, "모집이 마감됨")
    if has_team:
        return Decision(BLOCK, "이미 팀이 있음")
    if has_pending:
        return Decision(BLOCK, "결과를 기다리는 지원이 있음")
    if len(team_members) >= TEAM_MAX:
        return Decision(BLOCK, "팀이 꽉 참")
    if main_role_conflict(applicant, team_members):
        return Decision(BLOCK, "같은 주 역할의 팀원이 있음")
    if guard_required_seats and required_seats_short(list(team_members) + [applicant]):
        return Decision(BLOCK, "필수 포함 역할을 맡을 학생의 자리가 모자람")
    # 공고 2.4절: 빈 팀에 지원하면 투표할 팀원이 없으므로 바로 승인
    if not team_members:
        return Decision(OK, "빈 팀이라 바로 승인함")
    return Decision(WAIT, "팀원의 투표를 기다림")


def tally_votes(member_nos: Iterable[str], votes: dict[str, str]) -> str:
    """팀원의 투표를 세어 다음에 할 일을 정한다 (공고 2.4절).

    member_nos : 지금 그 팀의 팀원 학번들. "투표할 사람은 투표하는 때의 팀원임"이므로
                 지원한 뒤에 들어온 팀원도 투표 대상에 들어간다.
    votes      : 학번 -> "찬성" / "거부"

    돌려주는 값: "거부"(한 명이라도 거부 -> 바로 거절), "찬성"(모두 찬성 -> 승인 검사로),
                "대기"(아직 투표하지 않은 팀원이 있음)
    """
    member_nos = list(member_nos)
    if any(votes.get(no) == "거부" for no in member_nos):
        return "거부"
    if member_nos and all(votes.get(no) == "찬성" for no in member_nos):
        return "찬성"
    return "대기"


def check_before_approve(
    applicant: Student,
    team_members: Sequence[Student],
    *,
    closed: bool,
    guard_required_seats: bool = True,
) -> Decision:
    """승인 직전 재검사 (공고 2.4절, 3장 "같은 팀에 대기 중인 지원이 여럿"의 어려운 해결).

    앞의 지원이 먼저 승인되어 팀이 바뀌었을 수 있으므로 승인하려는 순간 다시 검사한다.
    """
    if closed:
        return Decision(REJECT, "모집이 마감됨")
    if len(team_members) >= TEAM_MAX:
        return Decision(REJECT, "승인 직전 검사에서 팀이 꽉 참")
    if main_role_conflict(applicant, team_members):
        return Decision(REJECT, "승인 직전 검사에서 같은 주 역할의 팀원이 생김")
    if guard_required_seats and required_seats_short(list(team_members) + [applicant]):
        return Decision(REJECT, "승인 직전 검사에서 필수 포함 역할 자리가 모자람")
    return Decision(OK, "모든 팀원이 찬성함")


# ---------------------------------------------------------------------------
# 배정안 검사 (공고 2.5절 4항) — 다섯 가지
# ---------------------------------------------------------------------------


def validate_assignment(
    final_teams: dict[int, list[Student]],
    unassigned: Sequence[Student],
    placement: dict[str, int],
) -> list[str]:
    """배정안이 공고 2.5절 4항의 검사 다섯 가지를 통과하는지 본다.

    final_teams : 배정을 적용한 뒤의 팀 번호 -> 팀원 목록
    unassigned  : 팀이 없던 학생들
    placement   : 학번 -> 팀 번호 (AI나 솔버가 낸 배정안)

    통과하면 빈 목록, 아니면 어긋난 이유 목록을 돌려준다.
    """
    errors: list[str] = []

    # 1) 팀이 없는 학생이 빠짐없이 배정됨
    missing = [s.name for s in unassigned if s.student_no not in placement]
    if missing:
        errors.append("배정되지 않은 학생이 있음: " + ", ".join(missing))

    # 2) 한 학생은 한 팀에만 배정됨
    #    placement 는 학번이 열쇠라 중복이 생길 수 없으나,
    #    배정 대상이 아닌 학생(이미 팀이 있는 학생)이 섞여 들어왔는지 본다.
    allowed = {s.student_no for s in unassigned}
    extra = [no for no in placement if no not in allowed]
    if extra:
        errors.append("배정 대상이 아닌 학생이 들어 있음: " + ", ".join(extra))

    for team_no, members in sorted(final_teams.items()):
        nos = [m.student_no for m in members]
        if len(nos) != len(set(nos)):
            errors.append(f"팀{team_no}에 같은 학생이 두 번 들어 있음")

        # 3) 모든 팀이 2~4명
        if not (TEAM_MIN <= len(members) <= TEAM_MAX):
            errors.append(f"팀{team_no}의 인원이 {len(members)}명임(2~4명이어야 함)")

        # 4) 팀 안에서 주 역할 중복 없음
        mains = [m.main_role for m in members]
        dup = {r for r in mains if mains.count(r) > 1}
        if dup:
            errors.append(f"팀{team_no}에 주 역할이 겹치는 팀원이 있음: {', '.join(sorted(dup))}")

        # 5) 필수 포함 역할 충족
        if members and required_unfilled(members) > 0:
            miss = ", ".join(missing_required_roles(members))
            errors.append(f"팀{team_no}에 {miss} 역할을 맡을 학생이 없음")

    return errors


def apply_placement(
    teams: dict[int, list[Student]],
    unassigned: Sequence[Student],
    placement: dict[str, int],
) -> dict[int, list[Student]]:
    """지금 팀 구성에 배정안을 얹은 결과를 만든다. 원래 팀원은 옮기지 않는다."""
    by_no = {s.student_no: s for s in unassigned}
    out = {no: list(members) for no, members in teams.items()}
    for student_no, team_no in placement.items():
        student = by_no.get(student_no)
        if student is None or team_no not in out:
            continue
        out[team_no].append(student)
    return out
