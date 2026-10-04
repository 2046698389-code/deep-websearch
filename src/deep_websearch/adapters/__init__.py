from .social import build_social_adapters
from .web import build_web_adapters
from .providers import route_providers


def build_adapters(settings, http):
    return route_providers(settings, http, {
        **build_social_adapters(settings, http), **build_web_adapters(settings, http)})
