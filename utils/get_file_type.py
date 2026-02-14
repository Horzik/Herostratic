def detect_file_category(data: bytes) -> str:
    """Checks the magic bytes to infer the file type."""
    if data[:3] == b'\xff\xd8\xff' or data[:8] == b'\x89PNG\r\n\x1a\n' or data[:6] in (b'GIF87a', b'GIF89a') or (data[:4] == b'RIFF' and data[8:12] == b'WEBP'):
        return 'image'
    if data[:4] in (b'\x00\x00\x00\x18', b'\x00\x00\x00\x1c', b'\x00\x00\x00 ') or data[4:8] == b'ftyp':
        return 'video'
    if data[:4] == b'%PDF' or data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':  # PDF + OLE (doc/xls)
        return 'document'
    return 'unknown'
