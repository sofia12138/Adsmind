import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pydantic import ValidationError
from fastapi import HTTPException
from unittest.mock import patch
from services import distribution_service as s


class ValidationTests(unittest.TestCase):
    def test_schedule_requires_future_timezone_aware_time(self):
        for date in (None, datetime.now(), datetime.now(timezone.utc)-timedelta(hours=1)):
            with self.assertRaises(ValidationError):
                s.DraftInput(drama_name='剧', publish_mode='scheduled', scheduled_at=date)
        s.DraftInput(drama_name='剧', publish_mode='scheduled', scheduled_at=datetime.now(timezone.utc)+timedelta(days=1))

    def test_draft_cannot_inject_platform_status_and_invalid_thumbnail(self):
        row = s.DraftInput(drama_name='剧', status='PUBLISHED')
        self.assertNotIn('status', row.model_dump())
        for url in ('javascript:alert(1)', 'https://user:secret@example.com/image'):
            with self.assertRaises(ValidationError):
                s.DraftInput(drama_name='剧', thumbnail_url=url)

    def test_channel_identifier_timezone_and_blank_name(self):
        for args in ({'name': ' ', 'channel_id': 'UC'+'a'*22, 'language': 'en'},
                     {'name': 'A', 'channel_id': '@name', 'language': 'en'},
                     {'name': 'A', 'channel_id': 'UC'+'a'*22, 'language': 'en', 'timezone': 'Invalid/Zone'}):
            with self.assertRaises(ValidationError):
                s.ChannelInput(**args)

    def test_precheck_never_claims_upload_ready(self):
        payload = s.DraftInput(drama_name='剧', file_name='movie.mp4', title='Title', description='Desc', language='en', audience='general', full_drama_confirmed=True, rights_confirmed=True).model_dump(mode='json')
        with patch.object(s, 'channels', return_value=[]):
            report = s.precheck({'payload': payload}, None)
        self.assertFalse(report['ok'])
        self.assertFalse(report['checks'][-1]['ok'])

    def test_read_and_write_permissions_are_enforced(self):
        from routes.distribution import reader, writer
        user = SimpleNamespace(username='test', role='viewer')
        with patch('services.panel_service.resolve_allowed_panels', return_value=[]):
            with self.assertRaises(HTTPException):
                reader(user)
        with patch('services.panel_service.resolve_allowed_panels', return_value=['creatives']):
            self.assertEqual(reader(user), user)
        with self.assertRaises(HTTPException):
            writer(user)


@unittest.skipUnless(os.environ.get('ADSMIND_INTEGRATION_TESTS') == '1', 'Requires local database')
class StorageTests(unittest.TestCase):
    def setUp(self):
        from repositories import application_repository, tenant_repository
        self.prefix = 'distribution-test-'+uuid.uuid4().hex
        tenant_a = tenant_repository.create(
            slug=self.prefix+'-a', name='Distribution test A', plan_id='pro'
        )
        tenant_b = tenant_repository.create(
            slug=self.prefix+'-b', name='Distribution test B', plan_id='pro'
        )
        app_a = application_repository.create(tenant_a['id'], 'Application A', is_default=True)
        app_a2 = application_repository.create(tenant_a['id'], 'Application A2')
        app_b = application_repository.create(tenant_b['id'], 'Application B', is_default=True)
        self.tenant_ids = (tenant_a['id'], tenant_b['id'])
        self.a = SimpleNamespace(tenant_id=tenant_a['id'], id=app_a['id'])
        self.other_app = SimpleNamespace(tenant_id=tenant_a['id'], id=app_a2['id'])
        self.other_tenant = SimpleNamespace(tenant_id=tenant_b['id'], id=app_b['id'])
        self.user = SimpleNamespace(username='_distribution_test')

    def tearDown(self):
        from db import get_app_conn
        with get_app_conn() as conn:
            cur = conn.cursor()
            for table in ('app_distribution_drafts', 'app_distribution_channels'):
                for tenant_id in self.tenant_ids:
                    cur.execute(f'DELETE FROM {table} WHERE tenant_id=%s', (tenant_id,))
            for tenant_id in self.tenant_ids:
                cur.execute('DELETE FROM app_applications WHERE tenant_id=%s', (tenant_id,))
                cur.execute('DELETE FROM app_tenants WHERE id=%s', (tenant_id,))
            conn.commit()

    def test_persistence_revision_and_cross_scope_isolation(self):
        channel = s.create_channel(s.ChannelInput(name='Test', channel_id='UC'+uuid.uuid4().hex[:22], language='en'), self.a)
        self.assertEqual(channel['authorization_status'], 'NOT_CONNECTED')
        row = s.save(s.DraftInput(drama_name='整剧', channel_id=channel['id']), self.a, self.user)
        self.assertEqual(s.load(row['id'], self.a)['payload']['drama_name'], '整剧')
        self.assertEqual(s.list_drafts(self.a, 1)['total'], 1)
        updated = s.save(s.DraftUpdate(**{**row['payload'], 'title': 'Title'}, revision=1), self.a, self.user, row['id'])
        self.assertEqual(updated['revision'], 2)
        with self.assertRaises(HTTPException):
            s.save(s.DraftUpdate(**row['payload'], revision=1), self.a, self.user, row['id'])
        for scope in (self.other_app, self.other_tenant):
            self.assertEqual(s.list_drafts(scope, 1)['total'], 0)
            self.assertEqual(s.channels(scope), [])
            with self.assertRaises(HTTPException):
                s.load(row['id'], scope)
            with self.assertRaises(HTTPException):
                s.save(s.DraftInput(drama_name='other', channel_id=channel['id']), scope, self.user)
