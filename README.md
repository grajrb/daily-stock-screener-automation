# Daily Stock Screener Automation

A Python-based automated stock screening system that runs daily scans to identify trading opportunities based on predefined criteria. This system generates comprehensive reports and maintains historical tracking for performance analysis.

## Overview

This automation tool performs daily analysis of stock markets to identify potential trading opportunities. The screener applies technical indicators, fundamental metrics, and custom filters to highlight stocks that meet specific criteria for further analysis.

## What the Screener Does

### Core Functionality

- **Daily Market Scans**: Automatically scans entire stock universe based on configured parameters
- **Technical Analysis**: Applies moving averages, RSI, MACD, volume analysis, and other technical indicators
- **Fundamental Screening**: Filters stocks based on P/E ratios, market cap, revenue growth, and financial health metrics
- **Pattern Recognition**: Identifies chart patterns like breakouts, reversals, and consolidations
- **Sector Analysis**: Provides sector-wise performance comparison and rotation insights
- **Risk Assessment**: Calculates volatility metrics and risk-adjusted returns

### Output Reports

- **Daily Screening Results**: Top stock picks with detailed analysis
- **Performance Tracking**: Historical performance of previous recommendations
- **Market Summary**: Overall market sentiment and sector performance
- **Watchlist Management**: Maintains and updates dynamic watchlists
- **Alert System**: Sends notifications for urgent market movements or opportunities

## Key Features

- ✅ **Automated Daily Execution**: Runs automatically during market hours
- ✅ **Multi-timeframe Analysis**: Analyzes stocks across different time horizons
- ✅ **Customizable Filters**: Easy-to-modify screening criteria
- ✅ **Excel Report Generation**: Professional formatted reports for easy analysis
- ✅ **Historical Data Integration**: Maintains comprehensive historical database
- ✅ **Risk Management**: Built-in position sizing and risk assessment
- ✅ **Backtesting Capabilities**: Tests strategies against historical data
- ✅ **Real-time Alerts**: Immediate notifications for time-sensitive opportunities

## Project Structure

### Core Files

- `screener.py` - Main screening engine and automation logic
- `report-template.xlsx` - Excel template for generating formatted reports
- `config.json` - Configuration file for screening parameters
- `requirements.txt` - Python dependencies

### Planned Components

- Data fetching modules for multiple sources (Yahoo Finance, Alpha Vantage, etc.)
- Technical indicator calculation libraries
- Report generation and formatting utilities
- Database management for historical data
- Notification system (email, SMS, webhooks)
- Web dashboard for monitoring and configuration

## Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/grajrb/daily-stock-screener-automation.git
   cd daily-stock-screener-automation
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure API keys**
   - Update `config.json` with your data provider API keys
   - Set up notification credentials (email, SMS services)

4. **Run the screener**
   ```bash
   python screener.py
   ```

## Configuration

The screener behavior can be customized through the configuration file:

- **Market Data Sources**: Choose between different data providers
- **Screening Criteria**: Set custom technical and fundamental filters
- **Report Settings**: Customize output format and delivery methods
- **Scheduling**: Configure automation timing and frequency
- **Risk Parameters**: Set position sizing and risk management rules

## Stock & Finance Research Data Sources

This screener can leverage comprehensive data sources grouped under 'stock & finance research' tabs to enhance screening accuracy and provide deeper market insights. These data sources are designed to work seamlessly with both manual analysis and automated screening processes.

### Available Data Types

The stock & finance research data sources provide four key categories of information:

- **News & Market Updates**: Real-time financial news, earnings announcements, and market-moving events that can impact stock prices and screening results
- **Fundamental Data**: Comprehensive financial statements, ratios, earnings history, and company metrics essential for fundamental analysis screening
- **Professional Analysis**: Research reports, analyst ratings, price targets, and institutional recommendations to supplement automated screening criteria
- **Crowd-Sourced Opinions**: Community sentiment, social media trends, and retail investor discussions that provide alternative perspectives on market sentiment

### Integration Benefits

Incorporating these diverse data sources into your daily stock screening automation provides several advantages:

- **Enhanced Signal Quality**: Combining technical indicators with fundamental data and market sentiment creates more robust screening signals
- **Risk Mitigation**: News alerts and analyst warnings can help filter out stocks with pending negative catalysts
- **Opportunity Discovery**: Community insights and social sentiment can identify emerging trends before they appear in traditional metrics
- **Validation Layer**: Professional analysis serves as a validation mechanism for automated screening results

### Usage for Users and Automation

These data sources are structured to support both manual research workflows and automated integration:

- **Manual Users**: Access organized tabs containing categorized information for efficient research and due diligence
- **Automation Systems**: Structured data feeds enable programmatic access for real-time screening enhancement and alert generation
- **Hybrid Workflows**: Automated screening can flag opportunities while manual review of research data provides final validation

*Note: When implementing these data sources, ensure proper API rate limiting and data usage compliance with provider terms of service.*

## Sample Screening Criteria

- Market cap > $100M
- Average daily volume > 500K shares
- RSI between 30-70 (avoiding overbought/oversold extremes)
- Price above 20-day moving average
- Recent earnings growth > 15%
- Debt-to-equity ratio < 0.5
- Insider buying activity in last 3 months

## Output Example

Daily reports include:

- Top 10 stock recommendations with confidence scores
- Sector performance rankings
- Market volatility index
- Economic calendar highlights
- Risk-adjusted portfolio suggestions

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for:

- New screening criteria
- Additional technical indicators
- Enhanced reporting features
- Performance optimizations
- Bug fixes and improvements

## Disclaimer

This tool is for educational and informational purposes only. Stock market investments carry inherent risks, and past performance does not guarantee future results. Always conduct your own research and consider consulting with financial advisors before making investment decisions.

## License

MIT License - see LICENSE file for details.

## Contact

For questions or support, please open an issue or contact [gauravupadhavay9801@gmail.com](mailto:gauravupadhavay9801@gmail.com)
