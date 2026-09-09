"""QQ 音乐歌词拉取、LRC 解析，以及按播放进度取当前句."""

from __future__ import annotations

import re

from qqmusic_api import Client

from src.logging import get_logger

from .online_search import credential_from_config

logger = get_logger()

# (时间秒, 文本)
LyricLine = tuple[float, str]
_LRC_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:\.\d+)?)\]")

# 过滤掉作词/作曲这类信息行
_METADATA_PREFIXES = (
    "作词",
    "作曲",
    "编曲",
    "制作",
    "演唱",
    "原唱",
    "翻唱",
)


def lyric_at(
    lyrics: list[LyricLine], current_time: float, *, lead: float = 0.5
) -> tuple[int, str] | None:
    """按当前播放时间找该显示哪句歌词."""
    if not lyrics:
        return None

    next_lyric_index = None
    for i, (time_sec, _) in enumerate(lyrics):
        if time_sec > current_time - lead:
            next_lyric_index = i
            break

    if next_lyric_index is not None and next_lyric_index > 0:
        idx = next_lyric_index - 1
    elif next_lyric_index is None:
        idx = len(lyrics) - 1
    else:
        idx = 0

    return idx, lyrics[idx][1]


def format_lyric_display(text: str, position: float, duration: float) -> str:
    """拼 UI 上用的歌词行，例如 [00:12/03:45] 歌词内容."""
    return f"[{_fmt(position)}/{_fmt(duration)}] {text}"


def _fmt(seconds: float) -> str:
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes:02d}:{secs:02d}"


def parse_lrc(text: str) -> tuple[list[LyricLine], int]:
    """解析标准 LRC；一行多个时间标签时分别展开."""
    lyrics: list[LyricLine] = []
    filtered = 0
    for raw_line in text.splitlines():
        matches = list(_LRC_TIME_RE.finditer(raw_line))
        if not matches:
            continue
        lyric_text = _LRC_TIME_RE.sub("", raw_line).strip()
        if not lyric_text:
            continue
        if lyric_text.startswith(_METADATA_PREFIXES) or any(
            lyric_text.startswith(f"{prefix}：")
            or lyric_text.startswith(f"{prefix}:")
            or lyric_text.startswith(f"{prefix} ")
            for prefix in _METADATA_PREFIXES
        ):
            filtered += 1
            continue
        for match in matches:
            seconds = int(match.group(1)) * 60 + float(match.group(2))
            lyrics.append((seconds, lyric_text))
    lyrics.sort(key=lambda item: item[0])
    return lyrics, filtered


async def fetch_qq_lyrics(song_mid: str, *, config: dict) -> list[LyricLine]:
    """通过 QQMusicApi 获取并解析当前歌曲歌词."""
    try:
        logger.info("获取 QQ 音乐歌词: MID=%s", song_mid)
        async with Client(credential=credential_from_config(config)) as client:
            result = await client.lyric.get_lyric(song_mid)
        lyrics, filtered = parse_lrc(result.lyric)
        logger.info("成功获取歌词，共 %d 行（过滤 %d 行元数据）", len(lyrics), filtered)
        return lyrics
    except Exception as e:
        logger.error("获取 QQ 音乐歌词失败: %s", e, exc_info=True)
        return []
