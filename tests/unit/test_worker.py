from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch, MagicMock

import pytest

from utils.datetime import utcnow


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


@pytest.mark.unit
class TestRecoverStuckProcessing:
    def _build_session_factory(self, stuck, fresh):
        """Return a session-factory stand-in that hands out a session whose
        scalars() reports exactly the stuck rows and tracks commits."""
        session = MagicMock()
        session.__enter__ = lambda self_: self_
        session.__exit__ = lambda *a: False

        scalars_result = MagicMock()
        scalars_result.all.return_value = stuck
        session.scalars.return_value = scalars_result

        @contextmanager
        def factory():
            yield session

        return factory, session

    def _make_file(self, status, age: timedelta):
        from files.models import ProcessingStatus
        record = MagicMock()
        record.processing_status = status
        record.updated_at = utcnow() - age
        record.processing_error = None
        return record

    def test_marks_old_processing_rows_as_failed(self):
        from files.models import ProcessingStatus
        from processing.worker import recover_stuck_processing, STUCK_AGE

        stuck = self._make_file(ProcessingStatus.PROCESSING, STUCK_AGE + timedelta(minutes=5))
        factory, session = self._build_session_factory([stuck], [])

        recovered = recover_stuck_processing(factory)

        assert recovered == 1
        assert stuck.processing_status == ProcessingStatus.FAILED
        assert stuck.processing_error == "worker restarted while processing"
        session.commit.assert_called_once()

    def test_no_op_when_nothing_stuck(self):
        from processing.worker import recover_stuck_processing

        factory, session = self._build_session_factory([], [])

        recovered = recover_stuck_processing(factory)

        assert recovered == 0
        session.commit.assert_not_called()
