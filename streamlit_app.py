"""팀 편성 웹 앱 (중간 과제).

화면 요소의 Streamlit key 는 공고 2.7절 "화면 이름 표"와 똑같이 지정했다.
자동 채점 프로그램이 이 key 로 요소를 찾으므로 고치면 안 된다.

  login_student_no / login_password / login_submit
  whoami / result
  team_1, team_2, ... / apply_1, apply_2, ...
  vote_yes_{지원자 학번} / vote_no_{지원자 학번}
  admin_roster_file / admin_team_count / admin_start / admin_close
  unassigned / admin_assign / assign_status / admin_confirm
  refresh

로그인 단추는 st.form_submit_button 이 아니라 st.button 으로 만들었다.
공고 2.7절 표에는 둘 다 쓸 수 있다고 적혀 있고, 어느 쪽이든 key 를 붙일 수 있다.
st.button 을 고른 이유는 비밀번호 칸의 on_change 로도 로그인을 끝낼 수 있어,
글자를 넣자마자 단추를 누른 클릭이 묻히는 일을 막기 쉬웠기 때문이다.
(처음에는 "st.form_submit_button 에는 key 가 없다"고 알고 썼으나 사실이 아니었다.
 공식 문서 확인 결과 key 매개변수가 있다. 자세한 경위는 README.md 6항에 적었다.)
"""

from __future__ import annotations

import streamlit as st

import actions
import db
from config import secret_status
from roster import RosterError
from rules import BLOCK, OK, Decision, Student

st.set_page_config(page_title="팀 편성", page_icon="🧩", layout="wide")

# 다른 사람의 변경 보기(공고 3장): 어려운 해결 — st.fragment 로 3초마다 바뀐 부분만 다시 그린다.
# 공고 2.7절이 요구하는 "5초 이하"를 지킨다.
REFRESH_SECONDS = 3


# ---------------------------------------------------------------------------
# result 안내 (공고 2.7절: "승인", "대기", "거절", "막힘" 가운데 하나로 시작)
# ---------------------------------------------------------------------------


def set_result(decision: Decision | str) -> None:
    st.session_state["result_text"] = decision if isinstance(decision, str) else decision.text


def render_result() -> None:
    with st.container(key="result", border=True):
        text = st.session_state.get("result_text", "")
        if not text:
            st.write("단추를 누르면 결과가 여기에 보입니다.")
        elif text.startswith(OK):
            st.success(text)
        elif text.startswith(BLOCK) or text.startswith("거절"):
            st.error(text)
        else:
            st.info(text)


# ---------------------------------------------------------------------------
# 로그인
# ---------------------------------------------------------------------------


def _attempt_login() -> bool:
    """학번과 비밀번호로 로그인을 시도한다. 둘 다 채워져 있을 때만 움직인다."""
    student_no = (st.session_state.get("login_student_no") or "").strip()
    password = st.session_state.get("login_password") or ""
    if not student_no or not password:
        return False
    user = actions.login(student_no, password)
    if user is None:
        set_result(Decision(BLOCK, "학번 또는 비밀번호가 맞지 않음"))
        return False
    st.session_state["user"] = user
    set_result(Decision(OK, f"{user['name']}(으)로 로그인함"))
    return True


def _login_on_change() -> None:
    """비밀번호 칸에서 Enter 를 누르거나 칸을 벗어날 때도 로그인되게 한다.

    폼을 쓰지 않으므로, 글자를 넣자마자 단추를 누르면 그 클릭이 다시 그리는 사이에
    묻힐 수 있다. 이 콜백이 먼저 로그인을 끝내 주어 그런 일을 막는다.
    """
    if "user" not in st.session_state:
        _attempt_login()


def login_view() -> None:
    st.title("팀 편성")
    st.caption("학번과 비밀번호로 로그인하세요. 관리자는 학번 admin 으로 로그인합니다.")

    st.text_input("학번", key="login_student_no", on_change=_login_on_change)
    st.text_input("비밀번호", type="password", key="login_password", on_change=_login_on_change)
    if st.button("로그인", key="login_submit", type="primary"):
        _attempt_login()
        st.rerun()

    render_result()


# ---------------------------------------------------------------------------
# 관리자 화면
# ---------------------------------------------------------------------------


def admin_view() -> None:
    st.subheader("관리자")

    with st.container(border=True):
        st.markdown("**1. 명단 올리기** — 명단 CSV 와 팀 수를 넣으면 앱 상태가 처음부터 다시 만들어집니다.")
        uploaded = st.file_uploader("명단 CSV", type=["csv"], key="admin_roster_file")
        st.number_input("팀 수", min_value=1, max_value=12, value=4, step=1, key="admin_team_count")
        if st.button("명단으로 처음 상태 만들기", key="admin_start", type="primary"):
            if uploaded is None:
                set_result(Decision(BLOCK, "명단 CSV 파일을 먼저 고르세요"))
            else:
                try:
                    set_result(
                        actions.upload_roster(
                            uploaded.getvalue(), st.session_state.get("admin_team_count", 4)
                        )
                    )
                except RosterError as exc:
                    set_result(Decision(BLOCK, str(exc)))
                except Exception as exc:
                    set_result(Decision(BLOCK, f"명단을 올리지 못함: {exc}"))
            st.session_state.pop("proposal", None)
            st.session_state.pop("assign_log", None)
            st.rerun()

    with st.container(border=True):
        st.markdown("**2. 모집 마감** — 마감하면 지원과 투표를 할 수 없습니다.")
        if st.button("모집 마감", key="admin_close"):
            try:
                set_result(actions.close_recruiting())
            except Exception as exc:
                set_result(Decision(BLOCK, f"마감하지 못함: {exc}"))
            st.rerun()

    with st.container(border=True):
        st.markdown("**3. AI 배정** — 팀이 없는 학생을 AI 가 배정하고, 앱이 규칙으로 검사합니다.")
        assign_clicked = st.button("AI 배정", key="admin_assign")

        # 단추를 누르기 전에 미리 만들어 두어야, 기다리는 동안 이 자리에 진행 상황을 적을 수 있다.
        status_box = st.container(key="assign_status", border=True)
        status_slot = status_box.empty()

        if assign_clicked:
            _run_assignment(status_slot)
            return

        stored = st.session_state.get("assign_log") or []
        status_slot.markdown(
            "\n".join(f"- {line}" for line in stored) if stored else "아직 배정을 하지 않았습니다."
        )
        render_proposal()

    with st.expander("비밀 값과 AI 호출 기록"):
        st.caption("값은 보여 주지 않고 있는지 없는지만 표시합니다 (공고 4.1절, 6.3절 8번).")
        for name, present in secret_status().items():
            st.write(f"- {name}: {'있음' if present else '없음'}")
        logs = actions.recent_ai_logs(12)
        if logs:
            st.caption("최근 AI 호출 (README 7.1절 5항의 실패 사례 증거로 쓰세요)")
            st.dataframe(logs)


def _run_assignment(status_slot) -> None:
    lines: list[str] = []

    def on_progress(message: str) -> None:
        lines.append(message)
        # 기다리는 동안에도 이 자리가 바로바로 바뀐다 (공고 3장 "AI 대기 중 화면"의 어려운 해결)
        status_slot.markdown("\n".join(f"- {line}" for line in lines))

    try:
        result = actions.run_assignment(on_progress)
    except Exception as exc:
        lines.append(f"오류: {exc}")
        st.session_state["assign_log"] = lines
        set_result(Decision(BLOCK, f"배정을 하지 못함: {exc}"))
        st.rerun()
        return

    if not result.ok:
        # 공고 2.5절 8항: 규칙을 지키는 배정이 없음 + 그 이유를 assign_status 안에 보여 준다
        lines.append("**규칙을 지키는 배정이 없음**")
        lines.extend(f"이유: {reason}" for reason in result.reasons)
        st.session_state["assign_log"] = lines
        st.session_state.pop("proposal", None)
        set_result(Decision(BLOCK, "규칙을 지키는 배정이 없음"))
    else:
        where = "AI 가 낸 배정안" if result.source == "AI" else "앱이 스스로 찾은 배정"
        lines.append(f"**검사를 통과한 {where}을 아래에 보여 줍니다.**")
        st.session_state["assign_log"] = lines
        st.session_state["proposal"] = result.placement
        st.session_state["board"] = result.state
        set_result(Decision(OK, f"배정안을 만듦 ({where})"))
    st.rerun()


def render_proposal() -> None:
    """검사를 통과한 배정안만 관리자에게 보여 준다 (공고 2.5절 7항)."""
    proposal = st.session_state.get("proposal")
    state = st.session_state.get("board")
    if state is None:
        try:
            state = actions.load_state()
            st.session_state["board"] = state
        except Exception:
            state = None

    if proposal and state is not None:
        rows = []
        for student_no, team_no in sorted(proposal.items(), key=lambda kv: (kv[1], kv[0])):
            student = state.students.get(student_no)
            if student is None:
                continue
            rows.append(
                {
                    "학번": student_no,
                    "이름": student.name,
                    "주 역할": student.main_role,
                    "보조 역할": ", ".join(student.sub_roles) or "없음",
                    "배정된 팀": f"팀{team_no}",
                }
            )
        if rows:
            st.markdown("**확정하기 전 배정안**")
            st.dataframe(rows, hide_index=True)

    if st.button("배정안 확정", key="admin_confirm", type="primary"):
        if proposal is None:
            set_result(Decision(BLOCK, "확정할 배정안이 없음"))
        else:
            try:
                set_result(actions.confirm_assignment(proposal))
                st.session_state.pop("proposal", None)
            except Exception as exc:
                set_result(Decision(BLOCK, f"확정하지 못함: {exc}"))
        st.rerun()


# ---------------------------------------------------------------------------
# 팀 목록 (학생과 관리자 모두 봄)
# ---------------------------------------------------------------------------


def member_line(student: Student) -> str:
    subs = ", ".join(student.sub_roles) if student.sub_roles else "없음"
    return f"- **{student.name}** · 주 역할 {student.main_role} · 보조 역할 {subs}"


def render_board() -> None:
    user = st.session_state["user"]
    is_admin = user["is_admin"]
    me = user["student_no"]

    try:
        state = actions.load_state()
    except Exception as exc:
        st.error(f"DB 를 읽지 못했습니다: {exc}")
        return
    st.session_state["board"] = state

    if not state.team_ids:
        st.info("아직 명단이 올라오지 않았습니다. 관리자가 명단 CSV 를 올리면 팀이 보입니다.")
        with st.container(key="unassigned", border=True):
            st.write("팀이 없는 학생: 없음")
        return

    my_team = state.member_team.get(me)
    if not is_admin:
        if my_team:
            st.success(f"내 팀: 팀{my_team}")
        else:
            st.warning("아직 팀이 없음")
        if state.closed:
            st.caption("모집이 마감되었습니다. 더 이상 지원과 투표를 할 수 없습니다.")

    my_pending = state.pending_of_student(me)
    # 공고 2.8절: 이미 팀에 속했거나, 결과를 기다리는 지원이 있거나, 마감되었으면
    #            지원 단추를 숨기거나 비활성화해야 함
    cannot_apply = is_admin or state.closed or my_team is not None or my_pending is not None

    columns = st.columns(min(len(state.team_ids), 4))
    for index, team_no in enumerate(sorted(state.team_ids)):
        with columns[index % len(columns)]:
            with st.container(key=f"team_{team_no}", border=True):
                mine = " — 내 팀" if my_team == team_no else ""
                members = state.members(team_no)
                st.markdown(f"#### 팀{team_no} ({len(members)}/4){mine}")

                if members:
                    for student in members:
                        st.markdown(member_line(student))
                else:
                    st.caption("아직 팀원이 없음")

                for application in state.pending_of_team(team_no):
                    render_application(state, application, team_no, me)

                if st.button(f"팀{team_no}에 지원", key=f"apply_{team_no}", disabled=cannot_apply):
                    try:
                        set_result(actions.apply_to_team(me, team_no))
                    except Exception as exc:
                        set_result(Decision(BLOCK, f"지원하지 못함: {exc}"))
                    st.rerun(scope="app")  # 화면 전체를 다시 그려 result 안내까지 바뀌게 한다

    render_unassigned(state)


def render_application(state, application: dict, team_no: int, me: str) -> None:
    applicant_no = application["student_no"]
    applicant = state.students.get(applicant_no)
    if applicant is None:
        return

    st.divider()
    subs = ", ".join(applicant.sub_roles) if applicant.sub_roles else "없음"
    st.markdown(f"지원 중: **{applicant.name}** · 주 {applicant.main_role} · 보조 {subs}")

    votes = state.votes.get(application["id"], {})
    members = state.team_members.get(team_no, [])
    waiting = [state.students[n].name for n in members if n not in votes]
    st.caption(
        f"찬성 {sum(1 for v in votes.values() if v == '찬성')}명 / "
        f"거부 {sum(1 for v in votes.values() if v == '거부')}명"
        + (f" / 아직 투표 안 한 팀원: {', '.join(waiting)}" if waiting else "")
    )

    # 투표는 그 팀의 팀원만 한다. 투표할 사람은 투표하는 때의 팀원이다 (공고 2.4절).
    if me not in members:
        return

    my_vote = votes.get(me)
    blocked = my_vote is not None or state.closed
    left, right = st.columns(2)
    yes = left.button("찬성", key=f"vote_yes_{applicant_no}", disabled=blocked)
    no = right.button("거부", key=f"vote_no_{applicant_no}", disabled=blocked)
    if my_vote:
        # 공고 2.8절: 이미 투표했으면 단추를 비활성화하고 내 투표를 보여 준다
        st.caption(f"내 투표: {my_vote}")

    if yes or no:
        try:
            set_result(actions.cast_vote(me, applicant_no, "찬성" if yes else "거부"))
        except Exception as exc:
            set_result(Decision(BLOCK, f"투표하지 못함: {exc}"))
        st.rerun(scope="app")  # 조각만이 아니라 화면 전체를 다시 그린다


def render_unassigned(state) -> None:
    with st.container(key="unassigned", border=True):
        left_out = state.unassigned()
        if left_out:
            st.markdown(f"**팀이 없는 학생 ({len(left_out)}명)**")
            for student in left_out:
                st.markdown(member_line(student))
        else:
            st.write("팀이 없는 학생: 없음")


# 바뀐 부분만 3초마다 다시 그린다. 다른 학생의 지원이나 투표가 저절로 나타난다.
@st.fragment(run_every=REFRESH_SECONDS)
def live_board() -> None:
    render_board()


# ---------------------------------------------------------------------------
# 들어가는 곳
# ---------------------------------------------------------------------------


def main() -> None:
    if not secret_status()["DATABASE_URL"]:
        st.error(
            "DATABASE_URL 이 없습니다. 내 컴퓨터에서는 .env 파일에, "
            "배포한 앱에서는 Streamlit Secrets 에 넣어 주세요."
        )
        st.stop()

    try:
        db.init_schema()
        actions.ensure_admin()
    except Exception as exc:
        st.error(f"DB 에 연결하지 못했습니다: {exc}")
        st.stop()

    if "user" not in st.session_state:
        login_view()
        return

    user = st.session_state["user"]
    with st.container(key="whoami", border=True):
        role = "관리자" if user["is_admin"] else f"학생 · 주 역할 {user['main_role']}"
        st.markdown(f"**{user['name']}** ({user['student_no']}) · {role}")

    render_result()

    left, right, _ = st.columns([1, 1, 5])
    # 자동 갱신이 멈추더라도 채점이 막히지 않도록 새로 고침 단추를 함께 둔다.
    if left.button("새로 고침", key="refresh"):
        st.rerun()
    if right.button("로그아웃", key="logout"):
        for key in ("user", "proposal", "assign_log", "board", "result_text"):
            st.session_state.pop(key, None)
        st.rerun()

    if user["is_admin"]:
        admin_view()

    live_board()


main()
