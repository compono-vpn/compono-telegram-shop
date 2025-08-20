from sqlalchemy.ext.asyncio import AsyncSession

from .base import BaseRepository
from .payment_gateway import PaymentGatewayRepository
from .plan import PlanRepository
from .promocode import PromocodeRepository
from .user import UserRepository


class RepositoriesFacade(BaseRepository):
    gateways: PaymentGatewayRepository
    users: UserRepository
    promocodes: PromocodeRepository
    plans: PlanRepository

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session=session)
        self.gateways = PaymentGatewayRepository(session=session)
        self.users = UserRepository(session=session)
        self.promocodes = PromocodeRepository(session=session)
        self.plans = PlanRepository(session=session)
