from src.ib_client import IBClient
from typing import Any
from ib_insync import IB, Stock, BarData, Order, Forex, MarketOrder
import time 



class Trader:
    """Executes buy/sell orders based on strategy decisions."""

    def __init__(self, ib_client: IBClient) -> None:
        """
        Initialize the Trader.

        :param ib_client: An instance of IBClient to handle API interactions.
        """
        self.ib: IBClient = ib_client

    def get_next_order_id(self):
        return self.ib.ib.getReqId()

    def wait_for_position(self, order_id, timeout=10):
        start_time = time.time()
        while time.time() - start_time < timeout:
            executions = self.ib.executions()
            for exec in executions:
                if exec.orderId == order_id:
                    return exec
            # await asyncio.sleep(0.5)
            time.sleep(1)
        return None

    def place_bracket_order(self, symbol, action, entry_price, quantity=1, target_pips=10, stop_loss_pips=10):
        contract = Forex(symbol)

        parent_order_id = self.get_next_order_id()
        parent_order = Order(
            orderId=parent_order_id, 
            action=action, 
            orderType='MKT', 
            totalQuantity=quantity, 
            transmit=True
        )

        # entry_price = self.ib.reqMktData(contract).last
        pip_size = 0.0001 if 'JPY' not in symbol else 0.01

        target_price = entry_price + (target_pips * pip_size if action == 'BUY' else -target_pips * pip_size)
        stop_loss_price = entry_price - (stop_loss_pips * pip_size if action == 'BUY' else -stop_loss_pips * pip_size)

        take_profit_order_id = parent_order_id + 1
        stop_order_id = parent_order_id + 2

        # Create the stop loss and take profit orders
        profit_order = Order(
            orderId=take_profit_order_id,
            action='SELL' if action == 'BUY' else 'BUY',
            orderType='LMT',
            totalQuantity=quantity,
            lmtPrice=target_price,
            transmit=True
        )

        loss_order = Order(
            orderId=stop_order_id,
            action='SELL' if action == 'BUY' else 'BUY',
            orderType='STP',
            totalQuantity=quantity,
            auxPrice=stop_loss_price,
            transmit=True
        )

        self.ib.placeOrder(contract, parent_order)
        time.sleep(1)
        self.ib.placeOrder(contract, loss_order)
        time.sleep(1)
        self.ib.placeOrder(contract, profit_order)

        # Wait for the parent order to be executed
        execution = self.wait_for_position(parent_order_id)

        if execution:
            print(f'✅ Parent order executed for {symbol}')
            
            entry_price = execution.price  # Get the actual executed price

            # Dynamically calculate the target and stop loss prices based on execution price
            if action == 'BUY':
                updated_target_price = entry_price + (target_pips * pip_size)
                updated_stop_loss_price = entry_price - (stop_loss_pips * pip_size)
            else:
                updated_target_price = entry_price - (target_pips * pip_size)
                updated_stop_loss_price = entry_price + (stop_loss_pips * pip_size)
            
            profit_order.totalQuanitity = execution.shares
            loss_order.totalQuantity = execution.shares
            profit_order.lmtPrice = updated_target_price
            loss_order.auxPrice = updated_stop_loss_price

            # Place the bracket orders
            time.sleep(2)
            self.ib.placeOrder(contract, profit_order)
            time.sleep(1)
            self.ib.placeOrder(contract, loss_order)

            print(f'✅ Bracket order placed successfully for {symbol}')
            print(f"🎯 Target Price: {updated_target_price}, Stop Loss Price: {updated_stop_loss_price}")
        
        else:
            print(f'❌ Parent order not executed. Aborting.')
    

