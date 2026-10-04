# Version 1.0.0 checks

The release contains 64,625 records: 57,723 data records, 3,185 models, 2,231 platforms and 1,486 case studies. Counts are computed from the individual JSON files and agree with the dashboard and downloads.

The release checks cover:

- JSON Schema, controlled vocabulary, stable identity and cross-record reference checks across the full snapshot.
- Python tests of metadata mappings, title preservation and snapshot imports, including community edits and conflicting deletions.
- Reference-query comparisons for 403 combinations over synthetic records and 16 combinations over the full catalogue.
- Browser checks for filters, shared URLs, exports, details, theme, keyboard controls, interface languages, responsive layouts and accessibility.
- Empty-catalogue behaviour and failure of a required data part.
- Citation metadata validation, public-file checks, download checksums and an independent checkout build.

The validator reports one warning for an unclassified licence-name string in the ApolloScape record. Its existing source statement is preserved; no licence is inferred from that warning.

These checks test the released files and software. They do not establish that every linked resource is currently available or suitable for a particular research application. See [limitations](limitations.md).
