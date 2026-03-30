from functools import lru_cache

from .config import *
from .config_ import Config
from .prompts import *


@lru_cache
def cfg() -> Config:
    return Config()
