import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# Define scope
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]

# Load credentials
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

# Open Google Sheet
sheet = client.open_by_key("1_ZtKjOOrcOkqsvyypGVzNlRoNwcn6LtwvXQPtOTea2Y").sheet1

def log_order(ticker, expiry, strike, premium, orderStatus, clientId, permId, reasonCancelled=""):
    """Append a log entry to Google Sheet."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # current timestamp
    row = [timestamp, ticker, expiry, strike, premium, orderStatus, clientId, permId, reasonCancelled]
    sheet.append_row(row, value_input_option="USER_ENTERED")
    print("Log entry added:", row)


# # Example usage:
# log_order(
#     ticker="AAPL",
#     expiry="2025-09-15",
#     strike=190,
#     premium=3.25,
#     orderStatus="FILLED",
#     clientId="12345",
#     permId="67890",
#     reasonCancelled=""
# )
