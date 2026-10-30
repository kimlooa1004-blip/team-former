"""잔 기능 시험: AI 응답 읽기, 배정이 불가능한 경우, 명단 CSV 읽기.

    python3 tests/test_units.py
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from ai_client import extract_placement  # noqa: E402
from roster import RosterError, parse_roster  # noqa: E402
from rules import Student, required_unfilled, required_seats_short  # noqa: E402
from solver import solve  # noqa: E402

failures = 0


def check(label: str, got, expected) -> None:
    global failures
    ok = got == expected
    if not ok:
        failures += 1
    print(f"  [{'OK ' if ok else '틀림'}] {label}\n        기대 {expected!r}\n        받음 {got!r}"
          if not ok else f"  [OK ] {label}")


print("\n== AI 응답에서 배정안 꺼내기 ==")
teams = {1, 2, 3}

plain = '{"assignments":[{"student_no":"2026301","team":2}]}'
check("그냥 JSON", extract_placement(plain, teams)[0], {"2026301": 2})

fenced = "여기 있습니다.\n```json\n" + plain + "\n```\n감사합니다."
check("코드 울타리와 설명이 붙은 경우", extract_placement(fenced, teams)[0], {"2026301": 2})

check("빈 응답은 실패", extract_placement("   ", teams)[0], None)
check("빈 응답의 이유", extract_placement("   ", teams)[1], "빈 응답")
check("JSON 이 아예 없으면 실패", extract_placement("배정을 못 하겠습니다", teams)[0], None)
check(
    "없는 팀 번호는 실패",
    extract_placement('{"assignments":[{"student_no":"1","team":9}]}', teams)[0],
    None,
)
check(
    "한 학생이 두 번 나오면 실패",
    extract_placement('{"assignments":[{"student_no":"1","team":1},{"student_no":"1","team":2}]}', teams)[0],
    None,
)
check(
    "팀 번호가 글자여도 숫자면 읽음",
    extract_placement('{"assignments":[{"student_no":"1","team":"3"}]}', teams)[0],
    {"1": 3},
)

print("\n== 필수 포함 역할 자리 계산 (공고 3장) ==")
pl_and_wp = Student("1", "가", "기획자", ("웹 프로그래머",))
check("둘 다 할 수 있는 사람 혼자면 1개만 채운 것", required_unfilled([pl_and_wp]), 1)

tt = Student("2", "나", "테스터", ())
pt = Student("3", "다", "발표자", ())
rw = Student("4", "라", "보고서 작성자", ())
check("테스터·발표자뿐인 팀에 보고서 작성자가 들어가면 자리가 모자람",
      required_seats_short([tt, pt, rw]), True)
check("3명이어도 기획자·웹프로그래머가 있으면 괜찮음",
      required_seats_short([pl_and_wp, Student("5", "마", "웹 프로그래머", ()), tt]), False)

print("\n== 규칙을 지키는 배정이 없는 경우 (공고 2.5절 8항) ==")
# 팀1은 4명이 꽉 찼는데 웹 프로그래머를 맡을 사람이 아무도 없다 -> 끝까지 채울 수 없음
full_no_wp = [
    Student("101", "A", "기획자", ()),
    Student("102", "B", "테스터", ()),
    Student("103", "C", "발표자", ()),
    Student("104", "D", "보고서 작성자", ()),
]
result = solve({1: full_no_wp, 2: []}, [Student("105", "E", "웹 프로그래머", ()),
                                        Student("106", "F", "기획자", ())])
check("꽉 찬 팀에 웹 프로그래머가 없으면 배정 불가", result.ok, False)
print("        이유:", result.reasons)

# 팀이 없는 학생이 빈 자리보다 많다
result2 = solve({1: full_no_wp}, [Student("107", "G", "웹 프로그래머", ())])
check("빈 자리가 없으면 배정 불가", result2.ok, False)

# 2명을 채우지 못하는 팀이 생기는 경우
result3 = solve({1: [], 2: []}, [Student("108", "H", "기획자", ()),
                                 Student("109", "I", "웹 프로그래머", ())])
check("학생 2명을 빈 팀 2개에 넣으면 각 팀이 1명뿐이라 불가", result3.ok, False)

print("\n== 명단 CSV 읽기 (공고 2.6절) ==")
with open(os.path.join(ROOT, "samples", "어려움.csv"), "rb") as f:
    students = parse_roster(f.read())
check("BOM 붙은 UTF-8 파일을 16명으로 읽음", len(students), 16)
check("보조 역할 2개를 ; 로 나눠 읽음", students[6].sub_roles, ("발표자", "테스터"))
check("보조 역할이 비면 빈 값", students[15].sub_roles, ())

bad = "student_no,name,main_role\n2026001,가나다,기획자\n".encode("utf-8")
try:
    parse_roster(bad)
    check("열이 3개면 오류", "오류 안 남", "RosterError")
except RosterError:
    check("열이 3개면 오류", "RosterError", "RosterError")

bad_role = "student_no,name,main_role,sub_roles\n2026001,가나다,디자이너,\n".encode("utf-8-sig")
try:
    parse_roster(bad_role)
    check("6개 역할 밖의 값이면 오류", "오류 안 남", "RosterError")
except RosterError:
    check("6개 역할 밖의 값이면 오류", "RosterError", "RosterError")

print("\n" + "=" * 50)
print("모두 통과" if failures == 0 else f"{failures}건 틀림")
raise SystemExit(0 if failures == 0 else 1)
