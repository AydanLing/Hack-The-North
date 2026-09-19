"""Offline icon target generators."""

from .base import PixelTarget
from .demo_icons import DEMO_ICONS, DEMO_ICON_NAMES, DemoIcon, get_demo, get_demo_icon
from .parametric import DEMO_NAMES, ICON_NAMES, get_icon, icons

__all__ = [
    "DEMO_ICONS",
    "DEMO_ICON_NAMES",
    "DemoIcon",
    "DEMO_NAMES",
    "ICON_NAMES",
    "PixelTarget",
    "get_demo",
    "get_demo_icon",
    "get_icon",
    "icons",
]
