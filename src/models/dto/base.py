from typing import Any

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict, PrivateAttr, SecretStr

from src.core.security.crypto import encrypt as encrypt_func


class BaseDto(_BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        populate_by_name=True,
    )


class TrackableDto(BaseDto):
    __changed_data: dict[str, Any] = PrivateAttr(default_factory=dict)

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        self.__changed_data[name] = value

    @property
    def changed_data(self) -> dict[str, Any]:
        return self.__changed_data

    def _process_value(self, value: Any, encrypt: bool = False) -> Any:
        if isinstance(value, SecretStr):
            raw = value.get_secret_value()
            if encrypt:
                raw = encrypt_func(raw)
            return raw
        if isinstance(value, list):
            return [self._process_value(v, encrypt) for v in value]
        if isinstance(value, dict):
            return {k: self._process_value(v, encrypt) for k, v in value.items()}
        if isinstance(value, TrackableDto):
            return value.prepare_init_data(encrypt)
        return value

    def prepare_init_data(self, encrypt: bool = False) -> dict[str, Any]:
        return {
            k: self._process_value(v, encrypt)
            for k, v in self.model_dump().items()
            if not k.startswith("_")
        }

    def prepare_changed_data(self, encrypt: bool = False) -> dict[str, Any]:
        return {
            k: self._process_value(v, encrypt)
            for k, v in self.changed_data.items()
            if not k.startswith("_")
        }
