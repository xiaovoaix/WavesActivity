from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.sv import SV, get_plugin_available_prefix

from ..utils.database.models import WavesBind, WavesLivenessRecord
from ..utils.api.requests import waves_api
from .waves_activity_config import WavesActivityConfig

sv_rover_reminder = SV("WavesActivity配置")

PREFIX = get_plugin_available_prefix("WavesActivity")


@sv_rover_reminder.on_prefix(("开启", "关闭"))
async def switch_liveness_push(bot: Bot, ev: Event):
    if ev.text not in ("活跃度推送",):
        return

    at_sender = bool(ev.group_id)

    if not WavesActivityConfig.get_config("EnableLivenessPush").data:
        msg = "活跃度推送功能未开启，请管理员先在配置中启用"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    if not ev.group_id:
        msg = "活跃度推送需要在群聊中使用，Bot 将在当前群内通知您"
        return await bot.send(msg)

    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if uid is None:
        msg = f"您还未绑定鸣潮特征码，请使用【{PREFIX}绑定uid】完成绑定！"
        return await bot.send(" " + msg, at_sender)

    ck = await waves_api.get_self_waves_ck(uid, ev.user_id, ev.bot_id)
    try:
        await WavesLivenessRecord.upsert_user_settings(
            user_id=ev.user_id,
            bot_id=ev.bot_id,
            bot_self_id=ev.bot_self_id or "",
            uid=uid,
            is_ck_valid=bool(ck),
        )
    except Exception:
        logger.exception("[WavesActivity] 更新CK有效状态失败")

    if not ck:
        msg = f"uid {uid} 登录状态无效！请重新登录后再设置推送"
        return await bot.send(" " + msg, at_sender)

    enable = "开启" in ev.command
    logger.info(f"[WavesActivity] [{ev.user_id}] 尝试[{'开启' if enable else '关闭'}]了[活跃度推送]")

    if enable:
        await WavesLivenessRecord.upsert_user_settings(
            user_id=ev.user_id,
            bot_id=ev.bot_id,
            bot_self_id=ev.bot_self_id or "",
            uid=uid,
            liveness_push_switch="on",
            group_id=ev.group_id,
        )
        msg = (
            f"uid {uid} 已开启活跃度推送！\n"
            f"将在每日 {WavesActivityConfig.get_config('LivenessPushTime').data} "
            f"检查活跃度，不足时会在本群@您"
        )
    else:
        await WavesLivenessRecord.upsert_user_settings(
            user_id=ev.user_id,
            bot_id=ev.bot_id,
            bot_self_id=ev.bot_self_id or "",
            uid=uid,
            liveness_push_switch="off",
        )
        msg = f"uid {uid} 已关闭活跃度推送！"

    await bot.send(" " + msg, at_sender)


@sv_rover_reminder.on_prefix(("活跃度阈值", "推送阈值"))
async def set_liveness_threshold(bot: Bot, ev: Event):
    at_sender = bool(ev.group_id)
    raw_value = ev.text.strip()
    if not raw_value.isdigit():
        msg = f"请输入正确的活跃度阈值（1~100），例如【{PREFIX}活跃度阈值 80】"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    value = int(raw_value)
    if value < 1 or value > 100:
        msg = "活跃度阈值范围为 1~100"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if uid is None:
        msg = f"您还未绑定鸣潮特征码，请使用【{PREFIX}绑定uid】完成绑定！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    ck = await waves_api.get_self_waves_ck(uid, ev.user_id, ev.bot_id)
    if not ck:
        msg = f"uid {uid} 登录状态无效，请重新登录后再设置阈值"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    await WavesLivenessRecord.upsert_user_settings(
        user_id=ev.user_id,
        bot_id=ev.bot_id,
        bot_self_id=ev.bot_self_id or "",
        uid=uid,
        liveness_threshold=value,
    )
    msg = f"uid {uid} 活跃度提醒阈值已设置为 {value}（低于此值将收到通知）"
    return await bot.send((" " if at_sender else "") + msg, at_sender)
