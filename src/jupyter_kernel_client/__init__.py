"""Small client for executing code in an existing Jupyter kernel."""

from .client import (
    InterruptResponse,
    KernelClientError,
    KernelResponse,
    RichOutput,
    execute,
    eval_expression,
    get_variable,
    interrupt_kernel,
    kernel_is_ready,
)
from .kernels import discover_kernels, start_kernel, stop_kernel

__all__ = [
    "InterruptResponse",
    "KernelClientError",
    "KernelResponse",
    "RichOutput",
    "execute",
    "eval_expression",
    "get_variable",
    "interrupt_kernel",
    "kernel_is_ready",
    "discover_kernels",
    "start_kernel",
    "stop_kernel",
]
