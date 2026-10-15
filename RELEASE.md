# Release checklist

Check registry availability and repository ownership before the first release.

Use the GitHub repository `Rayon-API/rayon-sdk-py` and a GitHub Actions
environment named `pypi`. Configure appropriate release reviewer permissions.

On [PyPI's pending publisher page](https://pypi.org/manage/account/publishing/),
select GitHub and enter these exact fields:

| Field | Value |
| --- | --- |
| PyPI project name | `rayon-sdk-py` |
| Owner | `Rayon-API` |
| Repository | `rayon-sdk-py` |
| Workflow filename | `publish.yml` |
| Environment name | `pypi` |

The workflow uses [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
with OpenID Connect. No stored PyPI token is required.

1. Set the version in `pyproject.toml` and `src/rayon_sdk_py/__init__.py` together.
2. Run `python -m pytest`, `python -m build`, and `python -m twine check dist/*`.
   Inspect both archives for source, metadata, README, and the MIT license; exclude
   local configuration, credentials, caches, and build-only dependencies.
3. Commit the reviewed changes and tag the same commit `v<version>` matching the package version.
4. Push the reviewed commit and tag, then publish a GitHub release for that tag.
   Creating a published release runs `.github/workflows/publish.yml`; drafts do not.
5. The workflow checks tag/version agreement, tests all three Python versions,
   builds and checks distributions, then publishes through the `pypi` environment.
6. Verify the PyPI project and installation.

PyPI versions cannot be overwritten. If a released package needs correction,
increment the version and publish a new release.

Verify the current API instructions, sync/async lifecycle, strict input limits, exact body preservation, error envelopes, expiry-scoped references, no automatic POST retries, and packed public type exports. Never rewrite published packages or their release tags. Do not include customer scripts, captured material, credentials, or private fixtures in distributions.

Version 1.0.2 rejects server-issued material references that cannot be reused as valid requests. Verify the short, oversized, and invalid-character response reference regressions before release.

See [CHANGELOG.md](CHANGELOG.md) for release notes.

Version 1.1.0 adds optional form mode. Verify strict encoding, application duplicates,
exact-case form families, telemetry-only body composition, transport mismatch rejection,
material reuse, and new public form types before publishing. Verify the six required
headers with optional fresh same-family `a0`, original names and values, duplicate and
incomplete-family rejection, and exactly six form fields with a larger `a` value.
