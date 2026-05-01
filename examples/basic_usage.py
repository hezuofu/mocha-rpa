"""Complete usage examples for the RPA framework.

This script demonstrates the declarative API, functional utilities,
async wrappers, plugin system, and the mock driver.
"""

import time
import asyncio

# -------------------------------------------------------
# Setup: import framework components and configure context
# -------------------------------------------------------

from rpabot.drivers.mock_driver import MockDriver, MockNativeElement
from rpabot.core.context import AutomationContext
from rpabot.builder.find_builder import Find
from rpabot.functional.utils import retry, pipe, tap, maybe, ignore_err
from rpabot.plugin.base import PluginManager
from rpabot.async_api.wrappers import AsyncFind, async_retry, run_async, gather


def create_context():
    """Create a connected automation context with a mock driver
    pre-populated with UI elements matching a login form."""
    driver = MockDriver()
    driver.connect()

    # Build a simple login dialog
    driver.inject(
        MockNativeElement(
            name="Login Window",
            automation_id="login_window",
            control_type="Window",
        )
    )
    driver.inject(
        MockNativeElement(
            name="Username",
            automation_id="txt_username",
            control_type="Edit",
        )
    )
    driver.inject(
        MockNativeElement(
            name="Password",
            automation_id="txt_password",
            control_type="Edit",
        )
    )
    driver.inject(
        MockNativeElement(
            name="LoginButton",
            automation_id="btn_login",
            control_type="Button",
        )
    )
    driver.inject(
        MockNativeElement(
            name="CancelButton",
            automation_id="btn_cancel",
            control_type="Button",
        )
    )

    context = AutomationContext(
        timeout=10.0,
        retry_count=3,
        retry_delay=0.5,
        driver=driver,
    )
    AutomationContext.set_current(context)
    return context


# ======================================================================
# Example 1: Declarative API — Login automation
# ======================================================================

print("=" * 60)
print("Example 1: Login automation (declarative API)")
print("=" * 60)

ctx = create_context()

# Simulate user login
Find().with_context(ctx).name("Username").do(
    lambda e: e.send_keys("admin")
)

Find().with_context(ctx).name("Password").do(
    lambda e: e.send_keys("secret123")
)

Find().with_context(ctx).name("LoginButton").do(
    lambda e: e.click()
)

print("Login sequence completed via declarative API.\n")


# ======================================================================
# Example 2: Functional utilities — retry and pipe
# ======================================================================

print("=" * 60)
print("Example 2: Functional utilities")
print("=" * 60)

# Retry a flaky operation
attempts = 0


def flaky_click():
    global attempts
    attempts += 1
    if attempts < 2:
        raise RuntimeError("Button not ready")
    print(f"  Click succeeded on attempt {attempts}")


retry(max_retries=3, delay=0.1)(flaky_click)()

# Pipe composition
process = pipe(
    lambda s: s.strip().upper(),
    lambda s: s.replace(" ", "_"),
    tap(lambda s: print(f"  Piped result: {s}")),
)
process(" hello world ")

print()


# ======================================================================
# Example 3: Locator chain and string parsing
# ======================================================================

print("=" * 60)
print("Example 3: Locator chains and string parsing")
print("=" * 60)

from rpabot.core.locator import LocatorFactory

# Using string syntax to build a composite locator
locator = LocatorFactory.create("name:Login Window > type:Window")
print(f"  Parsed locator: {locator}")

# Using & operator
from rpabot.core.locator import ByName, ByType
chain = ByName("Login") & ByType("Window")
print(f"  &-chain: {chain}")

print()


# ======================================================================
# Example 4: Plugin system
# ======================================================================

print("=" * 60)
print("Example 4: Plugin system")
print("=" * 60)


class TimingPlugin:
    """Plugin that logs execution timing."""

    name = "timing"

    def initialize(self, context):
        context.register_hook("pre_action", self._on_pre_action)
        context.register_hook("post_action", self._on_post_action)
        self._start = 0

    def _on_pre_action(self, **kwargs):
        self._start = time.time()

    def _on_post_action(self, **kwargs):
        elapsed = time.time() - self._start
        print(f"  [TimingPlugin] Action took {elapsed:.4f}s")

    def cleanup(self):
        print("  [TimingPlugin] Cleaned up")


mgr = PluginManager(context=ctx)
mgr.register(TimingPlugin())
mgr.start_all()

# Execute an action — the timing plugin will log it
Find().with_context(ctx).name("CancelButton").do(lambda e: e.click())

mgr.shutdown_all()
print()


# ======================================================================
# Example 5: Async API
# ======================================================================

print("=" * 60)
print("Example 5: Async API")
print("=" * 60)


async def async_demo():
    ctx2 = create_context()

    # Async retry
    @async_retry(max_retries=3, delay=0.1)
    async def async_click():
        print("  Attempting async click...")
        Find().with_context(ctx2).name("LoginButton").do(lambda e: e.click())
        return "done"

    result = await async_click()
    print(f"  Async result: {result}")

    # Concurrency example
    async def task_a():
        await asyncio.sleep(0.05)
        return "A"

    async def task_b():
        await asyncio.sleep(0.02)
        return "B"

    results = await gather(task_a(), task_b())
    print(f"  Concurrent results: {results}")

    ctx2.driver.disconnect()


asyncio.run(async_demo())
print()


# ======================================================================
# Example 6: Error handling
# ======================================================================

print("=" * 60)
print("Example 6: Error handling")
print("=" * 60)

from rpabot.core.exceptions import ElementNotFound

# Using maybe for optional elements
safe_result = maybe(
    lambda: Find().with_context(ctx).name("NonExistent").do(lambda e: e.click())
)()
print(f"  maybe() returned: {safe_result}")

# Cleanup
ctx.driver.disconnect()
print("\nAll examples completed.")
