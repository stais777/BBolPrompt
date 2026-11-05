import hashlib
import json
import unicodedata


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def digest(value):return hashlib.sha256(encoded(value).encode('utf8')).hexdigest()


def name(tag):return tag.get('tag',tag.get('name',''))


def key(tag):return unicodedata.normalize('NFC',name(tag)).strip().casefold()
