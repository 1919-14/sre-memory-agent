"""Sandbox execution: isolated verification of generated fixes."""

from .backends import DockerBackend, LocalBackend, select_backend
from .base import SandboxError, TestBackend
from .executor import SandboxExecutor

__all__ = [
    "DockerBackend",
    "LocalBackend",
    "SandboxError",
    "SandboxExecutor",
    "TestBackend",
    "select_backend",
]
