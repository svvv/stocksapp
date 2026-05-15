const API_BASE_URL = 'http://127.0.0.1:8001';

// --- State ---
let currentMinPrice = 0;
let currentMaxPrice = 0;
let watchlistLocked = false; // True once stocks are fetched for the day

// --- Price Filter Presets ---
function applyPreset(min, max) {
    currentMinPrice = min;
    currentMaxPrice = max;
    document.getElementById('min-price').value = min || '';
    document.getElementById('max-price').value = max || '';

    // Highlight the active preset
    document.querySelectorAll('.preset-btn').forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');

    updateFilterStatus(min, max);
    fetchNewStocks(); // Full scan when preset is clicked
}

function applyCustomFilter() {
    const min = parseFloat(document.getElementById('min-price').value) || 0;
    const max = parseFloat(document.getElementById('max-price').value) || 0;
    currentMinPrice = min;
    currentMaxPrice = max;

    document.querySelectorAll('.preset-btn').forEach(btn => btn.classList.remove('active'));
    updateFilterStatus(min, max);
    fetchNewStocks(); // Full scan when custom filter is applied
}

function updateFilterStatus(min, max) {
    const status = document.getElementById('filter-status');
    if (min === 0 && max === 0) {
        status.textContent = 'Showing: All Stocks';
    } else if (max === 0) {
        status.textContent = `Showing: Above ₹${min}`;
    } else {
        status.textContent = `Showing: ₹${min} – ₹${max}`;
    }
}

// --- Fetch NEW stocks (full universe scan) ---
async function fetchNewStocks() {
    const tbody = document.getElementById('stocks-body');
    const refreshBtn = document.getElementById('refresh-btn');
    
    try {
        refreshBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Scanning...';
        
        let data;
        try {
            let url = `${API_BASE_URL}/api/stocks`;
            const params = new URLSearchParams();
            if (currentMinPrice > 0) params.set('min_price', currentMinPrice);
            if (currentMaxPrice > 0) params.set('max_price', currentMaxPrice);
            if (params.toString()) url += '?' + params.toString();

            const response = await fetch(url);
            const result = await response.json();
            data = result.data;
        } catch (e) {
            console.warn("Backend not reachable. Using simulated data.");
            data = generateMockData();
        }

        watchlistLocked = true;
        renderStockTable(data);
        updateSimulator(data);

    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="9" class="negative" style="text-align: center;">Error loading data.</td></tr>`;
        console.error(error);
    } finally {
        refreshBtn.innerHTML = '<i class="fa-solid fa-rotate-right"></i> Refresh Prices';
    }
}

// --- Refresh ONLY the locked watchlist prices ---
async function refreshWatchlist() {
    const tbody = document.getElementById('stocks-body');
    const refreshBtn = document.getElementById('refresh-btn');
    
    try {
        refreshBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Refreshing...';
        
        const response = await fetch(`${API_BASE_URL}/api/stocks/refresh`);
        const result = await response.json();
        
        if (result.status === 'no_watchlist') {
            // No watchlist exists, prompt user to set filters
            showWaitingState();
            return;
        }
        
        renderStockTable(result.data);
        updateSimulator(result.data);
        
    } catch (error) {
        console.error("Refresh failed:", error);
    } finally {
        refreshBtn.innerHTML = '<i class="fa-solid fa-rotate-right"></i> Refresh Prices';
    }
}

// --- The main Refresh button: only refreshes prices once watchlist is set ---
async function handleRefresh() {
    if (watchlistLocked) {
        await refreshWatchlist();
    } else {
        showWaitingState();
    }
}

// --- Render stock data into the table ---
function renderStockTable(data) {
    const tbody = document.getElementById('stocks-body');
    tbody.innerHTML = '';
    let buyCount = 0;
    let riskCount = 0;

    if (!data || data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="loading">No stocks found in this price range. Try a different filter.</td></tr>`;
        document.getElementById('top-opp-count').innerText = '0';
        document.getElementById('risk-count').innerText = '0';
        return;
    }

    data.forEach((stock, index) => {
        if (stock.signal.includes('BUY')) buyCount++;
        if (stock.signal.includes('SELL')) riskCount++;

        const tr = document.createElement('tr');
        tr.style.animation = `fadeIn 0.5s ease forwards ${index * 0.1}s`;
        tr.style.opacity = '0';
        
        const changeClass = stock.changePercent >= 0 ? 'positive' : 'negative';
        const changeIcon = stock.changePercent >= 0 ? 'fa-arrow-trend-up' : 'fa-arrow-trend-down';
        const changeSign = stock.changePercent >= 0 ? '+' : '';

        tr.innerHTML = `
            <td class="symbol">${stock.symbol.replace('.NS', '')}</td>
            <td class="price">₹${stock.price.toFixed(2)}</td>
            <td>${stock.ema12 > stock.ema26 ? '<span class="positive">Bullish</span>' : '<span class="negative">Bearish</span>'} (${stock.ema12}/${stock.ema26})</td>
            <td>₹${stock.vwap}</td>
            <td>
                ${stock.target !== '-' ? `<span class="positive" style="font-weight: 600;">T: ₹${stock.target}</span><br><span class="negative" style="font-size: 0.85rem;">SL: ₹${stock.stop_loss}</span>` : '-'}
            </td>
            <td style="font-size: 0.85rem; color: var(--text-muted);">${stock.hold_time}</td>
            <td><span class="signal-badge signal-${stock.signal.replace(' ', '-')}">${stock.signal}</span></td>
            <td style="font-size: 0.85rem; color: var(--text-muted);">${stock.reason}</td>
            <td><button class="simulate-btn" onclick="simulateTrade('${stock.symbol.replace('.NS', '')}', ${stock.price}, ${stock.target !== '-' ? stock.target : null}, ${stock.stop_loss !== '-' ? stock.stop_loss : null}, '${stock.signal}')" ${stock.target === '-' ? 'disabled style="opacity: 0.5;"' : ''}>Simulate</button></td>
        `;
        tbody.appendChild(tr);
    });

    document.getElementById('top-opp-count').innerText = buyCount;
    document.getElementById('risk-count').innerText = riskCount;
    
    const now = new Date();
    document.getElementById('last-updated').innerText = now.toLocaleTimeString();
}

// --- Show a "waiting for filters" state ---
function showWaitingState() {
    const tbody = document.getElementById('stocks-body');
    tbody.innerHTML = `<tr><td colspan="9" class="loading" style="animation: none; opacity: 1;">
        <i class="fa-solid fa-filter" style="font-size: 1.5rem; margin-bottom: 8px; color: var(--accent);"></i><br>
        Select a price range above and click a preset or Apply to begin scanning.
    </td></tr>`;
}

// --- Check server cache on page load ---
async function checkCacheOnLoad() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/cache`);
        const result = await response.json();
        
        if (result.status === 'hit' && result.data && result.data.length > 0) {
            // Today's cache exists! Show it immediately.
            watchlistLocked = true;
            renderStockTable(result.data);
            document.getElementById('filter-status').textContent = `Watchlist locked (${result.watchlist.length} stocks)`;
            console.log("Loaded cached watchlist for today.");
        } else {
            // No cache for today. Don't auto-fetch. Wait for user to set filters.
            showWaitingState();
        }
    } catch (e) {
        // Backend not running, show waiting state
        console.warn("Backend not reachable on load.");
        showWaitingState();
    }
}

function generateMockData() {
    const symbols = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", "LT", "BAJFINANCE"];
    
    return symbols.map(sym => {
        const price = Math.random() * 3000 + 500;
        const changePct = (Math.random() * 10) - 5;
        const ema12 = price * (1 + (Math.random()*0.02 - 0.01));
        const ema26 = price * (1 + (Math.random()*0.02 - 0.01));
        const vwap = price * (1 + (Math.random()*0.02 - 0.01));
        const atr = price * 0.01; // 1% average true range
        
        let signal;
        let reasons = ["(Simulated Mode)"];
        
        let score = 0;
        if (ema12 > ema26) { score += 1; reasons.push("EMA12 > EMA26"); }
        else { score -= 1; reasons.push("EMA12 < EMA26"); }

        if (price > vwap) { score += 2; reasons.push("Price above VWAP"); }
        else { score -= 2; reasons.push("Price below VWAP"); }

        if (score >= 2) signal = "STRONG BUY";
        else if (score == 1) signal = "BUY";
        else if (score <= -2) signal = "STRONG SELL";
        else if (score == -1) signal = "SELL";
        else signal = "HOLD";

        let target = "-";
        let stop_loss = "-";
        let hold_time = "-";

        if (signal.includes("BUY")) {
            target = (price + (3.0 * atr)).toFixed(2);
            stop_loss = (price - (1.5 * atr)).toFixed(2);
            hold_time = "1 to 3 hours (Exit by 3:15 PM)";
        } else if (signal.includes("SELL")) {
            target = (price - (3.0 * atr)).toFixed(2);
            stop_loss = (price + (1.5 * atr)).toFixed(2);
            hold_time = "1 to 3 hours (Exit by 3:15 PM)";
        }

        return {
            symbol: sym,
            price,
            changePercent: changePct,
            ema12: parseFloat(ema12.toFixed(2)),
            ema26: parseFloat(ema26.toFixed(2)),
            vwap: parseFloat(vwap.toFixed(2)),
            target,
            stop_loss,
            hold_time,
            signal,
            reason: reasons.join(". ")
        };
    }).sort((a,b) => {
        const order = {"STRONG BUY":5, "BUY":4, "HOLD":3, "SELL":2, "STRONG SELL":1};
        return order[b.signal] - order[a.signal];
    });
}

// Paper Trading Logic
let simulatedTrades = JSON.parse(localStorage.getItem('quantumTrades')) || [];

function simulateTrade(symbol, entryPrice, target, stopLoss, signal) {
    if (!target || !stopLoss) return alert("Cannot simulate trade without a target and stop loss.");
    
    // Don't duplicate open trades
    if (simulatedTrades.find(t => t.symbol === symbol && t.status === 'OPEN')) {
        return alert(`You already have an open simulated trade for ${symbol}.`);
    }

    const trade = {
        id: Date.now(),
        symbol,
        entryPrice,
        target,
        stopLoss,
        signal,
        status: 'OPEN', // OPEN, PROFIT, LOSS
        currentPrice: entryPrice
    };

    simulatedTrades.push(trade);
    saveTrades();
    renderSimulator();
    
    // Auto scroll down
    document.querySelector('.simulator-container').scrollIntoView({behavior: 'smooth'});
}

function updateSimulator(liveData) {
    simulatedTrades.forEach(trade => {
        if (trade.status !== 'OPEN') return; // Only track open trades

        const liveStock = liveData.find(s => s.symbol.replace('.NS', '') === trade.symbol);
        if (liveStock) {
            trade.currentPrice = liveStock.price;
            
            // Check win/loss logic based on trade direction
            if (trade.signal.includes('BUY')) {
                if (trade.currentPrice >= trade.target) trade.status = 'PROFIT 🎯';
                else if (trade.currentPrice <= trade.stopLoss) trade.status = 'LOSS 🛑';
            } else if (trade.signal.includes('SELL')) {
                if (trade.currentPrice <= trade.target) trade.status = 'PROFIT 🎯';
                else if (trade.currentPrice >= trade.stopLoss) trade.status = 'LOSS 🛑';
            }
        }
    });
    
    saveTrades();
    renderSimulator();
}

function clearTrades() {
    simulatedTrades = [];
    saveTrades();
    renderSimulator();
}

async function clearAllPaperTrades() {
    if (!confirm('Clear ALL paper trades (both local simulator and server-side)? This cannot be undone.')) return;
    
    // Clear local simulator trades
    simulatedTrades = [];
    saveTrades();
    renderSimulator();
    
    // Clear server-side paper trades
    try {
        await fetch(`${API_BASE_URL}/api/paper-trades`, { method: 'DELETE' });
        console.log('Server paper trades cleared.');
    } catch (e) {
        console.warn('Could not clear server paper trades:', e);
    }
}

function deletePaperTrade(id) {
    simulatedTrades = simulatedTrades.filter(t => t.id !== id);
    saveTrades();
    renderSimulator();
}

async function exportPaperTrades() {
    // Build CSV from local simulator trades
    let csvContent = 'Symbol,Direction,Entry Price,Target,Stop Loss,Current Price,P&L %,Status\n';
    
    simulatedTrades.forEach(trade => {
        let pnl = 0;
        if (trade.signal.includes('BUY')) {
            pnl = ((trade.currentPrice - trade.entryPrice) / trade.entryPrice) * 100;
        } else {
            pnl = ((trade.entryPrice - trade.currentPrice) / trade.entryPrice) * 100;
        }
        csvContent += `${trade.symbol},${trade.signal.includes('BUY') ? 'LONG' : 'SHORT'},${trade.entryPrice.toFixed(2)},${trade.target.toFixed(2)},${trade.stopLoss.toFixed(2)},${trade.currentPrice.toFixed(2)},${pnl.toFixed(2)}%,${trade.status}\n`;
    });
    
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `paper_trades_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

function saveTrades() {
    localStorage.setItem('quantumTrades', JSON.stringify(simulatedTrades));
}

function renderSimulator() {
    const tbody = document.getElementById('simulator-body');
    if (!tbody) return;

    if (simulatedTrades.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted);">No simulated trades active. Click 'Simulate' on a signal above to track it.</td></tr>`;
        return;
    }

    tbody.innerHTML = '';
    
    simulatedTrades.slice().reverse().forEach(trade => {
        let plClass = '';
        let unpl = 0;
        
        if (trade.signal.includes('BUY')) {
            unpl = ((trade.currentPrice - trade.entryPrice) / trade.entryPrice) * 100;
        } else {
            unpl = ((trade.entryPrice - trade.currentPrice) / trade.entryPrice) * 100;
        }
        
        if (unpl > 0) plClass = 'positive';
        else if (unpl < 0) plClass = 'negative';

        const statusColor = trade.status.includes('PROFIT') ? 'var(--buy-color)' : trade.status.includes('LOSS') ? 'var(--sell-color)' : 'var(--hold-color)';

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="symbol">${trade.symbol} <span style="font-size: 0.7rem; color: gray;">(${trade.signal.includes('BUY') ? 'LONG' : 'SHORT'})</span></td>
            <td>₹${trade.entryPrice.toFixed(2)}</td>
            <td class="positive">₹${trade.target.toFixed(2)}</td>
            <td class="negative">₹${trade.stopLoss.toFixed(2)}</td>
            <td>₹${trade.currentPrice.toFixed(2)}</td>
            <td class="${plClass}" style="font-weight: bold;">${unpl > 0 ? '+' : ''}${unpl.toFixed(2)}%</td>
            <td style="color: ${statusColor}; font-weight: bold;">${trade.status}</td>
            <td>
                ${trade.status === 'OPEN' 
                    ? `<button class="sim-delete-btn" style="background: var(--hold-color);" onclick="closeTrade(${trade.id})">Close</button>
                       <button class="sim-delete-btn" style="margin-left:4px;" onclick="deletePaperTrade(${trade.id})"><i class="fa-solid fa-xmark"></i></button>` 
                    : `<button class="sim-delete-btn" onclick="deletePaperTrade(${trade.id})"><i class="fa-solid fa-xmark"></i></button>`
                }
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function closeTrade(id) {
    const trade = simulatedTrades.find(t => t.id === id);
    if (trade) {
        trade.status = 'MANUAL CLOSE ✖️';
        saveTrades();
        renderSimulator();
    }
}

const style = document.createElement('style');
style.innerHTML = `
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}
.simulate-btn {
    background: linear-gradient(135deg, #3a8dff 0%, #0056b3 100%);
    color: white;
    border: none;
    padding: 6px 12px;
    border-radius: 8px;
    cursor: pointer;
    font-weight: bold;
    transition: all 0.3s;
}
.simulate-btn:hover:not(:disabled) {
    transform: translateY(-2px);
    box-shadow: 0 5px 15px rgba(58, 141, 255, 0.4);
}
`;
document.head.appendChild(style);

let autoRefreshInterval = null;

// ====== BACKTESTING ENGINE ======

let btMode = 'single';
let btLastResults = [];

function setBtMode(mode) {
    btMode = mode;
    document.getElementById('bt-mode-single').classList.toggle('active', mode === 'single');
    document.getElementById('bt-mode-batch').classList.toggle('active', mode === 'batch');
    
    // Show/hide end date field
    document.querySelectorAll('.bt-range-field').forEach(el => {
        el.style.display = mode === 'batch' ? 'flex' : 'none';
    });
    
    // Update button text
    const btn = document.getElementById('bt-run-btn');
    if (mode === 'batch') {
        btn.innerHTML = '<i class="fa-solid fa-forward"></i> Run Batch Backtest';
    } else {
        btn.innerHTML = '<i class="fa-solid fa-play"></i> Run Backtest';
    }
}

async function runBacktest() {
    const dateVal = document.getElementById('bt-date').value;
    if (!dateVal) return alert('Please select a backtest date.');
    
    const minPrice = parseFloat(document.getElementById('bt-min-price').value) || 0;
    const maxPrice = parseFloat(document.getElementById('bt-max-price').value) || 0;
    const feedModel = document.getElementById('bt-feed-model').checked;
    const startTime = document.getElementById('bt-time').value;
    
    const btn = document.getElementById('bt-run-btn');
    btn.disabled = true;
    
    try {
        let url, apiLabel;
        
        if (btMode === 'batch') {
            const endDateVal = document.getElementById('bt-end-date').value;
            if (!endDateVal) return alert('Please select an end date for batch mode.');
            
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Running Batch...';
            url = `${API_BASE_URL}/api/backtest/batch?start_date=${dateVal}&end_date=${endDateVal}&min_price=${minPrice}&max_price=${maxPrice}&feed_model=${feedModel}&start_time=${startTime}`;
            apiLabel = 'Batch';
        } else {
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analyzing...';
            url = `${API_BASE_URL}/api/backtest?backtest_date=${dateVal}&min_price=${minPrice}&max_price=${maxPrice}&feed_model=${feedModel}&start_time=${startTime}`;
            apiLabel = 'Single';
        }
        
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.status === 'error') {
            alert(data.message);
            return;
        }
        
        if (btMode === 'batch') {
            // Aggregate batch results
            const summary = data.batch_summary;
            updateBtSummary({
                total_signals: summary.total_signals,
                target_hits: summary.total_target_hits,
                sl_hits: summary.total_signals - summary.total_target_hits, // approximate
                accuracy_pct: summary.overall_accuracy_pct,
                avg_pnl_pct: summary.overall_avg_pnl_pct,
                fed_to_model: summary.total_fed_to_model,
                model_total_real_samples: summary.model_total_real_samples
            });
            
            // Flatten daily results for table (show summaries per day)
            btLastResults = data.daily_results || [];
            renderBtBatchResults(data.daily_results);
        } else {
            updateBtSummary(data.summary);
            btLastResults = data.results || [];
            renderBtResults(data.results);
            updateBtModelStatus(data.summary);
        }
        
        // Refresh history list
        loadBacktestHistory();
        
        // Scroll to results
        document.getElementById('bt-summary').scrollIntoView({ behavior: 'smooth' });
        
    } catch (error) {
        console.error('Backtest failed:', error);
        alert('Backtest failed. Is the backend running?');
    } finally {
        btn.disabled = false;
        if (btMode === 'batch') {
            btn.innerHTML = '<i class="fa-solid fa-forward"></i> Run Batch Backtest';
        } else {
            btn.innerHTML = '<i class="fa-solid fa-play"></i> Run Backtest';
        }
    }
}

function updateBtSummary(summary) {
    document.getElementById('bt-summary').style.display = 'grid';
    document.getElementById('bt-model-status').style.display = 'block';
    document.getElementById('bt-results-section').style.display = 'block';
    
    document.getElementById('bt-total').textContent = summary.total_signals || 0;
    document.getElementById('bt-hits').textContent = summary.target_hits || 0;
    document.getElementById('bt-sl').textContent = summary.sl_hits || 0;
    document.getElementById('bt-accuracy').textContent = `${summary.accuracy_pct || 0}%`;
    
    const pnl = summary.avg_pnl_pct || 0;
    const pnlEl = document.getElementById('bt-pnl');
    pnlEl.textContent = `${pnl >= 0 ? '+' : ''}${pnl}%`;
    pnlEl.style.color = pnl >= 0 ? 'var(--buy-color)' : 'var(--sell-color)';
    document.getElementById('bt-pnl-icon').style.color = pnl >= 0 ? 'var(--buy-color)' : 'var(--sell-color)';
    
    document.getElementById('bt-fed').textContent = summary.fed_to_model || 0;
}

function updateBtModelStatus(summary) {
    const realSamples = summary.model_total_real_samples || 0;
    const badge = document.getElementById('bt-model-badge');
    const realBar = document.getElementById('bt-real-bar');
    const realPct = document.getElementById('bt-real-pct');
    
    document.getElementById('bt-real-samples').textContent = realSamples;
    
    // 1400 synthetic base + real samples (weighted 3x)
    const syntheticCount = 1400;
    const realWeight = realSamples * 3;
    const totalTraining = syntheticCount + realWeight;
    const realPercent = totalTraining > 0 ? (realWeight / totalTraining * 100) : 0;
    
    realBar.style.width = `${Math.min(realPercent, 100)}%`;
    realPct.textContent = `${realPercent.toFixed(1)}% real`;
    
    if (realSamples > 0) {
        badge.textContent = `Learning (${realSamples} real)`;
        badge.className = 'bt-model-badge real-data';
    } else {
        badge.textContent = 'Synthetic Only';
        badge.className = 'bt-model-badge';
    }
}

function getOutcomeClass(outcome) {
    switch (outcome) {
        case 'TARGET HIT': return 'bt-outcome-target';
        case 'STOP LOSS HIT': return 'bt-outcome-sl';
        case 'PARTIAL WIN': return 'bt-outcome-partial-win';
        case 'PARTIAL LOSS': return 'bt-outcome-partial-loss';
        default: return 'bt-outcome-pending';
    }
}

function getOutcomeEmoji(outcome) {
    switch (outcome) {
        case 'TARGET HIT': return '🎯';
        case 'STOP LOSS HIT': return '🛑';
        case 'PARTIAL WIN': return '📈';
        case 'PARTIAL LOSS': return '📉';
        default: return '⏳';
    }
}

function renderBtResults(results) {
    const tbody = document.getElementById('bt-results-body');
    
    if (!results || results.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color: var(--text-muted);">No actionable signals found for this date.</td></tr>';
        return;
    }
    
    tbody.innerHTML = '';
    results.forEach((r, idx) => {
        const tr = document.createElement('tr');
        tr.style.animation = `fadeIn 0.4s ease forwards ${idx * 0.05}s`;
        tr.style.opacity = '0';
        
        const pnlClass = r.pnl_pct > 0 ? 'positive' : r.pnl_pct < 0 ? 'negative' : '';
        const signalClass = r.signal.includes('BUY') ? 'signal-BUY' : r.signal.includes('SELL') ? 'signal-SELL' : 'signal-HOLD';
        
        tr.innerHTML = `
            <td class="symbol">${r.symbol.replace('.NS', '')}</td>
            <td style="font-size: 0.85rem;">${r.analysis_date}</td>
            <td><span class="signal-badge ${signalClass}">${r.signal}</span></td>
            <td style="font-family: monospace; font-weight: 600;">${(r.ai_probability * 100).toFixed(0)}%</td>
            <td class="price">₹${r.price}</td>
            <td class="positive" style="font-weight: 600;">₹${r.target || '-'}</td>
            <td class="negative" style="font-weight: 600;">₹${r.stop_loss || '-'}</td>
            <td style="font-family: monospace;">₹${r.exit_price || '-'}</td>
            <td class="${pnlClass}" style="font-weight: 700;">${r.pnl_pct > 0 ? '+' : ''}${r.pnl_pct}%</td>
            <td><span class="bt-outcome ${getOutcomeClass(r.outcome)}">${getOutcomeEmoji(r.outcome)} ${r.outcome}</span></td>
        `;
        tbody.appendChild(tr);
    });
}

function renderBtBatchResults(dailySummaries) {
    const tbody = document.getElementById('bt-results-body');
    
    if (!dailySummaries || dailySummaries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color: var(--text-muted);">No results from batch backtest.</td></tr>';
        return;
    }
    
    tbody.innerHTML = '';
    
    // Update the header for batch mode
    const thead = document.querySelector('#bt-results-table thead tr');
    thead.innerHTML = `
        <th>Date</th>
        <th>Signals</th>
        <th>Target Hits</th>
        <th>Stop Losses</th>
        <th>Partial Wins</th>
        <th>Partial Losses</th>
        <th>Accuracy</th>
        <th>Avg P&L</th>
        <th>Fed to Model</th>
        <th>Status</th>
    `;
    
    dailySummaries.forEach((s, idx) => {
        const tr = document.createElement('tr');
        tr.style.animation = `fadeIn 0.4s ease forwards ${idx * 0.08}s`;
        tr.style.opacity = '0';
        
        const accClass = s.accuracy_pct >= 60 ? 'positive' : s.accuracy_pct >= 40 ? '' : 'negative';
        const pnlClass = s.avg_pnl_pct > 0 ? 'positive' : s.avg_pnl_pct < 0 ? 'negative' : '';
        
        tr.innerHTML = `
            <td class="symbol">${s.date}</td>
            <td style="font-weight: 700;">${s.total_signals}</td>
            <td class="positive" style="font-weight: 700;">${s.target_hits}</td>
            <td class="negative" style="font-weight: 700;">${s.sl_hits}</td>
            <td style="color: #6ee7b7;">${s.partial_wins || 0}</td>
            <td style="color: #fca5a5;">${s.partial_losses || 0}</td>
            <td class="${accClass}" style="font-weight: 800;">${s.accuracy_pct}%</td>
            <td class="${pnlClass}" style="font-weight: 700;">${s.avg_pnl_pct > 0 ? '+' : ''}${s.avg_pnl_pct}%</td>
            <td style="color: #f59e0b; font-weight: 600;">${s.fed_to_model}</td>
            <td><span class="bt-outcome ${s.accuracy_pct >= 50 ? 'bt-outcome-target' : 'bt-outcome-sl'}">${s.accuracy_pct >= 50 ? '✅' : '⚠️'}</span></td>
        `;
        tbody.appendChild(tr);
    });
}

async function loadBacktestHistory() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/backtest/history`);
        const data = await response.json();
        
        const list = document.getElementById('bt-history-list');
        
        if (!data.history || data.history.length === 0) {
            list.innerHTML = '<div class="bt-history-empty"><i class="fa-solid fa-inbox"></i><br>No backtest sessions yet.</div>';
            return;
        }
        
        // Also update model status if available
        if (data.model_info) {
            updateBtModelStatus({ model_total_real_samples: data.model_info.total_real_samples });
            document.getElementById('bt-model-status').style.display = 'block';
        }
        
        list.innerHTML = '';
        data.history.slice().reverse().forEach((session, idx) => {
            const item = document.createElement('div');
            item.className = 'bt-history-item';
            item.style.animationDelay = `${idx * 0.05}s`;
            
            const accClass = session.accuracy_pct >= 60 ? 'high' : session.accuracy_pct >= 40 ? 'mid' : 'low';
            
            item.innerHTML = `
                <div>
                    <span class="bt-history-date"><i class="fa-solid fa-calendar-day" style="color: #8b5cf6; margin-right: 6px;"></i>${session.date}</span>
                </div>
                <div class="bt-history-meta">
                    <span>${session.total_signals} signals</span>
                    <span class="positive">${session.target_hits} 🎯</span>
                    <span class="negative">${session.sl_hits} 🛑</span>
                    <span class="bt-history-accuracy ${accClass}">${session.accuracy_pct}%</span>
                    <span style="color: ${session.avg_pnl_pct >= 0 ? 'var(--buy-color)' : 'var(--sell-color)'}; font-weight: 700;">${session.avg_pnl_pct >= 0 ? '+' : ''}${session.avg_pnl_pct}%</span>
                    <span style="color: #f59e0b;">🧠 ${session.fed_to_model}</span>
                </div>
            `;
            list.appendChild(item);
        });
        
    } catch (e) {
        console.warn('Could not load backtest history:', e);
    }
}

async function clearBacktestHistory() {
    if (!confirm('Clear ALL backtest history? This cannot be undone.')) return;
    
    try {
        await fetch(`${API_BASE_URL}/api/backtest/history`, { method: 'DELETE' });
        document.getElementById('bt-history-list').innerHTML = '<div class="bt-history-empty"><i class="fa-solid fa-inbox"></i><br>No backtest sessions yet.</div>';
    } catch (e) {
        console.warn('Could not clear backtest history:', e);
    }
}

function exportBacktestResults() {
    if (!btLastResults || btLastResults.length === 0) {
        return alert('No results to export. Run a backtest first.');
    }
    
    let csvContent = 'Symbol,Date,Signal,AI_Probability,Entry_Price,Target,Stop_Loss,Exit_Price,Exit_Date,PnL_Pct,Outcome\n';
    
    btLastResults.forEach(r => {
        // Handle both single results and batch summaries
        if (r.symbol) {
            csvContent += `${r.symbol},${r.analysis_date},${r.signal},${r.ai_probability},${r.price},${r.target || ''},${r.stop_loss || ''},${r.exit_price || ''},${r.exit_date || ''},${r.pnl_pct},${r.outcome}\n`;
        } else if (r.date) {
            csvContent += `${r.date},,SUMMARY,,,,,,${r.avg_pnl_pct},Accuracy: ${r.accuracy_pct}%\n`;
        }
    });
    
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `backtest_${document.getElementById('bt-date').value || 'results'}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

document.addEventListener('DOMContentLoaded', () => {
    // "Refresh" button now only refreshes prices for the locked watchlist
    document.getElementById('refresh-btn').addEventListener('click', handleRefresh);
    
    const toggle = document.getElementById('auto-refresh-toggle');
    if (toggle) {
        toggle.addEventListener('change', (e) => {
            if (e.target.checked) {
                // Auto-refresh only updates prices for the locked watchlist
                autoRefreshInterval = setInterval(refreshWatchlist, 60000);
            } else {
                clearInterval(autoRefreshInterval);
            }
        });
    }
    
    renderSimulator();
    
    // On page load: check server cache. Do NOT auto-fetch new stocks.
    checkCacheOnLoad();
    
    // Initialize backtest date to yesterday (most recent trading day)
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 3); // Default to 3 days ago for outcome data availability
    document.getElementById('bt-date').value = yesterday.toISOString().split('T')[0];
    
    const weekAgo = new Date();
    weekAgo.setDate(weekAgo.getDate() - 10);
    document.getElementById('bt-end-date').value = new Date(Date.now() - 3 * 86400000).toISOString().split('T')[0];
    
    // Set max date to 3 days ago (need future data for verification)
    const maxDate = new Date(Date.now() - 3 * 86400000).toISOString().split('T')[0];
    document.getElementById('bt-date').max = maxDate;
    document.getElementById('bt-end-date').max = maxDate;
    
    // Load backtest history
    loadBacktestHistory();
});

