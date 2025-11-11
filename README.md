# MCWatcher — AstrBot 插件：Minecraft 更新实时推送器

**MCWatcher** 是一个基于 **AstrBot** 的插件，用于 **自动监测 Mojang 的最新 Minecraft 版本（Snapshot & Release）并第一时间推送到指定会话**。

当官方发布新版本时，MCWatcher 会自动抓取版本信息并推送：

---

## 功能特点

- ✅ **自动监控 Minecraft 清单（version_manifest_v2.json）**  
- ✅ **支持 Snapshot / Release 两种更新渠道**
- ✅ **自动推送至绑定会话（群聊、私聊均可）**
- ✅ **支持手动立即检查更新**
- ✅ **采用 ETag/Last-Modified 优化请求（减少不必要访问）**
- ✅ **持久化存储最新版本状态，不重复推送**
- ✅ **轻量运行、无侵入、即装即用**

---
## 使用方法

1. 在 AstrBot 插件管理中安装：
   ```
   https://github.com/wadadawsd/astrbot_plugin_mcwatcher.git
   ```
2. 在你希望接收推送的群或私聊中输入：
   ```
   mcwatch bind
   ```
   绑定成功后，这个会话就会在每次 Minecraft 更新时收到推送。

3. 可用命令如下：
   ```
   mcwatch bind              绑定当前会话
   mcwatch unbind            取消绑定
   mcwatch list              查看已绑定的会话
   mcwatch now               立即检查是否有新版本
   mcwatch fake [版本号]     模拟一次快照版推送（测试用）
   mcwatch fake_release [版本号] 模拟一次正式版推送（测试用）
   ```

   示例：
   ```
   mcwatch bind
   mcwatch now
   mcwatch fake 25w45a
   mcwatch fake_release 1.21.3
   ```

4. 插件会定时访问 Mojang 官方接口：
   ```
   https://piston-meta.mojang.com/mc/game/version_manifest_v2.json
   ```
   检测新版本发布后自动发送消息，包括版本号、发布时间和官网更新链接。

5. 如果出现提示：
   ```
   MCWatcher: 无推送目标，跳过广播。
   ```
   说明当前会话未绑定，请先执行 `mcwatch bind`。

## 主要配置（可在面板中修改）

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| interval_seconds | 300 | 自动检测间隔（秒） |
| timezone | Asia/Shanghai | 显示时间的时区 |
| watch_channels | ["snapshot"] | 监听类型，可同时设置 snapshot 和 release |
| mc_article_lang | en-us | 官方文章语言，如 zh-hans、en-us 等 |

---
