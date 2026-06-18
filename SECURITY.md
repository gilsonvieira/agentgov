# Security Policy

agentgov is a governance and audit library — security and correctness are the
product. We take reports seriously.

## Reporting a vulnerability

Please **do not open a public issue** for security vulnerabilities.

Instead, report privately via GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
("Report a vulnerability" under the repository's **Security** tab).

When reporting, please include:

- A description of the issue and its impact.
- Steps to reproduce (a minimal example is ideal).
- The version / commit affected.

We aim to acknowledge reports within a few business days and will keep you
updated as we work on a fix.

## Scope of particular interest

Because the audit trail is the product, we especially want to hear about:

- Ways to commit a state transition that bypasses a hard rail.
- Ways to tamper with the event log without breaking `verify_chain`.
- Ways to forge or alter an `EvidenceBundle` that still passes `verify_bundle`.
- Replay non-determinism that lets a recorded run reproduce a different
  `state_hash`.
