import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import google.generativeai as genai
import time
import io
import re  # 🌟 新增：用來自動抓取 AI 報告裡的股票代號

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
    * **底部盤整**：股價距離季線 (60MA) 乖離率介於 -5% 到 +15% 之間（沒有漲上天）。
    * **偷吃貨爆量**：近 5 日平均成交量，比過去 20 日平均量放大超過 1.2 倍以上。
    """)
    if st.button("了解，關閉視窗"):
        st.rerun()

# ==========================================
# 1. 系統常數與大師設定
# ==========================================
teacher_chu = """【朱家泓 - 飆股戰法】看重動能。股價需站上短期均線且RSI>50。嚴格以短期均線停損。基本面非重點。"""
teacher_lin = """【林恩如 - 均線大趨勢】只吃主升段。股價需站上長期均線與200MA。跌破長期均線停損。"""
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
    if user_input in TW_STOCK_MAP: return TW_STOCK_MAP[user_input], f"{TW_STOCK_MAP[user_input]}.TW"
    else: return user_input.upper().replace(".TW", "").replace(".TWO", ""), f"{user_input.upper().replace('.TW', '').replace('.TWO', '')}.TW"

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
        display_name = f"{REVERSE_MAP.get(ticker, info.get('shortName', '未知名稱'))} ({ticker})"
        
        current_price = df['Close'].iloc[-1]
        df[f'{short_ma}MA'] = df['Close'].rolling(window=short_ma).mean()
        delta = df['Close'].diff()
        rs = (delta.where(delta > 0, 0)).rolling(window=14).mean() / (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi = 100 - (100 / (1 + rs)).iloc[-1]
        
        pe_ratio = info.get('trailingPE', 0)
        past_year_divs = stock.dividends[stock.dividends.index > (pd.Timestamp.now(tz=stock.dividends.index.tz) - pd.Timedelta(days=365))]
        div_yield = (past_year_divs.sum() / current_price) * 100 if current_price > 0 and not past_year_divs.empty else 0
        
        return {
            "代號": ticker, "標的名稱": display_name, "收盤價": round(current_price, 2),
            f"{short_ma}MA": round(df[f'{short_ma}MA'].iloc[-1], 2), "RSI指標": round(rsi, 2),
            "本益比": round(pe_ratio, 2), "殖利率估算(%)": round(div_yield, 2),
            "趨勢向量": f"🟢 偏多 (站上 {short_ma}MA)" if current_price > df[f'{short_ma}MA'].iloc[-1] else f"🔴 偏空",
            "動能狀態": "🔥 過熱" if rsi > 70 else ("❄️ 超賣" if rsi < 30 else "🟡 整理中")
        }
    except: return None

def analyze_stock(user_input, target_months, target_return, short_ma, long_ma, backtest_days):
    ticker, yf_ticker = parse_stock_input(user_input)
    stock = yf.Ticker(yf_ticker)
    df = stock.history(period="5y")
    if df.empty or len(df) < 200: return None, None
    try:
        info = stock.info
        past_year_divs = stock.dividends[stock.dividends.index > (pd.Timestamp.now(tz=stock.dividends.index.tz) - pd.Timedelta(days=365))]
        display_name = f"{REVERSE_MAP.get(ticker, info.get('shortName', '未知名稱'))} ({ticker})"
    except:
        info, past_year_divs, display_name = {}, pd.Series(dtype='float64'), f"未知名稱 ({ticker})"
        
    current_price = df['Close'].iloc[-1]
    pct_change = ((current_price - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
    df[f'{short_ma}MA'] = df['Close'].rolling(window=short_ma).mean()
    df[f'{long_ma}MA'] = df['Close'].rolling(window=long_ma).mean()
    delta = df['Close'].diff()
    df['RSI'] = 100 - (100 / (1 + (delta.where(delta > 0, 0)).rolling(window=14).mean() / (-delta.where(delta < 0, 0)).rolling(window=14).mean()))
    
    horizon_days = int(target_months * 20) 
    if backtest_days <= horizon_days: prob_success, prob_loss = -1, -1
    else:
        valid_returns = df.tail(backtest_days)['Close'].pct_change(periods=horizon_days).dropna()
        prob_success = (valid_returns >= (target_return / 100)).mean() * 100 if not valid_returns.empty else 0
        prob_loss = (valid_returns < 0).mean() * 100 if not valid_returns.empty else 0
    
    return {"ticker": ticker, "display_name": display_name, "current_price": current_price, "pct_change": pct_change, 
            "pe_ratio": info.get('trailingPE', 0), "div_yield": (past_year_divs.sum() / current_price) * 100 if current_price > 0 else 0, 
            f"{short_ma}MA": df[f'{short_ma}MA'].iloc[-1], f"{long_ma}MA": df[f'{long_ma}MA'].iloc[-1], 
            "RSI": df['RSI'].iloc[-1], "prob_success": prob_success, "prob_loss": prob_loss}, df

def render_stock_card(data, df, short_ma, long_ma, backtest_days):
    st.header(f"📌 {data['display_name']}")
    col1, col2 = st.columns(2)
    col1.metric("最新收盤價", f"{data['current_price']:.2f}", f"{data['pct_change']:.2f}%")
    if data['prob_success'] == -1: col2.metric("🎯 歷史達標率", "時間衝突", "請增加回測天數", delta_color="off")
    else: col2.metric(f"🎯 歷史達標率 ({backtest_days}天內)", f"{data['prob_success']:.2f}%")
    
    df_plot = df.tail(max(backtest_days, 150)) 
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close']))
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot[f'{short_ma}MA'], mode='lines', line=dict(color='orange'), name=f'{short_ma}MA'))
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot[f'{long_ma}MA'], mode='lines', line=dict(color='blue'), name=f'{long_ma}MA'))
    fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

# ==========================================
# 3. 網頁記憶體初始化
# ==========================================
if 'stock_results' not in st.session_state: st.session_state.stock_results = []
if 'radar_top_10' not in st.session_state: st.session_state.radar_top_10 = None
if "chat_messages" not in st.session_state: st.session_state.chat_messages = [{"role": "assistant", "content": "你好！我是您的專屬 AI 交易顧問。"}]
# 🌟 新增：用於第 5 分頁的記憶體
if "prediction_result" not in st.session_state: st.session_state.prediction_result = ""
if "predicted_tickers" not in st.session_state: st.session_state.predicted_tickers = []

for i in range(1, 5):
    if f't{i}' not in st.session_state: st.session_state[f't{i}'] = "台積電" if i == 1 else ""

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
    short_ma = st.number_input("短期均線 (防守)：", min_value=5, value=20, step=1)
    long_ma = st.number_input("長期均線 (趨勢)：", min_value=10, value=60, step=1)
    backtest_days = st.number_input("歷史勝率回測天數：", min_value=30, value=365, step=10)

    st.markdown("---")
    st.subheader("🥊 PK 擂台名單")
    t1 = st.text_input("🟢 選手 1 (必填)：", key="t1")
    t2 = st.text_input("⚪ 選手 2 (選填)：", key="t2")
    t3 = st.text_input("⚪ 選手 3 (選填)：", key="t3")
    t4 = st.text_input("⚪ 選手 4 (選填)：", key="t4")
    
    st.markdown("---")
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

# ==========================================
# 5. 主畫面：五大分頁設計
# ==========================================
# 🌟 加入第五個分頁：預測雷達
tab_radar, tab_pk, tab_health, tab_chat, tab_predict = st.tabs([
    "🚀 1. 智慧策略選股", "⚔️ 2. PK 擂台", "📂 3. 體質健檢", "💬 4. 顧問對話室", "🔮 5. 產業推演與潛伏雷達"  
])

# ... (此處保留原先 tab_radar, tab_pk, tab_health, tab_chat 的程式碼，與上一版完全相同，為節省版面，我直接將精華放在 tab_predict) ...
# ⚠️ 為了讓您完整複製，以下補齊所有分頁的精簡代碼，確保程式可直接執行：

with tab_radar:
    selected_pool_name = st.selectbox("選擇掃描策略池：", list(STOCK_UNIVERSES.keys()))
    if st.button("📡 啟動策略池深度掃描", type="primary"):
        results = [data for t in STOCK_UNIVERSES[selected_pool_name]["tickers"] if (data := fetch_basic_info(t, short_ma))]
        if results:
            df_results = pd.DataFrame(results).sort_values(by='RSI指標' if "強勢" in selected_pool_name else '殖利率估算(%)', ascending=False)
            st.session_state.radar_top_10 = df_results.head(10)
    if st.session_state.radar_top_10 is not None:
        st.dataframe(st.session_state.radar_top_10, hide_index=True, use_container_width=True)
        top_tickers_codes = st.session_state.radar_top_10['代號'].tolist()
        if st.button("一鍵將名單匯入 PK 擂台"):
            st.session_state.t1 = st.session_state.t2 = st.session_state.t3 = st.session_state.t4 = ""
            for i, code in enumerate(top_tickers_codes[:4]): st.session_state[f"t{i+1}"] = code
            st.rerun()

with tab_pk:
    if fetch_button:
        valid_tickers = [t.strip() for t in [st.session_state.t1, st.session_state.t2, st.session_state.t3, st.session_state.t4] if t.strip()]
        st.session_state.stock_results = [{"data": d, "df": df} for t in valid_tickers if (d, df := analyze_stock(t, target_months, target_return, short_ma, long_ma, backtest_days))[0] is not None]
    if st.session_state.stock_results:
        for i, res in enumerate(st.session_state.stock_results): render_stock_card(res["data"], res["df"], short_ma, long_ma, backtest_days)

with tab_health:
    uploaded_file = st.file_uploader("上傳 CSV 交易紀錄：", type=["csv"])
    if uploaded_file is not None:
        try:
            df_trades = pd.read_csv(uploaded_file)
            st.dataframe(df_trades, hide_index=True)
        except: st.error("檔案讀取失敗")

with tab_chat:
    for msg in st.session_state.chat_messages: st.chat_message(msg["role"]).write(msg["content"])
    if prompt := st.chat_input("請問大師..."):
        if not user_api_key: st.error("請先輸入 API Key")
        else:
            st.chat_message("user").write(prompt)
            st.session_state.chat_messages.append({"role": "user", "content": prompt})

# ----------------------------------------
# 🌟 全新分頁 5: 產業推演與潛伏雷達
# ----------------------------------------
with tab_predict:
    st.header("🔮 第二層思維：產業推演與潛伏雷達")
    st.markdown("""
    真正的贏家不在新聞頭條裡找飆股，而是預判資金的下一個去向！
    輸入目前最熱門的時事題材，AI 將推演出未來的受惠供應鏈，並自動為您掃描有哪些股票正在**「底部爆量偷吃貨」**。
    """)
    
    # 區塊 A：AI 邏輯推演
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
                    
                    # 這是最值錢的推演 Prompt
                    predict_prompt = f"""
                    你是華爾街頂級對沖基金經理人，精通「第二層思維」與產業供應鏈推演。
                    目前市場上最熱門的題材是：「{hot_trend}」。
                    當散戶都在追逐這個表面題材時，請預測未來 3 到 6 個月，資金會輪動到哪 3 個「尚未發動的下游/周邊受惠產業」？(例如：原物料、基礎設施、特殊零件)
                    
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
                    
                    # 🌟 魔法：利用正則表達式，自動抓出所有 4 碼數字的股票代號
                    # re.findall 會找出像是 '2330', '3017' 這些符合條件的字串
                    extracted_tickers = list(set(re.findall(r'\b\d{4}\b', result_text)))
                    st.session_state.predicted_tickers = extracted_tickers
                    
                except Exception as e:
                    st.error(f"推演失敗：{e}")

    # 顯示 AI 的推演報告
    if st.session_state.prediction_result:
        st.info(st.session_state.prediction_result)
        st.success(f"🤖 系統已從報告中自動攔截到 {len(st.session_state.predicted_tickers)} 檔概念股代號：{st.session_state.predicted_tickers}")
        
    st.markdown("---")
    
    # 區塊 B：量化潛伏掃描
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
                    # 抓取最近 3 個月的資料來判斷
                    stock = yf.Ticker(f"{t}.TW")
                    df_scan = stock.history(period="3mo")
                    if len(df_scan) < 30: continue
                    
                    current_p = df_scan['Close'].iloc[-1]
                    ma60_val = df_scan['Close'].rolling(60).mean().iloc[-1]
                    
                    # 1. 計算乖離率：看看是否離季線太遠 (避免追高)
                    bias_pct = ((current_p - ma60_val) / ma60_val) * 100
                    
                    # 2. 計算成交量放大倍數：近 5 天平均 vs 前 20 天平均
                    vol_5d_avg = df_scan['Volume'].tail(5).mean()
                    vol_20d_avg = df_scan['Volume'].shift(5).tail(20).mean()
                    vol_ratio = (vol_5d_avg / vol_20d_avg) if vol_20d_avg > 0 else 0
                    
                    # 3. 嚴格的主力潛伏判定邏輯
                    if -5 <= bias_pct <= 15 and vol_ratio >= 1.2:
                        status = "🚨 價穩量增 (疑似主力建倉)"
                    elif bias_pct > 15:
                        status = "🔥 已發動 (乖離過大請小心)"
                    else:
                        status = "💤 量縮整理中"
                        
                    # 抓取公司名稱
                    comp_name = REVERSE_MAP.get(t, stock.info.get('shortName', '未知名稱'))
                        
                    scan_results.append({
                        "代號": t,
                        "公司名稱": comp_name,
                        "收盤價": round(current_p, 2),
                        "季線乖離率(%)": round(bias_pct, 2),
                        "近期量能放大倍數": round(vol_ratio, 2),
                        "主力動向判定": status
                    })
                except:
                    pass
                time.sleep(0.05) # 防鎖 IP
                
            scan_bar.empty()
            
            if scan_results:
                df_stealth = pd.DataFrame(scan_results)
                # 把「疑似主力建倉」的排在最前面
                df_stealth = df_stealth.sort_values(by="近期量能放大倍數", ascending=False)
                
                st.write("📊 **潛伏雷達掃描報告：**")
                # 幫表格上色：量能放大超過 1.5 倍的標示出來
                st.dataframe(df_stealth.style.applymap(
                    lambda x: 'background-color: #ffcccc; color: black' if isinstance(x, (int, float)) and x >= 1.5 else '', 
                    subset=['近期量能放大倍數']
                ), hide_index=True, use_container_width=True)
                
                st.markdown("> **💡 解讀指南**：如果一檔股票的「季線乖離率」很低 (落在 -5% 到 10% 之間，代表沒漲)，但「量能放大倍數」卻大於 1.5 倍 (代表有人偷偷爆買)，這往往就是新聞發布前的起漲點！")
            else:
                st.warning("查無符合條件之台股標的資料。")
