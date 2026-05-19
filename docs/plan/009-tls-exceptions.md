# 009 TLS 例外审计清单

> 本文件记录 NAStool 在默认恢复 TLS 证书校验（`verify=True`）后，本地自签名 HTTPS 客户端的兼容状态及回归方式。
> 配套 Plan：009-security-audit-remediation.md

---

## 本地 HTTPS 客户端 TLS 行为审计表

| 文件 | 调用点（行号） | 服务类型 | 配置来源 | 默认 verify | 例外理由 | 回归方式 |
|---|---|---|---|---|---|---|
| `app/mediaserver/client/jellyfin.py` | `get_item:76`, `get_items:95`, `get_user:114`, `get_librarys:141`, `get_webhook_schemes:160`, `get_item_path:196`, `get_local_image_by_id:216`, `get_resume:242`, `get_filter_items:293`, `get_library_items:346`, `get_item_count:376`, `get_play_url:420`, `get_webhook_message:510`, `get_user_library:527`, `get_playing_sessions:569`, `get_server_info:599`, `get_libraries:646` | Jellyfin | 无（使用 `RequestUtils()` 默认构造） | `True` | 本地自签名证书需用户配置正式证书或显式关闭 | 本地 Jellyfin 启用 HTTPS + 自签名证书；配置 `host` 为 `https://...`；验证媒体库列表获取是否正常；若证书校验失败，建议更换为正式证书 |
| `app/mediaserver/client/emby.py` | `get_item:79`, `get_items:98`, `get_user:117`, `get_librarys:170`, `get_webhook_schemes:188`, `get_item_path:208`, `get_local_image_by_id:243`, `get_resume:266`, `get_filter_items:292`, `get_library_items:344`, `get_item_count:397`, `get_play_url:427`, `get_playback_info:471`, `get_webhook_message:490`, `get_webhook_schemes:607`, `get_user_library:631`, `get_playing_sessions:666`, `get_server_info:736`, `get_libraries:791` | Emby | 无（使用 `RequestUtils()` 默认构造） | `True` | 本地自签名证书需用户配置正式证书或显式关闭 | 本地 Emby 启用 HTTPS + 自签名证书；配置 `host` 为 `https://...`；验证媒体库列表获取是否正常；若证书校验失败，建议更换为正式证书 |
| `app/mediaserver/client/plex.py` | N/A（使用 `plexapi` 库，不直接构造 `RequestUtils`/`requests`） | Plex | `plexapi` 内部管理 | `True`（由库内部默认） | 本地自签名证书需用户配置正式证书或显式关闭 | 本地 Plex 启用 HTTPS + 自签名证书；配置 `host` 为 `https://...`；`plexapi` 库内部处理证书；若失败请参考 plexapi 文档配置 `session.verify = False` |
| `app/downloader/client/qbittorrent.py` | N/A（使用 `qbittorrent-api` 库） | qBittorrent | `qbittorrent-api` 内部管理 | `True`（由库内部默认） | 本地自签名证书需用户配置正式证书或显式关闭 | 本地 qBittorrent Web UI 启用 HTTPS + 自签名证书；配置 `host` 为 `https://...`；`qbittorrent-api` 内部处理证书 |
| `app/downloader/client/transmission.py` | `trc.verify_torrent:564`（`transmission-rpc` 库内部） | Transmission | `transmission-rpc` 内部管理 | `True`（由库内部默认） | 本地自签名证书需用户配置正式证书或显式关闭 | 本地 Transmission RPC 启用 HTTPS + 自签名证书；配置 `host` 为 `https://...`；`transmission-rpc` 内部处理证书 |

---

## 说明

1. **Jellyfin / Emby** 直接通过 `RequestUtils()` 默认构造发起 HTTPS 请求。由于 `RequestUtils` 在 Task 5.1 中已改为默认 `verify=True`，若用户配置的 `host` 使用 `https://` 且为自签名证书，请求将因证书校验失败而报错。
2. **Plex / qBittorrent / Transmission** 依赖第三方库（`plexapi` / `qbittorrent-api` / `transmission-rpc`），不直接构造 `RequestUtils` 或 `requests` 调用，证书校验由各自库内部管理。
3. 当前代码中**没有任何位置**显式传入 `verify=False` 给 `RequestUtils` 或 `requests`（公共互联网服务方向）。所有剩余的 `verify=False` 风险仅存在于上述本地客户端的隐式场景中。
4. 由于 Jellyfin/Emby 的配置界面目前未提供 `cert_verify` 开关，短期 workaround 为：使用 HTTP 而非 HTTPS（内网部署常见），或配置正式域名证书（Let's Encrypt 等）。

---

## 迁移指南（对使用自签名证书的用户）

### 方案 A：使用 HTTP（推荐，内网部署）
将 Media Server / Downloader 的 `host` 配置从 `https://...` 改为 `http://...`。内网环境下 HTTP 是安全且常见的选择。

### 方案 B：配置正式证书
为本地服务配置由受信任 CA 签发的证书（如 Let's Encrypt）。

### 方案 C：代码级临时关闭（不推荐，仅应急）
如需临时关闭 Jellyfin/Emby 的 TLS 校验，可在对应客户端的 `RequestUtils()` 调用处显式传入 `verify=False`，例如：
```python
res = RequestUtils(verify=False).get_res(req_url)
```
此修改属于本地补丁，不会进入主线代码。
