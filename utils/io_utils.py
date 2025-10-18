import asyncio
import json
import logging
import os
import tempfile

import aiofiles

from config import LOG_DIR, ERRORS_LOG_FP
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
    pass


async def async_json_read(fp: str) -> dict:
    """
        Helper to read json asynchronously
        Return the result OR return an empty dict

    """
    try:
        async with aiofiles.open(fp, 'r', encoding='utf-8') as a:
            content = await a.read()
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, json.loads, content)
    # If no file, start with empty object
    except (json.JSONDecodeError, FileNotFoundError):
        logger.info("Failed to open POLICE_ARTICLES_FP, creating empty dict...")
        data = {}

    return data


def atomic_json_write(data: dict, fp: str):
    """
        Helper to write json 'atomically': first writes to a tmp file
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
        logger.critical(f"!!CRITICAL ERROR WRITING RESULTS TO'!!", exc_info=True)
        raise CriticalDataError(f"Failed to write {fp}") from r