from src.data_handler import DataHandler
from src.ib_client import TradeManager
from datetime import datetime, timedelta
from src.ib_client import IBClient

def main() -> None:

    # Initialize and connect IB client
    ib_client = IBClient()
    ib_client.connect()

    tm = TradeManager(ib_client)
    # Initialize DataHandler with IB client
    data_handler = DataHandler(ib_client)

    # Fetch AAPL option chain and select candidate short put
    # res = data_handler.fetch_aapl_options_and_select_csp(min_unique_strikes=10)
    res  = {
        'symbol': 'AAPL',
        'expiry': datetime(2025, 8, 22).date(),
        'right': 'P',
        'strike': 230.0,
        'last': 2.0,
        'bid': 1.0,
        'ask': 1.0,
        'mid': 1,
        'iv': 0.0078,
        'qty': 1,
        'cash_required': 23000.0,
        'conId': None
    }
    mid_price = 1.25

    mid_price = res.get("mid") or (res["bid"] + res["ask"]) / 2 if res["bid"] and res["ask"] else None
    
    if mid_price:
        order_result = tm.place_option_limit_and_wait_cancel(
            ticker=res["symbol"],
            expiry=res["expiry"].strftime("%Y%m%d"),
            strike=res["strike"],
            right=res["right"],
            quantity=res["qty"],
            limit_price=mid_price,
            wait_seconds=5
        )
        
        print(order_result)
    else:
        print("⚠️ Could not determine mid price.")


if __name__ == "__main__":
    main()
