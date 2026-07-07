#!/usr/bin/env python3
import os
import sys
import json
import time
import logging
import threading
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

import logic


API_BASE = "https://api.telegram.org/bot"


def _api(method: str, payload: dict | None = None) -> dict | None:
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return None
    url = f"{API_BASE}{token}/{method}"
    try:
        if payload:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data,
                                         headers={'Content-Type': 'application/json'})
        else:
            req = urllib.request.Request(url)

        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        logger.error("Telegram API error %s: %s", e.code, body)
        return None
    except Exception as e:
        logger.error("Telegram API error: %s", e)
        return None


class CryptoBot:
    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self._offset = 0
        self._pending_signal: str | None = None
        self._pending_msg_id: int | None = None
        self._started_ok = False

        if not self.token:
            logger.error("TELEGRAM_BOT_TOKEN is missing in .env")
            return
        if not self.chat_id:
            logger.error("TELEGRAM_CHAT_ID is missing in .env")
            return

        try:
            logic.get_executor()
            logger.info("Bybit connection OK")
        except Exception as e:
            logger.warning("Bybit init failed (bot will retry on demand): %s", e)

        self._started_ok = True
        logger.info("Bot initialized. Authorized chat: %s", self.chat_id)

    def _log(self, msg: str):
        logger.info("[Bot] %s", msg)

    def _send(self, chat_id: str, text: str,
              keyboard: list | None = None, parse_mode: str = 'Markdown') -> dict | None:
        payload = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode}
        if keyboard:
            payload['reply_markup'] = json.dumps({'inline_keyboard': keyboard})
        return _api('sendMessage', payload)

    def _edit(self, chat_id: str, msg_id: int, text: str,
              keyboard: list | None = None, parse_mode: str = 'Markdown') -> None:
        payload = {
            'chat_id': chat_id,
            'message_id': msg_id,
            'text': text,
            'parse_mode': parse_mode,
        }
        if keyboard is not None:
            payload['reply_markup'] = json.dumps({'inline_keyboard': keyboard})
        elif keyboard == []:
            payload['reply_markup'] = json.dumps({'inline_keyboard': []})
        _api('editMessageText', payload)

    def _answer(self, callback_id: str, text: str = '') -> None:
        _api('answerCallbackQuery', {'callback_query_id': callback_id, 'text': text})

    def _process_message(self, text: str, chat_id: str) -> None:
        self._log("Message from %s: %.60s", chat_id, text.replace('\n', ' '))

        if text.startswith('/'):
            self._handle_command(text, chat_id)
            return

        preview = logic.compute_preview(text)
        if preview is None:
            self._send(chat_id,
                       "⚠️ Couldn't parse that as a signal.\n\n"
                       "Send a signal in this format or use /help for commands.")
            return

        signal, preview_data, risk = preview
        msg = logic.format_preview(signal, preview_data)
        result = self._send(chat_id, msg, keyboard=[
            [{'text': '✅ Execute', 'callback_data': 'exec'},
             {'text': '❌ Cancel', 'callback_data': 'cancel'}]
        ])

        if result and result.get('ok'):
            self._pending_signal = text
            self._pending_msg_id = result['result']['message_id']
            self._log("Preview sent, waiting for confirmation")

    def _handle_command(self, text: str, chat_id: str) -> None:
        cmd = text.split()[0].lower()

        if cmd == '/positions':
            self._log("Fetching positions")
            try:
                pos_text, keyboard = logic.format_positions()
                self._send(chat_id, pos_text, keyboard=keyboard or None)
            except Exception as e:
                self._send(chat_id, f"❌ Error fetching positions: {e}")
                logger.exception("Positions error")

        elif cmd == '/history':
            self._log("Fetching history")
            try:
                hist = logic.format_history()
                self._send(chat_id, hist)
            except Exception as e:
                self._send(chat_id, f"❌ Error: {e}")

        elif cmd == '/watch':
            trades = __import__('trades_logger', fromlist=['get_active_trades']).get_active_trades()
            if not trades:
                self._send(chat_id, "No active trades to watch.")
                return
            latest = trades[-1]
            trade_id = latest['id']
            sym = latest['symbol']
            self._log("Starting watch for %s (%s)", sym, trade_id)

            t = threading.Thread(
                target=logic.watch_worker,
                args=(self.token, chat_id, trade_id),
                daemon=True,
            )
            t.start()
            self._send(chat_id, f"👀 Watching {sym} in background...")

        elif cmd == '/cancel':
            if self._pending_signal:
                self._pending_signal = None
                if self._pending_msg_id:
                    self._edit(chat_id, self._pending_msg_id, "❌ Cancelled.")
                    self._pending_msg_id = None
                else:
                    self._send(chat_id, "❌ Cancelled.")
            else:
                self._send(chat_id, "Nothing to cancel.")

        elif cmd == '/start' or cmd == '/help':
            self._send(chat_id,
                       "🤖 *CryptoBot*\n\n"
                       "Send me a trading signal and I'll preview it for you.\n\n"
                       "*Commands:*\n"
                       "  Send any signal text → preview with Execute/Cancel\n"
                       "  /positions — view open positions\n"
                       "  /history — view trade history\n"
                       "  /watch — auto-move SL to entry after TP1\n"
                       "  /cancel — cancel pending trade\n"
                       "  /help — this message")

        else:
            self._send(chat_id, f"Unknown command: {cmd}\nUse /help for available commands.")

    def _process_callback(self, callback_id: str, data: str,
                          chat_id: str, msg_id: int) -> None:
        self._log("Callback: %s", data)

        if data == 'exec':
            if not self._pending_signal:
                self._answer(callback_id, "No pending trade")
                self._edit(chat_id, msg_id, "⚠️ No pending trade to execute.")
                return

            self._answer(callback_id, "Executing...")
            self._edit(chat_id, msg_id, "⏳ Executing trade...", keyboard=[])
            text = self._pending_signal
            self._pending_signal = None
            self._pending_msg_id = None

            try:
                signal, result, trade_id = logic.execute_trade(text)
                msg = logic.format_execution_result(signal, result, trade_id)
                self._edit(chat_id, msg_id, msg)
                self._log("Trade executed: %s %s", signal.symbol, signal.direction)
            except Exception as e:
                self._edit(chat_id, msg_id, f"❌ Trade failed: {e}")
                logger.exception("Execute error")

        elif data == 'cancel':
            self._answer(callback_id, "Cancelled")
            self._pending_signal = None
            self._pending_msg_id = None
            self._edit(chat_id, msg_id, "❌ Trade cancelled.")

        elif data.startswith('sl:'):
            base = data.split(':', 1)[1]
            self._answer(callback_id, f"Moving SL for {base}...")
            try:
                msg = logic.move_sl_to_entry(base)
                self._edit(chat_id, msg_id, msg, keyboard=[])
                self._log("SL moved: %s", base)
            except Exception as e:
                self._edit(chat_id, msg_id, f"❌ {e}")
                logger.exception("Move SL error")

    def run(self):
        if not self._started_ok:
            logger.error("Bot failed to start. Check your .env config.")
            sys.exit(1)

        logger.info("Bot polling started")
        while True:
            try:
                params = f"offset={self._offset}&timeout=10&allowed_updates=%5B%22message%22%2C%22callback_query%22%5D"
                url = f"{API_BASE}{self.token}/getUpdates?{params}"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read())

                for update in data.get('result', []):
                    self._offset = update['update_id'] + 1

                    if 'message' in update:
                        msg = update['message']
                        chat_id = str(msg['chat']['id'])
                        if chat_id != self.chat_id:
                            continue
                        text = msg.get('text', '')
                        if text:
                            self._process_message(text, chat_id)

                    elif 'callback_query' in update:
                        cq = update['callback_query']
                        cq_id = cq['id']
                        data = cq.get('data', '')
                        chat_id = str(cq['message']['chat']['id'])
                        msg_id = cq['message']['message_id']
                        if chat_id != self.chat_id:
                            continue
                        self._process_callback(cq_id, data, chat_id, msg_id)

            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.warning("Poll error (retrying): %s", e)
                time.sleep(5)

        logger.info("Bot exited")


def main():
    bot = CryptoBot()
    bot.run()


if __name__ == '__main__':
    main()
