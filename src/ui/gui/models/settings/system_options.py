"""系统选项：设备 ID、网络、MQTT、音乐、AEC."""


from src.logging import get_logger

logger = get_logger()

class SettingsSystemOptionsMixin:
    # ========== 系统选项 ==========

    # CLIENT_ID
    def _get_clientId(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.CLIENT_ID", "")

    def _set_clientId(self, value: str):
        self._set_value("SYSTEM_OPTIONS.CLIENT_ID", value)

    # DEVICE_ID
    def _get_deviceId(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.DEVICE_ID", "")

    def _set_deviceId(self, value: str):
        self._set_value("SYSTEM_OPTIONS.DEVICE_ID", value)

    # OTA_VERSION_URL
    def _get_otaUrl(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.NETWORK.OTA_VERSION_URL", "")

    def _set_otaUrl(self, value: str):
        self._set_value("SYSTEM_OPTIONS.NETWORK.OTA_VERSION_URL", value)

    # WEBSOCKET_URL
    def _get_websocketUrl(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL", "")

    def _set_websocketUrl(self, value: str):
        self._set_value("SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL", value)

    # WEBSOCKET_ACCESS_TOKEN
    def _get_websocketToken(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.NETWORK.WEBSOCKET_ACCESS_TOKEN", "")

    def _set_websocketToken(self, value: str):
        self._set_value("SYSTEM_OPTIONS.NETWORK.WEBSOCKET_ACCESS_TOKEN", value)

    # AUTHORIZATION_URL
    def _get_authorizationUrl(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.NETWORK.AUTHORIZATION_URL", "")

    def _set_authorizationUrl(self, value: str):
        self._set_value("SYSTEM_OPTIONS.NETWORK.AUTHORIZATION_URL", value)

    # ACTIVATION_VERSION
    def _get_activationVersion(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.NETWORK.ACTIVATION_VERSION", "v1")

    def _set_activationVersion(self, value: str):
        self._set_value("SYSTEM_OPTIONS.NETWORK.ACTIVATION_VERSION", value)

    # WINDOW_SIZE_MODE
    def _get_windowSizeMode(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.WINDOW_SIZE_MODE", "default")

    def _set_windowSizeMode(self, value: str):
        self._set_value("SYSTEM_OPTIONS.WINDOW_SIZE_MODE", value)

    # QQ 音乐配置与扫码登录状态
    def _get_musicDefaultQuality(self) -> str:
        return self._get_value("MUSIC.DEFAULT_QUALITY", "320k")

    def _set_musicDefaultQuality(self, value: str):
        self._set_value("MUSIC.DEFAULT_QUALITY", value)

    def _get_qqMusicLoginStatus(self) -> str:
        credential = self._get_value("MUSIC.QQ_CREDENTIAL", {}) or {}
        music_id = credential.get("musicid") if isinstance(credential, dict) else None
        return f"已登录（MusicID: {music_id}）" if music_id else "未登录"

    def _get_qqMusicLoginBusy(self) -> bool:
        return bool(getattr(self, "_qq_music_login_busy", False))

    def _get_qqMusicQrSource(self) -> str:
        return getattr(self, "_qq_music_qr_source", "")

    def _set_qq_music_login_state(
        self, *, busy: bool | None = None, qr_source: str | None = None
    ) -> None:
        if busy is not None:
            self._qq_music_login_busy = busy
        if qr_source is not None:
            self._qq_music_qr_source = qr_source
        self.qqMusicLoginChanged.emit()

    def _start_qq_music_login(self, login_type: str) -> None:
        if self._get_qqMusicLoginBusy():
            self.statusMessage.emit("QQ 音乐登录正在进行中")
            return

        task_manager = getattr(self, "_task_manager", None)
        if task_manager is None:
            self.statusMessage.emit("当前运行模式不支持扫码登录")
            return

        async def _login():
            import base64

            from qqmusic_api import Client
            from qqmusic_api.models.login import QRCodeLoginEvents, QRLoginType
            from qqmusic_api.modules.login_utils import QRCodeLoginSession

            qr_type = QRLoginType(login_type)
            async with Client() as client:
                session = QRCodeLoginSession(
                    client.login, qr_type, interval=1.5, timeout_seconds=180
                )
                qr = await session.get_qrcode()
                source = (
                    f"data:{qr.mimetype or 'image/png'};base64,"
                    f"{base64.b64encode(qr.data).decode('ascii')}"
                )
                self._schedule_ui(
                    lambda: self._set_qq_music_login_state(qr_source=source)
                )
                self._schedule_ui(
                    lambda: self.statusMessage.emit("请扫码并在手机上确认登录")
                )

                async for result in session.iter_events():
                    if result.event == QRCodeLoginEvents.CONF:
                        self._schedule_ui(
                            lambda: self.statusMessage.emit("已扫码，等待手机确认")
                        )
                    elif result.event == QRCodeLoginEvents.DONE:
                        if result.credential is None:
                            raise RuntimeError("登录结果缺少凭据")
                        credential = result.credential.model_dump(mode="json")
                        self._schedule_ui(
                            lambda c=credential: self._finish_qq_music_login(c)
                        )
                        return
                    elif result.event == QRCodeLoginEvents.REFUSE:
                        raise RuntimeError("已拒绝 QQ 音乐登录")
                    elif result.event == QRCodeLoginEvents.TIMEOUT:
                        raise RuntimeError("登录二维码已过期")

        def _done(task):
            def _apply():
                if task.cancelled():
                    self._set_qq_music_login_state(busy=False, qr_source="")
                    return
                error = task.exception()
                if error is not None:
                    logger.error("QQ 音乐扫码登录失败: %s", error, exc_info=error)
                    self.statusMessage.emit(f"QQ 音乐登录失败: {error}")
                    self._set_qq_music_login_state(busy=False, qr_source="")

            self._schedule_ui(_apply)

        self._set_qq_music_login_state(busy=True, qr_source="")
        self.statusMessage.emit("正在获取 QQ 音乐登录二维码…")
        task = task_manager.spawn(_login(), name="ui:qq_music_login")
        if task is None:
            self._set_qq_music_login_state(busy=False)
            self.statusMessage.emit("应用正在关闭，无法登录")
            return
        task.add_done_callback(_done)

    def _finish_qq_music_login(self, credential: dict) -> None:
        if not self._config_manager.update_config("MUSIC.QQ_CREDENTIAL", credential):
            self.statusMessage.emit("QQ 音乐登录成功，但凭据保存失败")
            self._set_qq_music_login_state(busy=False, qr_source="")
            return
        self._set_value("MUSIC.QQ_CREDENTIAL", credential)
        self.statusMessage.emit("QQ 音乐登录成功")
        self._set_qq_music_login_state(busy=False, qr_source="")

    def _logout_qq_music(self) -> None:
        if self._config_manager.update_config("MUSIC.QQ_CREDENTIAL", {}):
            self._set_value("MUSIC.QQ_CREDENTIAL", {})
            self.statusMessage.emit("已退出 QQ 音乐登录")
        else:
            self.statusMessage.emit("退出登录失败：无法保存配置")
        self._set_qq_music_login_state(busy=False, qr_source="")

    # MQTT 配置
    def _get_mqttEndpoint(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.endpoint", "")

    def _set_mqttEndpoint(self, value: str):
        self._set_value("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.endpoint", value)

    def _get_mqttClientId(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.client_id", "")

    def _set_mqttClientId(self, value: str):
        self._set_value("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.client_id", value)

    def _get_mqttUsername(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.username", "")

    def _set_mqttUsername(self, value: str):
        self._set_value("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.username", value)

    def _get_mqttPassword(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.password", "")

    def _set_mqttPassword(self, value: str):
        self._set_value("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.password", value)

    def _get_mqttPublishTopic(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.publish_topic", "")

    def _set_mqttPublishTopic(self, value: str):
        self._set_value("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.publish_topic", value)

    def _get_mqttSubscribeTopic(self) -> str:
        return self._get_value("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.subscribe_topic", "")

    def _set_mqttSubscribeTopic(self, value: str):
        self._set_value("SYSTEM_OPTIONS.NETWORK.MQTT_INFO.subscribe_topic", value)

    # AEC 启用
    def _get_aecEnabled(self) -> bool:
        return self._get_value("AEC_OPTIONS.ENABLED", False)

    def _set_aecEnabled(self, value: bool):
        self._set_value("AEC_OPTIONS.ENABLED", value)

    # AEC 在位时 TTS 与音乐并行播放（闪避混音）
    def _get_aecMusicParallel(self) -> bool:
        return self._get_value("AEC_OPTIONS.MUSIC_PARALLEL", True)

    def _set_aecMusicParallel(self, value: bool):
        self._set_value("AEC_OPTIONS.MUSIC_PARALLEL", value)

    # 延迟补偿帧数（40ms + N × 协议帧长）
    def _get_aecFrameDelay(self) -> int:
        try:
            return int(self._get_value("AEC_OPTIONS.FRAME_DELAY", 3))
        except (TypeError, ValueError):
            return 3

    def _set_aecFrameDelay(self, value: int):
        self._set_value("AEC_OPTIONS.FRAME_DELAY", int(value))

    # 噪声抑制/高通预处理
    def _get_aecEnablePreprocess(self) -> bool:
        return self._get_value("AEC_OPTIONS.ENABLE_PREPROCESS", True)

    def _set_aecEnablePreprocess(self, value: bool):
        self._set_value("AEC_OPTIONS.ENABLE_PREPROCESS", value)

    # ========== 可写目录 PATHS（config 目录不由此改）==========

    def _get_pathCacheDir(self) -> str:
        return self._get_value("PATHS.CACHE_DIR", "") or ""

    def _set_pathCacheDir(self, value: str):
        self._set_value("PATHS.CACHE_DIR", value.strip() if value else "")

    def _get_pathLogDir(self) -> str:
        return self._get_value("PATHS.LOG_DIR", "") or ""

    def _set_pathLogDir(self, value: str):
        self._set_value("PATHS.LOG_DIR", value.strip() if value else "")

    def _get_pathMusicCacheDir(self) -> str:
        return self._get_value("PATHS.MUSIC_CACHE_DIR", "") or ""

    def _set_pathMusicCacheDir(self, value: str):
        self._set_value("PATHS.MUSIC_CACHE_DIR", value.strip() if value else "")

    def _get_pathKeywordsDir(self) -> str:
        return self._get_value("PATHS.KEYWORDS_DIR", "") or ""

    def _set_pathKeywordsDir(self, value: str):
        self._set_value("PATHS.KEYWORDS_DIR", value.strip() if value else "")

    def _get_pathMcpPluginsDir(self) -> str:
        return self._get_value("MCP_PLUGINS.DIR", "") or ""

    def _set_pathMcpPluginsDir(self, value: str):
        self._set_value("MCP_PLUGINS.DIR", value.strip() if value else "")

    def _default_data_paths(self) -> dict[str, str]:
        """配置留空时各目录的系统默认绝对路径（不含 PATHS 覆盖）."""
        from pathlib import Path

        from src.utils.resource_finder import get_user_data_dir

        data = get_user_data_dir()
        cache_custom = (self._get_pathCacheDir() or "").strip()
        cache_default = Path(cache_custom) if cache_custom else (data / "cache")
        return {
            "cache": str(data / "cache"),
            "log": str(data / "logs"),
            # 音乐默认挂在「当前缓存」下：自定义了缓存则跟随
            "music": str(cache_default / "music"),
            "keywords": str(data / "keywords"),
            "mcp": str(data / "mcp_plugins"),
        }

    def _get_pathDefaultCacheDir(self) -> str:
        try:
            return self._default_data_paths()["cache"]
        except Exception:
            return ""

    def _get_pathDefaultLogDir(self) -> str:
        try:
            return self._default_data_paths()["log"]
        except Exception:
            return ""

    def _get_pathDefaultMusicCacheDir(self) -> str:
        try:
            return self._default_data_paths()["music"]
        except Exception:
            return ""

    def _get_pathDefaultKeywordsDir(self) -> str:
        try:
            return self._default_data_paths()["keywords"]
        except Exception:
            return ""

    def _get_pathDefaultMcpPluginsDir(self) -> str:
        try:
            return self._default_data_paths()["mcp"]
        except Exception:
            return ""

    def _get_pathHints(self) -> str:
        """只读：数据根与操作提示（默认路径已显示在各输入框占位符）."""
        try:
            from src.utils.resource_finder import get_user_data_dir

            data = get_user_data_dir()
            return (
                f"数据根(配置固定在此): {data}\n"
                f"留空=默认；点「选择」用系统对话框；保存后下次启动迁移"
            )
        except Exception:
            return "留空使用默认路径；保存后下次启动迁移"

    def _browse_directory(self, title: str, current: str, which: str = "") -> str:
        """打开系统文件夹选择对话框；取消返回空串（调用方勿覆盖）."""
        from pathlib import Path

        from PySide6.QtWidgets import QApplication, QFileDialog

        start = current.strip() if current else ""
        if not start and which:
            try:
                start = self._default_data_paths().get(which, "")
            except Exception:
                start = ""
        if not start:
            try:
                from src.utils.resource_finder import get_user_data_dir

                start = str(get_user_data_dir())
            except Exception:
                start = str(Path.home())
        parent = QApplication.activeWindow()
        path = QFileDialog.getExistingDirectory(
            parent,
            title,
            start,
            QFileDialog.Option.ShowDirsOnly
            | QFileDialog.Option.DontResolveSymlinks,
        )
        return path or ""

