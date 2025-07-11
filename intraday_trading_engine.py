# intraday_trading_engine.py

class TradingEngine:
    def __init__(self, dashboard, ps_api):
        self.dashboard = dashboard
        self.ps_api = ps_api
        self.positions = {}
        print("✅ TradingEngine ready for ProStocks")

    def get_quantity(self, price, qcfg):
        if 170 <= price <= 200:
            return qcfg.get("Q1", 0)
        elif 201 <= price <= 400:
            return qcfg.get("Q2", 0)
        elif 401 <= price <= 600:
            return qcfg.get("Q3", 0)
        elif 601 <= price <= 800:
            return qcfg.get("Q4", 0)
        elif 801 <= price <= 1000:
            return qcfg.get("Q5", 0)
        elif price > 1000:
            return qcfg.get("Q6", 0)
        return 0

    def process_trade(self, symbol, price, y_close, open_price, indicators, qcfg, time, balance):
        if symbol in self.positions:
            return  # Skip already traded stock

        # === Conditions (Buy Example) ===
        if (
            indicators["atr_trail"] == "Buy" and
            indicators["tkp_trm"] == "Buy" and
            indicators["macd_hist"] > 0 and
            indicators["above_pac"] and
            indicators["volatility"] >= indicators["min_vol_required"]
        ):
            qty = self.get_quantity(price, qcfg)
            if qty == 0:
                print(f"⚠️ Quantity config missing for {symbol}")
                return

            sl = indicators["pac_band_lower"]
            tgt = round(price * 1.10, 2)

            order = self.ps_api.place_bracket_order(
                symbol=symbol,
                qty=qty,
                price=price,
                sl=sl,
                target=tgt,
                side="BUY"
            )

            if order:
                self.positions[symbol] = {
                    "entry_price": price,
                    "side": "BUY",
                    "stop_loss": sl,
                    "target": tgt,
                    "time": time
                }
                self.dashboard.log_trade(symbol, "BUY", price, qty, sl, tgt, time)
            else:
                print(f"❌ Failed to place order for {symbol}")
