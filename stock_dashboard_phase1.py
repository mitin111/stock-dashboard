import streamlit as st
from datetime import datetime
import yfinance as yf

def fetch_volatility(symbol):
    try:
        yf_symbol = symbol + ".NS"  # NSE symbols
        data = yf.download(yf_symbol, period="1d", interval="5m", progress=False)
        if data.empty:
            return 0.0
        day_high = data["High"].max()
        day_low = data["Low"].min()
        if day_low > 0:
            return round(((day_high - day_low) / day_low) * 100, 2)
        else:
            return 0.0
    except Exception:
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
        tgt = price * 1.10 if side == "BUY" else price * 0.90

        self.positions[symbol] = {
            "side": side,
            "entry_price": price,
            "quantity": qty,
            "stop_loss": sl,
            "target": tgt,
            "entry_time": time,
            "trail_sl": sl
        }

        self.dashboard.log_trade(symbol, side, price, qty, sl, tgt, time)
        self.dashboard.update_visuals(self.positions, indicators)


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


symbol = st.selectbox("Select Stock", sorted(APPROVED_STOCK_LIST))
price = st.number_input("Current Price", min_value=10.0)
y_close = st.number_input("Yesterday's Close", min_value=10.0)
first_candle_open = st.number_input("First Candle Open", min_value=10.0)
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

def fetch_live_data(symbol):
    try:
        yf_symbol = symbol + ".NS"
        data = yf.download(yf_symbol, period="2d", interval="5m", progress=False)

        if data.empty or len(data) < 2:
            return None

        latest_row = data.iloc[-1]

        # Get the first 5-min candle for the day (usually 09:15 AM)
        first_candle = data[data.index.time == datetime.strptime("09:15", "%H:%M").time()]
        first_open = first_candle["Open"].iloc[0] if not first_candle.empty else latest_row["Open"]

        return {
            "price": round(latest_row["Close"], 2),
            "yesterday_close": round(data.iloc[-2]["Close"], 2),
            "first_open": round(first_open, 2)
        }
    except Exception as e:
        st.error(f"⚠️ Error fetching data for {symbol}: {e}")
        return None

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

        engine.process_trade(
            symbol,
            live_data["price"],
            live_data["yesterday_close"],
            live_data["first_open"],
            indicators,
            quantity_config,
            current_time,
            available_balance
        )

def calculate_indicators(live_data, symbol, pac_length, use_ha, min_vol_required):
    try:
        yf_symbol = symbol + ".NS"
        data = yf.download(yf_symbol, period="2d", interval="5m", progress=False)

        if data.empty or len(data) < pac_length:
            return None  # Not enough data

        df = calculate_pac_emas(data, length=pac_length, use_heikin_ashi=use_ha)
        latest = df.iloc[-1]
        price = live_data["price"]

        return {
            "atr_trail": "Buy",  # TODO: Replace with actual ATR logic
            "tkp_trm": "Buy",    # TODO: Replace with actual TRM logic
            "macd_hist": 0.8,    # TODO: Replace with real MACD Histogram
            "above_pac": price > latest['PAC_C'],
            "volatility": fetch_volatility(symbol),
            "pac_band_lower": round(latest['PAC_L'], 2),
            "pac_band_upper": round(latest['PAC_U'], 2),
            "min_vol_required": min_vol_required
        }
    except Exception as e:
        st.error(f"⚠️ Indicator calculation failed for {symbol}: {e}")
        return None

        indicators = calculate_indicators(live_data)

        engine.process_trade(
            symbol,
            live_data["price"],
            live_data["yesterday_close"],
            live_data["first_open"],
            indicators,
            quantity_config,
            current_time,
            available_balance
        )

if st.button("❌ Auto Exit All @ 15:12"):
    engine.auto_exit_positions(current_time)
if st.button("🔄 Update Trailing Stop-Loss"):
    engine.update_trailing_sl(symbol, price)




