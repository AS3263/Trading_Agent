# AI Trading Signal Agent

An AI-powered trading analysis system built with Python that combines market data, technical indicators, voting-based signal generation, news sentiment analysis, and a web dashboard.

## Overview

This project analyses multiple financial assets and generates trading signals using a multi-indicator voting system.

The system currently supports:

- Bitcoin (BTC/USD)
- Ethereum (ETH/USD)
- Gold (XAU/USD)
- EUR/USD
- GBP/USD
- S&P 500 (SPX)

The core agent uses 20 technical indicators organised into multiple analysis categories. A signal is generated when the configured minimum number of indicators agree.

## Features

### 1. 20-Indicator Signal Engine

The main trading agent combines multiple technical indicators and uses a voting mechanism to determine whether an asset produces a BUY, SELL, or WAIT signal.

The default minimum threshold is 6 votes.

### 2. Market Data

The application retrieves market information through external APIs, including:

- CoinGecko for cryptocurrency data
- Alpha Vantage for financial market data
- News API for financial news

API credentials are loaded from environment variables rather than being stored directly in the source code.

### 3. AI News Sentiment Analysis

Financial news headlines are collected and analysed to provide additional sentiment information alongside the technical-indicator signals.

### 4. Trade-Level Calculations

The system calculates:

- Entry levels
- Stop-loss levels
- Target levels
- Risk/reward information
- Position sizing
- Signal confidence

### 5. Web Dashboard

A Flask-based dashboard provides a browser interface for viewing the latest analysis.

The dashboard includes:

- Live market signals
- Trade analysis table
- Indicator information
- Sentiment information
- Timeframe information
- Account and risk information
- Force-rescan functionality

### 6. Automated Scheduler

`scheduler.py` can automatically run the trading analysis at regular intervals.

The current scheduler configuration runs a scan every 60 minutes.

## Project Structure

```text
Trading_Agent/
│
├── agent.py
├── Dashboard.py
├── scheduler.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
