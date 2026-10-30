"""앱이 하는 일 (DB를 바꾸는 쪽).

규칙 판단은 전부 rules.py 에 있고, 여기서는 DB에서 읽어다 rules.py 에 묻고
그 답대로 기록만 한다. tests/sim.py 와 부르는 차례가 같다.

읽고 판단해서 쓰는 일은 모두 하나의 거래(transaction) 안에서 하고,
그 팀의 줄을 FOR UPDATE 로 잠가 같은 팀에 동시에 들어오는 요청을 한 줄로 세운다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

import bcrypt
import psycopg2
import streamlit as st

import ai_client
import db
from config import TOTAL_ASSIGN_BUDGET_SEC, get_secret, models
from roster import parse_roster
from rules import (
    BLOCK,
    OK,
    REJECT,
    WAIT,
    Decision,
    Student,
    TEAM_MAX,
    apply_placement,
    check_apply,
    check_before_approve,
    tally_votes,
    validate_assignment,
)
from solver import solve

STUDENT_PASSWORD = "1234"  # 공고 2.2절: 학생의 비밀번호는 모두 1234


# ---------------------------------------------------------------------------
# 비밀번호 (공고 3장: 해시로 저장해야 함, 6.3절 10번)
# ---------------------------------------------------------------------------


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("ascii")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("ascii"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 지금 상태 읽기
# ---------------------------------------------------------------------------


@dataclass
class AppState:
    students: dict[str, Student] = field(default_factory=dict)
    ids: dict[str, int] = field(default_factory=dict)          # 학번 -> DB id
    numbers: dict[int, str] = field(default_factory=dict)      # DB id -> 학번
    team_ids: dict[int, int] = field(default_factory=dict)     # 팀 번호 -> DB id
    team_members: dict[int, list[str]] = field(default_factory=dict)  # 팀 번호 -> 학번들
    member_team: dict[str, int] = field(default_factory=dict)  # 학번 -> 팀 번호
    pending: list[dict] = field(default_factory=list)          # 대기 중인 지원
    votes: dict[int, dict[str, str]] = field(default_factory=dict)  # 지원 id -> {학번: 투표}
    closed: bool = False
    confirmed: bool = False

    def members(self, team_no: int) -> list[Student]:
        return [self.students[no] for no in self.team_members.get(team_no, [])]

    def unassigned(self) -> list[Student]:
        return [s for no, s in self.students.items() if no not in self.member_team]

    def pending_of_team(self, team_no: int) -> list[dict]:
        return [a for a in self.pending if a["team_no"] == team_no]

    def pending_of_student(self, student_no: str) -> dict | None:
        for a in self.pending:
            if a["student_no"] == student_no:
                return a
        return None

    def teams_as_students(self) -> dict[int, list[Student]]:
        return {no: self.members(no) for no in sorted(self.team_ids)}


_LOAD_STUDENTS = """
    select s.id, s.student_no, s.name, s.main_role,
           coalesce(array_agg(r.role order by r.role) filter (where r.role is not null),
                    array[]::text[]) as sub_roles
      from tf_students s
      left join tf_student_sub_roles r on r.student_id = s.id
     where s.is_admin = false
     group by s.id
     order by s.student_no
"""


def _read_students(cur) -> tuple[dict[str, Student], dict[str, int], dict[int, str]]:
    cur.execute(_LOAD_STUDENTS)
    students: dict[str, Student] = {}
    ids: dict[str, int] = {}
    numbers: dict[int, str] = {}
    for row in cur.fetchall():
        no = row["student_no"]
        students[no] = Student(no, row["name"], row["main_role"], tuple(row["sub_roles"] or ()))
        ids[no] = row["id"]
        numbers[row["id"]] = no
    return students, ids, numbers


def _read_state(cur) -> AppState:
    state = AppState()
    state.students, state.ids, state.numbers = _read_students(cur)

    cur.execute("select id, team_no from tf_teams order by team_no")
    for row in cur.fetchall():
        state.team_ids[row["team_no"]] = row["id"]
        state.team_members[row["team_no"]] = []
    team_no_by_id = {v: k for k, v in state.team_ids.items()}

    cur.execute("select team_id, slot_no, student_id from tf_members order by team_id, slot_no")
    for row in cur.fetchall():
        team_no = team_no_by_id.get(row["team_id"])
        student_no = state.numbers.get(row["student_id"])
        if team_no is None or student_no is None:
            continue
        state.team_members[team_no].append(student_no)
        state.member_team[student_no] = team_no

    cur.execute(
        "select id, team_id, student_id, created_at from tf_applications"
        " where status = %s order by created_at, id",
        (WAIT,),
    )
    for row in cur.fetchall():
        team_no = team_no_by_id.get(row["team_id"])
        student_no = state.numbers.get(row["student_id"])
        if team_no is None or student_no is None:
            continue
        state.pending.append(
            {"id": row["id"], "team_no": team_no, "student_no": student_no,
             "created_at": row["created_at"]}
        )

    if state.pending:
        ids = tuple(a["id"] for a in state.pending)
        cur.execute(
            "select application_id, voter_id, vote from tf_votes where application_id in %s",
            (ids,),
        )
        for row in cur.fetchall():
            voter_no = state.numbers.get(row["voter_id"])
            if voter_no is None:
                continue
            state.votes.setdefault(row["application_id"], {})[voter_no] = row["vote"]

    cur.execute("select key, value from tf_settings")
    settings = {row["key"]: row["value"] for row in cur.fetchall()}
    state.closed = settings.get("closed") == "true"
    state.confirmed = settings.get("assignment_confirmed") == "true"
    return state


def load_state() -> AppState:
    with db.transaction() as cur:
        return _read_state(cur)


def _setting(cur, key: str, value: str) -> None:
    cur.execute(
        "insert into tf_settings (key, value, updated_at) values (%s, %s, now())"
        " on conflict (key) do update set value = excluded.value, updated_at = now()",
        (key, value),
    )


def _is_closed(cur) -> bool:
    cur.execute("select value from tf_settings where key = %s", ("closed",))
    row = cur.fetchone()
    return bool(row and row["value"] == "true")


def _lock_team(cur, team_no: int) -> int | None:
    """그 팀의 줄을 잠가 같은 팀에 동시에 오는 요청을 한 줄로 세운다."""
    cur.execute("select id from tf_teams where team_no = %s for update", (team_no,))
    row = cur.fetchone()
    return row["id"] if row else None


def _team_members(cur, team_id: int, students: dict[str, Student], numbers: dict[int, str]) -> list[Student]:
    cur.execute("select student_id from tf_members where team_id = %s order by slot_no", (team_id,))
    out = []
    for row in cur.fetchall():
        no = numbers.get(row["student_id"])
        if no in students:
            out.append(students[no])
    return out


def _next_slot(cur, team_id: int) -> int | None:
    cur.execute("select slot_no from tf_members where team_id = %s", (team_id,))
    used = {row["slot_no"] for row in cur.fetchall()}
    for slot in range(1, TEAM_MAX + 1):
        if slot not in used:
            return slot
    return None


def _join_team(cur, team_id: int, student_id: int) -> bool:
    """팀에 넣는다. 유일성 제약에 걸리면 False.

    PostgreSQL 은 거래 안에서 문장 하나가 실패하면 그 거래 전체를 못 쓰게 만든다.
    그래서 저장점(savepoint)을 찍어 두고, 제약에 걸리면 저장점까지만 되돌린다.
    그래야 바로 뒤에서 지원을 '거절'로 바꾸는 문장이 이어서 돌아간다.
    """
    slot = _next_slot(cur, team_id)
    if slot is None:
        return False
    cur.execute("savepoint tf_join")
    try:
        cur.execute(
            "insert into tf_members (team_id, slot_no, student_id) values (%s, %s, %s)",
            (team_id, slot, student_id),
        )
    except psycopg2.Error:
        # (team_id, slot_no) 나 student_id 의 유일성 제약에 걸린 것.
        # 먼저 도착한 학생만 기록된다 (공고 3장).
        cur.execute("rollback to savepoint tf_join")
        return False
    cur.execute("release savepoint tf_join")
    return True


# ---------------------------------------------------------------------------
# 로그인
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner=False)
def ensure_admin() -> bool:
    """앱이 시작할 때 비밀 값 ADMIN_PASSWORD 로 관리자 계정을 만들거나 갱신한다 (공고 2.1절)."""
    db.init_schema()
    password = get_secret("ADMIN_PASSWORD")
    if not password:
        return False
    with db.transaction() as cur:
        cur.execute(
            "insert into tf_students (student_no, name, main_role, password_hash, is_admin)"
            " values (%s, %s, null, %s, true)"
            " on conflict (student_no) do update"
            " set password_hash = excluded.password_hash, is_admin = true, name = excluded.name",
            ("admin", "관리자", hash_password(password)),
        )
    return True


def login(student_no: str, password: str) -> dict | None:
    """학번과 비밀번호로 로그인. 비밀번호가 틀리면 절대 들여보내지 않는다 (공고 6.3절 12번)."""
    student_no = (student_no or "").strip()
    if not student_no or not password:
        return None
    row = db.query_one(
        "select id, student_no, name, main_role, password_hash, is_admin"
        " from tf_students where student_no = %s",
        (student_no,),
    )
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return {
        "id": row["id"],
        "student_no": row["student_no"],
        "name": row["name"],
        "main_role": row["main_role"],
        "is_admin": bool(row["is_admin"]),
    }


# ---------------------------------------------------------------------------
# 관리자: 명단 올리기 (공고 2.6절)
# ---------------------------------------------------------------------------


def upload_roster(data: bytes, team_count: int) -> Decision:
    """명단 CSV 와 팀 수로 앱 상태를 처음부터 다시 만든다.

    지원, 투표, 팀원, 마감 표시를 모두 지우고 명단의 학생과 빈 팀을 만든다.
    관리자 계정은 남긴다.
    """
    students = parse_roster(data)
    team_count = int(team_count)
    if team_count < 1:
        return Decision(BLOCK, "팀 수는 1 이상이어야 함")
    if len(students) > team_count * TEAM_MAX:
        return Decision(
            BLOCK,
            f"학생 {len(students)}명을 팀 {team_count}개(최대 {team_count * TEAM_MAX}명)에 넣을 수 없음",
        )

    # 모두 같은 비밀번호(1234)라서 해시는 한 번만 만들어 쓴다. 명단 올리기가 느려지지 않게 하려는 것.
    student_hash = hash_password(STUDENT_PASSWORD)

    with db.transaction() as cur:
        cur.execute("delete from tf_votes")
        cur.execute("delete from tf_applications")
        cur.execute("delete from tf_members")
        cur.execute("delete from tf_student_sub_roles")
        cur.execute("delete from tf_teams")
        cur.execute("delete from tf_students where is_admin = false")
        cur.execute("delete from tf_settings")
        cur.execute("delete from tf_ai_logs")

        for s in students:
            cur.execute(
                "insert into tf_students (student_no, name, main_role, password_hash, is_admin)"
                " values (%s, %s, %s, %s, false) returning id",
                (s.student_no, s.name, s.main_role, student_hash),
            )
            student_id = cur.fetchone()["id"]
            for role in s.sub_roles:
                cur.execute(
                    "insert into tf_student_sub_roles (student_id, role) values (%s, %s)"
                    " on conflict do nothing",
                    (student_id, role),
                )

        for team_no in range(1, team_count + 1):
            cur.execute(
                "insert into tf_teams (team_no, name) values (%s, %s)",
                (team_no, f"팀{team_no}"),
            )
        _setting(cur, "closed", "false")
        _setting(cur, "assignment_confirmed", "false")

    return Decision(OK, f"학생 {len(students)}명과 팀 {team_count}개로 처음 상태를 만듦")


# ---------------------------------------------------------------------------
# 학생: 지원 (공고 2.4절)
# ---------------------------------------------------------------------------


def apply_to_team(student_no: str, team_no: int) -> Decision:
    with db.transaction() as cur:
        team_id = _lock_team(cur, team_no)
        if team_id is None:
            return Decision(BLOCK, f"팀{team_no}이 없음")

        students, ids, numbers = _read_students(cur)
        student = students.get(student_no)
        if student is None:
            return Decision(BLOCK, "명단에 없는 학생")

        closed = _is_closed(cur)
        cur.execute("select 1 from tf_members where student_id = %s", (ids[student_no],))
        has_team = cur.fetchone() is not None
        cur.execute(
            "select 1 from tf_applications where student_id = %s and status = %s",
            (ids[student_no], WAIT),
        )
        has_pending = cur.fetchone() is not None
        members = _team_members(cur, team_id, students, numbers)

        decision = check_apply(
            student, members, closed=closed, has_team=has_team, has_pending=has_pending
        )
        if decision.head == BLOCK:
            # 막힌 지원은 접수하지 않으므로 DB에 기록하지 않는다 (공고 2.4절)
            return decision

        # 대기 중인 지원은 아직 결과가 안 났으므로 decided_at 을 비워 둔다
        decided = None if decision.head == WAIT else "now"
        cur.execute(
            "insert into tf_applications (team_id, student_id, status, reason, decided_at)"
            " values (%s, %s, %s, %s, case when %s is null then null else now() end) returning id",
            (team_id, ids[student_no], decision.head, decision.reason, decided),
        )
        app_id = cur.fetchone()["id"]

        if decision.head == OK:  # 빈 팀이라 바로 승인
            if not _join_team(cur, team_id, ids[student_no]):
                cur.execute(
                    "update tf_applications set status = %s, reason = %s, decided_at = now()"
                    " where id = %s",
                    (REJECT, "마지막 자리에 다른 학생이 먼저 들어감", app_id),
                )
                return Decision(REJECT, "마지막 자리에 다른 학생이 먼저 들어감")
        return decision


# ---------------------------------------------------------------------------
# 학생: 투표 (공고 2.4절)
# ---------------------------------------------------------------------------


def cast_vote(voter_no: str, applicant_no: str, choice: str) -> Decision:
    with db.transaction() as cur:
        students, ids, numbers = _read_students(cur)
        if voter_no not in ids or applicant_no not in ids:
            return Decision(BLOCK, "명단에 없는 학생")

        cur.execute(
            "select a.id, a.team_id, t.team_no from tf_applications a"
            " join tf_teams t on t.id = a.team_id"
            " where a.student_id = %s and a.status = %s",
            (ids[applicant_no], WAIT),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "select status, reason from tf_applications where student_id = %s"
                " order by id desc limit 1",
                (ids[applicant_no],),
            )
            last = cur.fetchone()
            if last:
                return Decision(last["status"], last["reason"] or "이미 결과가 나온 지원")
            return Decision(BLOCK, "투표할 지원이 없음")

        app_id, team_id, team_no = row["id"], row["team_id"], row["team_no"]
        _lock_team(cur, team_no)

        if _is_closed(cur):
            return Decision(BLOCK, "모집이 마감됨")

        members = _team_members(cur, team_id, students, numbers)
        member_nos = [m.student_no for m in members]
        if voter_no not in member_nos:
            return Decision(BLOCK, "그 팀의 팀원이 아님")

        # 한 번 투표하면 바꿀 수 없다 (공고 2.4절). 기본 키가 있어 DB에서도 막힌다.
        cur.execute(
            "insert into tf_votes (application_id, voter_id, vote) values (%s, %s, %s)"
            " on conflict (application_id, voter_id) do nothing",
            (app_id, ids[voter_no], choice),
        )
        if cur.rowcount == 0:
            return Decision(BLOCK, "이미 투표함")

        cur.execute("select voter_id, vote from tf_votes where application_id = %s", (app_id,))
        votes = {numbers[r["voter_id"]]: r["vote"] for r in cur.fetchall() if r["voter_id"] in numbers}

        result = tally_votes(member_nos, votes)
        if result == "거부":
            cur.execute(
                "update tf_applications set status = %s, reason = %s, decided_at = now() where id = %s",
                (REJECT, "팀원이 거부함", app_id),
            )
            return Decision(REJECT, "팀원이 거부함")

        if result == "찬성":
            # 승인 직전 재검사 (공고 2.4절, 3장의 어려운 해결)
            decision = check_before_approve(students[applicant_no], members, closed=False)
            if decision.head != OK:
                cur.execute(
                    "update tf_applications set status = %s, reason = %s, decided_at = now()"
                    " where id = %s",
                    (REJECT, decision.reason, app_id),
                )
                return decision
            if not _join_team(cur, team_id, ids[applicant_no]):
                cur.execute(
                    "update tf_applications set status = %s, reason = %s, decided_at = now()"
                    " where id = %s",
                    (REJECT, "마지막 자리에 다른 학생이 먼저 들어감", app_id),
                )
                return Decision(REJECT, "마지막 자리에 다른 학생이 먼저 들어감")
            cur.execute(
                "update tf_applications set status = %s, reason = %s, decided_at = now() where id = %s",
                (OK, decision.reason, app_id),
            )
            return decision

        return Decision(WAIT, "아직 투표하지 않은 팀원이 있음")


# ---------------------------------------------------------------------------
# 관리자: 마감 (공고 2.5절 1~2항)
# ---------------------------------------------------------------------------


def close_recruiting() -> Decision:
    with db.transaction() as cur:
        cur.execute("select 1 from tf_teams limit 1")
        if cur.fetchone() is None:
            return Decision(BLOCK, "먼저 명단을 올려야 함")
        if _is_closed(cur):
            return Decision(BLOCK, "이미 마감됨")

        _setting(cur, "closed", "true")
        # 마감 때 대기 중인 지원은 거절
        cur.execute(
            "update tf_applications set status = %s, reason = %s, decided_at = now()"
            " where status = %s",
            (REJECT, "모집 마감", WAIT),
        )
        rejected = cur.rowcount
        # 1명뿐인 팀의 학생은 팀에서 빠져 "팀이 없는 학생"이 됨
        cur.execute(
            "delete from tf_members m using ("
            "  select team_id from tf_members group by team_id having count(*) = 1"
            ") one where m.team_id = one.team_id"
        )
        removed = cur.rowcount
    return Decision(OK, f"모집을 마감함 (대기 지원 {rejected}건 거절, 1명뿐인 팀에서 {removed}명 빠짐)")


# ---------------------------------------------------------------------------
# 관리자: AI 배정 (공고 2.5절 3~8항)
# ---------------------------------------------------------------------------


@dataclass
class AssignResult:
    ok: bool
    placement: dict[str, int] | None
    source: str          # "AI" / "앱" / "없음"
    attempts: list       # ai_client.Attempt
    reasons: list[str]
    state: AppState


def run_assignment(on_progress: Callable[[str], None] | None = None) -> AssignResult:
    """배정안을 만든다. AI -> (실패하면) 앱이 스스로 차례.

    먼저 앱이 스스로 규칙을 지키는 배정이 있는지 끝까지 따져 본다.
    아예 없으면 AI 를 부르지 않고 그 사실과 이유를 알린다 (공고 2.5절 8항).
    있으면 그 답을 손에 쥔 채로 AI 에게 물어보고, AI 가 3차까지 실패하면 그것을 쓴다.
    """
    def say(message: str) -> None:
        if on_progress:
            on_progress(message)

    state = load_state()
    if not state.team_ids:
        return AssignResult(False, None, "없음", [], ["먼저 명단을 올려야 함"], state)
    if not state.closed:
        return AssignResult(False, None, "없음", [], ["먼저 모집을 마감해야 함"], state)

    teams = state.teams_as_students()
    unassigned = state.unassigned()

    say("규칙을 지키는 배정이 있는지 먼저 따져 보는 중...")
    own = solve(teams, unassigned)
    if not own.ok:
        # 공고 2.5절 8항: 배정안을 만들지 않고 이유를 보여 준다. AI 는 부르지 않는다.
        return AssignResult(False, None, "없음", [], own.reasons, state)

    if not unassigned:
        return AssignResult(True, {}, "앱", [], ["팀이 없는 학생이 없어 그대로 둠"], state)

    def validate(placement: dict[str, int]) -> list[str]:
        return validate_assignment(apply_placement(teams, unassigned, placement), unassigned, placement)

    prompt = ai_client.build_prompt(teams, unassigned)
    valid_team_nos = set(teams)
    model_names = models()
    deadline = time.monotonic() + TOTAL_ASSIGN_BUDGET_SEC

    ordinal = {1: "1차", 2: "2차", 3: "3차"}

    def progress(attempt_no: int, model: str, status: str) -> None:
        # 공고 3장 "AI 대기 중 화면"의 어려운 해결: 몇 차 모델을 기다리는 중인지 보여 준다
        if status == "요청 중":
            say(f"{ordinal.get(attempt_no, attempt_no)} 모델 `{model}` 의 응답을 기다리는 중... (최대 120초)")
        else:
            say(f"{ordinal.get(attempt_no, attempt_no)} 모델 `{model}` -> {status}")

    placement, attempts = ai_client.ask_models(
        model_names, prompt, valid_team_nos,
        validate=validate, on_progress=progress, deadline=deadline,
    )
    _log_attempts(attempts)

    if placement is not None:
        return AssignResult(True, placement, "AI", attempts, [], state)

    # 3차 모델까지 실패 -> 앱이 스스로 찾아 둔 배정을 쓴다 (공고 3장의 어려운 해결)
    say("3차 모델까지 실패하여 앱이 스스로 찾은 배정을 씁니다.")
    return AssignResult(True, own.placement, "앱", attempts, [], state)


def _log_attempts(attempts: Sequence) -> None:
    if not attempts:
        return
    try:
        with db.transaction() as cur:
            for a in attempts:
                cur.execute(
                    "insert into tf_ai_logs (attempt_no, model, status, elapsed_ms, message)"
                    " values (%s, %s, %s, %s, %s)",
                    (a.attempt_no, a.model, a.status, a.elapsed_ms, a.message),
                )
    except Exception:
        pass  # 기록에 실패해도 배정은 계속한다


def recent_ai_logs(limit: int = 20) -> list[dict]:
    try:
        return db.query(
            "select attempt_no, model, status, elapsed_ms, message, created_at"
            " from tf_ai_logs order by created_at desc, id desc limit %s",
            (limit,),
        )
    except Exception:
        return []


class ConfirmRefused(Exception):
    """확정할 수 없는 경우. 거래 전체를 되돌리려고 예외로 올린다."""


def confirm_assignment(placement: dict[str, int]) -> Decision:
    """관리자가 확정하면 DB에 저장한다 (공고 2.5절 7항).

    중간에 하나라도 어긋나면 예외를 올려 거래 전체를 되돌린다.
    그냥 return 하면 그때까지 넣은 팀원이 그대로 저장되어 반쪽짜리 구성이 남는다.
    """
    try:
        with db.transaction() as cur:
            if not _is_closed(cur):
                raise ConfirmRefused("먼저 모집을 마감해야 함")

            state_before = _read_state(cur)
            # 넣기 전에 먼저 검사한다 (공고 2.5절 4항)
            errors = validate_assignment(
                apply_placement(
                    state_before.teams_as_students(), state_before.unassigned(), placement
                ),
                state_before.unassigned(),
                placement,
            )
            if errors:
                raise ConfirmRefused("배정안이 규칙을 어김: " + "; ".join(errors))

            cur.execute("select id, team_no from tf_teams order by team_no")
            team_ids = {row["team_no"]: row["id"] for row in cur.fetchall()}

            placed = 0
            for student_no, team_no in placement.items():
                if student_no not in state_before.ids or team_no not in team_ids:
                    raise ConfirmRefused(f"배정안이 올바르지 않음: {student_no} -> 팀{team_no}")
                if not _join_team(cur, team_ids[team_no], state_before.ids[student_no]):
                    name = state_before.students[student_no].name
                    raise ConfirmRefused(f"{name}을(를) 팀{team_no}에 넣지 못함")
                placed += 1

            # 넣고 난 뒤 DB에서 다시 읽어 한 번 더 확인한다
            after = validate_assignment(_read_state(cur).teams_as_students(), [], {})
            if after:
                raise ConfirmRefused("확정한 구성이 규칙을 어김: " + "; ".join(after))

            _setting(cur, "assignment_confirmed", "true")
    except ConfirmRefused as exc:
        return Decision(BLOCK, str(exc))
    return Decision(OK, f"배정을 확정함 ({placed}명 배정)")
