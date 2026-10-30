"""DB 가 일시정지되지 않게 매일 질의를 보낸다 (공고 3장, 4.4절의 어려운 해결).

깃허브 Actions 가 하루 한 번 이 파일을 돌린다(.github/workflows/keepalive.yml).
Supabase 무료 프로젝트는 1주일 동안 DB 요청이 적으면 일시정지되고,
채점 기간에 일시정지되어 있으면 시나리오 점수가 0점이 된다(공고 6.3절 16번).

DB 주소와 비밀번호는 절대 출력하지 않는다 (공고 6.3절 8번).
오류 메시지는 비밀번호 부분만 가리고 그대로 보여 준다.
"""

import os
import re
import sys

import psycopg2


def hide_password(text):
    """postgresql://아이디:비밀번호@주소 에서 아이디와 비밀번호를 가린다."""
    return re.sub(r"://[^@\s]+@", "://***:***@", str(text))


url = os.environ.get("DATABASE_URL", "").strip()
if not url:
    print("DATABASE_URL 없음")
    sys.exit(1)
if "sslmode=" not in url:
    url += ("&" if "?" in url else "?") + "sslmode=require"

try:
    conn = psycopg2.connect(url, connect_timeout=20)
except Exception as exc:
    print(f"DB 연결 실패: {type(exc).__name__}: {hide_password(exc)}")
    sys.exit(1)

try:
    with conn:
        with conn.cursor() as cur:
            cur.execute("select now()")
            now = cur.fetchone()[0]
            # 테이블은 앱이 처음 켜질 때 만들어지므로, 아직 없어도 실패로 보지 않는다
            cur.execute("select to_regclass('public.tf_students') is not null")
            has_table = cur.fetchone()[0]
            if has_table:
                cur.execute("select count(*) from tf_students")
                count = cur.fetchone()[0]
                print(f"DB 살아 있음. tf_students {count}행, 서버 시각(UTC) {now}")
            else:
                print(f"DB 살아 있음. tf_ 테이블은 아직 없음(앱 첫 실행 때 생성), 서버 시각(UTC) {now}")
except Exception as exc:
    print(f"DB 질의 실패: {type(exc).__name__}: {hide_password(exc)}")
    sys.exit(1)
finally:
    conn.close()
