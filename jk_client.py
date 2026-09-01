#!/usr/bin/env python3
"""Compatibility entry point for the jk CLI."""

from jupyter_kernel_client.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
