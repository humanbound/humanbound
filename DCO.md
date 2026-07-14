# Developer Certificate of Origin

Contributions to this project are accepted under the
[Developer Certificate of Origin v1.1](https://developercertificate.org/)
(DCO), the same mechanism used by the Linux kernel, CNCF projects, and
GitLab. There is nothing to sign and no account to create: you certify the
DCO by adding a `Signed-off-by` line to each commit, which `git` does for
you with the `-s` flag:

```bash
git commit -s -m "fix: handle empty provider list"
```

That appends a trailer with the name and email from your git config:

```
Signed-off-by: Jane Developer <jane@example.com>
```

By signing off, you certify the statements below — in short, that you wrote
the change or otherwise have the right to submit it under the project's
open-source license ([Apache-2.0](./LICENSE)). Contributions are licensed
inbound = outbound: you keep the copyright to your work, and it is licensed
to the project and everyone else under Apache-2.0, exactly like the rest of
the codebase.

If you forget to sign off, amend the commit (`git commit --amend -s`) or
sign off a whole branch (`git rebase --signoff main`) and force-push; the
DCO check on the pull request will re-run automatically.

The full text of the Developer Certificate of Origin v1.1 follows, verbatim:

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.


Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```
