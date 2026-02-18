from db.police_normalizer import NormalizerStrategies


def get_db_strategy(domain: str) -> tuple | None:
    for key, fp, strat in NormalizerStrategies:
        if key == domain:
            return fp, strat
    return None
