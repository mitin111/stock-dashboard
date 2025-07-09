# prostocks_login_app.py

import streamlit as st
from prostocks_connector import ProStocksAPI

st.set_page_config(page_title="🔐 ProStocks Login", layout="centered")
st.title("🔐 ProStocks API Login")

# --- Login Form ---
with st.form("login_form"):
    uid = st.text_input("User ID", value="", max_chars=30)
    pwd = st.text_input("Password", type="password")
    factor2 = st.text_input("PAN / DOB (DD-MM-YYYY)")
    vc = st.text_input("Vendor Code")
    api_key = st.text_input("API Key", type="password")
    imei = st.text_input("IMEI (MAC or Unique ID)", value="MAC123456")
    submitted = st.form_submit_button("Login")

# --- After Submit ---
if submitted:
    if all([uid, pwd, factor2, vc, api_key, imei]):
        # Create API instance
        api = ProStocksAPI(uid, pwd, factor2, vc, api_key, imei)

        # Try to login
        success, result = api.login()

        if success:
            st.success("✅ Login successful.")
            st.code(result, language="bash")

            # Save API instance to session for future use
            st.session_state["prostocks_api"] = api
            st.session_state["token"] = result
        else:
            st.error(f"❌ Login failed: {result}")
    else:
        st.warning("⚠️ Please fill all fields to proceed.")

# --- Optional: Show status ---
if "token" in st.session_state:
    st.info("🔗 Connected with token:")
    st.code(st.session_state["token"], language="bash")
