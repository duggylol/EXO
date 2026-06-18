"""Single source of truth for the app version + update source.

Bump VERSION when you cut a release, then tag the repo with the same value
(e.g. git tag v1.0.2) so the GitHub Actions build publishes a matching release
that the in-app updater finds.

UPDATE_REPO is the default GitHub repo the auto-updater checks. Baking it in
here (rather than only in config.yaml) means every build can self-update even
if a user's saved config predates the setting.
"""
VERSION = "1.0.2"
UPDATE_REPO = "duggylol/EXO"
