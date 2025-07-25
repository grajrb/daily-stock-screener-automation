# main.py

import os
import logging
from datetime import datetime

# Import project modules
import config
from data_fetcher import get_nifty500_tickers, get_stock_data
from screener import run_screening
from reporting import create_excel_report, send_email_notification
from vcs_handler import push_to_github

# --- Logging Configuration ---
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"{datetime.now().strftime('%Y-%m-%d')}.log")

logging.basicConfig(
    level=logging.INFO if not config.DEBUG else logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

def update_readme_log(report_df):
    """Appends a log entry to the README.md file."""
    try:
        num_passed = len(report_df)
        if not report_df.empty:
            top_performer = report_df.iloc[0]
            summary_line = f"* **{datetime.now().strftime('%Y-%m-%d')}:** Screened 500 stocks, {num_passed} passed. Report generated. Top P/L: {top_performer['Stock Name']} ({top_performer['P/L (%)']:.2f}%)."
        else:
            summary_line = f"* **{datetime.now().strftime('%Y-%m-%d')}:** Screened 500 stocks, 0 passed. No report generated."

        with open('README.md', 'a') as f:
            f.write('\n' + summary_line)
        logging.info("Successfully updated README.md log.")
        return True
    except Exception as e:
        logging.error(f"Failed to update README.md: {e}")
        return False

def main():
    """
    Main function to orchestrate the stock screening workflow.
    """
    logging.info("--- Starting Daily Stock Screening Process ---")

    try:
        # 1. Get the list of tickers
        logging.info("Fetching NIFTY 500 ticker list...")
        tickers = get_nifty500_tickers(config.NIFTY_500_URL)
        if not tickers:
            logging.error("Could not fetch ticker list. Aborting.")
            return
        logging.info(f"Successfully fetched {len(tickers)} tickers.")

        # 2. Fetch stock data
        logging.info("Fetching stock data for all tickers...")
        raw_data_df = get_stock_data(tickers)
        if raw_data_df.empty:
            logging.error("Could not fetch stock data. Aborting.")
            return
        logging.info("Successfully fetched all stock data.")

        # 3. Run the screener
        logging.info("Running the screening process...")
        passed_stocks_df = run_screening(raw_data_df)

        # 4. Process results
        if not passed_stocks_df.empty:
            logging.info(f"{len(passed_stocks_df)} stocks passed the screening criteria.")
            
            # a. Create Excel report
            report_filename = f"{datetime.now().strftime('%Y-%m-%d')}-report.xlsx"
            report_path = os.path.join(config.REPORTS_DIR, report_filename)
            if create_excel_report(passed_stocks_df, report_path):
                
                # b. Send email notification
                send_email_notification(report_path, passed_stocks_df)

        else:
            logging.info("No stocks passed the screening criteria today.")

        # 5. Update README and push to Git regardless of whether stocks passed
        logging.info("Updating logs and pushing to version control...")
        update_readme_log(passed_stocks_df)
        push_to_github()

    except Exception as e:
        logging.critical(f"A critical error occurred in the main workflow: {e}", exc_info=True)
    
    finally:
        logging.info("--- Daily Stock Screening Process Finished ---")

if __name__ == '__main__':
    main()