# reporting.py

import pandas as pd
import smtplib
import os
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

import config

def create_excel_report(df, report_path):
    """
    Saves the DataFrame to an Excel file.

    Args:
        df (pandas.DataFrame): The DataFrame to save.
        report_path (str): The full path to save the Excel file.
    """
    try:
        # Create the directory if it doesn't exist
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        
        # Create a Pandas Excel writer using openpyxl as the engine.
        with pd.ExcelWriter(report_path, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Screening Report')
            
            # Get the openpyxl workbook and worksheet objects.
            workbook  = writer.book
            worksheet = writer.sheets['Screening Report']
            
            # Auto-adjust column widths
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = (max_length + 2)
                worksheet.column_dimensions[column_letter].width = adjusted_width

        logging.info(f"Successfully created Excel report at: {report_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to create Excel report: {e}")
        return False

def send_email_notification(report_path, report_df):
    """
    Sends an email notification with the report attached.

    Args:
        report_path (str): The path to the report file to be attached.
        report_df (pandas.DataFrame): The DataFrame with screened stocks for the email body.
    """
    email_conf = config.EMAIL_CONFIG
    
    try:
        msg = MIMEMultipart()
        msg['From'] = email_conf['SMTP_USER']
        msg['To'] = ", ".join(email_conf['RECIPIENT_EMAILS'])
        msg['Subject'] = f"Stock Screening Report: {datetime.now().strftime('%Y-%m-%d')}"

        # --- Email Body ---
        num_screened = 500 # This should ideally be passed from main.py
        num_passed = len(report_df)
        
        if not report_df.empty:
            top_performer = report_df.iloc[0]
            top_stock_info = f"Top theoretical trade: {top_performer['Stock Name']} with P/L of {top_performer['P/L (%)']:.2f}%"
        else:
            top_stock_info = "No stocks passed the screening criteria."

        body = f"""
        <html>
        <body>
            <h2>Daily Stock Screening Report</h2>
            <p>Date: {datetime.now().strftime('%Y-%m-%d')}</p>
            <p>Total stocks screened (NIFTY 500): {num_screened}</p>
            <p>Number of stocks passing all criteria: {num_passed}</p>
            <p>{top_stock_info}</p>
            <br>
            <p>Please find the detailed report attached.</p>
            <br>
            <p>Regards,</p>
            <p>Automated Stock Screener</p>
        </body>
        </html>
        """
        msg.attach(MIMEText(body, 'html'))

        # --- Attachment ---
        if os.path.exists(report_path):
            with open(report_path, "rb") as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f"attachment; filename= {os.path.basename(report_path)}",
            )
            msg.attach(part)
        else:
            logging.warning(f"Attachment not found at {report_path}. Sending email without it.")

        # --- Send Email ---
        with smtplib.SMTP(email_conf['SMTP_SERVER'], email_conf['SMTP_PORT']) as server:
            server.starttls()
            server.login(email_conf['SMTP_USER'], email_conf['SMTP_PASSWORD'])
            server.send_message(msg)
        
        logging.info("Successfully sent email notification.")
        return True

    except Exception as e:
        logging.error(f"Failed to send email notification: {e}")
        return False

if __name__ == '__main__':
    # Example Usage (requires a dummy config and data)
    class DummyConfig:
        REPORTS_DIR = "reports_test"
        EMAIL_CONFIG = {
            "SMTP_SERVER": "smtp.example.com", "SMTP_PORT": 587,
            "SMTP_USER": "test@example.com", "SMTP_PASSWORD": "password",
            "RECIPIENT_EMAILS": ["test@example.com"]
        }

    dummy_data = {
        'Date': ['2023-10-27'], 'Stock Name': ['TESTCORP'], 'Sector': ['IT'], 'Day': ['Friday'],
        'Entry Price': [100], 'Exit Price': [105], 'P/L (%)': [5.0], 'Volume': [100000],
        'Cfo/PAT': [1.2], 'PEG': [1.5], 'Cum. CFO': ['N/A'], 'Cum. PAT': ['N/A'], 'P/E': [20],
        'P/B': [3], 'EPS': [5], 'ROA': [0.12], 'ROE': [0.18], 'ROCE': ['N/A'], 'Debt/Equity': [0.5],
        'Promoter Holding (%)': [55], 'NPM': ['N/A'], 'Piotroski Score': [8], 'Asset Turnover': ['N/A'],
        '50DMA>200EMA': ['Yes'], 'FII/DII Trend': ['N/A'], 'MF Trend': ['N/A'], 'Price/Book': [3],
        'Forward P/E': [18], 'Trailing P/E': [20], 'Dividend Yield': [0.015], 'Technical Setup': ['N/A'],
        'Mistakes/Notes': ['N/A']
    }
    dummy_df = pd.DataFrame(dummy_data)
    
    report_filename = f"{datetime.now().strftime('%Y-%m-%d')}-report.xlsx"
    dummy_report_path = os.path.join(DummyConfig.REPORTS_DIR, report_filename)

    print("--- Testing Excel Report Creation ---")
    create_excel_report(dummy_df, dummy_report_path)

    print("\n--- Testing Email Notification (will fail without real SMTP server) ---")
    send_email_notification(DummyConfig, dummy_report_path, dummy_df)