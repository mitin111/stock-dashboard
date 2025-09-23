from datetime import datetime, time

def calculate_trailing_sl(entry_price, current_price, entry_time=None, signal_type="BUY"):
    """
    entry_price: price at which position was entered
    current_price: current market price
    entry_time: datetime object of trade entry
    signal_type: "BUY" or "SELL"
    Returns: new stop-loss price based on dynamic trailing logic
    """
    if entry_time is None:
        entry_time = datetime.now()
    
    # Define time windows
    morning_start = time(9, 15)
    morning_end = time(12, 0)
    afternoon_start = time(12, 0, 1)
    afternoon_end = time(14, 50)
    
    # Compute profit percentage
    if signal_type.upper() == "BUY":
        profit_pct = ((current_price - entry_price) / entry_price) * 100
    elif signal_type.upper() == "SELL":
        profit_pct = ((entry_price - current_price) / entry_price) * 100
    else:
        raise ValueError("signal_type must be 'BUY' or 'SELL'")
    
    trail_sl = None

    # --- Morning logic ---
    if morning_start <= entry_time.time() <= morning_end:
        if profit_pct >= 5:
            trail_sl = entry_price * (0.98 if signal_type.upper()=="BUY" else 1.02)
        elif profit_pct >= 3:
            trail_sl = entry_price * (0.985 if signal_type.upper()=="BUY" else 1.015)
        elif profit_pct >= 1:
            trail_sl = entry_price * (0.99 if signal_type.upper()=="BUY" else 1.01)
    
    # --- Afternoon logic ---
    elif afternoon_start <= entry_time.time() <= afternoon_end:
        if profit_pct >= 5:
            trail_sl = entry_price * (0.99 if signal_type.upper()=="BUY" else 1.01)
        elif profit_pct >= 2:
            trail_sl = entry_price * (0.995 if signal_type.upper()=="BUY" else 1.005)
        elif profit_pct >= 0.75:
            trail_sl = entry_price * (0.9925 if signal_type.upper()=="BUY" else 1.0075)

    return trail_sl
