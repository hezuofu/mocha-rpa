"""Tests for the functional utilities."""

import pytest
from mocharpa.functional.utils import (
    retry,
    pipe,
    tap,
    maybe,
    with_context,
    wait_until,
    ignore_err,
)
from mocharpa.core.context import AutomationContext
from mocharpa.core.exceptions import TimeoutError


class TestRetry:
    def test_success_first_try(self):
        call_count = 0

        @retry(max_retries=3, delay=0.01)
        def f():
            nonlocal call_count
            call_count += 1
            return 42

        assert f() == 42
        assert call_count == 1

    def test_success_after_retry(self):
        call_count = 0

        @retry(max_retries=3, delay=0.01)
        def f():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        assert f() == "ok"
        assert call_count == 3

    def test_exhaust_retries(self):
        @retry(max_retries=2, delay=0.01)
        def f():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            f()

    def test_specific_exceptions(self):
        @retry(max_retries=3, delay=0.01, exceptions=(ValueError,))
        def f():
            raise TypeError("not caught")

        with pytest.raises(TypeError):
            f()


class TestPipe:
    def test_empty(self):
        assert pipe()(42) == 42

    def test_single(self):
        f = pipe(lambda x: x + 1)
        assert f(1) == 2

    def test_chain(self):
        f = pipe(
            lambda x: x + 1,
            lambda x: x * 2,
            lambda x: f"[{x}]",
        )
        assert f(3) == "[8]"


class TestTap:
    def test_preserves_value(self):
        side: list = []
        result = tap(lambda x: side.append(x))(42)
        assert result == 42
        assert side == [42]


class TestMaybe:
    def test_normal(self):
        f = maybe(lambda x: x + 1)
        assert f(1) == 2

    def test_returns_none_on_error(self):
        f = maybe(lambda: 1 / 0)
        assert f() is None


class TestWithContext:
    def test_injects_context(self):
        ctx = AutomationContext(timeout=99)
        captured = []

        @with_context(ctx)
        def fn(*, context):
            captured.append(context)

        fn()
        assert captured[0] is ctx


class TestWaitUntil:
    def test_immediate_true(self):
        wait_until(lambda: True, timeout=1, interval=0.01)

    def test_timeout(self):
        with pytest.raises(TimeoutError):
            wait_until(lambda: False, timeout=0.1, interval=0.01)


class TestIgnoreErr:
    def test_normal(self):
        f = ignore_err(lambda x: x + 1, default=0)
        assert f(1) == 2

    def test_error_returns_default(self):
        f = ignore_err(lambda: 1 / 0, default=99)
        assert f() == 99
