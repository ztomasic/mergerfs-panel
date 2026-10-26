# Security policy

## Supported versions

The latest release on the `main` branch receives fixes. This is a small project with
no LTS branches; older releases are not maintained.

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's private
reporting form:

**Repository → Security → Report a vulnerability**

Include:

- affected version (`mergerfs-panel --version`),
- distribution and desktop environment,
- a description of the impact and the conditions required,
- reproduction steps or a proof of concept,
- any suggested mitigation.

You will get an acknowledgement when the report is reviewed. Fixes are coordinated
privately and published in a release with credit unless you prefer otherwise.

## Scope

The application runs as an ordinary user and has no setuid component, no root helper,
and no network listeners. It shells out to `mergerfs`, `fusermount3`,
`mergerfs-fusermount`, and `umount`, and writes xattrs on mounts owned by the current
user.

In scope:

- command or argument injection through paths, names, or config values;
- path validation bypasses that could make a pool recurse or operate outside the
  intended mount;
- privilege escalation beyond the user who started the app;
- unsafe handling of the configuration file;
- denial of service that requires no special local access beyond running the app.

Out of scope:

- problems in mergerfs, UDisks2, polkit, GTK, or the kernel — report those upstream;
- behaviour that requires root or another user's cooperation;
- the absence of `allow_other` (a deliberate default);
- data recovery after a disk failure (mergerfs has no redundancy).

## Disclosure

Please allow time for a fix and a release before public disclosure. There is no bug
bounty.
