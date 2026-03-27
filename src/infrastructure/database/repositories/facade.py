from sqlalchemy.ext.asyncio import AsyncSession

from .broadcast import BroadcastRepository
from .customer import CustomerRepository
from .payment_gateway import PaymentGatewayRepository
from .plan import PlanRepository
from .promocode import PromocodeRepository
from .referral import ReferralRepository
from .settings import SettingsRepository
from .subscription import SubscriptionRepository
from .transaction import TransactionRepository
from .user import UserRepository
from .web_order import WebOrderRepository
from .webhook_log import WebhookLogRepository


class RepositoriesFacade:
    session: AsyncSession

    customers: CustomerRepository
    gateways: PaymentGatewayRepository
    plans: PlanRepository
    promocodes: PromocodeRepository
    subscriptions: SubscriptionRepository
    transactions: TransactionRepository
    users: UserRepository
    settings: SettingsRepository
    broadcasts: BroadcastRepository
    referrals: ReferralRepository
    web_orders: WebOrderRepository
    webhook_logs: WebhookLogRepository

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

        self.customers = CustomerRepository(session)
        self.gateways = PaymentGatewayRepository(session)
        self.plans = PlanRepository(session)
        self.promocodes = PromocodeRepository(session)
        self.subscriptions = SubscriptionRepository(session)
        self.transactions = TransactionRepository(session)
        self.users = UserRepository(session)
        self.settings = SettingsRepository(session)
        self.broadcasts = BroadcastRepository(session)
        self.referrals = ReferralRepository(session)
        self.web_orders = WebOrderRepository(session)
        self.webhook_logs = WebhookLogRepository(session)
