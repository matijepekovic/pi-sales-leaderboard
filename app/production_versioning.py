"""Production release numbering and branch isolation.

Development/main keeps the appliance's internal numeric versions. Production
uses semantic versions and may only inspect/download the production branch,
never the development default branch.

This is an interim source-repo updater boundary. The public installer/OTA
pipeline can later replace the source download without changing the version
scheme.
"""
import base64
import sys
import urllib.parse

PRODUCTION_BRANCH = "production"
_INSTALLED = False
_BASE_REMOTE_INFO = None


def install():
    global _INSTALLED, _BASE_REMOTE_INFO
    if _INSTALLED:
        return False

    server = sys.modules.get("server") or sys.modules.get("__main__")
    if server is None:
        raise RuntimeError("Server module is unavailable for production versioning.")

    _BASE_REMOTE_INFO = getattr(server, "github_remote_info", None)
    if _BASE_REMOTE_INFO is None:
        raise RuntimeError("GitHub update helper is unavailable.")

    def production_remote_info(repo_value):
        repo = server.normalize_github_repo(repo_value)
        branch = PRODUCTION_BRANCH
        encoded_branch = urllib.parse.quote(branch, safe="")
        info = server.github_api_json(
            f"/repos/{repo}/contents/VERSION?ref={encoded_branch}"
        )
        encoded = str(info.get("content") or "").replace("\n", "")
        if not encoded:
            raise ValueError("Production VERSION file is missing from GitHub.")
        try:
            version = base64.b64decode(encoded).decode("utf-8").strip()
        except Exception as exc:
            raise ValueError("Could not read the production VERSION file.") from exc
        if not version:
            raise ValueError("Production VERSION file is empty.")
        return {"repo": repo, "branch": branch, "version": version}

    server.github_remote_info = production_remote_info
    _INSTALLED = True
    return True
