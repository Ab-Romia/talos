import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.unit
class TestRedisSettings:
    def test_parse_full_redis_url(self):
        mock_cfg = MagicMock()
        mock_cfg.redis.url = "redis://myhost:1234/2"

        with patch("processing.worker.cfg", return_value=mock_cfg):
            from processing.worker import get_redis_settings
            settings = get_redis_settings()

        assert settings.host == "myhost"
        assert settings.port == 1234
        assert settings.database == 2

    def test_parse_url_no_db_defaults_zero(self):
        mock_cfg = MagicMock()
        mock_cfg.redis.url = "redis://localhost:6379"

        with patch("processing.worker.cfg", return_value=mock_cfg):
            from processing.worker import get_redis_settings
            settings = get_redis_settings()

        assert settings.database == 0

    def test_parse_url_no_port_defaults_6379(self):
        mock_cfg = MagicMock()
        mock_cfg.redis.url = "redis://localhost"

        with patch("processing.worker.cfg", return_value=mock_cfg):
            from processing.worker import get_redis_settings
            settings = get_redis_settings()

        assert settings.port == 6379

    def test_parse_url_defaults_when_no_redis_config(self):
        mock_cfg = MagicMock()
        mock_cfg.redis = None

        with patch("processing.worker.cfg", return_value=mock_cfg):
            from processing.worker import get_redis_settings
            settings = get_redis_settings()

        assert settings.host == "localhost"
        assert settings.port == 6379
