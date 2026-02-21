"""核心服务层 - 封装业务逻辑供 Controller 调用"""
from wjx.core.services.survey_service import parse_survey
from wjx.core.services.proxy_service import prefetch_proxy_pool

__all__ = [
    "parse_survey",
    "prefetch_proxy_pool",
]
