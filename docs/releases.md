# Releases

## Versioning policy

The project follows Semantic Versioning:

- patch: fixes and internal improvements
- minor: backward-compatible features
- major: breaking API, schema, or workflow changes

## Release process

1. Prepare a version change on a release-preparation branch with
   `python scripts/release_prep.py <patch|minor|major> --apply`. Review the
   synchronized version touchpoints and changelog, then merge the PR through the
   normal required checks.
2. After `main` passes both the `CI` and `qBittorrent web-seed API integration`
   workflows for the exact same commit, run **Stage Windows release** from
   GitHub Actions with that version (without a `v` prefix).
3. The workflow verifies the version, rejects an existing tag/release, builds
   the portable x64 Windows ZIP from that exact `main` commit using the Python
   and NuGet locks, and smoke-tests a disposable backend container without host
   mounts. It creates a **draft** GitHub Release for the selected version and
   target SHA only after all gates pass. The version tag is created when the
   approved draft is published; GitHub then supplies source archives for that
   tag. The Windows ZIP and SHA-256 sidecar are attached release assets.
4. Review the draft, changelog, tag target SHA, and Windows assets. Publish the
   draft manually when the release is approved, then verify that the tag resolves
   to the validated SHA and the tagged source archives are available. Publishing
   is not a production deployment.
5. Record known limitations and upgrade notes in the changelog.

The workflow does not publish a container image or access production. Keep
real-instance QA and production promotion within their separately documented
operator/deployment gates.

## Upgrade notes

- Record schema changes in release notes
- Include any new environment variables
- Note any changed sync behavior or route additions

## Rollback expectations

- Keep a backup copy of the SQLite DB before upgrading across schema changes
- If a release causes sync regressions, stop the app and restore the prior DB backup
- qBittorrent remote rules can be rebuilt from the local DB via sync once the app is healthy again

