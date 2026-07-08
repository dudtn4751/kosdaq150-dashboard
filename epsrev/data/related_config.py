"""epsrev/data/related_config.py — '관련 데이터' 커스터마이징 config.

DATASETS: 데이터셋 레지스트리(각 지표의 소스·키·단위·상세항목·메타).
PANEL_CONFIG: 섹터/종목 → {핵심:[...], 연관:[...]} 데이터셋 배치.
get_related_panels(ticker): ticker→섹터 resolve + override 우선 → 패널별 데이터셋 dict 반환.

새 종목/섹터 커스터마이징은 여기 PANEL_CONFIG에 한 줄 추가하면 된다.
"""
from __future__ import annotations

# ── 데이터셋 레지스트리 ────────────────────────────────────────────────────────
# details: None 또는 [{"label","key"}] — 상세항목별 시리즈 키(bf_export는 'ic-pc').
_EXP = {"source": "bf_export", "unit": "USD", "frequency": "월간", "source_name": "관세청 TRASS"}
_IND = {"source": "industry", "frequency": "월간"}

DATASETS: dict[str, dict] = {
    # ── 수출(빅파이낸스 launch-data/trade 실데이터) ──
    "exp_semi": {**_EXP, "name": "반도체 수출", "key": "1-3",
                 "details": [{"label": "총계", "key": "1-3"}, {"label": "메모리", "key": "1-4"},
                             {"label": "D램", "key": "1-5"}, {"label": "낸드", "key": "1-6"},
                             {"label": "시스템", "key": "1-7"}]},
    "exp_auto": {**_EXP, "name": "자동차 수출", "key": "2-1",
                 "details": [{"label": "총계", "key": "2-1"}, {"label": "전기차", "key": "2-4"},
                             {"label": "엔진부품", "key": "2-7"}]},
    "exp_ship": {**_EXP, "name": "선박 수출", "key": "13-1", "details": None},
    "exp_bat":  {**_EXP, "name": "2차전지 수출", "key": "9-3", "details": None},
    "exp_cosmetic": {**_EXP, "name": "화장품 수출", "key": "5-1",
                     "details": [{"label": "총계", "key": "5-1"}, {"label": "기초", "key": "5-2"},
                                 {"label": "색조", "key": "5-3"}]},
    "exp_steel":  {**_EXP, "name": "철강 수출", "key": "3-1", "details": None},
    "exp_chem":   {**_EXP, "name": "화학 수출", "key": "8-1", "details": None},
    "exp_pharma": {**_EXP, "name": "의약품 수출", "key": "11-1", "details": None},

    # ── 산업 판매/생산(스텁 — get_industry_data 연동 예정) ──
    "ind_auto_sales": {**_IND, "name": "완성차 판매", "key": "auto_sales", "unit": "대",
                       "source_name": "KAMA(연동 예정)",
                       "details": [{"label": "내수", "key": "domestic"},
                                   {"label": "수출", "key": "export"},
                                   {"label": "글로벌", "key": "global"}]},
    "ind_import_car": {**_IND, "name": "수입차 판매", "key": "import_car", "unit": "대",
                       "source_name": "KAIDA(연동 예정)", "details": None},
    "ind_semi_prod":  {**_IND, "name": "반도체 생산·출하", "key": "semi_prod", "unit": "지수",
                       "source_name": "통계청(연동 예정)", "details": None},
}

# ── 패널 배치(섹터 기본값 + 종목 override) ────────────────────────────────────
PANEL_CONFIG: dict[str, dict] = {
    "sector:auto": {"핵심": ["ind_auto_sales"], "연관": ["ind_import_car", "exp_auto"]},
    "sector:semi": {"핵심": ["exp_semi"], "연관": ["ind_semi_prod"]},
    # 종목 override 예시(현대차)
    "ticker:005380": {"핵심": ["ind_auto_sales"], "연관": ["ind_import_car", "exp_auto"]},
}

# 섹터 → 기본 수출 데이터셋(PANEL_CONFIG 없을 때 핵심 패널로 사용)
SECTOR_DEFAULT: dict[str, str] = {
    "semi": "exp_semi", "auto": "exp_auto", "shipdef": "exp_ship", "bat": "exp_bat",
    "consumer": "exp_cosmetic", "steel": "exp_steel", "petrochem": "exp_chem", "bio": "exp_pharma",
}


def all_export_keys() -> list[str]:
    """스냅샷에 담아야 할 bf_export 키(기본 + 상세) 전체."""
    keys = set()
    for d in DATASETS.values():
        if d.get("source") != "bf_export":
            continue
        keys.add(d["key"])
        for dt in (d.get("details") or []):
            keys.add(dt["key"])
    return sorted(keys)


def _resolve(ids: list[str]) -> list[dict]:
    out = []
    for i in ids:
        d = DATASETS.get(i)
        if d:
            out.append({**d, "id": i})
    return out


def get_related_panels(ticker: str) -> dict:
    """{'핵심':[dataset dict...], '연관':[...]}. ticker override > sector > 기본(섹터 수출)."""
    ticker = str(ticker).zfill(6)
    try:
        from epsrev.data.dashboard_data import CO
        sec = (CO.get(ticker) or {}).get("secId")
    except Exception:
        sec = None
    cfg = PANEL_CONFIG.get(f"ticker:{ticker}") or PANEL_CONFIG.get(f"sector:{sec}")
    if not cfg:
        dsid = SECTOR_DEFAULT.get(sec)
        cfg = {"핵심": [dsid] if dsid else [], "연관": []}
    core = _resolve(cfg.get("핵심", []))
    rel = _resolve(cfg.get("연관", []))
    overrides = cfg.get("titles", {})

    def _title(role, datasets):
        if overrides.get(role):
            return overrides[role]
        if datasets and all(d.get("source") == "bf_export" for d in datasets):
            return "수출 데이터"
        return "핵심 산업지표" if role == "핵심" else "연관 산업지표"

    return {"핵심": core, "연관": rel,
            "titles": {"핵심": _title("핵심", core), "연관": _title("연관", rel)}}
