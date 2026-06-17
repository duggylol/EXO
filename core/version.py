"""Single source of truth for the app version.

Bump this when you cut a release, then tag the repo with the same value
(e.g. git tag v1.0.1) so the GitHub Actions build publishes a matching release
that the in-app updater can find.
"""
VERSION = "1.0.0"
