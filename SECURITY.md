# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Use GitHub's private reporting instead: open the **Security** tab of this repository and choose
**Report a vulnerability**. Include what you found, how to reproduce it and what you think the
impact is. You will get an answer as soon as possible.

## What is covered

This is a portfolio project, not a hosted service. The code in this repository is in scope:
the two Flask services, the Terraform and the GitHub Actions workflows. The controls in place
and the known gaps are listed in [`docs/security.md`](docs/security.md).

## Secrets

No secret belongs in this repository. If you find a key, token or credential in the code or in
the history, report it the same way so it can be revoked.
