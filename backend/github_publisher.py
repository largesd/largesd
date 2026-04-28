"""
GitHub Publisher — publish consolidated debate results to a GitHub repository.

Uses the GitHub Contents API (PUT /repos/{owner}/{repo}/contents/{path})
to create or update a JSON file. Handles SHA detection for updates.
"""
import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import requests


class GitHubPublishError(RuntimeError):
    """Raised when publishing to GitHub fails."""
    pass


@dataclass(frozen=True)
class GitHubPublishResult:
    repository: str
    branch: str
    path: str
    commit_sha: str
    html_url: Optional[str]
    api_url: Optional[str]
    download_url: Optional[str]


class GitHubPublisher:
    """
    Publish JSON payloads to a file in a GitHub repository via the Contents API.
    """

    def __init__(
        self,
        repository_full_name: str,
        token: str,
        path: str = "data/consolidated_results.json",
        branch: str = "main",
        api_base_url: str = "https://api.github.com",
        author_name: Optional[str] = None,
        author_email: Optional[str] = None,
    ):
        if "/" not in repository_full_name:
            raise ValueError(
                "repository_full_name must be in 'owner/repo' format"
            )
        self.repository_full_name = repository_full_name
        self.token = token
        self.path = path
        self.branch = branch
        self.api_base_url = api_base_url.rstrip("/")
        self.author_name = author_name or "Blind Debate Adjudicator"
        self.author_email = author_email or "bot@debate.local"

    @property
    def contents_url(self) -> str:
        return (
            f"{self.api_base_url}/repos/"
            f"{self.repository_full_name}/contents/{self.path}"
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }

    def _get_existing_sha(self) -> Optional[str]:
        """Return the SHA of the existing file, or None if it doesn't exist."""
        try:
            resp = requests.get(
                self.contents_url,
                headers=self._headers(),
                params={"ref": self.branch},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("sha")
            if resp.status_code == 404:
                return None
            raise GitHubPublishError(
                f"GitHub API error checking file: {resp.status_code} {resp.text}"
            )
        except requests.RequestException as exc:
            raise GitHubPublishError(f"Network error checking file: {exc}") from exc

    def publish_json(
        self,
        payload: Dict[str, Any],
        commit_message: str,
    ) -> GitHubPublishResult:
        """
        Publish a JSON payload to the configured path.

        Args:
            payload: The JSON-serializable dict to publish.
            commit_message: The Git commit message.

        Returns:
            GitHubPublishResult with commit metadata.
        """
        content_bytes = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        content_b64 = base64.b64encode(content_bytes).decode("ascii")

        body: Dict[str, Any] = {
            "message": commit_message,
            "content": content_b64,
            "branch": self.branch,
        }

        sha = self._get_existing_sha()
        if sha:
            body["sha"] = sha

        body["committer"] = {
            "name": self.author_name,
            "email": self.author_email,
        }

        try:
            resp = requests.put(
                self.contents_url,
                headers=self._headers(),
                json=body,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise GitHubPublishError(f"Network error publishing file: {exc}") from exc

        if resp.status_code not in (200, 201):
            raise GitHubPublishError(
                f"GitHub API error publishing file: {resp.status_code} {resp.text}"
            )

        data = resp.json()
        commit = data.get("commit", {})
        return GitHubPublishResult(
            repository=self.repository_full_name,
            branch=self.branch,
            path=self.path,
            commit_sha=commit.get("sha", ""),
            html_url=data.get("html_url"),
            api_url=data.get("url"),
            download_url=data.get("download_url"),
        )


def get_publisher_from_env() -> Optional[GitHubPublisher]:
    """Factory that reads GITHUB_REPO and GITHUB_TOKEN from environment."""
    repo = os.getenv("GITHUB_REPO")
    token = os.getenv("GITHUB_TOKEN")
    if not repo or not token:
        return None
    return GitHubPublisher(
        repository_full_name=repo,
        token=token,
        path=os.getenv("GITHUB_RESULTS_PATH", "data/consolidated_results.json"),
        branch=os.getenv("GITHUB_BRANCH", "main"),
        author_name=os.getenv("GITHUB_AUTHOR_NAME", "Blind Debate Adjudicator"),
        author_email=os.getenv("GITHUB_AUTHOR_EMAIL", "bot@debate.local"),
    )
