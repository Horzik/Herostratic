import argparse


class ScraperArguments:
    @staticmethod
    def init_argparse():
        p = argparse.ArgumentParser(
            prog='scraper',
            description='Graffiti news articles scraper.',
            epilog="Help",
            formatter_class=argparse.RawTextHelpFormatter
        )
        p.add_argument(
            "--cron",
            "-cr",
            dest="cron",
            action='store_true',
            help='''Run a scraper as a cron job'''
        )
        p.add_argument(
            "--max_pages",
            "-mp",
            dest="max_pages",
            type=int,
            help='''Define how many article listing pages the scraper should check'''
        )
        p.add_argument(
            "--insert_only",
            "-i",
            dest="insert_only",
            action='store_true',
            help='''Only insert already stored articles'''
        )
        return p
