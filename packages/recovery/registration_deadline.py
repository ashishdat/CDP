"""One per-application deadline for optional registration recovery work."""
from contextvars import ContextVar
from functools import wraps
from time import monotonic
import os

_deadline = ContextVar('registration_recovery_deadline', default=None)

def recovery_budget_exhausted():
    deadline = _deadline.get()
    return deadline is not None and monotonic() >= deadline

def bounded_registration(function):
    @wraps(function)
    def run(*args, **kwargs):
        seconds = float(os.environ.get('CDP_REGISTRATION_RECOVERY_BUDGET_SECONDS', '130'))
        if not 0 < seconds <= 150:
            raise ValueError('Registration recovery budget must be between 0 and 150 seconds')
        existing = _deadline.get()
        token = _deadline.set(min(existing, monotonic()+seconds) if existing is not None else monotonic()+seconds)
        try:
            return function(*args, **kwargs)
        finally:
            _deadline.reset(token)
    return run
