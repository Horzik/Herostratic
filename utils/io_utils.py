from functools import partial
import xml.etree.ElementTree as ET
import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

import aiofiles

from config import LOG_DIR, ERRORS_LOG_FP, DECODE_FORMATS, FILES_DIR
from utils.errors import YoutubeDownloadError, DownloadError
from utils.get_file_type import detect_file_metadata
from utils.logger import LogConfig, init_logging, get_logger

logConfig = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.INFO,
        log_file_path=LOG_DIR / 'io_utils.log',
        log_errors_file_path=ERRORS_LOG_FP
)
init_logging(logConfig)
logger = get_logger('io_utils')


#todo migrate to errors
class CriticalDataError(Exception):
    """Use if writing goes wrong."""
    pass


async def async_json_read(fp: str) -> dict:
    """Helper to read json asynchronously.
       Return the result OR return an empty dict.
    """
    try:
        async with aiofiles.open(fp, 'r', encoding='utf-8') as a:
            content = await a.read()
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, json.loads, content)
        return data

    except FileNotFoundError:
        logger.info(f"'{fp}' not found, returning empty dict...")
        return {}
    except json.JSONDecodeError:
        logger.info(f"'{fp}' is corrupted, returning empty dict...")
        return {}


async def async_text_read(fp: str) -> str:
    try:
        async with aiofiles.open(fp, 'r', encoding='utf-8') as a:
            content = await a.read()
        return content
    except FileNotFoundError:
        logger.info(f"'{fp}' not found, returning empty string...")
        return ""


def read_json(fp: str) -> dict:
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.info(f"'{fp}' not found, returning empty dict...")
        return {}


# todo this breaks if not json, fix it
def atomic_json_write(data: dict | list, fp: str | Path):
    """Helper to write json 'atomically': first writes to a tmp file
       and only then to the target file (cleans up the tmp file afterward).
    """
    try:
        tmp_name = None
        with tempfile.NamedTemporaryFile('w', delete=False, dir=os.path.dirname(fp)) as tmp:
            json.dump(data, tmp, indent=4, ensure_ascii=False)
            tmp_name = tmp.name
        os.replace(tmp_name, fp)
    except Exception as r:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)
        logger.critical(f"!Error while writing results, raising the exception...", exc_info=True)
        raise CriticalDataError(r)


async def parse_xml_tree(content_bytes: bytes, url: str) -> ET.Element | None:
    for encoding in DECODE_FORMATS: # Try various encodings because issues           z
        try:
            decoded_bytes = content_bytes.decode(encoding)
            if len(decoded_bytes) <= 10: # Return if no content
                return logger.warning(f"No content for {url}, skipping")
            loop = asyncio.get_event_loop()
            # noinspection PyTypeChecker
            element_tree: ET.Element = await loop.run_in_executor(
                None, partial(ET.fromstring, decoded_bytes))
            return element_tree
        except UnicodeDecodeError as e:
            logger.error(f"UnicodeDecodeError with {encoding}: {e}")
            continue
        except ET.ParseError as e:
            logger.error(f"ParseError with {encoding}: {e}")
            logger.error(f"First 500 chars with {encoding}:")
            continue
    else:
        return logger.warning(f"Could not parse {url} with any encoding")


def mk_filename_w_extension(file_name: str, extension: str | None) -> str:
    if not extension:
        return file_name

    path = Path(file_name)
    stem = path.stem.rstrip('. ') or 'file'
    return f"{stem}{extension}"


# Wrapper for non-blocking downloads, returns the title (used as file name)
def download_yt(ytb_url: str, options: dict[str, str | bool]):
    import yt_dlp
    with yt_dlp.YoutubeDL(options) as ydl:
        dl_info = ydl.extract_info(ytb_url, download=True)
        f_name = ydl.prepare_filename(dl_info)
        return f_name


async def download_ytb_video(ytb_url: str, dir_name: str) -> tuple[str, str] | None:
    """ Use the 'yt_dlp' lib to download 'youtube' links.

        Returns a tuple of (file_path, file_type).
    """
    import yt_dlp
    abs_dir: Path = FILES_DIR / dir_name
    options: dict[str, str | bool] = {'outtmpl': str(abs_dir / '%(title)s.%(ext)s'), 'format': 'best[height<=720]', 'quiet': True}
    try:
        file_name = await asyncio.to_thread(download_yt, ytb_url, options)
        rel_path = str(dir_name + '/' + Path(file_name).name)
        return str(rel_path), 'video'
    except yt_dlp.utils.DownloadError as e:
        raise YoutubeDownloadError()


def download_file(file_bytes, file_name, dir_name) -> tuple[str, str] | None:
    """ Saves target {file_bytes} as {file_name} in {dir_name}.

        Returns the file_path and file_type.
    """
    metadata = detect_file_metadata(file_bytes[:512], file_name)
    file_name = mk_filename_w_extension(file_name, metadata.extension)
    abs_file_path = FILES_DIR / dir_name / file_name # Where to write the file
    rel_file_path = dir_name + '/' + file_name # Stored in PG
    try:
        with open(abs_file_path, 'wb') as f:
            f.write(file_bytes)
        return str(rel_file_path), metadata.file_type
    except Exception as e:
        raise DownloadError()
