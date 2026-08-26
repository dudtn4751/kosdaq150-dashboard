"""수출입 데이터 — 새 앱(Flask) 이전 안내.

기존 Streamlit 구현은 `pages/_archive/수출입_데이터.py`에 그대로 보존돼 있다(롤백 가능:
이 파일과 맞바꾸면 즉시 복귀). 새 앱은 apps/trade_web(Flask + Chart.js)이며 URL은
st.secrets["TRADE_WEB_URL"] 또는 환경변수 TRADE_WEB_URL로 주입한다.
"""

import os

import streamlit as st


def _new_url() -> str:
    url = os.environ.get("TRADE_WEB_URL", "").strip()
    if not url:
        try:
            url = str(st.secrets.get("TRADE_WEB_URL", "")).strip()
        except Exception:
            url = ""
    return url.rstrip("/")


st.title("수출입 데이터 대시보드")
url = _new_url()

st.info(
    "수출입 대시보드가 **새 앱으로 이전**되었습니다. "
    "품목 카드 그리드 · 10일 단위/월간 두 층위 · 기업별 분해 · 투자 시그널 보드 · "
    "Watchlist · 기업 검색을 새 주소에서 이용하세요.",
    icon="🚢",
)

if url:
    st.link_button("새 수출입 대시보드 열기 →", url, type="primary", use_container_width=True)
    st.caption(f"주소: {url}")
else:
    st.warning(
        "새 앱 주소가 설정되지 않았습니다. 배포 후 `TRADE_WEB_URL`을 지정해주세요.\n\n"
        "- 로컬: `.streamlit/secrets.toml`에 `TRADE_WEB_URL = \"https://…\"`\n"
        "- 배포(Streamlit Cloud): 앱 Settings → Secrets에 같은 한 줄 추가\n"
        "- 로컬 개발 서버: `./scripts/run_trade_web.sh 5100` 실행 후 http://127.0.0.1:5100",
        icon="⚠️",
    )

with st.expander("이전 내역 · 롤백 방법"):
    st.markdown(
        """
**무엇이 바뀌었나** — 계산 로직(`trade_metrics.py`)과 데이터(`data/trade_dashboard/*.csv`)는
그대로 공유하고, 화면만 Flask + Chart.js로 옮겼습니다. 뷰 전환이 서버 왕복 없이 즉시
이뤄지고(Streamlit rerun 제약 해소), 지표는 서버에서 선계산해 API로 내려갑니다.

**롤백** — 기존 Streamlit 구현은 `pages/_archive/수출입_데이터.py`에 보존돼 있습니다.
이 파일과 맞바꾸면 이전 화면으로 즉시 복귀합니다.
"""
    )
