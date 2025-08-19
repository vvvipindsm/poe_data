from flask import Flask, render_template, request, jsonify,send_from_directory
import json
import config
import pandas as pd
import ta
import pytz
from datetime import datetime
import numpy as np

app = Flask(__name__)

CONFIG_FILE = 'config.json'
import os


@app.route('/add_symbol', methods=['POST'])
def add_symbol():
    symbol = request.json.get('symbol').upper()
    config_data = load_config()

    if symbol not in config_data['symbols']:
        config_data['symbols'][symbol] = True
        config_data['symbolsStatus'][symbol] = False
        # config_data['fetched'][symbol] = False
        save_config(config_data)
        return jsonify({'message': f'{symbol} added and started trading.'}), 200
    else:
        if not config_data['symbols'][symbol]:
            config_data['symbols'][symbol] = True
            save_config(config_data)
            return jsonify({'message': f'{symbol} started trading.'}), 200
        return jsonify({'message': f'{symbol} is already active.'}), 400


@app.route('/get_available_symbols')
def get_available_symbols():
    folder = 'data'
    if not os.path.exists(folder):
        return jsonify({'symbols': []})
    files = os.listdir(folder)
    symbols = [f.replace('.csv', '') for f in files if f.endswith('.csv')]
    return jsonify({'symbols': symbols})

@app.route('/get_active_symbols', methods=['GET'])
def get_active_symbols():
    config_data = load_config()
    print(config_data)
    active_symbols = [sym for sym, val in config_data['symbols'].items() if val]
    return jsonify({'stocks': active_symbols})

@app.route('/stop_trading', methods=['POST'])
def stop_trading():
    symbol = request.json.get('symbol').upper()
    config_data = load_config()
    if symbol in config_data['symbols']:
        config_data['symbols'][symbol] = False
        save_config(config_data)
        return jsonify({'message': f'{symbol} stopped trading.'}), 200
    return jsonify({'message': f'{symbol} not found.'}), 404


@app.route('/get_chart_data/<symbol>')
def get_chart_data(symbol):
    filepath = f"data/{symbol}.csv"
    try:
        df = pd.read_csv(filepath)
        df = df.tail(500)  # Use recent 500 candles

        df['time'] = pd.to_datetime(df['Date'])
        df['timestamp'] = df['time'].astype(int) // 10**9

        # === Calculate indicators ===
        len1, len2, len3, len4 = 9, 21, 50, 200
        df['ma1'] = ta.trend.ema_indicator(df['Close'], window=len1)
        df['ma2'] = df['Close'].rolling(window=len2).mean()
        df['ma3'] = ta.trend.ema_indicator(df['Close'], window=len3)
        df['ma4'] = ta.trend.ema_indicator(df['Close'], window=len4)

        # === OHLC Data ===
        chart_data = df[['timestamp', 'Open', 'High', 'Low', 'Close']].rename(
            columns={
                'timestamp': 'time',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close'
            }
        ).to_dict(orient='records')

        # === Trade Markers ===
        markers = []
        for _, row in df.iterrows():
            status = str(row.get('status', '')).upper()
            if "BUY" in status:
                markers.append({
                    'time': int(row['timestamp']),
                    'position': 'belowBar',
                    'color': 'green',
                    'shape': 'arrowUp',
                    'text': status
                })
            elif "SELL" in status:
                markers.append({
                    'time': int(row['timestamp']),
                    'position': 'aboveBar',
                    'color': 'red',
                    'shape': 'arrowDown',
                    'text': status
                })

        # === Moving Averages as Line Series ===
        def to_line_series(series):
            return [
                {'time': int(ts), 'value': round(val, 5)}
                for ts, val in zip(df['timestamp'], series)
                if not pd.isna(val)
            ]

        ma1 = to_line_series(df['ma1'])
        ma2 = to_line_series(df['ma2'])
        ma3 = to_line_series(df['ma3'])
        ma4 = to_line_series(df['ma4'])

        return jsonify({
            'candles': chart_data,
            'markers': markers,
            'ma1': ma1,
            'ma2': ma2,
            'ma3': ma3,
            'ma4': ma4
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def reset_config():
    symbols = config.FOREX_SYMBOLS
    default_config = {
        "symbols": {
            symbol: False for symbol in symbols
        }
    }
    with open(CONFIG_FILE, 'w') as file:
        json.dump(default_config, file, indent=4)

# Reset on every restart
reset_config()

def load_config():
    with open(CONFIG_FILE, 'r') as file:
        return json.load(file)

def save_config(data):
    with open(CONFIG_FILE, 'w') as file:
        json.dump(data, file, indent=4)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
