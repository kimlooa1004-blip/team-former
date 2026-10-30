"""Supabase(PostgreSQL) 연결 (공고 4.2절).

공고 4.2절: "질의를 할 때마다 DB 연결을 새로 만들면 오래 걸린다. 연결은 한 번만
만들고, 그 연결을 사용해 여러 번의 질의를 수행해야 한다."

그래서 연결 묶음(connection pool)을 st.cache_resource 로 앱에 하나만 만들어 두고,
질의할 때마다 그 묶음에서 이미 열린 연결을 빌려 쓰고 돌려준다. 새로 연결하지 않는다.
채점 때는 가상 학생마다 브라우저가 따로 열려 여러 요청이 동시에 오므로,
연결 하나를 그대로 돌려쓰지 않고 스레드에 안전한 ThreadedConnectionPool 을 쓴다.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool
import streamlit as st

from config import get_secret

_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
_schema_lock = threading.Lock()

# 채점 때는 가상 학생마다 브라우저가 따로 열려 최대 16개 화면이 동시에 DB를 읽는다.
# 연결을 그만큼 넉넉히 두고, 그래도 한꺼번에 몰리면 잠깐 기다렸다 다시 빌린다.
_POOL_MAX = 20
_POOL_WAIT_SEC = 5.0


class DatabaseNotConfigured(RuntimeError):
    pass


@st.cache_resource(show_spinner=False)
def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """앱이 사는 동안 딱 한 번 만들어지는 연결 묶음."""
    url = get_secret("DATABASE_URL")
    if not url:
        raise DatabaseNotConfigured(
            "DATABASE_URL 이 없습니다. .env 또는 Streamlit Secrets 에 넣어 주세요."
        )
    # Supabase 는 SSL 이 필요하다. 주소에 적혀 있지 않으면 붙인다.
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return psycopg2.pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=_POOL_MAX,
        dsn=url,
        connect_timeout=10,
        # 연결이 끊긴 것을 모르고 오래 매달리지 않게 한다
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
        application_name="teamform",
    )


def _getconn_waiting(pool):
    """연결을 빌린다. 다 나가 있으면 잠깐 기다렸다 다시 해 본다.

    psycopg2 의 묶음은 연결이 다 나가 있으면 기다리지 않고 바로 PoolError 를 낸다.
    화면 하나가 연결을 쥐는 시간은 아주 짧으므로, 몰린 순간만 넘기면 곧 빌릴 수 있다.
    그대로 두면 동시에 몰렸을 때 그 화면에만 "DB를 읽지 못했습니다"가 뜬다.
    """
    deadline = time.monotonic() + _POOL_WAIT_SEC
    while True:
        try:
            return pool.getconn()
        except psycopg2.pool.PoolError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


@contextmanager
def _borrow():
    """묶음에서 연결을 빌린다. 끊어진 연결이면 버리고 새 것을 받는다."""
    pool = _get_pool()
    conn = _getconn_waiting(pool)
    broken = False
    try:
        if conn.closed:
            broken = True
            pool.putconn(conn, close=True)
            conn = _getconn_waiting(pool)
            broken = False
        yield conn
    except psycopg2.Error:
        broken = True
        raise
    finally:
        try:
            pool.putconn(conn, close=broken)
        except Exception:
            pass


@contextmanager
def transaction():
    """하나의 거래. 중간에 잘못되면 전부 되돌린다.

    지원 접수, 투표, 승인처럼 "읽고 판단해서 쓰는" 일은 모두 이 안에서 한다.
    """
    with _borrow() as conn:
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def query(sql: str, params: tuple | dict | None = None) -> list[dict]:
    with transaction() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def query_one(sql: str, params: tuple | dict | None = None) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple | dict | None = None) -> None:
    with transaction() as cur:
        cur.execute(sql, params)


@st.cache_resource(show_spinner=False)
def init_schema() -> bool:
    """schema.sql 을 그대로 실행한다. 앱이 켜질 때 한 번만.

    이렇게 두면 저장소의 schema.sql 과 앱이 실제로 쓰는 테이블이 절대 어긋나지 않는다
    (공고 5장: "앱이 실제로 쓰는 테이블, 열, 제약과 같은지 확인").
    여러 번 실행해도 괜찮게 만들어 두었다.
    """
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        sql = f.read()
    with _schema_lock:
        with _borrow() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)  # 여러 문장을 한 번에 실행
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    return True


def healthcheck() -> bool:
    """DB 가 살아 있는지 본다. 깃허브 Actions 의 매일 질의도 이것과 같은 일을 한다."""
    try:
        return query_one("select 1 as ok") is not None
    except Exception:
        return False
