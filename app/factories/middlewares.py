from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from app.core.config import AppConfig

from fluent.runtime import FluentLocalization, FluentResourceLoader

from app.bot.middlewares import (
    ErrorMiddleware,
    GarbageMiddleware,
    I18nMiddleware,
    MaintenanceMiddleware,
    ThrottlingMiddleware,
    UserMiddleware,
)
from app.bot.middlewares.base import EventTypedMiddleware
from app.core.constants import RESOURCE_I18N


class Middlewares(NamedTuple):
    outer: list[EventTypedMiddleware]
    inner: list[EventTypedMiddleware]


def create_i18n_middleware(config: AppConfig) -> I18nMiddleware:
    loader = FluentResourceLoader(roots=f"{config.i18n.locales_dir}/{{locale}}")
    locales = {
        locale: FluentLocalization(
            locales=[locale, config.i18n.default_locale],
            resource_ids=RESOURCE_I18N,
            resource_loader=loader,
        )
        for locale in config.i18n.locales
    }
    return I18nMiddleware(locales=locales, default_locale=config.i18n.default_locale)


def create_middlewares(config: AppConfig) -> Middlewares:
    i18n_middleware = create_i18n_middleware(config)
    error_middleware = ErrorMiddleware()
    user_middleware = UserMiddleware()
    throttling_middleware = ThrottlingMiddleware()
    maintenance_middleware = MaintenanceMiddleware()
    garbage_middleware = GarbageMiddleware()
    # TODO: Implement middleware for global user lookup
    # TODO: Implement middleware for action auditing

    # NOTE: Order matters!
    outer_middlewares = [
        error_middleware,
        user_middleware,
        throttling_middleware,
        maintenance_middleware,
    ]
    inner_middlewares = [
        i18n_middleware,
        garbage_middleware,
    ]

    return Middlewares(outer=outer_middlewares, inner=inner_middlewares)
