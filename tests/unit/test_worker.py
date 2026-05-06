from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from utils.datetime import utcnow


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
        record = MagicMock()
        record.processing_status = status
        record.updated_at = utcnow() - age
        record.processing_error = None
        return record

    def test_marks_old_processing_rows_as_failed(self):
        from files.model import ProcessingStatus
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
