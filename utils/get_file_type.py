from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileMetadata:
    file_type: str
    extension: str | None

def detect_file_category(data: bytes) -> str:
    """Checks the magic bytes to infer the file type."""
    return detect_file_metadata(data).file_type


def detect_file_metadata(data: bytes, fallback_name: str | None = None) -> FileMetadata:
    """Checks magic bytes and returns the broad type plus a matching extension."""
    # Image
    if data[:3] == b'\xff\xd8\xff':
        return FileMetadata('image', '.jpg')
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return FileMetadata('image', '.png')
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return FileMetadata('image', '.gif')
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return FileMetadata('image', '.webp')
    if data[:2] == b'BM':
        return FileMetadata('image', '.bmp')
    if data[:4] == b'\x00\x00\x01\x00':
        return FileMetadata('image', '.ico')

    # Audio
    if data[:3] == b'ID3' or data[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'):
        return FileMetadata('audio', '.mp3')
    if data[:4] == b'fLaC':
        return FileMetadata('audio', '.flac')
    if data[:4] == b'OggS':
        return FileMetadata('audio', '.ogg')
    if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
        return FileMetadata('audio', '.wav')

    # Video
    if data[4:8] == b'ftyp':
        return FileMetadata('video', '.mp4')
    if data[:4] == b'\x1a\x45\xdf\xa3':
        return FileMetadata('video', '.mkv')
    if data[:4] in (b'\x00\x00\x01\xba', b'\x00\x00\x01\xb3'):
        return FileMetadata('video', '.mpeg')
    if data[:4] == b'\x00\x00\x00\x01' or data[:3] == b'\x00\x00\x01':
        return FileMetadata('video', '.h264')
    if data[:16] == bytes.fromhex('3026b2758e66cf11a6d900aa0062ce6c'):
        return FileMetadata('video', '.wmv')
    if data[:4] == b'RIFF' and data[8:12] == b'AVI ':
        return FileMetadata('video', '.avi')
    if data[:3] == b'FLV':
        return FileMetadata('video', '.flv')

    # Document
    if data[:4] == b'%PDF':
        return FileMetadata('document', '.pdf')
    if data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        return FileMetadata('document', _fallback_extension(fallback_name, '.doc'))
    if data[:4] == b'PK\x03\x04':
        return FileMetadata('document', _fallback_extension(fallback_name, '.zip'))

    if fallback_name:
        fallback_type = _fallback_type(fallback_name)
        if fallback_type != 'unknown':
            return FileMetadata(fallback_type, _fallback_extension(fallback_name, None))

    return FileMetadata('unknown', _fallback_extension(fallback_name, None))


def _fallback_extension(fallback_name: str | None, default: str | None) -> str | None:
    if not fallback_name:
        return default
    suffix = Path(fallback_name).suffix
    return suffix.lower() if suffix else default


def _fallback_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.ico'}:
        return 'image'
    if suffix in {'.mp4', '.mov', '.m4v', '.mkv', '.webm', '.flv', '.wmv', '.h264', '.avi', '.mpeg', '.mpg'}:
        return 'video'
    if suffix in {'.mp3', '.wav', '.flac', '.ogg'}:
        return 'audio'
    if suffix in {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.zip'}:
        return 'document'

    return 'unknown'
