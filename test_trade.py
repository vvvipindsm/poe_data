from src.ib_client import IBClient, TradeManager
from datetime import datetime
from ib_insync import IB, Option
import config

def main():
    # Connect to IB
    ib_client = IBClient()
    ib_client.connect()
    ib = ib_client.ib

    tm = TradeManager(ib_client)

    # Build raw contract for AAPL put
    symbol = "AAPL"
    strike = 230.0
    right = "P"
    expiry_input = datetime(2025, 9, 26).strftime("%Y%m%d")  # initial requested expiry

    contract = Option(
        symbol=symbol,
        lastTradeDateOrContractMonth=expiry_input,
        strike=strike,
        right=right,
        exchange="SMART",
        currency="USD"
    )

    # Qualify contract with IB
    qualified_contracts = ib.qualifyContracts(contract)
  
    if not qualified_contracts:
        raise Exception("No qualified contract returned")
    qualified_contract = qualified_contracts[0]

    print("✅ Qualified contract expiry:", qualified_contract.lastTradeDateOrContractMonth)
    print("✅ ConId:", qualified_contract.conId)
   
    # Prepare order data using qualified contract
    mid_price = 5.00  # example price
    res = {
        'symbol': symbol,
        'expiry': qualified_contract.lastTradeDateOrContractMonth,
        'right': right,
        'strike': strike,
        'mid': mid_price,
        'qty': 1,
        'conId': qualified_contract.conId
    }
  

    # Place order using TradeManager
    order_result = tm.place_option_limit_and_wait_cancel(
        ticker=res['symbol'],
        expiry=res['expiry'],
        strike=res['strike'],
        right=res['right'],
        quantity=res['qty'],
        limit_price=res['mid'],
        wait_seconds=5
    )

    print("Order Result:", order_result)


if __name__ == "__main__":
    main()
