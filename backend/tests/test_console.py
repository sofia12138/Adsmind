import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.application import get_current_application
from routes.biz import router
from services import console_service

class ConsoleTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.application = SimpleNamespace(id=9, name='测试应用', is_default=False, tenant_id=2)
        app.dependency_overrides[get_current_application] = lambda: self.application
        self.client = TestClient(app)
        self.params = dict(start_date='2026-10-01', end_date='2026-10-03', platform='tiktok', account_id='allowed')

    def test_search_before_pagination_and_clamped_page(self):
        rows = [{'campaign_id': str(i), 'campaign_name': '日本投放' if i % 2 else '美国投放'} for i in range(105)]
        page = console_service.select_page(rows, 'campaign', '日本', 2, 50)
        self.assertEqual(page['total'], 52)
        self.assertEqual(len(page['list']), 2)
        self.assertEqual(page['list'][0]['campaign_id'], '101')
        self.assertEqual(console_service.select_page(rows, 'campaign', '日本', 999, 50)['page'], 2)
        self.assertEqual(console_service.select_page(rows, 'campaign', '103', 1, 50)['total'], 1)

    def test_unbound_account_never_reaches_report_query(self):
        with patch('core.biz_filter.biz_account_repository.list_by_application', return_value=[{'account_id': 'allowed'}]), patch('services.console_service.query') as query:
            response = self.client.get('/biz/console/campaign', params={**self.params, 'account_id': 'other'})
            self.assertEqual(response.status_code, 403)
            query.assert_not_called()

    def test_children_use_same_account_scope(self):
        with patch('core.biz_filter.biz_account_repository.list_by_application', return_value=[{'account_id': 'allowed'}]), patch('services.console_service.query', return_value={'list': [], 'total': 0, 'page': 1, 'page_size': 50}) as query:
            response = self.client.get('/biz/console/adgroup', params={**self.params, 'campaign_id': 'campaign-1'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(query.call_args.kwargs['account_id'], 'allowed')
            self.assertEqual(query.call_args.kwargs['campaign_id'], 'campaign-1')

    def test_invalid_dates_and_missing_parent_do_not_query(self):
        with patch('services.console_service.query') as query:
            self.assertEqual(self.client.get('/biz/console/campaign', params={**self.params, 'start_date': '2026-02-30'}).status_code, 400)
            self.assertEqual(self.client.get('/biz/console/ad', params=self.params).status_code, 400)
            self.assertEqual(self.client.get('/biz/console/campaign', params={**self.params, 'page_size': 10000}).status_code, 422)
            query.assert_not_called()

    def test_empty_application_returns_hint_without_query(self):
        params = {k: v for k, v in self.params.items() if k != 'account_id'}
        with patch('core.biz_filter.biz_account_repository.list_by_application', return_value=[]), patch('services.console_service.query') as query:
            response = self.client.get('/biz/console/campaign', params=params)
            self.assertEqual(response.status_code, 200)
            self.assertIn('未绑定', response.json()['_hint'])
            self.assertEqual(response.json()['data']['total'], 0)
            query.assert_not_called()

if __name__ == '__main__':
    unittest.main()
