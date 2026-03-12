"""init"""

from gsuid_core.sv import Plugins
from gsuid_core.logger import logger

Plugins(name="WavesActivity", force_prefix=["ww"], allow_empty_prefix=False, alias=["wa"])

logger.info("[WavesActivity] 初始化插件...")

# 注册指令与定时任务
from . import waves_activity_config as _  # noqa: F401
from . import waves_activity_push as _  # noqa: F401
from . import waves_activity_status as _  # noqa: F401

logger.info("[WavesActivity] 插件初始化完成")
