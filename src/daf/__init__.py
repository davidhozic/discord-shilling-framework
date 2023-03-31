"""
Discord Advertisement Framework
"""
import _discord as discord
from . import annotations as _
from .client import *
from .core import *
from .dtypes import *
from .guild import *
from .message import *
from .logging import *
from .web import *



from .misc import DOCUMENTATION_MODE
if DOCUMENTATION_MODE:
    from .misc import *


VERSION = "v2.6.0"
