"""GitHub API client using httpx."""
import os
from typing import Dict, List, Optional
import httpx

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=GITHUB_API, headers=self.headers, timeout=30.0)

    # --- Repositories ---
    async def list_repos(self, installation_id: Optional[int] = None) -> list:
        """List every repository accessible to the token/installation.

        GitHub paginates this endpoint even when ``per_page=100``.  Following
        the response's ``Link`` header prevents accounts with more than 100
        repositories from being silently truncated.
        """
        params = {"per_page": 100, "page": 1, "sort": "updated"}
        if installation_id:
            params["installation_id"] = installation_id
        async with self._client() as client:
            repositories = []
            while True:
                resp = await client.get("/user/repos", params=params)
                resp.raise_for_status()
                page = resp.json()
                if not isinstance(page, list):
                    raise ValueError("GitHub repository response was not a list")
                repositories.extend(page)

                # Link headers are authoritative; the short-page fallback
                # also supports GitHub-compatible test doubles and proxies.
                if 'rel="next"' not in resp.headers.get("Link", ""):
                    break
                params["page"] += 1
                if params["page"] > 1000:
                    raise RuntimeError("GitHub repository pagination exceeded safety limit")
            return repositories

    async def get_repo(self, owner: str, repo: str) -> dict:
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}")
            resp.raise_for_status()
            return resp.json()

    # --- Commits ---
    async def list_commits(
        self,
        owner: str,
        repo: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
        branch: Optional[str] = None,
        per_page: int = 100,
    ) -> list:
        params = {"per_page": per_page}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if branch:
            params["sha"] = branch
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/commits", params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_commit(self, owner: str, repo: str, sha: str) -> dict:
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/commits/{sha}")
            resp.raise_for_status()
            return resp.json()

    async def get_file(self, owner: str, repo: str, path: str, ref: Optional[str] = None) -> dict:
        """Get file content from GitHub repository."""
        params = {}
        if ref:
            params["ref"] = ref
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/contents/{path}", params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_commit_diff(self, owner: str, repo: str, sha: str) -> str:
        async with httpx.AsyncClient(base_url=GITHUB_API, headers={
            **self.headers,
            "Accept": "application/vnd.github.v3.diff",
        }) as client:
            resp = await client.get(f"/repos/{owner}/{repo}/commits/{sha}")
            resp.raise_for_status()
            return resp.text

    # --- Pull Requests ---
    async def list_prs(
        self,
        owner: str,
        repo: str,
        state: str = "all",
        per_page: int = 100,
    ) -> list:
        params = {"state": state, "per_page": per_page}
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/pulls", params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_pr(self, owner: str, repo: str, number: int) -> dict:
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/pulls/{number}")
            resp.raise_for_status()
            return resp.json()

    async def get_pr_files(self, owner: str, repo: str, number: int) -> list:
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/pulls/{number}/files")
            resp.raise_for_status()
            return resp.json()

    async def get_pr_diff(self, owner: str, repo: str, number: int) -> str:
        async with httpx.AsyncClient(base_url=GITHUB_API, headers={
            **self.headers,
            "Accept": "application/vnd.github.v3.diff",
        }) as client:
            resp = await client.get(f"/repos/{owner}/{repo}/pulls/{number}")
            resp.raise_for_status()
            return resp.text

    # --- Branches ---
    async def list_branches(self, owner: str, repo: str, per_page: int = 100) -> list:
        params = {"per_page": per_page}
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/branches", params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_branch(self, owner: str, repo: str, branch: str) -> dict:
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/branches/{branch}")
            resp.raise_for_status()
            return resp.json()

    # --- Files ---
    async def get_file(self, owner: str, repo: str, path: str, ref: Optional[str] = None) -> dict:
        params = {}
        if ref:
            params["ref"] = ref
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/contents/{path}", params=params)
            resp.raise_for_status()
            return resp.json()

    # --- Deployments ---
    async def list_deployments(self, owner: str, repo: str, per_page: int = 100) -> list:
        params = {"per_page": per_page}
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/deployments", params=params)
            resp.raise_for_status()
            return resp.json()

    # --- Search ---
    async def search_code(self, query: str, per_page: int = 30) -> dict:
        params = {"q": query, "per_page": per_page}
        async with self._client() as client:
            resp = await client.get("/search/code", params=params)
            resp.raise_for_status()
            return resp.json()

    # --- Installation Token ---
    async def get_installation_token(self, installation_id: int, app_id: str, private_key: str) -> str:
        """Generate an installation access token using JWT."""
        import time
        import jwt

        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 600,
            "iss": app_id,
        }
        jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

        async with self._client() as client:
            resp = await client.post(
                f"/app/installations/{installation_id}/access_tokens",
                headers={"Authorization": f"Bearer {jwt_token}"}
            )
            resp.raise_for_status()
            return resp.json()["token"]

    # --- Webhooks ---
    async def create_webhook(
        self,
        owner: str,
        repo: str,
        url: str,
        events: list,
        secret: str,
    ) -> dict:
        async with self._client() as client:
            resp = await client.post(
                f"/repos/{owner}/{repo}/hooks",
                json={
                    "name": "web",
                    "active": True,
                    "events": events,
                    "config": {
                        "url": url,
                        "content_type": "json",
                        "secret": secret,
                    },
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def list_webhooks(self, owner: str, repo: str) -> list:
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/hooks")
            resp.raise_for_status()
            return resp.json()

    # --- Branch, Commit, PR Creation ---

    async def create_branch(self, owner: str, repo: str, branch_name: str, from_branch: str = "main") -> Dict:
        """Create a new branch from an existing branch."""
        # Get the SHA of the source branch
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/git/ref/heads/{from_branch}")
            if resp.status_code == 404:
                # Try master
                resp = await client.get(f"/repos/{owner}/{repo}/git/ref/heads/master")
            resp.raise_for_status()
            sha = resp.json()["object"]["sha"]

            # Create the new branch
            resp = await client.post(
                f"/repos/{owner}/{repo}/git/refs",
                json={
                    "ref": f"refs/heads/{branch_name}",
                    "sha": sha,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def create_commit(
        self, owner: str, repo: str, branch: str,
        message: str, files: List[Dict],
    ) -> Dict:
        """Create a commit with multiple file changes."""
        async with self._client() as client:
            # Get the latest commit SHA on the branch
            resp = await client.get(f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
            resp.raise_for_status()
            base_sha = resp.json()["object"]["sha"]

            # Get the tree
            resp = await client.get(f"/repos/{owner}/{repo}/git/commits/{base_sha}")
            resp.raise_for_status()
            base_tree = resp.json()["tree"]["sha"]

            # Create blobs for each file and build tree
            tree_items = []
            for file_info in files:
                content = file_info.get("content", "")
                # Create blob
                resp = await client.post(
                    f"/repos/{owner}/{repo}/git/blobs",
                    json={"content": content, "encoding": "utf-8"},
                )
                resp.raise_for_status()
                blob_sha = resp.json()["sha"]

                tree_items.append({
                    "path": file_info["path"],
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha,
                })

            # Create tree
            resp = await client.post(
                f"/repos/{owner}/{repo}/git/trees",
                json={"base_tree": base_tree, "tree": tree_items},
            )
            resp.raise_for_status()
            new_tree = resp.json()["sha"]

            # Create commit
            resp = await client.post(
                f"/repos/{owner}/{repo}/git/commits",
                json={
                    "message": message,
                    "tree": new_tree,
                    "parents": [base_sha],
                },
            )
            resp.raise_for_status()
            commit_sha = resp.json()["sha"]

            # Update branch reference
            resp = await client.patch(
                f"/repos/{owner}/{repo}/git/refs/heads/{branch}",
                json={"sha": commit_sha, "force": True},
            )
            resp.raise_for_status()

            return {"commit_sha": commit_sha, "branch": branch}

    async def create_pull_request(
        self, owner: str, repo: str,
        title: str, body: str, head: str, base: str = "main",
        draft: bool = True,
    ) -> Dict:
        """Create a pull request (draft or ready for review)."""
        async with self._client() as client:
            resp = await client.post(
                f"/repos/{owner}/{repo}/pulls",
                json={
                    "title": title,
                    "body": body,
                    "head": head,
                    "base": base,
                    "draft": draft,
                },
            )
            resp.raise_for_status()
            pr_data = resp.json()
            return {
                "pr_number": pr_data["number"],
                "pr_url": pr_data["html_url"],
                "pr_api_url": pr_data["url"],
                "draft": pr_data.get("draft", draft),
            }


# Singleton instance
_client: Optional[GitHubClient] = None


def get_github_client(token: Optional[str] = None) -> GitHubClient:
    global _client
    if _client is None or token:
        _client = GitHubClient(token)
    return _client
