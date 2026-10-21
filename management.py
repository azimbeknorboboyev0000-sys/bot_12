import copy
import json
import logging
import re
import sqlite3
import threading
import time
import urllib.error
from urllib.parse import urlencode, urlparse


LOGGER = logging.getLogger('kino_bot')
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, OSError)
CODE = re.compile(r'[0-9]{1,12}')


def keyboard(rows):
    return {'inline_keyboard': [[{'text': label, 'callback_data': data} for label, data in row] for row in rows]}


def valid_url(value):
    try:
        parsed = urlparse(value)
        return parsed.scheme in ('http', 'https') and bool(parsed.hostname) and not parsed.username and not any(character.isspace() for character in value) and len(value) <= 1000
    except ValueError:
        return False


def units(value):
    return len(value.encode('utf-16-le')) // 2


class ManagementMixin:
    def __init__(self, token, admins, database, channel_id=None):
        super().__init__(token, admins, database, channel_id)
        self.database = str(database)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA busy_timeout=5000')
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(movies)')}
        if 'description' not in columns:
            self.db.execute("ALTER TABLE movies ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, active INTEGER NOT NULL DEFAULT 1,
                pending_code TEXT, joined_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, chat_id INTEGER UNIQUE NOT NULL,
                url TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY, user_id INTEGER, code TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY, admin_id INTEGER NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft', reported INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS recipients (
                broadcast_id INTEGER, user_id INTEGER, status TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY (broadcast_id, user_id));
        ''')
        self.db.commit()
        self.worker_stop = threading.Event()
        self.worker = None

    def say(self, chat, text, markup=None):
        data = {'chat_id': chat, 'text': text}
        if markup:
            data['reply_markup'] = markup
        return self.api('sendMessage', **data)

    def remember(self, user):
        with self.db:
            self.db.execute('INSERT INTO users (id) VALUES (?) ON CONFLICT(id) DO UPDATE SET active=1', (user,))

    def session(self, user):
        row = self.db.execute('SELECT data FROM sessions WHERE id=?', (user,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_session(self, user, data):
        with self.db:
            if data is None:
                self.db.execute('DELETE FROM sessions WHERE id=?', (user,))
            else:
                self.db.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)', (user, json.dumps(data)))

    def controls(self):
        return keyboard([[('⬅️ Orqaga', 'a:back'), ('❌ Bekor qilish', 'a:cancel')]])

    def panel(self, user):
        self.save_session(user, None)
        self.say(user, 'Admin paneli', keyboard([
            [('📺 Seriallar', 's:menu')],
            [('🎬 Kino qo‘shish', 'a:add'), ('📋 Kinolar ro‘yxati', 'a:list:0')],
            [('✏️ Kinoni tahrirlash', 'a:edit'), ('🗑 Kinoni o‘chirish', 'a:delete')],
            [('📢 Majburiy kanallar', 'a:channels'), ('📣 Reklama boshqaruvi', 'a:ads')],
            [('📊 Statistika', 'a:stats'), ('❌ Bekor qilish', 'a:cancel')]]))

    def begin(self, user, flow):
        first = {'add': 'code', 'edit': 'target', 'delete': 'target', 'channel': 'name',
                 'ad': 'text', 'broadcast': 'content'}[flow]
        self.save_session(user, {'flow': flow, 'step': first, 'values': {}, 'history': []})
        self.prompt(user)

    def advance(self, user, session, step, **values):
        previous = copy.deepcopy(session)
        previous.pop('history', None)
        session['history'].append(previous)
        session['values'].update(values)
        session['step'] = step
        self.save_session(user, session)
        self.prompt(user)

    def prompt(self, user):
        session = self.session(user)
        flow, step = session['flow'], session['step']
        prompts = {
            'code': 'Kino kodini kiriting (1–12 raqam).',
            'target': 'Kino kodini kiriting.',
            'title': 'Kino nomini kiriting (1–200 belgi).',
            'description': 'Tavsifni kiriting (700 belgigacha). Tavsifsiz saqlash uchun - yuboring.',
            'media': 'Video yoki video fayl yuboring; yoxud kanal xabarini yo‘naltiring. Mavjud kanal xabari uchun: -1001234567890 | 42',
            'name': 'Kanal nomini kiriting (100 belgigacha).',
            'chat': 'Kanal chat_id raqamini yoki @username qiymatini kiriting.',
            'url': 'Kanalga obuna havolasini kiriting: https://t.me/kanal yoki yopiq kanal taklif havolasi.',
            'text': 'Reklama matnini kiriting (3000 belgigacha).',
            'content': 'Reklama matni, rasm yoki video yuboring. Media izohi 1024 belgidan oshmasin.',
            'button': 'URL tugmasi uchun: Tugma nomi | https://example.com\nTugmasiz davom etish uchun - yuboring.',
            'field': 'Qaysi ma’lumotni tahrirlaysiz?',
            'confirm': 'Kinoni katalogdan o‘chirishni tasdiqlang. Kanaldagi asl xabar o‘chirilmaydi.'}
        markup = self.controls()
        if step == 'field':
            markup['inline_keyboard'][:0] = keyboard([[('Nomi', 'a:field:title'), ('Tavsifi', 'a:field:description'), ('Videosi', 'a:field:media')]])['inline_keyboard']
        if flow == 'delete' and step == 'confirm':
            markup['inline_keyboard'].insert(0, [{'text': '🗑 O‘chirishni tasdiqlash', 'callback_data': 'a:delete_yes'}])
        self.say(user, prompts[step], markup)

    def setting(self, key, default=None):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def store_setting(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, json.dumps(value)))

    def stats(self, user):
        values = [self.db.execute(query).fetchone()[0] for query in (
            'SELECT COUNT(*) FROM users', 'SELECT COUNT(*) FROM movies',
            'SELECT COUNT(*) FROM deliveries', 'SELECT COUNT(*) FROM channels WHERE enabled=1')]
        self.say(user, '📊 Statistika\nJami foydalanuvchilar: {}\nJami kinolar: {}\nMuvaffaqiyatli kino yuborishlar: {}\nFaol majburiy kanallar: {}'.format(*values), self.controls())

    def channel_menu(self, user):
        self.save_session(user, None)
        rows = [[('➕ Kanal qo‘shish', 'a:channel_add')]]
        for row in self.db.execute('SELECT * FROM channels ORDER BY id'):
            self.say(user, f"{row['name']} | {row['chat_id']}\n{row['url']}\nHolati: " + ('yoqilgan' if row['enabled'] else 'o‘chirilgan'), keyboard([
                [('O‘chirish' if row['enabled'] else 'Yoqish', f"a:toggle:{row['id']}"), ('🗑 Olib tashlash', f"a:remove:{row['id']}")]]))
        rows += [[('⬅️ Orqaga', 'a:home')]]
        self.say(user, 'Majburiy kanallar boshqaruvi', keyboard(rows))

    def ad_menu(self, user):
        self.save_session(user, None)
        ad = self.setting('movie_ad', {})
        self.say(user, 'Kino reklamasi: ' + ('yoqilgan' if ad.get('enabled') else 'o‘chirilgan') + '\n' + ad.get('text', 'Hali sozlanmagan.'), keyboard([
            [('✏️ Kino reklamasini sozlash', 'a:ad_edit')],
            [('Yoqish / o‘chirish', 'a:ad_toggle')],
            [('📣 Foydalanuvchilarga tarqatish', 'a:broadcast')], [('⬅️ Orqaga', 'a:home')]]))

    def validate_channel(self, identifier):
        chat = self.api('getChat', chat_id=identifier)
        if chat.get('type') != 'channel':
            raise ValueError('Bu kanal emas. Kanal chat_id qiymatini kiriting.')
        bot_id = self.api('getMe')['id']
        member = self.api('getChatMember', chat_id=chat['id'], user_id=bot_id)
        if member['status'] not in ('administrator', 'creator'):
            raise ValueError('Bot kanal administratori emas. Botni kanalga admin qilib qo‘shing.')
        return chat['id']

    def diagnostic(self, context, exc, channel=None):
        reason = str(exc) if isinstance(exc, ValueError) else ''
        LOGGER.warning('%s; kanal=%s; xato=%s; kod=%s; sabab=%s', context, channel, type(exc).__name__, getattr(exc, 'code', '-'), reason)

    def callback(self, query):
        user = query['from']['id']
        message = query.get('message', {})
        data = query.get('data', '')
        if message.get('chat', {}).get('type') != 'private' or message['chat']['id'] != user:
            self.api('answerCallbackQuery', callback_query_id=query['id'], text='Bu tugma shaxsiy suhbat uchun.')
            return
        self.remember(user)
        if data.startswith('a:') and user not in self.admins:
            self.api('answerCallbackQuery', callback_query_id=query['id'], text='Bu amal faqat admin uchun.', show_alert=True)
            return
        if query['id'] != 'local':
            self.api('answerCallbackQuery', callback_query_id=query['id'])
        if data == 'subscription':
            row = self.db.execute('SELECT pending_code FROM users WHERE id=?', (user,)).fetchone()
            if row and row[0]:
                self.deliver_movie(user, row[0])
            else:
                self.say(user, 'Kino kodini qayta yuboring.')
            return
        if not data.startswith('a:'):
            return
        action = data[2:]
        if action in ('home', 'cancel'):
            self.cancel_drafts(user)
            self.panel(user)
        elif action == 'back':
            self.cancel_drafts(user)
            session = self.session(user)
            if session and session['history']:
                previous = session['history'].pop()
                previous['history'] = session['history']
                self.save_session(user, previous)
                self.prompt(user)
            else:
                self.panel(user)
        elif action in ('add', 'edit', 'delete', 'broadcast'):
            self.cancel_drafts(user)
            self.begin(user, action)
        elif action == 'channel_add':
            self.begin(user, 'channel')
        elif action == 'ad_edit':
            self.begin(user, 'ad')
        elif action == 'channels':
            self.channel_menu(user)
        elif action == 'ads':
            self.ad_menu(user)
        elif action == 'stats':
            self.stats(user)
        elif action.startswith('list:'):
            try:
                page = max(0, int(action.split(':')[1]))
            except ValueError:
                return
            movies = self.db.execute('SELECT code, title FROM movies ORDER BY code LIMIT 15 OFFSET ?', (page * 15,)).fetchall()
            text = '\n'.join(f"{row['code']} | {row['title']}" for row in movies) or 'Kinolar topilmadi.'
            buttons = [[('⬅️ Orqaga', 'a:home')]]
            if page:
                buttons.insert(0, [('Oldingi sahifa', f'a:list:{page - 1}')])
            if len(movies) == 15:
                buttons.insert(0, [('Keyingi sahifa', f'a:list:{page + 1}')])
            self.say(user, text, keyboard(buttons))
        elif action.startswith(('toggle:', 'remove:')):
            try:
                identifier = int(action.split(':')[1])
            except ValueError:
                return
            row = self.db.execute('SELECT * FROM channels WHERE id=?', (identifier,)).fetchone()
            if not row:
                self.say(user, 'Kanal topilmadi.')
                return
            if action.startswith('toggle:') and not row['enabled']:
                try:
                    self.validate_channel(row['chat_id'])
                except (self.api_error, *NETWORK_ERRORS, ValueError) as exc:
                    self.channel_error(user, exc, row['chat_id'])
                    return
            with self.db:
                if action.startswith('remove:'):
                    self.db.execute('DELETE FROM channels WHERE id=?', (identifier,))
                else:
                    self.db.execute('UPDATE channels SET enabled=1-enabled WHERE id=?', (identifier,))
            self.channel_menu(user)
        elif action == 'ad_toggle':
            ad = self.setting('movie_ad', {})
            if not ad.get('text'):
                self.say(user, 'Avval reklama matnini sozlang.')
                return
            ad['enabled'] = not ad.get('enabled')
            self.store_setting('movie_ad', ad)
            self.ad_menu(user)
        elif action.startswith('field:'):
            session = self.session(user)
            field = action.split(':')[1]
            if session and session['flow'] == 'edit' and session['step'] == 'field' and field in ('title', 'description', 'media'):
                self.advance(user, session, field)
        elif action == 'delete_yes':
            session = self.session(user)
            if session and session['flow'] == 'delete' and session['step'] == 'confirm':
                code = session['values']['code']
                with self.db:
                    self.db.execute('DELETE FROM movies WHERE code=?', (code,))
                    self.db.execute('DELETE FROM sources WHERE code=?', (code,))
                self.say(user, 'Kino katalogdan o‘chirildi.')
                self.panel(user)
        elif action.startswith('send:'):
            try:
                identifier = int(action.split(':')[1])
            except ValueError:
                return
            with self.db:
                result = self.db.execute("UPDATE broadcasts SET status='queued' WHERE id=? AND admin_id=? AND status='draft'", (identifier, user))
            self.say(user, 'Tarqatish navbatga qo‘yildi.' if result.rowcount else 'Bu tarqatish allaqachon tasdiqlangan yoki bekor qilingan.')
            self.save_session(user, None)

    def cancel_drafts(self, user):
        with self.db:
            self.db.execute("UPDATE broadcasts SET status='cancelled' WHERE admin_id=? AND status='draft'", (user,))

    def channel_error(self, user, exc, channel=None):
        self.diagnostic('Kanalni tekshirish amalga oshmadi', exc, channel)
        if isinstance(exc, ValueError):
            reason = str(exc)
        else:
            reason = {400: 'Kanal topilmadi yoki bot kanalga kira olmayapti. chat_id va bot a’zoligini tekshiring.',
                      403: 'Bot kanalga kira olmayapti yoki bloklangan. Uni kanal administratori qiling.',
                      429: 'Telegram so‘rovlar chegarasi. Birozdan keyin qayta urinib ko‘ring.'}.get(getattr(exc, 'code', None), 'Telegram bilan aloqa xatosi. Keyinroq qayta urinib ko‘ring.')
        self.say(user, reason, self.controls())

    def extract_media(self, message, text):
        if message.get('has_protected_content'):
            raise ValueError('Himoyalangan xabarni ishlatib bo‘lmaydi.')
        media = message.get('video') or message.get('document')
        if media:
            if 'document' in message and not media.get('mime_type', '').startswith('video/'):
                raise ValueError('Video yoki video fayl yuboring.')
            return {'file_id': media['file_id'], 'kind': 'video' if 'video' in message else 'document'}
        match = re.fullmatch(r'(-[0-9]+|@[A-Za-z0-9_]{5,32})\s*\|\s*([1-9][0-9]*)', text)
        if match:
            chat = int(match[1]) if match[1].startswith('-') else match[1]
            source = self.api('getChat', chat_id=chat)
            if source.get('type') != 'channel':
                raise ValueError('Saqlash manzili kanal bo‘lishi kerak.')
            return {'file_id': '', 'kind': 'video', 'source_chat': source['id'], 'source_message': int(match[2])}
        raise ValueError('Video yuboring yoki kanal xabarini chat_id | message_id shaklida kiriting.')

    def movie_link(self, code):
        username = self.api('getMe').get('username')
        if not username:
            raise ValueError('Bot username’ini aniqlab bo‘lmadi.')
        return f'https://t.me/{username}?{urlencode({"start": code})}'

    def movie_markup(self, code, title, markup=None):
        result = copy.deepcopy(markup) if markup else {'inline_keyboard': []}
        parameters = {'url': self.movie_link(code), 'text': f'🎬 {title}\n🍿 Kinoni bot orqali tomosha qiling!'}
        result['inline_keyboard'].append([{'text': '📤 Ulashish', 'url': 'https://t.me/share/url?' + urlencode(parameters)}])
        return result

    def movie_saved(self, chat, code):
        text = f'✅ Kino saqlandi. Kod: {code}'
        try:
            text += f'\n🔗 Kino havolasi: {self.movie_link(code)}'
        except (self.api_error, *NETWORK_ERRORS, ValueError) as exc:
            self.diagnostic('Kino havolasini yaratish xatosi', exc)
            text += '\nHavola uchun bot username’ini hozir aniqlab bo‘lmadi. Kino saqlangan.'
        self.say(chat, text)

    def save_movie(self, values, replace=False):
        code = values['code']
        with self.db:
            if replace:
                field = values['field']
                if field in ('title', 'description'):
                    self.db.execute(f'UPDATE movies SET {field}=? WHERE code=?', (values[field], code))
                    return
                self.db.execute('UPDATE movies SET file_id=?, kind=? WHERE code=?', (values['file_id'], values['kind'], code))
            else:
                self.db.execute('INSERT INTO movies (code,title,file_id,kind,description) VALUES (?,?,?,?,?)',
                                (code, values['title'], values['file_id'], values['kind'], values.get('description', '')))
            self.db.execute('DELETE FROM sources WHERE code=?', (code,))
            if 'source_chat' in values:
                self.db.execute('INSERT INTO sources VALUES (?,?,?)', (code, values['source_chat'], values['source_message']))

    def admin_input(self, user, message, session):
        if user not in self.admins:
            self.save_session(user, None)
            self.say(user, 'Bu amal faqat admin uchun.')
            return
        text = message.get('text', '').strip()
        flow, step, values = session['flow'], session['step'], session['values']
        try:
            if step in ('code', 'target'):
                if not CODE.fullmatch(text):
                    raise ValueError('Kod 1–12 raqamdan iborat bo‘lsin.')
                exists = self.db.execute('SELECT 1 FROM movies WHERE code=?', (text,)).fetchone()
                if flow == 'add' and exists:
                    raise ValueError('Bu kod band. Mavjud kino almashtirilmadi. Boshqa kod kiriting.')
                if flow != 'add' and not exists:
                    raise ValueError('Kino topilmadi. Kodni tekshiring.')
                self.advance(user, session, {'add': 'title', 'edit': 'field', 'delete': 'confirm'}[flow], code=text)
            elif step in ('title', 'description'):
                limit = 200 if step == 'title' else 700
                if not text or units(text) > limit:
                    raise ValueError(f'Matn kiriting, uzunligi {limit} belgidan oshmasin.')
                value = '' if step == 'description' and text == '-' else text
                if flow == 'edit':
                    self.save_movie({**values, step: value, 'field': step}, True)
                    self.say(user, 'Kino yangilandi.')
                    self.panel(user)
                else:
                    self.advance(user, session, 'description' if step == 'title' else 'media', **{step: value})
            elif step == 'media':
                media = self.extract_media(message, text)
                if 'source_chat' in media:
                    preview = self.api('forwardMessage', chat_id=user, from_chat_id=media['source_chat'], message_id=media['source_message'])
                    verified = self.extract_media(preview, '')
                    if not verified.get('file_id'):
                        raise ValueError('Tanlangan kanal xabarida video yo‘q.')
                    media.update(verified)
                self.save_movie({**values, **media, 'field': 'media'}, flow == 'edit')
                self.movie_saved(user, values['code'])
                self.panel(user)
            elif step == 'name':
                if not text or units(text) > 100:
                    raise ValueError('Kanal nomi 1–100 belgi bo‘lsin.')
                self.advance(user, session, 'chat', name=text)
            elif step == 'chat':
                if not re.fullmatch(r'-[0-9]+|@[A-Za-z0-9_]{5,32}', text):
                    raise ValueError('Manfiy chat_id yoki @username kiriting.')
                identifier = self.validate_channel(int(text) if text.startswith('-') else text)
                self.advance(user, session, 'url', chat_id=identifier)
            elif step == 'url':
                if not valid_url(text) or urlparse(text).hostname not in ('t.me', 'telegram.me') or not urlparse(text).path.strip('/'):
                    raise ValueError('To‘g‘ri Telegram kanal havolasini kiriting.')
                self.validate_channel(values['chat_id'])
                with self.db:
                    self.db.execute('INSERT INTO channels (name,chat_id,url) VALUES (?,?,?)', (values['name'], values['chat_id'], text))
                self.channel_menu(user)
            elif step == 'text':
                if not text or units(text) > 3000:
                    raise ValueError('Reklama matni 1–3000 belgi bo‘lsin.')
                self.advance(user, session, 'button', text=text)
            elif step == 'content':
                if message.get('photo') or message.get('video'):
                    kind = 'photo' if message.get('photo') else 'video'
                    media = message['photo'][-1] if kind == 'photo' else message['video']
                    payload = {'kind': kind, 'file_id': media['file_id'], 'text': message.get('caption', '')}
                    if units(payload['text']) > 1024:
                        raise ValueError('Media izohi 1024 belgidan oshmasin.')
                elif text and units(text) <= 4096:
                    payload = {'kind': 'text', 'text': text}
                else:
                    raise ValueError('Matn (4096 belgigacha), rasm yoki video yuboring.')
                self.advance(user, session, 'button', **payload)
            elif step == 'button':
                button = None
                if text != '-':
                    label, separator, url = text.partition('|')
                    if not separator or not label.strip() or units(label.strip()) > 64 or not valid_url(url.strip()):
                        raise ValueError('Namuna: Batafsil | https://example.com yoki - yuboring.')
                    button = {'text': label.strip(), 'url': url.strip()}
                payload = {**values, 'button': button}
                if flow == 'ad':
                    self.store_setting('movie_ad', {**payload, 'enabled': True})
                    self.ad_menu(user)
                else:
                    self.cancel_drafts(user)
                    self.send_payload(user, payload)
                    with self.db:
                        job = self.db.execute('INSERT INTO broadcasts (admin_id,payload) VALUES (?,?)', (user, json.dumps(payload))).lastrowid
                        self.db.execute('INSERT INTO recipients (broadcast_id,user_id) SELECT ?,id FROM users', (job,))
                    count = self.db.execute('SELECT COUNT(*) FROM recipients WHERE broadcast_id=?', (job,)).fetchone()[0]
                    previous = copy.deepcopy(session)
                    previous.pop('history', None)
                    session['history'].append(previous)
                    session['step'] = 'preview'
                    self.save_session(user, session)
                    self.say(user, f'Reklama ko‘rinishi yuqorida. Qabul qiluvchilar: {count}.\nTasdiqlanmaguncha tarqatilmaydi.', keyboard([
                        [('✅ Yuborishni tasdiqlash', f'a:send:{job}')], [('⬅️ Orqaga', 'a:back'), ('❌ Bekor qilish', 'a:cancel')]]))
            else:
                self.say(user, 'Kerakli tugmani bosing.', self.controls())
        except sqlite3.IntegrityError:
            self.say(user, 'Bu kod, kanal yoki kanal xabari bazada mavjud. Avval mavjud yozuvni tekshiring.', self.controls())
        except ValueError as exc:
            self.say(user, str(exc), self.controls())
        except (self.api_error, *NETWORK_ERRORS) as exc:
            if flow == 'channel':
                self.channel_error(user, exc, values.get('chat_id'))
            else:
                self.diagnostic('Admin amali amalga oshmadi', exc)
                self.say(user, 'Telegram amalni bajara olmadi. Kanal xabari, bot huquqi va aloqani tekshirib qayta urinib ko‘ring.', self.controls())

    def subscribed(self, user):
        missing = []
        try:
            for channel in self.db.execute('SELECT * FROM channels WHERE enabled=1').fetchall():
                self.validate_channel(channel['chat_id'])
                member = self.api('getChatMember', chat_id=channel['chat_id'], user_id=user)
                status = member.get('status')
                if status not in ('member', 'administrator', 'creator') and not (status == 'restricted' and member.get('is_member') is True):
                    missing.append(channel)
        except (self.api_error, *NETWORK_ERRORS, ValueError) as exc:
            self.diagnostic('Obunani tekshirish xatosi', exc, channel['chat_id'])
            self.say(user, 'Obunani hozir tekshirib bo‘lmadi. Bu obuna bo‘lmaganingizni anglatmaydi. Birozdan keyin qayta tekshiring.', keyboard([[('✅ Obunani tekshirish', 'subscription')]]))
            return False
        if missing:
            markup = {'inline_keyboard': [[{'text': channel['name'], 'url': channel['url']}] for channel in missing]}
            markup['inline_keyboard'].append([{'text': '✅ Obunani tekshirish', 'callback_data': 'subscription'}])
            self.say(user, 'Kinoni olish uchun quyidagi kanallarga obuna bo‘ling. Qo‘shilish so‘rovi tasdiqlanishi kerak.', markup)
            return False
        return True

    def deliver_movie(self, user, code):
        self.remember(user)
        with self.db:
            self.db.execute('UPDATE users SET pending_code=? WHERE id=?', (code, user))
        movie = self.db.execute('SELECT * FROM movies WHERE code=?', (code,)).fetchone()
        if not movie:
            self.say(user, 'Bu kod bilan kino topilmadi. Kodni tekshiring.')
            return
        if not self.subscribed(user):
            return
        caption = f"🎬 {movie['title']}\nKod: {code}"
        if movie['description']:
            caption += '\n' + movie['description']
        ad = self.setting('movie_ad', {})
        ad_text = ad.get('text', '') if ad.get('enabled') else ''
        combined = caption + ('\n\n' + ad_text if ad_text else '')
        separate = units(combined) > 1024
        markup = {'inline_keyboard': [[ad['button']]]} if ad_text and ad.get('button') else None
        data = {'chat_id': user, 'caption': caption if separate else combined}
        extra_caption = None
        if units(data['caption']) > 1024:
            extra_caption = caption
            data['caption'] = f'🎬 Kino kodi: {code}'
        source = self.db.execute('SELECT chat_id,message_id FROM sources WHERE code=?', (code,)).fetchone()
        try:
            data['reply_markup'] = self.movie_markup(code, movie['title'], markup if not separate else None)
            if source:
                self.api('copyMessage', from_chat_id=source[0], message_id=source[1], **data)
            else:
                self.api('sendVideo' if movie['kind'] == 'video' else 'sendDocument', **data, **{movie['kind']: movie['file_id']})
        except (self.api_error, *NETWORK_ERRORS, ValueError) as exc:
            self.diagnostic('Kino yuborilmadi', exc)
            self.say(user, 'Kinoni yuborib bo‘lmadi. Keyinroq qayta urinib ko‘ring yoki adminga xabar bering.')
            return
        with self.db:
            self.db.execute('INSERT INTO deliveries (user_id,code) VALUES (?,?)', (user, code))
            self.db.execute('UPDATE users SET pending_code=NULL WHERE id=?', (user,))
        if extra_caption:
            for start in range(0, len(extra_caption), 1800):
                self.say(user, extra_caption[start:start + 1800])
        if separate and ad_text:
            self.say(user, ad_text, markup)

    def handle(self, message):
        if message['chat']['type'] != 'private':
            return
        user = message['from']['id']
        self.remember(user)
        text = message.get('text', '').strip()
        command = text.split()[0].split('@')[0] if text else ''
        admin = user in self.admins
        if command in ('/admin', '/stats', '/delete'):
            if not admin:
                self.say(user, 'Bu buyruq faqat admin uchun.')
                return
            if command == '/admin':
                self.cancel_drafts(user)
                self.panel(user)
            elif command == '/stats':
                self.stats(user)
            else:
                self.begin(user, 'delete')
                parts = text.split()
                if len(parts) == 2:
                    self.admin_input(user, {'text': parts[1]}, self.session(user))
            return
        if command in ('/cancel', '/back'):
            if admin:
                self.callback({'id': 'local', 'from': {'id': user}, 'message': message, 'data': 'a:cancel' if command == '/cancel' else 'a:back'})
            else:
                self.say(user, 'Kino kodini yuboring.')
            return
        if command == '/id':
            self.say(user, f'Telegram ID: {user}')
            return
        if command in ('/start', '/help'):
            self.save_session(user, None)
            parts = text.split()
            if command == '/start' and len(parts) > 1:
                if len(parts) == 2 and CODE.fullmatch(parts[1]):
                    self.deliver_movie(user, parts[1])
                else:
                    self.say(user, 'Havoladagi kino kodi noto‘g‘ri. Kod 1–12 raqamdan iborat bo‘lsin. Masalan: /start 8')
            else:
                self.say(user, '🎬 Kino kodini yuboring. Masalan: 125' + ('\nBoshqaruv: /admin' if admin else ''))
            return
        session = self.session(user)
        if session:
            self.admin_input(user, message, session)
            return
        if admin and (message.get('video') or message.get('document')):
            parts = [part.strip() for part in message.get('caption', '').split('|', 2)]
            if len(parts) < 2 or not CODE.fullmatch(parts[0]) or not parts[1] or units(parts[1]) > 200 or (len(parts) == 3 and units(parts[2]) > 700):
                self.say(user, 'Video izohi: 125 | Kino nomi | Ixtiyoriy tavsif. Yoki /admin orqali qo‘shing.')
                return
            try:
                self.save_movie({'code': parts[0], 'title': parts[1], 'description': parts[2] if len(parts) == 3 else '', **self.extract_media(message, '')})
                self.movie_saved(user, parts[0])
            except sqlite3.IntegrityError:
                self.say(user, 'Bu kod band. Mavjud kino almashtirilmadi.')
            except ValueError as exc:
                self.say(user, str(exc))
            return
        if CODE.fullmatch(text):
            self.deliver_movie(user, text)
        else:
            self.say(user, 'Kino kodini 1–12 raqam bilan yuboring. Masalan: 125')

    def channel_post(self, message):
        chat = message['chat']['id']
        if message.get('text', '').strip().split('@')[0] == '/channelid':
            if chat == self.channel_id:
                self.say(chat, f'CHANNEL_ID={chat}')
            return
        if chat != self.channel_id or not (message.get('video') or message.get('document')):
            return
        parts = [part.strip() for part in message.get('caption', '').split('|', 2)]
        if len(parts) < 2 or not CODE.fullmatch(parts[0]) or not parts[1] or units(parts[1]) > 200 or (len(parts) == 3 and units(parts[2]) > 700):
            self.say(chat, 'Video izohi: 125 | Kino nomi | Ixtiyoriy tavsif. Kod 1–12 raqam bo‘lsin.')
            return
        code, title = parts[:2]
        source = self.db.execute('SELECT code FROM sources WHERE chat_id=? AND message_id=?', (chat, message['message_id'])).fetchone()
        exists = self.db.execute('SELECT 1 FROM movies WHERE code=?', (code,)).fetchone()
        if exists and (not source or source[0] != code):
            self.say(chat, 'Bu kod band. Mavjud kino almashtirilmadi.')
            return
        try:
            media = self.extract_media(message, '')
            with self.db:
                if source:
                    self.db.execute('DELETE FROM movies WHERE code=?', (source[0],))
                    self.db.execute('DELETE FROM sources WHERE code=?', (source[0],))
                self.db.execute('INSERT INTO movies (code,title,file_id,kind,description) VALUES (?,?,?,?,?)',
                                (code, title, media['file_id'], media['kind'], parts[2] if len(parts) == 3 else ''))
                self.db.execute('INSERT INTO sources VALUES (?,?,?)', (code, chat, message['message_id']))
            self.movie_saved(chat, code)
        except ValueError as exc:
            self.say(chat, str(exc))

    def process_update(self, update):
        if 'callback_query' in update:
            self.callback(update['callback_query'])
        else:
            super().process_update(update)

    def send_payload(self, user, payload):
        markup = {'inline_keyboard': [[payload['button']]]} if payload.get('button') else None
        data = {'chat_id': user}
        if markup:
            data['reply_markup'] = markup
        if payload['kind'] == 'text':
            return self.api('sendMessage', text=payload['text'], **data)
        kind = payload['kind']
        return self.api('sendPhoto' if kind == 'photo' else 'sendVideo', caption=payload['text'], **data, **{kind: payload['file_id']})

    def run_broadcast(self, connection, job):
        job_id = job['id']
        payload = json.loads(job['payload'])
        with connection:
            connection.execute("UPDATE broadcasts SET status='running' WHERE id=?", (job_id,))
        recipients = connection.execute("SELECT r.user_id,u.active FROM recipients r LEFT JOIN users u ON u.id=r.user_id WHERE broadcast_id=? AND r.status='pending' ORDER BY r.user_id", (job_id,)).fetchall()
        for recipient in recipients:
            if self.worker_stop.is_set():
                return
            user = recipient['user_id']
            status = 'skipped'
            if recipient['active']:
                with connection:
                    connection.execute("UPDATE recipients SET status='sending' WHERE broadcast_id=? AND user_id=?", (job_id, user))
                for attempt in range(4):
                    try:
                        self.send_payload(user, payload)
                        status = 'success'
                        break
                    except self.api_error as exc:
                        self.diagnostic('Reklama yuborish xatosi', exc)
                        if exc.code == 429 and attempt < 3:
                            if self.worker_stop.wait(max(1, exc.retry_after)):
                                with connection:
                                    connection.execute("UPDATE recipients SET status='pending' WHERE broadcast_id=? AND user_id=?", (job_id, user))
                                return
                            continue
                        status = 'failed'
                        if exc.code == 403:
                            with connection:
                                connection.execute('UPDATE users SET active=0 WHERE id=?', (user,))
                        break
                    except NETWORK_ERRORS as exc:
                        self.diagnostic('Reklama tarmoq xatosi', exc)
                        status = 'failed'
                        break
            with connection:
                connection.execute('UPDATE recipients SET status=? WHERE broadcast_id=? AND user_id=?', (status, job_id, user))
            if self.worker_stop.wait(0.1):
                return
        with connection:
            connection.execute("UPDATE broadcasts SET status='done' WHERE id=?", (job_id,))

    def report_broadcast(self, connection, job):
        counts = dict(connection.execute('SELECT status,COUNT(*) FROM recipients WHERE broadcast_id=? GROUP BY status', (job['id'],)).fetchall())
        self.say(job['admin_id'], 'Reklama tarqatish yakunlandi.\nMuvaffaqiyatli: {}\nMuvaffaqiyatsiz: {}\nO‘tkazib yuborilgan: {}'.format(counts.get('success', 0), counts.get('failed', 0), counts.get('skipped', 0)))
        with connection:
            connection.execute('UPDATE broadcasts SET reported=1 WHERE id=?', (job['id'],))

    def broadcast_loop(self):
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                connection.execute("UPDATE recipients SET status='skipped' WHERE status='sending'")
            while not self.worker_stop.is_set():
                try:
                    job = connection.execute("SELECT * FROM broadcasts WHERE status IN ('queued','running') ORDER BY id LIMIT 1").fetchone()
                    if job:
                        self.run_broadcast(connection, job)
                    report = connection.execute("SELECT * FROM broadcasts WHERE status='done' AND reported=0 ORDER BY id LIMIT 1").fetchone()
                    if report:
                        self.report_broadcast(connection, report)
                except (self.api_error, *NETWORK_ERRORS, sqlite3.Error) as exc:
                    self.diagnostic('Tarqatish oqimi xatosi', exc)
                    self.worker_stop.wait(max(3, getattr(exc, 'retry_after', 0)))
                self.worker_stop.wait(0.5)
        finally:
            connection.close()

    def run(self):
        self.api('getMe')
        if self.api('getWebhookInfo').get('url'):
            raise SystemExit('Webhook yoqilgan. Pollingdan avval webhookni o‘chiring.')
        self.worker = threading.Thread(target=self.broadcast_loop, name='reklama', daemon=True)
        self.worker.start()
        try:
            super().run()
        finally:
            self.stop_worker()

    def stop_worker(self):
        self.worker_stop.set()
        if self.worker:
            self.worker.join(timeout=50)
