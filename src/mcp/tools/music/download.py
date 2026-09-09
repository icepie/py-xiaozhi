"""QQ 音乐播放地址解析；后台 FFmpeg copy 预取到本地缓存."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from qqmusic_api import Client
from qqmusic_api.modules.song import SongFileInfo, SongFileType, SpecialSongFileType

from src.logging import get_logger
from src.utils.resource_finder import get_ffmpeg_path

from .cache import MusicCache
from .online_search import credential_from_config

logger = get_logger()

_QQ_SCHEME = "qqmusic"
_QUALITY_TYPES = {
    "128k": SongFileType.MP3_128,
    "320k": SongFileType.MP3_320,
    "flac": SongFileType.FLAC,
}

_SUBPROCESS_KW = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)


class MusicDownloader:
    """解析播放地址；可选后台 copy 整首到缓存（按网速，不跟播放进度走）."""

    def __init__(self, cache: MusicCache, config: dict[str, Any] | None = None) -> None:
        self._cache = cache
        self._config = config or {}
        # 上次失败原因，给上层提示用
        self.last_error: str | None = None
        self._prefetch_task: asyncio.Task | None = None
        self._prefetch_song_id: str | None = None

    def set_config(self, config: dict[str, Any]) -> None:
        self._config = config

    async def get_or_download(
        self,
        song_id: str,
        api_url: str,
        *,
        filename: str | None = None,
    ) -> Path | None:
        """有缓存直接用，没有再下载."""
        self._cache.prepare()
        name = filename or f"{song_id}.mp3"
        hit = self._cache.find_song_file(song_id)
        if hit is not None:
            logger.info(f"使用缓存: {hit}")
            return hit

        cache_path = self._cache.root / name
        if cache_path.exists():
            logger.info(f"使用缓存: {cache_path}")
            return cache_path

        return await self.download(api_url, name, song_id=song_id)


    @staticmethod
    def _parse_qq_descriptor(api_url: str) -> tuple[str, int, str]:
        parsed = urlparse(api_url)
        if parsed.scheme != _QQ_SCHEME or parsed.netloc != "song":
            raise ValueError("无效的 QQ 音乐音源描述符")
        song_mid = parsed.path.lstrip("/")
        if not song_mid:
            raise ValueError("QQ 音乐音源缺少歌曲 MID")
        params = dict(
            item.split("=", 1) if "=" in item else (item, "")
            for item in parsed.query.split("&")
            if item
        )
        try:
            song_type = int(params.get("song_type") or 0)
        except ValueError:
            song_type = 0
        return song_mid, song_type, params.get("media_mid", "")

    async def _resolve_via_qqmusic(self, api_url: str) -> str | None:
        song_mid, song_type, media_mid = self._parse_qq_descriptor(api_url)
        quality = str(self._config.get("DEFAULT_BR") or "320k").lower()
        preferred = _QUALITY_TYPES.get(quality, SongFileType.MP3_320)
        file_types = [preferred]
        if preferred not in (SongFileType.MP3_320, SongFileType.MP3_128):
            file_types.append(SongFileType.MP3_320)
        if SongFileType.MP3_128 not in file_types:
            file_types.append(SongFileType.MP3_128)
        # 未登录或无版权时仍请求官方试听，绝不绕过平台权限。
        file_types.append(SpecialSongFileType.TRY)

        credential = credential_from_config(self._config)
        async with Client(credential=credential) as client:
            dispatch = await client.song.get_cdn_dispatch()
            if not dispatch.sip:
                self.last_error = "QQ 音乐未返回可用 CDN"
                return None

            requests = [
                SongFileInfo(
                    mid=song_mid,
                    file_type=file_type,
                    song_type=song_type,
                    media_mid=media_mid or None,
                )
                for file_type in file_types
            ]
            result = await client.song.get_song_urls(requests)

        for info in result.data:
            if info.result == 0 and info.purl:
                cdn = next(
                    (
                        base
                        for base in dispatch.sip
                        if base.startswith("https://")
                        and "stream.qqmusic.qq.com" in base
                    ),
                    "https://isure.stream.qqmusic.qq.com/",
                )
                media_url = f"{cdn}{info.purl}"
                logger.info("QQ 音乐播放地址解析成功: %s", urlparse(media_url).hostname)
                return media_url

        codes = ", ".join(str(info.result) for info in result.data) or "无结果"
        self.last_error = f"QQ 音乐无可播放音质（结果码: {codes}）"
        return None


    def media_headers(self, media_url: str) -> dict[str, str]:
        """给 CDN / FFmpeg 流式播放用的请求头（不是 JSON API 那套）."""
        host = (urlparse(media_url).hostname or "").lower()
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        headers = {
            "User-Agent": ua,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
        if "qqmusic" in host or "gtimg" in host:
            headers["Referer"] = "https://y.qq.com/"
        return headers


    async def resolve_play_url(
        self, api_url: str, *, song_id: str | None = None
    ) -> str | None:
        """把内部 QQ 音源描述符解析为有时效的官方 CDN 地址."""
        _ = song_id
        self.last_error = None
        try:
            return await self._resolve_via_qqmusic(api_url)
        except Exception as e:
            self.last_error = f"解析 QQ 音乐播放地址失败: {e}"
            logger.error(self.last_error, exc_info=True)
            return None

    def _sync_download(
        self, download_url: str, headers: dict, temp_path: Path, cache_path: Path
    ) -> Path:
        # CDN 偶发 RemoteDisconnected，多试两次
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                if temp_path.exists():
                    temp_path.unlink()
                with requests.get(
                    download_url,
                    headers=headers,
                    stream=True,
                    timeout=45,
                    allow_redirects=True,
                ) as response:
                    response.raise_for_status()
                    with open(temp_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=64 * 1024):
                            if chunk:
                                f.write(chunk)
                if temp_path.stat().st_size <= 0:
                    raise OSError("下载文件为空")
                shutil.move(str(temp_path), str(cache_path))
                return cache_path
            except (requests.RequestException, OSError) as e:
                last_err = e
                logger.warning(
                    f"下载重试 {attempt + 1}/3 失败: {e}"
                )
        assert last_err is not None
        raise last_err

    async def download(
        self, api_url: str, filename: str, *, song_id: str | None = None
    ) -> Path | None:
        """下载并写入缓存目录."""
        self._cache.prepare()
        temp_path = None
        try:
            download_url = await self.resolve_play_url(api_url, song_id=song_id)
            if not download_url:
                return None

            temp_path = self._cache.temp_path(filename)
            cache_path = self._cache.root / filename
            headers = self.media_headers(download_url)
            logger.debug(
                f"开始下载音频: host={urlparse(download_url).hostname}"
            )

            result = await asyncio.to_thread(
                self._sync_download,
                download_url,
                headers,
                temp_path,
                cache_path,
            )
            logger.info(f"音乐下载完成并缓存: {result}")
            return result
        except Exception as e:
            self.last_error = f"下载失败: {e}"
            logger.error(self.last_error, exc_info=True)
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception as cleanup_e:
                    logger.debug(f"清理临时文件失败: {cleanup_e}")
            return None

    def start_prefetch(
        self,
        media_url: str,
        song_id: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """后台按网速 FFmpeg -c copy 整首落盘，不跟播放进度同步.

        类似 HTML audio 的缓冲：播的同时尽快把整文件拉完，听完前也可能已缓存好。
        换歌会取消上一次预取；暂停/停止当前歌不取消（继续缓冲）。
        """
        if not song_id or song_id == "unknown":
            return
        self._cache.prepare()
        if self._cache.find_song_file(song_id) is not None:
            logger.debug(f"已有缓存，跳过预取: {song_id}")
            return

        # 同一首歌已在预取
        if (
            self._prefetch_task
            and not self._prefetch_task.done()
            and self._prefetch_song_id == song_id
        ):
            return

        self.cancel_prefetch()
        hdrs = dict(headers or self.media_headers(media_url))
        self._prefetch_song_id = song_id
        self._prefetch_task = asyncio.create_task(
            self._prefetch_copy_loop(media_url, song_id, hdrs),
            name=f"music:prefetch:{song_id}",
        )
        logger.info(f"后台预取缓存: song_id={song_id}")

    def cancel_prefetch(self) -> None:
        """取消后台预取（换歌时）."""
        task = self._prefetch_task
        self._prefetch_task = None
        self._prefetch_song_id = None
        if task and not task.done():
            task.cancel()

    async def _prefetch_copy_loop(
        self, media_url: str, song_id: str, headers: dict[str, str]
    ) -> None:
        final = self._cache.path_for_song(song_id)
        part = final.with_name(f"{final.stem}.part{final.suffix}")
        try:
            if part.exists():
                part.unlink()
        except Exception:
            pass

        try:
            ok = await self._ffmpeg_copy_url(media_url, part, headers)
            if not ok:
                return
            if not part.exists() or part.stat().st_size <= 1024:
                logger.warning(f"预取文件过小，丢弃: {part.name}")
                if part.exists():
                    part.unlink()
                return
            if final.exists():
                final.unlink()
            part.replace(final)
            logger.info(
                f"后台预取完成（可本地播）: {final.name} ({final.stat().st_size} bytes)"
            )
        except asyncio.CancelledError:
            logger.debug(f"后台预取取消: {song_id}")
            try:
                if part.exists():
                    part.unlink()
            except Exception:
                pass
            raise
        except Exception as e:
            logger.warning(f"后台预取失败 {song_id}: {e}", exc_info=True)
            try:
                if part.exists():
                    part.unlink()
            except Exception:
                pass
        finally:
            if self._prefetch_song_id == song_id:
                self._prefetch_task = None
                self._prefetch_song_id = None

    async def _ffmpeg_copy_url(
        self, media_url: str, out_path: Path, headers: dict[str, str]
    ) -> bool:
        """用 FFmpeg -c copy 按网速拉整首，不解码、不跟播放限速."""
        from src.audio_codecs.music_decoder import _ffmpeg_header_args

        ffmpeg = get_ffmpeg_path()
        cmd = [
            ffmpeg,
            "-y",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
        ]
        cmd.extend(_ffmpeg_header_args(headers))
        cmd.extend(
            [
                "-i",
                media_url,
                "-vn",
                "-c:a",
                "copy",
                "-loglevel",
                "error",
                str(out_path),
            ]
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                **_SUBPROCESS_KW,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                err = (stderr or b"").decode("utf-8", errors="ignore").strip()
                logger.warning(
                    f"FFmpeg copy 预取失败 rc={proc.returncode}: {err[:300]}"
                )
                return False
            return True
        except FileNotFoundError:
            logger.warning("FFmpeg 不可用，后台预取跳过")
            return False
        except Exception as e:
            logger.warning(f"FFmpeg copy 预取异常: {e}", exc_info=True)
            return False
