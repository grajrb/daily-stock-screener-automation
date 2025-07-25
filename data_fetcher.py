# data_fetcher.py

import pandas as pd
import yfinance as yf
import requests
import io
import logging
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_nifty500_tickers(url):
    """
    Fetches the list of NIFTY 500 tickers from the NSE website.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        return [f"{symbol}.NS" for symbol in df['Symbol']]
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching NIFTY 500 list: {e}")
        return []

def get_stock_data(tickers):
    """
    Fetches EOD and fundamental data for a list of stock tickers.

    Args:
        tickers (list): A list of NSE stock tickers (e.g., ['RELIANCE.NS', 'TCS.NS']).

    Returns:
        pandas.DataFrame: A DataFrame containing the fetched data for all tickers.
                          Returns an empty DataFrame if fetching fails.
    """
    if not tickers:
        logging.warning("Ticker list is empty. No data to fetch.")
        return pd.DataFrame()

    try:
        # Fetching data for the last year to calculate moving averages
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * 2) # 2 years to have enough data for 200-day EMA

        logging.info(f"Fetching data for {len(tickers)} tickers from {start_date.date()} to {end_date.date()}...")

        # Download historical data
        data = yf.download(tickers, start=start_date, end=end_date, group_by='ticker')

        if data.empty:
            logging.warning("No data downloaded from yfinance.")
            return pd.DataFrame()

        all_stocks_df = pd.DataFrame()

        for ticker in tickers:
            try:
                stock_data = data[ticker]
                if stock_data.empty:
                    logging.warning(f"No data for ticker: {ticker}")
                    continue

                stock_info = yf.Ticker(ticker).info
                
                # Create a dataframe from the info dictionary
                info_df = pd.DataFrame([stock_info])

                # Select only the required columns from info_df
                required_cols = [
                    'sector', 'longName', 'trailingPE', 'priceToBook', 'returnOnEquity',
                    'returnOnAssets', 'debtToEquity', 'promoterHolding', 'pegRatio',
                    'forwardPE', 'trailingEps', 'dividendYield'
                ]
                
                # Use a dictionary to rename columns for clarity
                rename_map = {
                    'longName': 'Stock Name',
                    'sector': 'Sector',
                    'trailingPE': 'P/E',
                    'priceToBook': 'P/B',
                    'returnOnEquity': 'ROE',
                    'returnOnAssets': 'ROA',
                    'debtToEquity': 'Debt/Equity',
                    'promoterHolding': 'Promoter Holding (%)',
                    'pegRatio': 'PEG',
                    'forwardPE': 'Forward P/E',
                    'trailingEps': 'EPS',
                    'dividendYield': 'Dividend Yield'
                }

                # Filter and rename available columns
                info_subset = {}
                for col in required_cols:
                    if col in info_df.columns:
                        info_subset[rename_map.get(col, col)] = info_df[col].iloc[0]
                    else:
                        info_subset[rename_map.get(col, col)] = 'N/A'


                # Combine with historical data
                for col, val in info_subset.items():
                    stock_data[col] = val
                
                stock_data['Ticker'] = ticker
                all_stocks_df = pd.concat([all_stocks_df, stock_data])

            except Exception as e:
                logging.error(f"Could not process data for {ticker}: {e}")
                continue
        
        logging.info("Successfully fetched and processed data for all available tickers.")
        return all_stocks_df.reset_index()

    except Exception as e:
        logging.error(f"An error occurred during data fetching: {e}")
        return pd.DataFrame()

if __name__ == '__main__':
    # Example usage:
    from config import NIFTY_500_URL
    nifty_500_tickers = get_nifty500_tickers(NIFTY_500_URL)
    if nifty_500_tickers:
        # Fetch for a small subset for testing
        stock_data_df = get_stock_data(nifty_500_tickers[:10])
        if not stock_data_df.empty:
            print(stock_data_df.head())
            print("\nColumns:")
            print(stock_data_df.columns)