# backtester.py
import os
import pandas as pd
import yfinance as yf
from tabulate import tabulate
import glob
import re
from datetime import timedelta

def load_predictions():
    """Loads and consolidates all prediction CSV files."""
    prediction_files = glob.glob('intraday_watchlist_*.csv')
    if not prediction_files:
        raise FileNotFoundError("No 'intraday_watchlist_*.csv' files found.")
    
    all_predictions = []
    for f in prediction_files:
        df = pd.read_csv(f)
        df['Date'] = pd.to_datetime(f.split('_')[-1].replace('.csv', ''))
        all_predictions.append(df)
        
    return pd.concat(all_predictions, ignore_index=True)

def run_daily_data_backtest(predictions_df):
    """
    Runs the backtest by fetching daily OHLC data from yfinance.
    """
    results = []
    
    for index, trade in predictions_df.iterrows():
        ticker = trade['Ticker'] + ".NS"
        trade_date = trade['Date']
        prediction_type = trade['Signal']
        
        if prediction_type != 'BUY':
            continue

        try:
            target_str = re.search(r'(\d+\.\d+)', str(trade['Target_1']))
            stop_str = re.search(r'(\d+\.\d+)', str(trade['Stop_Loss']))
            if not target_str or not stop_str:
                continue
            target_price = float(target_str.group(1))
            stop_loss = float(stop_str.group(1))
        except (TypeError, IndexError):
            continue

        outcome = "No Result"
        day_high = None
        day_low = None

        try:
            # --- Fetch DAILY data using yfinance ---
            start_date = trade_date.strftime('%Y-%m-%d')
            end_date = (trade_date + timedelta(days=1)).strftime('%Y-%m-%d')
            
            daily_df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            
            # --- DEBUG: Print the raw dataframe received from yfinance ---
            print(f"\n--- Raw Data for {ticker} ---")
            print(daily_df.to_string())
            print("---------------------------\n")

            if daily_df.empty:
                outcome = "Data Not Found"
            else:
                day_high = daily_df['High'].iloc[0]
                day_low = daily_df['Low'].iloc[0]
                
                # --- Determine Outcome based on Daily OHLC ---
                if prediction_type == 'BUY':
                    # If stop-loss was hit during the day
                    if day_low <= stop_loss:
                        outcome = "Loss"
                    # If stop-loss was NOT hit and target was hit
                    elif day_high >= target_price:
                        outcome = "Win"
            
        except Exception as e:
            # Capture the full error message for better debugging
            outcome = f"yfinance_Error: {str(e)}"

        results.append({
            "Date": trade_date.date(),
            "Ticker": ticker.replace('.NS', ''),
            "Prediction_Type": prediction_type,
            "Target_Price": target_price,
            "Stop_Loss": stop_loss,
            "Day_High": day_high,
            "Day_Low": day_low,
            "Outcome": outcome
        })

    return pd.DataFrame(results)

if __name__ == "__main__":
    try:
        predictions = load_predictions()
        print(f"Loaded {len(predictions)} predictions from {len(glob.glob('intraday_watchlist_*.csv'))} files.")
        
        backtest_results = run_daily_data_backtest(predictions)
        
        if backtest_results.empty:
            print("\nBacktest complete. No valid trades could be analyzed.")
            exit()
            
        print("\n--- Performance Backtest & Audit (Based on Daily OHLC) ---")
        print(tabulate(backtest_results, headers='keys', tablefmt='grid'))
        
        backtest_results['Final_Outcome'] = backtest_results['Outcome'].apply(
            lambda x: 'Loss' if x in ['Loss', 'No Result', 'Data Not Found'] else x
        )
        
        summary = backtest_results['Final_Outcome'].value_counts()
        total_trades = len(backtest_results)
        wins = summary.get('Win', 0)
        losses = total_trades - wins
        win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
        
        print("\n--- Final Summary ---")
        print(f"Total Trades: {total_trades}")
        print(f"Number of Wins: {wins}")
        print(f"Number of Losses: {losses}")
        print(f"Win Rate: {win_rate:.2f}%")

    except FileNotFoundError as e:
        print(f"\nFATAL: {e}")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")