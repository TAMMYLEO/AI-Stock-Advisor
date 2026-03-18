import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import google.generativeai as genai
import time
import re

# ==========================================
# 0. 系統說明與彈跳視窗
# ==========================================
@st.dialog("🧠 系統運算邏輯大解密")
def show_logic_explanation():
    st.markdown("""
    ### 1. 歷史達標率 (Monte Carlo 滾動回測)
    這不是預測未來，而是告訴您歷史的真實機率：系統提取歷史 K 線，依照您設定的「回測天數」進行「每日滾動模擬」。

    ### 2. 基本面與量價雙軌預測
    我們不再只看技術面！系統會先請 AI 分析公司的「法說會、財報、接單狀況」，再搭配量化技術面給出操作建議。

    ### 3. 填息能力量化
    系統會追蹤近 3 年的除息紀錄，算出「填息機率」與「平均花費天數」，避開賺股息賠價差的陷阱！

    ### 4. 毒舌測謊機 (反阿諛奉承)
    AI 將化身極度懷疑論的外資分析師，將您貼上的利多新聞與「真實均線量能」交叉比對，無情戳破主力出貨的假消息！

    ### 5. 估值天花板偵測 (P/E & PEG)
    加入本益比 (P/E) 與本益成長比 (PEG) 指標。當 PEG > 1.5 時，代表股價可能已經透支未來成長性，接近「頂點」。

    ### 6. 支援興櫃股票分析
    系統已具備「自動盲測引擎」，您只需輸入股號，系統會自動辨識上市(.TW)或上櫃/興櫃(.TWO)。
    """)
    if st.button("了解，關閉視窗"):
        st.rerun()

# ==========================================
# 1. 系統常數與大師設定
# ==========================================
teacher_chu = """【朱家泓 - 飆股戰法】看重動能與型態。嚴格以短期均線停損。"""
teacher_lin = """【林恩如 - 均線大趨勢】只吃主升段。股價需站上長期均線。"""
teacher_chen = """【價值存股派 - 逢低佈局】越跌越買。看重「殖利率」、「本益比」與「PEG」，關注法說會與財報轉機，且極度在意填息能力。"""

strategies = {
    "朱家泓 (短波段動能 / 嚴格停損)": teacher_chu,
    "林恩如 (長線大趨勢 / 抱緊處理)": teacher_lin,
    "價值存股派 (看重財報與逢低佈局)": teacher_chen
}

STOCK_DB = {
    # 常用權值股名單
    "2330": {"name": "台積電", "market": "TW"},
    "2317": {"name": "鴻海", "market": "TW"},
    "2454": {"name": "聯發科", "market": "TW"},
    "3481": {"name": "群創", "market": "TW"},
    "7889": {"name": "騰勢", "market": "TWO"}, 
}

REVERSE_MAP = {v["name"]: k for k, v in STOCK_DB.items()}

def get_yf_ticker_candidates(user_input):
    """
    【全新雙重盲測引擎】
    回傳候選的 yfinance 代號列表。
    讓系統自己去撞測試，免除使用者手動輸入後綴的麻煩。
    """
    user_input = str(user_input).strip().upper()

    # 1. 如果使用者很明確給了後綴，就只相信使用者
    if user_input.endswith(".TW") or user_input.endswith(".TWO"):
        return user_input.split(".")[0], [user_input]

    # 2. 如果輸入中文名稱，轉換為代號
    ticker = REVERSE_MAP.get(user_input, user_input)
    
    # 3. 如果在我們的資料庫有建檔，直接回傳正確的
    if ticker in STOCK_DB:
        return ticker, [f"{ticker}.{STOCK_DB[ticker]['market']}"]

    # 4. 最強盲測：不知道是上市還上櫃？兩個都回傳，讓後續函式自己試！
    return ticker, [f"{ticker}.TW", f"{ticker}.TWO"]


# ==========================================
# 2. 核心數據引擎
# ==========================================
def analyze_stock(user_input, target_months, target_return, short_ma, long_ma, backtest_days):
    ticker, candidates = get_yf_ticker_candidates(user_input)
    
    # 【盲測啟動】輪流測試 .TW 與 .TWO，直到抓到資料為止
    df = pd.DataFrame()
    yf_ticker = ""
    stock = None
    for cand in candidates:
        stock = yf.Ticker(cand)
        df = stock.history(period="5y")
        if not df.empty and len(df) >= 10:
            yf_ticker = cand
            break # 成功抓到資料，跳出迴圈！
            
    if df.empty or len(df) < 10: 
        return None, None

    try:
        info = stock.info
        pe_ratio = info.get('trailingPE', 0)
        peg_ratio = info.get('pegRatio', 0)
        past_year_divs = stock.dividends[
            stock.dividends.index > (pd.Timestamp.now(tz=stock.dividends.index.tz) - pd.Timedelta(days=365))]
        total_div = past_year_divs.sum() if not past_year_divs.empty else 0
        company_name = STOCK_DB.get(ticker, {}).get("name", info.get('shortName', '未知名稱'))
        display_name = f"{company_name} ({ticker})"
    except:
        pe_ratio, peg_ratio, total_div = 0, 0, 0
        display_name = f"未知名稱 ({ticker})"

    current_price = df['Close'].iloc[-1]
    prev_price = df['Close'].iloc[-2] if len(df) > 1 else current_price
    pct_change = ((current_price - prev_price) / prev_price) * 100 if prev_price > 0 else 0
    div_yield = (total_div / current_price) * 100 if current_price > 0 else 0

    actual_short_ma = min(short_ma, len(df))
    actual_long_ma = min(long_ma, len(df))
    
    df[f'{short_ma}MA'] = df['Close'].rolling(window=actual_short_ma).mean()
    df[f'{long_ma}MA'] = df['Close'].rolling(window=actual_long_ma).mean()

    delta = df['Close'].diff()
    window_length = min(14, len(df))
    rs = (delta.where(delta > 0, 0)).rolling(window=window_length).mean() / (-delta.where(delta < 0, 0)).rolling(window=window_length).mean()
    df['RSI'] = 100 - (100 / (1 + rs))

    df_backtest = df.tail(backtest_days)
    horizon_days = int(target_months * 20)

    if len(df_backtest) <= horizon_days:
        prob_success, prob_loss = -1, -1
    else:
        valid_returns = df_backtest['Close'].pct_change(periods=horizon_days).dropna()
        prob_success = (valid_returns >= (target_return / 100)).mean() * 100 if not valid_returns.empty else 0
        prob_loss = (valid_returns < 0).mean() * 100 if not valid_returns.empty else 0

    # 填息量化引擎
    df_raw = stock.history(period="3y", auto_adjust=False)
    divs = stock.dividends
    fill_rate, avg_fill_days, total_recent_divs = 0, 0, 0

    if not divs.empty and not df_raw.empty:
        if divs.index.tz is None and df_raw.index.tz is not None:
            divs.index = divs.index.tz_localize(df_raw.index.tz)
        elif divs.index.tz is not None and df_raw.index.tz is None:
            divs.index = divs.index.tz_localize(None)

        recent_divs = divs[divs.index >= df_raw.index[0]]
        total_recent_divs = len(recent_divs)

        if total_recent_divs > 0:
            fill_count = 0
            days_to_fill = []
            for d_date, d_amt in recent_divs.items():
                try:
                    pre_dates = df_raw.loc[:d_date]
                    if len(pre_dates) < 2: continue
                    target_price = pre_dates['Close'].iloc[-2]

                    post_dates = df_raw.loc[d_date:]
                    filled_mask = post_dates['Close'] >= target_price

                    if filled_mask.any():
                        fill_count += 1
                        days = len(post_dates[:filled_mask.idxmax()])
                        days_to_fill.append(days)
                except:
                    pass

            fill_rate = (fill_count / total_recent_divs) * 100 if total_recent_divs > 0 else 0
            avg_fill_days = sum(days_to_fill) / len(days_to_fill) if days_to_fill else 0

    data_dict = {
        "ticker": ticker, "yf_ticker": yf_ticker, "display_name": display_name, "current_price": current_price, "pct_change": pct_change,
        "pe_ratio": pe_ratio, "peg_ratio": peg_ratio, "div_yield": div_yield,
        f"{short_ma}MA": df[f'{short_ma}MA'].iloc[-1], f"{long_ma}MA": df[f'{long_ma}MA'].iloc[-1],
        "RSI": df['RSI'].iloc[-1] if not pd.isna(df['RSI'].iloc[-1]) else 50, 
        "prob_success": prob_success, "prob_loss": prob_loss,
        "fill_rate": fill_rate, "avg_fill_days": avg_fill_days, "total_divs": total_recent_divs
    }
    return data_dict, df

def render_stock_card(data, df, short_ma, long_ma, backtest_days):
    st.header(f"📌 {data['display_name']}")
    
    # 🚨 上櫃/興櫃風險提醒
    if ".TWO" in data.get("yf_ticker", ""):
        st.warning("⚠️ **注意：此為上櫃/興櫃股票！** 流動性較低，股價波動風險較大，請謹慎評估。")
        
    col1, col2, col3 = st.columns(3)
    col1.metric("最新收盤價", f"{data['current_price']:.2f}", f"{data['pct_change']:.2f}%")

    if data['prob_success'] == -1:
        col2.metric("🎯 歷史達標率", "資料不足", "無法回測長週期", delta_color="off")
    else:
        col2.metric(f"🎯 歷史達標率 ({backtest_days}天內)", f"{data['prob_success']:.2f}%")

    if data['total_divs'] > 0:
        col3.metric("📈 近3年填息機率", f"{data['fill_rate']:.0f}%", f"平均 {data['avg_fill_days']:.0f} 天填息")
    else:
        col3.metric("📈 近3年填息機率", "無配息紀錄", delta_color="off")

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

    stats_df = pd.DataFrame([{
        "本益比 (P/E)": f"{data['pe_ratio']:.2f}" if data['pe_ratio'] > 0 else "N/A",
        "本益成長比 (PEG)": f"{data['peg_ratio']:.2f}" if data['peg_ratio'] > 0 else "N/A",
        "殖利率": f"{data['div_yield']:.2f}%",
        "RSI": f"{data['RSI']:.2f}"
    }])
    st.dataframe(stats_df, hide_index=True)

    if data['peg_ratio'] > 0:
        if data['peg_ratio'] < 1:
            st.success("✨ **估值偏低 (PEG < 1)：** 股價成長潛力大於目前估值，值得關注！")
        elif data['peg_ratio'] > 1.5:
            st.error("⚠️ **估值過高 (PEG > 1.5)：** 股價可能已經透支未來成長性，請留意追高風險！")


# ==========================================
# 3. 網頁記憶體初始化
# ==========================================
if 'stock_results' not in st.session_state:
    st.session_state.stock_results = []
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = [{"role": "assistant",
                                       "content": "您好呀！我是您的專屬 AI 交易顧問。我們現在不僅會幫您看均線，我也會幫您注意財報、法說會，甚至是填息的狀況喔！"}]
if "prediction_result" not in st.session_state:
    st.session_state.prediction_result = ""
if "predicted_tickers" not in st.session_state:
    st.session_state.predicted_tickers = []
if "finance_data_str" not in st.session_state:
    st.session_state.finance_data_str = ""

for i in range(1, 5):
    if f't{i}' not in st.session_state:
        st.session_state[f't{i}'] = "3481" if i == 1 else "" # 預設改成3481給您測測看

# ==========================================
# 4. 網頁介面設計 (側邊欄)
# ==========================================
st.set_page_config(page_title="AI 量化旗艦系統", layout="wide", page_icon="📈")

with st.sidebar:
    st.title("⚙️ 總司令控制台")
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
        selected_logic = st.text_area("自訂邏輯：",
                                      value=f"看重財報與法說會轉機，站上 {short_ma}MA 加碼，極度重視填息機率與估值 (PEG)。")
        teacher_prompt_name = "我的自訂量化策略"
    else:
        selected_logic = strategies[selected_teacher_name]
        teacher_prompt_name = selected_teacher_name

    fetch_button = st.button("📊 抓取 PK 名單深度數據", use_container_width=True)

    if st.button("📖 系統運算邏輯大解密", icon="ℹ️", use_container_width=True):
        show_logic_explanation()

# ==========================================
# 5. 主畫面：五大分頁設計
# ==========================================
tab_pk, tab_health, tab_chat, tab_predict, tab_finance = st.tabs([
    "⚔️ 1. PK 擂台",
    "📂 2. 體質健檢",
    "💬 3. 顧問對話室",
    "🔮 4. 產業推演與潛伏雷達",
    "📑 5. 財報與法說會解析"
])

# ----------------------------------------
# 分頁 1: PK 對戰台
# ----------------------------------------
with tab_pk:
    if fetch_button:
        raw_inputs = [st.session_state.t1, st.session_state.t2, st.session_state.t3, st.session_state.t4]
        valid_tickers = [t.strip() for t in raw_inputs if t.strip()]

        if not valid_tickers:
            st.error("要在左側至少輸入一檔股票名稱或代號，人家才能幫您算喔！")
        else:
            with st.spinner("正在啟動智慧盲測引擎，抓取最新深度數據..."):
                results = []
                for t in valid_tickers:
                    data, df = analyze_stock(t, target_months, target_return, short_ma, long_ma, backtest_days)
                    if data is not None:
                        results.append({"data": data, "df": df})
                    else:
                        st.error(f"⚠️ 找不到「{t}」的有效資料！連盲測引擎都失敗了，請確認這是一檔有交易紀錄的股票喔！")
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
                        render_stock_card(results[i + 1]["data"], results[i + 1]["df"], short_ma, long_ma,
                                          backtest_days)

        st.markdown("---")
        st.subheader("🗞️ 獨家情報與法說會查核 (選填)")
        user_news = st.text_area("貼上您看到的利多新聞、法說會大餅或小道消息，大師將化身「毒舌查核員」為您測謊：",
                                 placeholder="例如：群創2026下半年車載面板訂單滿載，產能供不應求，法人預估營收將創高...")

        if st.button("🧠 呼叫大師進行「基本面+技術面+毒舌測謊」終極評估", type="primary", use_container_width=True):
            if not user_api_key:
                st.error("🚨 記得先在左側輸入 API Key 喔！")
            else:
                with st.spinner("大師正在交叉比對新聞真偽與量價數據，請稍候一下下..."):
                    try:
                        genai.configure(api_key=user_api_key)
                        model = genai.GenerativeModel('gemini-2.5-flash-lite')

                        today_date = datetime.now().strftime("%Y年%m月%d日")

                        data_strings = []
                        headers = ["評估項目"]
                        for i, res in enumerate(results):
                            d = res["data"]
                            prob_text = "衝突" if d['prob_success'] == -1 else f"{d['prob_success']:.2f}%"
                            data_strings.append(
                                f"【標的 {i + 1} ({d['display_name']})】：收盤:{d['current_price']:.2f} | PE:{d['pe_ratio']:.2f} | PEG:{d['peg_ratio']:.2f} | 殖利率:{d['div_yield']:.2f}% | 填息機率:{d['fill_rate']:.0f}% (平均{d['avg_fill_days']:.0f}天) | {short_ma}MA:{d[f'{short_ma}MA']:.2f}")
                            headers.append(f"標的 {i + 1}<br>({d['display_name']})")

                        all_data_text = "\n".join(data_strings)
                        md_table_header = "| " + " | ".join(headers) + " |\n| " + " | ".join(
                            [":---"] * len(headers)) + " |"
                        task = "請評估是否值得買進。" if num_stocks == 1 else "這是一場 PK 賽，請明確宣告資金該如何分配？"

                        news_context = f"\n【使用者提供的最新情報/新聞】：\n{user_news}\n" if user_news else ""

                        prompt = f"""
                        你是台灣股市權威：{teacher_prompt_name}。核心邏輯：{selected_logic}。
                        總預算：{investment_amount}。

                        ⚠️【最高強制指令】：
                        1. 時間錨點：今天是 {today_date}。推演未來時，請嚴格以這個日期為基準。
                        2. 價格絕對服從：只能使用以下提供的最新收盤價與均線數據，絕對禁止瞎掰過時的價格。
                        3. 魔鬼代言人(毒舌測謊)模式：如果使用者有提供【最新情報/新聞】，請你切換為「極度懷疑論的外資做空分析師」。請嚴格將這篇新聞與下方的冷冰冰量化數據「對答案」。如果新聞狂畫大餅說利多，但股價卻跌破均線或毫無動靜，請毫不留情地戳破，警告這可能是「主力出貨文」！反之，若利空頻傳但股價不跌，請指出錯殺機會。絕對不要一味附和新聞！

                        量化資料如下：\n{all_data_text}
                        {news_context}
                        {task}

                        請輸出：
                        ### 🩸 大師測謊與總評 (情報真實性與技術面交叉比對)

                        ### 💰 資金配置與行動建議表
                        {md_table_header}
                        | **基本面預期與估值(PE/PEG/填息)** | (填寫) |
                        | **技術面現況與測謊結論** | (填寫) |
                        | **最終資金配置與策略** | (填寫) |
                        """
                        st.markdown(model.generate_content(prompt).text)
                    except Exception as e:
                        st.error(f"哎呀出錯了：{e}")

# ----------------------------------------
# 分頁 2: 交易體質健檢
# ----------------------------------------
with tab_health:
    st.header("📂 歷史交易體質大健檢")
    st.markdown("上傳您的真實歷史對帳單，讓人家請 AI 大師來幫您好好「抓漏」一下！")

    sample_csv_text = "股票名稱,買入日期,賣出日期,買入價,賣出價,股數\n台積電,2023-05-01,2023-06-10,500,580,1000\n長榮,2023-07-01,2023-07-15,120,110,2000\n富邦金,2023-08-01,2023-12-01,60,65,3000"
    sample_csv_bytes = sample_csv_text.encode('utf-8-sig')
    st.download_button(label="📥 下載標準 CSV 測試範本檔", data=sample_csv_bytes, file_name="sample_trades.csv",
                       mime="text/csv")

    uploaded_file = st.file_uploader("上傳您的 CSV 交易紀錄：", type=["csv"], key="trade_csv")
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
            if st.button("🚨 呈交給 AI 大師進行「毒舌體質診斷」", type="primary"):
                if not user_api_key:
                    st.error("🚨 記得先在左側欄位輸入您的 API Key 喔！")
                else:
                    with st.spinner(f"【{teacher_prompt_name}】正在認真審視您的對帳單..."):
                        genai.configure(api_key=user_api_key)
                        model = genai.GenerativeModel('gemini-2.5-flash-lite')
                        trade_details = df_trades[['股票名稱', '報酬率(%)', '單筆損益']].to_string(index=False)

                        prompt = f"""
                        你是台灣股市權威：{teacher_prompt_name}。核心邏輯：{selected_logic}。
                        總交易次數：{total_trades}次 | 勝率：{win_rate:.1f}% | 總損益：{total_pnl}元 | 平均報酬率：{avg_return:.2f}%
                        交易明細：{trade_details}

                        ⚠️【最高強制指令】：請僅依據上述真實明細進行分析，禁止自行編造不存在的交易。

                        請直接輸出：
                        ### 🩸 大師殘酷診斷
                        ### 🩺 致命傷分析
                        ### 💊 給你的三帖猛藥
                        """
                        st.markdown(model.generate_content(prompt).text)
        except Exception as e:
            st.error(f"哎呀，檔案讀取失敗了！錯誤訊息：{e}")

# ----------------------------------------
# 分頁 3: 顧問對話室
# ----------------------------------------
with tab_chat:
    st.header("💬 AI 交易顧問對話室")

    chat_container = st.container(height=400)
    with chat_container:
        for msg in st.session_state.chat_messages:
            st.chat_message(msg["role"]).write(msg["content"])

    if prompt := st.chat_input("請問大師... (例如：請問現在台積電的法說會預期好嗎？)"):
        if not user_api_key:
            st.error("🚨 請先輸入 API Key 才能開啟對話喔！")
        else:
            st.chat_message("user").write(prompt)
            st.session_state.chat_messages.append({"role": "user", "content": prompt})

            latest_data_context = ""
            if st.session_state.stock_results:
                latest_data_context = "【目前關注標的最新即時數據】\n"
                for res in st.session_state.stock_results:
                    d = res["data"]
                    latest_data_context += f"- {d['display_name']}：最新收盤價 {d['current_price']:.2f}\n"

            today_date = datetime.now().strftime("%Y年%m月%d日")

            system_context = f"""
            系統設定提示：
            角色：{teacher_prompt_name}。邏輯：{selected_logic}。

            ⚠️【最高強制指令】：
            1. 今天是 {today_date}。推演未來時，請嚴格以此日期為基準！
            2. 當使用者問到特定股票的價格時，僅能參考下方的【目前關注標的最新即時數據】。
            但當使用者問到「基本面、法說會、財報、訂單」時，請動用你的知識庫給出專業的產業洞察！
            {latest_data_context}
            請用繁體中文，以專業、溫柔親切的語氣回答。
            """

            history_text = system_context + "\n\n--- 對話紀錄 ---\n"
            for m in st.session_state.chat_messages[-4:]:
                role_name = "使用者" if m["role"] == "user" else "AI大師"
                history_text += f"{role_name}：{m['content']}\n"

            with st.spinner("大師調閱資料中，等我一下下喔..."):
                try:
                    genai.configure(api_key=user_api_key)
                    model = genai.GenerativeModel('gemini-2.5-flash-lite')
                    response = model.generate_content(history_text)
                    st.chat_message("assistant").write(response.text)
                    st.session_state.chat_messages.append({"role": "assistant", "content": response.text})
                    st.rerun()
                except Exception as e:
                    st.error(f"連線失敗了。錯誤：{e}")

# ----------------------------------------
# 分頁 4: 產業推演與潛力雷達
# ----------------------------------------
with tab_predict:
    st.header("🔮 產業推演與潛力雷達 (基本面雙軌判定)")
    st.markdown("""
    真正的贏家是**「用基本面選股，用技術面找買點」**！
    即使一檔股票現在跌破均線 (技術面差)，只要它近期的法說會報喜、接單量暴增 (基本面強)，系統就會幫您抓出來，並標記為**「左側建倉的好機會」**喔！
    """)

    st.subheader("第一步：設定未來劇本")
    hot_trend = st.text_input("輸入目前市場最熱門的題材或新聞：", value="輝達 GB200 下半年量產，供應鏈接單狀況")

    if st.button("🧠 啟動 AI 基本面推演與抓股", type="primary"):
        if not user_api_key:
            st.error("🚨 預測未來需要極大的算力，記得先在左側輸入您的 API Key 喔！")
        else:
            with st.spinner("AI 大師正在為您翻閱各大法說會與財報預期..."):
                try:
                    genai.configure(api_key=user_api_key)
                    model = genai.GenerativeModel('gemini-2.5-flash-lite')
                    today_date = datetime.now().strftime("%Y年%m月%d日")

                    predict_prompt = f"""
                    你是華爾街頂級對沖基金經理人，精通基本面與產業鏈推演。
                    ⚠️【時間基準】：今天是 {today_date}。請嚴格以這個時間點為基準進行未來推演！

                    目前市場關注題材：「{hot_trend}」。
                    我們不看現在死板的股價！我們要看「未來」。
                    請找出 3 到 5 檔「目前股價可能還在跌或盤整，但在近期的法說會、財報預期、或是供應鏈接單量上，已經有明確利多與轉機」的台灣股票。

                    請務必在推薦中，具體列出對應的「台灣股市股票代號」(請直接寫出4碼數字)。

                    請用以下格式輸出：
                    ### 🔮 基本面與訂單推演結論
                    (簡述為什麼這些產業未來的基本面會爆發)

                    ### 💎 潛力標的與基本面亮點
                    1. **[公司名稱]** (代號：放入4碼數字) -> **財報/接單亮點**：[具體說明它的接單或法說會轉機是什麼]
                    2. **[公司名稱]** (代號：放入4碼數字) -> **財報/接單亮點**：[具體說明它的接單或法說會轉機是什麼]
                    """

                    result_text = model.generate_content(predict_prompt).text
                    st.session_state.prediction_result = result_text

                    extracted_tickers = list(set(re.findall(r'\b\d{4}\b', result_text)))
                    st.session_state.predicted_tickers = extracted_tickers

                except Exception as e:
                    st.error(f"推演過程遇到小狀況了：{e}")

    if st.session_state.prediction_result:
        st.info(st.session_state.prediction_result)
        st.success(f"🤖 太棒了！系統已經鎖定 {len(st.session_state.predicted_tickers)} 檔潛力股代號：{st.session_state.predicted_tickers}")

    st.markdown("---")
    st.subheader("第二步：基本面與技術面「雙軌判定」")

    if st.button("📡 啟動雙軌策略判定雷達", type="primary"):
        target_tickers = st.session_state.predicted_tickers
        if not target_tickers:
            st.warning("⚠️ 麻煩您先執行上方的「AI 基本面推演」，讓系統有股票代號可以掃描喔！")
        else:
            scan_results = []
            scan_bar = st.progress(0, text="正在啟動盲測引擎，融合技術面數據...")

            for i, t in enumerate(target_tickers):
                scan_bar.progress((i + 1) / len(target_tickers), text=f"正在幫您判定買點: {t}")
                try:
                    clean_ticker, candidates = get_yf_ticker_candidates(t)
                    df_scan = pd.DataFrame()
                    scan_yf_ticker = ""
                    
                    # 盲測引擎上線
                    for cand in candidates:
                        stock = yf.Ticker(cand)
                        df_scan = stock.history(period="3mo")
                        if len(df_scan) >= 30:
                            scan_yf_ticker = cand
                            break

                    if len(df_scan) < 30: continue

                    current_p = df_scan['Close'].iloc[-1]
                    ma_long_val = df_scan['Close'].rolling(long_ma).mean().iloc[-1]
                    bias_pct = ((current_p - ma_long_val) / ma_long_val) * 100

                    vol_5d_avg = df_scan['Volume'].tail(5).mean()
                    vol_20d_avg = df_scan['Volume'].shift(5).tail(20).mean()
                    vol_ratio = (vol_5d_avg / vol_20d_avg) if vol_20d_avg > 0 else 0

                    if bias_pct < -5:
                        status = "💎 嚴重低估 (符合基本面利多，適合左側建倉)"
                    elif -5 <= bias_pct <= 15 and vol_ratio >= 1.2:
                        status = "🚨 籌碼進場 (基本面發酵，右側起漲點)"
                    elif bias_pct > 15:
                        status = "🔥 已反映利多 (乖離過大，請小心追高)"
                    else:
                        status = "💤 默默吃貨中 (量縮打底，可分批佈局)"

                    comp_name = REVERSE_MAP.get(clean_ticker, stock.info.get('shortName', '未知名稱'))
                    if ".TWO" in scan_yf_ticker: comp_name += " (上/興櫃)"

                    scan_results.append({
                        "代號": clean_ticker, "公司名稱": comp_name, "收盤價": round(current_p, 2),
                        f"下緣均線({long_ma}MA)乖離(%)": round(bias_pct, 2),
                        "綜合策略判定 (基本面+技術面)": status
                    })
                except:
                    pass
                time.sleep(0.05)

            scan_bar.empty()

            if scan_results:
                df_stealth = pd.DataFrame(scan_results)
                st.write("📊 **雙軌策略判定報告：**")
                st.dataframe(df_stealth.style.applymap(
                    lambda x: 'background-color: #e6f7ff; color: #0050b3; font-weight: bold' if "嚴重低估" in str(x) 
                    else ('background-color: #ffcccc; color: black' if "籌碼進場" in str(x) else ''),
                    subset=['綜合策略判定 (基本面+技術面)']
                ), hide_index=True, use_container_width=True)
            else:
                st.error("⚠️ 掃描完畢，但找不到這些代號的有效技術面資料。")

# ----------------------------------------
# 🌟 分頁 5: 財報與法說會深度解析
# ----------------------------------------
with tab_finance:
    st.header("📑 財報與法說會深度解析")
    st.markdown("將您的資源集中在最核心的「基本面」，讓 AI 為您剖析公司體質與未來展望！")

    st.subheader("第一步：設定欲分析之目標公司")
    col_t1, col_t2 = st.columns([1, 2])
    with col_t1:
        target_company = st.text_input("輸入股票代號或名稱：", value="2330")
    
    with col_t2:
        st.write("")
        st.write("")
        if st.button("🌐 自動抓取最新財報關鍵數據"):
            with st.spinner("啟動盲測引擎，前往資料庫撈取綜合損益與資產負債數據..."):
                try:
                    c_ticker, candidates = get_yf_ticker_candidates(target_company)
                    
                    q_fin = pd.DataFrame()
                    c_yf_ticker = ""
                    # 盲測引擎上線
                    for cand in candidates:
                        comp_stock = yf.Ticker(cand)
                        q_fin = comp_stock.quarterly_financials
                        if not q_fin.empty:
                            c_yf_ticker = cand
                            break

                    if not q_fin.empty:
                        fin_str = f"【股票代號 {c_yf_ticker} 近期財務重點數據】\n"
                        fin_str += q_fin.head(10).to_string()
                        st.session_state.finance_data_str = fin_str
                        st.success(f"✅ 成功抓取 {target_company} 的近期財報數據！")
                        with st.expander("👀 點擊預覽原始數據"):
                            st.dataframe(q_fin.head(10))
                    else:
                        st.error(f"⚠️ 找不到「{target_company}」的財務數據！連盲測引擎都失敗了，請您直接在下方手動上傳財報喔！")
                except Exception as e:
                    st.error(f"抓取失敗：{e}")

    st.markdown("---")
    st.subheader("第二步：上傳法說會情報或財報分析 (選填)")
    st.markdown("您可以上傳法說會的逐字稿、重點整理新聞，或您自己收集的 `.txt` / `.csv` 分析報告。")
    uploaded_report = st.file_uploader("上傳補充分析檔案 (支援 .txt 或 .csv)：", type=["txt", "csv"], key="finance_report")
    
    report_text_content = ""
    if uploaded_report is not None:
        try:
            report_text_content = uploaded_report.getvalue().decode("utf-8")
            st.success("✅ 檔案讀取成功！")
            with st.expander("👀 點擊預覽檔案內容"):
                st.text(report_text_content[:500] + "...\n(以下省略)")
        except Exception as e:
            st.error(f"讀取檔案失敗：{e}")

    st.markdown("---")
    if st.button("🧠 啟動 AI 首席分析師進行深度評估", type="primary", use_container_width=True):
        if not user_api_key:
            st.error("🚨 記得先在左側輸入您的 API Key 喔！")
        elif not st.session_state.finance_data_str and not report_text_content:
            st.warning("⚠️ 您尚未抓取財報數據，也未上傳任何法說會情報。請至少完成其中一項再交給 AI 評估！")
        else:
            with st.spinner(f"【外資首席分析師】正在熬夜為您解讀 {target_company} 的財報與法說會內容..."):
                try:
                    genai.configure(api_key=user_api_key)
                    model = genai.GenerativeModel('gemini-2.5-flash-lite')
                    
                    prompt = f"""
                    你是頂級外資券商的首席分析師。
                    請深度分析以下公司 ({target_company}) 的近期財務數據與法說會情報。
                    
                    【系統抓取的近期財報數據】：
                    {st.session_state.finance_data_str if st.session_state.finance_data_str else "無提供"}
                    
                    【使用者上傳的法說會/補充資訊】：
                    {report_text_content if report_text_content else "無提供"}
                    
                    請從以下幾個維度進行專業且易懂的解析：
                    ### 📊 1. 獲利能力與體質檢查
                    (分析毛利、營收趨勢、是否有潛在的財務風險或轉機)
                    
                    ### 🎤 2. 法說會/情報亮點與隱憂
                    (針對使用者上傳的資訊，或是你所知曉的近期產業動態進行點評。戳破可能的大餅，指出真實的利多)
                    
                    ### 🎯 3. 綜合評等與操作策略
                    (給出明確的基本面評等：強烈買進 / 買進 / 中立持有 / 減碼 / 賣出，並附上具體的操作建議)
                    """
                    
                    response = model.generate_content(prompt)
                    st.markdown(response.text)
                    
                except Exception as e:
                    st.error(f"分析過程出現錯誤：{e}")
