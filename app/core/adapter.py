import logging
from typing import Optional, Type, TypeVar

from aiogram_dialog import DialogManager
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class DialogDataAdapter:
    def __init__(self, dialog_manager: DialogManager) -> None:
        self.dialog_manager = dialog_manager

    def load(self, model_cls: Type[T]) -> Optional[T]:
        key = model_cls.__name__.lower()
        raw = self.dialog_manager.dialog_data.get(key)
        if raw is None:
            return None
        try:
            return model_cls.model_validate(raw)
        except ValidationError:
            return None

    def save(self, model: BaseModel) -> dict:
        key = model.__class__.__name__.lower()
        data = model.model_dump()
        try:
            self.dialog_manager.dialog_data[key] = data
            logger.debug(f"Saved model '{key}' data successfully")
        except Exception as exception:
            logger.error(f"Error saving model '{key}': {exception}")
        return data
