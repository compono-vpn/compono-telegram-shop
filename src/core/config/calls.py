from .base import BaseConfig


class CallsConfig(BaseConfig, env_prefix="CALLS_"):
    beta_allowlist: str = ""

    @property
    def beta_allowlist_ids(self) -> frozenset[int]:
        ids: set[int] = set()
        for part in self.beta_allowlist.replace(" ", "").split(","):
            if not part:
                continue
            try:
                ids.add(int(part))
            except ValueError:
                continue
        return frozenset(ids)

    def is_beta_user(self, telegram_id: int) -> bool:
        return telegram_id in self.beta_allowlist_ids
