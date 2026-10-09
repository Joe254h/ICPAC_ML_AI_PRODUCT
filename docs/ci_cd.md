# CI/CD

`ci.yml` verifies the committed HPC artifacts against their SHA-256, checks Python
formatting, lint and types, runs the Python tests, then the frontend lint, types, unit
tests and build, and the Playwright browser tests. Those start a local ECMWF Open Data
mirror (real GRIB2 files, made-up rainfall) and run the weekly cycle through the
interface before checking every page. `build.yml` builds the Compose images and starts both
services for health checks. `release.yml` is manually triggered and packages source;
deployment is not automatic.

Secrets stay in deployment environment variables or secret storage. CI does not need HPC
access, ECMWF or CHIRPS downloads.
