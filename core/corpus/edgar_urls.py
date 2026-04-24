from __future__ import annotations

from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
import httpx


SEC_USER_AGENT = 'hank-corpus/0.1 hank@hank.investments'
_SEC_BASE_URL = 'https://www.sec.gov'


def accession_document_url(cik: str, accession: str) -> str:
    """Construct the SEC accession index page URL."""
    cik_digits = ''.join(ch for ch in str(cik).strip() if ch.isdigit())
    cik_no_leading_zeros = cik_digits.lstrip('0') or '0'
    accession_with_dashes = str(accession).strip()
    accession_nodashes = accession_with_dashes.replace('-', '')
    return (
        f'{_SEC_BASE_URL}/Archives/edgar/data/'
        f'{cik_no_leading_zeros}/{accession_nodashes}/{accession_with_dashes}-index.htm'
    )


def fetch_primary_document_html(cik: str, accession: str) -> str:
    """Fetch the accession index, resolve the primary document link, then fetch HTML."""
    index_response = httpx.get(
        accession_document_url(cik, accession),
        headers={'User-Agent': SEC_USER_AGENT},
        timeout=30.0,
    )
    index_response.raise_for_status()

    primary_document_url = _extract_primary_document_url(index_response.text)
    document_response = httpx.get(
        primary_document_url,
        headers={'User-Agent': SEC_USER_AGENT},
        timeout=30.0,
    )
    document_response.raise_for_status()
    return document_response.text


def _extract_primary_document_url(index_html: str) -> str:
    soup = BeautifulSoup(index_html, 'html.parser')
    for row in soup.select('table.tableFile tr'):
        link = row.find('a', href=True)
        if link is None:
            continue
        return _normalize_sec_href(str(link['href']))

    raise ValueError('could not find primary document link on SEC accession index page')


def _normalize_sec_href(href: str) -> str:
    parsed = urlparse(href)
    doc_targets = parse_qs(parsed.query).get('doc')
    if doc_targets:
        href = doc_targets[0]

    if href.startswith('http://') or href.startswith('https://'):
        return href
    if href.startswith('/'):
        return f'{_SEC_BASE_URL}{href}'
    return urljoin(f'{_SEC_BASE_URL}/', href)


__all__ = ['SEC_USER_AGENT', 'accession_document_url', 'fetch_primary_document_html']
