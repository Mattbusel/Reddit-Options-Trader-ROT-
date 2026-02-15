# Third-Party License Compliance

## PRAW — Python Reddit API Wrapper

- **License**: BSD 2-Clause
- **PyPI**: https://pypi.org/project/praw/
- **Repository**: https://github.com/praw-dev/praw
- **SPDX**: BSD-2-Clause

PRAW itself is BSD-licensed. However, PRAW depends on **prawcore**, which is also
BSD 2-Clause. Neither PRAW nor prawcore are GPL-licensed.

> **Historical note**: Early versions of PRAW (pre-4.0) were GPLv3. Modern PRAW
> (4.0+, 2016 onward) uses BSD 2-Clause. ROT requires `praw` without a version
> pin, which resolves to the latest BSD-licensed release.

### Compliance

ROT uses PRAW as a **runtime dependency** (not bundled, not modified). Under
BSD 2-Clause, the only requirements are:

1. **Retain copyright notice** in redistributions of source code — satisfied by
   this file and the `praw` package metadata in the virtualenv.
2. **Retain disclaimer** — included in `praw`'s own `LICENSE.txt` within the
   installed package.

No source code from PRAW is copied into this repository.

## Other Security-Critical Dependencies

| Package | License | Notes |
|---------|---------|-------|
| FastAPI | MIT | Web framework |
| Starlette | BSD 3-Clause | ASGI toolkit |
| Pydantic | MIT | Data validation |
| aiosqlite | MIT | Async SQLite |
| python-jose | MIT | JWT tokens |
| cryptography | Apache 2.0 / BSD | Crypto primitives |
| bcrypt | Apache 2.0 | Password hashing |
| uvicorn | BSD 3-Clause | ASGI server |
| Jinja2 | BSD 3-Clause | Templating |
| httpx | BSD 3-Clause | HTTP client |
| scikit-learn | BSD 3-Clause | ML models |
| numpy | BSD 3-Clause | Numerics |
| yfinance | Apache 2.0 | Market data |
| nh3 | MIT | HTML sanitization |
| stripe | MIT | Payment processing |

All dependencies are permissively licensed (MIT, BSD, Apache 2.0). No copyleft
(GPL/LGPL/AGPL) dependencies are used in production.
