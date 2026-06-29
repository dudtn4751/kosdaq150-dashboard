"""dashboard_data 어댑터 — 팀원 pair_finder가 기대하는 SECTORS/CO/seed_rand/gen_spread를
우리 alpha.json에 연결. (실제 종목·섹터·가격·이벤트 + 시드 기반 placeholder 보조지표)

CO[ticker]  = {n,t,secName,secId,secColor,p(가격),br(차입%),ev[{pts,txt}]}
SECTORS     = [{id,name,cos:[{t,n,secName}]}]
seed_rand(seed)->callable, gen_spread(seed)->[{m,spread}]
"""

import json
import random
from pathlib import Path

_ALPHA = Path(__file__).resolve().parent / "alpha.json"

SEC_COLORS = {
    "정보기술": "#4f8eff", "산업재": "#00c87a", "헬스케어": "#ff6b9d",
    "자유소비재": "#ffaa00", "필수소비재": "#ffd24a", "금융": "#9b8cff",
    "소재": "#ff6b3d", "에너지": "#00c2c8", "커뮤니케이션서비스": "#c84fff",
    "유틸리티": "#7a8cff", "기타": "#8899bb",
}


def seed_rand(seed: int):
    """재현 가능한 난수 함수 반환 (placeholder 보조지표용)."""
    return random.Random(int(seed)).random


def gen_spread(seed: int):
    """12개월 누적 상대수익률(%) 시드 시계열 (실제 스프레드 연결 전 placeholder)."""
    rng = random.Random(int(seed))
    base, out = 0.0, []
    for i in range(12):
        base += (rng.random() - 0.48) * 4.5
        out.append({"m": f"{i+1}M", "spread": round(base, 1)})
    return out


def _build():
    try:
        ranked = json.loads(_ALPHA.read_text(encoding="utf-8")).get("ranked", [])
    except Exception:
        ranked = []
    co, sec_map = {}, {}
    for s in ranked:
        code = str(s.get("code", ""))
        if not code.isdigit():            # gen_spread가 int(code) 사용 → 숫자코드만
            continue
        sector = s.get("sector", "기타")
        price = ((s.get("ohlc") or {}).get("c") or [None])[-1]
        ev = []
        if s.get("index_event") == "add":
            ev.append({"pts": 60, "txt": "지수 편입 예상"})
        elif s.get("index_event") == "remove":
            ev.append({"pts": -60, "txt": "지수 편출 예상"})
        pe = s.get("pressure_eok")
        if pe and pe >= 1e4:
            ev.append({"pts": min(40, round(pe / 1e4)), "txt": f"ETF 매수압력 {pe/1e4:.1f}조"})
        # 차입비용(placeholder): 대형주 낮게, 소형주 높게
        mc = s.get("marcap") or 0
        br = 0.8 if mc >= 1e13 else (1.5 if mc >= 1e12 else 2.2)
        co[code] = {"n": s.get("name", code), "t": code, "secName": sector, "secId": sector,
                    "secColor": SEC_COLORS.get(sector, "#4f8eff"),
                    "p": round(price) if price else None, "br": br, "ev": ev}
        sec_map.setdefault(sector, {"id": sector, "name": sector, "cos": []})
        sec_map[sector]["cos"].append({"t": code, "n": s.get("name", code), "secName": sector})
    # 종목 많은 섹터부터
    sectors = sorted(sec_map.values(), key=lambda x: -len(x["cos"]))
    return co, sectors


CO, SECTORS = _build()
