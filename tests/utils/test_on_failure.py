"""Test utilities for Taskiq on_failure callbacks with in-memory broker."""

import pytest
from taskiq import InMemoryBroker

from broker import SmartRetryWithCallbackMiddleware, register_callback

failure_callbacks_executed = []


async def failure_callback(message, exception: Exception) -> None:
    """Test on_failure callback that records execution."""
    failure_callbacks_executed.append({
        "exception_type": type(exception).__name__,
        "exception_msg": str(exception),
        "message_id": getattr(message, "task_id", None),
    })


test_broker = InMemoryBroker(await_inplace=True).with_middlewares(
    SmartRetryWithCallbackMiddleware()
)


@pytest.mark.asyncio
async def test_callback_invoked_on_max_retries():
    """Test callback fires after Taskiq retries exhaust."""
    register_callback(failure_callback)
    failure_callbacks_executed.clear()

    @test_broker.task(
        retry_on_error=True,
        max_retries=2,
        on_failure=failure_callback.__name__,
    )
    async def failing_task(should_fail: bool = False):
        """Task that can optionally fail."""
        if should_fail:
            raise ValueError("Task failed as requested")
        return "success"

    task = await failing_task.kiq(should_fail=True)
    result = await task.wait_result()

    assert result.is_err is True
    assert str(result.error) == "Task failed as requested"
    assert len(failure_callbacks_executed) == 1

    callback_data = failure_callbacks_executed[0]
    assert callback_data["exception_type"] == "ValueError"
    assert "Task failed as requested" in callback_data["exception_msg"]


@pytest.mark.asyncio
async def test_callback_not_invoked_on_less_than_max():
    """Callback should NOT be invoked if retries do not reach max."""
    # Mutable state to control how many times the task will fail.
    _flaky_state = {"calls": 0, "failures": 1}

    @test_broker.task(
        retry_on_error=True,
        max_retries=3,  # allow more retries than failures
        on_failure=failure_callback.__name__,
    )
    async def flaky_task(should_fail: bool = False):
        """Task that fails N times then succeeds."""
        if should_fail:
            _flaky_state["calls"] += 1
            if _flaky_state["calls"] <= _flaky_state["failures"]:
                raise ValueError("Transient failure")
        return "success"

    register_callback(failure_callback)
    failure_callbacks_executed.clear()

    # ensure flaky will fail exactly once then succeed
    _flaky_state["calls"] = 0
    _flaky_state["failures"] = 1

    task = await flaky_task.kiq(should_fail=True)
    result = await task.wait_result()

    # should succeed ultimately
    assert result.is_err is False
    assert getattr(result, "return_value", None) == "success"

    # callback must NOT be invoked because max_retries (3) not reached
    assert len(failure_callbacks_executed) == 0
