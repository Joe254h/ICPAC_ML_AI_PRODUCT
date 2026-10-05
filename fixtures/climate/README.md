# Demonstration fixtures
Daily rainfall is generated deterministically in climate_engine/observations. Source perturbations are synthetic, not measurements. The 60×60 coarse grid makes CI small and fast; small countries can have no cell centres. These are reported as unavailable, never assigned another country's values.

countries.geojson is a subset of Natural Earth's public-domain 1:110m countries, fetched from nvkelso/natural-earth-vector. The same file is served by the frontend. These are cartographic demonstration boundaries, not ICPAC's authoritative operational mask. Full Somalia is present. Source: https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson
