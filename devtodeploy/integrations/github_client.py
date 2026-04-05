from __future__ import annotations

import base64
import time
from pathlib import Path

import git
from github import Github, GithubException, Repository

from devtodeploy.utils.logging import get_logger
from devtodeploy.utils.retry import with_retry

logger = get_logger("github_client")


class GitHubClient:
    def __init__(self, token: str, org: str) -> None:
        self.gh = Github(token)
        self.org = org
        self._token = token

    @with_retry(max_attempts=3, min_wait=2, max_wait=8, exceptions=(GithubException,))
    def create_repo(self, name: str, description: str = "", private: bool = False) -> Repository.Repository:
        """Create a new GitHub repository. Appends timestamp if name is taken."""
        try:
            owner = self.gh.get_organization(self.org)
        except GithubException:
            owner = self.gh.get_user(self.org)

        try:
            repo = owner.create_repo(
                name,
                description=description,
                private=private,
                auto_init=False,
            )
            logger.info("github_repo_created", repo=repo.full_name)
            return repo
        except GithubException as e:
            if e.status == 422:  # name already taken
                new_name = f"{name}-{int(time.time())}"
                logger.warning("repo_name_taken", original=name, new_name=new_name)
                return owner.create_repo(
                    new_name,
                    description=description,
                    private=private,
                    auto_init=False,
                )
            raise

    def push_directory(
        self,
        repo: Repository.Repository,
        local_path: str,
        commit_msg: str = "Initial commit",
        branch: str = "main",
    ) -> None:
        """Git init + push a local directory to the GitHub repo."""
        path = Path(local_path)
        git_repo = git.Repo.init(str(path))

        remote_url = (
            f"https://{self._token}@github.com/{repo.full_name}.git"
        )
        if "origin" in [r.name for r in git_repo.remotes]:
            git_repo.delete_remote("origin")
        origin = git_repo.create_remote("origin", remote_url)

        git_repo.git.add(A=True)
        git_repo.index.commit(commit_msg)
        git_repo.git.branch("-M", branch)
        origin.push(refspec=f"{branch}:{branch}", force=True)
        logger.info("pushed_to_github", repo=repo.full_name, branch=branch)

    @with_retry(max_attempts=3, min_wait=2, max_wait=8, exceptions=(GithubException,))
    def create_or_update_file(
        self,
        repo: Repository.Repository,
        path: str,
        content: str,
        commit_msg: str,
        branch: str = "main",
    ) -> None:
        """Create or update a single file in the repo via the GitHub API."""
        encoded = base64.b64encode(content.encode()).decode()
        try:
            existing = repo.get_contents(path, ref=branch)
            repo.update_file(path, commit_msg, content, existing.sha, branch=branch)
            logger.info("github_file_updated", path=path)
        except GithubException as e:
            if e.status == 404:
                repo.create_file(path, commit_msg, content, branch=branch)
                logger.info("github_file_created", path=path)
            else:
                raise

    @with_retry(max_attempts=3, min_wait=2, max_wait=8, exceptions=(GithubException,))
    def create_tag(
        self,
        repo: Repository.Repository,
        tag: str,
        message: str,
        branch: str = "main",
    ) -> None:
        """Create a lightweight tag on the latest commit of the given branch."""
        ref = repo.get_git_ref(f"heads/{branch}")
        sha = ref.object.sha
        repo.create_git_tag(tag, message, sha, "commit")
        repo.create_git_ref(f"refs/tags/{tag}", sha)
        logger.info("github_tag_created", tag=tag)

    @with_retry(max_attempts=3, min_wait=2, max_wait=8, exceptions=(GithubException,))
    def create_release(
        self,
        repo: Repository.Repository,
        tag: str,
        name: str,
        body: str,
    ) -> str:
        """Create a GitHub Release and return its HTML URL."""
        release = repo.create_git_release(
            tag=tag,
            name=name,
            message=body,
            draft=False,
            prerelease=False,
        )
        logger.info("github_release_created", url=release.html_url)
        return release.html_url
