# Third-party notices

CodeAsk's own code is under the MIT licence in [LICENSE](LICENSE). That licence does **not**
cover the third-party source code described below, which belongs to its authors and stays
under its own licence.

## Featured repositories

The public demo answers questions about three open-source projects. Short excerpts of their
source code, quoted with file paths and line numbers, appear in this repository: in the
pre-generated answers (`frontend/data/examples/`), the evaluation records (`eval/results/`),
the design mock-ups (`frontend/design/`) and test fixtures. The excerpts are unmodified copies
of lines from the commits pinned below. Each licence text in `third_party/licenses/` is a
byte-for-byte copy of the file in that repository at that commit.

| Project | Licence | Copyright holder(s) | Source | Pinned commit | Licence text |
|---|---|---|---|---|---|
| itsdangerous | BSD-3-Clause | Pallets | https://github.com/pallets/itsdangerous | `672971d66a2ef9f85151e53283113f33d642dabd` | [itsdangerous-LICENSE.txt](third_party/licenses/itsdangerous-LICENSE.txt) |
| Requests | Apache-2.0 | Kenneth Reitz (see NOTICE) | https://github.com/psf/requests | `3c7baaa05ab4aa49cc819ce3a819d260de19c157` | [requests-LICENSE.txt](third_party/licenses/requests-LICENSE.txt), [requests-NOTICE.txt](third_party/licenses/requests-NOTICE.txt) |
| Express | MIT | TJ Holowaychuk, Roman Shtylman, Douglas Christopher Wilson | https://github.com/expressjs/express | `1c6f1b0fe4000977b9a7b4f34097e4d527dd9824` | [express-LICENSE.txt](third_party/licenses/express-LICENSE.txt) |

### Requests NOTICE

As the Apache License 2.0 (section 4d) requires, the attribution notice from Requests' NOTICE
file is reproduced here:

```
Requests
Copyright 2019 Kenneth Reitz
```

## Tools

The Claude Code skills used while building CodeAsk are not included in this repository. The
README says where to install them from.
