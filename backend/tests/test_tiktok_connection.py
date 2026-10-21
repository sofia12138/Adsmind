import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from services.account_service import _verify_tiktok


class TikTokConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def verify(self, responses):
        client = AsyncMock()
        client.get.side_effect = responses
        with patch('tiktok_ads.api.client._get_shared_client', return_value=client):
            result = await _verify_tiktok('test-token', 'test-app', 'test-secret')
        return result, client

    def response(self, payload, status=200):
        return httpx.Response(status, json=payload, request=httpx.Request('GET', 'https://example.test'))

    async def test_metadata_is_read_from_authorized_advertiser_details(self):
        result, client = await self.verify([
            self.response({'code': 0, 'data': {'list': [{'advertiser_id': '11'}, {'advertiser_id': '11'}]}}),
            self.response({'code': 0, 'data': {'list': [{'advertiser_id': '11', 'name': 'Example', 'currency': 'CNY', 'timezone': 'Asia/Shanghai'}]}}),
        ])
        self.assertTrue(result['valid'])
        self.assertEqual(result['accounts'], [{'account_id': '11', 'account_name': 'Example', 'currency': 'CNY', 'timezone': 'Asia/Shanghai', 'status': ''}])
        self.assertEqual(json.loads(client.get.call_args.kwargs['params']['advertiser_ids']), ['11'])

    async def test_missing_credentials_do_not_use_global_configuration(self):
        with patch('tiktok_ads.api.client._get_shared_client') as client:
            result = await _verify_tiktok('test-token', '', '')
        self.assertFalse(result['valid'])
        client.assert_not_called()

    async def test_missing_currency_or_timezone_blocks_connection(self):
        result, _ = await self.verify([
            self.response({'code': 0, 'data': {'list': [{'advertiser_id': '11'}]}}),
            self.response({'code': 0, 'data': {'list': [{'advertiser_id': '11', 'currency': 'CNY'}]}}),
        ])
        self.assertFalse(result['valid'])
        self.assertEqual(result['accounts'], [])

    async def test_platform_rejection_and_timeout_do_not_echo_secrets(self):
        for response in (self.response({'code': 401, 'message': 'echo test-secret test-token'}), httpx.ReadTimeout('url?secret=test-secret')):
            result, _ = await self.verify([response])
            self.assertFalse(result['valid'])
            self.assertNotIn('test-secret', result['error'])
            self.assertNotIn('test-token', result['error'])

    async def test_detail_ids_cannot_expand_authorization(self):
        result, _ = await self.verify([
            self.response({'code': 0, 'data': {'list': [{'advertiser_id': '11'}]}}),
            self.response({'code': 0, 'data': {'list': [{'advertiser_id': '22', 'currency': 'USD', 'timezone': 'UTC'}]}}),
        ])
        self.assertFalse(result['valid'])


if __name__ == '__main__':
    unittest.main()
