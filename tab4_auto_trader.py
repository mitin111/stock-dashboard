# tab4_auto_trader.py  (CLEAN + FINAL VERSION)

import streamlit as st
import queue
from tkp_trm_chart import load_trm_settings_from_file
from dashboard_logic import save_qty_map, load_qty_map
import requests


# -----------------------------
# 🟦 Clean render_tab4()
# -----------------------------
def render_tab4(require_session_settings=False, allow_file_fallback=True):

    # LOGIN CHECK
    if not st.session_state.get("logged_in", False):
        st.info("🔐 Please login first to use Auto Trader settings.")
        return

    # Load TRM settings
    if "trm_settings" not in st.session_state:
        st.session_state["trm_settings"] = load_trm_settings_from_file()

    # Load Qty Map
    if "qty_map" not in st.session_state:
        st.session_state["qty_map"] = load_qty_map()

    st.subheader("📌 Position Quantity Mapping")

    current_map = st.session_state.get("qty_map", {})

    # 20 Qty inputs
    qty_map = {}
    for i, label in enumerate([
        "1-100", "101-150", "151-200", "201-250", "251-300",
        "301-350", "351-400", "401-450", "451-500", "501-550",
        "551-600", "601-650", "651-700", "701-750", "751-800",
        "801-850", "851-900", "901-950", "951-1000", "Above 1000"
    ], start=1):
        key = f"Q{i}"
        qty_map[key] = st.number_input(
            f"{key} ({label})",
            min_value=1,
            value=current_map.get(key, 1),
            key=f"qty_{i}"
        )

    # Save Qty Map
    if st.button("💾 Save Quantity Mapping"):
        save_qty_map(qty_map)
        st.session_state["qty_map"] = qty_map
        st.success("✅ Quantity mapping saved.")

    st.write("Current Mapping:", qty_map)

    st.subheader("⚡ Auto Trader Control")

    BACKEND_URL = "https://backend-stream-nmlf.onrender.com"

    # --------------------------
    # START AUTO TRADER
    # --------------------------
    if st.button("🚀 Start Auto Trader"):
        try:
            r = requests.post(f"{BACKEND_URL}/start_auto")
            st.success("Auto Trader Started (Background Worker Running)")
            st.write(r.json())
        except Exception as e:
            st.error(f"Start error: {e}")

    # --------------------------
    # STOP AUTO TRADER
    # --------------------------
    if st.button("🛑 Stop Auto Trader"):
        try:
            r = requests.post(f"{BACKEND_URL}/stop_auto")
            st.warning("Auto Trader Stopped")
            st.write(r.json())
        except Exception as e:
            st.error(f"Stop error: {e}")

