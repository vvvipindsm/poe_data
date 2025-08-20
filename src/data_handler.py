import pandas as pd
import os
import config
from ib_insync import IB, Stock, Option
from src.ib_client import IBClient
from logger import setup_logger
from datetime import datetime, date
import yfinance as yf


logger = setup_logger("DataHandler")

def get_option_data(symbol, expiry, strike, right="P", qty=1):
    # Fetch option chain for the given expiry
    # expiry_dt = datetime.datetime.strptime(expiry, "%Y%m%d").strftime("%Y-%m-%d")
    expiry = datetime.strptime(expiry, "%Y%m%d").date()
    expiry_formatted = expiry.strftime("%Y-%m-%d")

    ticker = yf.Ticker(symbol)
    opt_chain = ticker.option_chain(expiry_formatted)

    # Pick puts or calls
    if right.upper() == "C":
        options = opt_chain.calls
    else:
        options = opt_chain.puts

    # Match the strike
    option_row = options[options["strike"] == float(strike)]
    if option_row.empty:
        return None  # Option not found

    bid = option_row["bid"].values[0]
    ask = option_row["ask"].values[0]
    last = option_row["lastPrice"].values[0]
    iv = option_row["impliedVolatility"].values[0]

    # Calculate mid safely
    mid = (bid + ask) / 2 if (bid and ask) else None

    # Cash required (strike * qty * 100, for US options)
    cash_required = strike * qty * 100

    return {
        "symbol": symbol,
        "expiry": expiry,
        "right": right,
        "strike": strike,
        "last": last,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "iv": iv,
        "qty": qty,
        "cash_required": cash_required,
        "conId": None  # Yahoo doesn’t give conId, only IBKR has it
    }

def get_last_price(symbol: str) -> float:
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d", interval="1m")  # intraday
        if not data.empty:
            last_price = data['Close'].iloc[-1]
            return float(last_price)
        else:
            raise ValueError(f"No price data found for {symbol}")
    except Exception as e:
        print(f"⚠️ Error fetching {symbol} price from Yahoo Finance: {e}")
        return None

class DataHandler:
    """Manages historical and real-time stock & option data."""
   
    
    def __init__(self, ib_client: IBClient) -> None:
        """
        Initialize the data handler.
        :param ib_client: An instance of IBClient to handle API interactions.
        """
        self.ib_client: IBClient = ib_client

    # ---------- STOCK DATA ----------
    def one_time_historical_data_loading(self, symbol: str, end_date_time: str,
                                         duration: str = "10 D", bar_size: str = "30 secs"):
        """Fetch & save historical data for the first time (bulk load)."""
        data = self.ib_client.get_historical_data(
            symbol, end_date_time=end_date_time, duration=duration, bar_size=bar_size
        )
        df = pd.DataFrame([[bar.date, bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in data],
                          columns=["Date", "Open", "High", "Low", "Close", "Volume"])
        self.save_historical_data(symbol=symbol, data=df)
        logger.info(f"✅ Loaded historical data for {symbol} with {len(df)} rows.")

    def fetch_option_historical_data(self, conId: int, symbol: str,
                                     end_date_time: str = "", duration: str = "1 D", bar_size: str = "5 mins"):
        """
        Fetch historical data for a given option contract by conId.
        Saves CSV as {symbol}_OPT_{conId}.csv.
        """
        from ib_insync import Contract
        option_contract = Contract(conId=conId)
        self.ib_client.ib.qualifyContracts(option_contract)

        bars = self.ib_client.ib.reqHistoricalData(
            option_contract,
            endDateTime=end_date_time,
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="OPTION",
            useRTH=False,
            formatDate=1
        )

        df = pd.DataFrame([[bar.date, bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in bars],
                          columns=["Date", "Open", "High", "Low", "Close", "Volume"])

        file_path = os.path.join(config.DATA_FOLDER, f"{symbol}_OPT_{conId}.csv")
        df.to_csv(file_path, index=False)
        logger.info(f"💾 Saved option historical data for {symbol} (conId={conId}) with {len(df)} rows → {file_path}")
        return df

    def load_historical_data(self, symbol: str) -> pd.DataFrame:
        """Load stored historical data for a stock symbol."""
        file_path = os.path.join(config.DATA_FOLDER, f"{symbol}.csv")
        return pd.read_csv(file_path) if os.path.exists(file_path) else pd.DataFrame()

    def save_historical_data(self, symbol: str, data: pd.DataFrame) -> None:
        """Save historical data DataFrame to CSV."""
        file_path = os.path.join(config.DATA_FOLDER, f"{symbol}.csv")
        data.to_csv(file_path, index=False)

    def update_historical_data(self, symbol: str, end_date_time: str = "") -> pd.DataFrame:
        """Fetch new data and merge with old historical data."""
        old_data = self.load_historical_data(symbol)
        new_data = self.ib_client.get_historical_data(symbol, end_date_time=end_date_time,
                                                      duration="30 S", bar_size="30 secs")
        df_new = pd.DataFrame([[bar.date, bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in new_data],
                              columns=["Date", "Open", "High", "Low", "Close", "Volume"])
        df_new["status"] = ["null"] * len(df_new)
        df_new_temp = df_new.tail(1).reset_index(drop=True)

        df_combined = (pd.concat([old_data, df_new_temp])
                       .drop_duplicates(subset=["Date"], keep="first")
                       .reset_index(drop=True)) if not old_data.empty else df_new

        return df_new, df_combined

    # ---------- OPTION HELPERS ----------
    def _pick_nearest_friday(self, expirations):
        """Return nearest Friday expiry (YYYYMMDD) or earliest expiry available."""
        to_date = lambda s: datetime.strptime(s, "%Y%m%d").date()
        today = date.today()
        dts = [to_date(x) for x in expirations]
        fridays = sorted([d for d in dts if d >= today and d.weekday() == 4])
        return (fridays[0] if fridays else min(dts)).strftime("%Y%m%d")

    def _mid(self, bid, ask):
        return (bid + ask) / 2.0 if bid and ask and bid > 0 and ask > 0 else None

    def _as_float(self, x):
        try:
            return float(x) if x is not None else None
        except Exception:
            return None

    # ---------- CORE: SELECT CSP ----------
    def fetch_aapl_options_and_select_csp(self, min_unique_strikes: int = 10):
        """Fetch AAPL options chain and return best cash-secured put (CSP)."""
        ib = self.ib_client.ib
    
        stock = Stock("AAPL", "SMART", "USD")
        ib.qualifyContracts(stock)
        [stkTicker] = ib.reqTickers(stock)

        # last = self._as_float(stkTicker.marketPrice()) or self._as_float(stkTicker.last)
        # if last is None:
        #     raise RuntimeError("❌ Could not get AAPL last price (check market data permissions).")
        last = get_last_price("AAPL")
        last = 230.47
        # print("last price from  yahoo",last)
        params = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
        p = next((x for x in params if x.tradingClass == "AAPL" and x.exchange in ("SMART", "BOX", "CBOE", "ISE", "NASDAQOM")), params[0])
        expiry = self._pick_nearest_friday(p.expirations)

        strikes_sorted = sorted([float(s) for s in p.strikes if str(s).replace('.', '', 1).isdigit()])
        if not strikes_sorted:
            raise RuntimeError("❌ No strikes returned by IB for AAPL.")

        atm_idx = min(range(len(strikes_sorted)), key=lambda i: abs(strikes_sorted[i] - last))
        half = max(1, min_unique_strikes // 2)
        lo, hi = max(0, atm_idx - half), min(len(strikes_sorted), atm_idx + half + 1)
        sel = strikes_sorted[lo:hi]

        while len(sel) < min_unique_strikes:
            if lo > 0: sel.insert(0, strikes_sorted[lo-1]); lo -= 1
            if hi < len(strikes_sorted): sel.append(strikes_sorted[hi]); hi += 1

        contracts = [Option("AAPL", expiry, float(k), right, "SMART", currency="USD")
                     for k in sel for right in ("C", "P")]
        ib.qualifyContracts(*contracts)
        tickers = ib.reqTickers(*contracts)

        best_csp = None
        for t in tickers:
            k, right = t.contract.strike, t.contract.right
            bid, ask = self._as_float(t.bid), self._as_float(t.ask)
            iv = getattr(t.modelGreeks, "impliedVol", None) if getattr(t, "modelGreeks", None) else getattr(t, "impliedVolatility", None)
            if right == "P" and k < last:
                dist = last - k
                if best_csp is None or dist < best_csp[0]:
                    best_csp = (dist, k, t, bid, ask, iv)

        if not best_csp:
            logger.warning("[CSP] No OTM put found.")
            return None

        _, strike, tkr, bid, ask, iv = best_csp
        mid = self._mid(bid, ask)
        qty, cash_required = 1, strike * 100

        logger.info(f"✅ Selected CSP: AAPL {expiry} P {strike} @ {mid} (IV={iv})")
        # return {
        #     "symbol": "AAPL",
        #     "expiry": expiry,
        #     "right": "P",
        #     "strike": strike,
        #     "last": last,
        #     "bid": bid,
        #     "ask": ask,
        #     "mid": mid,
        #     "iv": iv,
        #     "qty": qty,
        #     "cash_required": cash_required,
        #     "conId": tkr.contract.conId
        # }

        return get_option_data("AAPL",expiry,strike,"P",qty=1)


if __name__ == "__main__":
    ib_client = IBClient()
    if not ib_client.ib.isConnected():
        ib_client.connect()
    logger.info("📡 Connected to IB.")
