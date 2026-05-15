from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import asyncio
import logging
import numpy as np
import csv
import os
import json
import time
from datetime import datetime, date, timedelta
from xgboost import XGBClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV

# --- Debug & Paper Trading Config ---
DEBUG_MODE = False
logging.basicConfig(level=logging.DEBUG if DEBUG_MODE else logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PAPER_TRADES = []
CSV_LOG_FILE = "paper_trades_log.csv"
CACHE_FILE = "stock_cache.json"
BACKTEST_FILE = "backtest_history.json"
MODEL_DATA_FILE = "model_training_data.json"

# --- Server-Side Cache ---
stock_cache = {
    "date": None,
    "data": [],
    "watchlist": []
}

def load_cache():
    global stock_cache
    if os.path.isfile(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                stock_cache = json.load(f)
            logger.info(f"Loaded cache from disk. Date: {stock_cache.get('date')}")
        except Exception as e:
            logger.error(f"Failed to load cache: {e}")

def save_cache():
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(stock_cache, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save cache: {e}")

def log_trade_to_csv(trade):
    file_exists = os.path.isfile(CSV_LOG_FILE)
    try:
        with open(CSV_LOG_FILE, mode='a', newline='') as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(['Symbol', 'Entry_Price', 'Exit_Price', 'Target', 'Stop_Loss', 'Status', 'Time_Opened', 'AI_Probability'])
            
            writer.writerow([
                trade.get('symbol', ''), 
                round(trade.get('entry_price', 0), 2) if trade.get('entry_price') else '', 
                round(trade.get('exit_price', 0), 2) if 'exit_price' in trade else '', 
                round(trade.get('target', 0), 2) if trade.get('target') else '', 
                round(trade.get('stop_loss', 0), 2) if trade.get('stop_loss') else '', 
                trade.get('status', ''), 
                trade.get('time', ''), 
                round(trade.get('prob', 0), 4) if trade.get('prob') else ''
            ])
    except Exception as e:
        logger.error(f"Failed to log trade to CSV: {e}")

# --- XGBoost AI Engine ---
# XGBoost gradient-boosted trees with 10 features for non-linear pattern capture.
# Captures feature interactions (e.g., RSI reversal + volume spike) that linear models miss.
FEATURE_NAMES = [
    'ema_diff_pct', 'vwap_diff_pct', 'change_pct', 'rsi', 'macd_hist',
    'volume_ratio', 'bb_position', 'stoch_rsi', 'obv_trend', 'candle_body_ratio'
]

scaler = StandardScaler()
ml_model = XGBClassifier(
    n_estimators=150,
    max_depth=5,
    learning_rate=0.08,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=3,
    gamma=0.1,
    reg_alpha=0.1,
    reg_lambda=1.0,
    use_label_encoder=False,
    eval_metric='logloss',
    random_state=42,
    verbosity=0
)

# Generate realistic correlated synthetic data (10 features, 500 per class)
np.random.seed(42)
n_seed = 500

def _generate_correlated_seeds(n, bullish=True):
    """Generate synthetic samples with realistic inter-feature correlations."""
    if bullish:
        ema_diff = np.random.uniform(0.05, 3.0, n)
        vwap_diff = ema_diff * np.random.uniform(0.3, 1.5, n) + np.random.normal(0, 0.2, n)
        change_pct = np.random.uniform(0.1, 5.0, n)
        rsi = np.random.uniform(40, 68, n)  # healthy, not overbought
        macd_hist = np.abs(np.random.normal(0.5, 0.8, n))
        vol_ratio = np.random.uniform(1.0, 4.0, n)
        bb_pos = np.random.uniform(0.3, 0.85, n)  # mid-to-upper Bollinger Band
        stoch_rsi = np.random.uniform(0.2, 0.75, n)
        obv_trend = np.random.uniform(0.1, 3.0, n)  # positive OBV slope
        candle_body = np.random.uniform(0.4, 0.95, n)  # strong body candles
    else:
        ema_diff = np.random.uniform(-3.0, -0.05, n)
        vwap_diff = ema_diff * np.random.uniform(0.3, 1.5, n) + np.random.normal(0, 0.2, n)
        change_pct = np.random.uniform(-5.0, 0.5, n)
        rsi = np.random.uniform(20, 80, n)  # wider, includes overbought/oversold
        macd_hist = -np.abs(np.random.normal(0.5, 0.8, n))
        vol_ratio = np.random.uniform(0.3, 1.8, n)
        bb_pos = np.random.uniform(0.0, 0.5, n)  # lower Bollinger Band
        stoch_rsi = np.random.uniform(0.5, 1.0, n)  # overbought stoch
        obv_trend = np.random.uniform(-3.0, 0.5, n)  # negative OBV slope
        candle_body = np.random.uniform(0.05, 0.6, n)  # indecision / doji candles
    return np.column_stack([ema_diff, vwap_diff, change_pct, rsi, macd_hist,
                            vol_ratio, bb_pos, stoch_rsi, obv_trend, candle_body])

X_win = _generate_correlated_seeds(n_seed, bullish=True)
X_lose = _generate_correlated_seeds(n_seed, bullish=False)
# Add ambiguous middle-ground samples to improve calibration
n_mid = 200
X_mid_win = _generate_correlated_seeds(n_mid, bullish=True) * 0.4 + _generate_correlated_seeds(n_mid, bullish=False) * 0.6
X_mid_lose = _generate_correlated_seeds(n_mid, bullish=True) * 0.6 + _generate_correlated_seeds(n_mid, bullish=False) * 0.4

X_seed = np.vstack([X_win, X_lose, X_mid_win, X_mid_lose])
y_seed = np.concatenate([np.ones(n_seed), np.zeros(n_seed), np.zeros(n_mid), np.ones(n_mid)])

# Shuffle training data
shuffle_idx = np.random.permutation(len(y_seed))
X_seed = X_seed[shuffle_idx]
y_seed = y_seed[shuffle_idx]

scaler.fit(X_seed)
X_seed_scaled = scaler.transform(X_seed)
ml_model.fit(X_seed_scaled, y_seed)

logger.info(f"XGBoost AI initialized with {len(y_seed)} samples across {len(FEATURE_NAMES)} features.")
logger.info(f"Feature importance: {dict(zip(FEATURE_NAMES, [round(v, 3) for v in ml_model.feature_importances_]))}")
# ------------------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dynamic NSE stock universe (~200 stocks across all price ranges)
from nse_universe import get_universe
STOCKS = get_universe()
logger.info(f"Loaded {len(STOCKS)} stocks from NSE universe.")

@app.on_event("startup")
async def startup_event():
    load_cache()
    load_training_data()
    if DEBUG_MODE:
        asyncio.create_task(monitor_paper_trades())

async def monitor_paper_trades():
    logger.info("Started continuous AI tuning monitor...")
    while True:
        try:
            await asyncio.sleep(60)
            open_trades = [t for t in PAPER_TRADES if t['status'] == 'OPEN']
            if not open_trades:
                continue
                
            symbols = [t['symbol'] for t in open_trades]
            logger.debug(f"Monitoring open trades for tuning: {symbols}")
            
            for trade in open_trades:
                ticker = trade['symbol']
                df = yf.download(ticker, period="1d", interval="5m", progress=False)
                if df.empty:
                    continue
                
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                    
                current_price = float(df['Close'].iloc[-1])
                
                if current_price >= trade['target']:
                    trade['status'] = 'CLOSED_WIN'
                    trade['exit_price'] = current_price
                    logger.info(f"WIN: {ticker} reached target {trade['target']:.2f}!")
                    fine_tune_model(True, trade)
                    log_trade_to_csv(trade)
                elif current_price <= trade['stop_loss']:
                    trade['status'] = 'CLOSED_LOSS'
                    trade['exit_price'] = current_price
                    logger.info(f"LOSS: {ticker} hit stop loss {trade['stop_loss']:.2f}!")
                    fine_tune_model(False, trade)
                    log_trade_to_csv(trade)
                    
        except Exception as e:
            logger.error(f"Error in tuning monitor: {e}")

# Store real outcome data for periodic retraining
REAL_TRADE_DATA = []
MAX_REAL_SAMPLES = 500  # Rolling cap to prevent model drift from ancient data
MIN_SAMPLES_TO_RETRAIN = 5  # Minimum real samples before first retrain

def _make_sample_key(symbol: str, date_str: str) -> str:
    """Create a unique key for deduplication."""
    return f"{symbol}|{date_str}"

def save_training_data():
    """Persist real trade outcomes to disk for model retention across restarts."""
    try:
        with open(MODEL_DATA_FILE, 'w') as f:
            json.dump(REAL_TRADE_DATA, f, indent=None)
        logger.debug(f"Training data saved: {len(REAL_TRADE_DATA)} samples to disk.")
    except Exception as e:
        logger.error(f"Failed to save training data: {e}")

def load_training_data():
    """Load persisted training data and retrain the model on startup."""
    global REAL_TRADE_DATA, ml_model, scaler
    if not os.path.isfile(MODEL_DATA_FILE):
        return
    try:
        with open(MODEL_DATA_FILE, 'r') as f:
            REAL_TRADE_DATA = json.load(f)
        
        # Migrate old format: add missing metadata fields
        for sample in REAL_TRADE_DATA:
            if 'symbol' not in sample:
                sample['symbol'] = 'UNKNOWN'
            if 'date' not in sample:
                sample['date'] = 'UNKNOWN'
        
        wins = sum(1 for d in REAL_TRADE_DATA if d['outcome'] == 1)
        losses = len(REAL_TRADE_DATA) - wins
        logger.info(f"Loaded {len(REAL_TRADE_DATA)} real trade samples from disk ({wins} wins, {losses} losses).")
        
        if len(REAL_TRADE_DATA) >= MIN_SAMPLES_TO_RETRAIN:
            _retrain_model(log_reason="startup reload")
        elif len(REAL_TRADE_DATA) > 0:
            logger.info(f"Skipping retrain on startup — only {len(REAL_TRADE_DATA)} samples (need {MIN_SAMPLES_TO_RETRAIN}).")
    except Exception as e:
        logger.error(f"Failed to load training data: {e}")

def _retrain_model(log_reason: str = "periodic"):
    """Core retraining logic — combines synthetic seed + weighted real data, refits scaler."""
    global ml_model, scaler
    
    X_real = np.array([d['features'] for d in REAL_TRADE_DATA])
    y_real = np.array([d['outcome'] for d in REAL_TRADE_DATA])
    
    # Dynamic weighting: give real data significant weight so the model actually learns
    real_weight = 15.0 + (len(REAL_TRADE_DATA) / 10.0)
    
    X_combined = np.vstack([X_seed, X_real])
    y_combined = np.concatenate([y_seed, y_real])
    weights_combined = np.concatenate([np.ones(len(y_seed)), np.full(len(y_real), real_weight)])
    
    # Refit scaler to include real data distributions (critical for out-of-range features)
    scaler.fit(X_combined)
    X_combined_scaled = scaler.transform(X_combined)
    
    ml_model.fit(X_combined_scaled, y_combined, sample_weight=weights_combined)
    
    importance = dict(zip(FEATURE_NAMES, [float(round(v, 3)) for v in ml_model.feature_importances_]))
    wins = int(y_real.sum())
    losses = len(y_real) - wins
    logger.info(
        f"XGBoost retrained ({log_reason}): {len(REAL_TRADE_DATA)} real samples "
        f"({wins}W/{losses}L), weight={real_weight:.1f}x, "
        f"importance={importance}"
    )

def fine_tune_model(won: bool, trade: dict):
    """Record a verified trade outcome and retrain the model."""
    global ml_model, REAL_TRADE_DATA
    
    symbol = trade.get('symbol', 'UNKNOWN')
    trade_date = trade.get('date', 'UNKNOWN')
    
    # --- Deduplication: skip if this exact symbol+date already trained ---
    sample_key = _make_sample_key(symbol, trade_date)
    existing_keys = {_make_sample_key(d.get('symbol', ''), d.get('date', '')) for d in REAL_TRADE_DATA}
    if sample_key in existing_keys and symbol != 'UNKNOWN':
        logger.debug(f"Skipping duplicate sample: {sample_key}")
        return False
        
    signal = trade.get('signal', 'BUY')
    
    # Ensure outcome correctly reinforces the model's prediction scale (1=BUY, 0=SELL)
    if "BUY" in signal:
        outcome_val = 1 if won else 0
    elif "SELL" in signal:
        outcome_val = 0 if won else 1
    else:
        return False  # Skip HOLD
    
    logger.info(f"Recording trade outcome for {symbol} ({trade_date}). Won={won}, Signal={signal}, Outcome={outcome_val}")
    
    REAL_TRADE_DATA.append({
        'features': trade['features'],
        'outcome': outcome_val,
        'symbol': symbol,
        'date': trade_date,
        'recorded_at': datetime.now().isoformat()
    })
    
    # --- Rolling cap: evict oldest samples if over limit ---
    if len(REAL_TRADE_DATA) > MAX_REAL_SAMPLES:
        evicted = len(REAL_TRADE_DATA) - MAX_REAL_SAMPLES
        REAL_TRADE_DATA[:] = REAL_TRADE_DATA[-MAX_REAL_SAMPLES:]
        logger.info(f"Evicted {evicted} oldest samples (cap={MAX_REAL_SAMPLES})")
    
    save_training_data()
    
    # --- Retrain schedule: every sample after minimum threshold ---
    if len(REAL_TRADE_DATA) >= MIN_SAMPLES_TO_RETRAIN:
        _retrain_model(log_reason=f"new sample #{len(REAL_TRADE_DATA)}")
    return True

def extract_features(df, close_price, change_pct):
    """Extract 10 normalized features from a stock's dataframe."""
    ema12 = float(df['EMA_12'].iloc[-1])
    ema26 = float(df['EMA_26'].iloc[-1])
    
    vwap_col = [c for c in df.columns if 'VWAP' in c][0]
    vwap = float(df[vwap_col].iloc[-1])
    
    atr_col = [c for c in df.columns if 'ATR' in c][0]
    atr = float(df[atr_col].iloc[-1])
    
    # RSI
    rsi_col = [c for c in df.columns if 'RSI' in c]
    rsi = float(df[rsi_col[0]].iloc[-1]) if rsi_col else 50.0
    
    # MACD histogram
    macd_col = [c for c in df.columns if 'MACDh' in c]
    macd_hist = float(df[macd_col[0]].iloc[-1]) if macd_col else 0.0
    
    # Volume ratio (current vs 20-period average)
    vol = df['Volume']
    vol_avg = vol.rolling(20).mean().iloc[-1]
    vol_ratio = float(vol.iloc[-1] / vol_avg) if vol_avg > 0 else 1.0
    
    # Bollinger Band position (0 = lower band, 1 = upper band)
    bb_cols = [c for c in df.columns if 'BBU' in c]
    bbl_cols = [c for c in df.columns if 'BBL' in c]
    if bb_cols and bbl_cols:
        bb_upper = float(df[bb_cols[0]].iloc[-1])
        bb_lower = float(df[bbl_cols[0]].iloc[-1])
        bb_range = bb_upper - bb_lower
        bb_position = (close_price - bb_lower) / bb_range if bb_range > 0 else 0.5
    else:
        bb_position = 0.5
    
    # Stochastic RSI
    stoch_cols = [c for c in df.columns if 'STOCHRSIk' in c]
    stoch_rsi = float(df[stoch_cols[0]].iloc[-1]) / 100.0 if stoch_cols else 0.5
    
    # OBV trend (slope of last 10 periods, normalized)
    obv_col = [c for c in df.columns if c == 'OBV']
    if obv_col:
        obv_vals = df['OBV'].iloc[-10:].values.astype(float)
        if len(obv_vals) >= 2:
            obv_trend = (obv_vals[-1] - obv_vals[0]) / (abs(obv_vals[0]) + 1e-9)
        else:
            obv_trend = 0.0
    else:
        obv_trend = 0.0
    
    # Candle body ratio (body size / total range)
    high = float(df['High'].iloc[-1])
    low = float(df['Low'].iloc[-1])
    open_price = float(df['Open'].iloc[-1])
    candle_range = high - low
    candle_body = abs(close_price - open_price)
    candle_body_ratio = candle_body / candle_range if candle_range > 0 else 0.5
    
    # Percentage-based features for normalization-friendly values
    ema_diff_pct = ((ema12 - ema26) / ema26) * 100 if ema26 != 0 else 0
    vwap_diff_pct = ((close_price - vwap) / vwap) * 100 if vwap != 0 else 0
    
    features = [ema_diff_pct, vwap_diff_pct, change_pct, rsi, macd_hist,
                vol_ratio, bb_position, stoch_rsi, obv_trend, candle_body_ratio]
    
    return features, ema12, ema26, vwap, atr

def analyze_ticker(ticker, prev_state=None):
    """Run full AI signal analysis on a single ticker. Returns result dict or None."""
    try:
        df = yf.download(ticker, period="5d", interval="15m", progress=False)
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        close_price = float(df['Close'].iloc[-1])
        prev_close = float(df['Close'].iloc[-2])
        change = close_price - prev_close
        change_pct = (change / prev_close) * 100
        
        # Compute all indicators (expanded for 10-feature model)
        df.ta.ema(length=12, append=True)
        df.ta.ema(length=26, append=True)
        df.ta.vwap(append=True)
        df.ta.atr(length=14, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(append=True)
        df.ta.bbands(length=20, append=True)
        df.ta.stochrsi(length=14, append=True)
        df.ta.obv(append=True)
        
        features, ema12, ema26, vwap, atr = extract_features(df, close_price, change_pct)
        
        # Scale features and predict — cast to native Python float for JSON serialization
        features_scaled = scaler.transform([features])
        prob_win = float(ml_model.predict_proba(features_scaled)[0][1])
        features = [float(f) for f in features]  # sanitize numpy types
        
        signal = "HOLD"
        reasons = [f"AI: {prob_win:.0%}"]
        
        # Rich human-readable technical reasons from all 10 features
        if features[0] > 0:
            reasons.append("EMA Bullish")
        else:
            reasons.append("EMA Bearish")
        if features[1] > 0:
            reasons.append("Above VWAP")
        else:
            reasons.append("Below VWAP")
        if features[3] > 70:
            reasons.append("Overbought")
        elif features[3] < 30:
            reasons.append("Oversold")
        if features[6] > 0.8:
            reasons.append("Near Upper BB")
        elif features[6] < 0.2:
            reasons.append("Near Lower BB")
        if features[5] > 2.0:
            reasons.append("High Volume")
        if features[8] > 0.5:
            reasons.append("OBV Rising")
        elif features[8] < -0.5:
            reasons.append("OBV Falling")
        
        if prob_win >= 0.70:
            signal = "STRONG BUY"
        elif prob_win >= 0.55:
            signal = "BUY"
        elif prob_win <= 0.30:
            signal = "STRONG SELL"
        elif prob_win <= 0.45:
            signal = "SELL"
            
        if "BUY" in signal:
            target = close_price + (2.5 * atr)
            stop_loss = close_price - (1.5 * atr)
            hold_time = "1 to 3 hours"
            
            if prev_state and "BUY" in prev_state.get("signal", ""):
                prev_target = prev_state.get("target")
                prev_sl = prev_state.get("stop_loss")
                if prev_target != "-" and prev_sl != "-":
                    if prev_sl < close_price < prev_target:
                        target = prev_target
                        stop_loss = prev_sl
            
            if DEBUG_MODE:
                open_tickers = [t['symbol'] for t in PAPER_TRADES if t['status'] == 'OPEN']
                if ticker not in open_tickers:
                    logger.debug(f"AI initiated paper trade for {ticker}")
                    new_trade = {
                        "symbol": ticker,
                        "entry_price": float(close_price),
                        "target": float(target),
                        "stop_loss": float(stop_loss),
                        "status": "OPEN",
                        "time": datetime.now().isoformat(),
                        "features": [float(f) for f in features],
                        "prob": float(prob_win),
                        "signal": "BUY"
                    }
                    PAPER_TRADES.append(new_trade)
                    log_trade_to_csv(new_trade)
                    
        elif "SELL" in signal:
            target = close_price - (2.5 * atr)
            stop_loss = close_price + (1.5 * atr)
            hold_time = "1 to 3 hours"
            
            if prev_state and "SELL" in prev_state.get("signal", ""):
                prev_target = prev_state.get("target")
                prev_sl = prev_state.get("stop_loss")
                if prev_target != "-" and prev_sl != "-":
                    if prev_target < close_price < prev_sl:
                        target = prev_target
                        stop_loss = prev_sl
        else:
            target = None
            stop_loss = None
            hold_time = "-"
            
        return {
            "symbol": ticker,
            "price": float(round(close_price, 2)),
            "change": float(round(change, 2)),
            "changePercent": float(round(change_pct, 2)),
            "ema12": float(round(ema12, 2)) if pd.notna(ema12) else None,
            "ema26": float(round(ema26, 2)) if pd.notna(ema26) else None,
            "vwap": float(round(vwap, 2)) if pd.notna(vwap) else None,
            "target": float(round(target, 2)) if target else "-",
            "stop_loss": float(round(stop_loss, 2)) if stop_loss else "-",
            "hold_time": hold_time,
            "signal": signal,
            "ai_probability": float(round(prob_win, 4)),
            "reason": " | ".join(reasons)
        }
        
    except Exception as e:
        logger.error(f"Error processing {ticker}: {e}")
        return None


# --- API Endpoints ---

@app.get("/api/cache")
def get_cache():
    """Returns the current cache status and data."""
    today = date.today().isoformat()
    if stock_cache.get("date") == today and stock_cache.get("data"):
        return {"status": "hit", "date": today, "data": stock_cache["data"], "watchlist": stock_cache["watchlist"]}
    return {"status": "empty", "date": today}


@app.get("/api/stocks")
def get_stock_signals(
    min_price: float = Query(default=0, description="Minimum stock price filter"),
    max_price: float = Query(default=0, description="Maximum stock price filter (0 = no upper limit)")
):
    """Full scan: batch-downloads prices for the entire NSE universe, filters by price, analyzes top candidates."""
    global stock_cache
    results = []
    
    eligible_tickers = []
    if min_price > 0 or max_price > 0:
        logger.info(f"Batch screening {len(STOCKS)} stocks for price range: ₹{min_price} – ₹{max_price if max_price > 0 else '∞'}")
        try:
            # Single batch download — MUCH faster than one-by-one
            batch_df = yf.download(STOCKS, period="1d", interval="1d", progress=False, threads=True)
            if not batch_df.empty:
                # yfinance returns MultiIndex columns: (Price, Ticker)
                if isinstance(batch_df.columns, pd.MultiIndex):
                    close_prices = batch_df['Close']
                else:
                    close_prices = batch_df[['Close']]
                
                last_prices = close_prices.iloc[-1]
                for ticker in STOCKS:
                    try:
                        price = float(last_prices[ticker]) if ticker in last_prices.index else None
                        if price and not pd.isna(price):
                            if price >= min_price and (max_price <= 0 or price <= max_price):
                                eligible_tickers.append(ticker)
                    except (KeyError, TypeError):
                        continue
        except Exception as e:
            logger.error(f"Batch download failed, falling back to individual downloads: {e}")
            # Fallback: download individually (slower but reliable)
            for ticker in STOCKS:
                try:
                    info_df = yf.download(ticker, period="1d", interval="1d", progress=False)
                    if info_df.empty:
                        continue
                    if isinstance(info_df.columns, pd.MultiIndex):
                        info_df.columns = info_df.columns.droplevel(1)
                    price = float(info_df['Close'].iloc[-1])
                    if price >= min_price and (max_price <= 0 or price <= max_price):
                        eligible_tickers.append(ticker)
                except Exception:
                    continue
        
        logger.info(f"Found {len(eligible_tickers)} stocks in ₹{min_price}-₹{max_price if max_price > 0 else '∞'} range")
    else:
        # No price filter — use full universe (limited to 50 for speed)
        eligible_tickers = STOCKS[:50]
        logger.info(f"No price filter — scanning top 50 stocks from universe")
    
    # Cap at 30 stocks for detailed analysis to avoid API overload
    if len(eligible_tickers) > 30:
        logger.info(f"Capping analysis from {len(eligible_tickers)} to 30 stocks")
        eligible_tickers = eligible_tickers[:30]
    
    for i, ticker in enumerate(eligible_tickers):
        result = analyze_ticker(ticker)
        if result:
            results.append(result)
        # Small delay every 5 tickers to avoid rate limiting
        if (i + 1) % 5 == 0 and i < len(eligible_tickers) - 1:
            time.sleep(0.5)
            
    results.sort(key=lambda x: x.get('ai_probability', 0), reverse=True)
    top_results = results[:10]
    
    today = date.today().isoformat()
    stock_cache["date"] = today
    stock_cache["data"] = top_results
    stock_cache["watchlist"] = [r["symbol"] for r in top_results]
    save_cache()
    logger.info(f"Cached {len(top_results)} stocks for {today}. Watchlist locked.")
    
    return {"status": "success", "data": top_results, "paper_trades": PAPER_TRADES}


@app.get("/api/stocks/refresh")
def refresh_watchlist():
    """Only refreshes prices for the locked-in watchlist."""
    today = date.today().isoformat()
    
    if stock_cache.get("date") != today or not stock_cache.get("watchlist"):
        return {"status": "no_watchlist", "message": "No watchlist for today. Use /api/stocks with filters first."}
    
    prev_data_map = {item["symbol"]: item for item in stock_cache.get("data", [])}
    
    results = []
    for ticker in stock_cache["watchlist"]:
        result = analyze_ticker(ticker, prev_state=prev_data_map.get(ticker))
        if result:
            results.append(result)
    
    results.sort(key=lambda x: x.get('ai_probability', 0), reverse=True)
    
    stock_cache["data"] = results
    save_cache()
    
    return {"status": "success", "data": results, "paper_trades": PAPER_TRADES}


# --- Paper Trade Management ---

@app.get("/api/paper-trades")
def get_paper_trades():
    """Get all paper trades."""
    return {"paper_trades": PAPER_TRADES}

@app.delete("/api/paper-trades")
def clear_all_paper_trades():
    """Clear all paper trades."""
    global PAPER_TRADES
    PAPER_TRADES = []
    return {"status": "cleared", "message": "All paper trades cleared."}

@app.delete("/api/paper-trades/{index}")
def delete_paper_trade(index: int):
    """Delete a single paper trade by index."""
    global PAPER_TRADES
    if 0 <= index < len(PAPER_TRADES):
        removed = PAPER_TRADES.pop(index)
        return {"status": "deleted", "removed": removed.get("symbol", "unknown")}
    return {"status": "error", "message": "Invalid trade index."}

@app.get("/api/paper-trades/export")
def export_paper_trades():
    """Export all paper trades to a CSV file and return it for download."""
    export_file = "paper_trades_export.csv"
    try:
        with open(export_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Symbol', 'Entry_Price', 'Exit_Price', 'Target', 'Stop_Loss', 'Status', 'Time_Opened', 'AI_Probability'])
            for trade in PAPER_TRADES:
                writer.writerow([
                    trade.get('symbol', ''),
                    round(trade.get('entry_price', 0), 2) if trade.get('entry_price') else '',
                    round(trade.get('exit_price', 0), 2) if 'exit_price' in trade else '',
                    round(trade.get('target', 0), 2) if trade.get('target') else '',
                    round(trade.get('stop_loss', 0), 2) if trade.get('stop_loss') else '',
                    trade.get('status', ''),
                    trade.get('time', ''),
                    round(trade.get('prob', 0), 4) if trade.get('prob') else ''
                ])
        return FileResponse(export_file, filename="paper_trades_export.csv", media_type="text/csv")
    except Exception as e:
        return {"status": "error", "message": str(e)}


# --- Backtesting Engine ---

BACKTEST_HISTORY = []

def load_backtest_history():
    global BACKTEST_HISTORY
    if os.path.isfile(BACKTEST_FILE):
        try:
            with open(BACKTEST_FILE, 'r') as f:
                BACKTEST_HISTORY = json.load(f)
            logger.info(f"Loaded {len(BACKTEST_HISTORY)} backtest sessions from disk.")
        except Exception as e:
            logger.error(f"Failed to load backtest history: {e}")

def save_backtest_history():
    try:
        with open(BACKTEST_FILE, 'w') as f:
            json.dump(BACKTEST_HISTORY, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save backtest history: {e}")

def _get_trading_days_around(target_date_str: str, before: int = 5, after: int = 3):
    """Get a date range for yfinance download that covers trading days around target."""
    target = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    start = target - timedelta(days=before + 10)  # buffer for weekends/holidays
    end = target + timedelta(days=after + 10)
    return start.isoformat(), end.isoformat()

def _extract_features_safe(df, close_price, change_pct):
    """Extract 10 features with graceful fallbacks for daily data (backtest mode).
    Returns (features_list, ema12, ema26, vwap, atr) or (None, ...) if critical data is missing."""
    try:
        # EMA columns
        ema12_col = [c for c in df.columns if 'EMA_12' in c]
        ema26_col = [c for c in df.columns if 'EMA_26' in c]
        if not ema12_col or not ema26_col:
            return None, None, None, None, None
        
        ema12 = float(df[ema12_col[0]].iloc[-1])
        ema26 = float(df[ema26_col[0]].iloc[-1])
        
        if pd.isna(ema12) or pd.isna(ema26):
            return None, None, None, None, None
        
        # VWAP — use proxy for daily data
        vwap_col = [c for c in df.columns if 'VWAP' in c]
        if vwap_col:
            vwap = float(df[vwap_col[0]].iloc[-1])
            if pd.isna(vwap):
                vwap = close_price  # fallback: use current price
        else:
            vwap = close_price
        
        # ATR
        atr_col = [c for c in df.columns if 'ATR' in c]
        if atr_col:
            atr = float(df[atr_col[0]].iloc[-1])
            if pd.isna(atr):
                atr = close_price * 0.02  # 2% default ATR
        else:
            atr = close_price * 0.02
        
        # RSI
        rsi_col = [c for c in df.columns if 'RSI' in c]
        rsi = float(df[rsi_col[0]].iloc[-1]) if rsi_col and not pd.isna(df[rsi_col[0]].iloc[-1]) else 50.0
        
        # MACD histogram
        macd_col = [c for c in df.columns if 'MACDh' in c]
        macd_hist = float(df[macd_col[0]].iloc[-1]) if macd_col and not pd.isna(df[macd_col[0]].iloc[-1]) else 0.0
        
        # Volume ratio
        vol = df['Volume']
        vol_avg = vol.rolling(20).mean().iloc[-1]
        vol_ratio = float(vol.iloc[-1] / vol_avg) if vol_avg and vol_avg > 0 and not pd.isna(vol_avg) else 1.0
        
        # Bollinger Band position
        bb_cols = [c for c in df.columns if 'BBU' in c]
        bbl_cols = [c for c in df.columns if 'BBL' in c]
        if bb_cols and bbl_cols:
            bb_upper = float(df[bb_cols[0]].iloc[-1])
            bb_lower = float(df[bbl_cols[0]].iloc[-1])
            if not pd.isna(bb_upper) and not pd.isna(bb_lower):
                bb_range = bb_upper - bb_lower
                bb_position = (close_price - bb_lower) / bb_range if bb_range > 0 else 0.5
            else:
                bb_position = 0.5
        else:
            bb_position = 0.5
        
        # Stochastic RSI
        stoch_cols = [c for c in df.columns if 'STOCHRSIk' in c]
        if stoch_cols and not pd.isna(df[stoch_cols[0]].iloc[-1]):
            stoch_rsi = float(df[stoch_cols[0]].iloc[-1]) / 100.0
        else:
            stoch_rsi = 0.5
        
        # OBV trend
        obv_col = [c for c in df.columns if c == 'OBV']
        if obv_col:
            obv_vals = df['OBV'].iloc[-10:].values.astype(float)
            obv_vals = obv_vals[~np.isnan(obv_vals)]
            if len(obv_vals) >= 2:
                obv_trend = (obv_vals[-1] - obv_vals[0]) / (abs(obv_vals[0]) + 1e-9)
            else:
                obv_trend = 0.0
        else:
            obv_trend = 0.0
        
        # Candle body ratio
        high = float(df['High'].iloc[-1])
        low = float(df['Low'].iloc[-1])
        open_price = float(df['Open'].iloc[-1])
        candle_range = high - low
        candle_body = abs(close_price - open_price)
        candle_body_ratio = candle_body / candle_range if candle_range > 0 else 0.5
        
        # Percentage-based features
        ema_diff_pct = ((ema12 - ema26) / ema26) * 100 if ema26 != 0 else 0
        vwap_diff_pct = ((close_price - vwap) / vwap) * 100 if vwap != 0 else 0
        
        features = [ema_diff_pct, vwap_diff_pct, change_pct, rsi, macd_hist,
                    vol_ratio, bb_position, stoch_rsi, obv_trend, candle_body_ratio]
        
        # Final NaN check
        if any(pd.isna(f) for f in features):
            features = [0.0 if pd.isna(f) else f for f in features]
        
        return features, ema12, ema26, vwap, atr
        
    except Exception as e:
        logger.debug(f"Feature extraction failed: {e}")
        return None, None, None, None, None

def analyze_ticker_historical(ticker: str, target_date_str: str, start_time: str = None):
    """Run AI analysis on historical data as-of a specific date and optional time, then verify outcome."""
    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        is_intraday = False
        df = pd.DataFrame()
        target_dt = None
        
        if start_time:
            target_dt_limit = pd.Timestamp(f"{target_date_str} {start_time}")
            # Try 15m data (only works if target_date is within last 60 days)
            start_d = (target_date - timedelta(days=15)).strftime("%Y-%m-%d")
            end_d = (target_date + timedelta(days=5)).strftime("%Y-%m-%d")
            df_intra = yf.download(ticker, start=start_d, end=end_d, interval="15m", progress=False)
            
            if not df_intra.empty:
                if isinstance(df_intra.columns, pd.MultiIndex):
                    df_intra.columns = df_intra.columns.droplevel(1)
                df_intra.index = pd.to_datetime(df_intra.index)
                if df_intra.index.tz is not None:
                    df_intra.index = df_intra.index.tz_convert(None)
                
                # Check if we have data up to the requested time
                if len(df_intra[df_intra.index <= target_dt_limit]) >= 30:
                    df = df_intra
                    is_intraday = True
                    target_dt = target_dt_limit
        
        # Fallback to daily if intraday failed or no start_time
        if not is_intraday:
            start_str, end_str = _get_trading_days_around(target_date_str, before=90, after=5)
            df = yf.download(ticker, start=start_str, end=end_str, interval="1d", progress=False)
            if df.empty:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            df.index = pd.to_datetime(df.index)
            if df.index.tz is not None:
                df.index = df.index.tz_convert(None)
            target_dt = pd.Timestamp(target_date_str) + pd.Timedelta(hours=15, minutes=30)
        
        available_dates = df.index[df.index <= target_dt]
        if len(available_dates) < 30:
            return None
        
        analysis_date = available_dates[-1]
        analysis_idx = df.index.get_loc(analysis_date)
        
        # Slice data UP TO the analysis date (simulate not having future data)
        df_past = df.iloc[:analysis_idx + 1].copy()
        
        close_price = float(df_past['Close'].iloc[-1])
        prev_close = float(df_past['Close'].iloc[-2])
        change = close_price - prev_close
        change_pct = (change / prev_close) * 100
        
        # Compute indicators on historical slice
        df_past.ta.ema(length=12, append=True)
        df_past.ta.ema(length=26, append=True)
        df_past.ta.atr(length=14, append=True)
        df_past.ta.rsi(length=14, append=True)
        df_past.ta.macd(append=True)
        df_past.ta.bbands(length=20, append=True)
        df_past.ta.stochrsi(length=14, append=True)
        df_past.ta.obv(append=True)
        
        if is_intraday:
            df_past.ta.vwap(append=True)
            features, ema12, ema26, vwap, atr = extract_features(df_past, close_price, change_pct)
        else:
            tp = (df_past['High'] + df_past['Low'] + df_past['Close']) / 3
            tp_vol = (tp * df_past['Volume']).rolling(20).sum()
            vol_sum = df_past['Volume'].rolling(20).sum()
            df_past['VWAP_proxy'] = tp_vol / vol_sum
            features, ema12, ema26, vwap, atr = _extract_features_safe(df_past, close_price, change_pct)
            
        if features is None or any(pd.isna(f) for f in features):
            return None
        
        features_scaled = scaler.transform([features])
        prob_win = float(ml_model.predict_proba(features_scaled)[0][1])
        features = [float(f) for f in features]
        
        signal = "HOLD"
        if prob_win >= 0.70:
            signal = "STRONG BUY"
        elif prob_win >= 0.55:
            signal = "BUY"
        elif prob_win <= 0.30:
            signal = "STRONG SELL"
        elif prob_win <= 0.45:
            signal = "SELL"
        
        target_price = None
        stop_loss = None
        
        if "BUY" in signal:
            target_price = close_price + (2.5 * atr)
            stop_loss = close_price - (1.5 * atr)
        elif "SELL" in signal:
            target_price = close_price - (2.5 * atr)
            stop_loss = close_price + (1.5 * atr)
        
        # --- Outcome Verification: Check subsequent days ---
        outcome = "PENDING"
        exit_price = None
        exit_date = None
        days_checked = 0
        
        if target_price and stop_loss:
            future_data = df.iloc[analysis_idx + 1:]  # Data AFTER the analysis date
            
            # If intraday, check up to 3 days worth of 15m candles (~75 candles). Else 3 daily candles.
            max_future_rows = 75 if is_intraday else 3
            
            for i in range(min(len(future_data), max_future_rows)):
                day = future_data.iloc[i]
                days_checked += 1
                high = float(day['High'])
                low = float(day['Low'])
                close = float(day['Close'])
                
                if "BUY" in signal:
                    if high >= target_price:
                        outcome = "TARGET HIT"
                        exit_price = float(target_price)
                        exit_date = str(future_data.index[i].date())
                        break
                    elif low <= stop_loss:
                        outcome = "STOP LOSS HIT"
                        exit_price = float(stop_loss)
                        exit_date = str(future_data.index[i].date())
                        break
                elif "SELL" in signal:
                    if low <= target_price:
                        outcome = "TARGET HIT"
                        exit_price = float(target_price)
                        exit_date = str(future_data.index[i].date())
                        break
                    elif high >= stop_loss:
                        outcome = "STOP LOSS HIT"
                        exit_price = float(stop_loss)
                        exit_date = str(future_data.index[i].date())
                        break
            
            if outcome == "PENDING" and days_checked > 0:
                # Neither target nor SL hit — use last close as exit
                last_future = future_data.iloc[min(max_future_rows - 1, len(future_data) - 1)]
                exit_price = float(last_future['Close'])
                if is_intraday:
                    exit_date = str(future_data.index[min(max_future_rows - 1, len(future_data) - 1)])
                else:
                    exit_date = str(future_data.index[min(max_future_rows - 1, len(future_data) - 1)].date())
                
                if "BUY" in signal:
                    outcome = "PARTIAL WIN" if exit_price > close_price else "PARTIAL LOSS"
                elif "SELL" in signal:
                    outcome = "PARTIAL WIN" if exit_price < close_price else "PARTIAL LOSS"
        
        # Calculate P&L
        pnl_pct = 0.0
        if exit_price and target_price:
            if "BUY" in signal:
                pnl_pct = ((exit_price - close_price) / close_price) * 100
            elif "SELL" in signal:
                pnl_pct = ((close_price - exit_price) / close_price) * 100
        
        return {
            "symbol": ticker,
            "analysis_date": str(analysis_date) if is_intraday else str(analysis_date.date()),
            "price": float(round(close_price, 2)),
            "signal": signal,
            "ai_probability": float(round(prob_win, 4)),
            "target": float(round(target_price, 2)) if target_price else None,
            "stop_loss": float(round(stop_loss, 2)) if stop_loss else None,
            "outcome": outcome,
            "exit_price": float(round(exit_price, 2)) if exit_price else None,
            "exit_date": exit_date,
            "pnl_pct": float(round(pnl_pct, 2)),
            "days_checked": days_checked,
            "features": features
        }
        
    except Exception as e:
        logger.error(f"Backtest error for {ticker} on {target_date_str}: {e}")
        return None


@app.get("/api/backtest")
def run_backtest(
    backtest_date: str = Query(..., description="Date to backtest (YYYY-MM-DD)"),
    min_price: float = Query(default=0, description="Min price filter"),
    max_price: float = Query(default=0, description="Max price filter (0 = no limit)"),
    feed_model: bool = Query(default=True, description="Feed outcomes into XGBoost"),
    start_time: str = Query(default=None, description="Time to backtest (HH:MM)")
):
    """Run a full backtest for a specific historical date.
    Analyzes stocks as-of that date, then verifies if targets were hit."""
    global BACKTEST_HISTORY
    load_backtest_history()  # refresh
    
    logger.info(f"Starting backtest for {backtest_date}, price range: {min_price}-{max_price}")
    
    # Use a subset of stocks for speed (configurable via price filter)
    test_tickers = STOCKS[:40]  # Default to top 40
    
    if min_price > 0 or max_price > 0:
        # Quick price screen using the backtest date
        try:
            start_d = (datetime.strptime(backtest_date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
            end_d = (datetime.strptime(backtest_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            batch_df = yf.download(STOCKS, start=start_d, end=end_d, interval="1d", progress=False, threads=True)
            if not batch_df.empty:
                if isinstance(batch_df.columns, pd.MultiIndex):
                    close_prices = batch_df['Close'].iloc[-1]
                else:
                    close_prices = batch_df['Close'].iloc[-1]
                
                test_tickers = []
                for ticker in STOCKS:
                    try:
                        price = float(close_prices[ticker]) if ticker in close_prices.index else None
                        if price and not pd.isna(price):
                            if price >= min_price and (max_price <= 0 or price <= max_price):
                                test_tickers.append(ticker)
                    except (KeyError, TypeError):
                        continue
        except Exception as e:
            logger.error(f"Price screening failed for backtest: {e}")
            test_tickers = STOCKS[:40]
    
    # Cap at 25 for backtest speed
    if len(test_tickers) > 25:
        test_tickers = test_tickers[:25]
    
    logger.info(f"Backtesting {len(test_tickers)} tickers for {backtest_date}")
    
    results = []
    fed_count = 0
    
    for i, ticker in enumerate(test_tickers):
        result = analyze_ticker_historical(ticker, backtest_date, start_time)
        if result and result['signal'] != 'HOLD':
            results.append(result)
            
            # Feed into XGBoost if outcome is definitive or partial
            if feed_model and result['outcome'] in ('TARGET HIT', 'STOP LOSS HIT', 'PARTIAL WIN', 'PARTIAL LOSS'):
                won = result['outcome'] in ('TARGET HIT', 'PARTIAL WIN')
                trade_data = {
                    'features': result['features'],
                    'symbol': result['symbol'],
                    'date': result['analysis_date'],
                    'signal': result['signal']
                }
                accepted = fine_tune_model(won, trade_data)
                if accepted:
                    fed_count += 1
        
        # Rate limiting
        if (i + 1) % 5 == 0 and i < len(test_tickers) - 1:
            time.sleep(0.5)
    
    # Summary stats
    total = len(results)
    target_hits = sum(1 for r in results if r['outcome'] == 'TARGET HIT')
    sl_hits = sum(1 for r in results if r['outcome'] == 'STOP LOSS HIT')
    partial_wins = sum(1 for r in results if r['outcome'] == 'PARTIAL WIN')
    partial_losses = sum(1 for r in results if r['outcome'] == 'PARTIAL LOSS')
    accuracy = (target_hits / total * 100) if total > 0 else 0
    avg_pnl = sum(r['pnl_pct'] for r in results) / total if total > 0 else 0
    
    session = {
        "date": backtest_date,
        "run_at": datetime.now().isoformat(),
        "total_signals": total,
        "target_hits": target_hits,
        "sl_hits": sl_hits,
        "partial_wins": partial_wins,
        "partial_losses": partial_losses,
        "accuracy_pct": round(accuracy, 1),
        "avg_pnl_pct": round(avg_pnl, 2),
        "fed_to_model": fed_count,
        "results": results
    }
    
    BACKTEST_HISTORY.append(session)
    save_backtest_history()
    
    logger.info(f"Backtest complete for {backtest_date}: {total} signals, {target_hits} hits, {accuracy:.1f}% accuracy, fed {fed_count} to model")
    
    return {
        "status": "success",
        "summary": {
            "date": backtest_date,
            "total_signals": total,
            "target_hits": target_hits,
            "sl_hits": sl_hits,
            "partial_wins": partial_wins,
            "partial_losses": partial_losses,
            "accuracy_pct": round(accuracy, 1),
            "avg_pnl_pct": round(avg_pnl, 2),
            "fed_to_model": fed_count,
            "model_total_real_samples": len(REAL_TRADE_DATA)
        },
        "results": results
    }


@app.get("/api/backtest/batch")
def run_batch_backtest(
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    min_price: float = Query(default=0),
    max_price: float = Query(default=0),
    feed_model: bool = Query(default=True),
    start_time: str = Query(default=None)
):
    """Run backtests across a range of dates (business days only)."""
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    
    if end <= start:
        return {"status": "error", "message": "End date must be after start date."}
    if (end - start).days > 30:
        return {"status": "error", "message": "Maximum 30-day range for batch backtest."}
    
    # Generate business days in range
    dates = pd.bdate_range(start, end).strftime("%Y-%m-%d").tolist()
    
    all_sessions = []
    total_fed = 0
    
    for dt in dates:
        logger.info(f"Batch backtest: processing {dt}...")
        result = run_backtest(
            backtest_date=dt,
            min_price=min_price,
            max_price=max_price,
            feed_model=feed_model,
            start_time=start_time
        )
        if result['status'] == 'success':
            all_sessions.append(result['summary'])
            total_fed += result['summary']['fed_to_model']
        time.sleep(1)  # Rate limit between days
    
    # Aggregate stats
    total_signals = sum(s['total_signals'] for s in all_sessions)
    total_hits = sum(s['target_hits'] for s in all_sessions)
    overall_accuracy = (total_hits / total_signals * 100) if total_signals > 0 else 0
    overall_avg_pnl = sum(s['avg_pnl_pct'] * s['total_signals'] for s in all_sessions) / total_signals if total_signals > 0 else 0
    
    return {
        "status": "success",
        "batch_summary": {
            "date_range": f"{start_date} to {end_date}",
            "days_tested": len(all_sessions),
            "total_signals": total_signals,
            "total_target_hits": total_hits,
            "overall_accuracy_pct": round(overall_accuracy, 1),
            "overall_avg_pnl_pct": round(overall_avg_pnl, 2),
            "total_fed_to_model": total_fed,
            "model_total_real_samples": len(REAL_TRADE_DATA)
        },
        "daily_results": all_sessions
    }


@app.get("/api/backtest/history")
def get_backtest_history():
    """Return all stored backtest sessions."""
    load_backtest_history()
    # Return summaries only (without per-stock results) for the list view
    summaries = []
    for session in BACKTEST_HISTORY:
        summaries.append({
            "date": session.get("date"),
            "run_at": session.get("run_at"),
            "total_signals": session.get("total_signals", 0),
            "target_hits": session.get("target_hits", 0),
            "sl_hits": session.get("sl_hits", 0),
            "accuracy_pct": session.get("accuracy_pct", 0),
            "avg_pnl_pct": session.get("avg_pnl_pct", 0),
            "fed_to_model": session.get("fed_to_model", 0)
        })
    return {
        "history": summaries,
        "model_info": {
            "total_real_samples": len(REAL_TRADE_DATA),
            "feature_importance": dict(zip(FEATURE_NAMES, [float(round(v, 3)) for v in ml_model.feature_importances_]))
        }
    }


@app.delete("/api/backtest/history")
def clear_backtest_history():
    """Clear all backtest history."""
    global BACKTEST_HISTORY
    BACKTEST_HISTORY = []
    save_backtest_history()
    return {"status": "cleared", "message": "Backtest history cleared."}


# Serve frontend files (must be AFTER all API routes)
app.mount("/", StaticFiles(directory=".", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    load_backtest_history()
    uvicorn.run(app, host="127.0.0.1", port=8001)
