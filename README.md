# Automated Daily Stock Screener for NSE

This project is a fully automated Python application that performs daily stock screening for the Indian stock market (NSE), specifically targeting the NIFTY 500 index. It fetches end-of-day data, applies a rigorous set of fundamental and technical filters, simulates paper trades, and generates a daily report.

## Features

- **Automated Daily Execution:** Designed to be run on a schedule (e.g., via cron or Task Scheduler).
- **NIFTY 500 Universe:** Screens all stocks in the NIFTY 500 index.
- **Multi-faceted Screening:** Applies a combination of performance, fundamental, and technical analysis criteria.
- **Paper Trading Simulation:** Calculates theoretical P/L for stocks that pass the screening.
- **Comprehensive Reporting:** Generates a detailed Excel report for passed stocks.
- **Email Notifications:** Sends a summary email with the report attached.
- **Automated Version Control:** Commits and pushes the daily report and log updates to a Git repository.

## Project Structure

```
/daily-stock-screener-automation/
├── main.py                 # Main orchestrator script
├── config.py               # All user-configurable parameters and secrets
├── data_fetcher.py         # Module for fetching all required stock data
├── screener.py             # Module containing the screening logic
├── reporting.py            # Module for generating Excel reports and email
├── vcs_handler.py          # Module for handling Git operations
├── requirements.txt        # List of all necessary Python libraries
├── .gitignore              # Standard gitignore for a Python project
└── README.md               # Project documentation and improvement log
```

## Setup Instructions

1.  **Clone the repository:**
    ```bash
    git clone <your-repository-url>
    cd daily-stock-screener-automation
    ```

2.  **Create a virtual environment and install dependencies:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

3.  **Configure the application:**
    *   Open the `config.py` file.
    *   Fill in your details for the `EMAIL_CONFIG` (SMTP server, credentials, recipients).
    *   Verify the `VCS_CONFIG` if you are using a different remote or branch name.
    *   Adjust the `FUNDAMENTAL_FILTERS` and `TECHNICAL_FILTERS` thresholds if desired.

## Usage

To run the application manually, execute the `main.py` script from the root of the project directory:

```bash
python main.py
```

The script will perform the entire workflow: fetch data, screen stocks, generate a report, send an email, and push the results to your Git repository.

## Scheduling the Screener

### On Linux/macOS (using cron)

1.  Open your crontab file for editing:
    ```bash
    crontab -e
    ```

2.  Add a new line to schedule the script. For example, to run it every day at 8 PM:
    ```cron
    0 20 * * * /path/to/your/project/venv/bin/python /path/to/your/project/main.py >> /path/to/your/project/cron.log 2>&1
    ```
    *Make sure to use the absolute paths to your virtual environment's Python interpreter and the `main.py` script.*

### On Windows (using Task Scheduler)

1.  Open Task Scheduler.
2.  Click "Create Basic Task...".
3.  Give the task a name (e.g., "Daily Stock Screener").
4.  Set the "Trigger" to "Daily" and choose a time (e.g., 8:00 PM).
5.  Set the "Action" to "Start a program".
6.  For "Program/script", browse to the Python executable inside your virtual environment (e.g., `C:\path\to\your\project\venv\Scripts\python.exe`).
7.  In the "Add arguments (optional)" field, enter `main.py`.
8.  In the "Start in (optional)" field, enter the full path to your project directory (e.g., `C:\path\to\your\project`).
9.  Finish the wizard.

---

## Improvement & Performance Log

*This section is automatically updated by the script on each successful run.*

* **2025-07-27:** Screened 500 stocks, 0 passed. No report generated.