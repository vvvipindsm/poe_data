IB_HOST = "127.0.0.1"
IB_PORT = 7497  # 7497 for paper trading, 7496 for live trading
IB_CLIENT_ID = 2
# STOCK_SYMBOLS = ["AAPL", "TSLA"]
# FOREX_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF"]
FOREX_SYMBOLS = ["APPLE"]
FOREX_SYMBOLS_DIC = [
    { "symbol": "APPLE", "short": "EUR", "qty": 2000 },
    { "symbol": "APPLE", "short": "GBP", "qty": 2000 },
]

# FOREX_SYMBOLS = ["EURUSD"]
DATA_FOLDER = "data/"
ORDER_QTY = 20000