import asyncio
from datetime import datetime
from typing import List, Set

from gsuid_core.aps import scheduler
from gsuid_core.bot import Bot
from gsuid_core.gss import gss
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.sv import SV

from ..utils.api.model import DailyData
from ..utils.api.request_util import KuroApiResp
from ..utils.api.requests import waves_api
from ..utils.database.models import WavesLivenessRecord
from ..utils.status_store import record_fail, record_success
from ..waves_activity_config.waves_activity_config import WavesActivityConfig

_check_lock = asyncio.Lock()

sv_WavesActivityPush = SV("WavesActivity推送")


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _parse_push_times(push_time_str: str) -> List[tuple]:
    """解析推送时间字符串，返回 (hour, minute) 列表"""
    results = []
    for slot in push_time_str.split(","):
        slot = slot.strip()
        if not slot:
            continue
        try:
            h, m = [int(x) for x in slot.split(":")]
            if 0 <= h <= 23 and 0 <= m <= 59:
                results.append((h, m))
            else:
                logger.warning(f"[WavesActivity] 推送时间超出范围: {slot!r}，跳过")
        except Exception:
            logger.warning(f"[WavesActivity] 推送时间格式错误: {slot!r}，跳过")
    return results


def _get_push_time_set() -> Set[str]:
    """返回当前配置的推送时间集合，格式为 {'HH:MM', ...}"""
    push_time_str = WavesActivityConfig.get_config("LivenessPushTime").data
    slots = _parse_push_times(push_time_str)
    return {f"{h:02d}:{m:02d}" for h, m in slots}


# ── 活跃度查询与通知 ──────────────────────────────────────────────────────────

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
        logger.info(f"[WavesActivity] uid={uid} 每日信息查询失败")
        return None

    daily_info = DailyData.model_validate(daily_info_res.data)
    if not daily_info.livenessData:
        logger.info(f"[WavesActivity] uid={uid} 活跃度数据为空")
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


async def _handle_record(record: WavesLivenessRecord, threshold_default: int) -> None:
    if not record.uid:
        return

    if record.liveness_push_switch != "on":
        logger.debug(f"[WavesActivity] 跳过 uid={record.uid}：推送未开启")
        return

    if not record.group_id:
        logger.info(f"[WavesActivity] 跳过 uid={record.uid}：未设置通知群组")
        return

    threshold = record.liveness_threshold if record.liveness_threshold is not None else threshold_default
    threshold = max(1, min(100, threshold))

    result = await _query_liveness(record.uid, record.user_id, record.bot_id)
    if result is None:
        logger.info(f"[WavesActivity] uid={record.uid} 活跃度查询失败，跳过")
        record_fail()
        return

    liveness_cur, liveness_total = result
    logger.info(
        f"[WavesActivity] uid={record.uid} 活跃度={liveness_cur}/{liveness_total} 阈值={threshold}"
    )

    if liveness_cur >= threshold:
        logger.info(f"[WavesActivity] uid={record.uid} 活跃度已达标，不通知")
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
            logger.info(
                f"[WavesActivity] uid={record.uid} 群 {record.group_id} 通知发送成功 "
                f"活跃度={liveness_cur}/{liveness_total}"
            )
            break
        except Exception as e:
            logger.warning(f"[WavesActivity] uid={record.uid} 群 {record.group_id} 通知发送失败: {e}")

    if sent:
        record_success()
    else:
        record_fail()


async def _run_liveness_check():
    """执行完整的活跃度检查流程（有锁保护，防止并发）"""
    if _check_lock.locked():
        logger.info("[WavesActivity] 活跃度检查跳过：已有任务运行中")
        return

    async with _check_lock:
        if not WavesActivityConfig.get_config("EnableLivenessPush").data:
            logger.info("[WavesActivity] 活跃度检查跳过：EnableLivenessPush 未开启，请在配置中启用")
            return

        try:
            records: List[WavesLivenessRecord] = await WavesLivenessRecord.get_all_push_on_records()
        except Exception:
            logger.exception("[WavesActivity] 查询活跃度推送记录失败")
            return

        if not records:
            logger.info("[WavesActivity] 活跃度检查结束：无开启推送的记录")
            return

        threshold_default = WavesActivityConfig.get_config("LivenessThreshold").data
        logger.info(
            f"[WavesActivity] 开始活跃度检查，记录数={len(records)} 默认阈值={threshold_default}"
        )

        for record in records:
            try:
                await _handle_record(record, threshold_default)
            except Exception:
                logger.exception(f"[WavesActivity] 处理记录失败 uid={record.uid}")
            await asyncio.sleep(0.5)

        logger.info("[WavesActivity] 活跃度检查完成")


# ── 定时任务：每分钟检查一次是否到达推送时间 ──────────────────────────────────

@scheduler.scheduled_job("cron", minute="*", id="waves_activity_minute_tick")
async def waves_activity_minute_tick():
    """每分钟触发，检查当前时间是否为配置的推送时间之一"""
    now = datetime.now()
    current_hhmm = f"{now.hour:02d}:{now.minute:02d}"

    push_times = _get_push_time_set()
    if not push_times:
        return

    if current_hhmm not in push_times:
        return  # 不是推送时间，静默返回

    logger.info(f"[WavesActivity] 到达推送时间 {current_hhmm}，触发活跃度检查")
    await _run_liveness_check()


# ── 指令 ─────────────────────────────────────────────────────────────────────

@sv_WavesActivityPush.on_fullmatch("手动检查活跃度")
async def manual_liveness_check(bot: Bot, ev: Event):
    """手动触发活跃度检查（调试用）"""
    logger.info(f"[WavesActivity] [{ev.user_id}] 手动触发活跃度检查")
    await bot.send("正在手动触发活跃度检查，请查看日志...")
    await _run_liveness_check()
    await bot.send("活跃度检查完成")


@sv_WavesActivityPush.on_fullmatch("查看推送时间")
async def show_push_times(bot: Bot, ev: Event):
    """查看当前配置的推送时间（调试用）"""
    push_time_str = WavesActivityConfig.get_config("LivenessPushTime").data
    slots = _parse_push_times(push_time_str)
    enabled = WavesActivityConfig.get_config("EnableLivenessPush").data

    if not slots:
        msg = f"⚠️ 当前推送时间配置无效：{push_time_str!r}\n请检查格式，例如：12:00,18:00,22:00"
    else:
        times_str = "、".join(f"{h:02d}:{m:02d}" for h, m in slots)
        now_str = datetime.now().strftime("%H:%M")
        msg = (
            f"📅 当前推送时间配置：{times_str}\n"
            f"🔧 推送总开关：{'已开启' if enabled else '❌ 未开启'}\n"
            f"🕐 当前时间：{now_str}"
        )
    await bot.send(msg)
