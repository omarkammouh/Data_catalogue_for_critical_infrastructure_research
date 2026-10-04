# Updates and releases

## Import a local snapshot

Imports are deliberate operations. They do not run on a schedule and do not change the source directory.

```sh
python scripts/import_snapshot.py --source /path/to/source
```

The source contains `catalog/data/`, `catalog/model/`, `catalog/platform/` and `catalog/case_study/`. The command reads the saved records twice to detect changes during capture. It compares incoming records with the last imported hashes and the current public files. Read `.local/import/report.json` before applying.

- An incoming change applies when the public record still matches the previous imported record.
- Community edits remain when the incoming record is unchanged.
- Different changes on both sides produce a conflict. Deleting a record that has a community edit also produces a conflict.
- New community records remain. The importer never replaces the repository tree.

If the source needs public-content transformations, use a reviewed local JSON policy with `--policy /path/to/policy.json`. The policy accepts field-scoped regular-expression replacements, excluded source URL prefixes and tag patterns. Keep local policy files in `.local/`; do not commit private source locations or working labels. Use the same policy for the dry run and apply.

Resolve conflicts explicitly. The importer has no force-overwrite option. Apply a conflict-free import with the same arguments plus `--apply`, then run the full checks and review the Git diff. Do not resolve a conflict by editing the baseline hashes to suppress it. The incoming data should first incorporate the agreed resolution, or the maintainer should make a reviewed reconciliation of both versions.

Dashboard code updates are separate patches, reviewed against public changes. No data import replaces code, documentation or workflow files.

## Prepare a release

Use semantic versions: a patch for corrections, a minor version for additions or compatible features, and a major version for incompatible schema or interface changes.

1. Update `catalog/snapshot.json` with the capture date, version and computed record counts. Update `CITATION.cff`, `.zenodo.json` and the changelog to the same version. Refresh README counts from the records.
2. Run `make validate test test-browser build release`. Inspect the complete dashboard at a project subpath and at phone width. Check the release download checksums.
3. Review the proposed public tree and commit it. Tag the reviewed commit with `vX.Y.Z`. Do not move published tags or rewrite public history.
4. Push the branch and tag. Confirm the Checks workflow succeeds. Run Publish dashboard on the reviewed version and verify the actual Pages site.
5. Before the first release, enable the repository in the maintainer's Zenodo GitHub settings.
6. Publish a GitHub release for the tag, attach `build/release/catalogue.json.gz`, `catalogue.csv.gz` and `SHA256SUMS`, and describe the changes.
7. Verify the Zenodo record and its archived source. The source archive contains the individual records and tool; do not assume separately attached GitHub release assets were archived by the integration.
8. Record the returned version DOI and concept DOI in the citation guide and website. Keep citation metadata consistent. Correct released files through a new release.

## Recover a deployment

If a site deployment fails, the preceding deployment remains available. Fix the build or configuration and deploy a checked revision. A published data correction receives a new release; it does not overwrite an archived version.
