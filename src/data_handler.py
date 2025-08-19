import pandas as pd
import os
import config
from ib_insync import IB, Stock, Option

from src.ib_client import IBClient
from typing import Optional
from logger import setup_logger
import json
from datetime import datetime, date
import math


logger = setup_logger("DataHandler")

def get_symbol_by_short(short_name, config_dict):
    for data in config_dict:
        if data.get("short") == short_name:
            return data
    return None

class DataHandler:
    """Manages historical and real-time stock data."""

    def __init__(self, ib_client: IBClient) -> None:
        """
        Initialize the data handler.

        :param ib_client: An instance of IBClient to handle API interactions.
        """
        self.ib_client: IBClient = ib_client

    def one_time_historical_data_loading(self, symbol:str, end_date_time:str, duration: str = "10 D", bar_size: str = "30 secs"):
        data = self.ib_client.get_historical_data(symbol, end_date_time=end_date_time, duration=duration, bar_size=bar_size)
        data = pd.DataFrame([[bar.date, bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in data],
                              columns=["Date", "Open", "High", "Low", "Close", "Volume"])
        self.save_historical_data(symbol=symbol, data=data)
        logger.info(f"Loaded historical data successfull for {symbol} with {len(data)} samples")

 

    def load_historical_data(self, symbol: str) -> pd.DataFrame:
        """
        Load stored historical data for a stock symbol.

        :param symbol: Stock symbol (e.g., "AAPL")
        :return: DataFrame containing historical data
        """
        file_path = os.path.join(config.DATA_FOLDER, f"{symbol}.csv")
        if os.path.exists(file_path):
            return pd.read_csv(file_path)
        return pd.DataFrame()

    def save_historical_data(self, symbol: str, data: pd.DataFrame) -> None:
        """
        Save updated historical data to a CSV file.

        :param symbol: Stock symbol
        :param data: DataFrame containing historical data
        """
        file_path = os.path.join(config.DATA_FOLDER, f"{symbol}.csv")
        data.to_csv(file_path, index=False)

    def initial_update_historical_data(self, symbol, end_date_time=""):
        new_data = self.ib_client.get_historical_data(symbol, end_date_time=end_date_time, duration="1 D", bar_size="30 secs")

        df_new = pd.DataFrame([[bar.date, bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in new_data],
                              columns=["Date", "Open", "High", "Low", "Close", "Volume"])
        
        # To-Do later stage remove 
        df_new["status"] = ["null" for _ in range(len(df_new))]
        print(df_new)
        self.save_historical_data(symbol, df_new)


    def update_historical_data(self, symbol: str, end_date_time:str = "") -> pd.DataFrame:
        """
        Fetch new historical data and update stored data.

        :param symbol: Stock symbol
        :return: Updated DataFrame containing historical data
        """
        old_data = self.load_historical_data(symbol)
        

        new_data = self.ib_client.get_historical_data(symbol, end_date_time=end_date_time, duration="30 S", bar_size="30 secs")

        df_new = pd.DataFrame([[bar.date, bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in new_data],
                              columns=["Date", "Open", "High", "Low", "Close", "Volume"])
        
        # print(len(df_new))
        df_new["status"] = ["null" for _ in range(len(df_new))]
        df_new_temp = df_new.tail(1).reset_index(drop=True)
        if not old_data.empty:
            df_combined = pd.concat([old_data, df_new_temp]).drop_duplicates(subset=["Date"], keep='first').reset_index(drop=True)
            
        else:
            df_combined = df_new

        # self.save_historical_data(symbol, df_combined)
        return df_new, df_combined
    
  # ---------- OPTIONS HELPERS ----------
    def _pick_nearest_friday(self, expirations):
        """
        expirations: iterable of 'YYYYMMDD' strings (from reqSecDefOptParams)
        returns: 'YYYYMMDD' for the nearest upcoming Friday (>= today),
                 else earliest available expiry.
        """
        def to_date(s): return datetime.strptime(s, "%Y%m%d").date()
        today = date.today()
        dts = [to_date(x) for x in expirations]
        fridays = sorted([d for d in dts if d >= today and d.weekday() == 4])
        return (fridays[0] if fridays else min(dts)).strftime("%Y%m%d")

    def _mid(self, bid, ask):
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        return None

    def _as_float(self, x):
        try:
            return float(x) if x is not None else None
        except Exception:
            return None

    # ---------- CORE: FETCH + PRINT + SELECT CSP ----------
    def fetch_aapl_options_and_select_csp(self, min_unique_strikes: int = 10):
        """
        1) Pull AAPL option chain for next/nearest Friday
        2) Print >=min_unique_strikes strikes (both calls & puts) with right, bid/ask, IV
        3) Select 1x cash-secured put: closest OTM strike below last. Compute mid-price.
        """
        ib = self.ib_client.ib

        # Underlying last price
        stock = Stock("AAPL", "SMART", "USD")
        print(stock)
        print(stock)
        ib.qualifyContracts(stock)
        [stkTicker] = ib.reqTickers(stock)
        last = self._as_float(stkTicker.marketPrice())
        if last is None or math.isnan(last):
            last = self._as_float(stkTicker.last)
        if last is None:
            raise RuntimeError("Could not get AAPL last/market price. Ensure market data permissions/delayed data enabled.")

        # Option params (expirations/strikes)
        # Request option parameters
        params = ib.reqSecDefOptParams(
            underlyingSymbol=stock.symbol,
            futFopExchange="",              # leave empty for stock options
            underlyingSecType=stock.secType,
            underlyingConId=stock.conId
        )       
        
        # choose the entry that has expirations/strikes for SMART
        p = next((x for x in params if x.tradingClass == "AAPL" and x.exchange in ("SMART", "BOX", "CBOE", "ISE", "NASDAQOM")), params[0])
        expiry = self._pick_nearest_friday(p.expirations)

        # choose a band around ATM that yields at least `min_unique_strikes` distinct strikes
        strikes_sorted = sorted([float(s) for s in p.strikes if isinstance(s, (int, float)) or str(s).replace('.', '', 1).isdigit()])
        if not strikes_sorted:
            raise RuntimeError("No strikes returned by IB for AAPL.")

        # find nearest strike to underlying
        atm_idx = min(range(len(strikes_sorted)), key=lambda i: abs(strikes_sorted[i] - last))

        # aim for ~min_unique_strikes around ATM
        half = max(1, min_unique_strikes // 2)
        lo = max(0, atm_idx - half)
        hi = min(len(strikes_sorted), atm_idx + half + 1)
        sel = strikes_sorted[lo:hi]

        # pad if near edges
        while len(sel) < min_unique_strikes:
            if lo > 0:
                lo -= 1
                sel.insert(0, strikes_sorted[lo])
            if len(sel) < min_unique_strikes and hi < len(strikes_sorted):
                sel.append(strikes_sorted[hi])
                hi += 1

        # build contracts for both calls & puts
        contracts = []
        for k in sel:
            k_int = int(round(k))
            contracts.append(Option("AAPL", expiry, k_int, "C", "SMART", currency="USD"))
            contracts.append(Option("AAPL", expiry, k_int, "P", "SMART", currency="USD"))

        ib.qualifyContracts(*contracts)
        tickers = ib.reqTickers(*contracts)

        # collect rows & find CSP
        rows = []
        best_csp = None  # tuple: (distance, strike, ticker, bid, ask, iv)

        for t in tickers:
            k = t.contract.strike
            right = t.contract.right
            bid = self._as_float(t.bid)
            ask = self._as_float(t.ask)

            # IV can be in modelGreeks.impliedVol or on the ticker directly (ib sometimes fills either)
            iv = None
            if getattr(t, "modelGreeks", None) and t.modelGreeks.impliedVol is not None:
                iv = float(t.modelGreeks.impliedVol)
            elif getattr(t, "impliedVolatility", None) is not None:
                iv = float(t.impliedVolatility)

            rows.append({
                "expiry": expiry,
                "strike": float(k),
                "right": right,
                "bid": bid,
                "ask": ask,
                "iv": iv
            })

            # choose closest OTM put below last
            if right == "P" and float(k) < last:
                dist = last - float(k)
                if best_csp is None or dist < best_csp[0]:
                    best_csp = (dist, float(k), t, bid, ask, iv)

        # -------- print report (≥ 10 strikes across both C/P in the band) --------
        print(f"\nUnderlying: AAPL   Last: {last:.2f}")
        print(f"Expiry (nearest Friday): {expiry}\n")
        print("{:<8} {:>8} {:>6} {:>10} {:>10} {:>9}".format("Expiry", "Strike", "Right", "Bid", "Ask", "IV"))
        print("-" * 60)
        for r in sorted(rows, key=lambda r: (r["strike"], r["right"])):
            iv_pct = f"{r['iv']*100:0.2f}%" if r["iv"] is not None else "—"
            bid_s = f"{r['bid']:.2f}" if r["bid"] is not None else "—"
            ask_s = f"{r['ask']:.2f}" if r["ask"] is not None else "—"
            print("{:<8} {:>8.2f} {:>6} {:>10} {:>10} {:>9}".format(
                r["expiry"], r["strike"], r["right"], bid_s, ask_s, iv_pct
            ))

        # -------- CSP selection summary --------
        if best_csp is None:
            print("\n[CSP] No OTM put below last price found in selected strikes.")
            return None

        _, strike, tkr, bid, ask, iv = best_csp
        mid = self._mid(bid, ask)
        qty = 1
        cash_required = strike * 100 * qty
        iv_pct = f"{iv*100:0.2f}%" if iv is not None else "—"

        print("\n[CSP] Selected cash-secured put")
        print(f"  Symbol: AAPL   Expiry: {expiry}   Right: P   Strike: {strike:.2f}")
        print(f"  Bid: {bid if bid is not None else '—'}   Ask: {ask if ask is not None else '—'}   Mid: {mid if mid is not None else '—'}")
        print(f"  IV: {iv_pct}   Qty: {qty}   Cash required: ${cash_required:,.2f}")

        # return a structured result in case you want to place an order next
        return {
            "symbol": "AAPL",
            "expiry": expiry,
            "right": "P",
            "strike": strike,
            "last": last,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "iv": iv,
            "qty": qty,
            "cash_required": cash_required,
            "conId": tkr.contract.conId
        }
if __name__ == "__main__":
    ib_client = IBClient()
    if not ib_client.ib.isConnected():
        ib_client.connect()
    else:
        print("Already connected to IB — reusing existing session")

    data_handler = DataHandler(ib_client)
    
    for symbol in config.STOCK_SYMBOLS:
        data_handler.one_time_historical_data_loading(symbol=symbol, end_date_time="20250301 23:59:59")
