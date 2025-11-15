import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Set

import httpx
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astrbot.api.all import (
    register, command, Context, Star, AstrMessageEvent,
    MessageChain, Plain, logger
)

from astrbot.api.star import StarTools


MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


def _ts():
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")


def format_article_url(lang: str, version_id: str) -> str:
    vid = (version_id or "").lower()
    if any(tag in vid for tag in ["w", "pre", "rc"]):
        slug = vid.replace(" ", "").replace("_", "-")
        return f"https://www.minecraft.net/{lang}/article/minecraft-snapshot-{slug}"
    return ""


class State:
    def __init__(self, path: Path):
        self.path = path
        self.last_snapshot_id: Optional[str] = None
        self.last_release_id: Optional[str] = None
        self.targets: Set[str] = set()
        self.etag: Optional[str] = None

    def load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text("utf-8"))
            self.last_snapshot_id = data.get("last_snapshot_id")
            self.last_release_id = data.get("last_release_id")
            self.targets = set(data.get("targets", []))
            self.etag = data.get("etag")
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"{_ts()} state 文件异常：{e}")

    def save(self):
        data = {
            "last_snapshot_id": self.last_snapshot_id,
            "last_release_id": self.last_release_id,
            "targets": list(self.targets),
            "etag": self.etag,
        }
        try:
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        except OSError as e:
            logger.warning(f"{_ts()} state 写入失败：{e}")


@register(
    "astrbot_plugin_mcwatcher",
    "noname2309-bot",
    "MCWatcher 是一个基于 AstrBot 的插件，用于 自动监测 Mojang 的最新 Minecraft 版本",
    "0.2.4",
    "https://github.com/wadadawsd/astrbot_plugin_mcwatcher"
)
class MCWatcher(Star):

    def __init__(self, context: Context, config: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__(context)

        # 保证 config 必为 dict
        self.config: Dict[str, Any] = config or {}
        self.ctx = context

        def cfg(key: str, default):
            return self.config.get(key, default)

        self.poll_seconds = int(cfg("interval_seconds", cfg("poll_seconds", 120)))
        self.tz_name = cfg("timezone", "Asia/Shanghai")
        self.watch_channels = set(cfg("watch_channels", ["snapshot"]))
        self.article_lang = cfg("mc_article_lang", "en-us")

        data_dir = Path(StarTools.get_data_dir("astrbot_plugin_mcwatcher"))
        data_dir.mkdir(parents=True, exist_ok=True)

        self.state = State(data_dir / "state.json")
        self.state.load()

        self._stop = False
        self._task = asyncio.create_task(self._poll_loop())

        logger.info(
            f"{_ts()} MCWatcher started. interval={self.poll_seconds}s tz={self.tz_name} watch={self.watch_channels}"
        )

    async def terminate(self):
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.state.save()

    # ========== 工具 ==========

    def _get_plain_text(self, event: AstrMessageEvent) -> str:
        """提取消息纯文本，捕获更具体异常"""
        try:
            mc = getattr(event, "message_chain", None)
            if mc:
                parts = []
                for seg in mc:
                    if isinstance(seg, Plain):
                        parts.append(getattr(seg, "text", "") or getattr(seg, "content", ""))
                return "".join(parts)
        except (AttributeError, TypeError) as e:
            logger.warning(f"Failed to parse plain text: {e}", exc_info=True)
        return ""

    def _parse_fake_version(self, raw: str, keyword: str, default_vid: str) -> str:
        """更健壮的 fake 参数解析"""
        toks = raw.replace("\u3000", " ").split()
        tokens_lower = [t.lower() for t in toks]

        # 形如：mcwatch fake 25w45a
        if keyword in tokens_lower:
            idx = tokens_lower.index(keyword)
            if idx + 1 < len(toks):
                return toks[idx + 1]
            return default_vid

        # 避免返回 toks[1] == "fake"
        if len(toks) <= 2:
            return default_vid

        # 假如输入：mcwatch fake 25w45a → 一般 toks[2] 为版本号
        return toks[2]

    # ========== 指令 ==========

    @command("mcwatch bind", alias={"mcwatch on", "mc订阅"})
    async def bind_here(self, event: AstrMessageEvent):
        sid = event.unified_msg_origin
        self.state.targets.add(sid)
        self.state.save()
        yield event.plain_result("已绑定本会话。")

    @command("mcwatch unbind", alias={"mcwatch off"})
    async def unbind_here(self, event: AstrMessageEvent):
        sid = event.unified_msg_origin
        if sid in self.state.targets:
            self.state.targets.remove(sid)
            self.state.save()
            yield event.plain_result("已取消绑定。")
        else:
            yield event.plain_result("本会话未绑定。")

    @command("mcwatch list")
    async def list_targets(self, event: AstrMessageEvent):
        if not self.state.targets:
            yield event.plain_result("暂无绑定会话。")
        else:
            yield event.plain_result("已绑定：\n" + "\n".join(sorted(self.state.targets)))

    @command("mcwatch now")
    async def check_now(self, event: AstrMessageEvent):
        await self._check_once(force_push=True)
        yield event.plain_result("OK，已主动检查一次。")

    # === fake 推送（仅当前会话，不广播） ===

    @command("mcwatch fake")
    async def fake_snapshot(self, event: AstrMessageEvent):
        raw = self._get_plain_text(event).strip()
        vid = self._parse_fake_version(raw, "fake", "25w45a")
        msg = self._build_message("snapshot", vid, datetime.now().isoformat())

        # 修复：只发到当前会话，不广播
        await self.ctx.send_message(event.unified_msg_origin, MessageChain([Plain(msg)]))

        yield event.plain_result(f"已模拟 snapshot 推送：{vid}")

    @command("mcwatch fake_release")
    async def fake_release(self, event: AstrMessageEvent):
        raw = self._get_plain_text(event).strip()
        vid = self._parse_fake_version(raw, "fake_release", "1.21.3")
        msg = self._build_message("release", vid, datetime.now().isoformat())

        # 修复：只发到当前会话，不广播
        await self.ctx.send_message(event.unified_msg_origin, MessageChain([Plain(msg)]))

        yield event.plain_result(f"已模拟 release 推送：{vid}")

    # ========== 轮询 ==========

    async def _poll_loop(self):
        try:
            await self._check_once(force_push=False)
        except Exception as e:
            logger.warning(f"MCWatcher 首次检查异常：{e}", exc_info=True)

        while not self._stop:
            try:
                await asyncio.sleep(self.poll_seconds)
                await self._check_once(force_push=False)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"MCWatcher loop error: {e}", exc_info=True)

    async def _fetch_manifest(self, ignore_cache: bool = False):
        headers = {}
        if not ignore_cache and self.state.etag:
            headers["If-None-Match"] = self.state.etag

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(MANIFEST_URL, headers=headers)

            if resp.status_code == 304:
                return None

            resp.raise_for_status()

            etag = resp.headers.get("ETag")
            if etag:
                self.state.etag = etag
                self.state.save()

            return resp.json()

    async def _check_once(self, force_push: bool):
        data = await self._fetch_manifest(ignore_cache=force_push)
        if data is None and not force_push:
            return

        latest = (data or {}).get("latest", {})
        msgs = []

        if "snapshot" in self.watch_channels:
            sid = latest.get("snapshot")
            if sid and sid != self.state.last_snapshot_id:
                t = self._lookup_release_time(data, sid)
                msgs.append(self._build_message("snapshot", sid, t))
                self.state.last_snapshot_id = sid

        if "release" in self.watch_channels:
            rid = latest.get("release")
            if rid and rid != self.state.last_release_id:
                t = self._lookup_release_time(data, rid)
                msgs.append(self._build_message("release", rid, t))
                self.state.last_release_id = rid

        if msgs:
            self.state.save()
            await self._broadcast("\n\n".join(msgs), self.state.targets)

    def _lookup_release_time(self, data: Optional[Dict[str, Any]], vid: str):
        if not data:
            return None
        for v in data.get("versions", []):
            if v.get("id") == vid:
                return v.get("releaseTime")
        return None

    def _build_message(self, vtype: str, vid: str, release_iso: Optional[str]):
        dt_str = "未知时间"
        if release_iso:
            try:
                dt = datetime.fromisoformat(
                    release_iso.replace("Z", "+00:00")
                ).astimezone(ZoneInfo(self.tz_name))
                dt_str = dt.strftime("%Y-%m-%d %H:%M:%S %z")
            except (ValueError, ZoneInfoNotFoundError):
                dt_str = release_iso

        article = format_article_url(self.article_lang, vid) if vtype == "snapshot" else ""

        lines = [
            f"MC 更新：{vid} ({vtype})",
            f"时间：{dt_str}"
        ]
        if article:
            lines.append(f"日志：{article}")

        return "\n".join(lines)

    # ========== 高性能并发广播（正式推送） ==========

    async def _broadcast(self, text: str, targets: Set[str]):
        if not targets:
            return

        mc = MessageChain([Plain(text)])
        sid_list = list(targets)

        tasks = [self.ctx.send_message(sid, mc) for sid in sid_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        ok = 0
        for sid, result in zip(sid_list, results):
            if isinstance(result, Exception):
                logger.warning(f"{_ts()} 推送失败 {sid}: {result}", exc_info=True)
            elif result:
                ok += 1

        logger.info(f"{_ts()} MCWatcher 已推送 {ok}/{len(targets)} 个会话。")





