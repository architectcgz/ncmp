import json
import os
import sys
import tempfile
import unittest
import types
from types import SimpleNamespace
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

crypto_module = types.ModuleType("Crypto")
cipher_module = types.ModuleType("Crypto.Cipher")
aes_module = types.ModuleType("Crypto.Cipher.AES")
aes_module.MODE_CBC = "MODE_CBC"
aes_module.new = mock.Mock()
cipher_module.AES = aes_module
crypto_module.Cipher = cipher_module
sys.modules.setdefault("Crypto", crypto_module)
sys.modules.setdefault("Crypto.Cipher", cipher_module)
sys.modules.setdefault("Crypto.Cipher.AES", aes_module)

nacl_module = types.ModuleType("nacl")
nacl_encoding_module = types.ModuleType("nacl.encoding")
nacl_public_module = types.ModuleType("nacl.public")
nacl_public_module.PublicKey = mock.Mock()
nacl_public_module.SealedBox = mock.Mock()
nacl_module.encoding = nacl_encoding_module
nacl_module.public = nacl_public_module
sys.modules.setdefault("nacl", nacl_module)
sys.modules.setdefault("nacl.encoding", nacl_encoding_module)
sys.modules.setdefault("nacl.public", nacl_public_module)

import main as main_module
import refresh_cookie as refresh_cookie_module
from src.core.signer import Signer
from src.utils.config import Config
from src.utils.github import GitHubService
from src.utils.http import request_json


class ConfigHardeningTest(unittest.TestCase):
    def test_file_cookie_config_is_preserved_without_env_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = os.path.join(temp_dir, "config")
            os.makedirs(config_dir, exist_ok=True)
            with open(os.path.join(config_dir, "setting.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "Cookie_MUSIC_U": "file-music-u",
                        "Cookie___csrf": "file-csrf",
                    },
                    handle,
                )

            with mock.patch.dict(os.environ, {}, clear=True):
                previous_cwd = os.getcwd()
                try:
                    os.chdir(temp_dir)
                    config = Config()
                finally:
                    os.chdir(previous_cwd)

            self.assertEqual(config.get("Cookie_MUSIC_U"), "file-music-u")
            self.assertEqual(config.get("Cookie___csrf"), "file-csrf")

    def test_refresh_config_does_not_require_existing_cookies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = os.path.join(temp_dir, "config")
            os.makedirs(config_dir, exist_ok=True)
            with open(os.path.join(config_dir, "setting.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "netease_phone": "13800000000",
                        "netease_md5_password": "md5-password",
                        "gh_token": "token",
                        "gh_repo": "user/repo",
                    },
                    handle,
                )

            with mock.patch.dict(os.environ, {}, clear=True):
                previous_cwd = os.getcwd()
                try:
                    os.chdir(temp_dir)
                    config = Config()
                finally:
                    os.chdir(previous_cwd)

            self.assertEqual(config.get("netease_phone"), "13800000000")
            with self.assertRaisesRegex(ValueError, "主程序缺少必要配置项"):
                config.validate_required(["Cookie_MUSIC_U", "Cookie___csrf"], "主程序")


class MainEntrypointHardeningTest(unittest.TestCase):
    def test_main_keeps_original_config_error(self):
        logger = mock.Mock()

        with mock.patch.object(main_module, "Logger", return_value=logger), mock.patch.object(
            main_module, "Config", side_effect=RuntimeError("boom")
        ):
            main_module.main()

        logger.error.assert_any_call("程序异常: boom")
        logger.end.assert_called_with("❌ 执行失败", True)


class GitHubServiceHardeningTest(unittest.TestCase):
    def test_github_service_reports_missing_repo_cleanly(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "token"}, clear=True):
            with self.assertRaisesRegex(ValueError, "GitHub仓库信息不完整"):
                GitHubService(mock.Mock())


class HttpWrapperHardeningTest(unittest.TestCase):
    def test_request_json_wraps_timeout(self):
        session = mock.Mock()
        session.request.side_effect = requests.Timeout("boom")

        with self.assertRaisesRegex(RuntimeError, "请求任务失败:"):
            request_json(
                session,
                "GET",
                "https://example.com",
                mock.Mock(),
                timeout=1,
                error_context="请求任务",
            )

    def test_request_json_wraps_non_json_response(self):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = json.JSONDecodeError("bad", "<html>", 0)
        response.text = "<html>blocked</html>"
        session = mock.Mock()
        session.request.return_value = response
        logger = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "响应不是合法 JSON"):
            request_json(
                session,
                "GET",
                "https://example.com",
                logger,
                timeout=1,
                error_context="请求任务",
            )

        logger.debug.assert_called_once()


class SignerRetryHardeningTest(unittest.TestCase):
    def test_signer_rate_limit_retry_is_bounded(self):
        session = mock.Mock()
        session.cookies = {"__csrf": "csrf-token"}
        rate_limited_response = mock.Mock()
        rate_limited_response.raise_for_status.return_value = None
        rate_limited_response.json.return_value = {"code": 500, "message": "操作频繁"}
        session.post.return_value = rate_limited_response

        config = SimpleNamespace(
            get=lambda key, default=None: {"rate_limit_retries": 2, "score": 3}.get(key, default),
            get_wait_time=lambda: 0,
            get_http_timeout=lambda: 1,
        )
        signer = Signer(session, "task-id", mock.Mock(), config)

        with mock.patch("src.core.signer.time.sleep", return_value=None), mock.patch.object(
            Signer, "_get_params", return_value="params"
        ), mock.patch.object(Signer, "_get_enc_sec_key", return_value="enc-key"):
            with self.assertRaisesRegex(RuntimeError, "已达到频率限制最大重试次数 2"):
                signer.sign({"id": "work-id", "name": "Song", "authorName": "Author"})

        self.assertEqual(session.post.call_count, 3)


class RefreshCookieFlowTest(unittest.TestCase):
    def _base_env(self):
        return {
            "NETEASE_PHONE": "13800000000",
            "NETEASE_MD5_PASSWORD": "md5-password",
            "GH_TOKEN": "token",
            "GH_REPO": "user/repo",
        }

    def test_refresh_cookie_success_path(self):
        logger = mock.Mock()
        config = mock.Mock()
        config.get.side_effect = lambda key, default=None: None
        task = mock.Mock()
        task.execute.return_value = True

        with mock.patch.dict(os.environ, self._base_env(), clear=True), mock.patch.object(
            refresh_cookie_module, "Logger", return_value=logger
        ), mock.patch.object(refresh_cookie_module, "Config", return_value=config), mock.patch.object(
            refresh_cookie_module, "NotificationService", return_value=mock.Mock()
        ), mock.patch.object(
            refresh_cookie_module, "CookieRefreshTask", return_value=task
        ):
            refresh_cookie_module.main()

        task.execute.assert_called_once()
        logger.info.assert_any_call("✅ Cookie刷新成功")

    def test_refresh_cookie_failure_path(self):
        logger = mock.Mock()
        config = mock.Mock()
        config.get.side_effect = lambda key, default=None: None
        task = mock.Mock()
        task.execute.return_value = False

        with mock.patch.dict(os.environ, self._base_env(), clear=True), mock.patch.object(
            refresh_cookie_module, "Logger", return_value=logger
        ), mock.patch.object(refresh_cookie_module, "Config", return_value=config), mock.patch.object(
            refresh_cookie_module, "NotificationService", return_value=mock.Mock()
        ), mock.patch.object(
            refresh_cookie_module, "CookieRefreshTask", return_value=task
        ):
            refresh_cookie_module.main()

        task.execute.assert_called_once()
        logger.error.assert_any_call("❌ Cookie刷新失败")


if __name__ == "__main__":
    unittest.main()
