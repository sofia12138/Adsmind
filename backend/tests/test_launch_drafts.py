import asyncio
import os
import uuid
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import HTTPException
from auth import User
from core.application import ApplicationCtx
from services import launch_draft_service as service
from meta_ads.api.client import MetaApiError

class DraftPrecheckTests(unittest.TestCase):
    def test_currency_and_minor_unit_contract(self):
        from services.launch_budget import budget_checks
        payload = {'budget': '12.34', 'budget_currency': 'CNY', 'adsets': [{'daily_budget': 1234}]}
        self.assertTrue(all(check['ok'] for check in budget_checks(payload, 'meta', 'CNY')))
        for bad in ({**payload, 'budget_currency': 'USD'}, {**payload, 'budget': '1.001'}, {**payload, 'budget': 'NaN'}, {**payload, 'adsets': [{'daily_budget': -1}]}, {**payload, 'adsets': [{'daily_budget': 1.1}]}):
            self.assertFalse(all(check['ok'] for check in budget_checks(bad, 'meta', 'CNY')))
        self.assertFalse(all(check['ok'] for check in budget_checks({'budget': 50}, 'meta', 'CNY')))
        self.assertFalse(all(check['ok'] for check in budget_checks({'budget': 50, 'budget_currency': 'JPY'}, 'meta', 'JPY')))

    def test_inactive_account_blocks_creation_but_active_account_passes(self):
        user = User(username='test', hashed_password='', role='admin')
        application = ApplicationCtx(id=1, tenant_id=1, slug='default', is_default=True)
        payload = {'advertiser_id': 'account-1', 'campaign_name': 'Test', 'budget': 50, 'video_id': 'video-1'}
        for status in ('ACTIVE', 'DISABLED', 'PAUSED', None):
            with self.subTest(status=status), patch('services.account_service.list_accounts', return_value=[{'account_id': 'account-1', 'status': status, 'currency': 'USD'}]), patch('core.biz_filter.resolve_account_filter'):
                result = service.precheck(payload, {'platform': 'tiktok'}, application, user)
                self.assertEqual(result['ok'], status == 'ACTIVE')
                check = next(check for check in result['checks'] if check['code'] == 'account_status')
                self.assertEqual(check['ok'], status == 'ACTIVE')

    def test_missing_account_cannot_pass_precheck(self):
        user = User(username='test', hashed_password='', role='admin')
        application = ApplicationCtx(id=1, tenant_id=1, slug='default', is_default=True)
        with patch('services.account_service.list_accounts', return_value=[]):
            result = service.precheck({'campaign_name': 'Test', 'budget': 50, 'video_id': 'video-1'}, {'platform': 'tiktok'}, application, user)
        self.assertFalse(result['ok'])
        self.assertFalse(next(check for check in result['checks'] if check['code'] == 'account')['ok'])


class CheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.run = service.Run({'id': 'test', 'checkpoints': {}})
        self.token = service._active.set(self.run)
        self.persist = patch.object(self.run, 'persist')
        self.persist.start()

    async def asyncTearDown(self):
        service._active.reset(self.token)
        self.persist.stop()

    async def test_success_is_replayed_without_another_platform_write(self):
        send = AsyncMock(return_value={'id': 'campaign-1'})
        self.assertEqual(await service.checkpoint_call('meta', 'campaigns', {'name': 'A'}, send), {'id': 'campaign-1'})
        self.run.counts = {}
        self.assertEqual(await service.checkpoint_call('meta', 'campaigns', {'name': 'A'}, send), {'id': 'campaign-1'})
        send.assert_awaited_once()

    async def test_unknown_write_is_never_repeated(self):
        send = AsyncMock(side_effect=httpx.ReadTimeout('platform response timed out'))
        with self.assertRaises(httpx.ReadTimeout):
            await service.checkpoint_call('meta', 'campaigns', {'name': 'A'}, send)
        self.run.counts = {}
        with self.assertRaises(HTTPException):
            await service.checkpoint_call('meta', 'campaigns', {'name': 'A'}, send)
        send.assert_awaited_once()
        self.assertEqual(service.result_status({'error': 'timeout'}, self.run.points), 'UNKNOWN')

    async def test_explicit_rejection_can_be_retried(self):
        send = AsyncMock(side_effect=[MetaApiError(100, 'invalid field'), {'id': 'campaign-2'}])
        with self.assertRaises(MetaApiError):
            await service.checkpoint_call('meta', 'campaigns', {'name': 'B'}, send)
        self.run.counts = {}
        self.assertEqual(await service.checkpoint_call('meta', 'campaigns', {'name': 'B'}, send), {'id': 'campaign-2'})
        self.assertEqual(send.await_count, 2)

    async def test_http_timeout_response_blocks_a_repeat(self):
        request = httpx.Request('POST', 'https://example.test/campaigns')
        error = httpx.HTTPStatusError('request timeout', request=request, response=httpx.Response(408, request=request))
        send = AsyncMock(side_effect=error)
        with self.assertRaises(httpx.HTTPStatusError):
            await service.checkpoint_call('meta', 'campaigns', {'name': 'A'}, send)
        self.run.counts = {}
        with self.assertRaises(HTTPException):
            await service.checkpoint_call('meta', 'campaigns', {'name': 'A'}, send)
        send.assert_awaited_once()
        self.assertEqual(service.result_status({}, self.run.points), 'UNKNOWN')

    async def test_write_ahead_record_precedes_the_platform_request(self):
        async def send():
            self.assertEqual(next(iter(self.run.points.values()))['status'], 'PENDING')
            self.run.persist.assert_called_once()
            return {'id': 'first'}
        await service.checkpoint_call('meta', 'campaigns', {}, send)

    async def test_identical_intended_steps_remain_distinct_and_secrets_are_removed(self):
        send = AsyncMock(side_effect=[{'id': 'first'}, {'id': 'second'}])
        await service.checkpoint_call('meta', 'ads', {'name': 'same'}, send)
        await service.checkpoint_call('meta', 'ads', {'name': 'same'}, send)
        self.assertEqual(len(self.run.points), 2)
        self.assertEqual(service.clean({'a': {'access_token': 'secret', 'id': 'x'}, 'app_secret': 'secret'}), {'a': {'id': 'x'}})

@unittest.skipUnless(os.environ.get('ADSMIND_INTEGRATION_TESTS') == '1', 'Requires the local development database')
class DurableDraftTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.user = User(username='_draft_test_'+str(uuid.uuid4()), hashed_password='', role='admin')
        self.application = ApplicationCtx(id=1, tenant_id=1, slug='default', is_default=True)
        self.payload = {'template_id': 'test-template', 'campaign_name': 'local automated validation', 'budget': 50}
        self.template = {'id': 'test-template', 'platform': 'meta'}
        self.tpl_patch = patch('services.template_service.get_template', return_value=self.template)
        self.tpl_patch.start()
        self.check_patch = patch('services.launch_draft_service.precheck', return_value={'ok': True, 'checks': []})
        self.check_patch.start()

    async def asyncTearDown(self):
        from db import get_app_conn
        with get_app_conn() as conn:
            conn.cursor().execute('DELETE FROM app_launch_drafts WHERE created_by=%s', (self.user.username,))
            conn.commit()
        self.check_patch.stop()
        self.tpl_patch.stop()

    def create(self):
        return service.create(self.payload, str(uuid.uuid4()), self.application, self.user)

    async def test_edit_preserves_assets_and_rejects_stale_or_executed_draft(self):
        self.payload.update({'ad_account_id': 'act_test', 'materials': [{'id': 'asset', 'image_hash': 'hash'}], 'adsets': [{'name': 'one', 'daily_budget': 5000, 'material_ids': ['asset'], 'targeting': {'country': 'CN'}}]})
        row = self.create()
        changes = {'campaign_name': 'Edited', 'budget': '12.34', 'adset_budgets': ['12.34']}
        with patch('repositories.biz_account_repository.get_by_platform_account', return_value={'currency': 'CNY'}):
            edited = service.update(row, changes, row['revision'], self.application, self.user)
            self.assertEqual(edited['revision'], row['revision']+1)
            self.assertEqual(edited['payload']['budget_currency'], 'CNY')
            self.assertEqual(edited['payload']['adsets'][0]['daily_budget'], 1234)
            self.assertEqual(edited['payload']['materials'], self.payload['materials'])
            self.assertEqual(edited['payload']['adsets'][0]['targeting'], {'country': 'CN'})
            with self.assertRaises(HTTPException) as conflict:
                service.update(row, changes, row['revision'], self.application, self.user)
            self.assertEqual(conflict.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            service.update({**edited, 'status': 'PARTIAL'}, changes, edited['revision'], self.application, self.user)

    async def test_cbo_edit_updates_campaign_budget_and_keeps_adsets(self):
        self.template['template_type'] = 'web_to_app_conversion_cbo'
        self.payload.update({'ad_account_id': 'act_test', 'adsets': [{'name': 'one', 'material_ids': ['asset']}], 'overrides': {'creative': {'headline': 'Keep me'}}})
        row = self.create()
        with patch('repositories.biz_account_repository.get_by_platform_account', return_value={'currency': 'EUR'}):
            edited = service.update(row, {'campaign_name': 'CBO', 'budget': '20.15'}, row['revision'], self.application, self.user)
        self.assertEqual(edited['payload']['overrides']['campaign']['daily_budget'], 2015)
        self.assertEqual(edited['payload']['overrides']['creative']['headline'], 'Keep me')
        self.assertEqual(edited['payload']['adsets'], self.payload['adsets'])
        self.assertEqual(service.public(edited)['budget_mode'], 'CBO')

    async def test_duplicate_request_and_owner_isolation(self):
        key = str(uuid.uuid4())
        first = service.create(self.payload, key, self.application, self.user)
        second = service.create(self.payload, key, self.application, self.user)
        self.assertEqual(first['id'], second['id'])
        with self.assertRaises(HTTPException) as denied:
            service.load(first['id'], self.application, User(username='different', hashed_password='', role='admin'))
        self.assertEqual(denied.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            service.create({**self.payload, 'budget': 100}, key, self.application, self.user)

    async def test_partial_result_survives_reload_and_only_failed_step_repeats(self):
        campaign = AsyncMock(return_value={'id': 'campaign-1'})
        ad = AsyncMock(side_effect=[MetaApiError(100, 'invalid asset'), {'id': 'ad-1'}])
        async def launch(payload, user):
            created_campaign = await service.checkpoint_call('meta', 'campaigns', {'name': 'A'}, campaign)
            try:
                created_ad = await service.checkpoint_call('meta', 'ads', {'campaign_id': created_campaign['id']}, ad)
                item = {'success': True, 'ad_id': created_ad['id']}
            except MetaApiError as error:
                item = {'success': False, 'error': str(error)}
            return {'data': {'campaign': {'success': True, 'campaign_id': created_campaign['id']}, 'ads': [item]}}
        row = self.create()
        with patch('routes.templates.launch_from_template', side_effect=launch):
            first = await service.execute(row, row['revision'], self.application, self.user)
            self.assertEqual(first['status'], 'PARTIAL')
            loaded = service.load(first['id'], self.application, self.user)
            with self.assertRaises(HTTPException):
                await service.execute(loaded, row['revision'], self.application, self.user)
            final = await service.execute(loaded, loaded['revision'], self.application, self.user)
            self.assertEqual(final['status'], 'SUCCEEDED')
        campaign.assert_awaited_once()
        self.assertEqual(ad.await_count, 2)

    async def test_timeout_blocks_repeated_execution(self):
        send = AsyncMock(side_effect=httpx.ReadTimeout('platform timed out'))
        async def launch(payload, user):
            return await service.checkpoint_call('meta', 'campaigns', {'name': 'A'}, send)
        row = self.create()
        with patch('routes.templates.launch_from_template', side_effect=launch):
            first = await service.execute(row, row['revision'], self.application, self.user)
            self.assertEqual(first['status'], 'UNKNOWN')
            with self.assertRaises(HTTPException):
                await service.execute(first, first['revision'], self.application, self.user)
        send.assert_awaited_once()
