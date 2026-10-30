"""DB 없이 돌아가는 모형 앱.

actions.py(진짜 앱)와 똑같은 차례로 rules.py의 함수를 부른다.
규칙 판단은 전부 rules.py에 있으므로, 여기서 통과한 규칙은 앱에서도 같다.
연습용 시나리오를 빠르게 되풀이해 보려고 만든 것이다.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rules import (  # noqa: E402
    BLOCK,
    OK,
    REJECT,
    WAIT,
    Decision,
    Student,
    check_apply,
    check_before_approve,
    tally_votes,
)
from solver import solve  # noqa: E402


class Sim:
    def __init__(self, students: list[Student], team_count: int):
        self.students = {s.student_no: s for s in students}
        self.teams: dict[int, list[str]] = {i: [] for i in range(1, team_count + 1)}
        self.apps: list[dict] = []
        self.votes: dict[int, dict[str, str]] = {}
        self.closed = False

    # --- 조회 -------------------------------------------------------------
    def team_of(self, student_no: str) -> int | None:
        for no, members in self.teams.items():
            if student_no in members:
                return no
        return None

    def members(self, team_no: int) -> list[Student]:
        return [self.students[no] for no in self.teams[team_no]]

    def pending_of(self, student_no: str) -> dict | None:
        for app in self.apps:
            if app["student_no"] == student_no and app["status"] == WAIT:
                return app
        return None

    def unassigned(self) -> list[Student]:
        return [s for s in self.students.values() if self.team_of(s.student_no) is None]

    # --- 동작 (actions.py 와 같은 차례) -------------------------------------
    def apply(self, student_no: str, team_no: int) -> Decision:
        student = self.students[student_no]
        decision = check_apply(
            student,
            self.members(team_no),
            closed=self.closed,
            has_team=self.team_of(student_no) is not None,
            has_pending=self.pending_of(student_no) is not None,
        )
        if decision.head == BLOCK:
            return decision  # 막힌 지원은 기록하지 않음 (공고 2.4절)

        app = {
            "id": len(self.apps) + 1,
            "team_no": team_no,
            "student_no": student_no,
            "status": decision.head,
            "reason": decision.reason,
        }
        self.apps.append(app)
        self.votes[app["id"]] = {}
        if decision.head == OK:
            self._join(team_no, student_no)
        return decision

    def vote(self, voter_no: str, applicant_no: str, choice: str) -> Decision:
        app = self.pending_of(applicant_no)
        if app is None:
            return Decision(BLOCK, "투표할 지원이 없음")
        if self.closed:
            return Decision(BLOCK, "모집이 마감됨")
        team_no = app["team_no"]
        if voter_no not in self.teams[team_no]:
            return Decision(BLOCK, "그 팀의 팀원이 아님")
        if voter_no in self.votes[app["id"]]:
            return Decision(BLOCK, "이미 투표함")

        self.votes[app["id"]][voter_no] = choice
        result = tally_votes(self.teams[team_no], self.votes[app["id"]])

        if result == "거부":
            app["status"] = REJECT
            app["reason"] = "팀원이 거부함"
            return Decision(REJECT, "팀원이 거부함")
        if result == "찬성":
            decision = check_before_approve(
                self.students[applicant_no], self.members(team_no), closed=self.closed
            )
            app["status"] = decision.head
            app["reason"] = decision.reason
            if decision.head == OK:
                self._join(team_no, applicant_no)
            return decision
        return Decision(WAIT, "아직 투표하지 않은 팀원이 있음")

    def close(self) -> Decision:
        self.closed = True
        for app in self.apps:
            if app["status"] == WAIT:
                app["status"] = REJECT
                app["reason"] = "모집 마감"
        for team_no, members in self.teams.items():
            if len(members) == 1:
                members.clear()
        return Decision(OK, "모집을 마감함")

    def assign(self):
        teams = {no: self.members(no) for no in self.teams}
        return solve(teams, self.unassigned())

    def confirm(self, placement: dict[str, int]) -> None:
        for student_no, team_no in placement.items():
            self._join(team_no, student_no)

    def _join(self, team_no: int, student_no: str) -> None:
        if len(self.teams[team_no]) >= 4:
            raise AssertionError("정원을 넘겨 넣으려 함")
        self.teams[team_no].append(student_no)
