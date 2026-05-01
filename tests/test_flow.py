"""Tests for the flow control primitives."""

import pytest

from mocharpa.flow.conditions import (
    exists as cond_exists,
    not_exists,
    visible,
    enabled,
    selected,
    eq,
    neq,
    contains,
    gt,
    lt,
    is_none,
    is_not_none,
    AND,
    OR,
    NOT,
)
from mocharpa.flow.branching import if_, switch_
from mocharpa.flow.loops import for_each, while_, until_, repeat
from mocharpa.flow.sequence import sequence, try_catch

from mocharpa.core.exceptions import ElementNotFound
from mocharpa.core.context import AutomationContext
from mocharpa.builder.find_builder import Find
from mocharpa.drivers.mock_driver import MockDriver, MockNativeElement


# ======================================================================
# fixtures
# ======================================================================

@pytest.fixture
def ctx():
    d = MockDriver()
    d.connect()
    c = AutomationContext(driver=d, timeout=2)
    return c


# ======================================================================
# Condition helpers
# ======================================================================

class TestConditionHelpers:
    def test_exists(self, ctx):
        ctx.driver.inject(MockNativeElement(name="Btn"))
        assert cond_exists(Find().with_context(ctx).name("Btn"))()
        assert not not_exists(Find().with_context(ctx).name("Btn"))()

    def test_visible(self, ctx):
        ctx.driver.inject(MockNativeElement(name="Btn", visible=True))
        assert visible(Find().with_context(ctx).name("Btn"))()

    def test_enabled(self, ctx):
        ctx.driver.inject(MockNativeElement(name="Btn", enabled=True))
        assert enabled(Find().with_context(ctx).name("Btn"))()

    def test_value_helpers(self):
        assert eq(1, 1)()
        assert not eq(1, 2)()
        assert neq(1, 2)()
        assert contains([1, 2, 3], 2)()
        assert gt(5, 3)()
        assert lt(3, 5)()
        assert is_none(None)()
        assert is_not_none(42)()

    def test_combinators(self):
        assert AND(True, True, True)()
        assert not AND(True, False, True)()
        assert OR(False, False, True)()
        assert not OR(False, False, False)()
        assert NOT(True)() is False
        assert NOT(False)() is True

    def test_lazy_evaluation(self):
        calls = []

        def lazy_true():
            calls.append(1)
            return True

        def lazy_false():
            calls.append(2)
            return False

        # AND short-circuits on first False
        AND(lazy_true, lazy_false, lazy_true)()
        assert len(calls) == 2

        calls.clear()
        # OR short-circuits on first True
        OR(lazy_false, lazy_true, lazy_false)()
        assert len(calls) == 2


# ======================================================================
# if_ / elif_ / else_
# ======================================================================

class TestIf:
    def test_then_else_true(self):
        results = []
        if_(True).then(lambda: results.append("yes")).else_(lambda: results.append("no"))
        assert results == ["yes"]

    def test_then_else_false(self):
        results = []
        if_(False).then(lambda: results.append("yes")).else_(lambda: results.append("no"))
        assert results == ["no"]

    def test_then_only(self):
        results = []
        if_(True).then(lambda: results.append("yes")).run()
        assert results == ["yes"]

    def test_elif_chain(self):
        results = []
        if_(False) \
            .then(lambda: results.append("if")) \
            .elif_(True).then(lambda: results.append("elif")) \
            .else_(lambda: results.append("else"))
        assert results == ["elif"]

    def test_with_condition_helper(self, ctx):
        ctx.driver.inject(MockNativeElement(name="OK"))
        results = []
        if_(cond_exists(Find().with_context(ctx).name("OK"))) \
            .then(lambda: results.append("found")) \
            .else_(lambda: results.append("missing"))
        assert results == ["found"]


# ======================================================================
# switch_
# ======================================================================

class TestSwitch:
    def test_matching_case(self):
        results = []
        switch_("b") \
            .case("a", lambda: results.append("A")) \
            .case("b", lambda: results.append("B")) \
            .default(lambda: results.append("default"))
        assert results == ["B"]

    def test_default(self):
        results = []
        switch_("x") \
            .case("a", lambda: results.append("A")) \
            .default(lambda: results.append("default"))
        assert results == ["default"]

    def test_no_match_no_default(self):
        result = switch_("x").case("a", lambda: "A").run()
        assert result is None


# ======================================================================
# for_each
# ======================================================================

class TestForEach:
    def test_static_list(self):
        results = []
        for_each([1, 2, 3]).do(lambda n: results.append(n * 2))
        assert results == [2, 4, 6]

    def test_with_index(self):
        results = []
        for_each(["a", "b"]).do_with_index(lambda i, v: results.append(f"{i}:{v}"))
        assert results == ["0:a", "1:b"]

    def test_lazy_items(self):
        counter = [0]

        def lazy_list():
            counter[0] += 1
            return [10, 20]

        results = []
        for_each(lazy_list).do(lambda n: results.append(n))
        assert results == [10, 20]


# ======================================================================
# while_
# ======================================================================

class TestWhile:
    def test_basic(self):
        counter = [0]
        while_(lambda: counter[0] < 3).do(lambda: counter.__setitem__(0, counter[0] + 1))
        assert counter[0] == 3

    def test_max_iterations(self):
        counter = [0]
        # Condition always true, but max_iterations limits it
        while_(True, max_iterations=5).do(lambda: counter.__setitem__(0, counter[0] + 1))
        assert counter[0] == 5

    def test_zero_iterations(self):
        results = []
        while_(False).do(lambda: results.append("x"))
        assert results == []


# ======================================================================
# until_
# ======================================================================

class TestUntil:
    def test_basic(self):
        counter = [0]
        until_(lambda: counter[0] >= 3).do(lambda: counter.__setitem__(0, counter[0] + 1))
        assert counter[0] == 3

    def test_executes_at_least_once(self):
        results = []
        until_(True).do(lambda: results.append("done"))
        assert results == ["done"]


# ======================================================================
# repeat
# ======================================================================

class TestRepeat:
    def test_zero(self):
        results = []
        repeat(0).do(lambda i: results.append(i))
        assert results == []

    def test_three(self):
        results = []
        repeat(3).do(lambda i: results.append(i))
        assert results == [0, 1, 2]

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            repeat(-1)


# ======================================================================
# sequence
# ======================================================================

class TestSequence:
    def test_basic(self):
        order = []
        sequence(
            lambda: order.append(1),
            lambda: order.append(2),
            lambda: order.append(3),
        ).run()
        assert order == [1, 2, 3]

    def test_then_extension(self):
        order = []
        seq = sequence(lambda: order.append("a"))
        seq.then(lambda: order.append("b")).run()
        assert order == ["a", "b"]

    def test_callable(self):
        order = []
        seq = sequence(lambda: order.append(1))
        seq()
        assert order == [1]


# ======================================================================
# try_catch
# ======================================================================

class TestTryCatch:
    def test_no_error(self):
        result = try_catch(lambda: 42).run()
        assert result == 42

    def test_catch_specific(self):
        def boom():
            raise ValueError("bad")

        caught = []
        result = try_catch(boom) \
            .catch(ValueError, lambda e: caught.append(str(e))) \
            .run()
        assert caught == ["bad"]

    def test_catch_order(self):
        def boom():
            raise ValueError("v")

        results = []
        try_catch(boom) \
            .catch(ValueError, lambda e: results.append("first")) \
            .catch(Exception, lambda e: results.append("second")) \
            .run()
        assert results == ["first"]

    def test_uncaught_propagates(self):
        def boom():
            raise ValueError("v")

        with pytest.raises(ValueError):
            try_catch(boom).catch(TypeError, lambda e: None).run()

    def test_finally_runs(self):
        cleanup = []
        try_catch(lambda: 1) \
            .finally_(lambda: cleanup.append("done")) \
            .run()
        assert cleanup == ["done"]

    def test_finally_runs_on_error(self):
        cleanup = []

        def boom():
            raise RuntimeError("err")

        with pytest.raises(RuntimeError):
            try_catch(boom).finally_(lambda: cleanup.append("clean")).run()
        assert cleanup == ["clean"]
