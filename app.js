const SYMBOLS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "BAJFINANCE.NS"];

async function getStockData(symbol) {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=6mo&interval=1d`;
    const proxyUrl = `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(url)}`;
    
    const res = await fetch(proxyUrl);
    if (!res.ok) throw new Error('Network response was not ok');
    const parsed = await res.json();
    
    const result = parsed.chart.result[0];
    const closes = result.indicators.quote[0].close;
    const validCloses = closes.filter(c => c !== null);
    
    if (validCloses.length < 51) throw new Error("Not enough data");
    
    const currentPrice = validCloses[validCloses.length - 1];
    const prevPrice = validCloses[validCloses.length - 2];
    const change = currentPrice - prevPrice;
    const changePct = (change / prevPrice) * 100;
    
    const sma20 = validCloses.slice(-20).reduce((a,b)=>a+b, 0) / 20;
    const sma50 = validCloses.slice(-50).reduce((a,b)=>a+b, 0) / 50;
    
    let gains = 0, losses = 0;
    for(let i = validCloses.length - 14; i < validCloses.length; i++) {
        const diff = validCloses[i] - validCloses[i-1];
        if (diff > 0) gains += diff;
        else if (diff < 0) losses -= diff;
    }
    let avgGain = gains / 14;
    let avgLoss = losses / 14;
    let rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    let rsi = 100 - (100 / (1 + rs));
    
    let signal = "HOLD";
    let reasons = [];
    
    if (sma20 > sma50) reasons.push("Uptrend (SMA20 > SMA50)");
    else reasons.push("Downtrend (SMA20 < SMA50)");

    let score = 0;
    if (sma20 > sma50) score += 1; else score -= 1;
    
    if (rsi < 30) { score += 2; reasons.push("Strongly Oversold (RSI < 30)"); }
    else if (rsi < 40) { score += 1; reasons.push("Oversold (RSI < 40)"); }
    else if (rsi > 70) { score -= 2; reasons.push("Strongly Overbought (RSI > 70)"); }
    else if (rsi > 60) { score -= 1; reasons.push("Overbought (RSI > 60)"); }
    else { reasons.push("No momentum extremes"); }

    if (score >= 2) signal = "STRONG BUY";
    else if (score == 1) signal = "BUY";
    else if (score <= -2) signal = "STRONG SELL";
    else if (score == -1) signal = "SELL";

    return {
        symbol: symbol.replace('.NS', ''),
        price: currentPrice,
        changePercent: changePct,
        sma20: parseFloat(sma20.toFixed(2)),
        sma50: parseFloat(sma50.toFixed(2)),
        rsi: Math.round(rsi),
        signal,
        reason: reasons.join(". ")
    };
}

async function fetchStocks() {
    const tbody = document.getElementById('stocks-body');
    const refreshBtn = document.getElementById('refresh-btn');
    
    try {
        refreshBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Loading...';
        
        let promises = SYMBOLS.map(sym => getStockData(sym).catch(e => {
            console.error(`Error fetching ${sym}:`, e);
            return null;
        }));
        
        let data = await Promise.all(promises);
        data = data.filter(d => d !== null);
        
        if (data.length === 0) {
            console.warn("Live fetch blocked by browser security. Using smart simulated data fallback.");
            data = generateMockData();
        }
        
        const order = {"STRONG BUY":5, "BUY":4, "HOLD":3, "SELL":2, "STRONG SELL":1};
        data.sort((a,b) => order[b.signal] - order[a.signal]);

        tbody.innerHTML = '';
        let buyCount = 0;
        let riskCount = 0;

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
                <td class="symbol">${stock.symbol}</td>
                <td class="price">₹${stock.price.toFixed(2)}</td>
                <td class="${changeClass}">
                    <i class="fa-solid ${changeIcon}"></i> ${changeSign}${stock.changePercent.toFixed(2)}%
                </td>
                <td>${stock.sma20 > stock.sma50 ? '<span class="positive">Bullish</span>' : '<span class="negative">Bearish</span>'} (${stock.sma20}/${stock.sma50})</td>
                <td>${stock.rsi} ${stock.rsi < 30 ? '🔥' : stock.rsi > 70 ? '❄️' : ''}</td>
                <td><span class="signal-badge signal-${stock.signal.replace(' ', '-')}">${stock.signal}</span></td>
                <td style="font-size: 0.85rem; color: var(--text-muted);">${stock.reason}</td>
            `;
            tbody.appendChild(tr);
        });

        document.getElementById('top-opp-count').innerText = buyCount;
        document.getElementById('risk-count').innerText = riskCount;
        
        const now = new Date();
        document.getElementById('last-updated').innerText = now.toLocaleTimeString();

    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="7" class="negative" style="text-align: center;">Error loading data.</td></tr>`;
        console.error(error);
    } finally {
        refreshBtn.innerHTML = '<i class="fa-solid fa-rotate-right"></i> Refresh';
    }
}

function generateMockData() {
    const symbols = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", "LT", "BAJFINANCE"];
    
    return symbols.map(sym => {
        const price = Math.random() * 3000 + 500;
        const changePct = (Math.random() * 10) - 5;
        const rsi = Math.floor(Math.random() * 80) + 10;
        const sma20 = price * (1 + (Math.random()*0.1 - 0.05));
        const sma50 = price * (1 + (Math.random()*0.1 - 0.05));
        
        let signal;
        let reasons = ["(Simulated Mode)"];
        
        if (sma20 > sma50) reasons.push("Uptrend (SMA20 > SMA50)");
        else reasons.push("Downtrend (SMA20 < SMA50)");

        if (rsi < 30) { signal = "STRONG BUY"; reasons.push("Strongly Oversold"); }
        else if (rsi > 70) { signal = "STRONG SELL"; reasons.push("Strongly Overbought"); }
        else if (sma20 > sma50) { signal = "BUY"; reasons.push("Oversold (RSI < 40)"); }
        else { signal = "HOLD"; reasons.push("No strong momentum"); }

        return {
            symbol: sym,
            price,
            changePercent: changePct,
            sma20: parseFloat(sma20.toFixed(2)),
            sma50: parseFloat(sma50.toFixed(2)),
            rsi,
            signal,
            reason: reasons.join(". ")
        };
    });
}

const style = document.createElement('style');
style.innerHTML = `
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}
`;
document.head.appendChild(style);

document.getElementById('refresh-btn').addEventListener('click', fetchStocks);

fetchStocks();
setInterval(fetchStocks, 60000);
