ICPAC ML/AI PRODUCT
HPC SCIENTIFIC ARTIFACT PACKAGE

Purpose
-------
These files are the frozen scientific artifacts required to connect
the ICPAC ML/AI web application to the validated HPC forecasting
pipeline.

Current model
-------------
MBC + Atmos37 + CatBoost residual learning.

Current experiment
------------------
MBC_EXPERIMENT_20261005

Domain
------
Authoritative ICPAC-11 corrected domain.

Full ECMWF grid
---------------
800 x 700

Evaluation domain
-----------------
205,999 cells

Feature count
-------------
37

Feature order
-------------
1  X_mean
2  X_spread
3  latitude
4  longitude
5  doy_sin
6  doy_cos
7  q850_mean
8  q850_spread
9  q700_mean
10 q700_spread
11 u850_mean
12 u850_spread
13 v850_mean
14 v850_spread
15 wind850_mean
16 wind850_spread
17 qu850_mean
18 qu850_spread
19 qv850_mean
20 qv850_spread
21 qwind850_mean
22 qwind850_spread
23 t850_mean
24 t850_spread
25 t500_mean
26 t500_spread
27 deltaT850_500_mean
28 deltaT850_500_spread
29 gh500_mean
30 gh500_spread
31 u200_mean
32 u200_spread
33 v200_mean
34 v200_spread
35 shear200_850_mean
36 shear200_850_spread
37 MBC_forecast

Important
---------
The training matrices, historical ECMWF archive, CHIRPS archive,
atmospheric chunks, validation arrays and 537-case prediction arrays
are intentionally NOT included.

Those remain on HPC.

The files in this package are the application-level scientific
artifacts required for inference and map production.
