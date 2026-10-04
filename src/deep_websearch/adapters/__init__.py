from .social import build_social_adapters
from .web import build_web_adapters


def build_adapters(settings, http):
    return {**build_social_adapters(settings, http), **build_web_adapters(settings, http)}
