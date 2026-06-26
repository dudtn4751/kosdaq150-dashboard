# FnGuide(DataGuide) 추정 데이터 입력 가이드

> 목적: DataGuide에서 **다년 추정(FY1/FY2)·분기 서프라이즈**를 엑셀로 뽑아
> `data/fnguide_estimates.json`으로 변환 → 대시보드 **EPS Revision 모듈**이 자동 사용.
> 이 작업만 하면 됩니다. 코드 수정 불필요.

---

## 0. 준비 (최초 1회)
- 이 저장소를 받은 PC에 Python 3 + 패키지: `pip install pandas openpyxl`
- 터미널에서 저장소 폴더로 이동.

## 1. 템플릿 생성
```bash
python3 scripts/build_fnguide_estimates.py --template
```
→ `data/fnguide_estimates_input.xlsx` 생성 (헤더 + **삼성전자 예시행 1줄** 포함).

## 2. DataGuide 값으로 채우기
엑셀을 열고 **한 종목 = 한 줄**로 입력. 예시행을 참고해 실제 값으로 교체/추가.
- **빈 칸은 그냥 비워둠** (모르면 비우기 — 0으로 채우지 말 것).
- 헤더(첫 줄) 이름은 **절대 바꾸지 말 것**.

| 컬럼 | DataGuide 항목 | 단위 |
|---|---|---|
| `code` | 6자리 종목코드 (필수) | 예) `005930` |
| `name` | 종목명 (선택, 가독용) | |
| `op_fy1_now` / `_1m` / `_3m` | **당해(FY1) 영업이익 컨센서스** — 현재 / 1개월 전 / 3개월 전 | 억원 |
| `op_fy2_now` / `_1m` / `_3m` | **차기(FY2) 영업이익 컨센서스** | 억원 |
| `eps_fy1_now` / `_1m` / `_3m` | **당해 EPS 컨센서스** — 현재/1M전/3M전 | 원 |
| `eps_fy2_now` / `_1m` / `_3m` | **차기 EPS 컨센서스** | 원 |
| `sup_q1_act` / `sup_q1_con` | **가장 최근 분기** 잠정 영업이익(actual) / 직전 컨센(consensus) | 억원 |
| `sup_q2_*` ~ `sup_q4_*` | 그 이전 분기들 (q2=2분기 전 …) | 억원 |
| `est_std` | 추정치 표준편차(애널리스트 분산) | 억원 |
| `est_mean` | 추정치 평균 | 억원 |
| `est_age_days` | 추정치 평균 경과일수 | 일 |
| `ytd_op` | 연초누계 영업이익 (선택) | 억원 |
| `fy_roll` | 회계연도 전환 구간이면 `TRUE`, 아니면 비우기 (선택) | |

> 💡 가장 중요한 칸: `op_fy1_*`, `eps_fy1_*` (실현 리비전·모멘텀), `sup_q*` (서프라이즈),
> `est_std`/`est_mean`/`est_age_days` (신뢰도). FY2는 있으면 좋고 없어도 됨.
> **단위 주의**: 영업이익·서프라이즈는 **억원**, EPS는 **원**.

## 3. 변환
```bash
python3 scripts/build_fnguide_estimates.py
```
→ `data/fnguide_estimates.json` 생성. 마지막에 "종목 N개 … 변환 완료"가 뜨면 성공.
(입력 파일을 다른 경로/이름으로 저장했다면: `python3 scripts/build_fnguide_estimates.py 경로.xlsx`)

## 4. 커밋 (반영)
```bash
git add data/fnguide_estimates.json
git commit -m "data: FnGuide 추정 갱신 YYYY-MM-DD"
git push
```
→ 다음 자동 갱신(매일 05:00 KST)부터 EPS Revision 점수에 반영됩니다.

## 5. 주기
- 컨센서스는 자주 안 변하므로 **월 1회(또는 실적시즌 직후)** 갱신이면 충분.
- 매번 1·2·3·4단계 반복. (1단계 템플릿은 이전 파일 재사용 가능 — 값만 업데이트)

---

### 자주 묻는 것
- **CSV로 해도 되나요?** 네. `--template fnguide.csv` 로 CSV 템플릿 생성, 채운 뒤 `... build_fnguide_estimates.py fnguide.csv`.
- **코드를 5930처럼 입력했어요** → 자동으로 `005930`으로 보정됩니다.
- **일부 종목만 있어도 되나요?** 네. 입력한 종목만 모듈이 정밀화되고, 나머지는 기존(무료) 방식 유지.
- **숫자에 콤마(,) 있어도?** 자동 제거됩니다.
