"""音乐相关配置读取."""

from src.logging import get_logger

logger = get_logger()

DEFAULT_SOURCE = "tx"
DEFAULT_QUALITY = "320k"


def _cfg_str(cm, path: str, default: str) -> str:
    # 设置页允许留空=用默认；get_config 对 "" 不会回落 default
    value = cm.get_config(path, default)
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def load_music_config() -> dict:
    from src.utils.config_manager import get_config

    cm = get_config()
    pick = _cfg_str

    return {
        "DEFAULT_SOURCE": pick(
            cm, "MUSIC.DEFAULT_PLATFORM", DEFAULT_SOURCE
        ).lower(),
        "DEFAULT_BR": pick(cm, "MUSIC.DEFAULT_QUALITY", DEFAULT_QUALITY).lower(),
        "SEARCH_LIMIT": 20,
        "QQ_CREDENTIAL": cm.get_config("MUSIC.QQ_CREDENTIAL", {}) or {},
        "HEADERS": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        },
    }
