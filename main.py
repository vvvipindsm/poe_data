import time
import config
from src.data_handler import DataHandler
from src.ib_client import IBClient
from datetime import datetime, timedelta
import json

from logger import setup_logger
from flask import Flask, jsonify

data_handler = None 
trade_executed = False

logger = setup_logger("main")
CONFIG_FILE = 'config.json'


def load_config():
    # time.sleep(2)
    with open(CONFIG_FILE, 'r') as file:
        return json.load(file)




def main() -> None:
    """
    Main function that runs the trading system.
    """
    global data_handler
    global trade_executed  
    

    ib_client = IBClient()
    ib_client.connect()

    data_handler = DataHandler(ib_client)
    data_fetched = []
   
    # dd = data_handler.fetch_aapl_options_and_select_csp(123)
    # print(dd)
    while True:
   
        # Align to next :00 or :30 second of the minute
        now = datetime.now()
        seconds = now.second
        millis = now.microsecond / 1_000_000
    
        if seconds < 30:
            sleep_time = 30 - seconds - millis
        else:
            sleep_time = 60 - seconds - millis
        # time.sleep(sleep_time)


        
        config_data = load_config()
        symbols = config_data['symbols']
        for symbol, status in symbols.items():
            if symbol not in data_fetched:
                print("symbol",symbol)
                res = data_handler.fetch_aapl_options_and_select_csp(min_unique_strikes=10)
                if res:
                    # symbol_name = occ_local_symbol(res["symbol"], res["expiry"], res["right"], res["strike"])
                    print("Selected option symbol:", res)
                data_handler.initial_update_historical_data(symbol, end_date_time="")
                data_fetched.append(symbol)
                logger.info(f"Intial - {symbol}")

            if status == False:
                continue

      
            data_new, data_combined = data_handler.update_historical_data(symbol, end_date_time="")

    
            data = data_combined.iloc[-300:]
           


            data_combined["status"] = status
            data_handler.save_historical_data(symbol, data_combined)


    #         time.sleep(2)

    ib_client.disconnect()


if __name__ == "__main__":
    main()


  
    
   
