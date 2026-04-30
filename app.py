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

# ── 모멘텀 계산 함수 ─────────────────────────────
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
@st.cache_data(ttl=86400)
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
        fallback = ['AAPL','MSFT','NVDA','AMZN','GOOGL','META','TSLA','BRK-B','LLY','JPM',
                    'V','UNH','XOM','MA','AVGO','PG','JNJ','HD','MRK','COST']
        return fallback[:n], market_caps

    top_n = sorted(market_caps, key=market_caps.get, reverse=True)[:n]
    return top_n, market_caps

# ── 메인 실행 부분 ────────────────────────────────────────
if st.button("🚀 전략 실행 및 결과 보기"):

    TOP_N = 20
    TIP_TICKER = 'TIP'

    with st.status("📋 데이터 수집 및 연산 중... (약 1~2분 소요됩니다)") as status:
        
        all_sp500 = get_sp500_tickers()
        
        prog = st.progress(0, text="시총 상위 종목 선별 중...")
        top20, market_caps = get_top_n_by_marketcap(all_sp500, TOP_N, prog)
        prog.empty()
        
        end_date   = datetime.today()
        start_date = end_date - timedelta(days=430)
        
        raw = yf.download(
            top20 + [TIP_TICKER],
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            auto_adjust=False, 
            progress=False
        )
        
        # 🚨 구조 변경/에러 완벽 방어 구간
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                prices = raw['Adj Close'] if 'Adj Close' in raw.columns.levels[0] else raw['Close']
            else:
                prices = raw[['Adj Close']] if 'Adj Close' in raw.columns else raw[['Close']]
        except:
            st.error("야후 파이낸스에서 주가 데이터를 거절했습니다. 몇 분 뒤에 다시 시도해주세요.")
            st.stop()

        if TIP_TICKER not in prices.columns:
            st.error("TIP 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
            st.stop()

        monthly = prices.resample('ME').last()
        
        tip_avg, tip_r1, tip_r3, tip_r6, tip_r12 = avg_momentum(monthly[TIP_TICKER])
        tip_pass = (not np.isnan(tip_avg)) and (tip_avg > 0)

        momentum_rows = []
        for tk in top20:
            if tk not in monthly.columns:
                continue
            m_avg, r1, r3, r6, r12 = avg_momentum(monthly[tk])
            if any(np.isnan(v) for v in [m_avg, r1, r3, r6, r12]):
                continue
            
            mc_val = market_caps.get(tk, 0)
            mc_str = f"${mc_val/1e12:.2f}T" if mc_val >= 1e12 else f"${mc_val/1e9:.0f}B"
            
            momentum_rows.append({
                '종목':          tk,
                '1M(%)':        round(r1  * 100, 2),
                '3M(%)':        round(r3  * 100, 2),
                '6M(%)':        round(r6  * 100, 2),
                '12M(%)':       round(r12 * 100, 2),
                '평균모멘텀(%)': round(m_avg * 100, 2),
                '시가총액':      mc_str,
            })

        df_rank = pd.DataFrame(momentum_rows)
        if not df_rank.empty:
            df_rank = df_rank.sort_values('평균모멘텀(%)', ascending=False).reset_index(drop=True)
            df_rank.index += 1
        
        status.update(label="✅ 계산 완료!", state="complete")

    # ── 화면에 보여주기 ─────────────────────────────────────────────
    st.subheader("📊 전략 결과 요약")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("TIP 모멘텀", f"{tip_avg*100:.2f}%" if not np.isnan(tip_avg) else "확인 불가", "PASS ✅" if tip_pass else "BLOCK 🚫")
    col2.metric("조회 종목 수", f"{len(df_rank)}개")
    col3.metric("기준일", datetime.today().strftime('%Y-%m-%d'))

    if not df_rank.empty:
        if tip_pass:
            best = df_rank.iloc[0]
            st.success("✅ 이번 달 투자를 진행합니다 (TIP 필터 통과)")
            st.info(f"🎯 **1위 종목 매수 추천: {best['종목']}**  (평균 모멘텀: {best['평균모멘텀(%)']:+.2f}%)")
        else:
            st.error("🚫 하락장 위험 (TIP 필터 차단됨) → **이번 달은 주식을 팔고 전량 달러(현금)를 보유하세요!**")

        st.subheader("🏆 모멘텀 순위표 (색칠 기능 제거하여 안정화)")
        # 표 그리는 부분 (색칠 코드를 완전히 빼서 무조건 뜨도록 만듦)
        st.dataframe(df_rank, use_container_width=True)

        st.subheader("📈 평균 모멘텀 차트")
        chart_data = df_rank.set_index('종목')[['평균모멘텀(%)']].sort_values('평균모멘텀(%)')
        st.bar_chart(chart_data)
    else:
        st.error("🚨 종목 데이터를 충분히 불러오지 못했습니다. 야후 서버 문제일 수 있으니 새로고침 후 다시 눌러보세요.")
