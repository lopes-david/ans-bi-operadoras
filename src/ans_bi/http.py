"""Cliente HTTP mínimo (só stdlib) para o portal de dados abertos da ANS."""

from __future__ import annotations

import html
import logging
import re
import shutil
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import USER_AGENT

log = logging.getLogger(__name__)

# linha do índice do Apache: <a href="x.csv">...</a></td><td align="right">2026-09-10 08:00 </td><td ...> 16M</td>
_ROW = re.compile(
    r'<a href="(?P<href>[^"?/][^"]*)">.*?</a>\s*</td>\s*<td[^>]*>\s*(?P<modified>\d{4}-\d{2}-\d{2} \d{2}:\d{2})'
    r"\s*</td>\s*<td[^>]*>\s*(?P<size>[^<]*?)\s*</td>"
)


@dataclass(frozen=True)
class Entry:
    name: str
    modified: str  # "YYYY-MM-DD HH:MM" (horário do servidor da ANS)
    size: str  # tamanho aproximado ("16M", "-" para diretórios)

    @property
    def is_dir(self) -> bool:
        return self.name.endswith("/")

    @property
    def version(self) -> str:
        """Identifica a versão do arquivo sem precisar de HEAD por arquivo."""
        return f"{self.modified}|{self.size}"


def _open(url: str, timeout: int):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def _retry(fn, attempts: int = 4, what: str = ""):
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # rede do portal da ANS oscila; backoff simples
            if i == attempts - 1:
                raise
            wait = 2 ** (i + 1)
            log.warning("falha em %s (%s); nova tentativa em %ss", what, exc, wait)
            time.sleep(wait)


def parse_listing(page: str) -> list[Entry]:
    entries = []
    for m in _ROW.finditer(page):
        name = urllib.parse.unquote(html.unescape(m["href"]))
        entries.append(Entry(name=name, modified=m["modified"], size=m["size"].strip()))
    return entries


def list_dir(url: str) -> list[Entry]:
    url = url.rstrip("/") + "/"

    def fetch():
        with _open(url, timeout=60) as resp:
            return resp.read().decode("utf-8", errors="replace")

    return parse_listing(_retry(fetch, what=url))


def download(url: str, dest: Path) -> int:
    """Baixa em streaming para o disco (a Lambda tem /tmp de até 10 GB)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    def fetch():
        with _open(url, timeout=900) as resp, open(tmp, "wb") as fh:
            shutil.copyfileobj(resp, fh, length=8 * 1024 * 1024)

    _retry(fetch, what=url)
    tmp.rename(dest)
    return dest.stat().st_size
