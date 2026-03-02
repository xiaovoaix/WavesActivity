import asyncio
from datetime import datetime
from typing import List

from gsuid_core.aps import scheduler
from gsuid_core.gss import gss
from gsuid_core.logger import logger
from gsuid_core.segment import MessageSegment

from ..utils.api.model import DailyData
from ..utils.api.request_util import KuroApiResp
from ..utils.api.requests import waves_api
from ..utils.database.models import WavesLivenessRecord
from ..utils.status_store import record_fail, record_success
from ..waves_activity_config.waves_activity_config import WavesActivityConfig

_check_lock = asyncio.Lock()


async def _query_liveness(uid: str, user_id: str, bot_id: str):
    """查询玩家的每日活跃度，返回 (liveness_cur, liveness_total) 或 None"""
    ck = await waves_api.get_self_waves_ck(uid, user_id, bot_id)
    if not ck:
        try:
            await WavesLivenessRecord.update_ck_valid(
                user_id=user_id,
                bot_id=bot_id,
                uid=uid,
                is_ck_valid=False,
            )
        except Exception:
            logger.exception("[WavesActivity] 更新CK有效状态失败")
        return None

    daily_info_res = await waves_api.get_daily_info(uid, ck)
    if not isinstance(daily_info_res, KuroApiResp) or not daily_info_res.success:
        logger.debug(f"[WavesActivity] uid={uid} 每日信息查询失败")
        return None

    daily_info = DailyData.model_validate(daily_info_res.data)
    if not daily_info.livenessData:
        logger.debug(f"[WavesActivity] uid={uid} 活跃度数据为空")
        return None

    try:
        await WavesLivenessRecord.update_ck_valid(
            user_id=user_id,
            bot_id=bot_id,
            uid=uid,
            is_ck_valid=True,
        )
    except Exception:
        logger.exception("[WavesActivity] 更新CK有效状态失败")

    return daily_info.livenessData.cur, daily_info.livenessData.total


async def _handle_record(record: WavesLivenessRecord, threshold_default: int, today_str: str) -> None:
    if not record.uid:
        return

    if record.liveness_push_switch != "on":
        logger.debug(f"[WavesActivity] 跳过 uid={record.uid}：推送未开启")
        return

    if not record.group_id:
        logger.debug(f"[WavesActivity] 跳过 uid={record.uid}：未设置通知群组")
        return

    # 今日已通知，跳过
    if record.liveness_last_notify_date == today_str:
        logger.debug(f"[WavesActivity] 跳过 uid={record.uid}：今日已发送通知")
        return

    threshold = record.liveness_threshold if record.liveness_threshold is not None else threshold_default
    threshold = max(1, min(100, threshold))

    result = await _query_liveness(record.uid, record.user_id, record.bot_id)
    if result is None:
        logger.debug(f"[WavesActivity] uid={record.uid} 活跃度查询失败，跳过")
        record_fail()
        return

    liveness_cur, liveness_total = result
    logger.debug(
        f"[WavesActivity] uid={record.uid} 活跃度={liveness_cur}/{liveness_total} 阈值={threshold}"
    )

    if liveness_cur >= threshold:
        logger.debug(f"[WavesActivity] uid={record.uid} 活跃度已达标，不通知")
        return

    # 活跃度不足，发送群内@通知
    msg = [
        MessageSegment.at(record.user_id),
        MessageSegment.text(
            f"\n⚠️ 鸣潮活跃度提醒\n"
            f"今日活跃度：{liveness_cur}/{liveness_total}\n"
            f"活跃度未达到 {threshold}，请及时完成每日任务！"
        ),
    ]

    sent = False
    for bot_id in gss.active_bot:
        try:
            await gss.active_bot[bot_id].target_send(
                msg,
                "group",
                record.group_id,
                record.bot_id,
                record.bot_self_id or "",
                "",
            )
            sent = True
            logger.debug(
                f"[WavesActivity] uid={record.uid} 群 {record.group_id} 通知发送成功 "
                f"活跃度={liveness_cur}/{liveness_total}"
            )
            break
        except Exception as e:
            logger.warning(f"[WavesActivity] uid={record.uid} 群 {record.group_id} 通知发送失败: {e}")

    if sent:
        record_success()
        try:
            await WavesLivenessRecord.update_last_notify_date(
                user_id=record.user_id,
                bot_id=record.bot_id,
                uid=record.uid,
                date_str=today_str,
            )
        except Exception:
            logger.exception("[WavesActivity] 更新最后通知日期失败")
    else:
        record_fail()


async def waves_activity_liveness_check_task():
    if _check_lock.locked():
        logger.debug("[WavesActivity] 定时检查跳过：已有任务运行中")
        return

    async with _check_lock:
        if not WavesActivityConfig.get_config("EnableLivenessPush").data:
            logger.debug("[WavesActivity] 定时检查跳过：活跃度推送未开启")
            return

        try:
            records: List[WavesLivenessRecord] = await WavesLivenessRecord.get_all_push_on_records()
        except Exception:
            logger.exception("[WavesActivity] 查询活跃度推送记录失败")
            return

        if not records:
            logger.debug("[WavesActivity] 定时检查结束：无开启推送的记录")
            return

        threshold_default = WavesActivityConfig.get_config("LivenessThreshold").data
        today_str = datetime.now().strftime("%Y-%m-%d")
        logger.info(
            f"[WavesActivity] 开始每日活跃度检查，记录数={len(records)} 默认阈值={threshold_default} 日期={today_str}"
        )

        for record in records:
            try:
                await _handle_record(record, threshold_default, today_str)
            except Exception:
                logger.exception(f"[WavesActivity] 处理记录失败 uid={record.uid}")
            await asyncio.sleep(0.5)

        logger.info("[WavesActivity] 每日活跃度检查完成")


def _register_liveness_job():
    """根据配置注册每日活跃度推送定时任务"""
    push_time_str = WavesActivityConfig.get_config("LivenessPushTime").data
    try:
        hour, minute = [int(x) for x in push_time_str.strip().split(":")]
    except Exception:
        logger.warning(f"[WavesActivity] 推送时间格式错误: {push_time_str!r}，使用默认 22:00")
        hour, minute = 22, 0

    scheduler.add_job(
        waves_activity_liveness_check_task,
        "cron",
        hour=hour,
        minute=minute,
        id="waves_activity_liveness_check",
        replace_existing=True,
    )
    logger.info(f"[WavesActivity] 活跃度推送定时任务已注册，每日 {hour:02d}:{minute:02d} 执行")


_register_liveness_job()
