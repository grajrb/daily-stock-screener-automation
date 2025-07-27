# screener.py

import pandas as pd
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

import config

def calculate_indicators(df):
    """
    Calculates technical indicators required for screening.
    """
    df['50_DMA'] = df.groupby('Ticker')['Close'].transform(lambda x: x.rolling(window=config.TECHNICAL_FILTERS['DMA_SHORT_TERM']).mean())
    df['200_EMA'] = df.groupby('Ticker')['Close'].transform(lambda x: x.ewm(span=config.TECHNICAL_FILTERS['EMA_LONG_TERM'], adjust=False).mean())
    return df

def get_piotroski_score(info):
    """
    Calculates Piotroski F-Score. This is a placeholder as yfinance does not provide all required data points directly.
    We will simulate this by returning a score for demonstration.
    A real implementation would need a more advanced data provider for metrics like net income, ROA, etc., for previous periods.
    """
    # In a real scenario, you would fetch financial statements and calculate this.
    # For now, we'll return a default value that can be configured or randomized for testing.
    return info.get('piotroskiFScore', 7) # yfinance sometimes provides this

def get_cfo_pat_ratio(info):
    """
    Placeholder for CFO/PAT ratio.
    """
    # yfinance free tier does not provide this reliably.
    # Returning a default value for demonstration.
    return 1.0

def run_screening(df):
    """
    Runs the screening process on the given DataFrame.

    Args:
        df (pandas.DataFrame): The raw data DataFrame from the data_fetcher.

    Returns:
        pandas.DataFrame: A new DataFrame with stocks that passed the screening.
    """
    if df.empty:
        logging.warning("Input DataFrame is empty. Skipping screening.")
        return pd.DataFrame()

    logging.info("Starting stock screening process...")

    # Calculate indicators first
    df = calculate_indicators(df)

    # Get the latest data for each stock and create a copy to avoid SettingWithCopyWarning
    latest_df = df.loc[df.groupby('Ticker')['Date'].idxmax()].copy()

    # --- Apply Filters ---
    f_filters = config.FUNDAMENTAL_FILTERS
    
    # Add placeholder columns before filtering
    latest_df['Piotroski Score'] = latest_df.apply(get_piotroski_score, axis=1)
    latest_df['Cfo/PAT'] = latest_df.apply(get_cfo_pat_ratio, axis=1)

    # Coerce columns to numeric, turning non-numeric values into NaN
    numeric_cols = ['P/E', 'P/B', 'ROE', 'Debt/Equity', 'Promoter Holding (%)', 'Piotroski Score', 'Cfo/PAT']
    for col in numeric_cols:
        latest_df[col] = pd.to_numeric(latest_df[col], errors='coerce')

    # Build a combined boolean mask for all filters
    # Using .fillna() to handle missing data gracefully during comparison
    mask = (
        (latest_df['Close'] > latest_df['Open']) &
        (latest_df['P/E'].fillna(999) <= f_filters['PE_RATIO_MAX']) &
        (latest_df['P/B'].fillna(0).between(f_filters['PB_RATIO_MIN'], f_filters['PB_RATIO_MAX'])) &
        (latest_df['ROE'].fillna(0) * 100 >= f_filters['ROE_MIN']) &
        (latest_df['Debt/Equity'].fillna(999) <= f_filters['DEBT_TO_EQUITY_MAX']) &
        (latest_df['Promoter Holding (%)'].fillna(0) >= f_filters['PROMOTER_HOLDING_MIN']) &
        (latest_df['Piotroski Score'].fillna(0) >= f_filters['PIOTROSKI_SCORE_MIN']) &
        (latest_df['Cfo/PAT'].fillna(0) >= f_filters['CFO_PAT_RATIO_MIN']) &
        (latest_df['50_DMA'] > latest_df['200_EMA'])
    )

    passing_stocks = latest_df[mask].copy()
    logging.info(f"{len(passing_stocks)} stocks passed all screening criteria.")
    
    passing_stocks['50DMA>200EMA'] = 'Yes'

    if passing_stocks.empty:
        logging.info("No stocks passed all screening criteria.")
        return pd.DataFrame()

    # --- Paper Trading Simulation ---
    passing_stocks['P/L (%)'] = ((passing_stocks['Close'] - passing_stocks['Open']) / passing_stocks['Open']) * 100
    passing_stocks['Entry Price'] = passing_stocks['Open']
    passing_stocks['Exit Price'] = passing_stocks['Close']

    # --- Format final report ---
    passing_stocks['Date'] = passing_stocks['Date'].dt.strftime('%Y-%m-%d')
    passing_stocks['Day'] = passing_stocks['Date'].apply(lambda x: datetime.strptime(x, '%Y-%m-%d').strftime('%A'))

    # Add placeholder columns
    placeholder_cols = ['Cum. CFO', 'Cum. PAT', 'NPM', 'Asset Turnover', 'FII/DII Trend', 'MF Trend', 'Price/Book', 'Technical Setup', 'Mistakes/Notes']
    for col in placeholder_cols:
        passing_stocks[col] = 'N/A'
    
    # Rename for consistency in report
    passing_stocks.rename(columns={'trailingEps': 'EPS', 'forwardPE': 'Forward P/E', 'trailingPE': 'Trailing P/E', 'priceToBook': 'P/B'}, inplace=True)

    # Ensure all required columns are present
    report_columns = [
        'Date', 'Stock Name', 'Sector', 'Day', 'Entry Price', 'Exit Price', 'P/L (%)', 'Volume', 'Cfo/PAT', 'PEG', 'Cum. CFO', 'Cum. PAT',
        'P/E', 'P/B', 'EPS', 'ROA', 'ROE', 'ROCE', 'Debt/Equity', 'Promoter Holding (%)', 'NPM', 'Piotroski Score', 'Asset Turnover',
        '50DMA>200EMA', 'FII/DII Trend', 'MF Trend', 'Price/Book', 'Forward P/E', 'Trailing P/E', 'Dividend Yield', 'Technical Setup', 'Mistakes/Notes'
    ]
    
    # Add missing columns with N/A
    for col in report_columns:
        if col not in passing_stocks.columns:
            passing_stocks[col] = 'N/A'

    final_report = passing_stocks[report_columns]
    
    logging.info(f"Screening complete. {len(final_report)} stocks passed all criteria.")
    
    return final_report.sort_values(by='P/L (%)', ascending=False)

if __name__ == '__main__':
    # Example usage:
    # This requires a sample data file to run standalone.
    # You would typically run this from main.py after fetching data.
    print("Screener module can be tested by running main.py")