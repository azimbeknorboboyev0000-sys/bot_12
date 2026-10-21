"""Persistent series catalog and ordered admin uploads; no media downloads."""
import json
import re
import sqlite3
from urllib.parse import urlencode

from management import keyboard, units, NETWORK_ERRORS


class SeriesMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS serials (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '', poster TEXT);
            CREATE TABLE IF NOT EXISTS uploads (
                admin INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, serial INTEGER NOT NULL,
                season INTEGER NOT NULL, number INTEGER NOT NULL,
                file_id TEXT NOT NULL, kind TEXT NOT NULL,
                UNIQUE(serial,season,number));
            CREATE TABLE IF NOT EXISTS episode_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT, admin INTEGER NOT NULL,
                message INTEGER, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(admin,message));
        ''')
        self.db.commit()

    def upload(self, user):
        row = self.db.execute('SELECT data FROM uploads WHERE admin=?', (user,)).fetchone()
        return json.loads(row[0]) if row else None

    def run(self):
        for row in self.db.execute('SELECT admin,data FROM uploads').fetchall():
            if row['admin'] not in self.admins or not json.loads(row['data']).get('active'):
                continue
            try:
                self.say(row['admin'], '📺 Bot qayta ishga tushdi. Tugallanmagan yuklash mavjud.',
                         keyboard([[('Davom ettirish', 's:resume'), ('✅ Yakunlash', 's:finish')]]))
            except (self.api_error, *NETWORK_ERRORS) as exc:
                self.diagnostic('Yuklashni davom ettirish eslatmasi yuborilmadi', exc)
        super().run()

    def put_upload(self, user, data):
        self.db.execute('INSERT OR REPLACE INTO uploads VALUES (?,?)', (user, json.dumps(data)))

    def upload_buttons(self):
        return keyboard([[('✅ Yakunlash', 's:finish')],
                         [('🔢 Keyingi qism raqamini o‘zgartirish', 's:number')],
                         [('🗓 Mavsumni o‘zgartirish', 's:season')],
                         [('↩️ Oxirgi qo‘shilgan qismni bekor qilish', 's:undo')]])

    def upload_prompt(self, user, data):
        serial = self.db.execute('SELECT * FROM serials WHERE id=?', (data['serial'],)).fetchone()
        self.say(user, f"📺 {serial['title']} | {data['season']}-mavsum\n"
                 f"Navbatdagi video: {data['next']}-qism.\n\n"
                 'Videolarni ketma-ket yuboring yoki kanaldan forward qiling. '
                 'Men qismlarni avtomatik raqamlab saqlayman.\n\n'
                 'Tugatgach, «✅ Yakunlash»ni bosing.', self.upload_buttons())

    def start_upload(self, user, serial, season=1):
        last = self.db.execute('SELECT MAX(number) FROM episodes WHERE serial=? AND season=?', (serial, season)).fetchone()[0]
        data = {'serial': serial, 'season': season, 'next': (last or 0) + 1,
                'step': 'upload', 'added': [], 'active': True}
        with self.db:
            self.put_upload(user, data)
        self.upload_prompt(user, data)

    def panel(self, user):
        super().panel(user)
        data = self.upload(user)
        if data and data.get('active'):
            self.say(user, '📺 Tugallanmagan serial yuklash mavjud.', keyboard([
                [('Davom ettirish', 's:resume'), ('✅ Yakunlash', 's:finish')]]))

    def callback(self, query):
        action = query.get('data', '')
        if not action.startswith(('s:', 'v:')):
            return super().callback(query)
        user = query['from']['id']
        chat = query.get('message', {}).get('chat', {})
        if chat.get('type') != 'private' or chat.get('id') != user:
            return
        if action.startswith('s:') and user not in self.admins:
            self.api('answerCallbackQuery', callback_query_id=query['id'], text='Bu amal faqat admin uchun.', show_alert=True)
            return
        self.api('answerCallbackQuery', callback_query_id=query['id'])
        self.remember(user)
        try:
            if action.startswith('v:'):
                parts = action.split(':')
                if parts[1] == 'e':
                    self.deliver_episode(user, int(parts[2]))
                else:
                    self.show_serial(user, int(parts[2]), int(parts[3]) if len(parts) > 3 else None,
                                     int(parts[4]) if len(parts) > 4 else 0)
                return
            self.serial_action(user, action[2:])
        except (ValueError, IndexError, TypeError):
            self.say(user, 'Ma’lumot topilmadi. Menyuni qayta oching.')

    def serial_action(self, user, action):
        data = self.upload(user)
        if action == 'menu':
            self.say(user, '📺 Seriallar', keyboard([[('➕ Yangi serial', 's:new')],
                     [('📋 Mavjud seriallar', 's:list:0')], [('🏠 Admin panel', 'a:home')]]))
        elif action == 'new':
            if data and data.get('active'):
                self.say(user, 'Avval joriy yuklashni yakunlang.', keyboard([[('Davom ettirish', 's:resume'), ('✅ Yakunlash', 's:finish')]]))
                return
            self.save_session(user, None)
            with self.db:
                self.put_upload(user, {'step': 'title', 'active': True})
            self.say(user, 'Serial nomini kiriting (200 belgigacha).')
        elif action.startswith('list:'):
            page = max(0, int(action.split(':')[1]))
            rows = self.db.execute('SELECT * FROM serials ORDER BY id LIMIT 11 OFFSET ?', (page * 10,)).fetchall()
            buttons = [[(r['title'], f"s:open:{r['id']}")] for r in rows[:10]]
            if page:
                buttons.append([('Oldingi sahifa', f's:list:{page-1}')])
            if len(rows) > 10:
                buttons.append([('Keyingi sahifa', f's:list:{page+1}')])
            self.say(user, '📋 Mavjud seriallar', keyboard(buttons))
        elif action.startswith('open:'):
            serial = int(action.split(':')[1])
            row = self.db.execute('SELECT * FROM serials WHERE id=?', (serial,)).fetchone()
            if not row:
                raise ValueError()
            self.say(user, row['title'], self.serial_admin_buttons(serial))
        elif action.startswith(('add:', 'newseason:')):
            serial = int(action.split(':')[1])
            if data and data.get('active'):
                self.say(user, 'Avval joriy yuklashni yakunlang.', keyboard([[('Davom ettirish', 's:resume'), ('✅ Yakunlash', 's:finish')]]))
                return
            if not self.db.execute('SELECT 1 FROM serials WHERE id=?', (serial,)).fetchone():
                raise ValueError()
            season = self.db.execute('SELECT MAX(season) FROM episodes WHERE serial=?', (serial,)).fetchone()[0] or 1
            if action.startswith('newseason:'):
                season += 1
            self.start_upload(user, serial, season)
        elif data and data.get('active'):
            if action == 'skip' and data['step'] in ('description', 'poster'):
                self.serial_input(user, {'text': '-'}, data)
            elif action == 'resume':
                if 'serial' not in data:
                    prompts = {'title': 'Serial nomini kiriting (200 belgigacha).',
                               'description': 'Tavsifni kiriting (700 belgigacha).',
                               'poster': 'Poster rasmini yuboring.'}
                    self.say(user, prompts[data['step']], keyboard([[('O‘tkazib yuborish', 's:skip')]]) if data['step'] != 'title' else None)
                    return
                self.save_session(user, None)
                data['step'] = 'upload'
                with self.db:
                    self.put_upload(user, data)
                self.upload_prompt(user, data)
                self.drain_episodes(user)
            elif action in ('number', 'season') and 'serial' in data:
                if self.db.execute("SELECT 1 FROM episode_queue WHERE admin=? AND status='pending'", (user,)).fetchone():
                    self.say(user, 'Avval navbatdagi qism to‘qnashuvini hal qiling.')
                    return
                data['step'] = action
                with self.db:
                    self.put_upload(user, data)
                self.say(user, 'Musbat butun raqam kiriting.')
            elif action == 'undo' and data.get('added'):
                if self.db.execute("SELECT 1 FROM episode_queue WHERE admin=? AND status='pending'", (user,)).fetchone():
                    self.say(user, 'Avval navbatdagi qism to‘qnashuvini hal qiling.')
                    return
                entry = data['added'].pop()
                with self.db:
                    if entry['old']:
                        old = entry['old']
                        self.db.execute('UPDATE episodes SET file_id=?,kind=? WHERE id=?', (old['file_id'], old['kind'], entry['id']))
                    else:
                        self.db.execute('DELETE FROM episodes WHERE id=?', (entry['id'],))
                    data['next'] = entry['number']
                    self.put_upload(user, data)
                self.say(user, 'Oxirgi qo‘shish bekor qilindi. Asl video saqlangan.', self.upload_buttons())
            elif action.startswith(('replace:', 'skip_episode:')):
                decision, item_id = action.split(':')
                item = self.db.execute("SELECT id FROM episode_queue WHERE admin=? AND status='pending' ORDER BY message,id LIMIT 1", (user,)).fetchone()
                if item and item[0] == int(item_id):
                    self.drain_episodes(user, decision)
            elif action == 'finish':
                if 'serial' not in data:
                    with self.db:
                        self.db.execute('DELETE FROM uploads WHERE admin=?', (user,))
                    self.panel(user)
                    return
                if self.db.execute("SELECT 1 FROM episode_queue WHERE admin=? AND status='pending'", (user,)).fetchone():
                    self.say(user, 'Avval navbatdagi qismlarni saqlang yoki to‘qnashuvni hal qiling.')
                    self.drain_episodes(user)
                    return
                data['active'] = False
                with self.db:
                    self.put_upload(user, data)
                row = self.db.execute('SELECT title FROM serials WHERE id=?', (data['serial'],)).fetchone()
                try:
                    link = self.movie_link(f"s{data['serial']}")
                except (self.api_error, *NETWORK_ERRORS, ValueError):
                    link = f"Kod: S{data['serial']} (havola uchun qayta oching)"
                self.say(user, f"✅ {row[0]} — {data['season']}-mavsum\nUshbu yuklashda qo‘shildi: {len(data['added'])} ta qism.\n🔗 Serial havolasi: {link}", self.serial_admin_buttons(data['serial']))

    def serial_admin_buttons(self, serial):
        return keyboard([[('➕ Yana qism qo‘shish', f's:add:{serial}')],
                         [('➕ Yangi mavsum', f's:newseason:{serial}')],
                         [('📋 Qismlarni ko‘rish', f'v:s:{serial}')], [('🏠 Admin panel', 'a:home')]])

    def handle(self, message):
        user = message.get('from', {}).get('id')
        if message.get('chat', {}).get('type') != 'private':
            return super().handle(message)
        text = message.get('text', '').strip()
        parts = text.split()
        target = parts[1] if len(parts) == 2 and parts[0].split('@')[0] == '/start' else text
        if re.fullmatch(r'[sS][1-9][0-9]*|e[1-9][0-9]*', target):
            self.remember(user)
            if target.startswith('e'):
                self.deliver_episode(user, int(target[1:]))
            else:
                self.show_serial(user, int(target[1:]))
            return
        data = self.upload(user)
        if self.session(user):
            return super().handle(message)
        if data and data.get('active') and not text.startswith('/'):
            if user not in self.admins:
                self.say(user, 'Bu amal faqat admin uchun.')
                return
            return self.serial_input(user, message, data)
        return super().handle(message)

    def serial_input(self, user, message, data):
        text = message.get('text', '').strip()
        step = data['step']
        if step in ('title', 'description', 'poster'):
            if step == 'poster':
                if text != '-' and not message.get('photo'):
                    self.say(user, 'Poster rasmini yuboring yoki o‘tkazib yuboring.', keyboard([[('O‘tkazib yuborish', 's:skip')]]))
                    return
                with self.db:
                    serial = self.db.execute('INSERT INTO serials(title,description,poster) VALUES (?,?,?)',
                        (data['title'], data.get('description', ''), message['photo'][-1]['file_id'] if message.get('photo') else None)).lastrowid
                    data = {'serial': serial, 'season': 1, 'next': 1,
                            'step': 'upload', 'added': [], 'active': True}
                    self.put_upload(user, data)
                self.upload_prompt(user, data)
                return
            if not text or units(text) > (200 if step == 'title' else 700):
                self.say(user, 'Matnni belgilangan uzunlikda kiriting.')
                return
            data[step] = '' if text == '-' and step == 'description' else text
            data['step'] = 'description' if step == 'title' else 'poster'
            with self.db:
                self.put_upload(user, data)
            self.say(user, 'Tavsifni kiriting (700 belgigacha).' if step == 'title' else 'Poster rasmini yuboring.', keyboard([[('O‘tkazib yuborish', 's:skip')]]))
            return
        if step in ('number', 'season'):
            if not re.fullmatch(r'[1-9][0-9]{0,5}', text):
                self.say(user, '1–999999 oralig‘ida raqam kiriting.')
                return
            if step == 'number':
                data['next'] = int(text)
            else:
                data['season'] = int(text)
                last = self.db.execute('SELECT MAX(number) FROM episodes WHERE serial=? AND season=?', (data['serial'], int(text))).fetchone()[0]
                data['next'] = (last or 0) + 1
            data['step'] = 'upload'
            with self.db:
                self.put_upload(user, data)
            self.upload_prompt(user, data)
            return
        try:
            media = self.extract_media(message, '')
        except ValueError:
            self.say(user, 'Video yoki video sifatidagi document faylini yuboring. Qism raqami o‘zgarmadi.', self.upload_buttons())
            return
        try:
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO episode_queue(admin,message,payload) VALUES (?,?,?)',
                                (user, message.get('message_id'), json.dumps(media)))
        except sqlite3.Error:
            self.say(user, 'Saqlanmadi. Raqam o‘zgarmadi, videoni qayta yuboring.')
            return
        self.drain_episodes(user)

    def drain_episodes(self, user, decision=None):
        while True:
            data = self.upload(user)
            item = self.db.execute("SELECT * FROM episode_queue WHERE admin=? AND status='pending' ORDER BY message,id LIMIT 1", (user,)).fetchone()
            if not item or not data or not data.get('active') or user not in self.admins:
                return
            number = data['next']
            try:
                with self.db:
                    old = self.db.execute('SELECT * FROM episodes WHERE serial=? AND season=? AND number=?', (data['serial'], data['season'], number)).fetchone()
                    if old and decision not in ('replace', 'skip_episode'):
                        conflict = True
                    else:
                        conflict = False
                        media = json.loads(item['payload'])
                        if old and decision == 'skip_episode':
                            self.db.execute("UPDATE episode_queue SET status='skipped' WHERE id=?", (item['id'],))
                        else:
                            if old:
                                identifier = old['id']
                                self.db.execute('UPDATE episodes SET file_id=?,kind=? WHERE id=?', (media['file_id'], media['kind'], identifier))
                            else:
                                identifier = self.db.execute('INSERT INTO episodes(serial,season,number,file_id,kind) VALUES (?,?,?,?,?)',
                                    (data['serial'], data['season'], number, media['file_id'], media['kind'])).lastrowid
                            data['added'].append({'id': identifier, 'number': number, 'old': dict(old) if old else None})
                            self.db.execute("UPDATE episode_queue SET status='saved' WHERE id=?", (item['id'],))
                        data['next'] += 1
                        self.put_upload(user, data)
            except sqlite3.Error:
                self.say(user, 'Saqlanmadi. Raqam o‘zgarmadi. «Davom ettirish»ni bosing yoki qayta yuboring.', keyboard([[('Davom ettirish', 's:resume')]]))
                return
            if conflict:
                self.say(user, f'{number}-qism mavjud. Navbat qaroringizni kutmoqda.', keyboard([[('Almashtirish', f"s:replace:{item['id']}"), ('O‘tkazib yuborish', f"s:skip_episode:{item['id']}")]]))
                return
            skipped = old and decision == 'skip_episode'
            decision = None
            self.say(user, f"{'⏭' if skipped else '✅'} {number}-qism {'o‘tkazildi' if skipped else 'saqlandi'}. Keyingi video — {data['next']}-qism.", self.upload_buttons())

    def show_serial(self, user, serial, season=None, page=0):
        row = self.db.execute('SELECT * FROM serials WHERE id=?', (serial,)).fetchone()
        if not row:
            self.say(user, 'Serial topilmadi.')
            return
        seasons = [r[0] for r in self.db.execute('SELECT DISTINCT season FROM episodes WHERE serial=? ORDER BY season', (serial,))]
        title = f"📺 {row['title']}\nKod: S{serial}\n{row['description']}"
        if season is None and len(seasons) > 1:
            buttons = [[(f'{s}-mavsum', f'v:s:{serial}:{s}')] for s in seasons]
        else:
            season = season or (seasons[0] if seasons else 1)
            page = max(0, page)
            episodes = self.db.execute('SELECT id,number FROM episodes WHERE serial=? AND season=? ORDER BY number LIMIT 13 OFFSET ?', (serial, season, page*12)).fetchall()
            title += f'\n{season}-mavsum' + ('' if episodes else '\nHali qismlar yo‘q.')
            buttons = [[(f"{e['number']}-qism", f"v:e:{e['id']}")] for e in episodes[:12]]
            nav = []
            if page:
                nav.append(('Oldingi sahifa', f'v:s:{serial}:{season}:{page-1}'))
            if len(episodes) > 12:
                nav.append(('Keyingi sahifa', f'v:s:{serial}:{season}:{page+1}'))
            if nav:
                buttons.append(nav)
            if len(seasons) > 1:
                buttons.append([('Mavsumlar', f'v:s:{serial}')])
        markup = keyboard(buttons)
        if row['poster']:
            self.api('sendPhoto', chat_id=user, photo=row['poster'], caption=title, reply_markup=markup)
        else:
            self.say(user, title, markup)

    def deliver_movie(self, user, code):
        if re.fullmatch(r'e[1-9][0-9]*', code):
            return self.deliver_episode(user, int(code[1:]))
        return super().deliver_movie(user, code)

    def deliver_episode(self, user, identifier):
        self.remember(user)
        episode = self.db.execute('SELECT e.*,s.title FROM episodes e JOIN serials s ON s.id=e.serial WHERE e.id=?', (identifier,)).fetchone()
        if not episode:
            self.say(user, 'Qism topilmadi.')
            return
        code = f'e{identifier}'
        with self.db:
            self.db.execute('UPDATE users SET pending_code=? WHERE id=?', (code, user))
        if not self.subscribed(user):
            return
        caption = f"📺 {episode['title']} | {episode['season']}-mavsum | {episode['number']}-qism"
        rows, nav = [], []
        for comparison, ordering, label in (('<', 'DESC', '⏮ Oldingi qism'), ('>', 'ASC', '⏭ Keyingi qism')):
            adjacent = self.db.execute(f'SELECT id FROM episodes WHERE serial=? AND season=? AND number{comparison}? ORDER BY number {ordering} LIMIT 1',
                                      (episode['serial'], episode['season'], episode['number'])).fetchone()
            if adjacent:
                nav.append((label, f'v:e:{adjacent[0]}'))
        if nav:
            rows.append(nav)
        rows.append([('📋 Barcha qismlar', f"v:s:{episode['serial']}:{episode['season']}")])
        markup = keyboard(rows)
        ad = self.setting('movie_ad', {})
        ad_text = ad.get('text', '') if ad.get('enabled') else ''
        combined = caption + ('\n\n' + ad_text if ad_text else '')
        separate = units(combined) > 1024
        if ad_text and ad.get('button'):
            markup['inline_keyboard'].append([ad['button']])
        try:
            markup['inline_keyboard'].append([{'text': '📤 Ulashish', 'url': 'https://t.me/share/url?' + urlencode({'url': self.movie_link(code), 'text': caption})}])
            self.api('sendVideo' if episode['kind'] == 'video' else 'sendDocument', chat_id=user,
                     caption=caption if separate else combined, reply_markup=markup,
                     **{episode['kind']: episode['file_id']})
        except (self.api_error, *NETWORK_ERRORS, ValueError) as exc:
            self.diagnostic('Qism yuborilmadi', exc)
            self.say(user, 'Qismni yuborib bo‘lmadi. Qayta urinib ko‘ring.')
            return
        with self.db:
            self.db.execute('INSERT INTO deliveries(user_id,code) VALUES (?,?)', (user, code))
            self.db.execute('UPDATE users SET pending_code=NULL WHERE id=?', (user,))
        if separate:
            self.say(user, ad_text, {'inline_keyboard': [[ad['button']]]} if ad.get('button') else None)
