# Execution and SLURM integration

JobExecutor exposes submit, status, cancel and logs. The Jobs page selects Local CPU, Simulated SLURM or Configured SLURM. POST /jobs?executor=local (or mock_slurm/slurm) accepts the forecast Selection. GET /jobs, /jobs/{id} and /jobs/{id}/logs expose states/logs; POST /jobs/{id}/cancel cancels the pipeline group.

## Local
LocalExecutor uses a single bounded CPU worker and fixed stages: download, QC, preprocess, features, inference, verification, products. It loads configured adapters, performs mandatory QC and exact alignment, runs the model, persists verification, and writes forecast.json, rainfall.png and a checksummed manifest under RUN_ROOT. In this prototype each fixed stage reloads small inputs; production should use immutable intermediate products and a durable queue.

Cancellation is cooperative between stages; a currently executing scientific function can finish before stopping. Its cancelled status is preserved. A service restart marks interrupted local jobs failed; it never reports them as completed. Run one API worker for the local executor. Move long-running operations to SLURM or a durable worker service before production.

## Simulation
MockSlurmExecutor advances stages when polled and models afterok dependencies. Its records explicitly say SIMULATED; it creates no scientific products or real cluster jobs. Failed/cancelled dependencies block downstream stages. Simulation is the default so demonstrations need no cluster.

## Real cluster, explicitly opt-in
1. Deploy the checkout and Python environment on trusted shared storage reachable by the API and compute nodes.
2. Configure hpc/templates/stage.slurm with ICPAC account, partition, module/Apptainer setup, memory and wall time.
3. Configure absolute RUN_ROOT, DATA_ROOT, ARTIFACT_ROOT and a shared DATABASE_URL. Use PostgreSQL rather than SQLite on distributed/shared-file deployments.
4. Ensure sinfo, sbatch, sacct and scancel work for the service's operator account. Configure cluster accounting for sacct.
5. Set ENABLE_SLURM=true on that cluster host and submit through the Jobs page or API.

SlurmExecutor uses argument arrays and a fixed template, verifies numeric job IDs, submits seven stages with afterok and --kill-on-invalid-dep=yes, polls sacct, retrieves bounded log tails, and cancels known group IDs. It attempts cancellation if submission partially fails. No user-provided command is executed. No cluster credentials, arbitrary shell, dissemination or model promotion tools are available to the chatbot.

The submission behavior follows the [official sbatch documentation](https://slurm.schedmd.com/sbatch.html); accounting parsing follows [sacct](https://slurm.schedmd.com/sacct.html). Cluster acceptance has not been tested because ICPAC access is unavailable. Deployment/resource values must be validated with the cluster operator.

## Event runner
`python -m scripts.run_pipeline --trigger forecast` generates products. `--trigger observation` persists verification. They use independent state, checksums across config/source/model/code, exclusive locking, and atomic success-state writes. No source archive deletion or automatic distribution is implemented. See the reference-repository assessment in implementation_plan.md.
