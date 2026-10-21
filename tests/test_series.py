from test_bot import BotTests
from bot import Bot
from urllib.parse import parse_qs, urlparse
import unittest
from unittest.mock import patch


class SeriesTests(BotTests):
    def create(self):
        self.callback('s:new')
        self.message(text='Arkeyn')
        self.callback('s:skip')
        self.callback('s:skip')

    def video(self, message_id, **extra):
        self.message(message_id=message_id, video={'file_id': f'video-{message_id}'}, **extra)

    def episodes(self):
        return self.bot.db.execute('SELECT * FROM episodes ORDER BY number').fetchall()

    def test_series_sequential_album_duplicate_and_invalid(self):
        self.create()
        self.message(text='Oddiy xabar', message_id=1)
        self.message(document={'file_id': 'bad', 'mime_type': 'application/pdf'}, message_id=2)
        self.assertEqual(self.bot.upload(1)['next'], 1)
        for n in range(3, 13):
            self.video(n, media_group_id='album')
        self.video(3)
        self.assertEqual([r['number'] for r in self.episodes()], list(range(1, 11)))
        self.assertEqual([r['file_id'] for r in self.episodes()], [f'video-{n}' for n in range(3, 13)])

    def test_series_conflict_queue_skip_and_stale_decision(self):
        self.create()
        self.video(1)
        self.callback('s:number')
        self.message(text='1')
        self.video(2)
        self.video(3)
        self.assertEqual(len(self.episodes()), 1)
        item = self.bot.db.execute("SELECT id FROM episode_queue WHERE status='pending' ORDER BY id").fetchone()[0]
        self.callback(f's:skip_episode:{item}')
        self.assertEqual([(r['number'], r['file_id']) for r in self.episodes()], [(1, 'video-1'), (2, 'video-3')])
        self.callback(f's:replace:{item}')
        self.assertEqual(len(self.episodes()), 2)

    def test_series_replace_undo_finish_and_append(self):
        self.create()
        self.video(1)
        self.callback('s:finish')
        self.callback('s:add:1')
        self.assertEqual(self.bot.upload(1)['next'], 2)
        self.callback('s:number')
        self.message(text='1')
        self.video(2)
        item = self.bot.db.execute("SELECT id FROM episode_queue WHERE status='pending'").fetchone()[0]
        self.callback(f's:replace:{item}')
        self.assertEqual(self.episodes()[0]['file_id'], 'video-2')
        self.callback('s:undo')
        self.assertEqual(self.episodes()[0]['file_id'], 'video-1')
        self.video(3)
        item = self.bot.db.execute("SELECT id FROM episode_queue WHERE status='pending'").fetchone()[0]
        self.callback(f's:skip_episode:{item}')
        self.video(4)
        self.callback('s:undo')
        self.assertEqual(len(self.episodes()), 1)
        self.assertFalse([m for m, _ in self.calls if m == 'deleteMessage'])

    def test_series_restart_pending_queue_and_subscription_exact_episode(self):
        self.create()
        self.video(1)
        self.bot.db.close()
        self.bot = Bot('0:test', {1, 3}, self.path, -10099)
        self.bot.api = self.api
        self.message(text='/admin')
        self.assertIn('Davom ettirish', str(self.calls[-1]))
        self.callback('s:resume')
        self.video(2)
        self.channel()
        self.member_status = 'left'
        self.message(2, '/start e2')
        self.assertFalse(self.media_calls())
        self.member_status = 'member'
        self.callback('subscription', 2)
        sent = self.media_calls()[-1][1]
        self.assertEqual(sent['video'], 'video-2')
        rows = sent['reply_markup']['inline_keyboard']
        self.assertIn('Oldingi qism', str(rows))
        self.assertNotIn('Keyingi qism', str(rows))
        self.assertEqual(parse_qs(urlparse(rows[-1][0]['url']).query)['url'], ['https://t.me/sinov_kino_bot?start=e2'])

    def test_series_database_failure_rolls_back_number_and_retries(self):
        self.create()
        self.bot.db.execute("CREATE TRIGGER fail_episode BEFORE INSERT ON episodes BEGIN SELECT RAISE(ABORT,'test'); END")
        self.video(1)
        self.assertEqual(self.bot.upload(1)['next'], 1)
        self.assertEqual(len(self.episodes()), 0)
        self.bot.db.execute('DROP TRIGGER fail_episode')
        self.callback('s:resume')
        self.assertEqual(self.bot.upload(1)['next'], 2)
        self.assertEqual(len(self.episodes()), 1)

    def test_series_document_admin_permissions_and_seasons(self):
        self.create()
        self.message(message_id=1, document={'file_id': 'doc', 'mime_type': 'video/mp4'})
        self.callback('s:finish')
        self.callback('s:newseason:1')
        self.assertEqual(self.bot.upload(1)['season'], 2)
        self.video(2)
        self.message(2, 'S1')
        self.assertIn('mavsum', str(self.calls[-1]))
        self.callback('v:e:1', 2)
        self.assertEqual(self.media_calls()[-1][0], 'sendDocument')
        self.callback('s:undo', 2)
        self.assertEqual(len(self.episodes()), 2)
        self.bot.admins.remove(1)
        self.video(3)
        self.assertEqual(len(self.episodes()), 2)

    def test_series_pagination_and_ad_buttons(self):
        self.create()
        for n in range(1, 15):
            self.video(n)
        self.message(2, 'S1')
        self.assertIn('Keyingi sahifa', str(self.calls[-1]))
        self.assertNotIn('Mavsumlar', str(self.calls[-1]))
        self.bot.store_setting('movie_ad', {'enabled': True, 'text': 'Reklama', 'button': {'text': 'Reklama', 'url': 'https://example.com'}})
        self.callback('v:e:1', 2)
        sent = self.media_calls()[-1][1]
        self.assertIn('Reklama', sent['caption'])
        self.assertIn('https://example.com', str(sent['reply_markup']))
        self.assertNotIn('Oldingi qism', str(sent['reply_markup']))

    def test_series_movie_admin_flow_remains_available(self):
        self.create()
        self.message(text='/admin')
        self.callback('a:add')
        for text in ('125', 'Kino', '-'):
            self.message(text=text)
        self.message(video={'file_id': 'movie'})
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM movies').fetchone()[0], 1)
        self.callback('s:resume')
        self.video(50)
        self.assertEqual(len(self.episodes()), 1)

    def test_series_replayed_update_and_restart_blocked_queue(self):
        self.create()
        update = {'update_id': 100, 'message': {'chat': {'id': 1, 'type': 'private'},
                  'from': {'id': 1}, 'message_id': 30, 'video': {'file_id': 'first'}}}
        self.bot.process_update(update)
        self.bot.process_update(update)
        self.assertEqual(len(self.episodes()), 1)
        self.callback('s:number')
        self.message(text='1')
        self.video(31)
        self.video(32)
        self.bot.db.close()
        self.bot = Bot('0:test', {1, 3}, self.path)
        self.bot.api = self.api
        self.callback('s:resume')
        item = self.bot.db.execute("SELECT id FROM episode_queue WHERE status='pending' ORDER BY id").fetchone()[0]
        self.callback(f's:skip_episode:{item}')
        self.assertEqual([r['file_id'] for r in self.episodes()], ['first', 'video-32'])

    def test_series_startup_offers_resume(self):
        self.create()
        with patch('management.ManagementMixin.run') as polling:
            self.bot.run()
        polling.assert_called_once()
        self.assertIn('Davom ettirish', str(self.calls[-1]))
        self.assertIn('Yakunlash', str(self.calls[-1]))


def load_tests(loader, tests, pattern):
    # Reuse the existing API fixture without running inherited movie tests twice.
    return unittest.TestSuite(SeriesTests(name) for name in SeriesTests.__dict__ if name.startswith('test_'))
