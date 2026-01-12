import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_MARKETING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def normalize_url(raw_url: str) -> str:
    raw_url = raw_url.strip()
    parts = urlsplit(raw_url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()

    path = re.sub(r"/{2,}", "/", parts.path)
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower.startswith("utm_"):
            continue
        if key_lower in _MARKETING_PARAMS:
            continue
        query_pairs.append((key, value))

    query_pairs.sort(key=lambda pair: pair[0])
    query = urlencode(query_pairs, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))
