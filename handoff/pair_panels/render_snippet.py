"""렌더 스니펫 (참고) — 페어 파인더 페이지의 '페어 상세 분석' 아래에 붙여 넣는 패널 블록.

이 블록은 두 순수 함수(pair_ratio_panel·leg_technical_panel)가 반환한 dict만 소비해 차트/메트릭을 그립니다.
의존 모듈이 없으면 크래시 없이 '비활성 캡션'만 표시(방어 import).

필요 전역(페어 파인더 페이지에 이미 있는 것):
  st, go(plotly.graph_objects), pairs, sel_pair, long_ticker, long_co, short_co
필요 파일(같은 repo):
  pair_panel.py, pair_tech_panel.py (루트),  data/scorer.py 에 get_price_df(ticker)
"""

# ── 아래를 페어 파인더 페이지 끝(페어 상세 분석 블록 다음)에 그대로 붙여넣기 ──

if pairs and sel_pair:                                   # noqa: F821
    # 의존(get_price_df·pair_panel·pair_tech_panel)이 없는 환경에서도 안 깨지게 방어
    try:
        from pair_panel import pair_ratio_panel
        from pair_tech_panel import leg_technical_panel
        from data.scorer import get_price_df
    except Exception:
        pair_ratio_panel = leg_technical_panel = get_price_df = None

    _dfl = get_price_df(long_ticker) if get_price_df else None        # noqa: F821
    _dfs = get_price_df(sel_pair["t"]) if get_price_df else None      # noqa: F821

    st.write("")                                          # noqa: F821
    if pair_ratio_panel is None or get_price_df is None:
        st.info("비율선·레그별 기술 패널: 일봉 소스(get_price_df)와 pair_panel·pair_tech_panel "  # noqa: F821
                "모듈을 repo에 추가하면 활성화됩니다.", icon="📐")
    elif _dfl is None or _dfs is None:
        st.caption("⚠ 선택 페어의 일봉 데이터가 없어 패널을 그릴 수 없습니다.")    # noqa: F821
    else:
        rp = pair_ratio_panel(_dfl, _dfs, lookback=40)
        tp = leg_technical_panel(_dfl, _dfs)

        def _v(x, suf="", nd=2):
            return f"{x:.{nd}f}{suf}" if isinstance(x, (int, float)) else "—"

        # ── 비율선 패널 ──
        with st.container(border=True):                  # noqa: F821
            st.markdown("**📐 비율선 패널**  <span style='font-size:0.72rem;color:#546080'>"  # noqa: F821
                        "진입 타이밍 · 헤지 건전성</span>", unsafe_allow_html=True)
            s, cur, fl = rp["series"], rp["current"], rp["flags"]
            fig_r = go.Figure()                          # noqa: F821
            fig_r.add_trace(go.Scatter(x=s["date"], y=s["log_ratio"], name="log비율",  # noqa: F821
                                       line=dict(color="#4f8eff", width=2)))
            fig_r.add_trace(go.Scatter(x=s["date"], y=s["ma20"], name="MA20",          # noqa: F821
                                       line=dict(color="#00c87a", width=1, dash="dot")))
            fig_r.add_trace(go.Scatter(x=s["date"], y=s["ma60"], name="MA60",          # noqa: F821
                                       line=dict(color="#ffaa00", width=1, dash="dot")))
            fig_r.update_layout(height=230, margin=dict(l=40, r=20, t=8, b=30),
                                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0a0d1a",
                                font=dict(color="#dde3f8", size=10),
                                legend=dict(orientation="h", y=1.12, font=dict(size=9)),
                                xaxis=dict(gridcolor="#1c2038", color="#546080", tickfont=dict(size=9)),
                                yaxis=dict(gridcolor="#1c2038", color="#546080", tickfont=dict(size=9)))
            st.plotly_chart(fig_r, use_container_width=True, config={"displayModeBar": False})  # noqa: F821

            z = cur["zscore"]
            z_col = "#ff4060" if (isinstance(z, (int, float)) and z >= 2) else (
                    "#00c87a" if (isinstance(z, (int, float)) and z <= -2) else "#dde3f8")
            m = st.columns(5)                            # noqa: F821
            for col, lbl, val, c in [
                (m[0], "z-score", _v(z), z_col),
                (m[1], "롤링상관", _v(cur["roll_corr"]), "#00c87a" if fl["corr_ok"] else "#ff4060"),
                (m[2], "추세기울기", _v(cur["slope60"], nd=4), "#dde3f8"),
                (m[3], "반감기(일)", _v(cur["half_life"], nd=1), "#dde3f8"),
                (m[4], "헤지베타", _v(cur["roll_beta"]), "#dde3f8"),
            ]:
                with col:
                    st.markdown(f"<div style='text-align:center'><div style='font-size:0.62rem;"  # noqa: F821
                                f"color:#546080'>{lbl}</div><div style='font-size:1rem;font-weight:800;"
                                f"color:{c}'>{val}</div></div>", unsafe_allow_html=True)
            corr_txt = "상관 양호" if fl["corr_ok"] else "⚠ 상관 약화(페어 논리 주의)"
            corr_c = "#00c87a" if fl["corr_ok"] else "#ff4060"
            st.markdown(f"<div style='margin-top:8px;font-size:0.78rem'>"   # noqa: F821
                        f"<span style='color:{corr_c}'>{corr_txt}</span> &nbsp;·&nbsp; "
                        f"<span style='color:#8899bb'>{fl['z_state']}</span> &nbsp;·&nbsp; "
                        f"<span style='color:#8899bb'>{fl['trend_state']}</span></div>",
                        unsafe_allow_html=True)

        st.write("")                                     # noqa: F821
        # ── 레그별 기술 확인(발산) 패널 ──
        with st.container(border=True):                  # noqa: F821
            ds, flag = tp["divergence_score"], tp["flag"]
            ds_col = ("#00c87a" if (isinstance(ds, (int, float)) and ds >= 40) else
                      "#ff4060" if (isinstance(ds, (int, float)) and ds <= -40) else "#ffaa00")
            flag_col = ("#00c87a" if flag == "이상적 발산" else
                        "#ffaa00" if flag.startswith("페어 약함") else "#8899bb")
            st.markdown(f"<div style='display:flex;align-items:center;justify-content:space-between'>"  # noqa: F821
                        f"<span style='font-weight:700'>🔬 레그별 기술 확인</span>"
                        f"<span style='font-size:0.95rem'>발산 점수 "
                        f"<b style='color:{ds_col};font-size:1.25rem'>{_v(ds, nd=0)}</b> &nbsp;"
                        f"<b style='color:{flag_col}'>{flag}</b></span></div>", unsafe_allow_html=True)

            def _leg_card(col, title, leg, tcolor):
                with col:
                    st.markdown(f"<div style='font-size:0.72rem;color:{tcolor};letter-spacing:1px;"  # noqa: F821
                                f"margin-bottom:6px'>{title}</div>", unsafe_allow_html=True)
                    rows = [("이격도(20일)", _v(leg["disparity20"], nd=1)), ("이동평균 배열", leg["ma_stack"]),
                            ("MACD", leg["macd_state"]), ("RSI(14)", _v(leg["rsi14"], nd=1)),
                            ("거래대금추세", _v(leg["vol_trend"]))]
                    body = "".join(
                        f"<div style='display:flex;justify-content:space-between;font-size:0.8rem;"
                        f"padding:3px 0;border-bottom:1px solid #14182c'><span style='color:#546080'>{k}</span>"
                        f"<span style='color:#dde3f8;font-weight:600'>{v}</span></div>" for k, v in rows)
                    st.markdown(body, unsafe_allow_html=True)   # noqa: F821

            t1, t2 = st.columns(2, gap="medium")          # noqa: F821
            _leg_card(t1, f"LONG · {long_co['n']}", tp["long"], "#00c87a")    # noqa: F821
            _leg_card(t2, f"SHORT · {short_co['n']}", tp["short"], "#ff4060")  # noqa: F821
            st.caption("좋은 페어 = 롱 강(정배열·골든·유입) / 숏 약(역배열·데드·무거래). "  # noqa: F821
                       "둘 다 같은 방향이면 발산 0 근처 → 페어 약함. (일봉 120일이면 정/역배열 산출)")
