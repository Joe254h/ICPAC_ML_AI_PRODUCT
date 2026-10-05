# Deployment

Docker Compose starts a non-root backend and frontend on localhost ports 8000 and 3000, with persistent SQLite storage. The frontend proxy resolves API_URL at runtime, including in its standalone container. Model files are external read-only mounts, not baked into images.

For shared ICPAC infrastructure, add authentication/roles, TLS reverse proxy, approved storage, authoritative region masks, validated science settings and trusted artifacts. DATABASE_URL accepts PostgreSQL through SQLAlchemy; install the postgres extra and use a postgresql+psycopg URL. The record repository is a prototype persistence design; normalize entities and add migrations/uniqueness/audit controls before production.

CDO is optional. Real ECMWF cumulative precipitation needs validated deaccumulation and unit conversion, not the demo increment adapter. HPC settings, partitions and Apptainer packaging depend on ICPAC infrastructure. No email credentials or SLURM secrets belong in Git.
