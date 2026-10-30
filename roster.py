"""명단 CSV 읽기 (공고 2.6절).

나눠 주는 CSV는 엑셀에서 한글이 깨지지 않도록 BOM이 붙은 UTF-8이므로
utf-8-sig 로 읽는다. 혹시 cp949(엑셀 한국어 기본)로 저장된 파일이 와도 읽히게 해 둔다.
"""

from __future__ import annotations

import csv
import io

from rules import ROLES, Student

HEADER = ("student_no", "name", "main_role", "sub_roles")


class RosterError(Exception):
    pass


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RosterError("CSV 파일의 문자 인코딩을 알 수 없음(UTF-8로 저장해 주세요)")


def _split_subs(raw: str) -> tuple[str, ...]:
    # 보조 역할이 2개면 ; 로 구분하고, 없으면 빈칸 (공고 2.6절)
    raw = (raw or "").replace("；", ";").replace(",", ";")
    out: list[str] = []
    for part in raw.split(";"):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return tuple(out)


def parse_roster(data: bytes) -> list[Student]:
    """CSV 바이트를 Student 목록으로. 형식이 틀리면 RosterError 를 낸다."""
    text = _decode(data)
    reader = csv.reader(io.StringIO(text))

    rows = [row for row in reader if any((cell or "").strip() for cell in row)]
    if not rows:
        raise RosterError("CSV 파일이 비어 있음")

    header = [(cell or "").strip().lstrip("﻿").lower() for cell in rows[0]]
    if header[:4] != list(HEADER):
        raise RosterError(
            "CSV의 첫 줄은 student_no,name,main_role,sub_roles 여야 함. 받은 값: " + ",".join(header)
        )

    students: list[Student] = []
    seen: set[str] = set()
    for line_no, row in enumerate(rows[1:], start=2):
        if len(row) < 3:
            raise RosterError(f"{line_no}째 줄의 열이 모자람(쉼표를 지우지 마세요): {row}")
        student_no = (row[0] or "").strip()
        name = (row[1] or "").strip()
        main_role = (row[2] or "").strip()
        # 보조 역할에 쉼표가 들어가 열이 5개 이상으로 쪼개진 파일도 읽어 낸다
        sub_roles = _split_subs(";".join(c for c in row[3:] if c and c.strip()))

        if not student_no:
            raise RosterError(f"{line_no}째 줄에 학번이 없음")
        if student_no.lower() == "admin":
            raise RosterError("학번 admin 은 관리자 계정이라 명단에 넣을 수 없음")
        if student_no in seen:
            raise RosterError(f"학번이 중복됨: {student_no}")
        seen.add(student_no)
        if not name:
            raise RosterError(f"{line_no}째 줄에 이름이 없음")
        if main_role not in ROLES:
            raise RosterError(f"{line_no}째 줄의 주 역할이 6개 역할에 없음: {main_role!r}")
        for role in sub_roles:
            if role not in ROLES:
                raise RosterError(f"{line_no}째 줄의 보조 역할이 6개 역할에 없음: {role!r}")
        sub_roles = tuple(r for r in sub_roles if r != main_role)
        if len(sub_roles) > 2:
            raise RosterError(f"{line_no}째 줄의 보조 역할이 2개를 넘음: {sub_roles}")

        students.append(Student(student_no, name, main_role, sub_roles))

    if not students:
        raise RosterError("CSV에 학생이 한 명도 없음")
    return students
