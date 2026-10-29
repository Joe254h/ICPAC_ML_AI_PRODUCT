# What to try after the CatBoost refit

The service's model in use is MBC plus a CatBoost residual on 24 inputs, refitted on
2005–2021 (docs/operational_models.md). CatBoost is close to the best a per-cell tree model
can do with those inputs. The next gains are more likely to come from models that see the
whole map, from probabilities instead of one number, and from more predictors. This note
lists what to try, in an order that fits a small team, with the reason each one fits East
Africa's Week-2 rainfall.

Facts about other projects were checked on 29 October 2026; licences change, so read each
model card before use.

## 1. Make the refit probabilistic first

A deterministic Week-2 total says nothing about how sure it is. Forecasters, and the
bulletin's heavy-rain wording, need probabilities such as "a 40% chance of more than 50 mm".
The refit's inputs are the ensemble mean and spread, so it cannot simply be run on each
ECMWF member. Four ways, cheapest first:

| Method | How | Why it fits |
|---|---|---|
| Residual quantiles (split conformal) | Keep the deterministic model. From its out-of-fold errors on 2005–2021, take the error quantiles by month and rainfall amount (conditioned on the forecast, as in conformalized quantile regression), add them to each new forecast and cut at 0 mm. | No retraining; intervals hold their stated coverage on data like the training years. A week to build. |
| Threshold classifiers | One CatBoost classifier per bulletin threshold (1, 10, 50, 200 mm/week) on the same 24 inputs, calibrated with isotonic regression on held-out years. | Gives exactly the probabilities the bulletin's classes need; CatBoost and the pipeline stay the same. |
| Quantile CatBoost | Retrain with `loss_function="MultiQuantile:alpha=0.1,0.33,0.5,0.67,0.9"` (or `RMSEWithUncertainty` for a mean and a variance). | One model gives the median and the tercile bounds; terciles against the 2005–2021 climatology give ICPAC's usual below / near / above normal probabilities. |
| Censored shifted gamma (CSGD) | Fit a censored, shifted gamma distribution per cell and month whose parameters depend on the CatBoost forecast and the ECMWF spread, by minimizing CRPS (Scheuerer and Hamill 2015). | The standard calibration for precipitation: it handles dry weeks (a point mass at zero) and heavy tails. |

Judge them with CRPS and its skill score against the 2005–2021 climatology and against the
raw ECMWF ensemble (whose CRPS the evidence page already has), Brier scores at 50 and 200
mm/week, reliability diagrams and the ranked probability skill score for terciles. Keep the
deterministic map as the median; publish the probabilities beside it.

## 2. Models that see the whole map

| Model | What it does | Why it fits |
|---|---|---|
| U-Net (or ResU-Net) post-processing | A convolutional network maps the gridded ECMWF fields (ensemble mean and spread of rainfall, the upper-air fields, topography, the month's climatology) to the Week-2 rainfall map in one pass. | Learns spatial patterns a per-cell model cannot: rain shadows, the lakes, coastal gradients, displaced rain bands. The same inputs and targets as now. |
| Conditional GAN or diffusion model | A generator makes many plausible rainfall maps from the same inputs. | Gives an ensemble with realistic local extremes. ICPAC already runs a cGAN on ECMWF IFS rainfall (the SEWAA project, 6-hour totals): the same approach for Week-2 totals builds on ICPAC's own expertise. |
| Distributional regression network | A neural network predicting the CSGD parameters per cell (Rasp and Lerch 2018). | Probabilistic by construction; sits between CatBoost and the image models. |
| Analog ensemble | For each forecast, the past reforecasts most like it and what was then observed. | A strong, explainable probabilistic baseline that any new model should beat. |

Add predictors the trees have not had: MJO phase and amplitude (RMM indices), the Indian
Ocean Dipole and ENSO indices, soil moisture. At Week 2 the MJO is the main source of
predictability beyond the weather itself.

## 3. Global AI models: use first, fine-tune later

| Model | Licence of the weights | Why it fits | How to use it here |
|---|---|---|---|
| ECMWF AIFS Single and AIFS ENS | CC BY 4.0 (check the checkpoint) | ECMWF's own AI system, run operationally at ECMWF; AIFS ENS gives a 15-day ensemble. Trained with Anemoi (Apache-2.0), which ECMWF documents for fine-tuning. | Add its Week-2 rainfall and fields as extra predictors (multi-model), then fine-tune with Anemoi on East African targets. |
| GenCast (Google DeepMind) | CC BY-NC-SA 4.0 (non-commercial, share-alike) | Probabilistic medium-range forecasts to 15 days; strong ensemble skill. | Run through ECMWF's ai-models or NVIDIA Earth2Studio; compare its Week-2 rain with the refit. ICPAC's public service is non-commercial, but share-alike binds derived weights. |
| Aurora (Microsoft) | Code MIT; weights CC BY-NC-SA 4.0 | Built to be fine-tuned (short and roll-out fine-tuning with LoRA); new variables can be learned from its latent space with the backbone frozen. | Fine-tune a precipitation head for East Africa on CHIRPS or IMERG. |
| Prithvi WxC (NASA and IBM) | Open weights on Hugging Face (check the licence) | A 2.3-billion-parameter foundation model with fine-tuning workflows for forecasting and downscaling; Prithvi-Precip fine-tunes it for medium-range precipitation. | Downscale and correct rainfall over the region. |
| FuXi-S2S | Check availability | Daily forecasts to 42 days that its authors report beat the ECMWF S2S model for precipitation. | A route to Weeks 3 and 4 if its code and weights are available. |

The cheapest useful step is to take the open AI models' Week-2 forecasts as extra inputs to
the existing pipeline and to verify them like every other forecast (the Copilot already
accepts another model's weekly NetCDF for comparison).
Fine-tuning a global model needs GPUs and ERA5-scale data handling; start it once the
multi-model comparison shows which one helps most.

## 4. Temperature and heat stress

* **Week-2 maximum and minimum temperature.** Additive bias correction plus CatBoost on the
  same pipeline; ensemble model output statistics (a normal distribution) for
  probabilities. Temperature is more predictable than rainfall at Week 2.
* **Heat stress.** Compute indices from forecast temperature, humidity, wind and radiation
  (heat index, wet-bulb globe temperature, or UTCI as in Copernicus's ERA5-HEAT), and warn
  at local percentiles. Check which of those fields ECMWF Open Data provides before
  committing to an index.
* **References.** CHIRTS-ERA5 (the Climate Hazards Center's daily maximum and minimum
  temperatures) for verification over East Africa, ERA5 elsewhere.
* **In the service.** Registry entries carry a model family and task: a temperature model
  is a new task with its own verification target, so it never mixes with the rainfall
  scores.

## 5. Bringing a new model into the service

A retrained bundle of the same kind as the refit (MBC plus CatBoost on the 24 inputs,
exported by the training pipeline with its manifest) is uploaded on the Models page as a
ZIP with its registration descriptor. It is checked and registered as experimental; run
forecasts with it from Operations ("Model for this run"), compare its verified weeks with
the model in use, then approve and activate it. A model of another kind (a U-Net, a
fine-tuned global model) needs a loader in `climate_engine/models/`; until then its weekly
NetCDF forecasts are uploaded in the Copilot and verified against CHIRPS the same way.

## Related work and code

* ICPAC's operational cGAN rainfall forecasts: [icpac-igad/SEWAA-forecasts](https://github.com/icpac-igad/SEWAA-forecasts)
  (fork of Fenwick-Cooper/SEWAA-forecasts), documented at
  [cgan.icpac.net](https://cgan.icpac.net/documentation); the method is Antonio et al.
  (2025, JAMES), "Postprocessing East African rainfall forecasts using a generative
  machine learning model"; see also "Improved rainfall forecasts in daily use over East
  Africa" ([arXiv:2512.24525](https://arxiv.org/abs/2512.24525)).
* ICPAC's cGAN tutorial: icpac-igad/cGAN_tutorial (fork of snath-xoc/cGAN_tutorial).
* Seasonal rainfall with machine learning over East Africa:
  [arXiv:2409.06238](https://arxiv.org/abs/2409.06238).
* ECMWF: [ecmwf/anemoi-core](https://github.com/ecmwf/anemoi-core) (training AIFS-type
  models), [ecmwf/ecmwf-opendata](https://github.com/ecmwf/ecmwf-opendata) (used here),
  [ecmwf-lab/ai-models](https://github.com/ecmwf-lab/ai-models) (running AI models from
  ECMWF data), AIFS weights at [huggingface.co/ecmwf](https://huggingface.co/ecmwf).
* [google-deepmind/graphcast](https://github.com/google-deepmind/graphcast) (GraphCast and
  GenCast), [microsoft/aurora](https://github.com/microsoft/aurora),
  [NVIDIA/earth2studio](https://github.com/NVIDIA/earth2studio) (many AI weather models in
  one toolkit), [google-research/weatherbench2](https://github.com/google-research/weatherbench2)
  (verification), Prithvi WxC on Hugging Face (ibm-nasa-geospatial).
* The WMO S2S AI Challenge (2021): machine learning for Weeks 3–4 and 5–6 temperature and
  rainfall, scored with the ranked probability skill score
  ([s2s-ai-challenge.github.io](https://s2s-ai-challenge.github.io)); its template moved
  to RenkuLab.
