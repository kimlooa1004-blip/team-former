# 팀 프로젝트를 위한 팀 편성 웹 앱

중간 과제 제출물. 작성자: 김루아 (한양여자대학교 빅데이터과)

---

## 1. 배포 주소

https://teamform-looa.streamlit.app/

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


어려움 연습용 시나리오의 AI 배정 실행 화면에서 확인한 호출 순서이다.

1. 1차 `nvidia/nemotron-3-ultra-550b-a55b:free`
2. 2차 `google/gemma-4-26b-a4b-it:free`
3. 3차 `thinkingmachines/inkling-small:free`

실행은 두 가지 경우가 모두 나왔다.

- **세 모델이 모두 실패한 실행**: 앱이 자체 배정으로 넘어갔다.
  근거 화면 → [AI 모델 실패 및 자체 배정 화면](스크린샷%202026-10-30%20150856.png)
- **1차 모델이 성공한 실행**: AI 가 낸 배정안이 앱의 검사 다섯 가지를 통과해 그대로 확정되었다.
  근거 화면 → [AI 호출 기록 (1차 성공, 53,498ms)](img/ai-elapsed-53s.png)

AI 호출은 `tf_ai_logs` 테이블에 차수·모델·상태·걸린 시간으로 기록되며,
관리자 화면의 「비밀 값과 AI 호출 기록」에서 볼 수 있다.





## 5. 오픈라우터 AI 모델 호출 실패 사례

어려움 연습용 시나리오(16명, 4팀)를 진행한 뒤, 관리자 화면에서
「AI 배정」을 눌렀다. 앱은 먼저 규칙을 지키는 배정이 가능한지
확인한 다음 오픈라우터 모델에 차례로 배정을 요청했다.

이 실행에서는 세 모델이 서로 다른 이유로 실패했다. 화면에 찍힌 그대로이다.

| 차수 | 모델 | 화면에 표시된 상태 | 뜻 |
| --- | --- | --- | --- |
| 1차 | `nvidia/nemotron-3-ultra-550b-a55b:free` | **형식 오류** | 응답은 왔으나 JSON 을 꺼낼 수 없어 앱이 걸러 냄 |
| 2차 | `google/gemma-4-26b-a4b-it:free` | **오류** | 오픈라우터가 오류 응답을 돌려줌 |
| 3차 | `thinkingmachines/inkling-small:free` | **오류** | 오픈라우터가 오류 응답을 돌려줌 |

특히 1차는 **모델이 응답을 하긴 했지만 앱이 받아들이지 않은** 경우다.
`ai_client.extract_placement` 가 응답에서 배정안을 꺼내지 못해 실패로 처리했고,
앱은 그 응답을 믿지 않고 2차 모델로 넘어갔다.

앱은 앞선 모델이 실패할 때마다 다음 모델로 넘어갔고, 3차까지 실패한 뒤에도
배정을 중단하지 않고 스스로 배정안을 찾았다. 관리자 화면에
「검사를 통과한 앱이 스스로 찾은 배정을 아래에 보여 줍니다」라는 안내와
확정 전 배정안이 표시되었다.

근거 화면: [`스크린샷 2026-10-30 150856.png`](스크린샷%202026-10-30%20150856.png)

다른 실행에서는 1차 모델이 53,498ms 만에 성공해 AI 배정안이 확정되었다.
근거 화면: [`img/ai-elapsed-53s.png`](img/ai-elapsed-53s.png)


## 6. 클로드가 잘못된 추론이나 답변을 한 사례

**사례: 클로드가 "`st.form_submit_button` 에는 `key` 매개변수가 없다"고 잘못 알려 주었다.**

로그인 단추를 무엇으로 만들지 정할 때, 클로드는 `st.form_submit_button` 에는 `key` 를
붙일 수 없고 붙이면 `TypeError` 로 앱이 죽는다고 단언했다. 그래서 폼을 쓰지 않는 구조로
가게 되었고, 그 설명을 그대로 믿고 `streamlit_app.py` 파일 맨 위와 README 에도
"`key` 가 없다"고 적어 두었다.

**알아챈 방법**: 제출 전에 Streamlit 공식 문서의
[`st.form_submit_button` API 참조](https://docs.streamlit.io/develop/api-reference/execution-flow/st.form_submit_button)
를 직접 열어 함수 서명을 확인했다. 서명은 다음과 같았다(Version 1.66.0).

```
st.form_submit_button(label="Submit", help=None, on_click=None, args=None,
                      kwargs=None, *, key=None, type="secondary", icon=None,
                      icon_position="left", disabled=False,
                      use_container_width=None, width="content",
                      shortcut=None, wrap=None)
```

`key=None` 이 분명히 들어 있다. 클로드의 말과 정반대였다.
근거 화면 → [`img/form-submit-has-key.png`](img/form-submit-has-key.png)

**고친 방법**: 코드는 바꾸지 않았다. 지금 쓰는 `st.button("로그인", key="login_submit")`
은 공고 2.7절 표가 허용하는 두 가지 중 하나라 그대로 두어도 채점에 문제가 없고,
비밀번호 칸의 `on_change` 로도 로그인이 끝나게 해 두어 글자를 넣자마자 누른 클릭이
묻히는 문제도 이미 막혀 있기 때문이다. 대신 **사실과 다른 설명을 지웠다.**
`streamlit_app.py` 맨 위 주석에서 "`key` 매개변수가 없어 붙일 수 없다"는 문장을
빼고, 실제 이유(`on_change` 를 쓰기 쉬움)와 잘못 알았던 경위를 적었다.

**배운 것**: 클로드가 함수 서명처럼 확인 가능한 사실을 단언할 때도 그대로 믿으면 안 되고,
공식 문서에서 직접 확인해야 한다. 이 사례는 앱이 멈추는 종류의 잘못은 아니었지만,
확인하지 않았다면 제출물에 사실이 아닌 설명을 그대로 남길 뻔했다.

## 7. 본인이 제출한 앱에서 발견한 문제점이나 개선 필요 사항

**문제: AI 배정을 누른 뒤 결과가 나올 때까지 너무 오래 기다려야 한다.**

어려움 연습용 시나리오(16명, 4팀)를 배포한 앱에서 끝까지 돌려 본 뒤,
관리자 화면에서 「AI 배정」을 눌렀다. 1차 모델이 **성공했는데도 53,498ms(약 53.5초)**
가 걸렸다. 그동안 관리자 화면에는 「1차 모델의 응답을 기다리는 중... (최대 120초)」만
떠 있고 다른 조작을 할 수 없다.

이것은 가장 운이 좋은 경우다. 1차가 실패하면 2차, 3차로 넘어가고 모델마다 120초를
기다리므로 **최대 6분까지** 걸릴 수 있다. 실제로 세 모델이 모두 실패한 실행(5항)도
있었다. 공고 6.3절 18번은 배정이 10분을 넘기면 감점하는데, 그 선에 가까워지는 것이다.

**발견한 단계와 근거 화면**: 어려움 시나리오의 마지막 배정 단계.
관리자 화면 「비밀 값과 AI 호출 기록」의 AI 호출 표에 `elapsed_ms = 53498`,
`created_at = 2026-10-30 06:31:05+00:00` 으로 기록되어 있다.
→ [`img/ai-elapsed-53s.png`](img/ai-elapsed-53s.png)

**개선 방향**

1. 앱은 AI 를 부르기 전에 이미 자체 배정안을 찾아 둔다(`actions.run_assignment` 가
   `solver.solve` 를 먼저 부른다). 그 답을 **먼저 화면에 보여 주고**, AI 응답이 오면
   그때 교체하면 관리자가 기다릴 필요가 없다.
2. 모델마다 120초인 제한을 60초 정도로 줄이면 최악의 경우가 6분에서 3분으로 준다.
   무료 모델은 어차피 늦게 오면 실패하는 일이 많다.
3. 남은 시간을 초 단위로 함께 보여 주면 멈춘 것인지 기다리는 중인지 구분된다.

시간이 부족해 이번 제출본에는 넣지 못했고, 지금은 「몇 차 모델을 기다리는 중」이라는
안내만 띄우는 선에서 멈추었다.

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
