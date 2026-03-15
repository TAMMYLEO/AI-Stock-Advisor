import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import google.generativeai as genai
import time
import io


# ==========================================
# 0. 系統說明與彈跳視窗
# ==========================================
@st.dialog("🧠 系統運算邏輯大解密")
def show_logic_explanation():
    st.markdown("""
    ### 1. 殖利率 (Trailing Dividend Yield)
    本系統採用**「近一年滾動殖利率」**的嚴謹算法：
    * **公式**：`(過去 365 天內實際發放的現金股利總和) ÷ (今日收盤價) × 100%`

    ### 2. 歷史達標率 (Monte Carlo 滾動回測)
    這不是預測未來，而是告訴您歷史的真實機率：
    * **算法**：系統提取歷史 K 線，依照您設定的「回測天數」進行「每日滾動模擬」。
    * **意義**：如果達標率顯示 65%，代表在您指定的歷史波段內，任何人只要在這檔股票裡**隨便挑一天閉著眼睛買進**並持有指定時間，有 65% 的機率可以帶著目標獲利出場。
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
    "🔥 科技權值與強勢動能池 (掃描 30 檔科技巨頭與飆股)": {
        "tickers": ["2330", "2317", "2454", "2382", "3231", "2357", "2353", "2377", "2376", "3017",
                    "3324", "2383", "3711", "2303", "3034", "2379", "2345", "6669", "3008", "3037",
                    "2308", "2301", "2395", "2059", "3533", "2603", "1519", "1503", "1513", "1514"],
        "desc": "尋找目前站上短期均線且 RSI 動能強勁的標的。"
    },
    "💰 穩健存股與避險價值池 (掃描 25 檔金融、傳產與 ETF)": {
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
        rs = (delta.where(delta > 0, 0)).rolling(window=14).mean() / (-delta.where(delta < 0, 0)).rolling(
            window=14).mean()
        rsi = 100 - (100 / (1 + rs)).iloc[-1]

        pe_ratio = info.get('trailingPE', 0)
        dividends = stock.dividends
        past_year_divs = dividends[dividends.index > (pd.Timestamp.now(tz=dividends.index.tz) - pd.Timedelta(days=365))]
        div_yield = (
                                past_year_divs.sum() / current_price) * 100 if current_price > 0 and not past_year_divs.empty else 0

        trend_vector = f"🟢 偏多 (站上 {short_ma}MA)" if current_price > df[f'{short_ma}MA'].iloc[
            -1] else f"🔴 偏空 (跌破 {short_ma}MA)"
        rsi_vector = "🔥 過熱 (>70)" if rsi > 70 else ("❄️ 超賣 (<30)" if rsi < 30 else "🟡 整理中")

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
        dividends = stock.dividends
        past_year_divs = dividends[dividends.index > (pd.Timestamp.now(tz=dividends.index.tz) - pd.Timedelta(days=365))]
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

    df_backtest = df.tail(backtest_days)
    horizon_days = int(target_months * 20)

    # 防呆機制：如果回測天數裝不下持有天數，回傳 -1
    if backtest_days <= horizon_days:
        prob_success = -1
        prob_loss = -1
    else:
        valid_returns = df_backtest['Close'].pct_change(periods=horizon_days).dropna()
        prob_success = (valid_returns >= (target_return / 100)).mean() * 100 if not valid_returns.empty else 0
        prob_loss = (valid_returns < 0).mean() * 100 if not valid_returns.empty else 0

    data_dict = {"ticker": ticker, "display_name": display_name, "current_price": current_price,
                 "pct_change": pct_change,
                 "pe_ratio": pe_ratio, "div_yield": div_yield,
                 f"{short_ma}MA": df[f'{short_ma}MA'].iloc[-1],
                 f"{long_ma}MA": df[f'{long_ma}MA'].iloc[-1],
                 "RSI": df['RSI'].iloc[-1], "prob_success": prob_success, "prob_loss": prob_loss}
    return data_dict, df


def render_stock_card(data, df, short_ma, long_ma, backtest_days):
    st.header(f"📌 {data['display_name']}")
    col1, col2 = st.columns(2)
    col1.metric("最新收盤價", f"{data['current_price']:.2f}", f"{data['pct_change']:.2f}%")

    # 歷史達標率防呆顯示
    if data['prob_success'] == -1:
        col2.metric("🎯 歷史達標率", "時間衝突", "請增加回測天數或減少目標時間", delta_color="off")
    else:
        col2.metric(f"🎯 歷史達標率 ({backtest_days}天內)", f"{data['prob_success']:.2f}%")

    df_plot = df.tail(max(backtest_days, 150))

    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'],
                                 close=df_plot['Close'], name="K線"))
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot[f'{short_ma}MA'], mode='lines', line=dict(color='orange'),
                             name=f'{short_ma}MA'))
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot[f'{long_ma}MA'], mode='lines', line=dict(color='blue'),
                             name=f'{long_ma}MA'))
    fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(pd.DataFrame([{"本益比": f"{data['pe_ratio']:.2f}" if data['pe_ratio'] > 0 else "N/A",
                                "殖利率": f"{data['div_yield']:.2f}%", "RSI": f"{data['RSI']:.2f}"}]), hide_index=True)


def import_to_pk_callback(selected_names, names_list, codes_list):
    st.session_state.t1 = st.session_state.t2 = st.session_state.t3 = st.session_state.t4 = ""
    for i, selected_name in enumerate(selected_names):
        idx = names_list.index(selected_name)
        st.session_state[f"t{i + 1}"] = codes_list[idx]


# ==========================================
# 3. 網頁記憶體初始化
# ==========================================
if 'stock_results' not in st.session_state: st.session_state.stock_results = []
if 'radar_top_10' not in st.session_state: st.session_state.radar_top_10 = None
if 'radar_pool_name' not in st.session_state: st.session_state.radar_pool_name = ""

# 🌟 新增：對話記憶體初始化
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = [
        {"role": "assistant",
         "content": "你好！我是您的專屬 AI 交易顧問。您可以詢問我關於目前雷達掃描的標的、PK擂台的分析，或是剛才體質健檢的相關問題！"}
    ]

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
    short_ma = st.number_input("短期均線 (短線防守/上緣)：", min_value=5, value=20, step=1)
    long_ma = st.number_input("長期均線 (長線趨勢/下緣)：", min_value=10, value=60, step=1)
    backtest_days = st.number_input("歷史勝率回測天數 (波段)：", min_value=30, value=365, step=10)

    st.markdown("---")
    st.subheader("🥊 PK 擂台名單")
    st.caption("支援輸入代號或公司名稱")
    t1 = st.text_input("🟢 選手 1 (必填)：", key="t1")
    t2 = st.text_input("⚪ 選手 2 (選填)：", key="t2")
    t3 = st.text_input("⚪ 選手 3 (選填)：", key="t3")
    t4 = st.text_input("⚪ 選手 4 (選填)：", key="t4")

    st.markdown("---")
    st.subheader("💰 資金與目標")
    investment_amount = st.number_input("預計總預算 (台幣)：", min_value=1000, value=300000, step=10000)
    target_return = st.number_input("預期獲利目標 (%)：", value=10.0, step=0.5)
    target_months = st.number_input("預期達成時間 (個月)：", min_value=1, value=6, step=1)

    st.markdown("---")
    options_list = list(strategies.keys()) + ["💡 自訂大師 (手動輸入)"]
    selected_teacher_name = st.selectbox("🧑‍⚖️ 選擇評比大師：", options=options_list)

    if selected_teacher_name == "💡 自訂大師 (手動輸入)":
        selected_logic = st.text_area("請輸入您的獨門判斷邏輯：",
                                      value=f"看重均線趨勢，必須站上 {short_ma}MA，且殖利率需大於 5% 才能買進。")
        teacher_prompt_name = "我的自訂量化策略"
    else:
        selected_logic = strategies[selected_teacher_name]
        teacher_prompt_name = selected_teacher_name

    fetch_button = st.button("📊 抓取 PK 名單最新圖表", use_container_width=True)

# ==========================================
# 5. 主畫面：四大分頁設計
# ==========================================
# 🌟 加入第四個分頁：對話室
tab_radar, tab_pk, tab_health, tab_chat = st.tabs([
    "🚀 1. 智慧策略選股雷達",
    "⚔️ 2. 雙股/多股 PK 擂台",
    "📂 3. AI 交易體質健檢",
    "💬 4. AI 交易顧問對話室"
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
            if data: results.append(data)
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
        selected_to_arena = st.multiselect("選擇參賽選手 (最多 4 名)：", options=top_tickers_names,
                                           default=top_tickers_names[:2], max_selections=4)
        st.button("一鍵將勾選名單匯入左側【PK 擂台】", type="primary", key="btn_import_pk",
                  on_click=import_to_pk_callback, args=(selected_to_arena, top_tickers_names, top_tickers_codes))

# ----------------------------------------
# 分頁 2: PK 對戰台
# ----------------------------------------
with tab_pk:
    if fetch_button:
        raw_inputs = [st.session_state.t1, st.session_state.t2, st.session_state.t3, st.session_state.t4]
        valid_tickers = [t.strip() for t in raw_inputs if t.strip()]
        if not valid_tickers:
            st.error("請在左側至少輸入一檔股票！")
        else:
            with st.spinner("正在抓取深度數據..."):
                results = []
                for t in valid_tickers:
                    data, df = analyze_stock(t, target_months, target_return, short_ma, long_ma, backtest_days)
                    if data is not None: results.append({"data": data, "df": df})
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
                    with cols[1]: render_stock_card(results[i + 1]["data"], results[i + 1]["df"], short_ma, long_ma,
                                                    backtest_days)

        st.markdown("---")
        if st.button("🧠 呼叫 AI 大師進行終極資金配置", type="primary", use_container_width=True):
            if not user_api_key:
                st.error("🚨 請先在左側輸入 API Key。")
            else:
                with st.spinner("大師深思熟慮中..."):
                    try:
                        genai.configure(api_key=user_api_key)
                        model = genai.GenerativeModel('gemini-2.5-flash')
                        data_strings, headers = [], ["評估項目"]
                        for i, res in enumerate(results):
                            d = res["data"]
                            prob_text = "衝突" if d['prob_success'] == -1 else f"{d['prob_success']:.2f}%"
                            data_strings.append(
                                f"【標的 {i + 1} ({d['display_name']})】：收盤:{d['current_price']:.2f} | PE:{d['pe_ratio']:.2f} | {short_ma}MA:{d[f'{short_ma}MA']:.2f} | {long_ma}MA:{d[f'{long_ma}MA']:.2f} | 達標率:{prob_text}")
                            headers.append(f"標的 {i + 1}<br>({d['display_name']})")
                        all_data_text = "\n".join(data_strings)
                        md_table_header = "| " + " | ".join(headers) + " |\n| " + " | ".join(
                            [":---"] * len(headers)) + " |"
                        task = "單獨分析" if num_stocks == 1 else "PK 資金分配"
                        prompt = f"你是{teacher_prompt_name}。邏輯：{selected_logic}。預算：{investment_amount}。資料：{all_data_text}。請輸出：\n### 🏆 總評\n\n### 💰 資金配置與行動建議表\n{md_table_header}\n| **技術與基本面(短評)** | ... |\n| **防守停損價位** | ... |\n| **最終資金配置** | ... |"
                        st.markdown(model.generate_content(prompt).text)
                    except Exception as e:
                        st.error(f"錯誤：{e}")

# ----------------------------------------
# 分頁 3: 交易體質健檢 
# ----------------------------------------
with tab_health:
    st.header("📂 歷史交易體質大健檢")
    st.markdown("上傳您的真實歷史對帳單，讓 AI 大師來幫您「抓漏」！")

    sample_csv_text = "股票名稱,買入日期,賣出日期,買入價,賣出價,股數\n台積電,2023-05-01,2023-06-10,500,580,1000\n長榮,2023-07-01,2023-07-15,120,110,2000\n富邦金,2023-08-01,2023-12-01,60,65,3000"
    sample_csv_bytes = sample_csv_text.encode('utf-8-sig')
    st.download_button(label="📥 下載標準 CSV 測試範本檔", data=sample_csv_bytes, file_name="sample_trades.csv",
                       mime="text/csv")

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
                        response = model.generate_content(prompt)
                        st.warning("⚠️ 以下為 AI 大師基於歷史紀錄的客製化診斷：")
                        st.markdown(response.text)
        except Exception as e:
            st.error(f"檔案讀取失敗！錯誤訊息：{e}")

# ----------------------------------------
# 🌟 全新分頁 4: AI 交易顧問對話室
# ----------------------------------------
with tab_chat:
    st.header("💬 AI 交易顧問對話室")
    st.markdown("除了看報告，您也可以在這裡直接跟 AI 大師「一對一」提問，討論操作細節或大盤趨勢！")

    # 建立一個卷軸區塊來顯示歷史訊息
    chat_container = st.container(height=400)
    with chat_container:
        for msg in st.session_state.chat_messages:
            st.chat_message(msg["role"]).write(msg["content"])

    # 接收使用者聊天輸入框
    if prompt := st.chat_input("請問大師... (例如：請問剛剛的長榮，如果不想停損有什麼補救方法嗎？)"):
        if not user_api_key:
            st.error("🚨 請先在左側欄位輸入您的 API Key 才能開啟對話喔！")
        else:
            # 1. 顯示並儲存使用者的問題
            st.chat_message("user").write(prompt)
            st.session_state.chat_messages.append({"role": "user", "content": prompt})

            # 2. 構建給 AI 的背景知識 (讓它知道您當前的設定)
            system_context = f"""
            系統設定提示 (不用回覆這段)：
            你目前的角色是：{teacher_prompt_name}。
            你的核心交易邏輯是：{selected_logic}。
            使用者的總預算是：{investment_amount} 元，目標是 {target_months} 個月內賺取 {target_return}%。
            請用繁體中文，以專業、自信且符合你流派的語氣，回答使用者接下來的問題。
            """

            # 3. 將最近幾次的對話打包，讓 AI 有「記憶」
            history_text = system_context + "\n\n--- 以下是最近的對話紀錄 ---\n"
            # 為了節省 Token，我們只取最近的 6 句話作為上下文記憶
            for m in st.session_state.chat_messages[-6:]:
                role_name = "使用者" if m["role"] == "user" else "AI大師"
                history_text += f"{role_name}：{m['content']}\n"

            with st.spinner("大師正在打字中..."):
                try:
                    genai.configure(api_key=user_api_key)
                    model = genai.GenerativeModel('gemini-2.5-flash')

                    # 傳送完整上下文給 Gemini
                    response = model.generate_content(history_text)

                    # 4. 顯示並儲存 AI 的回答
                    st.chat_message("assistant").write(response.text)
                    st.session_state.chat_messages.append({"role": "assistant", "content": response.text})

                    # 強制畫面重新整理，確保聊天室卷軸自動滾到最下面
                    st.rerun()
                except Exception as e:
                    st.error(f"連線失敗，請確認 API 金鑰。錯誤：{e}")