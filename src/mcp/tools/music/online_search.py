"""使用 QQMusicApi 搜索歌曲并补齐播放所需元数据."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from qqmusic_api import Client, Credential
from qqmusic_api.modules.song import SongQueryInfo

from src.logging import get_logger

logger = get_logger()


@dataclass
class SearchHit:
    song_id: str
    display_name: str
    duration: float
    # 交给 MusicDownloader.resolve_play_url 的内部音源描述符。
    api_url: str


def credential_from_config(config: dict) -> Credential:
    raw = config.get("QQ_CREDENTIAL") or {}
    if not isinstance(raw, dict):
        raw = {}
    return Credential.model_validate(raw)


async def search_song(song_name: str, config: dict) -> SearchHit | None:
    """通过 QQ 音乐搜索首个匹配项；失败返回 None."""
    keyword = song_name.strip()
    if not keyword:
        return None

    try:
        credential = credential_from_config(config)
        limit = max(1, int(config.get("SEARCH_LIMIT") or 20))
        async with Client(credential=credential) as client:
            # 类型搜索在匿名状态下容易触发风控；快速搜索是官方轻量接口。
            result = await client.search.quick_search(keyword)
            items = result.song.itemlist[:limit]
            if not items:
                logger.warning("QQ 音乐未找到歌曲: %s", keyword)
                return None

            item = items[0]
            detail = await client.song.query_song([SongQueryInfo(mid=item.mid)])
            track = detail.tracks[0] if detail.tracks else None

        title = track.name if track else item.name
        singers = [s.name for s in track.singer if s.name] if track else []
        artist = " / ".join(singers) or item.singer
        display_name = f"{title} - {artist}" if artist else title
        duration = float(track.interval if track else 0)
        params = {
            "song_type": track.type if track else 0,
            "media_mid": track.file.media_mid if track else "",
        }
        api_url = f"qqmusic://song/{item.mid}?{urlencode(params)}"

        logger.info("QQ 音乐找到歌曲: %s, MID: %s", display_name, item.mid)
        return SearchHit(
            song_id=item.mid,
            display_name=display_name,
            duration=duration,
            api_url=api_url,
        )
    except Exception as e:
        logger.error("QQ 音乐搜索失败: %s", e, exc_info=True)
        return None
