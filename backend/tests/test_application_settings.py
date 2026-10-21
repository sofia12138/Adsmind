import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from services import account_group_service, naming_rule_service


class AccountGroupServiceTests(unittest.TestCase):
    @patch("services.account_group_service.account_group_repository.create")
    @patch("services.account_group_service.biz_account_repository.list_all")
    def test_create_normalizes_and_deduplicates_owned_accounts(self, list_accounts, create):
        list_accounts.return_value = [
            {"platform": "tiktok", "account_id": "a-1"},
            {"platform": "meta", "account_id": "m-1"},
        ]
        create.return_value = {"id": 1}

        result = account_group_service.create_group(
            name="  主账户  ",
            account_refs=[
                {"platform": "TikTok", "account_id": "a-1"},
                {"platform": "tiktok", "account_id": "a-1"},
            ],
            created_by="editor",
        )

        self.assertEqual(result, {"id": 1})
        create.assert_called_once_with(
            name="主账户",
            account_refs=[{"platform": "tiktok", "account_id": "a-1"}],
            created_by="editor",
        )

    @patch("services.account_group_service.biz_account_repository.list_all")
    def test_foreign_or_missing_account_is_indistinguishable(self, list_accounts):
        list_accounts.return_value = []
        with self.assertRaises(HTTPException) as caught:
            account_group_service.create_group(
                name="越界引用",
                account_refs=[{"platform": "tiktok", "account_id": "foreign"}],
                created_by="editor",
            )
        self.assertEqual(caught.exception.status_code, 404)

    def test_empty_group_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "至少"):
            account_group_service.create_group(name="空组", account_refs=[], created_by="editor")


class NamingRuleServiceTests(unittest.TestCase):
    def test_rule_is_normalized_and_fields_keep_first_use_order(self):
        self.assertEqual(
            naming_rule_service.normalize_rule({
                "pattern": " {platform}_{country}_{platform}_{date} ",
                "description": "  团队规则  ",
            }),
            {
                "pattern": "{platform}_{country}_{platform}_{date}",
                "description": "团队规则",
                "fields": ["platform", "country", "date"],
            },
        )

    def test_unknown_field_and_unbalanced_braces_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "不支持"):
            naming_rule_service.normalize_rule({"pattern": "{tenant_secret}"})
        with self.assertRaisesRegex(ValueError, "大括号"):
            naming_rule_service.normalize_rule({"pattern": "{platform"})
        with self.assertRaisesRegex(ValueError, "格式化"):
            naming_rule_service.normalize_rule({"pattern": "{date:%Y%m%d}"})


class ApplicationSettingsMigrationTests(unittest.TestCase):
    def test_runner_keeps_0001_through_0009_contiguous_and_rejects_a_gap(self):
        from migrations import runner

        self.assertEqual(
            [row["version"] for row in runner.plan()],
            [
                "0001_legacy_baseline",
                "0002_scope_foreign_keys",
                "0003_application_resources",
                "0004_drama_catalog",
                "0005_application_settings_panels",
                "0006_material_catalog",
                "0007_creative_groups",
                "0008_ad_creation_drafts",
                "0009_platform_preflight",
            ],
        )
        modules_with_gap = tuple(
            module for module in runner.MODULES if ".v0004_" not in module
        )
        with (
            patch.object(runner, "MODULES", modules_with_gap),
            patch.object(runner, "get_app_conn") as get_conn,
        ):
            with self.assertRaisesRegex(RuntimeError, "缺少 0004"):
                runner.upgrade_all()
        get_conn.assert_not_called()

    def test_0005_refuses_to_write_before_an_integrated_0004(self):
        from migrations.versions import v0005_application_settings_panels as migration

        conn = MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.return_value = None
        manager = MagicMock()
        manager.__enter__.return_value = conn
        manager.__exit__.return_value = False

        with patch.object(migration, "get_app_conn", return_value=manager):
            with self.assertRaisesRegex(RuntimeError, "依赖已整合并执行的 0004"):
                migration.upgrade()

        self.assertEqual(cursor.execute.call_count, 1)
        conn.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
