"""
FOREX SIGNALS - PAPER MODE ONLY
- Watches major forex pairs using Twelve Data candle data.
- Sends signal and result notifications to Telegram and Gmail.
- Tracks a simple virtual $500 balance (+$5 for a simulated win, -$5 for a simulated loss).
- Does NOT place trades or connect to a broker.

Before running:
  1) Install Python 3.10+.
  2) Set environment variables:
       TWELVE_DATA_API_KEY
       TELEGRAM_BOT_TOKEN
       TELEGRAM_CHAT_ID
       TRADING_EMAIL
       TRADING_EMAIL_APP_PASSWORD
  3) Keep this script in paper mode. Do not add broker execution.

Twelve Data API limits depend on your plan. Seven pairs queried once per minute
may exceed some free-plan limits. If you get rate-limit errors, reduce PAIRS.
"""

import json
import os
import smtplib
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

# -------------------- SETTINGS --------------------

EMAIL_TO = "olivermakdisi12@gmail.com"

TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

EMAIL_FROM = os.getenv("TRADING_EMAIL", "")
EMAIL_PASSWORD = os.getenv("TRADING_EMAIL_APP_PASSWORD", "")

# Major forex pairs (not cryptocurrencies)
PAIRS = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "AUD/USD",
    "USD/CAD",
    "NZD/USD",
]

INTERVAL = "1min"
CANDLE_COUNT = 60
SCAN_EVERY_SECONDS = 60
TRADE_DURATION_MINUTES = 2

START_BALANCE = 500.00
SIMULATED_RESULT_AMOUNT = 5.00  # demo bookkeeping only; not a real trading P&L
MIN_SAMPLES = 5

# -------------------- HTTP / NOTIFICATIONS --------------------

def http_json(url, payload=None):
    data = None
    headers = {"User-Agent": "ForexPaperSignals/1.0"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram settings missing; message was not sent to Telegram.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    http_json(url, {"chat_id": TELEGRAM_CHAT_ID, "text": message})


def send_email(message):
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("Email settings missing; message was not sent by email.")
        return

    msg = EmailMessage()
    msg["Subject"] = "Forex Paper Trading Alert"
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.set_content(message)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.send_message(msg)


def notify(message):
    print("\n" + message + "\n")
    try:
        send_telegram(message)
    except Exception as exc:
        print(f"Telegram error: {exc}")

    try:
        send_email(message)
    except Exception as exc:
        print(f"Email error: {exc}")


# -------------------- MARKET DATA --------------------

def get_candles(pair):
    if not TWELVE_DATA_API_KEY:
        raise RuntimeError("Missing TWELVE_DATA_API_KEY environment variable.")

    params = urllib.parse.urlencode({
        "symbol": pair,
        "interval": INTERVAL,
        "outputsize": CANDLE_COUNT,
        "apikey": TWELVE_DATA_API_KEY,
        "format": "JSON",
        "timezone": "UTC",
    })
    url = "https://api.twelvedata.com/time_series?" + params
    data = http_json(url)

    if "values" not in data:
        message = data.get("message") or data.get("status") or str(data)
        raise RuntimeError(f"Twelve Data response for {pair}: {message}")

    # API returns newest first; use chronological order.
    values = list(reversed(data["values"]))
    return [
        {
            "datetime": item["datetime"],
            "close": float(item["close"]),
        }
        for item in values
    ]


# -------------------- INDICATORS / SIGNALS --------------------

def ema(values, period):
    if len(values) < period:
        raise ValueError("Not enough values for EMA.")
    multiplier = 2.0 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = value * multiplier + result * (1.0 - multiplier)
    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        raise ValueError("Not enough values for RSI.")

    gains = 0.0
    losses = 0.0
    recent = values[-(period + 1):]

    for index in range(1, len(recent)):
        change = recent[index] - recent[index - 1]
        if change > 0:
            gains += change
        else:
            losses -= change

    average_gain = gains / period
    average_loss = losses / period

    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def analyze(pair):
    candles = get_candles(pair)
    closes = [candle["close"] for candle in candles]

    # Exclude the newest candle because it may still be forming.
    closed_closes = closes[:-1]
    if len(closed_closes) < 22:
        return None

    fast_ema = ema(closed_closes[-30:], 9)
    slow_ema = ema(closed_closes[-30:], 21)
    current_rsi = rsi(closed_closes, 14)

    if fast_ema > slow_ema and 50 < current_rsi < 70:
        direction = "BUY"
        reason = f"EMA9 above EMA21; RSI {current_rsi:.1f}"
    elif fast_ema < slow_ema and 30 < current_rsi < 50:
        direction = "SELL"
        reason = f"EMA9 below EMA21; RSI {current_rsi:.1f}"
    else:
        return None

    return {
        "pair": pair,
        "direction": direction,
        "entry": closed_closes[-1],
        "reason": reason,
    }


# -------------------- PAPER RESULTS --------------------

def main():
    if not TWELVE_DATA_API_KEY:
        raise SystemExit(
            "Set TWELVE_DATA_API_KEY before running. "
            "Get an API key from Twelve Data."
        )

    virtual_balance = START_BALANCE
    stats = {}
    history = []
    signal_number = 1
    active_trade = None

    print("Forex paper-signal script started.")
    print(f"Virtual starting balance: ${virtual_balance:.2f}")
    print("No real orders will be placed.")

    notify(
        "FOREX PAPER SIGNALS STARTED\n"
        f"Virtual starting balance: ${virtual_balance:.2f}\n"
        "Pairs: " + ", ".join(PAIRS) + "\n"
        "Mode: PAPER ONLY - no real trades"
    )

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Check whether the simulated signal duration has ended.
            if active_trade and now >= active_trade["close_time"]:
                candles = get_candles(active_trade["pair"])
                closing_price = candles[-2]["close"]
                is_buy = active_trade["direction"] == "BUY"

                if closing_price == active_trade["entry"]:
                    result = "DRAW"
                elif (closing_price > active_trade["entry"]) == is_buy:
                    result = "WIN"
                else:
                    result = "LOSS"

                key = active_trade["pair"] + "|" + active_trade["direction"]
                if key not in stats:
                    stats[key] = {"wins": 0, "trades": 0}

                if result != "DRAW":
                    stats[key]["trades"] += 1
                    if result == "WIN":
                        stats[key]["wins"] += 1
                        virtual_balance += SIMULATED_RESULT_AMOUNT
                    else:
                        virtual_balance -= SIMULATED_RESULT_AMOUNT

                history.append(result)
                history = history[-30:]

                wins = history.count("WIN")
                losses = history.count("LOSS")
                draws = history.count("DRAW")

                report = (
                    f"FOREX REPORT #{active_trade['number']}\n"
                    f"Pair: {active_trade['pair']}\n"
                    f"Direction: {active_trade['direction']}\n"
                    f"Entry: {active_trade['entry']}\n"
                    f"Close: {closing_price}\n"
                    f"Result: {result}\n"
                    f"Virtual balance: ${virtual_balance:.2f}\n"
                    f"Last {len(history)} results: "
                    f"{wins} WIN / {losses} LOSS / {draws} DRAW\n"
                    "Demo accounting only; not actual broker profit/loss."
                )
                notify(report)
                active_trade = None

            # Scan once per UTC minute, near the end of the minute.
            if now.second >= 50 and active_trade is None:
                best_signal = None

                for pair in PAIRS:
                    try:
                        candidate = analyze(pair)
                    except Exception as exc:
                        print(f"Skipping {pair}: {exc}")
                        continue

                    if candidate:
                        pair_key = candidate["pair"] + "|" + candidate["direction"]
                        record = stats.get(pair_key)
                        if record and record["trades"] >= MIN_SAMPLES:
                            score = record["wins"] / record["trades"]
                        else:
                            score = 0.5

                        if best_signal is None or score > best_signal["score"]:
                            best_signal = {**candidate, "score": score}

                    # Small pause to reduce API burst rate.
                    time.sleep(1)

                if best_signal:
                    close_time = now.replace(second=0, microsecond=0) + timedelta(
                        minutes=TRADE_DURATION_MINUTES
                    )
                    active_trade = {
                        "number": signal_number,
                        "pair": best_signal["pair"],
                        "direction": best_signal["direction"],
                        "entry": best_signal["entry"],
                        "close_time": close_time,
                    }

                    message = (
                        f"FOREX SIGNAL #{signal_number}\n"
                        f"Pair: {best_signal['pair']}\n"
                        f"Action: {best_signal['direction']}\n"
                        f"Entry reference: {best_signal['entry']}\n"
                        f"Reason: {best_signal['reason']}\n"
                        f"Virtual balance: ${virtual_balance:.2f}\n"
                        f"Simulated check: {close_time.strftime('%H:%M:%S UTC')}\n"
                        "PAPER ONLY - not a live trade. Not financial advice."
                    )
                    notify(message)
                    signal_number += 1
                else:
                    print(f"{now:%Y-%m-%d %H:%M:%S} UTC - no signal")

                # Avoid scanning repeatedly during the same minute.
                time.sleep(max(1, 60 - datetime.now(timezone.utc).second))

            time.sleep(1)

        except KeyboardInterrupt:
            print("Stopped by user.")
            break
        except Exception as exc:
            print(f"Main loop error: {exc}")
            time.sleep(10)


if __name__ == "__main__":
    main()
