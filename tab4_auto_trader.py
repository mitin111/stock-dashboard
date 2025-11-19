# tab4_auto_trader.py  (CLEAN + FINAL VERSION)

import streamlit as st
import queue
from tkp_trm_chart import load_trm_settings_from_file
from dashboard_logic import save_qty_map, load_qty_map
import requests

import streamlit as st
import queue
from tkp_trm_chart import load_trm_settings_from_file
from dashboard_logic import save_qty_map, load_qty_map
import requests


# ============================================================
# ⭐ REQUIRED FUNCTION — Backend session auto attach
# ============================================================
def init_backend_session():
    """Attach Streamlit session to backend-stream worker."""
    BACKEND_URL = "https://backend-stream-nmlf.onrender.com"

    # Must have ps_api
    if "ps_api" not in st.session_state:
        return

    ps = st.session_state.ps_api

    # Prevent multiple initializations
    if st.session_state.get("backend_inited", False):
        return

    try:
        resp = requests.post(
            f"{BACKEND_URL}/init",
            json={
                "jKey": ps.session_token,
                "userid": ps.userid,
                "vc": ps.vc,
                "api_key": ps.api_key,
                "imei": ps.imei
            },
            timeout=5
        )

        st.session_state["backend_inited"] = True
        st.success("Backend attached (Tab-4 auto init)")
    except Exception as e:
        st.warning(f"Backend init failed: {e}")

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

        # 🔵 STEP 1: INIT BACKEND SESSION
        try:
            ps = st.session_state.ps_api
            resp = requests.post(
                f"{BACKEND_URL}/init",
                json={
                    "jKey": ps.session_token,
                    "userid": ps.userid,
                    "vc": ps.vc,
                    "api_key": ps.api_key,
                    "imei": ps.imei,
                    "trm_settings": st.session_state.get("trm_settings", {})
                },
                timeout=5
            )
            st.success("Backend initialized for Auto Trader")
            st.write(resp.json())
        except Exception as e:
            st.error(f"Backend init failed: {e}")
            st.stop()

        # 🔵 STEP 2: START AUTO TRADER
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





