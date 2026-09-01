from __future__ import annotations
from abc import ABC, abstractmethod
from app.core.types import ProviderResult

class Provider(ABC):
    name: str = "base"
    model: str = "unknown"

    @abstractmethod
    async def generate(self, *, system: str, user: str) -> ProviderResult:
        raise NotImplementedError
