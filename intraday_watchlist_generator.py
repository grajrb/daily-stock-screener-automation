# intraday_watchlist_generator.py
import os
import json
from datetime import datetime
import pandas as pd
from tabulate import tabulate
import yfinance as yf
from gnewsclient import gnewsclient
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

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
    if not api_key or api_key == "YOUR_GNEWS_API_KEY_HERE": return 0.0
    try:
        client = gnewsclient.NewsClient(language='english', location='India', topic=ticker.replace('.NS', ''), max_results=3)
        news_list = client.get_news()
        if not news_list: return 0.0
        analyzer = SentimentIntensityAnalyzer()
        total_sentiment = sum(analyzer.polarity_scores(item['title'])['compound'] for item in news_list)
        return total_sentiment / len(news_list)
    except Exception: return 0.0

def get_eod_analysis_and_technicals(ticker):
    """
    Performs a full EOD analysis, calculating both the initial score metrics
    and the detailed technicals needed for the action plan.
    """
    try:
        hist = yf.Ticker(ticker).history(period="1y")
        if len(hist) < 201: return None # Need 200 days for SMA

        # --- Initial Scoring Metrics ---
        latest = hist.iloc[-1]
        price_strength = (latest['Close'] - latest['Low']) / (latest['High'] - latest['Low']) if (latest['High'] - latest['Low']) > 0 else 0
        avg_volume_20d = hist['Volume'].rolling(window=20).mean().iloc[-1]
        volume_spike = latest['Volume'] / avg_volume_20d if avg_volume_20d > 0 else 0
        
        # --- Detailed Technicals for Action Plan ---
        # SMAs
        sma_20 = hist['Close'].rolling(window=20).mean().iloc[-1]
        sma_50 = hist['Close'].rolling(window=50).mean().iloc[-1]
        sma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        
        # RSI
        delta = hist['Close'].diff(1)
        gain = (delta.where(delta > 0, 0)).ewm(com=13, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(com=13, adjust=False).mean()
        rsi = 100 - (100 / (1 + (gain / loss)))
        
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
            "pivot": pivot, "r1": r1, "s1": s1, "r2": r2, "s2": s2
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
    for i, ticker in enumerate(tickers):
        print(f"Screening {i+1}/{len(tickers)}: {ticker}", end='\r')
        
        analysis_data = get_eod_analysis_and_technicals(ticker)
        if not analysis_data: continue

        news_sentiment = get_news_sentiment(ticker, cfg_api['gnews'])
        
        tech_momentum_score = 0
        if analysis_data['rsi'] > 60: tech_momentum_score += 1
        if analysis_data['last_close'] > analysis_data['sma_50']: tech_momentum_score += 1

        score = (
            analysis_data['price_strength'] * cfg_weights['eod_price_strength'] +
            analysis_data['volume_spike'] * cfg_weights['eod_volume_spike'] +
            news_sentiment * cfg_weights['news_sentiment'] +
            tech_momentum_score * cfg_weights['technical_momentum'] +
            global_score * cfg_weights['global_sentiment']
        )
        
        # Store both score and detailed technicals
        analysis_data['ticker'] = ticker
        analysis_data['potential_gainer_score'] = score
        results.append(analysis_data)

    if not results:
        print("\nNo stocks could be analyzed.")
        return

    # --- STAGE 2: Generate Action Plan for Top Stocks ---
    ranked_df = pd.DataFrame(results).sort_values(by='potential_gainer_score', ascending=False)
    top_stocks = ranked_df.head(cfg_settings['top_n_gainers']).copy()

    watchlist = []
    for index, row in top_stocks.iterrows():
        # Define Signal
        signal = "HOLD"
        if row['last_close'] > row['sma_50'] and row['last_close'] > row['sma_200'] and row['rsi'] < 80:
            signal = "BUY"
            
        watchlist.append({
            "Ticker": row['ticker'].replace('.NS', ''),
            "Signal": signal,
            "Last_Close": f"{row['last_close']:.2f}",
            "Potential_Gainer_Score": f"{row['potential_gainer_score']:.2f}",
            "Entry_Zone": f"Enter on breakout above R1 ({row['r1']:.2f}) or on dip near Pivot ({row['pivot']:.2f})",
            "Target_1": f"{row['r1']:.2f}",
            "Target_2": f"{row['r2']:.2f}",
            "Stop_Loss": f"Below Pivot ({row['pivot']:.2f}) or S1 ({row['s1']:.2f})"
        })

    # --- STAGE 3: Save Final Report ---
    watchlist_df = pd.DataFrame(watchlist)
    output_filename = f"intraday_watchlist_{datetime.now().strftime('%Y-%m-%d')}.csv"
    watchlist_df.to_csv(output_filename, index=False)

    print("\n\n--- Intraday Bullish Watchlist Generated ---")
    print(f"Report saved to '{output_filename}'")
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