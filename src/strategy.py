import pandas as pd
import ta

class Strategy:
    """Trading strategy using moving average crossover."""

    @staticmethod
    def moving_average_crossover(data: pd.DataFrame, short_window: int = 5, long_window: int = 20) -> str:
        """
        Implements a simple moving average crossover strategy.

        :param data: DataFrame containing stock price history
        :param short_window: Short moving average window (default: 5)
        :param long_window: Long moving average window (default: 20)
        :return: "BUY", "SELL", or "HOLD"
        """
        data["SMA_Short"] = data["Close"].rolling(window=short_window).mean()
        data["SMA_Long"] = data["Close"].rolling(window=long_window).mean()

        if data["SMA_Short"].iloc[-1] > data["SMA_Long"].iloc[-1]:
            return "BUY"
        elif data["SMA_Short"].iloc[-1] < data["SMA_Long"].iloc[-1]:
            return "SELL"
        return "HOLD"
    


def trading_signal(df, len1=110, len2=110, len3=18, len4=45):
    """
    Determines trading signals (Buy, Sell, or Null) based on moving average crossovers.
    
    Parameters:
        df (pd.DataFrame): DataFrame with 'close' column.
        len1 (int): Length for first moving average.
        len2 (int): Length for second moving average.
        len3 (int): Length for third moving average.
        len4 (int): Length for fourth moving average.
    
    Returns:
        str: "buy", "sell", or "null".
    """
  
    df = df.copy()  # Avoid modifying the original DataFrame
    # Ensure required columns exist
    if 'Close' not in df.columns:
        raise ValueError("DataFrame must contain a 'Close' column.")

    # Calculate moving averages
    df['ma1'] = ta.trend.ema_indicator(df['Close'], window=len1)
    df['ma2'] = df['Close'].rolling(window=len2).mean()  # Using SMA as a WMA replacement
    df['ma3'] = ta.trend.ema_indicator(df['Close'], window=len3)
    df['ma4'] = ta.trend.ema_indicator(df['Close'], window=len4)
    #print last df value
    
    # Drop NaN values to avoid errors
    df.dropna(inplace=True)
    
    if len(df) == 0:
        return "null"  # Return null if there's no data after dropping NaNs
    
    # Check crossover conditions
    df['crossover'] = (df['ma3'] > df['ma4']) & (df['ma3'].shift(1) <= df['ma4'].shift(1))
    df['crossunder'] = (df['ma3'] < df['ma4']) & (df['ma3'].shift(1) >= df['ma4'].shift(1))
    
    # Long and Short Conditions
    df['long_condition'] = df['crossover'] & (df['ma1'] < df['ma2']) & (df['ma4'] > df[['ma1', 'ma2']].max(axis=1))
    df['short_condition'] = df['crossunder'] & (df['ma1'] > df['ma2']) & (df['ma4'] < df[['ma1', 'ma2']].min(axis=1))
    # print(df.tail(10000))
    # Determine signal
    if df.iloc[-1]['long_condition']:
        return "BUY"
    elif df.iloc[-1]['short_condition']:
        return "SELL"
    else:
        return "null"


