import streamlit as st
from datetime import datetime

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
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.positions = {}

    def is_buy_time_allowed(self, current_time): return "09:15" <= current_time <= "14:50"
    def is_sell_time_allowed(self, current_time): return "09:15" <= current_time <= "14:50"

    def check_margin(self, stock_price, quantity, available_balance):
        return available_balance >= (stock_price * quantity) / 4

    def get_quantity(self, stock_price, qcfg):
        return (
            qcfg["Q1"] if 170 <= stock_price <= 200 else
            qcfg["Q2"] if 201 <= stock_price <= 400 else
            qcfg["Q3"] if 401 <= stock_price <= 600 else
            qcfg["Q4"] if 601 <= stock_price <= 800 else
            qcfg["Q5"] if 801 <= stock_price <= 1000 else
            qcfg["Q6"] if stock_price > 1000 else 0
        )

    def should_skip_gap_up(self, open, close): return ((open - close) / close) * 100 >= 2
    def should_skip_gap_down(self, open, close): return ((close - open) / close) * 100 >= 2

    def evaluate_buy_conditions(self, indicators, current_time, y_close, open):
        return (
            self.is_buy_time_allowed(current_time) and
            not self.should_skip_gap_up(open, y_close) and
            indicators["atr_trail"] == "Buy" and
            indicators["tkp_trm"] == "Buy" and
            indicators["macd_hist"] > 0 and
            indicators["above_pac"] and
            indicators["volatility"] >= 2
        )

    def evaluate_sell_conditions(self, indicators, current_time, y_close, open):
        return (
            self.is_sell_time_allowed(current_time) and
            not self.should_skip_gap_down(open, y_close) and
            indicators["atr_trail"] == "Sell" and
            indicators["tkp_trm"] == "Sell" and
            indicators["macd_hist"] < 0 and
            not indicators["above_pac"] and
            indicators["volatility"] >= 2
        )

    def process_trade(self, symbol, price, y_close, open, indicators, qcfg, time, balance):
        if symbol not in APPROVED_STOCK_LIST or symbol in self.positions: return
        qty = self.get_quantity(price, qcfg)
        if not self.check_margin(price, qty, balance): return

        if self.dashboard.auto_buy and self.dashboard.master_auto:
            if self.evaluate_buy_conditions(indicators, time, y_close, open):
                self.place_order("BUY", symbol, price, qty, indicators, time)
        if self.dashboard.auto_sell and self.dashboard.master_auto:
            if self.evaluate_sell_conditions(indicators, time, y_close, open):
                self.place_order("SELL", symbol, price, qty, indicators, time)

    def place_order(self, side, symbol, price, qty, indicators, time):
        sl = indicators["pac_band_lower"] if side == "BUY" else indicators["pac_band_upper"]
        tgt = price * 1.10 if side == "BUY" else price * 0.90
        self.positions[symbol] = {"side": side, "entry_price": price, "quantity": qty, "stop_loss": sl, "target": tgt, "entry_time": time}
        self.dashboard.log_trade(symbol, side, price, qty, sl, tgt, time)
        self.dashboard.update_visuals(self.positions, indicators)

    def auto_exit_positions(self, current_time):
        if current_time == "15:12":
            for stock in list(self.positions):
                self.dashboard.close_position(stock, self.positions[stock])
                del self.positions[stock]

# ====== Dummy Dashboard for UI Feedback ======
class Dashboard:
    auto_buy = True
    auto_sell = True
    master_auto = True
    def log_trade(self, *args): st.success(f"Trade Log: {args}")
    def update_visuals(self, positions, indicators):
        st.info("Positions:"); st.json(positions)
        st.subheader("Indicators"); st.json(indicators)
    def close_position(self, symbol, pos): st.warning(f"Closed {symbol}: {pos}")

# ====== Streamlit UI ======
dashboard = Dashboard()
engine = TradingEngine(dashboard)

st.set_page_config(page_title="Auto Intraday Trading", layout="wide")
st.title("📈 Automated Intraday Trading System")
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

indicators = {
    "atr_trail": st.selectbox("ATR Trail", ["Buy", "Sell"]),
    "tkp_trm": st.selectbox("TKP TRM", ["Buy", "Sell"]),
    "macd_hist": st.number_input("MACD Histogram", step=0.1),
    "above_pac": st.checkbox("Above PAC EMA", value=True),
    "volatility": st.number_input("Volatility %", min_value=0.0, step=0.1),
    "pac_band_lower": st.number_input("PAC Band Lower", min_value=0.0),
    "pac_band_upper": st.number_input("PAC Band Upper", min_value=0.0),
}

quantity_config = {"Q1": 100, "Q2": 80, "Q3": 60, "Q4": 40, "Q5": 30, "Q6": 20}
available_balance = st.number_input("Available Balance ₹", min_value=0.0, value=100000.0)

if st.button("🔁 Run Trade Engine"):
    engine.process_trade(
        symbol, price, y_close, first_candle_open,
        indicators, quantity_config, current_time,
        available_balance
    )

if st.button("❌ Auto Exit All @ 15:12"):
    engine.auto_exit_positions(current_time)

