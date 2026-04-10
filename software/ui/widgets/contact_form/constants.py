"""联系表单常量。"""
from decimal import Decimal

REQUEST_MESSAGE_TYPE = "额度申请"
PAYMENT_METHOD_OPTIONS = ("微信", "支付宝")
DONATION_AMOUNT_OPTIONS = ["8.88", "11.45", "20.26", "50", "78.91", "114.51"]
DONATION_AMOUNT_BLOCK_MESSAGE = "该金额下开发者已亏本💔"
MAX_REQUEST_QUOTA = 19999
REQUEST_QUOTA_STEP = Decimal("0.5")
DONATION_AMOUNT_RULES = [
    (Decimal("13000"), Decimal("114.51")),
    (Decimal("8000"), Decimal("78.91")),
    (Decimal("3500"), Decimal("50")),
    (Decimal("2000"), Decimal("20.26")),
    (Decimal("1500"), Decimal("11.45")),
]
