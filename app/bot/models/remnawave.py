from pydantic import BaseModel


class SystemData(BaseModel):
    cpu_cores: int
    cpu_threads: int
    ram_used: str
    ram_total: str
    ram_used_percent: str
    uptime: str


# TODO: Вынести нахуй в роутеры
