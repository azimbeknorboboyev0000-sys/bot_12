"""Kino kodi orqali ishlaydigan Telegram bot. Python 3.10+."""
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

from management import ManagementMixin
from series import SeriesMixin


ROOT = Path(__file__).resolve().parent


def load_config():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())
    token = os.environ.get('BOT_TOKEN', '')
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token):
        raise SystemExit('.env fayliga BotFather tokenini kiriting.')
    raw = os.environ.get('ADMIN_IDS', '')
    if raw and not all(value.strip().isdigit() for value in raw.split(',')):
        raise SystemExit('ADMIN_IDS faqat raqamli Telegram IDlardan iborat bo‘lsin.')
    channel = os.environ.get('CHANNEL_ID', '').strip()
    if channel and not re.fullmatch(r'-[0-9]+', channel):
        raise SystemExit('CHANNEL_ID manfiy raqam bo‘lsin. Masalan: -1001234567890')
    return token, {int(value.strip()) for value in raw.split(',') if value.strip()}, int(channel) if channel else None


class APIError(Exception):
    def __init__(self, code, retry_after=0):
        super().__init__(f'Telegram API xatosi: {code}')
        self.code = code
        self.retry_after = retry_after


class TelegramBot:
    def __init__(self, token, admins, database, channel_id=None):
        self.token = token
        self.admins = admins
        self.channel_id = channel_id
        self.db = sqlite3.connect(database, timeout=5)
        self.db.execute('CREATE TABLE IF NOT EXISTS movies (code TEXT PRIMARY KEY, title TEXT, file_id TEXT, kind TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS sources (code TEXT PRIMARY KEY, chat_id INTEGER, message_id INTEGER, UNIQUE(chat_id, message_id))')
        self.db.commit()

    def api(self, method, **data):
        request = urllib.request.Request(
            f'https://api.telegram.org/bot{self.token}/{method}',
            data=json.dumps(data).encode(),
            headers={'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                result = json.load(exc)
            except (ValueError, OSError):
                raise APIError(exc.code) from None
        if not result.get('ok'):
            raise APIError(result.get('error_code', 500), result.get('parameters', {}).get('retry_after', 0))
        return result['result']

    def process_update(self, update):
        for key in ('channel_post', 'edited_channel_post'):
            if key in update:
                self.channel_post(update[key])
                return
        if 'message' in update:
            self.handle(update['message'])

    def run(self):
        print('Bot ishga tushdi. To‘xtatish: Ctrl+C')
        row = self.db.execute("SELECT value FROM state WHERE key='offset'").fetchone()
        offset = row[0] if row else 0
        while True:
            try:
                updates = self.api('getUpdates', offset=offset, timeout=30,
                                   allowed_updates=['message', 'callback_query', 'channel_post', 'edited_channel_post'])
                for update in updates:
                    try:
                        self.process_update(update)
                    except APIError as exc:
                        if exc.code == 429 or exc.code >= 500:
                            raise
                        self.diagnostic('Xabarni qayta ishlash xatosi', exc)
                    offset = update['update_id'] + 1
                    with self.db:
                        self.db.execute("INSERT OR REPLACE INTO state VALUES ('offset', ?)", (offset,))
            except APIError as exc:
                if exc.code in (401, 409):
                    raise SystemExit('Token noto‘g‘ri yoki bot boshqa joyda ham ishlayapti.') from None
                print(f'Telegram xatosi: {exc.code}. Qayta uriniladi.')
                time.sleep(max(3, exc.retry_after))
            except (urllib.error.URLError, TimeoutError, OSError):
                print('Tarmoq bilan aloqa yo‘q. Qayta uriniladi.')
                time.sleep(3)


class Bot(SeriesMixin, ManagementMixin, TelegramBot):
    api_error = APIError


if __name__ == '__main__':
    token, admins, channel = load_config()
    bot = Bot(token, admins, ROOT / 'movies.db', channel)
    try:
        bot.run()
    except KeyboardInterrupt:
        print('\nBot to‘xtadi.')
    finally:
        bot.stop_worker()
        bot.db.close()
