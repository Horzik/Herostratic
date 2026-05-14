# def detect_file_category(data: bytes) -> str:
#     """Checks the magic bytes to infer the file type."""
#     if data[:3] == b'\xff\xd8\xff' or data[:8] == b'\x89PNG\r\n\x1a\n' or data[:6] in (b'GIF87a', b'GIF89a') or (data[:4] == b'RIFF' and data[8:12] == b'WEBP'):
#         return 'image'
#     if data[:4] in (b'\x00\x00\x00\x18', b'\x00\x00\x00\x1c', b'\x00\x00\x00 ') or data[4:8] == b'ftyp':
#         return 'video'
#     if data[:4] == b'%PDF' or data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':  # PDF + OLE (doc/xls)
#         return 'document'
#     if data[:3] == b'ID3' or data[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'):
#         return 'audio'
#     return 'unknown'

def detect_file_category(data: bytes) -> str:
    """Checks the magic bytes to infer the file type."""
    # Image
    if (data[:3] == b'\xff\xd8\xff'
        or data[:8] == b'\x89PNG\r\n\x1a\n'
        or data[:6] in (b'GIF87a', b'GIF89a')
        or (data[:4] == b'RIFF' and data[8:12] == b'WEBP')
        or data[:4] == b'BM'           # BMP
        or data[:4] == b'\x00\x00\x01\x00'  # ICO
        ):
        return 'image'

    # Audio
    if (data[:3] == b'ID3'
        or data[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2')  # MP3
        or data[:4] == b'fLaC'         # FLAC
        or data[:4] == b'OggS'         # OGG (could also be video, but usually audio)
        or (data[:4] == b'RIFF' and data[8:12] == b'WAVE')  # WAV
        ):
        return 'audio'

    # Video
    if (data[4:8] == b'ftyp'           # MP4/MOV/M4V
        or data[:4] == b'\x1a\x45\xdf\xa3'  # MKV/WebM (Matroska/EBML)
        or data[:4] == b'\x00\x00\x01\xba'  # MPEG-PS
        or data[:4] == b'\x00\x00\x01\xb3'  # MPEG video stream
        or (data[:4] == b'RIFF' and data[8:12] == b'AVI ')  # AVI
        or data[:3] == b'FLV'          # FLV
        ):
        return 'video'

    # Document
    if (data[:4] == b'%PDF'
        or data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'  # OLE (doc/xls/ppt)
        or data[:4] == b'PK\x03\x04'   # ZIP-based (docx/xlsx/pptx/odt/epub)
        ):
        return 'document'

    return 'unknown'
