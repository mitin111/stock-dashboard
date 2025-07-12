# test_prostocks_login.py

import os
from dotenv import load_dotenv
from prostocks_connector import login_ps

load_dotenv()

# Read credentials from .env
user_id = os.getenv("PROSTOCKS_USER_ID")
password = os.getenv("PROSTOCKS_PASSWORD")
factor2 = os.getenv("PROSTOCKS_TOTP_SECRET")  # TOTP / PAN / DOB
api_key = os.getenv("PROSTOCKS_API_KEY")

# Try login
api = login_ps(user_id, password, factor2, api_key)

if api:
    print("✅ Success! Token:", api.token)
else:
    print("❌ Login failed.")
