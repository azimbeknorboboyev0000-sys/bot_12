import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

from bot import APIError, Bot


class BotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'movies.db'
        self.bot = Bot('0:test', {1, 3}, self.path, -10099)
        self.calls = []
        self.member_status = 'member'
        self.bot_admin = True
        self.failure = None
        self.bot.api = self.api

    def tearDown(self):
        self.bot.stop_worker()
        self.bot.db.close()
        self.directory.cleanup()

    def api(self, method, **data):
        self.calls.append((method, data))
        if self.failure:
            self.failure(method, data)
        if method == 'getMe':
            return {'id': 99, 'username': 'sinov_kino_bot'}
        if method == 'getChat':
            return {'id': -100, 'type': 'channel'}
        if method == 'getChatMember':
            if data['user_id'] == 99:
                return {'status': 'administrator' if self.bot_admin else 'member'}
            return {'status': self.member_status}
        if method == 'forwardMessage':
            return {'video': {'file_id': 'existing-video'}}
        return {'message_id': 10}

    def message(self, user=1, text='', **data):
        self.bot.handle({'chat': {'id': user, 'type': 'private'}, 'from': {'id': user}, 'text': text, **data})

    def callback(self, action, user=1):
        self.bot.process_update({'callback_query': {'id': 'callback', 'from': {'id': user}, 'message': {'chat': {'id': user, 'type': 'private'}}, 'data': action}})

    def movie(self, code='125', source=False):
        values = {'code': code, 'title': 'Sinov kinosi', 'description': 'Asl tavsif', 'kind': 'video', 'file_id': 'video-file'}
        if source:
            values.update(source_chat=-10099, source_message=42)
        self.bot.save_movie(values)

    def channel(self, enabled=1):
        with self.bot.db:
            self.bot.db.execute('INSERT INTO channels (name,chat_id,url,enabled) VALUES (?,?,?,?)', ('Kanal', -100, 'https://t.me/+test', enabled))

    def media_calls(self):
        return [(method, data) for method, data in self.calls if method in ('sendVideo', 'sendDocument', 'copyMessage')]

    def draft(self):
        self.bot.remember(1)
        self.bot.remember(2)
        self.callback('a:broadcast')
        self.message(text='Sinov reklamasi')
        self.message(text='Batafsil | https://example.com')
        return self.bot.db.execute('SELECT * FROM broadcasts ORDER BY id DESC').fetchone()

    def test_non_admin_commands_callbacks_and_steps_denied(self):
        self.movie()
        for command in ('/admin', '/stats', '/delete 125'):
            self.message(2, command)
        for action in ('a:delete_yes', 'a:add', 'a:send:1', 'a:remove:1', 'a:ad_toggle'):
            self.callback(action, 2)
        self.bot.begin(2, 'add')
        self.message(2, '999')
        self.assertIsNone(self.bot.session(2))
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM movies').fetchone()[0], 1)
        self.assertFalse(self.media_calls())

    def test_no_channels_sends_and_counts_movie(self):
        self.movie()
        self.message(2, '125')
        self.assertEqual(len(self.media_calls()), 1)
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0], 1)

    def test_unsubscribed_then_callback_delivers_pending_movie(self):
        self.movie(source=True)
        self.channel()
        self.member_status = 'left'
        self.message(2, '125')
        self.assertFalse(self.media_calls())
        self.assertEqual(self.bot.db.execute('SELECT pending_code FROM users WHERE id=2').fetchone()[0], '125')
        self.member_status = 'member'
        self.callback('subscription', 2)
        self.assertEqual(self.media_calls()[0][0], 'copyMessage')
        self.assertIsNone(self.bot.db.execute('SELECT pending_code FROM users WHERE id=2').fetchone()[0])

    def test_join_request_and_nonmember_restriction_are_not_membership(self):
        self.movie()
        self.channel()
        for status in ('left', 'kicked', 'restricted'):
            self.member_status = status
            self.message(2, '125')
        self.assertFalse(self.media_calls())

    def test_disabled_channel_does_not_block(self):
        self.movie()
        self.channel(0)
        self.member_status = 'left'
        self.message(2, '125')
        self.assertEqual(len(self.media_calls()), 1)

    def test_membership_api_failure_is_not_reported_as_nonmembership(self):
        self.movie()
        self.channel()

        def failure(method, data):
            if method == 'getChatMember' and data['user_id'] == 2:
                raise APIError(500)

        self.failure = failure
        self.message(2, '125')
        self.assertFalse(self.media_calls())
        self.assertIn('hozir tekshirib bo‘lmadi', self.calls[-1][1]['text'])

    def test_channel_requires_bot_admin_and_valid_url(self):
        self.bot_admin = False
        self.callback('a:channel_add')
        self.message(text='Sinov')
        self.message(text='@kanal')
        self.assertEqual(self.bot.session(1)['step'], 'chat')
        self.assertIn('administratori emas', self.calls[-1][1]['text'])
        self.bot_admin = True
        self.message(text='@kanal')
        self.message(text='javascript:alert(1)')
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM channels').fetchone()[0], 0)
        self.message(text='https://t.me/+yopiq')
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM channels').fetchone()[0], 1)

    def test_duplicate_code_never_overwrites(self):
        self.movie()
        self.message(video={'file_id': 'replacement'}, caption='125 | Boshqa')
        self.callback('a:add')
        self.message(text='125')
        self.assertEqual(self.bot.session(1)['step'], 'code')
        self.assertEqual(self.bot.db.execute('SELECT title FROM movies WHERE code=?', ('125',)).fetchone()[0], 'Sinov kinosi')

    def test_add_edit_and_delete_keep_original_channel_message(self):
        self.callback('a:add')
        for text in ('200', 'Yangi kino', 'Tavsif', '-10099 | 42'):
            self.message(text=text)
        self.assertIsNotNone(self.bot.db.execute("SELECT * FROM sources WHERE code='200'").fetchone())
        self.callback('a:edit')
        self.message(text='200')
        self.callback('a:field:title')
        self.message(text='Yangilangan nom')
        self.assertEqual(self.bot.db.execute("SELECT title FROM movies WHERE code='200'").fetchone()[0], 'Yangilangan nom')
        self.message(text='/delete 200')
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM movies').fetchone()[0], 1)
        self.callback('a:delete_yes')
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM movies').fetchone()[0], 0)
        self.assertNotIn('deleteMessage', [method for method, data in self.calls])

    def test_movie_ad_overflow_separate_and_original_preserved(self):
        self.movie()
        self.bot.store_setting('movie_ad', {'text': 'Reklama ' * 200, 'enabled': True, 'button': {'text': 'Havola', 'url': 'https://example.com'}})
        self.message(2, '125')
        self.assertIn('Asl tavsif', self.media_calls()[0][1]['caption'])
        self.assertNotIn('Reklama', self.media_calls()[0][1]['caption'])
        self.assertIn('reply_markup', self.calls[-1][1])
        self.assertEqual(self.bot.db.execute('SELECT description FROM movies').fetchone()[0], 'Asl tavsif')

    def test_short_movie_ad_uses_caption(self):
        self.movie()
        self.bot.store_setting('movie_ad', {'text': 'Reklama', 'enabled': True})
        self.message(2, '125')
        self.assertIn('Asl tavsif\n\nReklama', self.media_calls()[0][1]['caption'])

    def test_draft_not_sent_until_confirmation_and_confirm_is_idempotent(self):
        draft = self.draft()
        self.assertEqual(draft['status'], 'draft')
        self.assertFalse([data for method, data in self.calls if data.get('chat_id') == 2])
        self.assertEqual(self.bot.db.execute("SELECT COUNT(*) FROM broadcasts WHERE status IN ('queued','running')").fetchone()[0], 0)
        self.callback(f"a:send:{draft['id']}", 3)
        self.assertEqual(self.bot.db.execute('SELECT status FROM broadcasts').fetchone()[0], 'draft')
        self.callback(f"a:send:{draft['id']}")
        self.callback(f"a:send:{draft['id']}")
        self.assertEqual(self.bot.db.execute('SELECT status FROM broadcasts').fetchone()[0], 'queued')
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM broadcasts').fetchone()[0], 1)

    def test_cancel_and_back_invalidate_draft(self):
        draft = self.draft()
        self.callback('a:back')
        self.assertEqual(self.bot.session(1)['step'], 'button')
        self.callback(f"a:send:{draft['id']}")
        self.assertEqual(self.bot.db.execute('SELECT status FROM broadcasts').fetchone()[0], 'cancelled')

    def test_broadcast_worker_retries_rate_limit_and_continues_blocked_users(self):
        draft = self.draft()
        self.bot.remember(4)
        with self.bot.db:
            self.bot.db.execute('UPDATE users SET active=0 WHERE id=4')
            self.bot.db.execute('INSERT INTO recipients (broadcast_id,user_id) VALUES (?,4)', (draft['id'],))
        self.callback(f"a:send:{draft['id']}")
        attempts = []

        def failure(method, data):
            if method == 'sendMessage' and data.get('text') == 'Sinov reklamasi':
                if data['chat_id'] == 1 and not attempts:
                    attempts.append(1)
                    raise APIError(429, 2)
                if data['chat_id'] == 2:
                    raise APIError(403)

        self.failure = failure
        original_stop = self.bot.worker_stop
        self.bot.worker_stop = Mock()
        self.bot.worker_stop.is_set.return_value = False
        self.bot.worker_stop.wait.return_value = False
        job = self.bot.db.execute('SELECT * FROM broadcasts').fetchone()
        self.bot.run_broadcast(self.bot.db, job)
        counts = dict(self.bot.db.execute('SELECT status,COUNT(*) FROM recipients GROUP BY status').fetchall())
        self.assertEqual(counts, {'success': 1, 'failed': 1, 'skipped': 1})
        self.assertEqual(self.bot.db.execute('SELECT active FROM users WHERE id=2').fetchone()[0], 0)
        self.bot.worker_stop.wait.assert_any_call(2)
        self.bot.worker_stop = original_stop
        self.bot.report_broadcast(self.bot.db, job)
        self.assertIn('Muvaffaqiyatli: 1', self.calls[-1][1]['text'])

    def test_restart_retains_settings_sessions_channels_and_pending_movie(self):
        self.movie()
        self.channel()
        self.member_status = 'left'
        self.message(2, '125')
        self.bot.store_setting('movie_ad', {'text': 'Saqlangan', 'enabled': True})
        self.callback('a:add')
        self.message(text='900')
        self.bot.db.close()
        self.bot = Bot('0:test', {1, 3}, self.path, -10099)
        self.bot.api = self.api
        self.assertEqual(self.bot.setting('movie_ad')['text'], 'Saqlangan')
        self.assertEqual(self.bot.session(1)['step'], 'title')
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM channels').fetchone()[0], 1)
        self.member_status = 'member'
        self.callback('subscription', 2)
        self.assertEqual(len(self.media_calls()), 1)

    def test_legacy_schema_migration_preserves_movies_sources_and_offset(self):
        path = Path(self.directory.name) / 'legacy.db'
        with sqlite3.connect(path) as connection:
            connection.executescript("CREATE TABLE movies(code TEXT PRIMARY KEY,title TEXT,file_id TEXT,kind TEXT); INSERT INTO movies VALUES('001','Eski kino','old','video'); CREATE TABLE sources(code TEXT PRIMARY KEY,chat_id INTEGER,message_id INTEGER,UNIQUE(chat_id,message_id)); INSERT INTO sources VALUES('001',-10099,42); CREATE TABLE state(key TEXT PRIMARY KEY,value INTEGER); INSERT INTO state VALUES('offset',123);")
        connection.close()
        migrated = Bot('0:test', {1}, path)
        try:
            self.assertEqual(migrated.db.execute('SELECT title,description FROM movies').fetchone()[:], ('Eski kino', ''))
            self.assertEqual(migrated.db.execute('SELECT value FROM state').fetchone()[0], 123)
            self.assertEqual(migrated.db.execute('SELECT message_id FROM sources').fetchone()[0], 42)
        finally:
            migrated.db.close()

    def test_channel_ingestion_and_edit_preserve_duplicate_protection(self):
        post = {'chat': {'id': -10099}, 'message_id': 42, 'video': {'file_id': 'channel-video'}, 'caption': '125 | Kino | Tavsif'}
        self.bot.process_update({'channel_post': post})
        self.bot.process_update({'edited_channel_post': {**post, 'caption': '125 | Yangi nom | Yangi tavsif'}})
        self.bot.process_update({'channel_post': {**post, 'message_id': 43, 'caption': '125 | Begona'}})
        self.assertEqual(self.bot.db.execute('SELECT title FROM movies').fetchone()[0], 'Yangi nom')
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM movies').fetchone()[0], 1)

    def test_failed_movie_send_does_not_increment_stats(self):
        self.movie()

        def failure(method, data):
            if method == 'sendVideo':
                raise APIError(400)

        self.failure = failure
        self.message(2, '125')
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0], 0)

    def test_every_movie_transport_and_start_link_require_membership(self):
        self.movie('125')
        self.movie('126', source=True)
        self.channel()
        self.member_status = 'left'
        for text in ('125', '126', '/start 125'):
            self.message(2, text)
        self.assertFalse(self.media_calls())

    def test_all_active_channels_are_required(self):
        self.movie()
        self.channel()
        with self.bot.db:
            self.bot.db.execute('INSERT INTO channels (name,chat_id,url) VALUES (?,?,?)', ('Ikkinchi', -200, 'https://t.me/second'))
        original_api = self.bot.api

        def second_channel(method, **data):
            if method == 'getChat':
                return {'id': data['chat_id'], 'type': 'channel'}
            if method == 'getChatMember' and data['chat_id'] == -200 and data['user_id'] == 2:
                return {'status': 'left'}
            return original_api(method, **data)

        self.bot.api = second_channel
        self.message(2, '125')
        self.assertFalse(self.media_calls())
        self.assertIn('Ikkinchi', str(self.calls[-1]))

    def test_text_channel_message_cannot_be_added_as_movie(self):
        original_api = self.bot.api

        def no_video(method, **data):
            if method == 'forwardMessage':
                return {'text': 'Video emas'}
            return original_api(method, **data)

        self.bot.api = no_video
        self.callback('a:add')
        for text in ('125', 'Kino', '-', '-10099 | 42'):
            self.message(text=text)
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM movies').fetchone()[0], 0)
        self.assertEqual(self.bot.session(1)['step'], 'media')

    def test_back_cancel_commands_do_not_send_invalid_callback_ack(self):
        self.callback('a:add')
        self.message(text='125')
        self.message(text='/back')
        self.assertEqual(self.bot.session(1)['step'], 'code')
        self.message(text='/cancel')
        self.assertIsNone(self.bot.session(1))
        self.assertFalse([data for method, data in self.calls if method == 'answerCallbackQuery' and data['callback_query_id'] == 'local'])

    def test_background_worker_resumes_queue_and_skips_uncertain_delivery(self):
        draft = self.draft()
        self.callback(f"a:send:{draft['id']}")
        with self.bot.db:
            self.bot.db.execute("UPDATE recipients SET status='sending' WHERE user_id=1")
            self.bot.db.execute("UPDATE broadcasts SET status='running'")
        finished = threading.Event()
        original_api = self.bot.api

        def notify(method, **data):
            result = original_api(method, **data)
            if method == 'sendMessage' and 'Reklama tarqatish yakunlandi.' in data.get('text', ''):
                finished.set()
            return result

        self.bot.api = notify
        self.bot.worker = threading.Thread(target=self.bot.broadcast_loop, daemon=True)
        self.bot.worker.start()
        self.assertTrue(finished.wait(5))
        self.bot.stop_worker()
        counts = dict(self.bot.db.execute('SELECT status,COUNT(*) FROM recipients GROUP BY status').fetchall())
        self.assertEqual(counts, {'success': 1, 'skipped': 1})
        delivered = [data for method, data in self.calls if method == 'sendMessage' and data.get('text') == 'Sinov reklamasi']
        self.assertEqual([data['chat_id'] for data in delivered], [1, 2])

    def test_photo_and_video_broadcast_preview(self):
        for kind in ('photo', 'video'):
            self.callback('a:broadcast')
            media = {'file_id': 'ad-file'}
            self.message(**{kind: [media] if kind == 'photo' else media}, caption='Media reklamasi')
            self.message(text='-')
            self.assertEqual(self.calls[-2][0], 'sendPhoto' if kind == 'photo' else 'sendVideo')
            self.assertEqual(self.bot.db.execute('SELECT status FROM broadcasts ORDER BY id DESC LIMIT 1').fetchone()[0], 'draft')
            self.callback('a:cancel')

    def test_admin_authority_rechecked_after_id_is_removed(self):
        self.callback('a:add')
        self.bot.admins.remove(1)
        self.message(text='125')
        self.assertIsNone(self.bot.session(1))
        self.assertIn('faqat admin', self.calls[-1][1]['text'])

    def test_slow_broadcast_does_not_block_movie_requests(self):
        self.movie()
        draft = self.draft()
        self.callback(f"a:send:{draft['id']}")
        sending = threading.Event()
        release = threading.Event()
        original_api = self.bot.api

        def slow_ad(method, **data):
            if method == 'sendMessage' and data.get('text') == 'Sinov reklamasi':
                sending.set()
                release.wait(5)
            return original_api(method, **data)

        self.bot.api = slow_ad
        self.bot.worker = threading.Thread(target=self.bot.broadcast_loop, daemon=True)
        self.bot.worker.start()
        try:
            self.assertTrue(sending.wait(5))
            self.message(3, '125')
            self.assertEqual(self.media_calls()[0][1]['chat_id'], 3)
        finally:
            release.set()
            self.bot.stop_worker()

    def test_start_link_sends_same_movie_without_extra_menu(self):
        self.movie('8')
        self.message(2, '/start 8')
        self.assertEqual(len(self.media_calls()), 1)
        self.assertIn('Kod: 8', self.media_calls()[0][1]['caption'])
        self.assertFalse([data for method, data in self.calls if method == 'sendMessage'])

    def test_start_link_preserves_leading_zeroes_and_bot_mention(self):
        self.movie('008')
        self.message(2, '/start@sinov_kino_bot 008')
        self.assertIn('Kod: 008', self.media_calls()[0][1]['caption'])

    def test_start_link_pending_movie_is_sent_after_subscription(self):
        self.movie('8', source=True)
        self.channel()
        self.member_status = 'left'
        self.message(2, '/start 8')
        self.assertFalse(self.media_calls())
        self.assertEqual(self.bot.db.execute('SELECT pending_code FROM users WHERE id=2').fetchone()[0], '8')
        self.member_status = 'member'
        self.callback('subscription', 2)
        self.assertEqual(self.media_calls()[0][0], 'copyMessage')
        self.assertIn('Kod: 8', self.media_calls()[0][1]['caption'])

    def test_start_without_code_keeps_greeting(self):
        self.message(2, '/start')
        self.assertIn('Kino kodini yuboring', self.calls[-1][1]['text'])
        self.assertFalse(self.media_calls())

    def test_start_invalid_and_missing_movie_codes(self):
        for text in ('/start abc', '/start 8 9', '/start -8', '/start 1234567890123'):
            self.message(2, text)
            self.assertIn('kino kodi noto‘g‘ri', self.calls[-1][1]['text'])
        self.message(2, '/start 999')
        self.assertIn('kino topilmadi', self.calls[-1][1]['text'])
        self.assertFalse(self.media_calls())

    def test_admin_add_methods_return_ready_movie_link(self):
        self.message(video={'file_id': 'new'}, caption='008 | Yangi kino')
        self.assertIn('https://t.me/sinov_kino_bot?start=008', self.calls[-1][1]['text'])
        self.callback('a:add')
        for text in ('9', 'Panel kinosi', '-', '-10099 | 42'):
            self.message(text=text)
        self.assertTrue(any('https://t.me/sinov_kino_bot?start=9' in data.get('text', '') for method, data in self.calls))
        self.bot.channel_post({'chat': {'id': -10099}, 'message_id': 43, 'video': {'file_id': 'channel-video'}, 'caption': '10 | Kanal kinosi'})
        self.assertIn('https://t.me/sinov_kino_bot?start=10', self.calls[-1][1]['text'])

    def test_username_api_failure_does_not_undo_saved_movie(self):
        def failure(method, data):
            if method == 'getMe':
                raise APIError(500)

        self.failure = failure
        self.message(video={'file_id': 'new'}, caption='8 | Yangi kino')
        self.assertEqual(self.bot.db.execute("SELECT title FROM movies WHERE code='8'").fetchone()[0], 'Yangi kino')
        self.assertIn('Kino saqlangan', self.calls[-1][1]['text'])

    def test_share_button_encodes_movie_link_and_exact_text(self):
        title = 'O‘zbek & kino? #1 + 🎥'
        self.bot.save_movie({'code': '008', 'title': title, 'kind': 'video', 'file_id': 'video'})
        self.message(2, '008')
        button = self.media_calls()[0][1]['reply_markup']['inline_keyboard'][-1][0]
        self.assertEqual(button['text'], '📤 Ulashish')
        parsed = urlparse(button['url'])
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path), ('https', 't.me', '/share/url'))
        self.assertEqual(parse_qs(parsed.query), {
            'url': ['https://t.me/sinov_kino_bot?start=008'],
            'text': [f'🎬 {title}\n🍿 Kinoni bot orqali tomosha qiling!']})

    def test_share_button_present_for_code_start_and_subscription_transports(self):
        for kind in ('video', 'document', 'source'):
            for entry in ('code', 'start', 'subscription'):
                with self.subTest(kind=kind, entry=entry):
                    code = str(1000 + len(self.calls))
                    values = {'code': code, 'title': 'Kino', 'file_id': 'video', 'kind': 'document' if kind == 'document' else 'video'}
                    if kind == 'source':
                        values.update(source_chat=-10099, source_message=int(code))
                    self.bot.save_movie(values)
                    if entry == 'subscription':
                        self.bot.remember(2)
                        with self.bot.db:
                            self.bot.db.execute('UPDATE users SET pending_code=? WHERE id=2', (code,))
                        self.callback('subscription', 2)
                    else:
                        self.message(2, f'/start {code}' if entry == 'start' else code)
                    button = self.media_calls()[-1][1]['reply_markup']['inline_keyboard'][-1][0]
                    self.assertEqual(parse_qs(urlparse(button['url']).query)['url'], [f'https://t.me/sinov_kino_bot?start={code}'])

    def test_share_button_keeps_ad_button_on_separate_row(self):
        self.movie()
        ad_button = {'text': 'Reklama havolasi', 'url': 'https://example.com'}
        self.bot.store_setting('movie_ad', {'enabled': True, 'text': 'Reklama', 'button': ad_button})
        self.message(2, '125')
        rows = self.media_calls()[0][1]['reply_markup']['inline_keyboard']
        self.assertEqual(rows[0], [ad_button])
        self.assertEqual(rows[1][0]['text'], '📤 Ulashish')
        original = {'inline_keyboard': [[ad_button], [{'text': 'Boshqa tugma', 'callback_data': 'other'}]]}
        merged = self.bot.movie_markup('125', 'Kino', original)
        self.assertEqual(merged['inline_keyboard'][:-1], original['inline_keyboard'])
        self.assertEqual(len(original['inline_keyboard']), 2)

    def test_share_button_stays_under_video_when_ad_is_separate(self):
        self.movie()
        ad_button = {'text': 'Reklama', 'url': 'https://example.com'}
        self.bot.store_setting('movie_ad', {'enabled': True, 'text': 'Reklama ' * 200, 'button': ad_button})
        self.message(2, '125')
        self.assertEqual(self.media_calls()[0][1]['reply_markup']['inline_keyboard'][-1][0]['text'], '📤 Ulashish')
        self.assertEqual(self.calls[-1][1]['reply_markup']['inline_keyboard'], [[ad_button]])

    def test_shared_link_recipient_must_subscribe_before_movie_with_share_button(self):
        self.movie('8')
        self.message(2, '8')
        shared = self.media_calls()[-1][1]['reply_markup']['inline_keyboard'][-1][0]['url']
        deep_link = parse_qs(urlparse(shared).query)['url'][0]
        code = parse_qs(urlparse(deep_link).query)['start'][0]
        self.channel()
        self.member_status = 'left'
        before = len(self.media_calls())
        self.message(4, f'/start {code}')
        self.assertEqual(len(self.media_calls()), before)
        self.member_status = 'member'
        self.callback('subscription', 4)
        self.assertEqual(len(self.media_calls()), before + 1)
        self.assertEqual(self.media_calls()[-1][1]['chat_id'], 4)
        self.assertEqual(self.media_calls()[-1][1]['reply_markup']['inline_keyboard'][-1][0]['text'], '📤 Ulashish')

    def test_video_document_uses_same_subscription_gate(self):
        self.bot.save_movie({'code': '300', 'title': 'Video fayl', 'file_id': 'document-id', 'kind': 'document'})
        self.channel()
        self.member_status = 'left'
        self.message(2, '300')
        self.assertFalse(self.media_calls())
        self.member_status = 'member'
        self.callback('subscription', 2)
        self.assertEqual(self.media_calls()[0][0], 'sendDocument')


if __name__ == '__main__':
    unittest.main()
