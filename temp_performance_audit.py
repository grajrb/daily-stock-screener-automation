# temp_performance_audit.py
import yfinance as yf
import pandas as pd
from tabulate import tabulate

# --- Configuration ---
PREDICTIONS = {
    "2024-03-25": {"LONG": ["META"], "SHORT": ["PFE"]}, # Using Mon, Mar 25, 2024
    "2024-03-26": {"LONG": ["NVDA", "AMD"], "SHORT": []},
    "2024-03-27": {"LONG": ["COST"], "SHORT": ["TGT"]},
    "2024-03-28": {"LONG": ["TSLA"], "SHORT": ["BA"]}, # Mar 29 was Good Friday (market closed)
}
WIN_THRESHOLD_PCT = 1.5

def run_performance_audit():
    """
    Fetches historical data to audit the performance of hypothetical trades.
    """
    results = []
    
    print("Running Performance Audit...")
    
    for date_str, trades in PREDICTIONS.items():
        # yfinance needs end date to be the day after
        start_date = date_str
        end_date = (pd.to_datetime(date_str) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        
        all_tickers = trades.get("LONG", []) + trades.get("SHORT", [])
        if not all_tickers:
            continue
            
        data = yf.download(all_tickers, start=start_date, end=end_date, progress=False)
        
        if data.empty:
            print(f"Could not fetch data for {date_str}")
            continue

        # --- Process LONG positions ---
        for ticker in trades.get("LONG", []):
            try:
                day_data = data.loc[start_date] if len(all_tickers) == 1 else data.loc[start_date, :][:, ticker]
                market_open = day_data['Open']
                day_high = day_data['High']
                
                max_intraday_gain = ((day_high - market_open) / market_open) * 100
                is_correct = max_intraday_gain >= WIN_THRESHOLD_PCT
                
                results.append({
                    "Date": date_str,
                    "Ticker": ticker,
                    "Prediction": "LONG",
                    "Outcome": "Correct" if is_correct else "Incorrect",
                    "Max Intraday Move (%)": f"{max_intraday_gain:.2f}%"
                })
            except KeyError:
                results.append({"Date": date_str, "Ticker": ticker, "Prediction": "LONG", "Outcome": "Data Error"})

        # --- Process SHORT positions ---
        for ticker in trades.get("SHORT", []):
            try:
                day_data = data.loc[start_date] if len(all_tickers) == 1 else data.loc[start_date, :][:, ticker]
                market_open = day_data['Open']
                day_low = day_data['Low']

                max_intraday_loss = ((day_low - market_open) / market_open) * 100
                is_correct = max_intraday_loss <= -WIN_THRESHOLD_PCT
                
                results.append({
                    "Date": date_str,
                    "Ticker": ticker,
                    "Prediction": "SHORT",
                    "Outcome": "Correct" if is_correct else "Incorrect",
                    "Max Intraday Move (%)": f"{max_intraday_loss:.2f}%"
                })
            except KeyError:
                results.append({"Date": date_str, "Ticker": ticker, "Prediction": "SHORT", "Outcome": "Data Error"})

    # --- Display Results ---
    results_df = pd.DataFrame(results)
    print("\n--- Performance Audit Results ---")
    print(tabulate(results_df, headers='keys', tablefmt='grid'))
    
    win_loss_tally = results_df['Outcome'].value_counts()
    print("\n--- Final Tally ---")
    print(win_loss_tally)

if __name__ == "__main__":
    run_performance_audit()