# Glossary for the Forecaster Copilot

Approved short definitions. The Copilot quotes them for "what is ..." questions; they
describe terms, never current forecast values.

## Weather
aliases: weather
The state of the atmosphere at a given time and place (rainfall, temperature, wind, humidity and cloud) over hours to days.

## Climate
aliases: climate
The long-term statistics of weather in a place, usually summarised over 30 years: the averages, variability and extremes of rainfall, temperature and other variables.

## Climatology
aliases: climatology, normal, normals
The long-term average and spread of a variable for a given place and time of year. Anomalies and percentiles are measured against it.

## Rainfall anomaly
aliases: rainfall anomaly, anomaly, anomalies, more than usual rainfall, less than usual rainfall
The difference between forecast rainfall and the climatology for the same period and place, often given in percent. It needs an approved Week-2 rainfall climatology, which this platform does not have yet.

## Exceptional rainfall
aliases: exceptional rainfall, 95th percentile, extreme rainfall
Rainfall above the 95th percentile of the climatological distribution for that place and time of year: amounts exceeded only 5% of the time. It needs approved percentile thresholds, which this platform does not have yet.

## Week-2 forecast
aliases: week-2, week 2, week two, week-2 forecast, days 8-14
A forecast of the total over days 8 to 14 after the forecast initialisation (forecast hours 168 to 336). This platform forecasts Week-2 rainfall totals in mm.

## Sub-seasonal forecast
aliases: s2s, sub-seasonal, subseasonal, sub-seasonal to seasonal
A forecast two weeks to two months ahead, between weather forecasts and seasonal outlooks. The ECMWF sub-seasonal (S2S) ensemble is this platform's input.

## ECMWF
aliases: ecmwf, raw ecmwf
The European Centre for Medium-Range Weather Forecasts. Its extended-range ensemble provides the raw Week-2 rainfall and the atmospheric fields this platform corrects.

## CHIRPS
aliases: chirps
Climate Hazards Group InfraRed Precipitation with Station data: a rainfall dataset combining satellite estimates and rain gauges at about 0.05 degrees. It is the observation reference for training and verification.

## MBC
aliases: mbc, bias correction, multiplicative bias correction
The locked multiplicative bias correction of the ECMWF ensemble-mean Week-2 rainfall: MBC = max(0, ensemble mean x R), where R is a fixed ratio for the initialisation month and grid cell.

## Atmos37
aliases: atmos37, atmos37 features, features
The 37 predictors the CatBoost model reads for each grid cell: Week-2 ensemble rainfall statistics, MBC and ECMWF atmospheric fields, in a fixed order checked against the model's feature schema.

## CatBoost
aliases: catboost, mbc + atmos37 catboost, hybrid, hybrid forecast
A gradient-boosted decision-tree library. Here a CatBoost model predicts the residual (CHIRPS minus MBC) from the Atmos37 features; the hybrid forecast is MBC plus that residual, floored at zero.

## Candidate model
aliases: candidate, candidate model, production model, production
A registered model that passed its integrity checks but has not been promoted to production. Production needs the independent 2022-2024 test and a named reviewer; until then forecasts are drafts for forecaster review.

## RMSE
aliases: rmse, root mean square error
Root mean square error: the square root of the mean squared difference between forecast and observation, in mm. Lower is better; large errors weigh more.

## MAE
aliases: mae, mean absolute error
Mean absolute error: the average size of the forecast minus observation difference, in mm. Lower is better.

## Bias
aliases: bias
The mean of forecast minus observation, in mm. Positive bias means the forecast was too wet on average, negative too dry.

## Correlation
aliases: correlation, spatial correlation, pearson correlation
The Pearson correlation between forecast and observed values across grid cells for one week: how well the spatial pattern matches, from -1 to 1. One week's correlation is not temporal forecast skill.

## Heat stress
aliases: heat stress, heat stress index, heat index
How hot conditions feel to the body, combining temperature and humidity, grouped into caution, extreme caution and danger categories. This platform has no temperature or humidity forecast yet.

## Greater Horn of Africa
aliases: gha, greater horn of africa
The 11 countries ICPAC serves: Burundi, Djibouti, Eritrea, Ethiopia, Kenya, Rwanda, Somalia, South Sudan, Sudan, Tanzania and Uganda.

## ICPAC
aliases: icpac
The IGAD Climate Prediction and Applications Centre in Nairobi, Kenya: the regional climate centre for the Greater Horn of Africa.

## IGAD
aliases: igad
The Intergovernmental Authority on Development, the regional economic community of Djibouti, Eritrea, Ethiopia, Kenya, Somalia, South Sudan, Sudan and Uganda.
