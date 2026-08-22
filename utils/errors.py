class DownloadError(Exception):
    pass

class YoutubeDownloadError(DownloadError):
    pass

class FileDownloadError(DownloadError):
    pass