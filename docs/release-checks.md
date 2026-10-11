# Version 1.1.0 checks

The release contains 68,670 records: 61,318 data records, 3,466 models, 2,288
platforms and 1,598 case studies. It includes 467 searchable data catalogue links.
All resource IDs match the maintained source, and the reviewed public metadata
policy preserves resource identity while omitting private working references.

Checks cover schema and vocabulary consistency, stable identities, cross-record
references, conflict-aware imports, public-file hygiene, compact and full search
and filter equivalence, details and exports. The full dashboard is tested at a
project subpath, at phone width and with a 192 MB JavaScript heap limit. These
browser checks do not reproduce a physical phone's memory limit.

Validation reports zero errors and 12 inherited warnings for licence labels,
URL normalization and historical verification dates. All 136 Python tests and
54 browser tests pass, with one browser test skipped. All 403 fixture reference
filter states agree. These checks do not establish that every provider link works,
that external catalogue coverage is complete or that each resource is suitable
for a particular simulation. See [limitations](limitations.md).

Version 1.1.0 replaces the initial full-record loading with a compact index of
about 58 MB. All entries remain searchable. Full metadata loads for individual
records and exports, and large filter lists create controls as needed.

All 18 full-catalogue reference queries pass. The initial index is 58,413,402 bytes. The tested browser reports zero console errors and no detected accessibility violations in the phone-width detail view. The JSON and CSV downloads each contain all 68,670 unique IDs, pass the credential guard and match SHA256SUMS.

The [GitHub release](https://github.com/omarkammouh/Data_catalogue_for_critical_infrastructure_research/releases/tag/v1.1.0) is published and archived by [Zenodo](https://doi.org/10.5281/zenodo.23294021). All 68,774 files in the downloaded Zenodo ZIP match the exact Git tree at tag `v1.1.0` (`7f3d999bf718e369e6722bc6be0b10b6bf3dc2a8`), including all 68,670 resource records. The archive checksum matches Zenodo's checksum, and the published JSON/CSV downloads match their checked SHA-256 values. No credential-pattern matches were found in the archive. The live Pages site passed all 18 reference queries with zero console errors. [Saved verification](releases/v1.1.0.json) records the archive and download hashes.

The new version DOI was added to the current citation metadata after archival. This documentation update preserves the released records and software. Version 1.0.0 remains a separate fixed archive.

## Previous release checks

### Version 1.0.0 checks

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

## Published release

The [GitHub release](https://github.com/omarkammouh/Data_catalogue_for_critical_infrastructure_research/releases/tag/v1.0.0) is archived by [Zenodo](https://doi.org/10.5281/zenodo.23143543). The archived ZIP was downloaded and its checksum checked. All 64,714 archived files match the tagged Git tree, including every catalogue record and the dashboard source. The compressed JSON and CSV files downloaded from GitHub match the published SHA-256 checksums.

The deployed Pages site passed the full-catalogue browser checks on 4 October 2026. All 16 reference queries matched and no browser errors were observed. The tested mobile detail view had no detected WCAG 2 A/AA or 2.1 AA violations. This automated check is limited to the tested view and does not certify the entire interface.

DOI links were added to the citation guidance and website after archival.

On 5 October 2026, a security correction removed four direct resource links containing embedded access keys. The affected Git history was rewritten and `v1.0.0` now points to `d3171d4c616f6b6afec0420f027229b927ec997e`. This is an exceptional correction to the published tag. The JSON/CSV release downloads and checksums were replaced. Zenodo’s archive was corrected under the same version and concept DOIs. All 64,714 archived files match the corrected tag; all 64,625 records are retained. The corrected Git history and downloaded exports contain no matches for the four reported credential values. Obsolete GitHub commit URLs still serve the original files and require provider-side removal; this check does not establish that the credentials have been revoked.
