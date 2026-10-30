# 팀 프로젝트를 위한 팀 편성 웹 앱

중간 과제 제출물. 작성자: 김루아 (한양여자대학교 빅데이터과)

---

## 1. 배포 주소

<!-- TODO: Streamlit 배포가 끝나면 실제 주소로 바꾸세요 -->
`https://________.streamlit.app`

## 2. PRD와 구현 계획의 위치

- `docs/PRD.md`
- `docs/구현 계획.md`

## 3. 고른 해결 방법 (공고 3장)

| 기능 | 고른 것 | 어떻게 |
| --- | --- | --- |
| 다른 사람의 변경 보기 | **어려운 해결** | `st.fragment(run_every=3)` 으로 바뀐 부분만 3초마다 다시 표시 (`streamlit_app.py` 의 `live_board`). 자동 갱신이 멈추더라도 채점이 막히지 않도록 `refresh` 단추를 안전장치로 함께 두었다 |
| 필수 포함 역할을 지킬 수 없는 팀 | **어려운 해결** | 지원 단계에서 막는다. "지원자가 들어간 뒤 남는 자리 < 아직 채우지 못한 필수 포함 역할 수"이면 `막힘` (`rules.required_seats_short`) |
| 같은 팀에 대기 중인 지원이 여럿 | **어려운 해결** | 승인 직전에 규칙을 다시 검사한다 (`rules.check_before_approve`). 처리 순서는 투표가 끝난 순서 |
| 마지막 자리에 두 명이 동시에 들어감 | **어려운 해결** | DB 유일성 제약. `tf_members` 의 기본 키 `(team_id, slot_no)` 와 `student_id` unique, `check (slot_no between 1 and 4)` (`schema.sql`) |
| AI 응답이 늦을 때 | **어려운 해결** | 모델마다 120초의 **전체** 대기 시간을 따로 재서 끊고 다음 모델로 넘어간다. 호출을 다른 스레드에 맡기고 `future.result(timeout=120)` 으로 잰다 (`ai_client.call_one_model`) |
| 3차 모델까지 실패 | **어려운 해결** | 되추적으로 2.5절 4항의 검사 다섯 가지를 모두 통과하는 배정을 모든 경우를 따져 끝까지 찾는다 (`solver.solve`) |
| AI 대기 중 화면 | **어려운 해결** | 몇 차 모델의 응답을 기다리는 중인지 `assign_status` 에 계속 적는다 |
| DB(Supabase)가 일시정지되지 않게 | **어려운 해결** | 깃허브 Actions 가 매일 DB에 질의를 보낸다 (`.github/workflows/keepalive.yml`, `keepalive.py`) |

## 4. 쓴 모델 3개 (공고 4.3절)

<!-- TODO: 오픈라우터에서 실제로 쓰기로 한 모델 이름으로 바꾸고, 셋 다 응답하는지 확인하세요 -->

1. 1차 `deepseek/deepseek-chat-v3-0324:free`
2. 2차 `meta-llama/llama-3.3-70b-instruct:free`
3. 3차 `mistralai/mistral-small-3.2-24b-instruct:free`

모델 이름은 `config.py` 의 `DEFAULT_MODELS` 에 있고, Streamlit Secrets 에
`MODEL_1` / `MODEL_2` / `MODEL_3` 을 넣으면 코드를 고치지 않고 바꿀 수 있다.
무료 모델로 자동 연결하는 라우터(`openrouter/free`)는 쓰지 않는다.

## 5. 오픈라우터 AI 모델 호출 실패 사례

<!-- TODO: 반드시 직접 돌려 본 실제 기록으로 채우세요. 꾸며 내면 시나리오 밖 점수가 0점입니다(공고 6.3절 20번).
     증거 얻는 법:
       - 관리자 화면 아래 "비밀 값과 AI 호출 기록" 을 펼치면 tf_ai_logs 표가 보입니다.
         차수, 모델, 상태(시간 초과/오류/빈 응답/검사 실패), 걸린 시간(ms), 메시지가 그대로 남습니다.
       - AI 배정 중 assign_status 영역도 화면 캡처해서 img/ 폴더에 넣으세요.
     예시 형식(실제 값으로 바꿀 것):
       - "1차 모델 X 가 120초 안에 응답하지 않아 2차 모델로 넘어감 (화면 img/ai-timeout.png, tf_ai_logs 의 '시간 초과' 행)"
       - "1차 모델 Y 의 배정안에서 팀2에 웹 프로그래머가 없어 앱이 걸러 내고 2차로 넘어감 (화면 img/ai-rejected.png)"
-->

- (직접 돌려 본 실패 사례를 여기에 적고, 화면 파일 경로를 함께 적으세요)

## 6. 클로드가 잘못된 추론이나 답변을 한 사례

**사례: 로그인 단추를 `st.form_submit_button` 으로 만들면서 `key="login_submit"` 을 붙였다.**

공고 2.7절 표에 로그인 단추가 "`st.button` 또는 `st.form_submit_button`"으로 적혀 있어,
클로드는 폼이 입력 묶음 전송에 안전하다는 이유로 `st.form_submit_button("로그인",
key="login_submit")` 로 코드를 썼다. 그러나 `st.form_submit_button` 에는 `key` 매개변수가
없다. 그대로 두었다면 `TypeError` 로 앱이 뜨지 않았을 것이고, 설령 떴더라도 채점 프로그램이
`login_submit` 을 찾지 못해 멈추고 5점이 깎였을 것이다(공고 6.3절 15번).

**알아챈 방법**: 코드를 쓰고 나서 Streamlit 공식 문서의 `st.form_submit_button` 함수
서명을 확인했다. 매개변수는 `label, help, on_click, args, kwargs, type, disabled,
use_container_width` 뿐이고 `key` 가 없다.

**고친 방법**: 폼을 쓰지 않고 `st.text_input` 두 개와 `st.button(key="login_submit")` 으로
바꾸었다. 폼을 못 쓰게 되어 생기는 문제(글자를 넣자마자 단추를 누르면 그 클릭이 화면을 다시
그리는 사이에 묻힐 수 있음)는, 비밀번호 칸의 `on_change` 로도 로그인되게 해서 막았다.
`streamlit_app.py` 의 `_login_on_change` 와 파일 맨 위 설명에 그 이유를 적어 두었다.

**근거**: `streamlit_app.py` 파일 맨 위 설명과 `_login_on_change` 함수의 주석에 이 판단과
이유가 그대로 적혀 있다. Streamlit 공식 문서의 `st.form_submit_button` 함수 서명
(`docs.streamlit.io` 의 API 참조)에 `key` 가 없다는 것도 함께 확인했다.

<!-- TODO (점수를 다 받으려면 둘 중 하나를 더하세요)
     (가) 위 문서 화면을 캡처해 img/form-submit-no-key.png 로 넣고 여기에 경로를 적기
     (나) 앱을 직접 돌려 보다 클로드가 잘못한 다른 사례를 찾으면, 그것을 고친 커밋 해시를 적기
          (예: "커밋 a1b2c3d 에서 고침")
-->


## 7. 본인이 제출한 앱에서 발견한 문제점이나 개선 필요 사항

<!-- TODO: 반드시 직접 돌려 보고 찾은 것을 적으세요. "문제 없음"은 인정되지 않습니다.
     부록 1~3 시나리오를 배포한 앱에서 직접 해 보면서, 어느 단계에서 무엇이 이상했는지와
     그때의 화면(img/step__.png)을 함께 적으세요. -->

- (직접 돌려 보고 찾은 문제를 여기에 적고, 연습용 시나리오의 몇 단계였는지와 화면 파일 경로를 적으세요)

---

## 어떻게 돌리는가

### 내 컴퓨터에서

```bash
pip install -r requirements.txt
cp .env.example .env     # 값을 자기 것으로 바꾼다
streamlit run streamlit_app.py
```

### 시험

DB도 Streamlit도 없이 돌아간다.

```bash
python3 tests/test_scenarios.py   # 부록 1~3 연습용 시나리오 전 단계
python3 tests/test_units.py       # AI 응답 읽기, 규칙 계산, CSV 읽기
```

`samples/` 에 연습용 명단 CSV 3개가 들어 있다 (쉬움 3팀, 중간 4팀, 어려움 4팀).

### DB

테이블은 앱이 시작할 때 `schema.sql` 을 그대로 실행해 만든다. 여러 번 실행해도 괜찮다.
Supabase 화면의 SQL 편집기에 `schema.sql` 을 붙여 넣어 미리 만들어 두어도 된다.
테이블 이름은 모두 `tf_` 로 시작한다.

## 비밀 값

`OPENROUTER_API_KEY`, `DATABASE_URL`, `ADMIN_PASSWORD` 세 개를 쓴다.
내 컴퓨터에서는 `.env`, 배포한 앱에서는 Streamlit Secrets 에 둔다.
코드에 적지 않고, 화면이나 로그에 출력하지 않는다. 관리자 화면에서는 "있음 / 없음"만 보여 준다.

## 로그인

- 학생: 명단 CSV의 학번 / 비밀번호 `1234`
- 관리자: 학번 `admin` / 비밀번호는 `ADMIN_PASSWORD` 값

비밀번호는 bcrypt 해시로 저장한다. 원래 값은 DB에 남지 않는다.
