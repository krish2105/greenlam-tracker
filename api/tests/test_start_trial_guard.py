"""The clear must never leave a system nobody can enter.

`wipe()` deletes every account, and the boot chain relies on `bootstrap`
putting the first admin back afterwards. Bootstrap only does that when
BOOTSTRAP_ADMIN_PIN is set and valid — and the README tells people to clear it
once the trial has started, which is exactly right and exactly what makes this
dangerous the next time somebody starts a trial.

Without the guard, both steps report success and the plant is left with its
data gone and no way in.
"""

import os

import pytest

from app.start_trial import can_recreate_an_admin


@pytest.fixture
def env():
    before = os.environ.get("BOOTSTRAP_ADMIN_PIN")
    yield os.environ
    if before is None:
        os.environ.pop("BOOTSTRAP_ADMIN_PIN", None)
    else:
        os.environ["BOOTSTRAP_ADMIN_PIN"] = before


class TestTheGuard:
    def test_it_refuses_when_no_pin_is_set(self, env):
        """The case that actually happens: cleared after the last trial."""
        env.pop("BOOTSTRAP_ADMIN_PIN", None)
        refusal = can_recreate_an_admin()
        assert refusal is not None
        # The message has to say what to do, not just that something is wrong.
        assert "BOOTSTRAP_ADMIN_PIN" in refusal
        assert "redeploy" in refusal

    def test_it_refuses_a_pin_bootstrap_would_reject(self, env):
        # Set but useless is worse than unset: it reads as configured.
        env["BOOTSTRAP_ADMIN_PIN"] = "123456"
        assert can_recreate_an_admin() is not None

    def test_it_allows_a_pin_that_will_work(self, env):
        env["BOOTSTRAP_ADMIN_PIN"] = "481920"
        assert can_recreate_an_admin() is None

    def test_blank_is_the_same_as_absent(self, env):
        env["BOOTSTRAP_ADMIN_PIN"] = "   "
        assert can_recreate_an_admin() is not None
