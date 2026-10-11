"""Small, lossless search/filter index with separately fetched full records."""
import json
import unicodedata
import base64
from hashlib import sha256


def normalise(text):
    text = ''.join(c for c in unicodedata.normalize('NFKD', text)
                   if not '\u0300' <= c <= '\u036f').lower()
    return ' '.join(''.join(c if unicodedata.category(c)[0] in 'LN' else ' '
                           for c in text).split())


def compact_bundle(bundle, text_fields, extract, stem):
    """Keep all searchable words and facet values, including missing values.

    Search tokens are independent words, so word order and repeated words do
    not affect substring or padded-trigram matching. Original names remain
    intact for the existing phrase and name scoring rules.
    """
    facets = bundle['facets']
    codes = [{str(v['value']): i for i, v in enumerate(f.get('values', []))}
             for f in facets]
    for i, f in enumerate(facets):
        f['_column'] = i
    words, word_codes, rows, detail_parts = [], {}, [], []
    card_fields = ('id', 'type', 'name', 'title_en', 'provider', 'sectors',
                   'catalogues', 'countries', 'data_resource_type', 'licence',
                   'cost', 'date_catalogued', 'date_verified', 'last_updated',
                   'description_checked')
    for start in range(0, len(bundle['records']), 128):
        records = bundle['records'][start:start + 128]
        text = json.dumps(records, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        name = f'records-{sha256(text.encode()).hexdigest()[:20]}.json'
        detail_parts.append((name, text))
        for r in records:
            row = {k: r[k] for k in card_fields if k in r}
            row['description'] = (r.get('description') or '')[:160]
            row['_detail'] = len(detail_parts) - 1
            fields = [r.get(k) for k in text_fields]
            text = ' '.join(' '.join(map(str, v)) if isinstance(v, list)
                            else str(v) for v in fields if v is not None)
            indices = []
            for word in sorted(set(normalise(text).split())):
                if word not in word_codes:
                    word_codes[word] = len(words)
                    words.append(word)
                indices.append(word_codes[word])
            row['_words'] = indices
            row['_facets'] = [None if f['kind'] == 'text' else
                              extract(r, f) if f['kind'] == 'range' else
                              [codes[i][str(v)] for v in extract(r, f)]
                              for i, f in enumerate(facets)]
            rows.append(row)
    meta = dict(bundle['meta'], detail_parts=[p[0] for p in detail_parts],
                loading_format='compact-v1')
    compact = dict(meta=meta, facets=facets, records=rows, search_words=words)
    # Independently valid JSON parts: only two responses need to be retained
    # while loading; there is no full-sized join and parse copy.
    # Intern card values and facet value sets once. The wire format uses
    # variable-length integers; the browser keeps search/facet columns in
    # typed arrays instead of millions of separate number/empty-array objects.
    fields = list(card_fields) + ['description']
    values, value_codes = [None], {'null': 0}
    sets, set_codes = [], {}
    def intern(value, table, codes):
        key = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        if key not in codes:
            codes[key] = len(table); table.append(value)
        return codes[key]
    encoded_rows, word_stream, facet_stream = [], [], []
    for row in rows:
        encoded_rows.append([intern(row.get(k), values, value_codes) for k in fields]
                            + [len(row['_words']), row['_detail']])
        ids = sorted(row['_words'])
        word_stream.append([v - (ids[i - 1] if i else 0) for i, v in enumerate(ids)])
        facet_stream.append([intern(v or [], sets, set_codes) for v in row['_facets']])
    def encode(stream):
        out = bytearray()
        for value in stream:
            while value >= 128:
                out.append((value & 127) | 128); value >>= 7
            out.append(value)
        return base64.b64encode(out).decode('ascii')
    parts = []
    for i, start in enumerate(range(0, max(1, len(rows)), 2000)):
        end = start + 2000
        part = dict(records=encoded_rows[start:end],
                    word_codes=encode(v for row in word_stream[start:end] for v in row),
                    facet_codes=encode(v for row in facet_stream[start:end] for v in row))
        if i == 0:
            part.update(meta=meta, facets=facets, search_words=words,
                        card_fields=fields, card_values=values, facet_sets=sets)
        text = json.dumps(part, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        parts.append((f'{stem}-{i + 1}-{sha256(text.encode()).hexdigest()[:16]}.json', text))
    return compact, parts + detail_parts, [p[0] for p in parts]
