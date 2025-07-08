import streamlit as st
from datetime import datetime

from prostocks_connector import ProStocksAPI  # ✅ NEW IMPORT

ps_api = ProStocksAPI()  # ✅ Initialize once
ps_api.login()           # ✅ Login once

def fetch_volatility(symbol):
    try:
        # Fetch 1-day 5-min candle data from ProStocks
        candles = ps_api.get_candles(symbol, interval="5minute", days=1)
        if not candles or len(candles) == 0:
            return 0.0

        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]

        day_high = max(highs)
        day_low = min(lows)

        if day_low > 0:
            return round(((day_high - day_low) / day_low) * 100, 2)
        else:
            return 0.0

    except Exception as e:
        st.error(f"⚠️ ProStocks Volatility Error for {symbol}: {e}")
        return 0.0



# ====== Trading Engine Logic with Whitelist ======


APPROVED_STOCK_LIST = [
    "LTFOODS", "HSCL", "REDINGTON", "FIRSTCRY", "GSPL", "ATGL", "HEG", "RAYMOND", "GUJGASLTD",
    "TRITURBINE", "ADANIPOWER", "ELECON", "JIOFIN", "USHAMART", "INDIACEM", "HINDPETRO", "SONATSOFTW",
    "HONASA", "BSOFT", "KARURVYSYA", "SYRMA", "IGIL", "GRAPHITE", "BLS", "IGL", "NATIONALUM",
    "ENGINERSIN", "MANAPPURAM", "SWIGGY", "GODIGIT", "DBREALTY", "NAVA", "TRIVENI", "SWSOLAR", "BERGEPAINT",
    "JINDALSAW", "ABCAPITAL", "ANANTRAJ", "GMDCLTD", "PETRONET", "VEDL", "HINDCOPPER", "NYKAA", "RBLBANK",
    "AKUMS", "HUDCO", "STARHEALTH", "EIHOTEL", "SCI", "OIL", "CGPOWER", "NLCINDIA", "LTF", "AWL", "RVNL",
    "SUMICHEM", "KANSAINER", "HBLENGINE", "CHENNPETRO", "LICHSGFIN", "ELGIEQUIP", "KALYANKJIL", "PRAJIND",
    "KIMS", "INDUSTOWER", "INDIANB", "VGUARD", "JSL", "AMBUJACEM", "TARIL", "GAIL", "RHIM", "IRCON", "ASTERDM",
    "BANKBARODA", "POONAWALLA", "M&MFIN", "KNRCON", "DELHIVERY", "RKFORGE", "POWERGRID", "JSWENERGY", "INDGN",
    "PCBL", "IEX", "CASTROLIND", "IIFL", "SWANENERGY", "JKTYRE", "JYOTHYLAB", "CUB", "NIACL", "RAILTEL",
    "ETERNAL", "GPIL", "HAPPSTMNDS", "GNFC", "RECLTD", "PNCINFRA", "WIPRO", "BPCL", "NTPC", "JSWINFRA", "PFC",
    "SYNGENE", "JWL", "BANDHANBNK", "BHEL", "CGCL", "INOXWIND", "RITES", "FSL", "MINDACORP", "LATENTVIEW",
    "AADHARHFC", "GICRE", "AFCONS", "CROMPTON", "FEDERALBNK", "BEL", "PPLPHARMA", "ONGC", "JBMA", "UPL", "NCC",
    "CAMPUS", "GRANULES", "APOLLOTYRE", "VBL", "SARDAEN", "FINPIPE", "SONACOMS", "BIOCON", "AARTIIND",
    "ACMESOLAR", "BALRAMCHIN", "EXIDEIND", "TATAPOWER", "SHRIRAMFIN", "DEVYANI", "CHAMBLFERT", "HINDZINC",
    "COALINDIA", "DABUR", "SAPPHIRE", "ICICIPRULI", "HINDALCO", "TATAMOTORS", "ASHOKLEY", "CESC", "ITC"
]


class TradingEngine:
    def __init__(self, dashboard, trading_start, trading_end, cutoff_time, auto_exit_time):
        self.dashboard = dashboard
        self.trading_start = trading_start.strftime("%H:%M")
        self.trading_end = trading_end.strftime("%H:%M")
        self.cutoff_time = cutoff_time.strftime("%H:%M")
        self.auto_exit_time = auto_exit_time.strftime("%H:%M")
        self.positions = {}

    def is_buy_time_allowed(self, current_time):
        return self.trading_start <= current_time <= self.cutoff_time

    def is_sell_time_allowed(self, current_time):
        return self.trading_start <= current_time <= self.cutoff_time

    def check_margin(self, stock_price, quantity, available_balance):
        return available_balance >= (stock_price * quantity) / 4

    def get_quantity(self, price, qcfg):
        if 170 <= price <= 200:
            return qcfg["Q1"]
        elif 201 <= price <= 400:
            return qcfg["Q2"]
        elif 401 <= price <= 600:
            return qcfg["Q3"]
        elif 601 <= price <= 800:
            return qcfg["Q4"]
        elif 801 <= price <= 1000:
            return qcfg["Q5"]
        elif price > 1000:
            return qcfg["Q6"]
        return 0  # fallback

    def process_trade(self, symbol, price, y_close, open, indicators, qcfg, time, balance):
        if symbol not in APPROVED_STOCK_LIST or symbol in self.positions:
            return

        qty = self.get_quantity(price, qcfg)

        if qty == 0:
            st.warning(f"⚠️ No quantity set for price ₹{price} — skipping order.")
            return

        if not self.check_margin(price, qty, balance):
            st.warning(f"❌ Not enough margin for {symbol} — required: ₹{(price * qty) / 4:.2f}")
            return

        if self.dashboard.auto_buy and self.dashboard.master_auto:
            if self.evaluate_buy_conditions(indicators, time, y_close, open):
                self.place_order("BUY", symbol, price, qty, indicators, time)

        if self.dashboard.auto_sell and self.dashboard.master_auto:
            if self.evaluate_sell_conditions(indicators, time, y_close, open):
                self.place_order("SELL", symbol, price, qty, indicators, time)

    def should_skip_gap_up(self, open, close):
        return ((open - close) / close) * 100 >= 2

    def should_skip_gap_down(self, open, close):
        return ((close - open) / close) * 100 >= 2

    def evaluate_buy_conditions(self, indicators, current_time, y_close, open):
        return (
            self.is_buy_time_allowed(current_time) and
            not self.should_skip_gap_up(open, y_close) and
            indicators["atr_trail"] == "Buy" and
            indicators["tkp_trm"] == "Buy" and
            indicators["macd_hist"] > 0 and
            indicators["above_pac"] and
            indicators["volatility"] >= indicators["min_vol_required"]
        )



    def evaluate_sell_conditions(self, indicators, current_time, y_close, open):
        return (
            self.is_sell_time_allowed(current_time) and
            not self.should_skip_gap_down(open, y_close) and
            indicators["atr_trail"] == "Sell" and
            indicators["tkp_trm"] == "Sell" and
            indicators["macd_hist"] < 0 and
            not indicators["above_pac"] and
            indicators["volatility"] >= indicators["min_vol_required"]
        )
    def place_order(self, side, symbol, price, qty, indicators, time):
        sl = indicators["pac_band_lower"] if side == "BUY" else indicators["pac_band_upper"]
        tgt = round(price * 1.10, 2) if side == "BUY" else round(price * 0.90, 2)

        st.info(f"📤 Placing {side} order for {symbol} at ₹{price} | SL: ₹{sl}, Target: ₹{tgt}")

        order_response = ps_api.place_bracket_order(
            symbol=symbol,
            qty=qty,
            price=price,
            sl=sl,
            target=tgt,
            side=side
        )

        if order_response:
            self.positions[symbol] = {
                "entry_price": price,
                "stop_loss": sl,
                "trail_sl": sl,
                "target": tgt,
                "side": side,
                "entry_time": time
            }
            self.dashboard.log_trade(symbol, side, price, qty, sl, tgt, time)
        else:
            st.error(f"❌ Failed to place order for {symbol}")


    def auto_exit_positions(self, current_time):
        if current_time == self.auto_exit_time:
            for stock in list(self.positions):
                self.dashboard.close_position(stock, self.positions[stock])
                del self.positions[stock]

    def update_trailing_sl(self, symbol, current_price):
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]
        entry = float(pos["entry_price"])
        time_str = pos["entry_time"]
        hr, mn = map(int, time_str.split(":"))
        entry_time = hr * 60 + mn
        price_change = ((current_price - entry) / entry) * 100 if pos["side"] == "BUY" else ((entry - current_price) / entry) * 100

        if entry_time <= 12 * 60:
            rules = [(1, 1), (3, 1.5), (5, 2)]
        else:
            rules = [(0.75, 0.75), (2, 0.5), (5, 1)]

        new_sl = pos["stop_loss"]
        for level, trail in rules:
            if price_change >= level:
                if pos["side"] == "BUY":
                    new_sl = max(new_sl, entry * (1 + (price_change - trail) / 100))
                else:
                    new_sl = min(new_sl, entry * (1 - (price_change - trail) / 100))

        if (pos["side"] == "BUY" and new_sl > pos["trail_sl"]) or (pos["side"] == "SELL" and new_sl < pos["trail_sl"]):
            self.positions[symbol]["trail_sl"] = round(new_sl, 2)
            st.info(f"🔄 Trailing SL updated for {symbol}: ₹{round(new_sl, 2)}")
import pandas as pd

st.subheader("📊 Real-Time Stock Signal Table")



# ====== Dummy Dashboard for UI Feedback ======
class Dashboard:
    def __init__(self):
        self.auto_buy = True
        self.auto_sell = True
        self.master_auto = True

    def log_trade(self, *args): st.success(f"Trade Log: {args}")
    def update_visuals(self, positions, indicators):
        st.info("Positions:"); st.json(positions)
        st.subheader("Indicators"); st.json(indicators)
    def close_position(self, symbol, pos): st.warning(f"Closed {symbol}: {pos}")


# ====== Streamlit UI ======
dashboard = Dashboard()
min_vol_required = st.number_input(
    "🔧 Min Volatility % Required", min_value=0.0, value=2.0, step=0.1
)


st.set_page_config(page_title="Auto Intraday Trading", layout="wide")
st.title("📈 Automated Intraday Trading System")
# ==== Step 0: Dashboard Controls for Buy/Sell Toggles ====
with st.expander("⚙️ Step 0: Control Panel", expanded=True):
    dashboard.master_auto = st.toggle("✅ Master Auto Buy + Sell", value=True)
    dashboard.auto_buy = st.toggle("▶️ Auto Buy Enabled", value=True)
    dashboard.auto_sell = st.toggle("🔽 Auto Sell Enabled", value=True)

with st.expander("🕒 Step 1: Time Configuration", expanded=True):
    trading_start = st.time_input("Trading Start", value=datetime.strptime("09:15", "%H:%M").time())
    trading_end = st.time_input("Trading End", value=datetime.strptime("15:15", "%H:%M").time())
    cutoff_time = st.time_input("No Buy/Sell After", value=datetime.strptime("14:50", "%H:%M").time())
    auto_exit_time = st.time_input("Auto Exit All Positions At", value=datetime.strptime("15:12", "%H:%M").time())
    chart_tf = st.selectbox("Chart Timeframe", ["5-Minute", "15-Minute", "30-Minute"], index=0)
engine = TradingEngine(dashboard, trading_start, trading_end, cutoff_time, auto_exit_time)
with st.expander("🟦 Step 2: Indicator Settings (Click to Expand)", expanded=True):
    st.subheader("📌 TKP TRM Settings")
    tsi_long = st.slider("TSI Long Length", 5, 50, 25)
    tsi_short = st.slider("TSI Short Length", 1, 20, 5)
    tsi_signal = st.slider("TSI Signal Length", 1, 30, 14)
    rsi_length = st.slider("RSI Length", 2, 20, 5)
    rsi_buy = st.slider("RSI Buy Level", 10, 90, 50)
    rsi_sell = st.slider("RSI Sell Level", 10, 90, 50)

    st.subheader("📌 PAC EMA Settings")
    pac_length = st.slider("PAC Channel Length", 5, 55, 34)
    pac_source = st.selectbox("PAC Source", ["close", "open", "hl2", "heikin_ashi"], index=0)
    pac_use_ha = st.checkbox("Use Heikin Ashi Candles", value=True)

    st.subheader("📌 ATR Settings")
    atr_fast_period = st.slider("Fast ATR Period", 1, 20, 5)
    atr_fast_mult = st.number_input("Fast Multiplier", value=0.5)
    atr_slow_period = st.slider("Slow ATR Period", 5, 30, 10)
    atr_slow_mult = st.number_input("Slow Multiplier", value=3.0)
    atr_source_pos = st.slider("Position Source", 1, 100, 50)

    st.subheader("📌 MACD Histogram Settings")
    macd_fast = st.slider("MACD Fast Length", 5, 150, 90)
    macd_slow = st.slider("MACD Slow Length", 20, 300, 210)
    macd_signal = st.slider("MACD Signal Smoothing", 3, 20, 9)
    macd_source = st.selectbox("MACD Source", ["close", "open", "hl2", "heikin_ashi"], index=0)
    macd_ma_type = st.selectbox("MACD MA Type", ["EMA", "SMA"], index=0)
    # === ✅ Run Signal Scan After All Inputs Are Loaded ===
from prostocks_connector import ProStocksAPI

# Initialize and login once
ps_api = ProStocksAPI()
ps_api.login()

def fetch_live_data(symbol):
    try:
        ltp = ps_api.get_ltp(symbol)
        if ltp is None:
            return None

        # Approximate other values with same price since GetQuotes doesn't return OHLC
        return {
            "price": round(ltp, 2),
            "yesterday_close": round(ltp, 2),
            "first_open": round(ltp, 2)
        }
    except Exception as e:
        st.error(f"⚠️ Error fetching ProStocks data for {symbol}: {e}")
        return None

all_rows = []
for symbol in APPROVED_STOCK_LIST:
    live_data = fetch_live_data(symbol)
    if not live_data:
        continue

    



symbol = st.selectbox("Select Stock", sorted(APPROVED_STOCK_LIST), key="select_stock_main_1")

price = st.number_input("Current Price", min_value=10.0, key="price_input_final")
y_close = st.number_input("Yesterday's Close", min_value=10.0, key="y_close_input_final")
first_candle_open = st.number_input("First Candle Open", min_value=10.0, key="open_input_final")

current_time = st.text_input("Current Time (HH:MM)", value=datetime.now().strftime("%H:%M"))
# ✅ Calculate volatility from YFinance
volatility = fetch_volatility(symbol)
indicators = {
    "atr_trail": st.selectbox("ATR Trail", ["Buy", "Sell"], key="atr_trail_input"),
    "tkp_trm": st.selectbox("TKP TRM", ["Buy", "Sell"], key="tkp_trm_input"),
    "macd_hist": st.number_input("MACD Histogram", step=0.1, key="macd_hist_input"),
    "above_pac": st.checkbox("Above PAC EMA", value=True, key="above_pac_input"),
    "volatility": volatility,
    "pac_band_lower": st.number_input("PAC Band Lower", min_value=0.0, key="pac_band_lower_input"),
    "pac_band_upper": st.number_input("PAC Band Upper", min_value=0.0, key="pac_band_upper_input"),
    "min_vol_required": min_vol_required
}



engine = TradingEngine(dashboard, trading_start, trading_end, cutoff_time, auto_exit_time)

with st.expander("🧮 Quantity Mapping by Price Range", expanded=True):
    q1 = st.slider("Q1 (₹170–200)", 0, 1000, 100)
    q2 = st.slider("Q2 (₹201–400)", 0, 1000, 80)
    q3 = st.slider("Q3 (₹401–600)", 0, 1000, 60)
    q4 = st.slider("Q4 (₹601–800)", 0, 1000, 40)
    q5 = st.slider("Q5 (₹801–1000)", 0, 1000, 30)
    q6 = st.slider("Q6 (Above ₹1000)", 0, 1000, 20)

quantity_config = {
    "Q1": q1,
    "Q2": q2,
    "Q3": q3,
    "Q4": q4,
    "Q5": q5,
    "Q6": q6,
}


available_balance = st.number_input("Available Balance ₹", min_value=0.0, value=100000.0)

import schedule
import time
def calculate_macd(df, fast_length=12, slow_length=26, signal_length=9, 
                   src_col='Close', 
                   ma_type_macd='EMA', 
                   ma_type_signal='EMA'):
    df = df.copy()
    src = df[src_col]

    def ma(series, length, method):
        return series.ewm(span=length, adjust=False).mean() if method == 'EMA' else series.rolling(window=length).mean()

    fast_ma = ma(src, fast_length, ma_type_macd)
    slow_ma = ma(src, slow_length, ma_type_macd)
    df['MACD'] = fast_ma - slow_ma
    df['Signal'] = ma(df['MACD'], signal_length, ma_type_signal)
    df['Histogram'] = df['MACD'] - df['Signal']

    return df[['MACD', 'Signal', 'Histogram']]

def calculate_heikin_ashi(df):
    ha_df = df.copy()
    ha_df['HA_Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4

    ha_open = [(df['Open'].iloc[0] + df['Close'].iloc[0]) / 2]
    for i in range(1, len(df)):
        ha_open.append((ha_open[i - 1] + ha_df['HA_Close'].iloc[i - 1]) / 2)
    ha_df['HA_Open'] = ha_open
    ha_df['HA_High'] = ha_df[['High', 'HA_Open', 'HA_Close']].max(axis=1)
    ha_df['HA_Low'] = ha_df[['Low', 'HA_Open', 'HA_Close']].min(axis=1)

    return ha_df
def calculate_atr_trailing_stop(df, fast_period=5, fast_mult=0.5, slow_period=10, slow_mult=3):
    df = df.copy()
    df["ATR_FAST"] = df["High"].rolling(fast_period).max() - df["Low"].rolling(fast_period).min()
    df["ATR_FAST"] *= fast_mult

    df["ATR_SLOW"] = df["High"].rolling(slow_period).max() - df["Low"].rolling(slow_period).min()
    df["ATR_SLOW"] *= slow_mult

    trail1 = []
    trail2 = []
    buy = []
    sell = []

    last_trail1 = df["Close"].iloc[0]
    last_trail2 = df["Close"].iloc[0]

    for i in range(len(df)):
        close = df["Close"].iloc[i]
        atr1 = df["ATR_FAST"].iloc[i]
        atr2 = df["ATR_SLOW"].iloc[i]

        # --- Fast trail
        if close > last_trail1:
            trail_1 = max(last_trail1, close - atr1)
        else:
            trail_1 = min(last_trail1, close + atr1)

        # --- Slow trail
        if close > last_trail2:
            trail_2 = max(last_trail2, close - atr2)
        else:
            trail_2 = min(last_trail2, close + atr2)

        last_trail1 = trail_1
        last_trail2 = trail_2

        trail1.append(trail_1)
        trail2.append(trail_2)
        buy.append(trail_1 > trail_2 and (i > 0 and trail1[i-1] <= trail2[i-1]))
        sell.append(trail_1 < trail_2 and (i > 0 and trail1[i-1] >= trail2[i-1]))

    df["Trail1"] = trail1
    df["Trail2"] = trail2
    df["Buy"] = buy
    df["Sell"] = sell

    return df

def calculate_pac_emas(df, length=34, use_heikin_ashi=True):
    if use_heikin_ashi:
        df = calculate_heikin_ashi(df)
        close_col, high_col, low_col = 'HA_Close', 'HA_High', 'HA_Low'
    else:
        close_col, high_col, low_col = 'Close', 'High', 'Low'

    df['PAC_C'] = df[close_col].ewm(span=length, adjust=False).mean()
    df['PAC_U'] = df[high_col].ewm(span=length, adjust=False).mean()
    df['PAC_L'] = df[low_col].ewm(span=length, adjust=False).mean()

    return df

def run_engine_for_all():
    current_time = datetime.now().strftime("%H:%M")
    for symbol in APPROVED_STOCK_LIST:
        live_data = fetch_live_data(symbol)
        if not live_data:
            continue

        indicators = calculate_indicators(
            live_data,
            symbol,
            pac_length=pac_length,
            use_ha=pac_use_ha,
            min_vol_required=min_vol_required
        )

        if indicators is None:
            continue

        condition_buy = engine.evaluate_buy_conditions(
            indicators, current_time, live_data["yesterday_close"], live_data["first_open"]
        )
        condition_sell = engine.evaluate_sell_conditions(
            indicators, current_time, live_data["yesterday_close"], live_data["first_open"]
        )

        all_rows.append({
            "Symbol": symbol,
            "Price": live_data["price"],
            "ATR Trail": indicators["atr_trail"],
            "TKP TRM": indicators["tkp_trm"],
            "MACD Hist": round(indicators["macd_hist"], 2),
            "PAC Above": indicators["above_pac"],
            "Volatility %": round(indicators["volatility"], 2),
            "PAC Lower": indicators["pac_band_lower"],
            "PAC Upper": indicators["pac_band_upper"],
            "BUY Signal": "✅" if condition_buy else "",
            "SELL Signal": "❌" if condition_sell else ""
        })

if all_rows:
    df = pd.DataFrame(all_rows)
    st.dataframe(df.style.applymap(
        lambda x: "background-color: #d4f4dd" if x == "✅" else ("background-color: #fcdede" if x == "❌" else "")
    , subset=["BUY Signal", "SELL Signal"]), height=800, use_container_width=True)
else:
    st.warning("⚠️ No data to display. Please check your connection or time settings.")
       
   
def calculate_tkp_trm(df, tsi_long=25, tsi_short=5, tsi_signal_len=14, rsi_len=5, rsi_buy=50, rsi_sell=50):
    """
    TKP TRM Calculation based on TSI + RSI logic.
    Returns: "Buy", "Sell", or "Neutral"
    """
    df = df.copy()
    close = df["Close"]

    # TSI (True Strength Index)
    pc = close.diff()
    first_smooth = pc.ewm(span=tsi_long, adjust=False).mean()
    double_smoothed_pc = first_smooth.ewm(span=tsi_short, adjust=False).mean()

    abs_pc = pc.abs()
    first_smooth_abs = abs_pc.ewm(span=tsi_long, adjust=False).mean()
    double_smoothed_abs_pc = first_smooth_abs.ewm(span=tsi_short, adjust=False).mean()

    tsi = 100 * (double_smoothed_pc / double_smoothed_abs_pc)
    tsi_signal = tsi.ewm(span=tsi_signal_len, adjust=False).mean()

    # RSI (Wilder's RMA)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / rsi_len, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / rsi_len, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    latest_tsi = tsi.iloc[-1]
    latest_signal = tsi_signal.iloc[-1]
    latest_rsi = rsi.iloc[-1]

    if latest_tsi > latest_signal and latest_rsi > rsi_buy:
        return "Buy"
    elif latest_tsi < latest_signal and latest_rsi < rsi_sell:
        return "Sell"
    else:
        return "Neutral"

def calculate_indicators(live_data, symbol, pac_length, use_ha, min_vol_required):
    try:
        yf_symbol = symbol + ".NS"
        data = yf.download(yf_symbol, period="2d", interval="5m", progress=False)

        if data.empty or len(data) < pac_length:
            return None  # Not enough data

        df = calculate_pac_emas(data, length=pac_length, use_heikin_ashi=use_ha)
        latest = df.iloc[-1]
        price = live_data["price"]

               # ✅ Apply TKP TRM
        tkp_trm_signal = calculate_tkp_trm(
            data,
            tsi_long=tsi_long,
            tsi_short=tsi_short,
            tsi_signal_len=tsi_signal,
            rsi_len=rsi_length,
            rsi_buy=rsi_buy,
            rsi_sell=rsi_sell
        )

                # ✅ Apply ATR Trailing Stop
        atr_df = calculate_atr_trailing_stop(data)
        atr_signal = "Buy" if atr_df.iloc[-1]["Buy"] else "Sell" if atr_df.iloc[-1]["Sell"] else "Neutral"

               # ✅ MACD Histogram Calculation
        macd_df = calculate_macd(
            data,
            fast_length=macd_fast,
            slow_length=macd_slow,
            signal_length=macd_signal,
            src_col=macd_source.lower().capitalize(),
            ma_type_macd=macd_ma_type,
            ma_type_signal=macd_ma_type
        )
        macd_hist = macd_df["Histogram"].iloc[-1]

        return {
            "atr_trail": atr_signal,
            "tkp_trm": tkp_trm_signal,
            "macd_hist": round(macd_hist, 3),
            "above_pac": price > latest['PAC_C'],
            "volatility": fetch_volatility(symbol),
            "pac_band_lower": round(latest['PAC_L'], 2),
            "pac_band_upper": round(latest['PAC_U'], 2),
            "min_vol_required": min_vol_required
        }


    
    except Exception as e:
        st.error(f"⚠️ Error calculating indicators for {symbol}: {e}")
        return None



symbol = st.selectbox("Select Stock", sorted(APPROVED_STOCK_LIST), key="select_stock_main_2")


price = st.number_input("Current Price", min_value=10.0)

if st.button("❌ Auto Exit All @ 15:12"):
    engine.auto_exit_positions(current_time)
if st.button("🔄 Update Trailing Stop-Loss"):
    engine.update_trailing_sl(symbol, price)




