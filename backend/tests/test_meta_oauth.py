import logging
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
from core.log_redaction import OAuthLogFilter
from integrations.meta.oauth import MetaOAuth
from integrations.oauth_base import OAuthError


class MetaOAuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.flow = MetaOAuth('test-app', 'test-secret', 'https://graph.facebook.com/v21.0')

    def response(self, payload):
        return httpx.Response(200, json=payload, request=httpx.Request('GET', 'https://graph.facebook.com'))

    def account(self, number):
        return {'id': 'act_'+number, 'account_id': number, 'currency': 'EUR', 'timezone_name': 'Europe/Paris', 'name': 'Example', 'account_status': 1}

    async def test_pagination_uses_cursor_and_does_not_follow_next_url(self):
        client = AsyncMock()
        client.get.side_effect = [
            self.response({'data': [self.account('11')], 'paging': {'next': 'https://untrusted.test/?access_token=token', 'cursors': {'after': 'cursor1'}}}),
            self.response({'data': [self.account('12'), self.account('11')]}),
        ]
        accounts = await self.flow._fetch_ad_accounts(client, 'test-token')
        self.assertEqual([a['account_id'] for a in accounts], ['act_11', 'act_12'])
        for call in client.get.call_args_list:
            self.assertEqual(call.args[0], 'https://graph.facebook.com/v21.0/me/adaccounts')
            self.assertNotIn('access_token', call.kwargs['params'])
            self.assertEqual(call.kwargs['headers']['Authorization'], 'Bearer test-token')
        self.assertEqual(client.get.call_args.kwargs['params']['after'], 'cursor1')

    async def test_missing_metadata_and_repeated_cursor_fail_closed(self):
        for payload in ({'data': [{'id': 'act_11'}]}, {'data': [self.account('11')], 'paging': {'next': 'ignored', 'cursors': {'after': 'repeat'}}}):
            client = AsyncMock()
            client.get.return_value = self.response(payload)
            with self.assertRaises(OAuthError):
                await self.flow._fetch_ad_accounts(client, 'test-token')

    async def test_actual_permissions_and_platform_expiry_are_saved(self):
        client = AsyncMock()
        client.get.side_effect = [self.response({'access_token': 'short-token', 'expires_in': 60}),
                                  self.response({'access_token': 'long-token', 'expires_in': 3600}),
                                  self.response({'data': [self.account('11')]}),
                                  self.response({'data': [{'permission': p, 'status': 'granted'} for p in ('ads_read', 'ads_management')]})]
        with patch('integrations.meta.oauth.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = client
            bundle = await self.flow.exchange_code('test-code', 'https://example.test/callback')
        self.assertEqual(bundle.access_token, 'long-token')
        self.assertEqual(bundle.scopes, ['ads_management', 'ads_read'])
        self.assertIsNotNone(bundle.expires_at)

    async def test_declined_permissions_block_success(self):
        with patch.object(self.flow, '_post_token', new=AsyncMock(return_value={'access_token': 'token'})), patch.object(self.flow, '_fetch_ad_accounts', new=AsyncMock(return_value=[self.account('11')])), patch.object(self.flow, '_read_graph', new=AsyncMock(return_value={'data': [{'permission': 'ads_read', 'status': 'granted'}]})):
            with self.assertRaises(OAuthError):
                await self.flow.exchange_code('code')

    async def test_transport_errors_and_logs_do_not_expose_tokens(self):
        client = AsyncMock()
        client.get.side_effect = httpx.ReadTimeout('url?client_secret=test-secret&code=test-code')
        with self.assertRaises(OAuthError) as error:
            await self.flow._post_token(client, {'client_secret': 'test-secret'})
        self.assertNotIn('test-secret', str(error.exception))
        record = logging.LogRecord('httpx', 20, '', 1, 'GET %s', ('https://example.test?client_secret=test-secret&code=test-code&access_token=test-token',), None)
        OAuthLogFilter().filter(record)
        for secret in ('test-secret', 'test-code', 'test-token'):
            self.assertNotIn(secret, record.getMessage())

    async def test_authorization_url_uses_configured_version_and_permissions(self):
        url = self.flow._build_url('https://example.test/callback', 'state')
        self.assertEqual(urlparse(url).path, '/v21.0/dialog/oauth')
        self.assertEqual(parse_qs(urlparse(url).query)['scope'], ['ads_read,ads_management'])

    async def test_access_log_formatter_preserves_arguments_and_redacts_query(self):
        from uvicorn.logging import AccessFormatter
        record = logging.LogRecord('uvicorn.access', 20, '', 1, '%s - "%s %s HTTP/%s" %d',
                                   ('127.0.0.1:1234', 'GET', '/callback?code=sensitive-code&state=sensitive-state', '1.1', 303), None)
        OAuthLogFilter().filter(record)
        output = AccessFormatter('%(request_line)s %(status_code)s', use_colors=False).format(record)
        self.assertIn('303', output)
        self.assertIn('[redacted]', output)
        self.assertNotIn('sensitive-code', output)
        self.assertNotIn('sensitive-state', output)
