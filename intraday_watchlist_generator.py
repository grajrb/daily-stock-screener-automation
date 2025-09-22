# intraday_watchlist_generator.py
import os
import json
from datetime import datetime
import pandas as pd
from tabulate import tabulate
import yfinance as yf
from gnewsclient import gnewsclient
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import time
import concurrent.futures
from math import ceil

# --- 1. Configuration ---
def load_config(path='config.json'):
    """Loads the JSON configuration file."""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Configuration file not found at '{path}'. Exiting.")
        exit()

# --- 2. Core Analysis Functions ---
def get_nifty500_tickers():
    """Fetches the latest Nifty 500 stock list."""
    print("Fetching latest Nifty 500 constituents...")
    try:
        url = 'https://archives.nseindia.com/content/indices/ind_nifty500list.csv'
        df = pd.read_csv(url)
        return [f"{symbol}.NS" for symbol in df['Symbol']]
    except Exception as e:
        print(f"Could not fetch Nifty 500 list: {e}")
        return []

def get_news_sentiment(ticker, api_key):
    """Fetches news and calculates a sentiment score."""
    # If an API key isn't provided, fall back to the gnewsclient scraper (no key required).
    if not api_key or api_key == "YOUR_GNEWS_API_KEY_HERE":
        print(f"No GNews API key provided - using gnewsclient scraper for {ticker} (may be rate-limited)")
        try:
            client = gnewsclient.NewsClient(language='english', location='India', topic=ticker.replace('.NS', ''), max_results=3)
        except Exception:
            return 0.0
    else:
        try:
            client = gnewsclient.NewsClient(language='english', location='India', topic=ticker.replace('.NS', ''), max_results=3)
        except Exception:
            return 0.0
    try:
        # Run the network call with a timeout to avoid hanging if a request stalls.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(client.get_news)
            try:
                news_list = future.result(timeout=6)
            except concurrent.futures.TimeoutError:
                # Timed out fetching news for this ticker
                return 0.0

        if not news_list:
            return 0.0

        analyzer = SentimentIntensityAnalyzer()
        total_sentiment = sum(analyzer.polarity_scores(item.get('title', ''))['compound'] for item in news_list)
        # Be polite to the news provider
        time.sleep(0.2)
        return total_sentiment / len(news_list)
    except Exception:
        return 0.0

def fetch_history(ticker, period="1y"):
    """Fetch history for a single ticker, returning (ticker, DataFrame or None)."""
    try:
        df = yf.Ticker(ticker).history(period=period)
        if df is None or df.empty:
            return ticker, None
        return ticker, df
    except Exception:
        return ticker, None

def bulk_fetch_histories(tickers, period="1y", max_workers=8):
    """Fetch multiple ticker histories in parallel, returning dict[ticker]=DataFrame or None.
    Respects a max_workers cap and batches to avoid overloading remote API.
    """
    results = {}
    # Batch size heuristic: workers * 5 to keep queue fed without huge burst
    batch_size = max(10, max_workers * 5)
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(fetch_history, t, period): t for t in batch}
            for fut in concurrent.futures.as_completed(futures):
                tkr, df = fut.result()
                results[tkr] = df
        # Gentle pause between batches
        time.sleep(0.5)
    return results

def get_eod_analysis_and_technicals(ticker):
    """
    Performs a full EOD analysis, calculating both the initial score metrics
    and the detailed technicals needed for the action plan.
    """
    try:
        hist = yf.Ticker(ticker).history(period="1y")
        if len(hist) < 201:
            return None  # Need 200 days for SMA

        # --- Initial Scoring Metrics ---
        latest = hist.iloc[-1]
        price_strength = (latest['Close'] - latest['Low']) / (latest['High'] - latest['Low']) if (latest['High'] - latest['Low']) > 0 else 0
        avg_volume_20d = hist['Volume'].rolling(window=20).mean().iloc[-1]
        volume_spike = latest['Volume'] / avg_volume_20d if avg_volume_20d > 0 else 0

        # --- Detailed Technicals for Action Plan ---
        # True Range & ATR(14)
        hist['prev_close'] = hist['Close'].shift(1)
        tr = pd.concat([
            (hist['High'] - hist['Low']).abs(),
            (hist['High'] - hist['prev_close']).abs(),
            (hist['Low'] - hist['prev_close']).abs()
        ], axis=1).max(axis=1)
        atr_14 = tr.rolling(window=14).mean().iloc[-1]

        # Average daily % move (absolute close-to-close pct change) over last 20 days
        abs_pct_move_20 = hist['Close'].pct_change().abs().rolling(window=20).mean().iloc[-1]

        # SMAs
        sma_20 = hist['Close'].rolling(window=20).mean().iloc[-1]
        sma_50 = hist['Close'].rolling(window=50).mean().iloc[-1]
        sma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]

        # RSI
        delta = hist['Close'].diff(1)
        gain = (delta.where(delta > 0, 0)).ewm(com=13, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(com=13, adjust=False).mean()
        rsi = 100 - (100 / (1 + (gain / loss)))

        # 52-week High metrics
        high_52w = hist['High'].rolling(window=252, min_periods=100).max().iloc[-1]
        pct_from_52w_high = ((high_52w - latest['Close']) / high_52w) * 100 if high_52w and high_52w > 0 else None

        # Pivot Points
        pivot = (latest['High'] + latest['Low'] + latest['Close']) / 3
        r1 = (2 * pivot) - latest['Low']
        s1 = (2 * pivot) - latest['High']
        r2 = pivot + (latest['High'] - latest['Low'])
        s2 = pivot - (latest['High'] - latest['Low'])

        return {
            "last_close": latest['Close'],
            "price_strength": price_strength,
            "volume_spike": volume_spike,
            "rsi": rsi.iloc[-1],
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "pivot": pivot, "r1": r1, "s1": s1, "r2": r2, "s2": s2,
            "atr_14": atr_14,
            "avg_abs_pct_move_20": abs_pct_move_20,
            "high_52w": high_52w,
            "pct_from_52w_high": pct_from_52w_high
        }
    except Exception:
        return None

def get_global_sentiment():
    """Fetches performance of the S&P 500."""
    try:
        sp500 = yf.Ticker("^GSPC").history(period="2d")
        sp500_change = sp500['Close'].pct_change().iloc[-1]
        return 1 if sp500_change > 0.001 else (-1 if sp500_change < -0.001 else 0)
    except Exception: return 0

# --- 3. Main Orchestration ---
def generate_intraday_watchlist():
    config = load_config()
    cfg_settings = config['screener_settings']
    cfg_weights = config['scoring_weights']
    cfg_api = config['api_keys']

    tickers = get_nifty500_tickers()
    if not tickers: return

    global_score = get_global_sentiment()
    print(f"Global Sentiment Score: {global_score}")

    # --- STAGE 1: Broad EOD Screening ---
    results = []
    max_workers = config.get('performance', {}).get('parallel_max_workers', 8)
    histories = bulk_fetch_histories(tickers, period="1y", max_workers=max_workers)
    min_price = cfg_settings.get('min_price', 0)
    min_traded_value = cfg_settings.get('min_traded_value_20d', 0)

    for i, ticker in enumerate(tickers):
        print(f"Screening {i+1}/{len(tickers)}: {ticker}", end='\r')
        hist_df = histories.get(ticker)
        if hist_df is None or len(hist_df) < 201:
            continue
        # Temporarily inject a lightweight override into analysis function by patching yf call? Simpler: reuse logic inline.
        # Re-run indicator logic locally replicating get_eod_analysis_and_technicals to avoid refactor right now.
        try:
            latest = hist_df.iloc[-1]
            # Liquidity filters: price and median traded value (Close * Volume) rolling 20d median
            if latest['Close'] < min_price:
                continue
            traded_value_20d = (hist_df['Close'] * hist_df['Volume']).rolling(window=20).median().iloc[-1]
            if traded_value_20d is not None and traded_value_20d < min_traded_value:
                continue
            price_strength = (latest['Close'] - latest['Low']) / (latest['High'] - latest['Low']) if (latest['High'] - latest['Low']) > 0 else 0
            avg_volume_20d = hist_df['Volume'].rolling(window=20).mean().iloc[-1]
            volume_spike = latest['Volume'] / avg_volume_20d if avg_volume_20d > 0 else 0
            hist_df['prev_close'] = hist_df['Close'].shift(1)
            tr = pd.concat([
                (hist_df['High'] - hist_df['Low']).abs(),
                (hist_df['High'] - hist_df['prev_close']).abs(),
                (hist_df['Low'] - hist_df['prev_close']).abs()
            ], axis=1).max(axis=1)
            atr_14 = tr.rolling(window=14).mean().iloc[-1]
            abs_pct_move_20 = hist_df['Close'].pct_change().abs().rolling(window=20).mean().iloc[-1]
            sma_20 = hist_df['Close'].rolling(window=20).mean().iloc[-1]
            sma_50 = hist_df['Close'].rolling(window=50).mean().iloc[-1]
            sma_200 = hist_df['Close'].rolling(window=200).mean().iloc[-1]
            delta = hist_df['Close'].diff(1)
            gain = (delta.where(delta > 0, 0)).ewm(com=13, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(com=13, adjust=False).mean()
            rsi_series = 100 - (100 / (1 + (gain / loss)))
            pivot = (latest['High'] + latest['Low'] + latest['Close']) / 3
            r1 = (2 * pivot) - latest['Low']
            s1 = (2 * pivot) - latest['High']
            r2 = pivot + (latest['High'] - latest['Low'])
            s2 = pivot - (latest['High'] - latest['Low'])
            high_52w = hist_df['High'].rolling(window=252, min_periods=100).max().iloc[-1]
            pct_from_52w_high = ((high_52w - latest['Close']) / high_52w) * 100 if high_52w and high_52w > 0 else None
            analysis_data = {
                'last_close': latest['Close'],
                'price_strength': price_strength,
                'volume_spike': volume_spike,
                'rsi': rsi_series.iloc[-1],
                'sma_20': sma_20,
                'sma_50': sma_50,
                'sma_200': sma_200,
                'pivot': pivot, 'r1': r1, 's1': s1, 'r2': r2, 's2': s2,
                'atr_14': atr_14,
                'avg_abs_pct_move_20': abs_pct_move_20,
                'high_52w': high_52w,
                'pct_from_52w_high': pct_from_52w_high
            }
        except Exception:
            continue

        # Defer news sentiment lookup until after initial scoring to avoid
        # making a network request for every ticker.
        tech_momentum_score = 0
        if analysis_data['rsi'] > 60: tech_momentum_score += 1
        if analysis_data['last_close'] > analysis_data['sma_50']: tech_momentum_score += 1

        # Calculate a preliminary score without news sentiment.
        # Volatility penalty (ATR / price)
        atr_penalty = 0
        if analysis_data.get('atr_14') and analysis_data['last_close'] > 0:
            atr_ratio = analysis_data['atr_14'] / analysis_data['last_close']
            # Assume optional weight in config; fallback constant if not present
            vol_weight = cfg_weights.get('volatility_penalty', 1.0)
            atr_penalty = atr_ratio * vol_weight * -1  # subtractive

        # 52W proximity boost (closer to high -> positive). Normalize inverse distance (cap at 1)
        proximity_component = 0
        pct_from_high = analysis_data.get('pct_from_52w_high')
        if pct_from_high is not None:
            # If within 10% of high, scale 1 -> 0 by distance
            if pct_from_high <= 10:
                proximity_component = (10 - pct_from_high) / 10  # 0..1
        prox_weight = cfg_weights.get('fiftytwo_wk_proximity', 0.5)

        price_component = analysis_data['price_strength'] * cfg_weights['eod_price_strength']
        volume_component = analysis_data['volume_spike'] * cfg_weights['eod_volume_spike']
        momentum_component = tech_momentum_score * cfg_weights['technical_momentum']
        global_component = global_score * cfg_weights['global_sentiment']
        proximity_component_weighted = proximity_component * prox_weight
        volatility_component = atr_penalty  # already negative
        score = (
            price_component + volume_component + momentum_component +
            global_component + proximity_component_weighted + volatility_component
        )
        
        # Store both score and detailed technicals
        analysis_data['ticker'] = ticker
        analysis_data['potential_gainer_score'] = score
        analysis_data['score_components'] = {
            'price': price_component,
            'volume': volume_component,
            'momentum': momentum_component,
            'global': global_component,
            'proximity': proximity_component_weighted,
            'volatility_penalty': volatility_component
        }
        results.append(analysis_data)

    if not results:
        print("\nNo stocks could be analyzed.")
        return

    # --- STAGE 2: Generate Action Plan for Top Stocks ---
    ranked_df = pd.DataFrame(results).sort_values(by='potential_gainer_score', ascending=False)
    top_stocks = ranked_df.head(cfg_settings['top_n_gainers']).copy()
    # Now enrich the shortlisted top stocks with news sentiment (network calls only for top N).
    watchlist = []
    for index, row in top_stocks.iterrows():
        news_sentiment = get_news_sentiment(row['ticker'], cfg_api['gnews'])
        # Combine the previously computed potential_gainer_score with news
        news_component = news_sentiment * cfg_weights['news_sentiment']
        combined_score = row['potential_gainer_score'] + news_component
        comps = row['score_components']
        total_components = {
            'price': comps['price'],
            'volume': comps['volume'],
            'momentum': comps['momentum'],
            'global': comps['global'],
            'proximity': comps['proximity'],
            'volatility_penalty': comps['volatility_penalty'],
            'news': news_component
        }

        # Define Signal
        signal = "HOLD"
        if row['last_close'] > row['sma_50'] and row['last_close'] > row['sma_200'] and row['rsi'] < 80:
            signal = "BUY"
        # Target1 potential percentage
        target1_potential_pct = ((row['r1'] - row['last_close']) / row['last_close']) * 100 if row['last_close'] > 0 else 0
        # Estimate days to reach Target1 using average absolute pct move (avoid divide by zero)
        avg_move = row.get('avg_abs_pct_move_20', 0)
        est_days = (target1_potential_pct / (avg_move * 100)) if avg_move and avg_move > 0 else None

        # Derive extended target levels (R3, R4) using classic pivot extensions
        # R3 = pivot + 2*(High-Low), R4 = pivot + 3*(High-Low) (approx heuristic)
        range_hl = (row['r2'] - row['pivot'])  # (High-Low)
        r3 = row['pivot'] + 2 * range_hl
        r4 = row['pivot'] + 3 * range_hl

        row_dict = {
            "Ticker": row['ticker'].replace('.NS', ''),
            "Signal": signal,
            "Last_Close": f"{row['last_close']:.2f}",
            "Potential_Gainer_Score": f"{combined_score:.2f}",
            "Score_Price": f"{total_components['price']:.2f}",
            "Score_Volume": f"{total_components['volume']:.2f}",
            "Score_Momentum": f"{total_components['momentum']:.2f}",
            "Score_Global": f"{total_components['global']:.2f}",
            "Score_Proximity": f"{total_components['proximity']:.2f}",
            "Score_VolPenalty": f"{total_components['volatility_penalty']:.2f}",
            "Score_News": f"{total_components['news']:.2f}",
            "Target1_Potential_%": f"{target1_potential_pct:.2f}",
            "Est_Days_To_Target1": f"{est_days:.1f}" if est_days is not None else "-",
            "ATR14": f"{row['atr_14']:.2f}" if row.get('atr_14') is not None else "-",
            "AvgAbsPctMove20": f"{row['avg_abs_pct_move_20']*100:.2f}" if row.get('avg_abs_pct_move_20') is not None else "-",
            "Pct_From_52W_High": f"{row['pct_from_52w_high']:.2f}" if row.get('pct_from_52w_high') is not None else "-",
            "Entry_Zone": f"Enter on breakout above R1 ({row['r1']:.2f}) or on dip near Pivot ({row['pivot']:.2f})",
            "Target_1": f"{row['r1']:.2f}",
            "Target_2": f"{row['r2']:.2f}",
            "Target_3": f"{r3:.2f}",
            "Target_4": f"{r4:.2f}",
            "Stop_Loss": f"Below Pivot ({row['pivot']:.2f}) or S1 ({row['s1']:.2f})"
        }
        watchlist.append(row_dict)

    # --- STAGE 3: Save Final Report ---
    watchlist_df = pd.DataFrame(watchlist)
    # Sort: higher Target1 % potential first, then fewer estimated days
    if 'Target1_Potential_%' in watchlist_df.columns:
        # Convert to numeric for sorting
        watchlist_df['Target1_Potential_%_num'] = pd.to_numeric(watchlist_df['Target1_Potential_%'], errors='coerce')
        watchlist_df['Est_Days_To_Target1_num'] = pd.to_numeric(watchlist_df['Est_Days_To_Target1'].replace('-', None), errors='coerce')
        watchlist_df = watchlist_df.sort_values(by=['Target1_Potential_%_num','Est_Days_To_Target1_num'], ascending=[False, True])
        watchlist_df = watchlist_df.drop(columns=['Target1_Potential_%_num','Est_Days_To_Target1_num'])
    date_str = datetime.now().strftime('%Y-%m-%d')
    output_filename = f"intraday_watchlist_{date_str}.csv"
    watchlist_df.to_csv(output_filename, index=False)

    # Markdown summary export (top table only)
    md_filename = f"intraday_watchlist_{date_str}.md"
    try:
        with open(md_filename, 'w', encoding='utf-8') as f:
            f.write(f"# Intraday Bullish Watchlist ({date_str})\n\n")
            f.write(watchlist_df.to_markdown(index=False))
            f.write("\n")
    except Exception as e:
        print(f"Could not write markdown summary: {e}")

    print("\n\n--- Intraday Bullish Watchlist Generated ---")
    print(f"Report saved to '{output_filename}' and markdown '{md_filename}'")
    print(tabulate(watchlist_df, headers='keys', tablefmt='grid', showindex=False))

if __name__ == "__main__":
    try:
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
        SentimentIntensityAnalyzer()
    except LookupError:
        import nltk
        print("Downloading VADER sentiment lexicon for NLTK...")
        nltk.download('vader_lexicon')
        
    generate_intraday_watchlist()