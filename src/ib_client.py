
import csv
import os
import time
from datetime import datetime,timedelta
from ib_insync import Option, Order
from logger import setup_logger
import config
from ib_insync import IB

logger = setup_logger("TradeManager")

ORDER_LOG_CSV = "logs/option_order_log.csv"

def _normalize_expiry(expiry_str: str) -> str:
    """
    Normalize expiry to IB's expected Friday date (YYYYMMDD).
    """
    dt = datetime.strptime(expiry_str, "%Y%m%d")
    # If it's Saturday, roll back 1 day
    if dt.weekday() == 5:  # Saturday
        dt -= timedelta(days=1)
    # If it's Sunday, roll back 2 days
    elif dt.weekday() == 6:  # Sunday
        dt -= timedelta(days=2)
    return dt.strftime("%Y%m%d")

def _ensure_csv_header(path):
    header = ["timestamp", "ticker", "expiry", "strike", "premium", "orderStatus",
              "clientId", "permId", "reasonCancelled"]
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)

class IBClient:
    def __init__(self):
        self.ib = IB()

    def connect(self):
        if not self.ib.isConnected():
            self.ib.connect(config.IB_HOST, config.IB_PORT, clientId=config.IB_CLIENT_ID)

class TradeManager:
    """
    Small manager focused on placing a SELL limit order for an option,
    waiting for a short window for fills, canceling if not filled,
    and logging a CSV line with status and metadata.
    """

    def __init__(self, ib_client):
        """
        ib_client: instance of your IBClient (has .ib attribute that is an ib_insync.IB).
        """
        self.ib_client = ib_client
        self.ib = ib_client.ib
        _ensure_csv_header(ORDER_LOG_CSV)

    def place_option_limit_and_wait_cancel(self,
                                           ticker: str,
                                           expiry: str,
                                           strike: float,
                                           right: str = "P",
                                           quantity: int = 1,
                                           limit_price: float = None,
                                           wait_seconds: int = 5) -> dict:
        """
        Place a SELL limit order for an option and wait `wait_seconds` for any orderStatus events.
        If not filled within that time, cancel the order.

        Returns a dict with final info for caller.
        """
        # Build option contract (expiry expected in YYYYMMDD or YYYY-MM-DD)
        # Normalize expiry to YYYYMMDD if user passed a date
    
        expiry_str = str(expiry).replace("-", "")
        expiry_str = _normalize_expiry(expiry_str)
        contract = Option(symbol=ticker, lastTradeDateOrContractMonth=expiry_str,
                          strike=float(strike), right=right.upper(), exchange="SMART", currency="USD")

        # Ensure contract is qualified
        try:
            self.ib.qualifyContracts(contract)
        except Exception as e:
            logger.error(f"Failed to qualify contract {ticker} {expiry_str} {strike} {right}: {e}")
            raise

        # Build limit order (SELL)
        # price fallback: if limit_price is None, try mid/bid/ask order outside (caller should pass)
        order_price = float(limit_price) if limit_price is not None else None
        order = Order(action="SELL", orderType="LMT", totalQuantity=quantity, lmtPrice=order_price, transmit=True)

        # Place
        trade = self.ib.placeOrder(contract, order)
        clientId = getattr(self.ib.client, "clientId", config.IB_CLIENT_ID if hasattr(config, "IB_CLIENT_ID") else "")
        # permId may be 0 or None until IB replies; capture whatever's there.
        permId = getattr(trade.order, "permId", None)

        logger.info(f"Placed SELL LMT order: {ticker} {expiry_str} {strike} {right} qty={quantity} @ {order_price} (orderId={trade.order.orderId})")

        # Wait loop: check trade.orderStatus.status; allow ib.waitOnUpdate to process events
        start = time.time()
        last_status = None
        filled = False
        while time.time() - start < wait_seconds:
            # let ib_insync process events (updates trade.orderStatus live)
            self.ib.waitOnUpdate(timeout=1.0)  # short blocking call, process network events
            last_status = trade.orderStatus.status
            logger.debug(f"OrderId={trade.order.orderId} status={last_status}")
            if last_status and last_status.lower() == "filled":
                filled = True
                break

        reason_cancelled = ""
        if not filled:
            # Cancel the order
            try:
                self.ib.cancelOrder(trade.order)
                logger.info(f"Cancelled orderId={trade.order.orderId} after {wait_seconds}s (not filled).")
                reason_cancelled = "Cancelled by timeout"
                # allow any final status updates to arrive
                self.ib.waitOnUpdate(timeout=1.0)
                last_status = trade.orderStatus.status
            except Exception as e:
                logger.error(f"Error cancelling order {trade.order.orderId}: {e}")
                reason_cancelled = f"Cancel error: {e}"

        # Prepare CSV row details
        timestamp = datetime.now().astimezone().isoformat()
        premium = order_price
        status_for_log = last_status if last_status is not None else "Unknown"

        # Try to pull permId and client id again after IB responded
        permId = getattr(trade.order, "permId", permId)
        client_id_logged = clientId

        # Log CSV row
        row = [timestamp, ticker, expiry_str, float(strike), premium, status_for_log, client_id_logged, permId, reason_cancelled]
        try:
            with open(ORDER_LOG_CSV, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception as e:
            logger.error(f"Failed to write order log row: {e}")

        # Return structured result for the caller
        result = {
            "timestamp": timestamp,
            "ticker": ticker,
            "expiry": expiry_str,
            "strike": float(strike),
            "premium": float(premium) if premium is not None else None,
            "orderStatus": status_for_log,
            "clientId": client_id_logged,
            "permId": permId,
            "reasonCancelled": reason_cancelled,
            "orderId": getattr(trade.order, "orderId", None),
            "filled": filled
        }
        return result

    # --- reconnect & resync sketch (code + short explanation) ---
    def reconnect_and_resync(self, max_retries: int = 5, retry_delay: int = 3):
        """
        Try to reconnect to IB and resync open orders & positions.

        What it does:
        1. Try to re-establish connection (retries with backoff).
        2. After connect: fetch open orders (reqOpenOrders / openOrders) and current positions().
        3. Reconcile your internal cache/tracked orders with IB state:
           - For any order we believed open but IB doesn't show → mark as canceled/needs investigation.
           - For any order IB shows open but not in cache → add to cache and start monitoring.
        4. Re-subscribe to relevant streaming data if needed (market data, tickers).
        """
        tries = 0
        while tries < max_retries:
            try:
                if not self.ib.isConnected():
                    self.ib.connect(config.IB_HOST, config.IB_PORT, clientId=config.IB_CLIENT_ID)
                # Successfully connected
                logger.info("Reconnected to IB")
                break
            except Exception as e:
                tries += 1
                logger.warning(f"Reconnect attempt {tries}/{max_retries} failed: {e}. Retrying in {retry_delay}s")
                time.sleep(retry_delay)

        # After connection, resync orders & positions
        try:
            # Open orders
            open_orders = self.ib.reqOpenOrders()
            # Current positions
            positions = self.ib.positions()
            logger.info(f"Resynced: {len(open_orders)} open orders, {len(positions)} positions")
            # Example reconciliation logic (extend as needed)
            # Map by orderId or contract
            ib_open_ids = {getattr(trade.order, "orderId", None) for trade in open_orders}
            # If you track orders in a separate datastore, compare and fix mismatches here.
            return {"openOrders": open_orders, "positions": positions}
        except Exception as e:
            logger.error(f"Error during resync: {e}")
            return None
