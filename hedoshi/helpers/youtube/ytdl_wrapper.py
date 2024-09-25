# Copyright (C) 2024 frknkrc44 <https://gitlab.com/frknkrc44>
#
# This file is part of HedoshiMusicBot project,
# and licensed under GNU Affero General Public License v3.
# See the GNU Affero General Public License for more details.
#
# All rights reserved. See COPYING, AUTHORS.
#

from asyncio import get_event_loop
from asyncio import run as async_run
from logging import info
from os import getcwd, sep
from os.path import exists
from re import match
from traceback import format_exception
from typing import Dict, Optional, Tuple

import yt_dlp.extractor.extractors as ex
from pyrogram.types import Message
from yt_dlp import YoutubeDL
from yt_dlp.extractor.unsupported import KnownDRMIE, KnownPiracyIE
from yt_dlp.networking.common import _REQUEST_HANDLERS, register_rh
from yt_dlp.postprocessor.common import PostProcessor

from ..pre_query import insert_pre_query, remove_pre_query
from ..progress import progress_func_wrapper
from ..proxy import get_proxy
from .invidious import download_from_invidious, is_valid_invidious_match
from .ytdl_httpx_handler import HTTPXRH

yt_valid_ends = [
    '.m3u8'
]

def set_httpx_handler():
    from ... import bot_config

    use_httpx = (
        bot_config.YTDL_USE_HTTPX if hasattr(bot_config, "YTDL_USE_HTTPX") else False
    )

    if not use_httpx:
        return

    try:
        from yt_dlp.networking._curlcffi import CurlCFFIRH

        del _REQUEST_HANDLERS[CurlCFFIRH.RH_KEY]
    except BaseException:
        pass

    try:
        from yt_dlp.networking._requests import RequestsRH

        del _REQUEST_HANDLERS[RequestsRH.RH_KEY]
    except BaseException:
        pass

    try:
        from yt_dlp.networking._urllib import UrllibRH

        del _REQUEST_HANDLERS[UrllibRH.RH_KEY]
    except BaseException:
        pass

    register_rh(HTTPXRH)


set_httpx_handler()


class FilenameCollectorPP(PostProcessor):
    # https://stackoverflow.com/a/68165682
    def __init__(self, is_audio: bool):
        super(FilenameCollectorPP, self).__init__(None)
        self.is_audio = is_audio
        self.filename = ""
        self.filepath = ""

    def run(self, information: Dict):
        path: str = information.get("filepath")
        uploader: str = information.get("uploader")
        title: str = information.get("title")

        if exists(path):
            self.filename = f"{uploader} - {title} ({'a' if self.is_audio else 'v'})"
            self.filepath = path

        return [], information


def _is_valid_ends(url: str):
    for item in yt_valid_ends:
        if item in url:
            return True

    return False


def is_in_blacklist(url: str):
    for rule in KnownDRMIE.URLS:
        if match(f".*{rule}.*", url):
            return True

    for rule in KnownPiracyIE.URLS:
        if match(f".*{rule}.*", url):
            return True

    return False


def is_valid(url: str):
    if not url or not url.startswith("http"):
        return False

    for item in ex._ALL_CLASSES:
        try:
            if hasattr(item, "_VALID_URL") and match(getattr(item, "_VALID_URL"), url):
                return True
        except BaseException:
            pass

    return _is_valid_ends(url)


async def download_media(
    source: Message,
    reply: Message,
    url: str,
    audio: bool = False,
) -> Optional[Tuple[str, str]]:
    if is_in_blacklist(url):
        return None

    if insert_pre_query(
        source.chat.id,
        url,
        source.from_user.id if source.from_user else source.chat.id,
    ):
        return None

    async def invidious_progress_hook(current: int, total: int):
        await progress_func_wrapper(
            reply,
            current,
            total,
        )

    def ytdl_progress_hook(progress: Dict):
        downloaded = progress.get("downloaded_bytes", 0)
        total = progress.get("total_bytes")

        if not total:
            total = max(downloaded, 1)

        async_run(
            invidious_progress_hook(
                downloaded,
                total,
            )
        )

    from ... import bot_config

    ytdl_cookie_file = (
        bot_config.YTDL_COOKIE_FILE if hasattr(bot_config, "YTDL_COOKIE_FILE") else None
    )

    use_invidious = (
        bot_config.BOT_USE_INVIDIOUS
        if hasattr(bot_config, "BOT_USE_INVIDIOUS")
        else False
    )

    enable_oauth2 = (
        bot_config.YTDL_ENABLE_OAUTH2
        if hasattr(bot_config, "YTDL_ENABLE_OAUTH2")
        else False
    )

    use_proxy = (
        bot_config.BOT_USE_PROXY if hasattr(bot_config, "BOT_USE_PROXY") else False
    )

    max_video_quality = (
        bot_config.BOT_MAX_VIDEO_QUALITY
        if hasattr(bot_config, "BOT_MAX_VIDEO_QUALITY")
        else 1080
    )

    if max_video_quality not in (144, 240, 360, 480, 720, 1080, 2160):
        max_video_quality = 1080

    if use_invidious and is_valid_invidious_match(url):
        try_count = 0
        while try_count < 10:
            try:
                proxy: Optional[str] = None
                if use_proxy:
                    proxy = await get_proxy()

                try_invidious = await download_from_invidious(
                    url,
                    audio,
                    invidious_progress_hook,
                    proxy,
                    max_video_quality=max_video_quality,
                )

                if try_invidious:
                    remove_pre_query(
                        source.chat.id,
                        url,
                    )

                    return try_invidious

                try_count = try_count + 1
            except BaseException as e:
                print(format_exception(e))
                try_count = try_count + 1

    opts = {
        "ignoreerrors": True,
        "outtmpl": f'{getcwd()}{sep}downloads{sep}%(id)s-{"a" if audio else "v"}.%(ext)s',
        "cachedir": f"{getcwd()}{sep}downloads",
        "progress_hooks": [ytdl_progress_hook],
        "geo_bypass": True,
        "nocheckcertificate": True,
        "prefer_ffmpeg": True,
    }

    if is_valid_invidious_match(url) and enable_oauth2:
        opts["username"] = "oauth2"
        opts["password"] = ""

    if not enable_oauth2 and ytdl_cookie_file and exists(ytdl_cookie_file):
        opts["cookiefile"] = ytdl_cookie_file

    if audio:
        opts["format"] = "bestaudio/m4a/worstvideo/worst/source"
    else:
        opts["format"] = (
            f"bestvideo[height<={max_video_quality}][protocol!*=m3u8]+bestaudio/bestvideo[height<={max_video_quality}]+bestaudio/best/source"
        )

    filename_collector = FilenameCollectorPP(audio)

    with YoutubeDL(opts) as ytdl:
        ytdl.add_post_processor(filename_collector)

        try_count = 0
        while try_count < 4:
            try:
                if use_proxy and try_count < 3:
                    ytdl.cookiejar.clear()

                    proxy = await get_proxy()
                    ytdl.proxies = {
                        "https": proxy,
                        "http": proxy,
                    }
                    info(f"Set a random proxy {ytdl.proxies}")
                else:
                    ytdl.proxies.clear()

                assert not await get_event_loop().run_in_executor(
                    None,
                    ytdl.download,
                    [url],
                )
            except BaseException:
                try_count = try_count + 1
                continue

            break

    remove_pre_query(
        source.chat.id,
        url,
    )

    return (
        (filename_collector.filepath, filename_collector.filename)
        if len(filename_collector.filename)
        else None
    )
