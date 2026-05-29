"""Models package: import all to register with SQLAlchemy."""
from .user import User, Role  # noqa: F401
from .settings import Settings  # noqa: F401
from .client import Client, Car, CarBodyType, BODY_TYPE_LABELS  # noqa: F401
from .service import Service, ServiceCategory, ServicePackage  # noqa: F401
from .order import Order, OrderItem, OrderStatus, OrderPhoto  # noqa: F401
from .order_assignment import OrderAssignment  # noqa: F401
from .order_material import OrderMaterialPlan  # noqa: F401
from .payment import Payment, PaymentMethod, PaymentStatus  # noqa: F401
from .azericard import AzericardPaymentIntent, AzericardLog, AzericardIntentStatus  # noqa: F401
from .cash_expense import CashExpense  # noqa: F401
from .bonus import BonusWallet, BonusTransaction  # noqa: F401
from .inventory import InventoryItem, InventoryMovement  # noqa: F401
from .employee import Employee, Salary  # noqa: F401
from .branch import Branch  # noqa: F401
from .audit import AuditLog  # noqa: F401
from .wa_template import WaMessageTemplate  # noqa: F401
