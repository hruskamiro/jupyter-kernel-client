"""Small client for executing code in an existing Jupyter kernel."""

from .client import (
    KernelClientError,
    KernelResponse,
    RichOutput,
    execute,
    eval_expression,
    get_variable,
    kernel_is_ready,
)

__all__ = [
    "KernelClientError",
    "KernelResponse",
    "RichOutput",
    "execute",
    "eval_expression",
    "get_variable",
    "kernel_is_ready",
]
