"""Serve our own APK from our own server at /download/sh-prediction.apk.

The APK is built for free by our GitHub Actions workflow (android-apk.yml) and attached to the
`apk-latest` release. When the repository is private, GitHub release links need a login, so this
server fetches the file with a read-only token (env SH_GITHUB_TOKEN) and streams it to the phone.
Without a token it redirects to the public release link (works while the repository is public).
"""
import json
import os
import urllib.error
import urllib.request

REPO = os.getenv("SH_GITHUB_REPO", "shsportsaclub-dot/sh-prediction")
TAG = "apk-latest"
ASSET = "sh-prediction.apk"
PUBLIC_URL = "https://github.com/%s/releases/download/%s/%s" % (REPO, TAG, ASSET)

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None

def _default_open(req, follow=True):
    if follow:
        return urllib.request.urlopen(req, timeout=60)
    return urllib.request.build_opener(_NoRedirect).open(req, timeout=60)

def resolve(token=None, opener=_default_open):
    """Return ("redirect", url) or ("stream", response). opener is injectable for tests."""
    token = token if token is not None else os.getenv("SH_GITHUB_TOKEN", "")
    if not token:
        return "redirect", PUBLIC_URL
    h = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "User-Agent": "sh-prediction-server"}
    rel = json.loads(opener(urllib.request.Request("https://api.github.com/repos/%s/releases/tags/%s" % (REPO, TAG), headers=h)).read())
    asset = next(a for a in rel["assets"] if a["name"] == ASSET)
    h["Accept"] = "application/octet-stream"
    try:
        # GitHub answers with a redirect to a signed storage URL; follow it WITHOUT the token.
        r = opener(urllib.request.Request(asset["url"], headers=h), follow=False)
        return "stream", r
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            return "stream", opener(urllib.request.Request(e.headers["Location"], headers={"User-Agent": "sh-prediction-server"}))
        raise
