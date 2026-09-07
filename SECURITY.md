# Security policy

## Supported versions

Security fixes are applied to the latest release.

| Version | Supported |
| --- | --- |
| 0.3.x | Yes |
| Earlier | No |

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. If that is unavailable, open a minimal issue asking for a private contact channel without including exploit details, task contents, tokens, or personal data.

Include the affected version, operating system, Herdr version, reproduction conditions, and impact. Please allow a reasonable period for investigation before public disclosure.

## Threat model

Herdr Tasks reduces accidental browser exposure by binding the viewer to `127.0.0.1`, using an opaque per-space capability URL, fixing each server to one queue, rejecting browser writes and foreign hosts, omitting durable actor IDs, and shipping a restrictive Content Security Policy.

It is not an authorization boundary between processes running as the same operating-system user. A local process that can read the task database or viewer state directory can read task content. Do not put credentials, authentication codes, private keys, or unrelated private conversation data in tasks.
