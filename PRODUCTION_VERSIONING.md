# Production Versioning

Public production releases use semantic versioning: `MAJOR.MINOR.PATCH`.

- `MAJOR`: incompatible/breaking production change.
- `MINOR`: new production-ready feature.
- `PATCH`: production bug fix or small correction.

The production branch starts at `1.0.0`.

Development on `main` keeps the existing internal numeric versions (`119`, `120`, ...). Development version numbers do not determine the public production version.

Only bump the production version when a production release is intentionally shipped.
