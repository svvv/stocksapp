import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np

ticker = "RELIANCE.NS"
target_date_str = "2024-05-10" # Recent date within 60 days to test 15m
start_time = "10:15"

target_dt = pd.Timestamp(f"{target_date_str} {start_time}")
start_d = (target_dt.date() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
end_d = (target_dt.date() + pd.Timedelta(days=5)).strftime("%Y-%m-%d")

df = yf.download(ticker, start=start_d, end=end_d, interval="15m", progress=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)
df.index = pd.to_datetime(df.index).tz_localize(None)

available_dates = df.index[df.index <= target_dt]
print(f"Total rows: {len(df)}")
print(f"Available rows up to {target_dt}: {len(available_dates)}")
if len(available_dates) > 0:
    analysis_date = available_dates[-1]
    analysis_idx = df.index.get_loc(analysis_date)
    print(f"Analysis date: {analysis_date}, index: {analysis_idx}")
    future = df.iloc[analysis_idx+1 : analysis_idx+1+75]
    print(f"Future rows: {len(future)}")
