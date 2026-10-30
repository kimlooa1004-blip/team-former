-- 팀 편성 앱 테이블 (공고 5장 "DB 최소 참고안")
--
-- 모든 테이블 이름은 tf_ 로 시작한다 (공고 4.2절).
-- 6장 실습 테이블과 같은 Supabase 프로젝트에 함께 들어가므로 이름으로 구분한다.
--
-- 이 파일은 앱이 시작할 때 그대로 실행된다(db.py 의 init_schema).
-- 따라서 "앱이 실제로 쓰는 테이블, 열, 제약"과 이 파일은 항상 같다.
-- Supabase 화면의 SQL 편집기에 그대로 붙여 넣어 미리 만들어 두어도 된다.
-- 여러 번 실행해도 괜찮다(IF NOT EXISTS).

-- 학생과 관리자
create table if not exists tf_students (
    id              bigserial primary key,
    student_no      text        not null unique,
    name            text        not null,
    main_role       text,
    password_hash   text        not null,          -- 공고 3장: 비밀번호는 해시로 저장 (bcrypt)
    is_admin        boolean     not null default false,
    created_at      timestamptz not null default now(),
    constraint tf_students_main_role_check check (
        main_role is null or main_role in (
            '기획자', '웹 프로그래머', '프론트엔드 디자이너', '테스터', '보고서 작성자', '발표자'
        )
    )
);

-- 보조 역할. 학생 1명에 0~2행 (공고 2.2절)
create table if not exists tf_student_sub_roles (
    student_id  bigint not null references tf_students(id) on delete cascade,
    role        text   not null,
    primary key (student_id, role),
    constraint tf_sub_roles_role_check check (
        role in ('기획자', '웹 프로그래머', '프론트엔드 디자이너', '테스터', '보고서 작성자', '발표자')
    )
);

-- 팀. 관리자가 명단을 올릴 때 정한 팀 수만큼 만든다 (공고 2.6절)
create table if not exists tf_teams (
    id      bigserial primary key,
    team_no int  not null unique,
    name    text not null unique
);

-- 팀원.
--   (team_id, slot_no) 를 기본 키로 두어, 마지막 자리에 두 명이 동시에 들어가면
--   먼저 도착한 학생만 기록된다 (공고 3장 "마지막 자리에 두 명이 동시에 들어감"의 어려운 해결).
--   student_id 의 유일성 제약이 "한 학생은 한 팀에만 소속"을 DB에서 지켜 준다.
--   slot_no 의 check 가 다섯 번째 자리를 막는다 (정원 4명).
create table if not exists tf_members (
    team_id     bigint      not null references tf_teams(id) on delete cascade,
    slot_no     int         not null,
    student_id  bigint      not null references tf_students(id) on delete cascade,
    joined_at   timestamptz not null default now(),
    primary key (team_id, slot_no),
    constraint tf_members_student_unique unique (student_id),
    constraint tf_members_slot_check check (slot_no between 1 and 4)
);

-- 지원
create table if not exists tf_applications (
    id          bigserial primary key,
    team_id     bigint      not null references tf_teams(id) on delete cascade,
    student_id  bigint      not null references tf_students(id) on delete cascade,
    status      text        not null default '대기',
    reason      text,
    created_at  timestamptz not null default now(),
    decided_at  timestamptz,
    constraint tf_applications_status_check check (status in ('대기', '승인', '거절'))
);

-- 한 학생은 결과를 기다리는 지원을 하나만 가질 수 있다 (공고 2.4절 "한 학생의 지원").
-- 앱에서도 검사하지만 DB에서도 막는다.
create unique index if not exists tf_applications_one_pending
    on tf_applications (student_id)
    where status = '대기';

create index if not exists tf_applications_team_status
    on tf_applications (team_id, status);

-- 투표. 한 번 투표하면 바꿀 수 없으므로 (application_id, voter_id) 가 기본 키 (공고 2.4절)
create table if not exists tf_votes (
    application_id bigint      not null references tf_applications(id) on delete cascade,
    voter_id       bigint      not null references tf_students(id) on delete cascade,
    vote           text        not null,
    created_at     timestamptz not null default now(),
    primary key (application_id, voter_id),
    constraint tf_votes_vote_check check (vote in ('찬성', '거부'))
);

-- 마감 여부 등
create table if not exists tf_settings (
    key        text primary key,
    value      text,
    updated_at timestamptz not null default now()
);

-- AI 호출 기록. README 의 실패 사례(7.1절 5항)를 꾸며 내지 않고 실제 기록으로 쓰기 위함.
create table if not exists tf_ai_logs (
    id          bigserial primary key,
    attempt_no  int,
    model       text,
    status      text,                -- 성공 / 시간 초과 / 오류 / 빈 응답 / 검사 실패
    elapsed_ms  int,
    message     text,
    created_at  timestamptz not null default now()
);

create index if not exists tf_ai_logs_created on tf_ai_logs (created_at desc);
