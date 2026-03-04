from functools import lru_cache

from .config import *
from .config_ import Config


@lru_cache
def config() -> Config:
    return Config()
