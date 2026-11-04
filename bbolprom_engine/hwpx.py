"""HWPX source reader. Does not import, inspect or modify approved reference cards."""
from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from xml.etree import ElementTree as ET

SECTION_RE = re.compile(r'(?:^|/)section(\d+)\.xml$', re.I)
ASSET_RE = re.compile(r'(?:^|/)bindata/([^/]+)$', re.I)
MAX_SECTION_SIZE = 64 * 1024 * 1024
MAX_META_SIZE = 32 * 1024 * 1024
MAX_SECTION_COUNT = 512
MAX_ZIP_ENTRIES = 30000


class HWPXError(ValueError):
    pass


def local_name(raw: str) -> str:
    return raw.split('}', 1)[-1].split(':')[-1].lower()


def clean_path(path: str) -> str:
    return path.replace('\\', '/').removeprefix('./').removeprefix('/')


@dataclass
class Paragraph:
    index: int
    section: int
    text: str
    image_refs: list[str]
    # A table row is a structural grouping hint (never an approved-card ID).
    container: str | None = None
    break_before: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class HWPXReader:
    def __init__(self, source: str | Path):
        self.source = Path(source)
        if not self.source.is_file():
            raise HWPXError(f'파일을 찾을 수 없습니다: {self.source}')
        if self.source.suffix.lower() != '.hwpx':
            raise HWPXError('*.hwpx 파일만 처리합니다.')
        self.zip = zipfile.ZipFile(self.source, 'r')
        self.members = [m for m in self.zip.infolist() if not m.is_dir()]
        if len(self.members) > MAX_ZIP_ENTRIES:
            raise HWPXError('ZIP 구성 요소 개수가 제한을 초과했습니다.')
        names = [m.filename for m in self.members]
        self.sections = sorted([n for n in names if SECTION_RE.search(n)],
                               key=lambda n: int(SECTION_RE.search(n).group(1)))
        if not self.sections:
            raise HWPXError('HWPX 섹션 XML이 없습니다. 일반 ZIP 또는 잘못된 HWPX일 수 있습니다.')
        if len(self.sections) > MAX_SECTION_COUNT:
            raise HWPXError('섹션 개수가 비정상적으로 많습니다.')
        self.names = names
        self.lower_names = {n.lower(): n for n in names}
        self.assets = self._index_assets()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.zip.close()

    def _safe_xml(self, name: str, size_limit: int) -> ET.Element:
        info = self.zip.getinfo(name)
        if info.file_size > size_limit:
            raise HWPXError(f'너무 큰 XML 구성 요소: {name}')
        contents = self.zip.read(info)
        if re.search(rb'<!\s*(?:DOCTYPE|ENTITY)\b', contents, re.I):
            raise HWPXError(f'허용하지 않는 XML DTD/ENTITY: {name}')
        try:
            return ET.fromstring(contents)
        except ET.ParseError as exc:
            raise HWPXError(f'XML 파싱 실패 {name}: {exc}') from exc

    def _index_assets(self) -> dict[str, str]:
        out = {}
        # A direct BinData entry takes precedence over generic names.
        for n in self.names:
            m = ASSET_RE.search(n)
            if m:
                filename = m.group(1)
                out.setdefault(filename.lower(), n)
                out.setdefault(filename.rsplit('.', 1)[0].lower(), n)
        for n in self.names:
            stem = n.split('/')[-1]
            if re.search(r'\.(?:bmp|png|jpe?g|webp|gif|tiff?|emf|wmf)$', stem, re.I):
                out.setdefault(stem.lower(), n)
                out.setdefault(stem.rsplit('.', 1)[0].lower(), n)
        for n in self.names:
            if not re.search(r'content\.hpf$|header\.xml$|manifest[^/]*\.xml$|meta\.xml$', n, re.I):
                continue
            try:
                root = self._safe_xml(n, MAX_META_SIZE)
            except (HWPXError, KeyError):
                continue
            for el in root.iter():
                a = {local_name(k): v for k, v in el.attrib.items()}
                ident = a.get('id') or a.get('itemid') or a.get('name')
                href = a.get('href') or a.get('full-path') or a.get('path') or a.get('file-name')
                if ident and href:
                    path = clean_path(href)
                    candidates = [path, 'Contents/'+path, path.removeprefix('Contents/'),
                                  'BinData/'+path.split('/')[-1]]
                    for can in candidates:
                        resolved = self.lower_names.get(can.lower())
                        if resolved:
                            out[ident.lower()] = resolved
                            break
        return out

    def resolve_image(self, ref: str) -> str | None:
        key = str(ref).lower()
        got = self.assets.get(key)
        if got:
            return got
        # Some HWPX files store binaryItemIDRef as an asset path rather than ID.
        return self.lower_names.get(clean_path(ref).lower())

    def read_paragraphs(self) -> tuple[list[Paragraph], dict]:
        paras: list[Paragraph] = []
        total_xml_bytes = 0
        xml_paragraphs = 0
        for section_num, name in enumerate(self.sections):
            info = self.zip.getinfo(name)
            total_xml_bytes += info.file_size
            if total_xml_bytes > 256 * 1024 * 1024:
                raise HWPXError('HWPX 본문 XML 총량이 제한을 초과했습니다.')
            root = self._safe_xml(name, MAX_SECTION_SIZE)
            xml_paragraphs += sum(local_name(el.tag) == 'p' for el in root.iter())
            rows = {id(el): f'{section_num}:row:{i}' for i, el in
                    enumerate(el for el in root.iter() if local_name(el.tag) == 'tr')}

            def text_content(node):
                # itertext() silently loses lineBreak/tab controls inside hp:t.
                kind = local_name(node.tag)
                if kind in {'linebreak', 'br'}:
                    return '\n'
                if kind == 'tab':
                    return '\t'
                return (node.text or '') + ''.join(text_content(c) + (c.tail or '') for c in node)

            def visit(node, container=None):
                container = rows.get(id(node), container)
                if local_name(node.tag) != 'p':
                    for child in node:
                        visit(child, container)
                    return
                fragments, images = [], []
                attrs = {local_name(k): v for k, v in node.attrib.items()}
                page_break = attrs.get('pagebreak', '').lower() in {'1', 'true'}
                emitted = False
                nested = False

                def flush(force=False):
                    nonlocal fragments, images, emitted
                    if fragments or images or force:
                        paras.append(Paragraph(len(paras), section_num, ''.join(fragments),
                                               images, container, page_break and not emitted))
                        emitted = True
                        fragments, images = [], []

                def walk(current):
                    nonlocal nested
                    if current is not node and local_name(current.tag) == 'p':
                        # Nested cell/textbox paragraphs are emitted exactly once,
                        # in document order; an outer host must not repeat them.
                        nested = True
                        flush()
                        visit(current, rows.get(id(current), active_container[0]))
                        return
                    old = active_container[0]
                    active_container[0] = rows.get(id(current), old)
                    if local_name(current.tag) == 't':
                        fragments.append(text_content(current))
                    else:
                        for key, value in current.attrib.items():
                            if local_name(key) == 'binaryitemidref':
                                images.append(value)
                        for child in current:
                            walk(child)
                    active_container[0] = old

                active_container = [container]
                walk(node)
                flush(force=not nested and not emitted)

            visit(root)
        total_refs = sum(len(p.image_refs) for p in paras)
        stats = {
            'section_count': len(self.sections),
            'paragraph_count': len(paras),
            'xml_paragraph_count': xml_paragraphs,
            'source_chars': sum(len(p.text) for p in paras) + len(paras),
            'image_ref_count': total_refs,
            'embedded_media_count': sum(bool(ASSET_RE.search(n)) for n in self.names),
            'xml_bytes': total_xml_bytes,
        }
        return paras, stats

    def media_digest(self, path: str) -> dict:
        """Hashes original ZIP member bytes; never recodes/resizes images."""
        md5, sha1, sha256 = hashlib.md5(), hashlib.sha1(), hashlib.sha256()
        size = 0
        with self.zip.open(path, 'r') as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                md5.update(block)
                sha1.update(block)
                sha256.update(block)
        return {'bytes': size, 'md5': md5.hexdigest(), 'sha1': sha1.hexdigest(),
                'sha256': sha256.hexdigest()}
