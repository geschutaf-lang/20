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

if st.button("🚀 전략 실행 및 결과 보기"):
    with st.spinner("데이터를 수집하고 계산하는 중입니다... (약 1분 정도 소요됩니다)"):
        # 1. 상위 20개 종목 수집
        TOP_N = 20
        TIP_TICKER = 'TIP'
        
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table', {'id': 'constituents'})
        rows = table.find_all('tr')[1:]
        tickers = [row.find_all('td')[0].text.strip().replace('.', '-') for row in rows if row.find_all('td')]
        
        market_caps = {}
        for tk in tickers[:50]: # 빠른 실행을 위해 상위 50개만 우선 체크
            try:
                info = yf.Ticker(tk).fast_info
                mc = getattr(info, 'market_cap', None)
                if mc and mc > 0:
                    market_caps[tk] = mc
            except:
                pass
                
        top20 = sorted(market_caps, key=market_caps.get, reverse=True)[:TOP_N]
        
        # 2. 데이터 수집
        end_date = datetime.today()
        start_date = end_date - timedelta(days=430)
        all_tickers = top20 + [TIP_TICKER]
        
        raw = yf.download(all_tickers, start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'), auto_adjust=True, progress=False)
        prices = raw['Close']
        monthly = prices.resample('ME').last()
        
        # 3. 모멘텀 계산 함수
        def avg_momentum(series):
            s = series.dropna()
            if len(s) < 13: return np.nan, np.nan, np.nan, np.nan, np.nan
            p = s.iloc[-1]
            r1 = p / s.iloc[-2] - 1
            r3 = p / s.iloc[-4] - 1
            r6 = p / s.iloc[-7] - 1
            r12 = p / s.iloc[-13] - 1
            return (r1 + r3 + r6 + r12) / 4, r1, r3, r6, r12

        # 4. 결과 계산
        tip_avg, tip_r1, tip_r3, tip_r6, tip_r12 = avg_momentum(monthly[TIP_TICKER])
        tip_pass = (not np.isnan(tip_avg)) and tip_avg > 0

        rows = []
        for tk in top20:
            if tk not in monthly.columns: continue
            avg, r1, r3, r6, r12 = avg_momentum(monthly[tk])
            rows.append({
                '종목': tk,
                '1M(%)': round(r1*100, 2), '3M(%)': round(r3*100, 2),
                '6M(%)': round(r6*100, 2), '12M(%)': round(r12*100, 2),
                '평균모멘텀(%)': round(avg*100, 2)
            })

        df_rank = pd.DataFrame(rows).dropna().sort_values('평균모멘텀(%)', ascending=False).reset_index(drop=True)
        df_rank.index += 1

        # 5. 화면에 출력하기
        st.subheader("📊 전략 결과 요약")
        if tip_pass:
            best = df_rank.iloc[0]
            st.success(f"✅ TIP 필터 통과! (TIP 모멘텀: {tip_avg*100:.2f}%)")
            st.info(f"🎯 **이번 달 추천 매수 종목: {best['종목']}** (평균 모멘텀: {best['평균모멘텀(%)']:.2f}%)")
        else:
            st.error(f"🚫 TIP 필터 차단 (TIP 모멘텀: {tip_avg*100:.2f}%) → **이번 달은 전량 현금 보유하세요!**")

        st.subheader("🏆 S&P500 시총 상위 모멘텀 순위")
        st.dataframe(df_rank, use_container_width=True)
        
        st.subheader("📈 모멘텀 차트")
        chart_data = df_rank.set_index("종목")[["평균모멘텀(%)"]]
        st.bar_chart(chart_data)
