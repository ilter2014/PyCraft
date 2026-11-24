# Contributing to PyCraft

Thank you for your interest in contributing to PyCraft. This document explains how authorized contributors should propose, develop, and submit changes.

## 1. Contributor Access

PyCraft is a source-available project maintained under the terms of its proprietary license.

- Write access is granted only to contributors approved by the repository owner.
- Public access to the repository does not automatically grant permission to push changes.
- Contributors must follow the repository's license and contribution requirements.
- Do not share your repository access or credentials with another person.

If you do not have write access, you may still review the public source and report issues through the repository's available GitHub features. Do not assume that a public fork or local modification grants permission to redistribute or commercially use the project.

## 2. Branch Workflow

All development work must take place on a separate branch.

1. Start from the latest available `main` branch.
2. Create a clearly named branch for your change.
3. Make and test your changes on that branch.
4. Push your branch to the repository.
5. Open a pull request targeting `main`.

Examples of branch names:

- `feature/inventory-improvements`
- `fix/texture-loading`
- `docs/update-controls`

Do not commit directly to `main`. Do not attempt to bypass repository rules or review requirements.

## 3. Pull Request Requirements

Every proposed change to `main` must be submitted through a pull request.

A pull request should:

- Have a clear, specific title.
- Explain what changed and why.
- Identify relevant issues, if any.
- Include steps used to test the change.
- Mention known limitations or possible side effects.
- Keep unrelated changes out of the same pull request.

Before submitting, check that your branch is up to date with the intended target and that the project still runs as expected.

## 4. Release Notes and Labels

PyCraft uses GitHub's automatically generated release notes. Contributors do not need to edit a changelog file for every change.

Repository maintainers categorize merged pull requests with labels. The release notes configuration uses these labels:

| Label | Release notes category |
| --- | --- |
| `feature` | Features |
| `bug`, `fix` | Bug Fixes |
| `enhancement`, `update` | Improvements |
| `documentation`, `docs` | Documentation |
| `skip-changelog` | Excluded from release notes |

If a pull request has no specific category label, it may appear under Other Changes. Maintainers are responsible for applying the appropriate label before a release is published.

## 5. Review and Approval

Pull requests are reviewed by the repository owner or an authorized maintainer.

- A pull request is not approved merely because it has been opened.
- Review feedback must be addressed before merging.
- New commits may require another review.
- Required GitHub review checks and branch protection rules must pass.
- Only an authorized maintainer may merge an accepted pull request.

The repository's configured GitHub rules take precedence if they impose additional requirements.

## 6. Code and Project Quality

When contributing code:

- Keep changes focused and consistent with the existing project structure.
- Prefer clear names and readable implementations.
- Avoid adding dependencies unless they are necessary.
- Do not include generated files, temporary files, local settings, credentials, or personal data.
- Never commit API keys, passwords, access tokens, or other secrets.
- Preserve existing functionality unless the pull request explicitly changes it.
- Explain significant architectural or performance-related changes.

For rendering, world-generation, or performance changes, describe the expected impact and test the change in a representative environment where possible.

## 7. Testing

Run the relevant checks before opening a pull request.

For the current project, the following commands are available:

```bash
python app.py --selftest
python app.py
```

If a change affects startup, rendering, input, world interaction, or asset loading, test that behavior in the running game as well. Include the checks you actually performed in the pull request description. Do not claim tests passed if they were not run.

## 8. Reporting Issues

When reporting a bug, include:

- A concise description of the problem.
- Steps to reproduce it.
- Expected behavior and actual behavior.
- Relevant error messages or logs.
- Your operating system, Python version, and relevant hardware or graphics information.
- Screenshots or recordings when they help explain the issue.

For feature suggestions, explain the use case and the problem the suggestion would solve.

Do not publish security-sensitive information in a public issue. Follow the instructions in `SECURITY.md` for security reports.

## 9. Contributor Access Maintenance

Repository write access may be periodically reviewed to keep collaborator permissions current.

Where the repository owner requests an activity confirmation by email, the recipient is expected to respond within the period stated in that request. Under the project's current access-maintenance policy, if no response is received within 15 calendar days after delivery, write access may be revoked as an administrative cleanup measure.

This is not a ban or a judgment about a contributor's work. Existing branches, commits, and contributions are not deleted by this access change. A former contributor may contact the repository owner to request access again.

## 10. License and Contributions

By submitting a contribution, you confirm that you have the right to submit it and that it does not knowingly violate another party's rights.

All contributions remain subject to the project's `LICENSE` and applicable third-party licenses. Submitting a pull request does not grant permission to independently redistribute, sell, or commercially exploit PyCraft or its materials.

Read the complete `LICENSE` before contributing. If you are unsure whether a proposed contribution or included asset is permitted, ask the repository owner before submitting it.

## 11. Questions

For questions about contributor access, permissions, or whether a proposed contribution is appropriate, contact the repository owner before making changes.

Thank you for helping improve PyCraft.
