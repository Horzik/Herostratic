from typing import TypedDict

from config import POLICE_RESULTS_FP, AKT_ART_FP, METRO_ARTICLES_FP
from db.domain_strats import NormalizerStrategies
from utils.io_utils import async_json_read


def get_db_strategy(domain: str) -> tuple | None:
    for key, fp, strat in NormalizerStrategies:
        if key == domain:
            return fp, strat
    return None


async def normalize_results(domain):
    fp, strategy = get_db_strategy(domain)
    results = await async_json_read(fp)
    normalized_results = strategy(results)
    return normalized_results


# todo
async def batch_insert(normalized_data):
    # await db.execute("""
    #        INSERT INTO articles (url, title, content, ...)
    #        VALUES (...)
    #        ON CONFLICT (url) DO NOTHING
    #    """, normalized_data)
    pass


async def push_to_db(domain: str):
    normalized = await normalize_results(domain)
    await batch_insert(normalized)
