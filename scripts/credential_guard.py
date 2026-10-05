"""Reject credential-shaped values without including them in diagnostics."""
import json
import re

PATTERNS = (
    re.compile(r'AIza[A-Za-z0-9_-]{35}'),
    re.compile(r'ghp_[A-Za-z0-9]{30,}'),
    re.compile(r'github_pat_[A-Za-z0-9_]{30,}'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
)


def contains_credential(text):
    return any(pattern.search(text) for pattern in PATTERNS)


def check_record(record):
    if contains_credential(json.dumps(record, ensure_ascii=False)):
        raise ValueError('Record contains a possible credential; import/export refused. '
                         'Use a public landing page without embedded access keys.')
