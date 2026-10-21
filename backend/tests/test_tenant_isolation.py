import os
import uuid
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from core.isolation import (
    Scope,
    ScopeNotBoundError,
    current_scope,
    scoped_object_path,
    scoped_sql,
    scope_cache_key,
    tenant_id,
)


class SQLBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.token = current_scope.set(Scope(42))

    def tearDown(self):
        current_scope.reset(self.token)

    def test_parenthesized_or_cannot_escape_scope(self):
        sql = scoped_sql('SELECT * FROM app_templates WHERE name=%s OR platform=%s ORDER BY id LIMIT %s', 'app_templates')
        self.assertIn('WHERE tenant_id = 42 AND (name=%s OR platform=%s) ORDER BY', sql)

    def test_count_insert_update_and_delete_are_scoped(self):
        for sql in ('SELECT COUNT(*) FROM app_templates', 'UPDATE app_templates SET name=%s WHERE tpl_id=%s', 'DELETE FROM app_templates WHERE tpl_id=%s'):
            self.assertIn('tenant_id = 42', scoped_sql(sql, 'app_templates'))
        self.assertIn('(tenant_id, name) VALUES (42, %s)', scoped_sql('INSERT INTO app_templates (name) VALUES (%s)', 'app_templates'))

    def test_compound_and_foreign_queries_fail_closed(self):
        for sql in ('SELECT * FROM app_templates UNION SELECT * FROM app_users', 'SELECT * FROM app_users', 'SELECT * FROM app_templates; DELETE FROM app_templates'):
            with self.assertRaises(ValueError):
                scoped_sql(sql, 'app_templates')


class ScopeContractTests(unittest.TestCase):
    def test_internal_route_prefixes_do_not_capture_customer_catalog_routes(self):
        source = Path(__file__).parents[1].joinpath("core/isolation.py").read_text(encoding="utf-8")
        self.assertIn("scope['path'] == prefix", source)
        self.assertIn("scope['path'].startswith(prefix + '/')", source)

    def test_missing_scope_never_defaults_to_internal_tenant(self):
        self.assertIsNone(current_scope.get())
        with self.assertRaises(ScopeNotBoundError):
            tenant_id()

    def test_cache_and_object_paths_include_both_ownership_levels(self):
        token = current_scope.set(Scope(42, 73))
        try:
            self.assertEqual(
                scope_cache_key('uploads', 'record-1'),
                'uploads:tenant:42:application:73:record-1',
            )
            self.assertEqual(
                scoped_object_path('materials', 'video.mp4'),
                'materials/tenants/42/applications/73/video.mp4',
            )
        finally:
            current_scope.reset(token)

    def test_account_backed_business_rows_are_application_scoped(self):
        token = current_scope.set(Scope(42, 73))
        try:
            sql = scoped_sql('SELECT * FROM biz_campaigns', 'biz_campaigns')
            self.assertIn('tenant_id = 42', sql)
            self.assertIn('application_id = 73', sql)
        finally:
            current_scope.reset(token)

    def test_application_owned_crud_injects_and_filters_both_scope_columns(self):
        token = current_scope.set(Scope(42, 73))
        try:
            inserted = scoped_sql(
                'INSERT INTO app_account_groups (name, account_refs) VALUES (%s, %s)',
                'app_account_groups',
            )
            self.assertIn(
                '(tenant_id, application_id, name, account_refs) VALUES (42, 73, %s, %s)',
                inserted,
            )
            for statement in (
                'SELECT * FROM app_account_groups WHERE id=%s',
                'UPDATE app_account_groups SET name=%s WHERE id=%s',
                'DELETE FROM app_account_groups WHERE id=%s',
            ):
                scoped = scoped_sql(statement, 'app_account_groups')
                self.assertIn('tenant_id = 42', scoped)
                self.assertIn('application_id = 73', scoped)
        finally:
            current_scope.reset(token)

    def test_migration_plan_is_reviewable_and_has_a_reversible_scope_step(self):
        from migrations.runner import plan
        rows = plan()
        self.assertEqual([row['version'] for row in rows], sorted(row['version'] for row in rows))
        self.assertTrue(any(row['reversible'] for row in rows))
        self.assertTrue(all(len(row['checksum']) == 64 for row in rows))

    def test_account_upsert_guards_every_duplicate_update_with_both_scopes(self):
        from core.isolation import bound_scope
        from repositories import biz_account_repository
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = {
            'id': 9, 'tenant_id': 42, 'application_id': 73,
        }
        manager = MagicMock()
        manager.__enter__.return_value = conn
        manager.__exit__.return_value = False
        with patch.object(biz_account_repository, 'get_biz_conn', return_value=manager):
            with bound_scope(Scope(42, 73)):
                self.assertEqual(
                    biz_account_repository.upsert(
                        platform='tiktok', account_id='account-a', app_secret='secret'
                    ),
                    9,
                )
        upsert_sql = cursor.execute.call_args_list[0].args[0]
        self.assertIn('ON DUPLICATE KEY UPDATE', upsert_sql)
        self.assertGreaterEqual(
            upsert_sql.count('application_id = VALUES(application_id)'), 9
        )
        for column in ('currency', 'timezone', 'status', 'app_id', 'app_secret', 'raw_json'):
            self.assertIn(f'{column}', upsert_sql)
            self.assertIn(f'VALUES({column})', upsert_sql)

    def test_application_resource_migration_resumes_a_valid_partial_run(self):
        from migrations.versions import v0003_application_resources as migration

        class Cursor:
            def __init__(self):
                self.tables = {'app_account_groups'}
                self.rows = []

            def execute(self, sql, args=None):
                normalized = ' '.join(sql.split())
                if 'INFORMATION_SCHEMA.TABLES' in normalized:
                    self.rows = [{'TABLE_NAME': table} for table in sorted(self.tables)]
                elif 'INFORMATION_SCHEMA.COLUMNS' in normalized:
                    table = args[0]
                    self.rows = [
                        {'COLUMN_NAME': column}
                        for column in sorted(migration._REQUIRED_COLUMNS[table])
                    ]
                elif 'INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS' in normalized:
                    self.rows = [{'CONSTRAINT_NAME': args[1]}]
                elif normalized.startswith('CREATE TABLE IF NOT EXISTS'):
                    self.tables.add(normalized.split()[5])
                    self.rows = []
                else:
                    self.rows = []

            def fetchall(self):
                return list(self.rows)

            def fetchone(self):
                return self.rows[0] if self.rows else None

        cursor = Cursor()
        conn = MagicMock()
        conn.cursor.return_value = cursor

        @contextmanager
        def fake_conn():
            yield conn

        with patch.object(migration, 'get_app_conn', fake_conn):
            migration.upgrade()
        self.assertEqual(cursor.tables, set(migration._TABLES))
        conn.commit.assert_called_once()

    def test_creative_group_rejects_an_unowned_asset_reference(self):
        from core.isolation import bound_scope
        from creative_groups import repository as material_group_repository
        from repositories import creative_group_repository
        with patch.object(material_group_repository, 'get_selectable_material', return_value=None):
            with bound_scope(Scope(42, 73)):
                with self.assertRaises(HTTPException) as caught:
                    creative_group_repository._validate_refs([
                        {'material_id': 9001, 'selection_mode': 'latest'},
                    ])
        self.assertEqual(caught.exception.status_code, 404)

    def test_account_transfer_is_tenant_scoped_and_target_app_verified(self):
        from core.isolation import bound_scope
        from repositories import application_repository, biz_account_repository
        conn = MagicMock()
        cursor = MagicMock()
        cursor.rowcount = 1
        conn.cursor.return_value = cursor
        manager = MagicMock()
        manager.__enter__.return_value = conn
        manager.__exit__.return_value = False
        target = {'id': 74, 'tenant_id': 42, 'status': 'active'}
        with patch.object(application_repository, 'get', return_value=target), \
             patch.object(biz_account_repository, 'get_biz_conn', return_value=manager):
            with bound_scope(Scope(42, 73)):
                changed = biz_account_repository.transfer_to_application(
                    99, 74, from_application_id=73,
                )
        self.assertEqual(changed, 1)
        sql, params = cursor.execute.call_args.args
        self.assertIn('tenant_id=%s', sql)
        self.assertIn('application_id=%s', sql)
        self.assertEqual(params, [74, 99, 42, 73])


@unittest.skipUnless(os.environ.get('ADSMIND_INTEGRATION_TESTS') == '1', 'Requires local database')
class TenantIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from repositories import tenant_repository, application_repository, user_repository, tenant_member_repository
        from auth import create_token
        from app import app
        cls.ids, cls.users, cls.apps, cls.headers = [], [], [], []
        cls.prefix = '_isolation_'+uuid.uuid4().hex
        for suffix in ('a', 'b'):
            tenant = tenant_repository.create(slug=cls.prefix.replace('_', '-')+suffix, name='Isolation test '+suffix, plan_id='pro')
            cls.ids.append(tenant['id'])
            app_row = application_repository.create(tenant['id'], 'Isolation application', is_default=True)
            cls.apps.append(app_row['id'])
            row = user_repository.create(username=cls.prefix+suffix, password_hash='unused-test-hash', role='admin', display_name='Isolation owner', assigned_accounts=[])
            cls.users.append(row)
            tenant_member_repository.ensure_member(tenant['id'], row['id'], 'owner')
            cls.headers.append({'Authorization': 'Bearer '+create_token(row['username'], 'admin', tenant_id=tenant['id']), 'X-Application-Id': str(app_row['id'])})
        cls.same_tenant_app = application_repository.create(
            cls.ids[0], 'Second isolation application'
        )['id']
        cls.same_tenant_headers = {
            **cls.headers[0],
            'X-Application-Id': str(cls.same_tenant_app),
        }
        limited = user_repository.create(
            username=cls.prefix+'limited',
            password_hash='unused-test-hash',
            role='viewer',
            display_name='Limited application member',
            assigned_accounts=[],
        )
        cls.users.append(limited)
        tenant_member_repository.ensure_member(cls.ids[0], limited['id'], 'member')
        application_repository.add_member(cls.apps[0], limited['id'], 'viewer')
        cls.limited_headers = {
            'Authorization': 'Bearer '+create_token(
                limited['username'], 'viewer', tenant_id=cls.ids[0]
            ),
            'X-Application-Id': str(cls.apps[0]),
        }
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        from db import get_app_conn, get_biz_conn
        from core.isolation import APPLICATION_OWNED_TABLES, OWNED_TABLES
        with get_app_conn() as conn:
            cur = conn.cursor()
            for tid in cls.ids:
                cur.execute(
                    """DELETE FROM app_application_members
                       WHERE application_id IN (
                           SELECT id FROM app_applications WHERE tenant_id=%s
                       )""",
                    (tid,),
                )
                for table in sorted(OWNED_TABLES - {'biz_ad_accounts', 'tiktok_material_uploads'}):
                    cur.execute(f'DELETE FROM {table} WHERE tenant_id=%s', (tid,))
                for table in sorted(APPLICATION_OWNED_TABLES - {'biz_ad_accounts'}):
                    cur.execute(f'DELETE FROM {table} WHERE tenant_id=%s', (tid,))
                for table in ('app_oauth_sessions', 'app_launch_drafts', 'app_oauth_credentials', 'app_tenant_members', 'app_applications', 'app_tenants'):
                    key = 'id' if table == 'app_tenants' else 'tenant_id'
                    cur.execute(f'DELETE FROM {table} WHERE {key}=%s', (tid,))
            for user in cls.users:
                cur.execute('DELETE FROM app_email_verifications WHERE user_id=%s', (user['id'],))
                cur.execute('DELETE FROM app_users WHERE id=%s', (user['id'],))
            conn.commit()
        with get_biz_conn() as conn:
            cur = conn.cursor()
            for tid in cls.ids:
                cur.execute('SELECT account_id FROM biz_ad_accounts WHERE tenant_id=%s', (tid,))
                for row in cur.fetchall():
                    for table in ('biz_campaigns', 'biz_adgroups', 'biz_ads', 'biz_campaign_daily_normalized', 'biz_adgroup_daily_normalized', 'biz_ad_daily_normalized'):
                        cur.execute(f'DELETE FROM {table} WHERE platform=%s AND account_id=%s', ('tiktok', row['account_id']))
                for table in ('biz_ad_accounts', 'tiktok_material_uploads'):
                    cur.execute(f'DELETE FROM {table} WHERE tenant_id=%s', (tid,))
            conn.commit()

    def test_empty_account_overview_has_complete_metrics(self):
        response = self.client.get('/api/biz/overview?start_date=2026-01-01&end_date=2026-01-02&platform=meta', headers=self.headers[1])
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['total_spend'], 0)
        self.assertEqual(data['total_revenue'], 0)
        self.assertIn('avg_roas', data)
        self.assertTrue(data['_hint'])

    def test_password_recovery_invalid_expired_and_single_use(self):
        from services.password_recovery import issue
        from services.user_service import verify_password
        from repositories import user_repository
        from db import get_app_conn
        user = self.users[0]
        password = 'Recovery-test-8!'
        def reset(token):
            return self.client.post('/api/auth/reset-password', json={'token': token, 'password': password})
        self.assertEqual(reset('x'*43).status_code, 422)
        expired = issue(user['id'], user['username'])
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE app_email_verifications SET expires_at=NOW()-INTERVAL 1 SECOND WHERE user_id=%s AND purpose='password_reset'", (user['id'],))
            conn.commit()
        self.assertEqual(reset(expired).status_code, 422)
        token = issue(user['id'], user['username'])
        self.assertEqual(reset(token).status_code, 200)
        self.assertTrue(verify_password(password, user_repository.get_by_id(user['id'])['password_hash']))
        self.assertEqual(reset(token).status_code, 422)
        self.assertEqual(user_repository.get_by_id(self.users[1]['id'])['password_hash'], 'unused-test-hash')

    def test_auth_rejects_no_token_forged_token_foreign_app_and_foreign_member(self):
        from auth import create_token
        path = '/api/templates/'
        self.assertEqual(self.client.get(path).status_code, 401)
        token = self.headers[0]['Authorization'][7:]
        parts = token.split('.')
        parts[2] = 'invalid'
        self.assertEqual(self.client.get(path, headers={'Authorization': 'Bearer '+'.'.join(parts)}).status_code, 401)
        self.assertEqual(self.client.get(path, headers={**self.headers[0], 'X-Application-Id': str(self.apps[1])}).status_code, 403)
        self.assertEqual(
            self.client.get('/api/material-catalog/references', headers={**self.headers[0], 'X-Application-Id': str(self.apps[1])}).status_code,
            404,
        )
        forged_tenant = create_token(self.users[0]['username'], 'admin', tenant_id=self.ids[1])
        self.assertEqual(self.client.get(path, headers={'Authorization': 'Bearer '+forged_tenant}).status_code, 403)
        # An arbitrary tenant header never overrides signed identity.
        response = self.client.get('/api/users/me', headers={**self.headers[0], 'X-Tenant-Id': str(self.ids[1])})
        self.assertEqual(response.json()['tenant']['id'], self.ids[0])

    def test_ordinary_member_requires_explicit_application_membership(self):
        self.assertEqual(
            self.client.get('/api/users/me', headers=self.limited_headers).status_code,
            200,
        )
        denied = self.client.get('/api/users/me', headers={
            **self.limited_headers,
            'X-Application-Id': str(self.same_tenant_app),
        })
        self.assertEqual(denied.status_code, 403)

    def test_template_and_asset_crud_are_independent(self):
        response = self.client.post('/api/templates/', headers=self.headers[0], json={'name': self.prefix, 'platform': 'tiktok'})
        self.assertEqual(response.status_code, 200, response.text)
        tpl = response.json()['data']['id']
        foreign = self.client.get('/api/templates/', headers=self.headers[1]).json()['data']
        self.assertNotIn(tpl, [r['id'] for r in foreign])
        self.assertNotIn('data', self.client.get('/api/templates/'+tpl, headers=self.headers[1]).json())
        self.client.put('/api/templates/'+tpl, headers=self.headers[1], json={'name': 'hijack'})
        self.client.delete('/api/templates/'+tpl, headers=self.headers[1])
        own = self.client.get('/api/templates/'+tpl, headers=self.headers[0]).json()['data']
        self.assertEqual(own['name'], self.prefix)
        asset = self.client.post('/api/ad-assets/landing-pages', headers=self.headers[0], json={'name': self.prefix, 'landing_page_url': 'https://example.test'}).json()['data']
        self.client.put('/api/ad-assets/landing-pages/'+str(asset['id']), headers=self.headers[1], json={'name': 'hijack'})
        self.client.delete('/api/ad-assets/landing-pages/'+str(asset['id']), headers=self.headers[1])
        self.assertEqual(self.client.get('/api/ad-assets/landing-pages/'+str(asset['id']), headers=self.headers[0]).json()['data']['name'], self.prefix)

    def test_same_tenant_resources_follow_tenant_or_application_contract(self):
        # Templates are tenant-level and intentionally reusable across apps.
        template = self.client.post(
            '/api/templates/',
            headers=self.headers[0],
            json={'name': self.prefix+' shared', 'platform': 'tiktok'},
        ).json()['data']
        visible = self.client.get('/api/templates/', headers=self.same_tenant_headers).json()['data']
        self.assertIn(template['id'], [row['id'] for row in visible])

        # Accounts and launch drafts are application-level and must not leak to a
        # second application owned by the same tenant.
        account_id = self.prefix+'same-tenant-app'
        response = self.client.post('/api/ad-accounts/', headers=self.headers[0], json={
            'platform': 'tiktok',
            'account_id': account_id,
            'account_name': account_id,
            'access_token': 'test-only',
        })
        self.assertEqual(response.status_code, 200, response.text)
        other_accounts = self.client.get('/api/ad-accounts/', headers=self.same_tenant_headers).json()['data']
        self.assertNotIn(account_id, [row['account_id'] for row in other_accounts])
        account = next(row for row in self.client.get('/api/ad-accounts/', headers=self.headers[0]).json()['data'] if row['account_id'] == account_id)
        self.assertEqual(self.client.get('/api/ad-accounts/'+str(account['id']), headers=self.same_tenant_headers).json(), {'error': 'not_found'})
        self.client.put('/api/ad-accounts/'+str(account['id']), headers=self.same_tenant_headers, json={'account_name': 'same-tenant-hijack'})
        self.client.delete('/api/ad-accounts/'+str(account['id']), headers=self.same_tenant_headers)
        self.assertEqual(self.client.get('/api/ad-accounts/'+str(account['id']), headers=self.headers[0]).json()['data']['account_name'], account_id)
        from core.isolation import bound_scope
        from repositories import biz_campaign_repository
        with bound_scope(Scope(self.ids[0], self.same_tenant_app)):
            with self.assertRaises(ScopeNotBoundError):
                biz_campaign_repository.upsert(
                    platform='tiktok', account_id=account_id,
                    campaign_id=self.prefix+'foreign-write', campaign_name='must not persist',
                )

        available = self.client.get(
            '/api/applications/ad-accounts/available',
            headers=self.same_tenant_headers,
        )
        self.assertIn(account_id, [row['account_id'] for row in available.json()])
        moved = self.client.post(
            f'/api/applications/{self.same_tenant_app}/ad-accounts/bind',
            headers=self.same_tenant_headers,
            json={'account_row_id': account['id']},
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertIsNone(self.client.get(
            '/api/ad-accounts/'+str(account['id']), headers=self.headers[0]
        ).json().get('data'))
        unbound = self.client.post(
            f'/api/applications/{self.same_tenant_app}/ad-accounts/unbind',
            headers=self.same_tenant_headers,
            json={'account_row_id': account['id']},
        )
        self.assertEqual(unbound.status_code, 200, unbound.text)
        self.assertEqual(
            self.client.get('/api/ad-accounts/'+str(account['id']), headers=self.headers[0]).json()['data']['account_id'],
            account_id,
        )

        payload = {
            'request_key': str(uuid.uuid4()),
            'payload': {
                'template_id': template['id'],
                'campaign_name': 'application scoped draft',
                'budget': 50,
            },
        }
        draft = self.client.post('/api/launch-drafts', headers=self.headers[0], json=payload)
        self.assertEqual(draft.status_code, 200, draft.text)
        other_drafts = self.client.get('/api/launch-drafts', headers=self.same_tenant_headers).json()['data']
        self.assertEqual(other_drafts['total'], 0)

    def test_application_configuration_repositories_hide_foreign_ids(self):
        from core.isolation import bound_scope
        from repositories import (
            account_group_repository,
            execution_record_repository,
            naming_rule_repository,
        )

        from repositories import (
            biz_account_repository,
        )

        with bound_scope(Scope(self.ids[0], self.apps[0])):
            account_id = self.prefix+'group-account'
            biz_account_repository.upsert(platform='tiktok', account_id=account_id)
            cases = (
                (account_group_repository, {'account_refs': [{
                    'platform': 'tiktok', 'account_id': account_id,
                }]}),
                (naming_rule_repository, {'rule': {'pattern': '{drama}-{language}'}}),
            )
            created = []
            for repository, field in cases:
                row = repository.create(name=self.prefix+repository.__name__, created_by=self.prefix, **field)
                created.append((repository, field, row))
            execution = execution_record_repository.create(
                operation='campaign.create', target_type='campaign', target_id='target-a',
                request_payload={'name': 'safe'}, created_by=self.prefix,
            )

        with bound_scope(Scope(self.ids[0], self.same_tenant_app)):
            with self.assertRaises(ScopeNotBoundError):
                account_group_repository.create(
                    name=self.prefix+'foreign-account-group',
                    account_refs=[{'platform': 'tiktok', 'account_id': account_id}],
                )

        for foreign_scope in (
            Scope(self.ids[0], self.same_tenant_app),
            Scope(self.ids[1], self.apps[1]),
        ):
            with bound_scope(foreign_scope):
                for repository, field, row in created:
                    self.assertIsNone(repository.get(row['id']))
                    self.assertIsNone(repository.update(row['id'], name='hijack', **field))
                    self.assertFalse(repository.delete(row['id']))
                self.assertIsNone(execution_record_repository.get(execution['id']))
                self.assertIsNone(execution_record_repository.finish(execution['id'], status='SUCCEEDED'))

        with bound_scope(Scope(self.ids[0], self.apps[0])):
            for repository, _, row in created:
                self.assertEqual(repository.get(row['id'])['name'], self.prefix+repository.__name__)
            finished = execution_record_repository.finish(
                execution['id'], status='SUCCEEDED', result={'platform_id': 'safe-id'}
            )
            self.assertEqual(finished['status'], 'SUCCEEDED')

    def test_naming_rule_api_is_application_scoped_and_viewer_is_read_only(self):
        payload = {
            'name': self.prefix+' naming rule',
            'rule': {'pattern': '{platform}_{product}_{date}', 'description': 'test'},
        }
        created = self.client.post('/api/naming-rules', headers=self.headers[0], json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        rule_id = created.json()['data']['id']

        own = self.client.get(f'/api/naming-rules/{rule_id}', headers=self.headers[0])
        self.assertEqual(own.status_code, 200)
        self.assertEqual(
            self.client.get('/api/naming-rules', headers=self.same_tenant_headers).json()['data'],
            [],
        )
        self.assertEqual(
            self.client.get(f'/api/naming-rules/{rule_id}', headers=self.headers[1]).status_code,
            404,
        )
        self.assertEqual(
            self.client.post('/api/naming-rules', headers=self.limited_headers, json=payload).status_code,
            403,
        )

    def test_creative_group_api_is_scoped_audited_and_viewer_is_read_only(self):
        from db import get_app_conn

        master = self.client.post('/api/material-catalog/masters', headers=self.headers[0], json={
            'name': self.prefix+' creative material', 'material_type': 'video',
        })
        self.assertEqual(master.status_code, 201, master.text)
        material_id = master.json()['id']
        version = self.client.post(
            f'/api/material-catalog/masters/{material_id}/versions',
            headers=self.headers[0],
            json={'source_filename': 'creative.mp4', 'mime_type': 'video/mp4', 'size_bytes': 128},
        )
        self.assertEqual(version.status_code, 201, version.text)
        version_id = version.json()['id']
        attached = self.client.post('/api/material-catalog/references', headers=self.headers[0], json={
            'material_id': material_id, 'selection_mode': 'latest', 'status': 'selected',
        })
        self.assertEqual(attached.status_code, 201, attached.text)

        payload = {'name': self.prefix+' creative group', 'materials': [{
            'material_id': material_id, 'selection_mode': 'latest', 'selected_version_id': None,
        }]}
        created = self.client.post('/api/creative-groups', headers=self.headers[0], json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        group = created.json()['data']
        self.assertFalse(group['can_deliver'])
        self.assertTrue(group['blocking_reasons'])
        self.assertEqual(self.client.get('/api/creative-groups', headers=self.limited_headers).status_code, 200)
        self.assertEqual(self.client.post('/api/creative-groups', headers=self.limited_headers, json=payload).status_code, 403)
        self.assertEqual(self.client.get('/api/creative-groups', headers=self.same_tenant_headers).json()['data'], [])
        self.assertEqual(self.client.get(f"/api/creative-groups/{group['id']}", headers=self.headers[1]).status_code, 404)

        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE material_versions SET upload_status='uploaded' WHERE tenant_id=%s AND id=%s",
                (self.ids[0], version_id),
            )
            conn.commit()
        refreshed = self.client.get(f"/api/creative-groups/{group['id']}", headers=self.headers[0])
        self.assertTrue(refreshed.json()['data']['can_deliver'])
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) AS total FROM app_oplog WHERE tenant_id=%s AND target_type='creative_group' AND target_id=%s",
                (self.ids[0], str(group['id'])),
            )
            self.assertGreaterEqual(int(cur.fetchone()['total']), 1)

        self.assertEqual(self.client.delete(f"/api/creative-groups/{group['id']}", headers=self.headers[0]).status_code, 200)
        self.assertEqual(self.client.delete(f'/api/material-catalog/references/{material_id}', headers=self.headers[0]).status_code, 200)
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM material_versions WHERE tenant_id=%s AND material_id=%s", (self.ids[0], material_id))
            cur.execute("DELETE FROM material_masters WHERE tenant_id=%s AND id=%s", (self.ids[0], material_id))
            conn.commit()

    def test_accounts_cannot_be_read_mutated_rebound_or_overwritten_by_other_tenant(self):
        payload = {'platform': 'tiktok', 'account_id': self.prefix+'acct', 'account_name': self.prefix, 'access_token': 'test-only-no-platform-access', 'app_secret': 'test-secret', 'currency': 'USD'}
        response = self.client.post('/api/ad-accounts/', headers=self.headers[0], json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        row = response.json()['data']
        from db import get_biz_conn
        with get_biz_conn() as conn:
            cur = conn.cursor()
            cur.execute('SELECT access_token, app_secret FROM biz_ad_accounts WHERE id=%s', (row['id'],))
            stored = cur.fetchone()
            self.assertEqual(stored['access_token'], '')
            self.assertTrue(stored['app_secret'].startswith('enc:'))
        self.assertEqual(self.client.get('/api/ad-accounts/'+str(row['id']), headers=self.headers[1]).json(), {'error': 'not_found'})
        self.client.put('/api/ad-accounts/'+str(row['id']), headers=self.headers[1], json={'account_name': 'hijack'})
        self.assertEqual(self.client.post('/api/ad-accounts/', headers=self.headers[1], json={**payload, 'access_token': 'foreign-token'}).status_code, 409)
        self.client.post(f'/api/applications/{self.apps[1]}/ad-accounts/bind', headers=self.headers[1], json={'account_row_id': row['id']})
        self.assertEqual(self.client.get('/api/ad-accounts/'+str(row['id']), headers=self.headers[0]).json()['data']['account_name'], self.prefix)

    def test_connection_rechecks_authorization_and_uses_platform_metadata(self):
        from unittest.mock import AsyncMock
        payload = {'platform': 'tiktok', 'account_id': self.prefix+'connected', 'access_token': 'test-token', 'app_id': 'app', 'app_secret': 'test-secret', 'currency': 'USD', 'timezone': 'UTC'}
        discovered = {'valid': True, 'accounts': [{'account_id': payload['account_id'], 'account_name': self.prefix, 'currency': 'CNY', 'timezone': 'Asia/Shanghai'}]}
        with patch('services.account_service.verify_token', new=AsyncMock(return_value=discovered)):
            invalid = self.client.post('/api/ad-accounts/connect', headers=self.headers[0], json={**payload, 'account_id': 'not-authorized'})
            self.assertEqual(invalid.status_code, 403)
            response = self.client.post('/api/ad-accounts/connect', headers=self.headers[0], json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()['data']
        self.assertEqual(data['currency'], 'CNY')
        self.assertEqual(data['timezone'], 'Asia/Shanghai')
        self.assertEqual(data['application_id'], self.apps[0])
        self.assertNotIn('access_token', data)
        self.assertNotIn('app_secret', data)
        self.assertEqual(self.client.get('/api/ad-accounts/', headers=self.headers[1]).json()['data'], [])

    def test_meta_oauth_selection_platform_isolation_and_quota_retry(self):
        from config import get_settings
        from unittest.mock import AsyncMock
        from integrations.oauth_base import TokenBundle, verify_state
        from db import get_app_conn
        settings = get_settings().model_copy(update={'meta_app_id': 'test-app', 'meta_app_secret': 'test-secret'})
        with patch('services.platform_authorization.get_settings', return_value=settings):
            start = self.client.get('/api/integrations/meta/oauth/start', headers=self.headers[0])
        self.assertEqual(start.status_code, 200, start.text)
        state = start.json()['state']
        sid = verify_state(state)['x']['s']
        account_id = self.prefix+'meta'
        bundle = TokenBundle(access_token='sensitive-meta-token', scopes=['ads_read', 'ads_management'], accounts=[{'account_id': account_id, 'account_name': self.prefix, 'currency': 'CNY', 'timezone': 'Asia/Shanghai', 'status': 'DISABLED'}])
        with patch('services.platform_authorization.MetaOAuth.exchange_code', new=AsyncMock(return_value=bundle)) as exchange:
            callback = self.client.get('/api/integrations/meta/oauth/callback', params={'code': 'test-code', 'state': state}, follow_redirects=False)
            self.assertEqual(callback.status_code, 303, callback.text)
            self.assertIn('/meta/complete?', callback.headers['location'])
            self.assertEqual(self.client.get('/api/integrations/meta/oauth/callback', params={'code': 'test-code', 'state': state}, follow_redirects=False).status_code, 409)
            self.assertEqual(exchange.await_count, 1)
        path = '/api/integrations/meta/authorization/'+sid
        self.assertEqual(self.client.get(path, headers=self.headers[1]).status_code, 404)
        self.assertEqual(self.client.get('/api/integrations/tiktok/authorization/'+sid, headers=self.headers[0]).status_code, 404)
        details = self.client.get(path, headers=self.headers[0])
        self.assertEqual(details.status_code, 200, details.text)
        self.assertNotIn('sensitive-meta-token', details.text)
        with patch('services.quota_service.enforce_account_quota', side_effect=HTTPException(422, 'quota')):
            self.assertEqual(self.client.post(path, headers=self.headers[0], json={'account_id': account_id}).status_code, 422)
        self.assertEqual(self.client.get(path, headers=self.headers[0]).status_code, 200)
        saved = self.client.post(path, headers=self.headers[0], json={'account_id': account_id})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['data']['status'], 'DISABLED')
        self.assertEqual(saved.json()['data']['currency'], 'CNY')
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute('SELECT status,payload_cipher FROM app_oauth_sessions WHERE id=%s', (sid,))
            row = cur.fetchone()
            self.assertEqual(row['status'], 'COMPLETED')
            self.assertIsNone(row['payload_cipher'])

    def test_tiktok_oauth_selection_is_one_time_encrypted_and_tenant_bound(self):
        from config import get_settings
        from unittest.mock import AsyncMock
        from integrations.oauth_base import TokenBundle
        from db import get_app_conn
        from urllib.parse import parse_qs, urlparse
        settings = get_settings().model_copy(update={'tiktok_app_id': 'test-app', 'tiktok_app_secret': 'test-secret'})
        with patch('services.platform_authorization.get_settings', return_value=settings):
            response = self.client.get('/api/integrations/tiktok/oauth/start', headers=self.headers[0])
        self.assertEqual(response.status_code, 200, response.text)
        state = response.json()['state']
        from integrations.oauth_base import verify_state
        sid = verify_state(state)['x']['s']
        account_id = self.prefix+'oauth'
        bundle = TokenBundle(access_token='sensitive-test-token', accounts=[{'account_id': account_id, 'account_name': self.prefix, 'currency': 'EUR', 'timezone': 'Europe/Paris'}])
        with patch('services.platform_authorization.TikTokOAuth.exchange_code', new=AsyncMock(return_value=bundle)) as exchange:
            callback = self.client.get('/api/integrations/tiktok/oauth/callback', params={'auth_code': 'test-code', 'state': state}, follow_redirects=False)
            self.assertEqual(callback.status_code, 303, callback.text)
            self.assertEqual(parse_qs(urlparse(callback.headers['location']).query)['session_id'], [sid])
            replay = self.client.get('/api/integrations/tiktok/oauth/callback', params={'auth_code': 'test-code', 'state': state}, follow_redirects=False)
            self.assertEqual(replay.status_code, 409)
            self.assertEqual(exchange.await_count, 1)
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute('SELECT payload_cipher FROM app_oauth_sessions WHERE id=%s', (sid,))
            self.assertNotIn(b'sensitive-test-token', cur.fetchone()['payload_cipher'])
        path = '/api/integrations/tiktok/authorization/'+sid
        self.assertEqual(self.client.get(path, headers=self.headers[1]).status_code, 404)
        details = self.client.get(path, headers=self.headers[0])
        self.assertNotIn('sensitive-test-token', details.text)
        self.assertEqual(details.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.post(path, headers=self.headers[0], json={'account_id': 'not-authorized'}).status_code, 403)
        saved = self.client.post(path, headers=self.headers[0], json={'account_id': account_id})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['data']['currency'], 'EUR')
        self.assertEqual(self.client.post(path, headers=self.headers[0], json={'account_id': account_id}).status_code, 422)
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute('SELECT payload_cipher FROM app_oauth_sessions WHERE id=%s', (sid,))
            self.assertIsNone(cur.fetchone()['payload_cipher'])

    def test_tiktok_oauth_unconfigured_denied_and_expired(self):
        from config import get_settings
        from integrations.oauth_base import verify_state
        from db import get_app_conn
        settings = get_settings().model_copy(update={'tiktok_app_id': '', 'tiktok_app_secret': ''})
        with patch('services.platform_authorization.get_settings', return_value=settings):
            self.assertEqual(self.client.get('/api/integrations/tiktok/oauth/start', headers=self.headers[0]).status_code, 503)
        settings = settings.model_copy(update={'tiktok_app_id': 'test-app', 'tiktok_app_secret': 'test-secret'})
        with patch('services.platform_authorization.get_settings', return_value=settings):
            start = self.client.get('/api/integrations/tiktok/oauth/start', headers=self.headers[0]).json()
        denied = self.client.get('/api/integrations/tiktok/oauth/callback', params={'state': start['state'], 'error': 'denied'}, follow_redirects=False)
        self.assertEqual(denied.status_code, 303)
        self.assertIn('result=failed', denied.headers['location'])
        sid = verify_state(start['state'])['x']['s']
        with get_app_conn() as conn:
            cur = conn.cursor()
            cur.execute('UPDATE app_oauth_sessions SET expires_at=NOW()-INTERVAL 1 SECOND WHERE id=%s', (sid,))
            conn.commit()
        self.assertEqual(self.client.get('/api/integrations/tiktok/authorization/'+sid, headers=self.headers[0]).status_code, 404)

    def test_credentials_materials_logs_and_sync_do_not_cross_tenants(self):
        from repositories import tiktok_material_repository, oplog_repository
        from services import sync_state, credential_service
        token = current_scope.set(Scope(self.ids[0], self.apps[0]))
        try:
            mid = tiktok_material_repository.create({'advertiser_id': 'test', 'local_file_name': self.prefix})
            oplog_repository.insert(username=self.users[0]['username'], action=self.prefix)
            sync_state.set_error('structure', self.prefix)
        finally:
            current_scope.reset(token)
        token = current_scope.set(Scope(self.ids[1], self.apps[1]))
        try:
            self.assertIsNone(tiktok_material_repository.get_by_id(mid))
            self.assertEqual(tiktok_material_repository.delete_by_id(mid), 0)
            logs, _ = oplog_repository.list_logs()
            self.assertNotIn(self.prefix, [r['action'] for r in logs])
            self.assertNotEqual(sync_state.get_module_state('structure')['last_error'], self.prefix)
            with patch('services.credential_service._from_oauth_credentials', return_value=None), patch('services.credential_service._from_legacy_biz_accounts', return_value=None), patch('services.credential_service._from_settings_default', return_value='internal-secret'):
                self.assertIsNone(credential_service.resolve_access_token('tiktok'))
            with self.assertRaises(HTTPException):
                credential_service.resolve_access_token('tiktok', self.prefix+'acct')
        finally:
            current_scope.reset(token)

    def test_foreign_member_management_and_internal_sources_are_denied(self):
        self.assertEqual(self.client.put('/api/users/'+self.users[0]['username'], headers=self.headers[1], json={'display_name': 'hijack'}).status_code, 404)
        self.assertEqual(self.client.get('/api/bizdata/channel_report_summary?start_date=2026-10-01&end_date=2026-10-03', headers=self.headers[1]).status_code, 403)
        self.assertEqual(self.client.get('/api/users/', headers=self.headers[1]).json()[0]['username'], self.users[1]['username'])
        from repositories import tenant_member_repository
        tenant_member_repository.backfill_internal_members()
        self.assertIsNone(tenant_member_repository.get(1, self.users[0]['id']))
        self.assertIsNone(tenant_member_repository.get(1, self.users[1]['id']))

    def test_reports_entities_and_drafts_only_access_owned_accounts_and_templates(self):
        from repositories import biz_campaign_repository, biz_daily_report_repository
        for index in (0, 1):
            aid = self.prefix+'report'+str(index)
            response = self.client.post('/api/ad-accounts/', headers=self.headers[index], json={'platform': 'tiktok', 'account_id': aid, 'account_name': aid, 'access_token': 'test-only'})
            self.assertEqual(response.status_code, 200, response.text)
            token = current_scope.set(Scope(self.ids[index], self.apps[index]))
            try:
                cid = self.prefix+'campaign'+str(index)
                biz_campaign_repository.upsert(platform='tiktok', account_id=aid, campaign_id=cid, campaign_name=cid, status='ENABLE')
                biz_daily_report_repository.upsert(platform='tiktok', account_id=aid, campaign_id=cid, campaign_name=cid, stat_date='2026-10-01', spend=100 if index == 0 else 900)
            finally:
                current_scope.reset(token)
        query = '?start_date=2026-10-01&end_date=2026-10-03&platform=tiktok&source=legacy&account_id='+self.prefix+'report0'
        own = self.client.get('/api/biz/campaign-agg'+query, headers=self.headers[0])
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual(len(own.json()['data']), 1)
        self.assertEqual(own.json()['data'][0]['total_spend'], 100)
        self.assertEqual(self.client.get('/api/biz/campaign-agg'+query, headers=self.headers[1]).status_code, 403)
        self.assertEqual(self.client.post('/api/biz/update-status', headers=self.headers[1], params={'platform': 'tiktok', 'entity_type': 'campaign', 'entity_id': self.prefix+'campaign0', 'status': 'DISABLE'}).status_code, 403)
        tpl = self.client.post('/api/templates/', headers=self.headers[0], json={'name': self.prefix+'draft', 'platform': 'tiktok'}).json()['data']['id']
        payload = {'request_key': str(uuid.uuid4()), 'payload': {'template_id': tpl, 'campaign_name': 'saved only', 'budget': 50}}
        draft = self.client.post('/api/launch-drafts', headers=self.headers[0], json=payload)
        self.assertEqual(draft.status_code, 200, draft.text)
        did = draft.json()['data']['id']
        self.assertEqual(self.client.post('/api/launch-drafts', headers=self.headers[1], json=payload).status_code, 404)
        self.assertEqual(self.client.post('/api/launch-drafts/'+did+'/check', headers=self.headers[1]).status_code, 404)
        self.assertEqual(self.client.get('/api/launch-drafts', headers=self.headers[1]).json()['data']['total'], 0)

    def test_registration_provisions_an_independent_team_without_sending_email(self):
        from repositories import user_repository, tenant_member_repository
        with patch('services.email_service.send_verify_email', return_value=True), patch('services.email_service.get_sender') as sender:
            sender.return_value.kind = 'test'
            response = self.client.post('/api/auth/register', json={'email': self.prefix+'@example.test', 'password': uuid.uuid4().hex, 'company_name': self.prefix+' registered team'})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.ids.append(data['tenant']['id'])
        user = user_repository.get_by_username(self.prefix+'@example.test')
        self.users.append(user)
        headers = {'Authorization': 'Bearer '+data['token']}
        self.assertEqual(self.client.get('/api/users/me', headers=headers).json()['tenant']['id'], data['tenant']['id'])
        self.assertEqual(self.client.get('/api/ad-accounts/', headers=headers).json()['data'], [])
        self.assertEqual(self.client.get('/api/templates/', headers=headers).json()['data'], [])
        self.assertIsNone(tenant_member_repository.get(1, user['id']))
