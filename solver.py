"""앱이 스스로 하는 배정 (공고 3장 "3차 모델까지 실패"의 어려운 해결).

AI 모델 3개가 모두 실패했을 때, 공고 2.5절 4항의 검사 다섯 가지를 모두 통과하는
배정을 "모든 경우를 따져 끝까지" 찾는다. 무작위로 넣는 쉬운 해결이 아니다.

되추적(backtracking)에 가지치기를 붙였다. 배정 대상 학생은 8명을 넘지 않고
(공고 6.2절 9항) 팀은 3~4개이므로, 가지치기를 하면 사실상 즉시 끝난다.

같은 함수를 "규칙을 지키는 배정이 있는가"를 미리 보는 데에도 쓴다.
배정이 아예 불가능하면 AI를 부르지 않고 바로 안내한다(공고 2.5절 8항).
"""

from __future__ import annotations

import time
from typing import Sequence

from rules import (
    REQUIRED_ROLES,
    TEAM_MAX,
    TEAM_MIN,
    Student,
    missing_required_roles,
    required_unfilled,
    validate_assignment,
)

# 혹시 모를 폭주를 막는 안전장치
NODE_LIMIT = 2_000_000
TIME_LIMIT_SEC = 8.0


class SolverResult:
    def __init__(self, placement: dict[str, int] | None, reasons: list[str], nodes: int, elapsed: float):
        self.placement = placement
        self.reasons = reasons
        self.nodes = nodes
        self.elapsed = elapsed

    @property
    def ok(self) -> bool:
        return self.placement is not None


def _teams_still_need(members: Sequence[Student]) -> int:
    """이 팀이 2명을 채우려면 앞으로 몇 명이 더 필요한가."""
    return max(0, TEAM_MIN - len(members))


def solve(
    teams: dict[int, list[Student]],
    unassigned: Sequence[Student],
    *,
    time_limit: float = TIME_LIMIT_SEC,
) -> SolverResult:
    """팀이 없는 학생만 팀에 넣는 배정을 찾는다. 이미 팀에 있는 학생은 옮기지 않는다."""
    started = time.monotonic()
    team_nos = sorted(teams)
    current: dict[int, list[Student]] = {no: list(teams[no]) for no in team_nos}
    students = list(unassigned)

    # 배정할 학생이 없으면 지금 구성이 그대로 규칙을 지키는지만 본다.
    if not students:
        errors = validate_assignment(current, [], {})
        if errors:
            return SolverResult(None, errors, 0, time.monotonic() - started)
        return SolverResult({}, [], 0, time.monotonic() - started)

    # 들어가기 전에 분명히 불가능한 경우를 먼저 걸러 내고 이유를 모은다.
    pre = _preflight(current, students)
    if pre:
        return SolverResult(None, pre, 0, time.monotonic() - started)

    placement: dict[str, int] = {}
    remaining = list(students)
    nodes = 0
    deadline = started + time_limit
    timed_out = False

    def feasible_teams(student: Student) -> list[int]:
        out = []
        for no in team_nos:
            members = current[no]
            if len(members) >= TEAM_MAX:
                continue
            if any(m.main_role == student.main_role for m in members):
                continue
            out.append(no)
        return out

    def prune() -> bool:
        """지금까지의 부분 배정으로 이미 불가능해졌으면 True."""
        left = len(remaining)
        need_min = sum(_teams_still_need(current[no]) for no in team_nos)
        if need_min > left:
            return True  # 2명을 채우지 못하는 팀이 생긴다
        free = sum(TEAM_MAX - len(current[no]) for no in team_nos)
        if left > free:
            return True  # 남은 학생을 넣을 자리가 모자라다

        # 필수 포함 역할: 팀마다 남은 자리가 빈 필수 역할 수보다 적으면 불가능
        need_role = {role: 0 for role in REQUIRED_ROLES}
        for no in team_nos:
            members = current[no]
            short = required_unfilled(members)
            if short > TEAM_MAX - len(members):
                return True
            for role in REQUIRED_ROLES:
                if not any(m.can_fill(role) for m in members):
                    need_role[role] += 1

        # 남은 학생 가운데 그 역할을 맡을 수 있는 사람이 모자라면 불가능 (홀의 조건)
        supply = {role: [s for s in remaining if s.can_fill(role)] for role in REQUIRED_ROLES}
        for role in REQUIRED_ROLES:
            if need_role[role] > len(supply[role]):
                return True
        union = {s.student_no for role in REQUIRED_ROLES for s in supply[role]}
        if sum(need_role.values()) > len(union):
            return True
        return False

    def search() -> bool:
        nonlocal nodes, timed_out
        if timed_out:
            return False
        nodes += 1
        if nodes > NODE_LIMIT or time.monotonic() > deadline:
            timed_out = True
            return False

        if not remaining:
            return not validate_assignment(current, students, placement)

        if prune():
            return False

        # MRV: 넣을 수 있는 팀이 가장 적은 학생부터 정한다 (가지가 빨리 줄어든다)
        best_i, best_opts = -1, None
        for i, student in enumerate(remaining):
            opts = feasible_teams(student)
            if not opts:
                return False
            if best_opts is None or len(opts) < len(best_opts):
                best_i, best_opts = i, opts
                if len(opts) == 1:
                    break

        student = remaining.pop(best_i)
        # 빈 자리가 급한 팀(아직 2명이 안 된 팀)부터 시도하면 답을 빨리 만난다
        best_opts.sort(key=lambda no: (-_teams_still_need(current[no]), len(current[no]), no))
        for no in best_opts:
            current[no].append(student)
            placement[student.student_no] = no
            if search():
                return True
            current[no].pop()
            placement.pop(student.student_no, None)
        remaining.insert(best_i, student)
        return False

    found = search()
    elapsed = time.monotonic() - started
    if found:
        return SolverResult(dict(placement), [], nodes, elapsed)

    reasons = _diagnose(teams, students, timed_out)
    return SolverResult(None, reasons, nodes, elapsed)


def _preflight(teams: dict[int, list[Student]], students: Sequence[Student]) -> list[str]:
    """시작도 하기 전에 분명한 이유로 불가능한 경우."""
    reasons: list[str] = []
    free = sum(TEAM_MAX - len(m) for m in teams.values())
    need_min = sum(_teams_still_need(m) for m in teams.values())
    if len(students) > free:
        reasons.append(f"팀이 없는 학생이 {len(students)}명인데 빈 자리는 {free}개뿐임")
    if need_min > len(students):
        reasons.append(f"모든 팀을 2명 이상으로 채우려면 {need_min}명이 필요한데 {len(students)}명뿐임")
    for no, members in sorted(teams.items()):
        short = required_unfilled(members)
        if short > TEAM_MAX - len(members):
            miss = ", ".join(missing_required_roles(members))
            reasons.append(f"팀{no}은 자리가 {TEAM_MAX - len(members)}개뿐인데 {miss} 역할이 비어 있음")
    return reasons


def _diagnose(teams: dict[int, list[Student]], students: Sequence[Student], timed_out: bool) -> list[str]:
    """되추적으로도 답을 찾지 못했을 때 관리자에게 보여 줄 이유."""
    if timed_out:
        return ["배정을 찾는 데 시간이 너무 오래 걸려 중단함"]
    reasons = _preflight(teams, students)
    if reasons:
        return reasons
    for role in REQUIRED_ROLES:
        need = [no for no, members in sorted(teams.items()) if not any(m.can_fill(role) for m in members)]
        supply = [s for s in students if s.can_fill(role)]
        if len(need) > len(supply):
            team_list = ", ".join(f"팀{no}" for no in need)
            reasons.append(
                f"{team_list}에 {role}를 맡을 학생이 없는데, 남은 학생 가운데 {role}를 맡을 수 있는 사람은 {len(supply)}명뿐임"
            )
    if not reasons:
        reasons.append("모든 경우를 따져 보았으나 2.3절의 규칙을 모두 지키는 배정 조합이 없음")
    return reasons
