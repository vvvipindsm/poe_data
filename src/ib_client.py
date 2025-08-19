from textwrap import fill
from ib_insync import IB, Forex, Order, Trade, BarData
import time
import uuid
import threading
import config
from logger import setup_logger
from typing import List
import asyncio, nest_asyncio
from ib_insync import util, IB
import json
from datetime import datetime
import pytz
import os

def setup_event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    nest_asyncio.apply()
    util.patchAsyncio()


logger = setup_logger("IBClient")
tracked_order_ids = []  # Global list for entry/TP/SL order IDs

signal_file = "data/order_signal.json"
trade_file_open = "data/open_position.json"



def save_trade_records_open(data):
    with open(trade_file_open, 'w') as f:
        json.dump(data, f, indent=4)




class IBClient:
    def __init__(self):
        setup_event_loop()
        self.ib = IB()
        # self.ib.execDetailsEvent += self._on_exec_details

        self.active_order_status = {}  # orderId -> status
        self.tracked_orders = set()
        self.fill_timeout = 30
        self.watchdog_timeout = 15

    def connect(self):
        self.ib.connect(config.IB_HOST, config.IB_PORT, clientId=config.IB_CLIENT_ID)
       # self.ib.orderStatusEvent += self._handle_order_status
        logger.info("✅ Connected to IB Gateway")
        
  

    def disconnect(self):
        self.ib.disconnect()
        logger.info("🔌 Disconnected from IB Gateway")
    def get_symbol_key(contract):
        return f"{contract.symbol}{contract.currency}"
    



    def get_historical_data(self, symbol: str, end_date_time:str, duration: str = "1 D", bar_size: str = "5 mins") -> List[BarData]:
        
        contract = Forex(symbol)
        self.ib.qualifyContracts(contract) 

        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime='',
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow='MIDPOINT',
            useRTH=True,
            formatDate=1
        )
        return bars

 
    def _pre_submitted_watchdog(self, order_id, timeout=15):
        def check():
            status = self.active_order_status.get(order_id)
            if status == "PreSubmitted":
                logger.warning(f"[WATCHDOG] Order {order_id} stuck in PreSubmitted after {timeout}s")
        threading.Timer(timeout, check).start()

    def get_next_order_id(self):
        return self.ib.client.getReqId()
    
    def wait_for_execution(self, order_id, symbol, action, timeout=10, is_entry=True, track=True):
        print(f"Waiting for execution of order {order_id} for {symbol} ({action})...")
        start = time.time()
        while time.time() - start < timeout:
            fills = self.ib.fills()
            for fill in fills:
                # print(f"Fill: {fill}")
                if fill.execution.orderId == order_id:
                    return fill.execution
            self.ib.sleep(3)
            
        raise TimeoutError(f"Timeout waiting for execution of order {order_id}")

    def cancel_order(self, order):
        self.ib.cancelOrder(order)
        logger.info(f"❌ Cancelled order {order.orderId}")

    def flatten_position(self, contract, action, quantity):
        market_order = Order(
            action='SELL' if action.upper() == 'BUY' else 'BUY',
            orderType='MKT',
            totalQuantity=quantity
        )
        self.ib.placeOrder(contract, market_order)
        logger.critical(f"[KILL SWITCH] Flattened position on {contract.symbol}")

    def get_open_positions(self, symbol: str = None):
        open_positions = []
        open_orders = []

        try:
            if not self.ib.isConnected():
                self.connect()

            positions = self.ib.positions()
     
            for pos in positions:
                contract = pos.contract

                # Ensure symbol extraction works for both Forex and Stocks
                contract_symbol = getattr(contract, "localSymbol", None) or getattr(contract, "symbol", None)
                contract_symbol = contract_symbol.replace(".", "") 
                stock_position = getattr(pos, "position", None)

                if not contract_symbol:
                    logger.warning("Skipping position due to missing symbol:", pos)
                    continue  # Skip if no symbol is found

                if (contract_symbol == symbol and stock_position != 0):
                    open_positions.append({
                        'account': pos.account,
                        'symbol': contract_symbol,
                        'position': stock_position,
                        'avgCost': pos.avgCost
                    })


            open_statuses = ["Submitted", "PreSubmitted", "PendingSubmit", "PendingCancel"]
            trades = self.ib.reqOpenOrders()  # Returns a list of Trade objects

            for trade in trades:
                order = trade.order
                orderState = trade.orderStatus
                contract = trade.contract

                if orderState.status in open_statuses:
                    if not symbol or (contract.symbol == symbol):

                        open_orders.append({
                            'orderId': order.orderId,         # Changed from order.permId to order.orderId
                            'symbol': contract.symbol,
                            'action': order.action,
                            'orderType': order.orderType,
                            'quantity': order.totalQuantity,
                            'status': orderState.status
                        })

            logger.info(f"✅ Open Positions: {open_positions}")
            logger.info(f"✅ Open Orders: {open_orders}")

            return {'openPositions': open_positions, 'openOrders': open_orders}

        except Exception as e:
            logger.error(f"❌ Error in fetching open positions or orders: {e}")
            raise
    def get_order_status(self, order_id):
        return self.active_order_status.get(order_id, 'Unknown')

    def fallback_kill_switch(self, contract, action, quantity, tp_order, sl_order, timeout=30):
        def task():
            time.sleep(timeout)
            # tp_status = self.get_order_status(tp_order.orderId)
            # sl_status = self.get_order_status(sl_order.orderId)

            # if (tp_status == 'Filled' and sl_status == 'Cancelled') or (sl_status == 'Filled' and tp_status == 'Cancelled'):
            #     logger.info("✅ TP/SL executed properly. Kill switch not needed.")
            #     return

            # logger.error(f"🛑 [KILL SWITCH] TP: {tp_status}, SL: {sl_status}. Triggering fallback.")
            # self.cancel_order(tp_order)
            # self.cancel_order(sl_order)
            # self.flatten_position(contract, action, quantity)

        threading.Thread(target=task).start()

    def place_bracket_order(self, symbol, action, quantity=20000, target_pips=5, stop_loss_pips=5):
        contract = Forex(symbol)
        self.ib.qualifyContracts(contract)
        open_positions = self.get_open_positions(symbol)
        logger.info(f"✅ Open Positions: {open_positions}")
        # print(open_positions)

        if len(open_positions["openPositions"]) > 0 or len(open_positions["openOrders"]) > 0:
            logger.info(f'An existing order already exists for {symbol}, so no new order placed')
            return
        
        pip_size = 0.01 if 'JPY' in symbol else 0.0001

        # Place entry order (market)
        entry_order = Order(
            action=action.upper(),
            orderType='MKT',
            totalQuantity=quantity,
            transmit=True
        )
        entry_trade = self.ib.placeOrder(contract, entry_order)
        entry_order_id = entry_trade.order.orderId
        logger.info(f"📥 Entry Order Sent: ID {entry_order_id} | {action.upper()} {quantity} {symbol}")

        try:
            execution = self.wait_for_execution(entry_order_id, symbol, action, self.fill_timeout, is_entry=True)
        except TimeoutError as e:
            logger.error(str(e))
            return

        entry_price = float(execution.price)
        shares = execution.shares
        is_buy = action.upper() == "BUY"
        
        #storing action
        symbol = symbol
        direction = action.upper()  # 'buy' or 'sell'
        timestamp = execution.time.astimezone(pytz.timezone("Asia/Kolkata")).isoformat()
        price = entry_price

        signal_record = {
            "symbol": symbol,
            "datetime": timestamp,
            "direction": direction,
            "price" :price

        }
        open_order = {
           
            "entryDateTime": timestamp,
            "symbolName": symbol,
            "orderId": execution.orderId,
            "qty":quantity,
            "entryPrice": price,
            "exitDateTime": "",
            "exitPrice": ""
        }
        # Load existing file or create new list
        if os.path.exists(signal_file):
            with open(signal_file, "r") as f:
                try:
                    records = json.load(f)
                except json.JSONDecodeError:
                    records = []
        else:
            records = []
        
        # Open Orders
        if os.path.exists(trade_file_open):
            with open(trade_file_open, "r") as f:
                try:
                    open_orders = json.load(f)
                except json.JSONDecodeError:
                    open_orders = []
        else:
            open_orders = []
        open_orders.append(open_order)
        # Append new signal and save
        records.append(signal_record)
        with open(signal_file, "w") as f:
            json.dump(records, f, indent=4)
        
        with open(trade_file_open, "w") as f:
            json.dump(open_orders, f, indent=4)

        tp_price = round(entry_price + target_pips * pip_size, 5) if is_buy else round(entry_price - target_pips * pip_size, 5)
        sl_price = round(entry_price - stop_loss_pips * pip_size, 5) if is_buy else round(entry_price + stop_loss_pips * pip_size, 5)
        oca_group = f"OCA_{str(uuid.uuid4())[:8]}"
        logger.info(f"📈 TP Price: {tp_price:.5f}, 📉 SL Price: {sl_price:.5f}")
        # Place SL and TP orders as OCA group
        sl_order = Order(
            action='SELL' if is_buy else 'BUY',
            orderType='STP',
            auxPrice=sl_price,
            totalQuantity=shares,
            ocaGroup=oca_group,
            ocaType=1,
            transmit=True  # transmit=False for first OCA order
        )

        tp_order = Order(
            action='SELL' if is_buy else 'BUY',
            orderType='LMT',
            lmtPrice=tp_price,
            totalQuantity=shares,
            ocaGroup=oca_group,
            ocaType=1,
            transmit=True  # transmit=True for last OCA order
        )

        # Place both OCA orders as a group
        sl_trade = self.ib.placeOrder(contract, sl_order)
        tp_trade = self.ib.placeOrder(contract, tp_order)
        logger.info(f"📈 TP Order Sent: Qty: {shares} @ {tp_price:.5f}")
        logger.info(f"📉 SL Order Sent: Qty: {shares} @ {sl_price:.5f}")
        tracked_order_ids.extend([entry_order_id, tp_trade.order.orderId, sl_trade.order.orderId])
     
        logger.info(f"✅  Order Sent: Entry={entry_price:.5f}, TP={tp_price:.5f}, SL={sl_price:.5f}")

        # Optionally, track OCA order IDs for status
        self.tracked_orders.update([sl_trade.order.orderId, tp_trade.order.orderId])

        self._pre_submitted_watchdog(sl_trade.order.orderId, self.watchdog_timeout)
        self._pre_submitted_watchdog(tp_trade.order.orderId, self.watchdog_timeout)
        self.fallback_kill_switch(contract, action, shares, tp_trade.order, sl_trade.order, timeout=30)
