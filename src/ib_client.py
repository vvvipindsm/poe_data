import csv
import os
import time
from datetime import datetime, timedelta
from ib_insync import Option, Order, IB
from logger import setup_logger
import config
from google_logger import log_order



logger = setup_logger("TradeManager")

ORDER_LOG_CSV = "logs/option_order_log.csv"


def _normalize_expiry(expiry_str: str) -> str:
    """
    Normalize expiry to IB's expected Friday date (YYYYMMDD).
    """
    dt = datetime.strptime(expiry_str, "%Y%m%d")
    # If it's Saturday, roll back 1 day
    if dt.weekday() == 5:
        dt -= timedelta(days=1)
    # If it's Sunday, roll back 2 days
    elif dt.weekday() == 6:
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
    def __init__(self, ib_client):
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
        # Normalize expiry
        expiry_str = str(expiry).replace("-", "")
        expiry_str = _normalize_expiry(expiry_str)

        # Build raw contract
        contract = Option(
            symbol=ticker,
            lastTradeDateOrContractMonth=expiry_str,
            strike=float(strike),
            right=right.upper(),
            exchange="SMART",
            currency="USD"
        )

        # Qualify contract
        try:
            qualified_contracts = self.ib.qualifyContracts(contract)
            if not qualified_contracts:
                raise Exception("No qualified contract returned")
            qualified_contract = qualified_contracts[0]
        except Exception as e:
            raise Exception(f"Failed to qualify contract {ticker} {expiry_str} {strike} {right}: {e}")

        # Build limit order
        order_price = float(limit_price) if limit_price is not None else None
        order = Order(
            action="SELL",
            orderType="LMT",
            totalQuantity=quantity,
            lmtPrice=order_price,
            transmit=True
        )

        # Place order
        trade = self.ib.placeOrder(qualified_contract, order)
        clientId = getattr(self.ib.client, "clientId", config.IB_CLIENT_ID)
        permId = getattr(trade.order, "permId", None)

        logger.info(
            f"Placed SELL LMT order: {ticker} {qualified_contract.lastTradeDateOrContractMonth} "
            f"{strike} {right} qty={quantity} @ {order_price} (orderId={trade.order.orderId})"
        )

        # Wait for fill or cancel
        start = time.time()
        last_status = None
        filled = False
        while time.time() - start < wait_seconds:
            self.ib.waitOnUpdate(timeout=1.0)
            last_status = trade.orderStatus.status
            if last_status and last_status.lower() == "filled":
                filled = True
                break

        reason_cancelled = ""
        if not filled and (last_status is None or last_status.lower() not in ["cancelled", "inactive"]):
            try:
                self.ib.cancelOrder(trade.order)
                logger.info(f"Cancelled orderId={trade.order.orderId} after {wait_seconds}s (not filled).")
                reason_cancelled = "Cancelled by timeout"
                self.ib.waitOnUpdate(timeout=1.0)
                last_status = trade.orderStatus.status
            except Exception as e:
                logger.error(f"Error cancelling order {trade.order.orderId}: {e}")
                reason_cancelled = f"Cancel error: {e}"

        # Log to CSV + Google Sheet
        timestamp = datetime.now().astimezone().isoformat()
        status_for_log = last_status if last_status else "Unknown"
        expiry_logged = qualified_contract.lastTradeDateOrContractMonth

        row = [timestamp, ticker, expiry_logged, float(strike), order_price,
               status_for_log, clientId, permId, reason_cancelled]
        try:
            with open(ORDER_LOG_CSV, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception as e:
            logger.error(f"Failed to write order log row: {e}")

        # ✅ Google Sheets logging (always, even if cancelled)
        try:
            log_order(
                ticker=ticker,
                expiry=expiry_logged,
                strike=float(strike),
                premium=float(order_price) if order_price is not None else None,
                orderStatus=status_for_log,
                clientId=clientId,
                permId=permId,
                reasonCancelled=reason_cancelled
            )
        except Exception as e:
            logger.error(f"Failed to log order to Google Sheet: {e}")

        # Return structured result
        return {
            "timestamp": timestamp,
            "ticker": ticker,
            "expiry": expiry_logged,
            "strike": float(strike),
            "premium": float(order_price) if order_price is not None else None,
            "orderStatus": status_for_log,
            "clientId": clientId,
            "permId": permId,
            "reasonCancelled": reason_cancelled,
            "orderId": getattr(trade.order, "orderId", None),
            "filled": filled
        }

    def reconnect_and_resync(self, max_retries: int = 5, retry_delay: int = 3):
        tries = 0
        while tries < max_retries:
            try:
                if not self.ib.isConnected():
                    self.ib.connect(config.IB_HOST, config.IB_PORT, clientId=config.IB_CLIENT_ID)
                logger.info("Reconnected to IB")
                break
            except Exception as e:
                tries += 1
                logger.warning(f"Reconnect attempt {tries}/{max_retries} failed: {e}. Retrying in {retry_delay}s")
                time.sleep(retry_delay)

        try:
            open_orders = self.ib.reqOpenOrders()
            positions = self.ib.positions()
            logger.info(f"Resynced: {len(open_orders)} open orders, {len(positions)} positions")
            return {"openOrders": open_orders, "positions": positions}
        except Exception as e:
            logger.error(f"Error during resync: {e}")
            return None
