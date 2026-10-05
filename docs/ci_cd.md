# CI/CD

ci.yml validates formatting, lint, Python types, scientific/adapter/API tests, frontend lint/types/unit tests/build, and a small Playwright workflow. build.yml builds Compose images and starts both services for health checks. release.yml is manually triggered and packages source; production deployment is not automatic. Configure required reviewers for the release-review GitHub environment before releasing operational artifacts.

Secrets stay in deployment environment variables or approved secret storage. Small synthetic fixtures ship in the repository. CI does not require HPC/GPU access or climate-data downloads. Branch protection and required checks should be enabled by the repository administrator.
