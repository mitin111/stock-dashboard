from datetime import datetime, time

def calculate_trailing_sl(entry_price, current_price, entry_time=None, signal_type="BUY"):
    if entry_time is None:
        entry_time = datetime.now()
    elif isinstance(entry_time, str):
        try:
            entry_time = datetime.fromisoformat(entry_time)
        except Exception:
            entry_time = datetime.now()
    
    if not signal_type or signal_type.upper() not in ["BUY", "SELL"]:
        print(f"⚠️ Invalid signal_type={signal_type} for trailing SL. Skipping calculation.")
        return None
    signal_type = signal_type.upper()
    
    morning_start = time(9, 15)
    morning_end = time(12, 0)
    afternoon_start = time(12, 0, 1)
    afternoon_end = time(14, 50)
    
    if signal_type == "BUY":
        profit_pct = ((current_price - entry_price) / entry_price) * 100
    else:
        profit_pct = ((entry_price - current_price) / entry_price) * 100
    
    trail_sl = None
    
    if morning_start <= entry_time.time() <= morning_end:
        if profit_pct >= 5:
            trail_sl = entry_price * (0.98 if signal_type=="BUY" else 1.02)
        elif profit_pct >= 3:
            trail_sl = entry_price * (0.985 if signal_type=="BUY" else 1.015)
        elif profit_pct >= 1:
            trail_sl = entry_price * (0.99 if signal_type=="BUY" else 1.01)
    elif afternoon_start <= entry_time.time() <= afternoon_end:
        if profit_pct >= 5:
            trail_sl = entry_price * (0.99 if signal_type=="BUY" else 1.01)
        elif profit_pct >= 2:
            trail_sl = entry_price * (0.995 if signal_type=="BUY" else 1.005)
        elif profit_pct >= 0.75:
            trail_sl = entry_price * (0.9925 if signal_type=="BUY" else 1.0075)
    
    return trail_sl
