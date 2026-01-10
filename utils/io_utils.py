from functools import partial
import xml.etree.ElementTree as ET
import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

import aiofiles

from config import LOG_DIR, ERRORS_LOG_FP, DECODE_FORMATS, INPUT_DIR
from utils.logger import LogConfig, init_logging, get_logger


logConfig = LogConfig(
        log_level=logging.DEBUG,
        log_std_level=logging.INFO,
        log_file_path=LOG_DIR / 'io_utils.log',
        log_errors_file_path=ERRORS_LOG_FP
)
init_logging(logConfig)
logger = get_logger('io_utils')


class CriticalDataError(Exception):
    """ We failed at the same time as the only time we write? """
    pass


async def async_json_read(fp: str) -> dict:
    # todo this only seems to act as a dict reader, rename or idk
    """
        Helper to read json asynchronously \n
        Return the result OR return an empty dict

    """
    try:
        async with aiofiles.open(fp, 'r', encoding='utf-8') as a:
            content = await a.read()
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, json.loads, content)
    # If no file, start with empty object
    except (json.JSONDecodeError, FileNotFoundError):
        logger.info(f"Failed to open {fp}, creating empty dict...")
        data = {}

    return data


# todo add file creation if not existing?
def atomic_json_write(data: dict | list, fp: str | Path):
    """ Helper to write json 'atomically': first writes to a tmp file
        and only then to the target file (cleans up the tmp file afterward)
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