"""Packaged logo helpers, called by invoice rendering in the executor."""

from base64 import b64encode
from functools import cache
from pathlib import Path


@cache
def logo_bytes():
    return (Path(__file__).parent / "brand" / "logo.png").read_bytes()


def logo_data_uri():
    return "data:image/png;base64," + b64encode(logo_bytes()).decode("ascii")
