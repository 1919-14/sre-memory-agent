"""Failure classification package."""

from . import taxonomy
from .classifier import Classifier
from .taxonomy import ErrorClassSpec, spec_for, specialist_for

__all__ = ["Classifier", "ErrorClassSpec", "spec_for", "specialist_for", "taxonomy"]
