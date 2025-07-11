from prostocks_connector import ProStocksAPI

# ✅ Provide all required login arguments
user_id = "YourUserID"
password = "YourPassword"
factor2 = "ABCDE1234F"  # PAN or DOB
vc = "YourVendorCode"
app_key = "pssUATAPI12122021ASGND1234DL"  # Replace with actual app key
imei = "abc1234"

# Create instance
api = ProStocksAPI(user_id, password, factor2, vc, app_key, imei)

# Attempt login
success, result = api.login()

if success:
    print("✅ Login successful. Token:", result)
else:
    print("❌ Login failed. Reason:", result)
