"""부록 1~3 연습용 시나리오를 그대로 돌려 기대 결과와 맞는지 본다.

    python3 tests/test_scenarios.py

DB도 Streamlit도 없이 돌아간다. 규칙을 고친 뒤에는 반드시 이것을 먼저 돌린다.
채점 시나리오는 공개되지 않지만, 규칙은 공고에 적힌 그대로이므로
이 세 가지를 통과하면 규칙 자체는 맞게 만든 것이다.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from roster import parse_roster  # noqa: E402
from rules import validate_assignment  # noqa: E402
from sim import Sim  # noqa: E402

# 각 줄: (단계, 동작, 기대하는 result 첫 단어)
#   ("apply", 학번, 팀번호) / ("vote", 투표자, 지원자, "찬성"|"거부")

EASY = [
    (1, ("apply", "2026101", 1), "승인"),
    (1, ("apply", "2026102", 2), "승인"),
    (1, ("apply", "2026103", 3), "승인"),
    (2, ("apply", "2026104", 1), "대기"),
    (2, ("vote", "2026101", "2026104", "찬성"), "승인"),
    (3, ("apply", "2026105", 2), "대기"),
    (3, ("vote", "2026102", "2026105", "찬성"), "승인"),
    (4, ("apply", "2026107", 1), "대기"),
    (4, ("vote", "2026101", "2026107", "찬성"), "대기"),
    (4, ("vote", "2026104", "2026107", "거부"), "거절"),
    (5, ("apply", "2026106", 3), "대기"),
    (5, ("vote", "2026103", "2026106", "찬성"), "승인"),
    (6, ("close",), "승인"),
]

MID = [
    (1, ("apply", "2026201", 1), "승인"),
    (2, ("apply", "2026205", 1), "대기"),
    (2, ("vote", "2026201", "2026205", "찬성"), "승인"),
    (3, ("apply", "2026202", 1), "막힘"),  # 주 역할 중복
    (4, ("apply", "2026206", 2), "승인"),
    (5, ("apply", "2026209", 2), "대기"),
    (5, ("vote", "2026206", "2026209", "찬성"), "승인"),
    (6, ("apply", "2026210", 2), "대기"),
    (6, ("vote", "2026206", "2026210", "찬성"), "대기"),
    (6, ("vote", "2026209", "2026210", "거부"), "거절"),
    (7, ("apply", "2026203", 3), "승인"),
    (7, ("apply", "2026211", 4), "승인"),
    (8, ("apply", "2026212", 4), "대기"),
    (8, ("apply", "2026212", 3), "막힘"),  # 결과를 기다리는 지원이 있음
    (9, ("close",), "승인"),
    (10, ("apply", "2026202", 3), "막힘"),  # 마감
]

HARD = [
    (1, ("apply", "2026301", 1), "승인"),
    (2, ("apply", "2026304", 1), "대기"),
    (2, ("vote", "2026301", "2026304", "찬성"), "승인"),
    (3, ("apply", "2026307", 1), "대기"),
    (3, ("vote", "2026301", "2026307", "찬성"), "대기"),
    (3, ("vote", "2026304", "2026307", "찬성"), "승인"),
    (4, ("apply", "2026302", 2), "승인"),
    (5, ("apply", "2026308", 2), "대기"),
    (5, ("vote", "2026302", "2026308", "찬성"), "승인"),
    (6, ("apply", "2026305", 2), "대기"),
    (6, ("apply", "2026306", 2), "대기"),
    (7, ("vote", "2026302", "2026305", "찬성"), "대기"),
    (7, ("vote", "2026308", "2026305", "찬성"), "승인"),
    (8, ("vote", "2026302", "2026306", "찬성"), "대기"),
    (8, ("vote", "2026308", "2026306", "찬성"), "대기"),
    # 학생5가 승인되어 팀원이 되었으므로 학생5도 투표한다 (공고 2.4절)
    (8, ("vote", "2026305", "2026306", "찬성"), "거절"),  # 승인 직전 검사: 주 역할 중복
    (9, ("apply", "2026311", 3), "승인"),
    (10, ("apply", "2026315", 3), "대기"),
    (10, ("vote", "2026311", "2026315", "찬성"), "승인"),
    (11, ("apply", "2026314", 3), "막힘"),  # 필수 포함 역할 자리
    (12, ("apply", "2026310", 4), "승인"),
    (13, ("apply", "2026313", 1), "대기"),
    (13, ("vote", "2026301", "2026313", "찬성"), "대기"),
    (14, ("close",), "승인"),
]

SCENARIOS = [
    ("부록 1 (쉬움)", "samples/쉬움.csv", 3, EASY, {"2026107", "2026108"}),
    ("부록 2 (중간)", "samples/중간.csv", 4, MID,
     {"2026202", "2026203", "2026204", "2026207", "2026208", "2026210", "2026211", "2026212"}),
    ("부록 3 (어려움)", "samples/어려움.csv", 4, HARD,
     {"2026303", "2026306", "2026309", "2026310", "2026312", "2026313", "2026314", "2026316"}),
]


def run(title, csv_path, team_count, steps, expected_unassigned) -> bool:
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")
    with open(os.path.join(ROOT, csv_path), "rb") as f:
        students = parse_roster(f.read())
    sim = Sim(students, team_count)
    names = {s.student_no: s.name for s in students}
    failures = 0

    for step, op, expected in steps:
        if op[0] == "apply":
            got = sim.apply(op[1], op[2]).head
            what = f"{names[op[1]]} -> 팀{op[2]} 지원"
        elif op[0] == "vote":
            got = sim.vote(op[1], op[2], op[3]).head
            what = f"{names[op[1]]}이(가) {names[op[2]]}에 {op[3]}"
        else:
            got = sim.close().head
            what = "관리자 모집 마감"
        mark = "OK " if got == expected else "틀림"
        if got != expected:
            failures += 1
        print(f"  [{mark}] {step:>2}단계 {what:<42} 기대 {expected} / 받음 {got}")

    # 마감 뒤 팀이 없는 학생
    left = {s.student_no for s in sim.unassigned()}
    if left == expected_unassigned:
        print(f"  [OK ] 마감 뒤 팀이 없는 학생 {len(left)}명: "
              + ", ".join(sorted(names[n] for n in left)))
    else:
        failures += 1
        print(f"  [틀림] 팀이 없는 학생이 기대와 다름\n"
              f"        기대: {sorted(names[n] for n in expected_unassigned)}\n"
              f"        받음: {sorted(names[n] for n in left)}")

    # 앱이 스스로 하는 배정 (AI가 3차까지 실패했을 때와 같은 경로)
    result = sim.assign()
    if not result.ok:
        failures += 1
        print(f"  [틀림] 배정을 찾지 못함: {result.reasons}")
        return failures == 0

    print(f"  [OK ] 배정안을 찾음 ({result.nodes}개 경우를 따짐, {result.elapsed * 1000:.0f}ms)")
    sim.confirm(result.placement)

    final = {no: sim.members(no) for no in sim.teams}
    errors = validate_assignment(final, [], {})
    for no, members in sorted(final.items()):
        print(f"        팀{no}: " + ", ".join(m.label for m in members))
    if errors:
        failures += 1
        print(f"  [틀림] 확정한 구성이 규칙을 어김: {errors}")
    else:
        print("  [OK ] 확정한 구성이 2.3절 규칙을 모두 지킴")
    return failures == 0


def main() -> int:
    all_ok = True
    for args in SCENARIOS:
        if not run(*args):
            all_ok = False
    print("\n" + "=" * 64)
    print("모두 통과" if all_ok else "틀린 단계가 있음")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
