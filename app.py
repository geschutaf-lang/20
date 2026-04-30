import streamlit as st
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

st.set_page_config(page_title="모멘텀 전략 웹앱", layout="wide")

st.title("📈 S&P500 모멘텀 전략 자동 탐색")
st.write("버튼을 누르면 실시간으로 데이터를 수집하여 이번 달 매수 종목을 계산합니다.")

# ── 모멘텀 계산 함수 (전역 선언) ─────────────────────────────
def avg_momentum(series):
    s = series.dropna()
    if len(s) < 13:
        return np.nan, np.nan, np.nan, np.nan, np.nan
    p = s.iloc[-1]
    r1  = p / s.iloc[-2]  - 1
    r3  = p / s.iloc[-4]  - 1
    r6  = p / s.iloc[-7]  - 1
    r12 = p / s.iloc[-13] - 1
    avg = (r1 + r3 + r6 + r12) / 4
    return avg, r1, r3, r6, r12

# ── S&P500 종목 목록 수집 ────────────────────────────────────
@st.cache_data(ttl=86400)  # 하루 1번만 새로 조회 (속도 개선)
def get_sp500_tickers():
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(url, headers=headers, timeout=15)
    soup = BeautifulSoup(resp.text, 'html.parser')
    table = soup.find('table', {'id': 'constituents'})
    sp_rows = table.find_all('tr')[1:] 
    tickers = [
        row.find_all('td')[0].text.strip().replace('.', '-')
        for row in sp_rows if row.find_all('td')
    ]
    return tickers

# ── 시총 상위 N개 선별 ────────────────────────────────────────
def get_top_n_by_marketcap(tickers, n=20, progress_bar=None):
    """
    전체 S&P500 종목을 배치로 조회해 시총 상위 N개 반환
    """
    market_caps = {}
    total = len(tickers)

    for i, tk in enumerate(tickers):
        if progress_bar is not None:
            progress_bar.progress(
                (i + 1) / total,
                text=f"시총 조회 중... {i+1}/{total} ({tk})"
            )
        try:
            info = yf.Ticker(tk).fast_info
            mc = getattr(info, 'market_cap', None)
            if mc and mc > 0:
                market_caps[tk] = mc
        except Exception:
            pass

    if len(market_caps) < n:
        # 폴백: API 실패 시 검증된 대형주 목록 사용
        fallback = [
            'AAPL','MSFT','NVDA','AMZN','GOOGL',
            'META','TSLA','BRK-B','LLY','JPM',
            'V','UNH','XOM','MA','AVGO',
            'PG','JNJ','HD','MRK','COST'
        ]
        return fallback[:n], market_caps

    top_n = sorted(market_caps, key=market_caps.get, reverse=True)[:n]
    return top_n, market_caps


if st.button("🚀 전략 실행 및 결과 보기"):

    TOP_N      = 20
    TIP_TICKER = 'TIP'

    # ── Step 1: S&P500 종목 목록 ─────────────────────────────
    with st.status("📋 S&P500 종목 목록 수집 중...") as status:
        try:
            all_sp500 = get_sp500_tickers()
            st.write(f"✅ S&P500 구성 종목 {len(all_sp500)}개 확인")
        except Exception as e:
            st.error(f"종목 목록 수집 실패: {e}")
            st.stop()

        # ── Step 2: 시총 상위 20개 선별 ──────────────────────
        st.write("📊 시총 조회 중... (전체 종목 대상, 약 2~3분 소요)")
        prog = st.progress(0, text="시총 조회 준비 중...")
        try:
            top20, market_caps = get_top_n_by_marketcap(all_sp500, TOP_N, prog)
            prog.empty()
            st.write(f"✅ 시총 상위 {TOP_N}개 선별 완료: {', '.join(top20)}")
        except Exception as e:
            prog.empty()
            st.error(f"시총 조회 실패: {e}")
            st.stop()

        # ── Step 3: 주가 데이터 수집 ─────────────────────────
        st.write("📡 주가 데이터 수집 중 (14개월)...")
        try:
            end_date   = datetime.today()
            start_date = end_date - timedelta(days=430)
            raw = yf.download(
                top20 + [TIP_TICKER],
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d'),
                auto_adjust=True,
                progress=False
            )
            # ✅ yfinance 멀티인덱스 안전 처리
            if isinstance(raw.columns, pd.MultiIndex):
                if 'Close' in raw.columns.levels[0]:
                    prices = raw['Close']
                else:
                    prices = raw.xs('Close', axis=1, level=1)
            else:
                prices = raw[['Close']]

            monthly = prices.resample('ME').last()
            st.write(f"✅ {len(monthly)}개월치 주가 수집 완료")
        except Exception as e:
            st.error(f"주가 데이터 수집 실패: {e}")
            st.stop()

        # ── Step 4: 모멘텀 계산 ───────────────────────────────
        st.write("🧮 모멘텀 계산 중...")

        # TIP 필터 판정
        tip_avg, tip_r1, tip_r3, tip_r6, tip_r12 = avg_momentum(monthly[TIP_TICKER])
        tip_pass = (not np.isnan(tip_avg)) and (tip_avg > 0)

        # 종목별 모멘텀
        momentum_rows = []
        for tk in top20:
            if tk not in monthly.columns:
                continue
            m_avg, r1, r3, r6, r12 = avg_momentum(monthly[tk])
            # ✅ NaN 안전 처리
            if any(np.isnan(v) for v in [m_avg, r1, r3, r6, r12]):
                continue
            momentum_rows.append({
                '종목':          tk,
                '1M(%)':        round(r1  * 100, 2),
                '3M(%)':        round(r3  * 100, 2),
                '6M(%)':        round(r6  * 100, 2),
                '12M(%)':       round(r12 * 100, 2),
                '평균모멘텀(%)': round(m_avg * 100, 2),
                '시가총액':      f"${market_caps.get(tk,0)/1e12:.2f}T"
                                 if market_caps.get(tk,0) >= 1e12
                                 else f"${market_caps.get(tk,0)/1e9:.0f}B",
            })

        df_rank = (
            pd.DataFrame(momentum_rows)
            .sort_values('평균모멘텀(%)', ascending=False)
            .reset_index(drop=True)
        )
        df_rank.index += 1
        status.update(label="✅ 계산 완료!", state="complete")

    # ── 결과 출력 ─────────────────────────────────────────────
    st.subheader("📊 전략 결과 요약")

    col1, col2, col3 = st.columns(3)
    col1.metric("TIP 모멘텀",   f"{tip_avg*100:.2f}%", "PASS ✅" if tip_pass else "BLOCK 🚫")
    col2.metric("조회 종목 수", f"{len(df_rank)}개")
    col3.metric("기준일",       datetime.today().strftime('%Y-%m-%d'))

    if tip_pass:
        best = df_rank.iloc[0]
        st.success(f"✅ TIP 필터 통과! (TIP 평균 모멘텀: {tip_avg*100:.2f}%)")
        st.info(
            f"🎯 **이번 달 추천 매수 종목: {best['종목']}**  "
            f"(평균 모멘텀: {best['평균모멘텀(%)']:+.2f}%  |  시총: {best['시가총액']})"
        )
    else:
        st.error(
            f"🚫 TIP 필터 차단 (TIP 평균 모멘텀: {tip_avg*100:.2f}%)  "
            f"→ **이번 달은 전량 현금 보유하세요!**"
        )

    st.subheader("🏆 모멘텀 순위표")
    # 양수/음수에 따라 색상 적용
    def color_momentum(val):
        if isinstance(val, (int, float)):
            color = '#39d98a' if val >= 0 else '#ff4757'
            return f'color: {color}'
        return ''

    styled = df_rank.style.applymap(
        color_momentum,
        subset=['1M(%)','3M(%)','6M(%)','12M(%)','평균모멘텀(%)']
    )
    st.dataframe(styled, use_container_width=True)

    st.subheader("📈 평균 모멘텀 순위 차트")
    chart_data = df_rank.set_index('종목')[['평균모멘텀(%)']].sort_values('평균모멘텀(%)')
    st.bar_chart(chart_data)
