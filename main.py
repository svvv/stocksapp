from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import pandas_ta as ta

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STOCKS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", 
    "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "BAJFINANCE.NS",
    "HINDUNILVR.NS", "AXISBANK.NS", "KOTAKBANK.NS", "MARUTI.NS", "SUNPHARMA.NS"
]

@app.get("/api/stocks")
def get_stock_signals():
    results = []
    
    for ticker in STOCKS:
        try:
            df = yf.download(ticker, period="6mo", interval="1d", progress=False)
            if df.empty:
                continue
                
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
                
            close_price = float(df['Close'].iloc[-1])
            prev_close = float(df['Close'].iloc[-2])
            change = close_price - prev_close
            change_pct = (change / prev_close) * 100
            
            # Indicators
            df.ta.sma(length=20, append=True)
            df.ta.sma(length=50, append=True)
            df.ta.rsi(length=14, append=True)
            
            sma20 = float(df['SMA_20'].iloc[-1])
            sma50 = float(df['SMA_50'].iloc[-1])
            rsi = float(df['RSI_14'].iloc[-1])
            
            signal = "HOLD"
            score = 0
            reasons = []
            
            if sma20 > sma50:
                score += 1
                reasons.append("Uptrend (SMA20 > SMA50)")
            else:
                score -= 1
                reasons.append("Downtrend (SMA20 < SMA50)")
                
            if rsi < 30:
                score += 2
                reasons.append("Strongly Oversold (RSI < 30)")
            elif rsi < 40:
                score += 1
                reasons.append("Oversold (RSI < 40)")
            elif rsi > 70:
                score -= 2
                reasons.append("Strongly Overbought (RSI > 70)")
            elif rsi > 60:
                score -= 1
                reasons.append("Overbought (RSI > 60)")
                
            if score >= 2:
                signal = "STRONG BUY"
            elif score == 1:
                signal = "BUY"
            elif score <= -2:
                signal = "STRONG SELL"
            elif score == -1:
                signal = "SELL"
            else:
                reasons.append("No strong momentum")
                
            results.append({
                "symbol": ticker,
                "price": round(close_price, 2),
                "change": round(change, 2),
                "changePercent": round(change_pct, 2),
                "sma20": round(sma20, 2) if pd.notna(sma20) else None,
                "sma50": round(sma50, 2) if pd.notna(sma50) else None,
                "rsi": round(rsi, 2) if pd.notna(rsi) else None,
                "signal": signal,
                "score": score,
                "reason": ". ".join(reasons)
            })
            
        except Exception as e:
            print(f"Error processing {ticker}: {e}")
            continue
            
    results.sort(key=lambda x: x['score'], reverse=True)
    return {"status": "success", "data": results[:10]}
