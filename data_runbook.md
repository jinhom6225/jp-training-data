# data_runbook.md — 職業訓練アラート 데이터 운영 런북

이 저장소(`jinhom6225/jp-training-data`)의 운영 방법입니다. plan.md Phase 9를 지금 설계에 맞춰 옮겼습니다.
푸시(FCM)는 쓰지 않습니다(2026-10-28 결정). 그래서 푸시 사고 절차는 없습니다.

- 수집: 매일 JST 06:30·18:30 (GitHub Actions `collect`). 수요일 아침은 전체 상세를 다시 받습니다.
- 배포: `https://jinhom6225.github.io/jp-training-data/` 의 `meta.json`, `stats.json`, `pref/01.json` … `pref/47.json`.
- 커밋은 명박사, **push는 진호님**입니다.

## 1. 東京 보충 (overrides.json)

HWIS에는 東京 코스가 늦게 올라옵니다. 그래서 공식 페이지에 일정이 나온 "予告"를 사람이 넣습니다.

### 언제

- 매월 **첫째·셋째 월요일**.
- 출시 전 첫 입력: 都立 4월생(모집 2027-01-07~01-29). 2026-10-29에 넣었습니다.

### 무엇을 보나

| 페이지 | 주소 | 보는 것 |
|---|---|---|
| 東京労働局 求職者支援訓練 募集中・募集予定 | https://jsite.mhlw.go.jp/tokyo-roudoukyoku/newpage_00139.html | 다음 개강 회차의 募集期間 (HWIS에 아직 없는 것만) |
| TOKYOはたらくネット 都立 募集案内 | https://www.hataraku.metro.tokyo.lg.jp/kyushokusha-kunren/school/annai/index.html | 入校時期별 募集期間·選考日 |
| 각 센터(校)의 入校生募集 | 예: https://www.hataraku.metro.tokyo.lg.jp/vsdc/joto/nyukobosyu.html | 회차별 科目 목록(공표되면) |

- 페이지는 몇 번만 엽니다. 자동 수집하지 않습니다.
- **공식 페이지에 날짜가 없으면 넣지 않습니다.** 날짜를 추측하지 않습니다.

### 항목 형식

`overrides.json` 은 `{"entries": [...]}` 입니다. 항목 하나는 앱의 코스 객체와 같고 `origin` 은 `override` 입니다.

- `id`: `tokyo-{학교 slug}-{입교 연월 YYYYMM}` (소문자·숫자·하이픈, 최대 48자).
- 꼭 있어야 하는 것: `name`(학교·실시기관 이름), `kind`, `fields`(1개 이상), `rounds`(1~5회차), `childcare`, `sourceUrl`(허용 도메인), `sourceName`, `checkedAt`(+09:00), `entryMonth`(YYYY-MM), `targetCourses`(1~20개).
- 모르는 칸은 `null`: 주소, 自己負担額, 定員, 訓練期間, 選考日 등.
- 숫자는 반각만 씁니다(全角 숫자는 앱이 파일 전체를 거부합니다).

지금 들어 있는 항목(예시):

```json
{
  "id": "tokyo-toritsu-202704",
  "origin": "override",
  "kind": "public",
  "name": "都立職業能力開発センター（各校）",
  "fields": ["it", "office", "medical", "care", "design", "building", "manufacturing", "other"],
  "city": null,
  "address": null,
  "rounds": [{"no": 1, "start": "2027-01-07", "end": "2027-01-29"}],
  "trainingStart": null,
  "trainingEnd": null,
  "hours": null,
  "selfCost": null,
  "capacity": null,
  "selectionDate": null,
  "resultDate": null,
  "conditions": "募集期間は予定。選考日は2027年2月9日・10日・12日のいずれか（予定）。ジョブセレクト科・実務作業科・東京障害者職業能力開発校の科目は対象外",
  "childcare": false,
  "provider": null,
  "phone": null,
  "sourceUrl": "https://www.hataraku.metro.tokyo.lg.jp/kyushokusha-kunren/school/annai/index.html",
  "sourceName": "TOKYOはたらくネット",
  "checkedAt": "2026-10-29T04:10:00+09:00",
  "entryMonth": "2027-04",
  "targetCourses": ["4月入校の各科目（科目一覧は未公表）"]
}
```

科目 목록이 공표되면 학교별 항목(`tokyo-joto-202704` 등)으로 나누고 `targetCourses` 에 科目 이름을 넣습니다.

### 확인과 커밋

```bash
cd ~/Documents/jinhom6225/jp-training-data
.venv/bin/python -m scraper.overrides --check
.venv/bin/python -m pytest -q
git add overrides.json
git commit -m "data: add Tokyo 予告 <학교> <YYYY-MM>"
```

- `--check` 가 `ok` 이고 pytest가 모두 통과해야 커밋합니다.
- 명박사가 커밋하고, **push는 진호님**이 합니다.
- push 뒤 다음 수집에서 앱의 東京 목록에 「予告」 카드가 보이는지 확인합니다.
- 항목이 잘못되면 그 실행은 overrides를 하나도 합치지 않고 Telegram으로 알립니다(배포는 계속).

### 자동 숨김과 지우기

- HWIS에 **같은 학교**(이름이 서로 포함, 「都立」은 빼고 비교) + **같은 입교 연월**(`trainingStart` 의 연월 = `entryMonth`) 코스가 올라오면 그 予告는 자동으로 숨겨집니다.
- 모집 회차가 모두 끝난 予告도 자동으로 빠집니다.
- 숨겨졌거나 끝난 항목은 Actions 로그의 "Run report" → `overrides.hidden` / `overrides.expired` 에 나옵니다. **다음 정기 점검 때 overrides.json에서 지웁니다.**

## 2. 이상 알림 대응

실패 알림은 모두 `jp-training-data` 로 시작합니다. 먼저 Actions 실행 로그와 "Run report"(report.json)를 봅니다.

### 성공 요약 (매일 아침)

- **아침 정기 실행(06:30 JST)** 과 **모든 수동 실행** 이 배포까지 성공하면 요약 1건이 옵니다. 저녁 실행은 성공해도 조용합니다(실패는 알림).
- 요약은 Pages 배포가 끝난 뒤에만 보냅니다. 그래서 요약이 왔다면 "배포됨"입니다.
- 아침/저녁은 시계가 아니라 cron 문자열(`30 21 * * *`)로 구분합니다. 실행이 늦게 시작해도 아침으로 셉니다.

```
✅ 배포 완료: 코스 2,112개
직전 대비 +5 / −3 (도도부현 4곳 변동)
기타 분야 5.4% · 東京 予告 1건
상세: 바뀐 코스만 · 실행 14분
https://jinhom6225.github.io/jp-training-data/meta.json
실행: 아침 정기
```

- 0건인 도도부현이 있으면 「0건 도도부현: 16, 31」 줄이 더 붙습니다.
- 수요일 아침은 「상세: 전체 (수요일·전체 실행)」 이고 90분 안팎 걸립니다.
- **09:00 JST까지 요약이 없으면 아침 실행이 배포하지 못한 것입니다.** 실패 알림이 없어도 Actions에서 그날 아침 `collect` 실행을 확인합니다(지연·취소·대기 중일 수 있음). 수요일은 10:00 JST까지 기다립니다.

### 실패 알림

| 알림 / 종료 코드 | 뜻 | 할 일 |
|---|---|---|
| `✅ 배포 완료` (종료 0, 아침·수동) | 정상 배포 | 숫자만 훑어봄. 변동이 크면 stats.json 확인 |
| (알림 없음) 종료 0, 저녁 | 정상 배포 | 없음 |
| `anomaly, nothing published` (종료 2) — 건수 30% 넘게 감소, 도도부현 0건, 상세 실패 10% 초과, 구조 표식 없음 | 이번 결과를 배포하지 않음. 앱은 직전 파일을 계속 씀 | 아래 "판단 순서" |
| `anomaly … no previous publish … bootstrap` / `previous publish unreadable` / `previous pref files unreadable` (종료 2) | Pages의 직전 파일이 없거나 깨짐 | Pages URL을 브라우저로 열어 확인. 원인을 확인한 뒤에만 bootstrap (아래) |
| `stopped: HWIS blocked the run` (종료 3) — 403/429, 상세 10건 연속 실패, 상세 실패율 10% 초과(50건 이후), 도도부현 3곳 연속 실패 | 차단 또는 사이트 장애 의심 | 다음 실행 1~2회를 기다림. 계속되면 **진호님께 보고** |
| `failed: …` (종료 1) 또는 `collect job failed, see …` | 코드 오류, Pages 응답 이상(200·404 외), 설치·테스트 실패 | 로그의 오류를 보고 고침 |
| `run problem: collect=… deploy=failure/cancelled` | 배포 실패 또는 실행 취소(시간 초과 등) | Actions에서 deploy 로그 확인. Pages 설정이 "GitHub Actions"인지 확인 후 collect 수동 실행 |
| `overrides.json has problems, none merged` | overrides 형식 오류 | `--check` 로 고쳐 커밋 → 진호님 push |
| `smoke OK` / `smoke FAILED` | 접근 시험 결과 | FAILED면 차단 의심 → 진호님께 보고 |

로그에 `TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set` 경고가 보이면 Secret이 빠진 것입니다. 진호님이 넣습니다.

### 판단 순서 (종료 2·3)

1. **HWIS 일시 오류**(システムエラー 페이지, 일시적 실패): 다음 실행을 기다립니다.
2. **HTML 변경**(구조 표식 없음이 계속됨):
   - 실패한 페이지를 저장해 `tests/fixtures/` 에 넣고, 테스트를 먼저 고친 뒤(RED) 파서를 고칩니다.
   - `pytest` 통과 → 커밋 → 진호님 push.
   - Actions에서 `collect` 를 **mode=dry** 로 실행(배포 없음). 정상이면 **mode=normal** 로 실행.
3. **차단 의심**(403/429, 연속 실패가 며칠 계속): **진호님께 보고**합니다. 홈서버로 옮기는 일은 **진호님 허락이 필요**합니다.

### bootstrap을 다시 쓰는 경우

- bootstrap은 "직전 배포본 없이" 전체를 새로 만드는 실행입니다. 처음 한 번만 씁니다.
- 다시 쓰는 것은 **직전 배포본이 정말 깨졌고 원인을 확인한 뒤**뿐입니다. 이상 감지를 피하려고 쓰지 않습니다.

### 3일 규칙

- 데이터의 `generatedAt` 이 72시간보다 오래되면 앱이 스스로 「情報が古い可能性があります」와 「…の予定です」 문장으로 바꿉니다.
- 그래서 고치는 데 3일이 넘어도 **손으로 배포해서 우회하지 않습니다.** 검증과 이상 감지를 지난 결과만 배포합니다.

## 3. 점검 달력

| 주기 | 할 일 |
|---|---|
| 매일 | 아침 ✅ 요약 확인 (09:00 JST까지, 수요일은 10:00). 없으면 Actions 확인. 실패 알림 확인 |
| 매주 수요일 | 아침 실행이 전체 상세(full)인지 로그 확인. `stats.json` 의 `total`(약 2,100 ±20%), `byPref`, `otherRatio`(20% 이하) 추이 확인 |
| 매월 1회 | `other` 코스 이름을 보고 `scraper/fields.yml` 키워드 보강 → 테스트 → 커밋 |
| 매월 첫째·셋째 월요일 | 東京 보충 (1장) |
| 12/15~1/31 | 주요 회차 매일 확인: 大阪府立(~1/25), 福岡県立(~1/21), ポリテク関西(12/23~), 都立 4월생(1/7~1/29). 앱 목록과 HWIS 원문 비교 |

`stats.json`: https://jinhom6225.github.io/jp-training-data/stats.json

## 4. 긴급 정정 (「情報の誤りを報告」)

1. 메일을 받으면 **24시간 안에** 그 코스의 HWIS 원문(코스의 `sourceUrl`)과 앱 표시를 비교합니다.
2. HWIS가 바뀐 것뿐이면: 다음 수집(하루 2회)에서 반영됩니다. 급하면 `collect` 를 mode=normal 로 수동 실행.
3. 파서 문제면: 원문 페이지를 fixture로 저장 → 테스트 먼저 → 파서 수정 → 커밋 → 진호님 push → mode=dry → mode=normal.
4. 東京 予告 문제면: overrides.json 을 고쳐 커밋 → 진호님 push.
5. 원인과 조치를 기록합니다.

## 5. 수동 실행

### GitHub Actions (`collect` → Run workflow → mode)

| mode | 하는 일 |
|---|---|
| auto | 평소와 같음 (수요일 아침이면 full) |
| normal | 새 코스·바뀐 코스·14일 안 마감 코스만 상세 |
| full | 모든 상세 (약 90분) |
| dry | auto와 같지만 배포하지 않음 (수정 확인용) |
| force-anomaly | 이상 감지 경로 시험: Telegram 1건, 배포 없음 |
| bootstrap | 첫 배포 전용 (위 "bootstrap을 다시 쓰는 경우") |

`smoke` → Run workflow: HWIS 접근 시험(요청 3건).

### 로컬

```bash
cd ~/Documents/jinhom6225/jp-training-data
.venv/bin/python -m pytest -q
.venv/bin/python -m scraper.overrides --check

# 東京만 시험 수집 (직전 배포본 없이, 원본 페이지를 캐시)
.venv/bin/python -m scraper.run --mode full --bootstrap --prefs 13 --pages-url "" --out out --cache out/cache

# 키워드만 바꿨을 때: 캐시로 다시 만들기 (HWIS 요청 없음)
.venv/bin/python -m scraper.run --mode full --bootstrap --pages-url "" --out out --cache out/cache --from-cache

# 결과: out/site/ (배포본과 같은 형식), out/report.json (실행 보고)
```

- 로컬 수집도 1.5초 간격을 지킵니다. 전국 전체는 약 90분입니다. 꼭 필요할 때만 합니다.
- 로컬 결과를 Pages에 직접 올리지 않습니다. 배포는 Actions만 합니다.
