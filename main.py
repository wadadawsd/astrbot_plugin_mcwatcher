

def format_article_url(lang: str, version_id: str) -> str:
    vid = version_id.lower()
    vid = (version_id or "").lower()
    if any(tag in vid for tag in ["w", "pre", "rc"]):
        slug = vid.replace(" ", "").replace("_", "-")
        return f"https://www.minecraft.net/{lang}/article/minecraft-snapshot-{slug}"
@@ -59,7 +59,7 @@ def save(self):
@register(
    "astrbot_plugin_mcwatcher", "you",
    "自动监听 Minecraft 版本更新并转发（支持 snapshot / release）",
    "0.2.1", "https://github.com/you/astrbot_plugin_mcwatcher"
    "0.2.2", "https://github.com/you/astrbot_plugin_mcwatcher"
)
class MCWatcher(Star):
    def __init__(self, context: Context, config: Optional[Dict[str, Any]] = None, **kwargs):
@@ -72,7 +72,7 @@ def __init__(self, context: Context, config: Optional[Dict[str, Any]] = None, **
        self.ctx = context
        self.config = config or {}

        # 统一配置读取函数
        # 统一配置读取
        def cfg(key: str, default):
            if isinstance(self.config, dict):
                return self.config.get(key, default)
@@ -81,17 +81,19 @@ def cfg(key: str, default):
                return self.config.get(key, default)
            return default

        # 从配置读取参数
        # 配置
        self.poll_seconds = int(cfg("interval_seconds", cfg("poll_seconds", 120)))
        self.tz_name = cfg("timezone", "Asia/Shanghai")
        self.watch_channels = set(cfg("watch_channels", ["snapshot"]))
        self.article_lang = cfg("mc_article_lang", "en-us")

        # 数据目录与状态
        data_dir = Path(StarTools.get_data_dir("astrbot_plugin_mcwatcher"))
        data_dir.mkdir(parents=True, exist_ok=True)
        self.state = State(data_dir / "state.json")
        self.state.load()

        # 轮询任务
        self._stop = False
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"{_ts()} MCWatcher started. interval={self.poll_seconds}s tz={self.tz_name} watch={self.watch_channels}")
@@ -106,7 +108,24 @@ async def terminate(self):
        self.state.save()
        logger.info(f"{_ts()} MCWatcher terminated.")

    # ========== 指令 ==========
    # ========= 工具 =========
    def _get_plain_text(self, event: AstrMessageEvent) -> str:
        """
        从消息事件中提取纯文本（兼容 aiocqhttp 等适配器：遍历 message_chain 的 Plain 片段）
        """
        try:
            mc = getattr(event, "message_chain", None)
            if mc:
                parts = []
                for seg in mc:
                    if isinstance(seg, Plain):
                        parts.append(getattr(seg, "text", "") or getattr(seg, "content", ""))
                return "".join(parts)
        except Exception:
            pass
        return ""

    # ========= 指令 =========
    @command("mcwatch bind", alias={"mcwatch on", "mc订阅"})
    async def bind_here(self, event: AstrMessageEvent):
        sid = event.unified_msg_origin
@@ -137,24 +156,40 @@ async def check_now(self, event: AstrMessageEvent):
        await self._check_once(force_push=True)
        yield event.plain_result("OK，已主动检查一次。")

    # 开发/调试：模拟推送（无需改 state.json）
    # 开发/调试：模拟推送（无需修改 state.json）
    @command("mcwatch fake")
    async def fake_snapshot(self, event: AstrMessageEvent):
        parts = (event.plain_text or "").strip().split()
        vid = parts[1] if len(parts) > 1 else "25w45a"
        raw = (self._get_plain_text(event) or "").strip()

        def parse_vid(s: str, default_vid: str) -> str:
            toks = s.replace("\u3000", " ").split()
            for i, t in enumerate(toks):
                if t.lower() == "fake":
                    return toks[i + 1] if i + 1 < len(toks) else default_vid
            return toks[0] if toks else default_vid

        vid = parse_vid(raw, "25w45a")
        msg = self._build_message("snapshot", vid, datetime.now().isoformat())
        await self._broadcast(msg, self.state.targets)
        yield event.plain_result(f"已模拟 snapshot 推送：{vid}")

    @command("mcwatch fake_release")
    async def fake_release(self, event: AstrMessageEvent):
        parts = (event.plain_text or "").strip().split()
        vid = parts[1] if len(parts) > 1 else "1.21.3"
        raw = (self._get_plain_text(event) or "").strip()

        def parse_vid(s: str, default_vid: str) -> str:
            toks = s.replace("\u3000", " ").split()
            for i, t in enumerate(toks):
                if t.lower() == "fake_release":
                    return toks[i + 1] if i + 1 < len(toks) else default_vid
            return toks[0] if toks else default_vid

        vid = parse_vid(raw, "1.21.3")
        msg = self._build_message("release", vid, datetime.now().isoformat())
        await self._broadcast(msg, self.state.targets)
        yield event.plain_result(f"已模拟 release 推送：{vid}")

    # ========== 轮询 ==========
    # ========= 轮询 =========
    async def _poll_loop(self):
        try:
            await self._check_once(force_push=False)
@@ -169,7 +204,7 @@ async def _poll_loop(self):
            except Exception as e:
                logger.warning(f"MCWatcher loop error: {e}", exc_info=True)

    # === 补丁：支持忽略缓存，避免 304 导致 latest 为空 ===
    # 补丁：支持忽略缓存，避免 304 导致 latest 为空
    async def _fetch_manifest(self, ignore_cache: bool = False) -> Optional[Dict[str, Any]]:
        headers = {}
        if (not ignore_cache) and self.state.etag:
@@ -187,7 +222,7 @@ async def _fetch_manifest(self, ignore_cache: bool = False) -> Optional[Dict[str
            return resp.json()

    async def _check_once(self, force_push: bool):
        # 补丁：强制检查时忽略缓存，确保拿到 latest
        # 强制检查时忽略缓存，确保拿到 latest
        data = await self._fetch_manifest(ignore_cache=force_push)
        if data is None and not force_push:
            return
@@ -252,3 +287,5 @@ async def _broadcast(self, text: str, targets: set[str]):
        logger.info(f"{_ts()} MCWatcher pushed to {ok}/{len(targets)} targets.")





