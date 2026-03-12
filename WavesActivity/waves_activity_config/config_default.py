from typing import Dict

from gsuid_core.utils.plugins_config.models import GSC, GsBoolConfig, GsIntConfig, GsStrConfig

CONFIG_DEFAULT: Dict[str, GSC] = {
    "EnableLivenessPush": GsBoolConfig(
        "开启活跃度推送",
        "全局活跃度推送开关，关闭后所有玩家的推送均停止",
        False,
    ),
    "LivenessThreshold": GsIntConfig(
        "活跃度推送阈值",
        "活跃度低于该值时将在群内@通知玩家（鸣潮每日活跃度满值为100）",
        100,
        100,
    ),
    "LivenessPushTime": GsStrConfig(
        "活跃度推送时间",
        "每日推送检查时间，支持多个时间用英文逗号分隔，例如 12:00,18:00,22:00。修改后需重启生效",
        "22:00",
    ),
}
