import streamlit as st
from datetime import datetime
# intraday_trading_engine.py
# Complete implementation of BUY/SELL system for whitelisted stocks with dashboard integration controls

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

    def is_within_trading_time(self, current_time):
        return "09:15" <= current_time <= "15:15"

    def is_buy_time_allowed(self, current_time):
        return "09:15" <= current_time <= "14:50"

    def is_sell_time_allowed(self, current_time):
        return "09:15" <= current_time <= "14:50"

    def check_margin(self, stock_price, quantity, available_balance):
        required_margin = (stock_price * quantity) / 4
        return available_balance >= required_margin

    def get_quantity(self, stock_price, quantity_config):
        if 170 <= stock_price <= 200:
            return quantity_config["Q1"]
        elif 201 <= stock_price <= 400:
            return quantity_config["Q2"]
        elif 401 <= stock_price <= 600:
            return quantity_config["Q3"]
        elif 601 <= stock_price <= 800:
            return quantity_config["Q4"]
        elif 801 <= stock_price <= 1000:
            return quantity_config["Q5"]
        elif stock_price > 1000:
            return quantity_config["Q6"]
        else:
            return 0

    def should_skip_gap_up(self, first_candle_open, y_close):
        return ((first_candle_open - y_close) / y_close) * 100 >= 2

    def should_skip_gap_down(self, first_candle_open, y_close):
        return ((y_close - first_candle_open) / y_close) * 100 >= 2

    def evaluate_buy_conditions(self, indicators, current_time, y_close, first_candle_open):
        if not self.is_buy_time_allowed(current_time):
            return False
        if self.should_skip_gap_up(first_candle_open, y_close):
            return False

        return (
            indicators["atr_trail"] == "Buy" and
            indicators["tkp_trm"] == "Buy" and
            indicators["macd_hist"] > 0 and
            indicators["above_pac"] and
            indicators["volatility"] >= 2
        )

    def evaluate_sell_conditions(self, indicators, current_time, y_close, first_candle_open):
        if not self.is_sell_time_allowed(current_time):
            return False
        if self.should_skip_gap_down(first_candle_open, y_close):
            return False

        return (
            indicators["atr_trail"] == "Sell" and
            indicators["tkp_trm"] == "Sell" and
            indicators["macd_hist"] < 0 and
            not indicators["above_pac"] and
            indicators["volatility"] >= 2
        )

    def process_trade(self, stock_symbol, stock_price, y_close, first_candle_open, indicators, quantity_config, current_time, available_balance):
        if stock_symbol not in APPROVED_STOCK_LIST:
            return

        if stock_symbol in self.positions:
            return  # position already open

        quantity = self.get_quantity(stock_price, quantity_config)
        if not self.check_margin(stock_price, quantity, available_balance):
            return

        if self.dashboard.auto_buy and self.dashboard.master_auto:
            if self.evaluate_buy_conditions(indicators, current_time, y_close, first_candle_open):
                self.place_order("BUY", stock_symbol, stock_price, quantity, indicators, current_time)

        if self.dashboard.auto_sell and self.dashboard.master_auto:
            if self.evaluate_sell_conditions(indicators, current_time, y_close, first_candle_open):
                self.place_order("SELL", stock_symbol, stock_price, quantity, indicators, current_time)

    def place_order(self, side, stock_symbol, stock_price, quantity, indicators, current_time):
        if side == "BUY":
            stop_loss = indicators["pac_band_lower"]
            target = stock_price * 1.10
        else:
            stop_loss = indicators["pac_band_upper"]
            target = stock_price * 0.90

        self.positions[stock_symbol] = {
            "side": side,
            "entry_price": stock_price,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "target": target,
            "entry_time": current_time,
        }

        self.dashboard.log_trade(stock_symbol, side, stock_price, quantity, stop_loss, target, current_time)
        self.dashboard.update_visuals(self.positions, indicators)

    def update_trailing_sl(self, stock_symbol, current_price, current_time):
        position = self.positions.get(stock_symbol)
        if not position:
            return

        profit_percent = (current_price - position["entry_price"]) / position["entry_price"] * 100 if position["side"] == "BUY" else (position["entry_price"] - current_price) / position["entry_price"] * 100

        time_bracket_a = "09:15" <= position["entry_time"] <= "12:00"
        time_bracket_b = "12:00" < position["entry_time"] <= "14:50"

        if position["side"] == "BUY":
            if time_bracket_a:
                if profit_percent >= 5:
                    position["stop_loss"] = max(position["stop_loss"], position["entry_price"] * 1.02)
                elif profit_percent >= 3:
                    position["stop_loss"] = max(position["stop_loss"], position["entry_price"] * 1.015)
                elif profit_percent >= 1:
                    position["stop_loss"] = max(position["stop_loss"], position["entry_price"] * 1.01)
            elif time_bracket_b:
                if profit_percent >= 5:
                    position["stop_loss"] = max(position["stop_loss"], position["entry_price"] * 1.01)
                elif profit_percent >= 2:
                    position["stop_loss"] = max(position["stop_loss"], position["entry_price"] * 1.005)
                elif profit_percent >= 0.75:
                    position["stop_loss"] = max(position["stop_loss"], position["entry_price"] * 1.0075)

        elif position["side"] == "SELL":
            if time_bracket_a:
                if profit_percent >= 5:
                    position["stop_loss"] = min(position["stop_loss"], position["entry_price"] * 0.98)
                elif profit_percent >= 3:
                    position["stop_loss"] = min(position["stop_loss"], position["entry_price"] * 0.985)
                elif profit_percent >= 1:
                    position["stop_loss"] = min(position["stop_loss"], position["entry_price"] * 0.99)
            elif time_bracket_b:
                if profit_percent >= 5:
                    position["stop_loss"] = min(position["stop_loss"], position["entry_price"] * 0.99)
                elif profit_percent >= 2:
                    position["stop_loss"] = min(position["stop_loss"], position["entry_price"] * 0.995)
                elif profit_percent >= 0.75:
                    position["stop_loss"] = min(position["stop_loss"], position["entry_price"] * 0.9925)

    def auto_exit_positions(self, current_time):
        if current_time == "15:12":
            for stock in list(self.positions):
                self.dashboard.close_position(stock, self.positions[stock])
                del self.positions[stock]

# Dashboard class should expose:
# .auto_buy, .auto_sell, .master_auto, .log_trade(), .close_position(), .update_visuals()
# Quantity config: {"Q1": 100, "Q2": 80, "Q3": 60, "Q4": 40, "Q5": 30, "Q6": 20}
# Indicators per stock should be fetched from analytical engine using your strategy logic


