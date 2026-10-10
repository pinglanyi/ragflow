"""Opt-in strict persistence for independent existing-chunk compilation."""
from contextvars import ContextVar

strict_compilation = ContextVar('strict_compilation', default=False)
