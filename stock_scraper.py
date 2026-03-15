import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import google.generativeai as genai
import time
import io
import re

# ==========================================
# 0. 系統說明與彈跳視窗
# ==========================================
@st.dialog("🧠 系統運算邏輯大解密")
def show_logic_explanation():
    st.markdown("""
    ### 1. 歷史達標率 (Monte Carlo 滾動回測)
    這不是預測未來，而是告訴您歷史的真實機率：系統提取歷史 K 線，依照您設定的「回測天數」進行「每日滾動模擬」。
    
    ### 2. 潛伏雷達 (量價異常偵測)
    尋找「聰明錢」的足跡：
    * **底部盤整**：股價距離季線 (長期均線) 乖離率介於 -5% 到 +15% 之間（沒有漲上天）。
    * **偷吃貨爆量**：近 5 日平均成交量，比過去 20 日平均量放大超過 1.2 倍以上。
    """)
    if st.button("了解，關閉視窗"):
        st.rerun()

# ==========================================
# 1. 系統常數與大師設定
# ==========================================
teacher_chu = """【朱家泓 - 飆股戰法】看重動能。股價需站上短期均線且RSI>50。嚴格以短期均線停損。基本面非重點。"""
teacher_lin = """【林恩如 - 均線大趨勢】只吃主升段。股價需站上長期均線與200MA。跌破長期均線停損。若本益比合理是加分項。"""
teacher_chen = """【價值存股派 - 逢低佈局】越跌越買。極度看重「殖利率(>4%)」與「本益比(<15)」。股價在均線下且RSI<40為佳。嚴格分批，不停損。"""

strategies = {
    "朱家泓 (短波段動能 / 嚴格停損)": teacher_chu,
    "林恩如 (長線大趨勢 / 抱緊處理)": teacher_lin,
    "價值存股派 (看重本益比與殖利率)": teacher_chen
}

TW_STOCK_MAP = {
    "台積電": "2330", "鴻海": "2317", "聯發科": "2454", "廣達": "2382", "緯創": "3231",
    "華碩": "2357", "宏碁": "2353", "微星": "2377", "技嘉": "2376", "奇鋐": "3017",
    "雙鴻": "3324", "台光電": "2383", "日月光": "3711", "聯電": "2303", "聯詠": "3034",
    "瑞昱": "2379", "智邦": "2345", "緯穎": "6669", "大立光": "3008", "欣興": "3037",
    "台達電": "2308", "光寶科": "2301", "研華": "2395", "川湖": "2059", "嘉澤": "3533",
    "長榮": "2603", "陽明": "2609", "萬海": "2615", "華城": "1519", "士電": "1503",
    "中興電": "1513", "亞力": "1514", "台泥": "1101", "亞泥": "1102", "中鋼": "2002",
    "統一": "1216", "統一超": "2912", "和泰車": "2207", "儒鴻": "1476", "聚陽": "1477",
    "富邦金": "2881", "國泰金": "2882", "兆豐金": "2886", "中信金": "2891", "玉山金": "2884", 
    "元大金": "2885", "第一金": "2892", "合庫金": "5880", "華南金": "2880", "開發金": "2883",
    "台新金": "2887", "彰銀": "2801", "永豐金": "2890", "中華電": "2412", "台灣大": "3045", "遠傳": "4904",
    "國泰永續高股息": "00878", "元大高股息": "0056", "群益台灣精選高息": "00919",
    "元大台灣高息低波": "00713", "元大台灣50": "0050", "富邦台50": "006208"
}
REVERSE_MAP = {v: k for k, v in TW_STOCK_MAP.items()}

STOCK_UNIVERSES = {
    "🔥 科技權值與強勢動能池 (掃描 30 檔科技巨頭)": {
        "tickers": ["2330", "2317", "2454", "2382", "3231", "2357", "2353", "2377", "2376", "3017", 
                    "3324", "2383", "3711", "2303", "3034", "2379", "2345", "6669", "3008", "3037", 
                    "2308", "2301", "2395", "2059", "3533", "2603", "1519", "1503", "1513", "1514"],
        "desc": "尋找目前站上短期均線且 RSI 動能強勁的標的。"
    },
    "💰 穩健存股與避險價值池 (掃描 25 檔金融與傳產)": {
        "tickers": ["2881", "2882", "2886", "2891", "2884", "2885", "2892", "5880", "2880", "2883", 
                    "2887", "2801", "2890", "2412", "3045", "4904", "1101", "1102", "2002", "1216", 
                    "2912", "00878", "0056", "00919", "00713"],
        "desc": "尋找殖利率高，且目前 RSI 相對較低、適合分批存股的標的。"
    }
}

def parse_stock_input(user_input):
    user_input = str(user_input).strip()
    if user_input in TW_STOCK_MAP:
        ticker = TW_STOCK_MAP[user_input]
    else:
        ticker = user_input.upper().replace(".TW", "").replace(".TWO", "")
    yf_ticker = f"{ticker}.TW"
    return ticker, yf_ticker

# ==========================================
# 2. 核心數據引擎
# ==========================================
@st.cache_data(ttl=3600)
def fetch_basic_info(user_input, short_ma):
    try:
        ticker, yf_ticker = parse_stock_input(user_input)
        stock = yf.Ticker(yf_ticker)
        df = stock.history(period="6mo")
        if df.empty: return None
        
        info = stock.info
        company_name = REVERSE_MAP.get(ticker, info.get('shortName', '未知名稱'))
        display_name = f"{company_name} ({ticker})"
        
        current_price = df['Close'].iloc[-1]
        df[f'{short_ma}MA'] = df['Close'].rolling(window=short_ma).mean()
        delta = df['Close'].diff()
        rs = (delta.where(delta > 0, 0)).rolling(window=14).mean() / (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi = 100 - (100 / (1 + rs)).iloc[-1]
        
        pe_ratio = info.get('trailingPE', 0)
        past_year_divs = stock.dividends[stock.dividends.index > (pd.Timestamp.now(tz=stock.dividends.index.tz) - pd.Timedelta(days=365))]
        div_yield = (past_year_divs.sum() / current_price) * 100 if current_price > 0 and not past_year_divs.empty else 0
        
        trend_vector = f"🟢 偏多 (站上 {short_ma}MA)" if current_price > df[f'{short_ma}MA'].iloc[-1] else f"🔴 偏空"
        rsi_vector = "🔥 過熱" if rsi > 70 else ("❄️ 超賣" if rsi < 30 else "🟡 整理中")
        
        return {
            "代號": ticker, "標的名稱": display_name, "收盤價": round(current_price, 2),
            f"{short_ma}MA": round(df[f'{short_ma}MA'].iloc[-1], 2), "RSI指標": round(rsi, 2),
            "本益比": round(pe_ratio, 2), "殖利率估算(%)": round(div_yield, 2),
            "趨勢向量": trend_vector, "動能狀態": rsi_vector
        }
    except:
        return None

def analyze_stock(user_input, target_months, target_return, short_ma, long_ma, backtest_days):
    ticker, yf_ticker = parse_stock_input(user_input)
    stock = yf.Ticker(yf_ticker)
    df = stock.history(period="5y")
    if df.empty or len(df) < 200: return None, None
    try:
        info = stock.info
        pe_ratio = info.get('trailingPE', 0)
        past_year_divs = stock.dividends[stock.dividends.index > (pd.Timestamp.now(tz=stock.dividends.index.tz) - pd.Timedelta(days=365))]
        total_div = past_year_divs.sum() if not past_year_divs.empty else 0
        company_name = REVERSE_MAP.get(ticker, info.get('shortName', '未知名稱'))
        display_name = f"{company_name} ({ticker})"
    except:
        pe_ratio = total_div = 0
        display_name = f"未知名稱 ({ticker})"
        
    current_price = df['Close'].iloc[-1]
    prev_price = df['Close'].iloc[-2]
    pct_change = ((current_price - prev_price) / prev_price) * 100
    div_yield = (total_div / current_price) * 100 if current_price > 0 else 0

    df[f'{short_ma}MA'] = df['Close'].rolling(window=short_ma).mean()
    df[f'{long_ma}MA'] = df['Close'].rolling(window=long_ma).mean()
    df['200MA'] = df['Close'].rolling(window=200).mean()
    
    delta = df['Close'].diff()
    rs = (delta.where(delta > 0, 0)).rolling(window=14).mean() / (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 計算歷史達標率
    df_backtest = df.tail(backtest_days)
    horizon_days = int(target_months * 20) 
    
    if backtest_days <= horizon_days:
        prob_success = -1
        prob_loss = -1
    else:
        valid_returns = df_backtest['Close'].pct_change(periods=horizon_days).dropna()
        prob_success = (valid_returns >= (target_return / 100)).mean() * 100 if not valid_returns.empty else 0
        prob_loss = (valid_returns < 0).mean() * 100 if not valid_returns.empty else 0
    
    data_dict = {
        "ticker": ticker, "display_name": display_name, "current_price": current_price, "pct_change": pct_change, 
        "pe_ratio": pe_ratio, "div_yield": div_yield, 
        f"{short_ma}MA": df[f'{short_ma}MA'].iloc[-1], f"{long_ma}MA": df[f'{long_ma}MA'].iloc[-1], 
        "RSI": df['RSI'].iloc[-1], "prob_success": prob_success, "prob_loss": prob_loss
    }
    return data_dict, df

def render_stock_card(data, df, short_ma, long_ma, backtest_days):
    st.header(f"📌 {data['display_name']}")
    col1, col2 = st.columns(2)
    col1.metric("最新收盤價", f"{data['current_price']:.2f}", f"{data['pct_change']:.2f}%")
    
    if data['prob_success'] == -1:
        col2.metric("🎯 歷史達標率", "時間衝突", "請增加回測天數或減少目標時間", delta_color="off")
    else:
        col2.metric(f"🎯 歷史達標率 ({backtest_days}天內)", f"{data['prob_success']:.2f}%")
    
    df_plot = df.tail(max(backtest_days, 150)) 
    
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name="K線"))
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot[f'{short_ma}MA'], mode='lines', line=dict(color='orange'), name=f'{short_ma}MA'))
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot[f'{long_ma}MA'], mode='lines', line=dict(color='blue'), name=f'{long_ma}MA'))
    fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)
    
    stats_df = pd.DataFrame([{
        "本益比": f"{data['pe_ratio']:.2f}" if data['pe_ratio'] > 0 else "N/A",
        "殖利率": f"{data['div_yield']:.2f}%", 
        "RSI": f"{data['RSI']:.2f}"
    }])
    st.dataframe(stats_df, hide_index=True)

def import_to_pk_callback(selected_names, names_list, codes_list):
    st.session_state.t1 = st.session_state.t2 = st.session_state.t3 = st.session_state.t4 = ""
    for i, selected_name in enumerate(selected_names):
        idx = names_list.index(selected_name)
        st.session_state[f"t{i+1}"] = codes_list[idx]

# ==========================================
# 3. 網頁記憶體初始化
# ==========================================
if 'stock_results' not in st.session_state: 
    st.session_state.stock_results = []
if 'radar_top_10' not in st.session_state: 
    st.session_state.radar_top_10 = None
if 'radar_pool_name' not in st.session_state: 
    st.session_state.radar_pool_name = ""
if "chat_messages" not in st.session_state: 
    st.session_state.chat_messages = [{"role": "assistant", "content": "你好！我是您的專屬 AI 交易顧問。您可以詢問我關於標的、PK擂台或體質健檢的問題！"}]
if "prediction_result" not in st.session_state: 
    st.session_state.prediction_result = ""
if "predicted_tickers" not in st.session_state: 
    st.session_state.predicted_tickers = []

for i in range(1, 5):
    if f't{i}' not in st.session_state:
        st.session_state[f't{i}'] = "台積電" if i == 1 else ""

# ==========================================
# 4. 網頁介面設計 (側邊欄)
# ==========================================
st.set_page_config(page_title="AI 量化旗艦系統", layout="wide", page_icon="📈")

with st.sidebar:
    st.title("⚙️ 控制中心")
    st.markdown("---")
    st.subheader("🔑 AI 大腦連線設定")
    user_api_key = st.text_input("輸入您的 Gemini API Key：", type="password")
    
    st.markdown("---")
    st.subheader("🛠️ 專業級動態參數設定")
    short_ma = st.number_input("短期均線 (防守/上緣)：", min_value=5, value=20, step=1)
    long_ma = st.number_input("長期均線 (趨勢/下緣)：", min_value=10, value=60, step=1)
    backtest_days = st.number_input("歷史勝率回測天數：", min_value=30, value=365, step=10)

    st.markdown("---")
    st.subheader("🥊 PK 擂台名單")
    t1 = st.text_input("🟢 選手 1 (必填)：", key="t1")
    t2 = st.text_input("⚪ 選手 2 (選填)：", key="t2")
    t3 = st.text_input("⚪ 選手 3 (選填)：", key="t3")
    t4 = st.text_input("⚪ 選手 4 (選填)：", key="t4")
    
    st.markdown("---")
    st.subheader("💰 資金與目標")
    investment_amount = st.number_input("預算 (台幣)：", min_value=1000, value=300000, step=10000)
    target_return = st.number_input("目標 (%)：", value=10.0, step=0.5)
    target_months = st.number_input("時間 (個月)：", min_value=1, value=6, step=1)
    
    st.markdown("---")
    options_list = list(strategies.keys()) + ["💡 自訂大師 (手動輸入)"]
    selected_teacher_name = st.selectbox("🧑‍⚖️ 選擇評比大師：", options=options_list)
    
    if selected_teacher_name == "💡 自訂大師 (手動輸入)":
        selected_logic = st.text_area("自訂邏輯：", value=f"必須站上 {short_ma}MA，且殖利率大於 5%。")
        teacher_prompt_name = "我的自訂量化策略"
    else:
        selected_logic = strategies[selected_teacher_name]
        teacher_prompt_name = selected_teacher_name
    
    fetch_button = st.button("📊 抓取 PK 名單最新圖表", use_container_width=True)
    
    if st.button("📖 系統運算邏輯大解密", icon="ℹ️", use_container_width=True):
        show_logic_explanation()

# ==========================================
# 5. 主畫面：五大分頁設計
# ==========================================
tab_radar, tab_pk, tab_health, tab_chat, tab_predict = st.tabs([
    "🚀 1. 智慧策略選股", 
    "⚔️ 2. PK 擂台", 
    "📂 3. 體質健檢", 
    "💬 4. 顧問對話室", 
    "🔮 5. 產業推演與潛伏雷達"  
])

# ----------------------------------------
# 分頁 1: 智慧雷達
# ----------------------------------------
with tab_radar:
    st.header("🚀 智慧選股雷達與戰力向量表")
    selected_pool_name = st.selectbox("選擇掃描策略池：", list(STOCK_UNIVERSES.keys()))
    
    if st.button("📡 啟動策略池深度掃描", type="primary"):
        pool_tickers = STOCK_UNIVERSES[selected_pool_name]["tickers"]
        results = []
        my_bar = st.progress(0, text="純量化演算法掃描中...")
        for i, t in enumerate(pool_tickers):
            my_bar.progress((i + 1) / len(pool_tickers), text=f"正在掃描: {t}")
            data = fetch_basic_info(t, short_ma)
            if data:
                results.append(data)
            time.sleep(0.05) 
        my_bar.empty()
        
        if results:
            df_results = pd.DataFrame(results)
            if "強勢" in selected_pool_name:
                df_results = df_results[df_results['收盤價'] > df_results[f'{short_ma}MA']]
                df_results = df_results.sort_values(by='RSI指標', ascending=False)
            else:
                df_results = df_results.sort_values(by='殖利率估算(%)', ascending=False)
            
            st.session_state.radar_top_10 = df_results.head(10)
            st.session_state.radar_pool_name = selected_pool_name

    if st.session_state.radar_top_10 is not None:
        top_10 = st.session_state.radar_top_10
        pool_name = st.session_state.radar_pool_name
        
        st.success("✅ 掃描完成！以下是目前最符合策略的潛力名單：")
        st.subheader("📋 Top 10 動能向量表")
        display_cols = ['標的名稱', '收盤價', '趨勢向量', '動能狀態', 'RSI指標', '本益比', '殖利率估算(%)']
        st.dataframe(top_10[display_cols], hide_index=True, use_container_width=True)
        
        st.subheader("🕸️ Top 4 綜合戰力雷達圖")
        top_4_radar = top_10.head(4)
        fig_radar = go.Figure()
        categories = ['動能爆發(RSI)', '價值保護(PE)', '防禦收息(殖利率)', f'乖離率({short_ma}MA)']
        
        for index, row in top_4_radar.iterrows():
            rsi_score = row['RSI指標']
            pe = row['本益比']
            pe_score = max(0, min(100, 100 - (pe / 30 * 100))) if pe > 0 else 0
            dy = row['殖利率估算(%)']
            dy_score = min(100, dy * 10)
            bias = (row['收盤價'] - row[f'{short_ma}MA']) / row[f'{short_ma}MA'] * 100
            bias_score = max(0, min(100, (bias + 10) * 5))
            fig_radar.add_trace(go.Scatterpolar(
                r=[rsi_score, pe_score, dy_score, bias_score, rsi_score], 
                theta=categories + [categories[0]], fill='toself', name=row['標的名稱']
            ))
            
        fig_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100])), showlegend=True, height=450)
        st.plotly_chart(fig_radar, use_container_width=True)
        
        st.markdown("---")
        st.subheader("🤖 需要第二意見？")
        if st.button("點我呼叫 AI 生成這 10 檔標的的洞察報告"):
            if not user_api_key: 
                st.error("🚨 請先在左側輸入您的 API Key。")
            else:
                with st.spinner("AI 大師正在解讀名單..."):
                    try:
                        genai.configure(api_key=user_api_key)
                        model = genai.GenerativeModel('gemini-2.5-flash')
                        insight_prompt = f"雷達掃描出這10名標的：\n{top_10[display_cols].to_string()}\n請用150字說明共通點及風險。"
                        st.info(model.generate_content(insight_prompt).text)
                    except Exception as e: 
                        st.error(f"錯誤訊息：{e}")
        
        st.markdown("---")
        st.subheader("📥 將標的送入 PK 擂台")
        top_tickers_names = top_10['標的名稱'].tolist()
        top_tickers_codes = top_10['代號'].tolist()
        selected_to_arena = st.multiselect("選擇參賽選手 (最多 4 名)：", options=top_tickers_names, default=top_tickers_names[:2], max_selections=4)
        
        st.button(
            "一鍵將勾選名單匯入左側【PK 擂台】", 
            type="primary", 
            key="btn_import_pk", 
            on_click=import_to_pk_callback, 
            args=(selected_to_arena, top_tickers_names, top_tickers_codes)
        )

# ----------------------------------------
# 分頁 2: PK 對戰台
# ----------------------------------------
with tab_pk:
    if fetch_button:
        raw_inputs = [st.session_state.t1, st.session_state.t2, st.session_state.t3, st.session_state.t4]
        valid_tickers = [t.strip() for t in raw_inputs if t.strip()]
        
        if not valid_tickers:
            st.error("請在左側至少輸入一檔股票名稱或代號！")
        else:
            with st.spinner("正在為 PK 名單抓取深度數據..."):
                # 🌟 這裡就是修正 NameError 的清爽標準寫法！
                results = []
                for t in valid_tickers:
                    data, df = analyze_stock(t, target_months, target_return, short_ma, long_ma, backtest_days)
                    if data is not None:
                        results.append({"data": data, "df": df})
                st.session_state.stock_results = results

    results = st.session_state.stock_results
    num_stocks = len(results)

    if num_stocks > 0:
        st.header(f"📊 動態數據看板 ({num_stocks} 檔標的)")
        
        if num_stocks == 1: 
            render_stock_card(results[0]["data"], results[0]["df"], short_ma, long_ma, backtest_days)
        else:
            for i in range(0, num_stocks, 2):
                cols = st.columns(2)
                with cols[0]: 
                    render_stock_card(results[i]["data"], results[i]["df"], short_ma, long_ma, backtest_days)
                if i + 1 < num_stocks:
                    with cols[1]: 
                        render_stock_card(results[i+1]["data"], results[i+1]["df"], short_ma, long_ma, backtest_days)
                        
        st.markdown("---")
        if st.button("🧠 呼叫 AI 大師進行終極資金配置", type="primary", use_container_width=True):
            if not user_api_key: 
                st.error("🚨 請先在左側輸入 API Key。")
            else:
                with st.spinner("大師深思熟慮中..."):
                    try:
                        genai.configure(api_key=user_api_key)
                        model = genai.GenerativeModel('gemini-2.5-flash')
                        
                        data_strings = []
                        headers = ["評估項目"]
                        for i, res in enumerate(results):
                            d = res["data"]
                            prob_text = "衝突" if d['prob_success'] == -1 else f"{d['prob_success']:.2f}%"
                            data_strings.append(f"【標的 {i+1} ({d['display_name']})】：收盤:{d['current_price']:.2f} | PE:{d['pe_ratio']:.2f} | {short_ma}MA:{d[f'{short_ma}MA']:.2f} | {long_ma}MA:{d[f'{long_ma}MA']:.2f} | 達標率:{prob_text}")
                            headers.append(f"標的 {i+1}<br>({d['display_name']})")
                            
                        all_data_text = "\n".join(data_strings)
                        md_table_header = "| " + " | ".join(headers) + " |\n| " + " | ".join([":---"] * len(headers)) + " |"
                        task = "這是一檔單獨的股票分析，請評估是否值得買進。" if num_stocks == 1 else "這是一場 PK 賽，請明確宣告資金該如何分配？"
                        
                        prompt = f"""
                        你是台灣股市權威：{teacher_prompt_name}。核心邏輯：{selected_logic}。
                        總預算：{investment_amount}。資料如下：\n{all_data_text}\n{task}
                        
                        請輸出：
                        ### 🏆 大師總評
                        
                        ### 💰 資金配置與行動建議表
                        {md_table_header}
                        | **技術與基本面(短評)** | (填寫) |
                        | **防守停損價位** | (填寫) |
                        | **最終資金配置** | (填寫) |
                        """
                        st.markdown(model.generate_content(prompt).text)
                    except Exception as e: 
                        st.error(f"錯誤：{e}")

# ----------------------------------------
# 分頁 3: 交易體質健檢 
# ----------------------------------------
with tab_health:
    st.header("📂 歷史交易體質大健檢")
    st.markdown("上傳您的真實歷史對帳單，讓 AI 大師來幫您「抓漏」！")
    
    st.info("💡 **小提醒**：請確保您的 CSV 檔案包含以下欄位名稱：`股票名稱`, `買入日期`, `賣出日期`, `買入價`, `賣出價`, `股數`")
    sample_csv_text = "股票名稱,買入日期,賣出日期,買入價,賣出價,股數\n台積電,2023-05-01,2023-06-10,500,580,1000\n長榮,2023-07-01,2023-07-15,120,110,2000\n富邦金,2023-08-01,2023-12-01,60,65,3000"
    sample_csv_bytes = sample_csv_text.encode('utf-8-sig')
    st.download_button(label="📥 下載標準 CSV 測試範本檔", data=sample_csv_bytes, file_name="sample_trades.csv", mime="text/csv")
    
    st.markdown("---")
    uploaded_file = st.file_uploader("上傳您的 CSV 交易紀錄：", type=["csv"])
    
    if uploaded_file is not None:
        try:
            df_trades = pd.read_csv(uploaded_file)
            st.write("🔍 **您上傳的原始紀錄：**")
            st.dataframe(df_trades, hide_index=True)
            
            df_trades['總成本'] = df_trades['買入價'] * df_trades['股數']
            df_trades['總拿回'] = df_trades['賣出價'] * df_trades['股數']
            df_trades['單筆損益'] = df_trades['總拿回'] - df_trades['總成本']
            df_trades['報酬率(%)'] = (df_trades['賣出價'] - df_trades['買入價']) / df_trades['買入價'] * 100
            
            total_trades = len(df_trades)
            win_trades = len(df_trades[df_trades['單筆損益'] > 0])
            win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0
            total_pnl = df_trades['單筆損益'].sum()
            avg_return = df_trades['報酬率(%)'].mean()
            
            st.subheader("📊 您的真實量化體質指標")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("總交易筆數", f"{total_trades} 筆")
            col2.metric("真實勝率", f"{win_rate:.1f}%", "- 危險" if win_rate < 40 else "+ 優秀")
            col3.metric("總損益金額", f"{total_pnl:,.0f} 元", "虧損" if total_pnl < 0 else "獲利")
            col4.metric("平均每筆報酬率", f"{avg_return:.2f}%")
            
            st.markdown("---")
            if st.button("🚨 呈交給 AI 大師進行「毒舌體質診斷」", type="primary", use_container_width=True):
                if not user_api_key:
                    st.error("🚨 請先在左側欄位輸入您的 API Key！")
                else:
                    with st.spinner(f"【{teacher_prompt_name}】正在審視您的對帳單..."):
                        genai.configure(api_key=user_api_key)
                        model = genai.GenerativeModel('gemini-2.5-flash')
                        trade_details = df_trades[['股票名稱', '報酬率(%)', '單筆損益']].to_string(index=False)
                        
                        prompt = f"""
                        你是台灣股市權威：{teacher_prompt_name}。核心邏輯：{selected_logic}。
                        總交易次數：{total_trades}次 | 勝率：{win_rate:.1f}% | 總損益：{total_pnl}元 | 平均報酬率：{avg_return:.2f}%
                        交易明細：{trade_details}
                        請直接輸出以下格式 (遵守 Markdown)：
                        ### 🩸 大師殘酷診斷
                        (用一段話點評他整體的狀況，毒舌且直接)
                        ### 🩺 致命傷分析
                        (找出賺最多或賠最慘的案例，告訴他哪裡做錯/做對)
                        ### 💊 給你的三帖猛藥
                        1. 
                        2. 
                        3. 
                        """
                        response = model.generate_content(
    prompt,
    request_options={"timeout": 15.0} # 設定 15 秒強制逾時
)
                        st.warning("⚠️ 以下為 AI 大師基於歷史紀錄的客製化診斷：")
                        st.markdown(response.text)
        except Exception as e:
            st.error(f"檔案讀取失敗！錯誤訊息：{e}")

# ----------------------------------------
# 分頁 4: 顧問對話室
# ----------------------------------------
with tab_chat:
    st.header("💬 AI 交易顧問對話室")
    st.markdown("您可以直接跟 AI 大師「一對一」提問，討論操作細節或大盤趨勢！")
    
    chat_container = st.container(height=400)
    with chat_container:
        for msg in st.session_state.chat_messages:
            st.chat_message(msg["role"]).write(msg["content"])
            
    if prompt := st.chat_input("請問大師..."):
        if not user_api_key: 
            st.error("🚨 請先輸入 API Key 才能開啟對話喔！")
        else:
            st.chat_message("user").write(prompt)
            st.session_state.chat_messages.append({"role": "user", "content": prompt})
            
            system_context = f"""
            系統設定提示：
            角色：{teacher_prompt_name}。邏輯：{selected_logic}。
            預算：{investment_amount}。目標：{target_months} 個月賺取 {target_return}%。
            請用繁體中文，以專業、符合你流派的語氣回答。
            """
            
            history_text = system_context + "\n\n--- 對話紀錄 ---\n"
            for m in st.session_state.chat_messages[-6:]: 
                role_name = "使用者" if m["role"] == "user" else "AI大師"
                history_text += f"{role_name}：{m['content']}\n"
                
            with st.spinner("大師打字中..."):
                try:
                    genai.configure(api_key=user_api_key)
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    response = model.generate_content(history_text)
                    st.chat_message("assistant").write(response.text)
                    st.session_state.chat_messages.append({"role": "assistant", "content": response.text})
                    st.rerun()
                except Exception as e:
                    st.error(f"連線失敗。錯誤：{e}")

# ----------------------------------------
# 分頁 5: 產業推演與潛伏雷達
# ----------------------------------------
with tab_predict:
    st.header("🔮 第二層思維：產業推演與潛伏雷達")
    st.markdown("""
    真正的贏家不在新聞頭條裡找飆股，而是預判資金的下一個去向！
    輸入目前最熱門的時事題材，AI 將推演出未來的受惠供應鏈，並自動為您掃描有哪些股票正在**「底部爆量偷吃貨」**。
    """)
    
    st.subheader("第一步：設定未來劇本")
    hot_trend = st.text_input("輸入目前市場最熱門的題材或新聞：", value="輝達最新 GB200 AI 伺服器面臨散熱與耗電雙重瓶頸")
    
    if st.button("🧠 啟動 AI 產業供應鏈推演", type="primary"):
        if not user_api_key:
            st.error("🚨 預測未來需要極大的算力，請先在左側輸入您的 API Key！")
        else:
            with st.spinner("AI 大師正在進行第二層思維推演..."):
                try:
                    genai.configure(api_key=user_api_key)
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    
                    predict_prompt = f"""
                    你是華爾街頂級對沖基金經理人，精通「第二層思維」與產業供應鏈推演。
                    目前市場上最熱門的題材是：「{hot_trend}」。
                    請預測未來 3 到 6 個月，資金會輪動到哪 3 個「尚未發動的下游/周邊受惠產業」？
                    
                    請務必在每個推演的產業中，具體列出 2~4 檔對應的「台灣股市股票代號」(請直接寫出4碼數字，例如 2330)。
                    
                    請用以下格式輸出：
                    ### 🔮 第二層思維推演結論
                    (簡述為什麼資金會往這些地方外溢)
                    
                    ### 🛠️ 潛在爆發板塊與台股標的
                    1. **[板塊名稱]**：[推演邏輯] -> 關注標的：(放入代號)
                    2. **[板塊名稱]**：[推演邏輯] -> 關注標的：(放入代號)
                    3. **[板塊名稱]**：[推演邏輯] -> 關注標的：(放入代號)
                    """
                    
                    result_text = model.generate_content(predict_prompt).text
                    st.session_state.prediction_result = result_text
                    
                    extracted_tickers = list(set(re.findall(r'\b\d{4}\b', result_text)))
                    st.session_state.predicted_tickers = extracted_tickers
                    
                except Exception as e:
                    st.error(f"推演失敗：{e}")

    if st.session_state.prediction_result:
        st.info(st.session_state.prediction_result)
        st.success(f"🤖 系統已從報告中自動攔截到 {len(st.session_state.predicted_tickers)} 檔概念股代號：{st.session_state.predicted_tickers}")
        
    st.markdown("---")
    st.subheader("第二步：量價異常潛伏偵測")
    st.markdown("AI 給出方向後，我們讓 Python 檢查這些股票是否已經有主力進場的物理足跡 (價穩量增)。")
    
    if st.button("📡 啟動聰明錢抓漏雷達", type="primary"):
        target_tickers = st.session_state.predicted_tickers
        if not target_tickers:
            st.warning("⚠️ 請先執行上方的「AI 產業供應鏈推演」，讓系統獲取股票代號！")
        else:
            scan_results = []
            scan_bar = st.progress(0, text="正在深入掃描籌碼與量價結構...")
            
            for i, t in enumerate(target_tickers):
                scan_bar.progress((i + 1) / len(target_tickers), text=f"正在分析主力動向: {t}")
                try:
                    stock = yf.Ticker(f"{t}.TW")
                    df_scan = stock.history(period="3mo")
                    if len(df_scan) < 30: continue
                    
                    current_p = df_scan['Close'].iloc[-1]
                    ma_long_val = df_scan['Close'].rolling(long_ma).mean().iloc[-1]
                    
                    bias_pct = ((current_p - ma_long_val) / ma_long_val) * 100
                    
                    vol_5d_avg = df_scan['Volume'].tail(5).mean()
                    vol_20d_avg = df_scan['Volume'].shift(5).tail(20).mean()
                    vol_ratio = (vol_5d_avg / vol_20d_avg) if vol_20d_avg > 0 else 0
                    
                    if -5 <= bias_pct <= 15 and vol_ratio >= 1.2:
                        status = "🚨 價穩量增 (疑似主力建倉)"
                    elif bias_pct > 15:
                        status = "🔥 已發動 (乖離過大請小心)"
                    else:
                        status = "💤 量縮整理中"
                        
                    comp_name = REVERSE_MAP.get(t, stock.info.get('shortName', '未知名稱'))
                        
                    scan_results.append({
                        "代號": t,
                        "公司名稱": comp_name,
                        "收盤價": round(current_p, 2),
                        f"下緣均線({long_ma}MA)乖離(%)": round(bias_pct, 2),
                        "近期量能放大倍數": round(vol_ratio, 2),
                        "主力動向判定": status
                    })
                except:
                    pass
                time.sleep(0.05)
                
            scan_bar.empty()
            
            if scan_results:
                df_stealth = pd.DataFrame(scan_results)
                df_stealth = df_stealth.sort_values(by="近期量能放大倍數", ascending=False)
                
                st.write("📊 **潛伏雷達掃描報告：**")
                st.dataframe(df_stealth.style.applymap(
                    lambda x: 'background-color: #ffcccc; color: black' if isinstance(x, (int, float)) and x >= 1.5 else '', 
                    subset=['近期量能放大倍數']
                ), hide_index=True, use_container_width=True)
                
                st.markdown(f"> **💡 解讀指南**：如果一檔股票的「{long_ma}MA 乖離率」很低 (落在 -5% 到 10% 之間，代表沒漲)，但「量能放大倍數」卻大於 1.5 倍 (代表有人偷偷爆買)，這往往就是新聞發布前的起漲點！")
            else:
                st.warning("查無符合條件之台股標的資料。")
