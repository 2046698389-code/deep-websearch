from bs4 import BeautifulSoup

from ..models import AdapterError as AdapterError, SourceState, SourceStatus


class BaseAdapter:
    name = ""
    required_env: tuple[str, ...] = ()

    def __init__(self, settings, http):
        self.settings = settings
        self.http = http

    def availability(self):
        if self.settings.sources[self.name].enabled is False:
            return SourceStatus(source=self.name, status=SourceState.unavailable, reason="Disabled by source config")
        missing = [name for name in self.required_env if not self.settings.env.get(name, "").strip()]
        if missing:
            return SourceStatus(source=self.name, status=SourceState.missing_credentials,
                                reason="Missing " + " / ".join(missing), missing_credentials=missing)
        return SourceStatus(source=self.name, status=SourceState.enabled)

    async def initialize(self):
        return self.availability()

    @staticmethod
    def clean(value):
        return BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)

    async def search(self, query, limit):
        raise NotImplementedError
