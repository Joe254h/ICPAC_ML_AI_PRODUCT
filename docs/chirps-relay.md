# CHIRPS relay

The service verifies each week against CHIRPS v2.0 from the Climate Hazards Center (CHC).
CHC answers the Hugging Face Space with "429 Too Many Requests", Spaces cannot use FTP, and
CHC does not always answer GitHub's machines either. So CHIRPS reaches the service through
a relay:

1. `scripts/chirps_relay.sh` reads the recent days (final product when published, else the
   preliminary one) and dekads from CHC, cuts them to the region and publishes them on this
   repository's `chirps-relay` branch.
2. The service reads that branch over HTTPS before it asks CHC (config `chirps.relay`,
   `CHIRPS_RELAY_URL`; `off` switches it off). It replaces a preliminary day with the final
   one when the relay has it.

The script runs every six hours in GitHub Actions (`.github/workflows/chirps-relay.yml`)
and on any machine CHC serves. Runs from several machines add to the branch: a day one of
them read is never lost.

## Run it on the ICPAC HPC (recommended)

CHC serves the HPC, so this is the dependable source, including the preliminary product
of the last weeks.

1. On GitHub: Settings, Developer settings, Personal access tokens, Fine-grained tokens,
   Generate new token. Repository access: only `Joe254h/ICPAC_ML_AI_PRODUCT`.
   Permissions: Contents, Read and write. Copy the token.
2. On the HPC, once:

   ```bash
   cd /scratch/njoel
   git clone https://github.com/Joe254h/ICPAC_ML_AI_PRODUCT.git icpac-relay
   cd icpac-relay
   conda activate climate_dell
   pip install -e .
   printf '%s' 'PASTE_THE_TOKEN' > ~/.chirps-relay-token && chmod 600 ~/.chirps-relay-token
   GITHUB_TOKEN=$(cat ~/.chirps-relay-token) scripts/chirps_relay.sh /scratch/njoel/chirps-relay
   ```

   The first run reads up to 120 days (about 20 minutes); it ends with
   "Published on Joe254h/ICPAC_ML_AI_PRODUCT, branch chirps-relay."
3. Every six hours: `crontab -e` and add (one line; use the environment's own Python):

   ```
   17 */6 * * * cd /scratch/njoel/icpac-relay && git pull -q && PATH=$HOME/miniconda3/envs/climate_dell/bin:$PATH GITHUB_TOKEN=$(cat ~/.chirps-relay-token) scripts/chirps_relay.sh /scratch/njoel/chirps-relay >> $HOME/chirps-relay.log 2>&1
   ```

   Where cron is not allowed on the login node, `scrontab -e` takes the same line (SLURM).
   Adjust `$HOME/miniconda3/envs/climate_dell` to where the environment lives
   (`conda env list`).

## Check it

* `https://raw.githubusercontent.com/Joe254h/ICPAC_ML_AI_PRODUCT/chirps-relay/index.json`
  lists the days held (with final or preliminary) and the dekads.
* On the website, the Archive page shows weeks "Verified · CHIRPS" once their seven days are
  relayed; the verification pass runs every three hours.
