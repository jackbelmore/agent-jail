# Security policy

`agent-jail` is a security boundary, so escapes are bugs I want to hear about.

**Reporting:** please use GitHub's private vulnerability reporting
(Security → "Report a vulnerability") rather than a public issue. Include the
profile and options, your distribution, kernel, bubblewrap and pasta versions,
and the steps that reach something the jail should hide.

**In scope:** anything listed under "What is protected" in
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) that a process inside the jail can
read, write or connect to.

**Out of scope:** the items under "What is not protected" in the same file, and
anything that needs `--net host`, `--git off`, `--force` or extra `--ro` paths.
