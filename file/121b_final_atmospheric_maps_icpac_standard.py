#!/usr/bin/env python

from pathlib import Path
import numpy as np

import icpac_maps as std


# =============================================================================
# PATHS
# =============================================================================

ROOT = Path(
    "/scratch/njoel/s2s_master_data/results/"
    "FRESH_ATMOS36_20260924/full_corrected_domain"
)

SPATIAL = (
    ROOT
    / "spatial_diagnostics"
)

OUT = (
    ROOT
    / "final_scientific_maps"
)

OUT.mkdir(
    parents=True,
    exist_ok=True,
)


RAW = (
    SPATIAL
    / "Raw_ECMWF_spatial_metrics.npz"
)

MBC = (
    SPATIAL
    / "MBC_spatial_metrics.npz"
)

FINAL7 = (
    SPATIAL
    / "Previous_Final_Hybrid7_spatial_metrics.npz"
)

ATM37 = (
    SPATIAL
    / "Atmospheric_Hybrid37_spatial_metrics.npz"
)

ADDED = (
    SPATIAL
    / "Atmos37_vs_Previous_Final_Hybrid7_added_value.npz"
)


# =============================================================================
# FORCE THE SAME OUTPUT STANDARD AS PREVIOUS HYBRID
# =============================================================================

std.OUTDIR = OUT

# These are presentation labels only.
std.HDR = (
    "Week-2 (days 8–14) | "
    "537 independent test cases | "
    "2022–2024 | "
    "verified against CHIRPS"
)


# =============================================================================
# DATA ACCESSOR
# =============================================================================

def field(
    path,
    key,
    name,
):

    z = np.load(
        path,
        allow_pickle=False,
    )

    required = {
        "latitude",
        "longitude",
        key,
    }

    missing = (
        required
        -
        set(
            z.files
        )
    )

    if missing:
        raise RuntimeError(
            f"{path.name}: missing {missing}"
        )

    return std.Field(
        name,
        np.asarray(
            z[key],
            dtype=float,
        ),
        np.asarray(
            z["latitude"],
            dtype=float,
        ),
        np.asarray(
            z["longitude"],
            dtype=float,
        ),
    )


def F(
    path,
    key,
    name,
):
    return lambda: field(
        path,
        key,
        name,
    )


# =============================================================================
# ADDITIONAL STYLES
# =============================================================================

# Keep the existing frozen "rmse" style unchanged.
#
# These are only quantities that did not exist in the original
# seven-feature map registry.

std.STYLES[
    "delta_rmse_atmos"
] = std.Style(
    "RdBu_r",
    "Atmospheric37 − Final Hybrid7 RMSE (mm/week)",
    "diverging",
    vmin=-1.0,
    vmax=1.0,
    extend="both",
)

std.STYLES[
    "gain_final7"
] = std.Style(
    "RdBu",
    "RMSE improvement vs Final Hybrid7 (%)",
    "diverging",
    vmin=-10.0,
    vmax=10.0,
    extend="both",
)

std.STYLES[
    "delta_corr_atmos"
] = std.Style(
    "RdBu",
    "Change in Pearson correlation",
    "diverging",
    vmin=-0.10,
    vmax=0.10,
    extend="both",
)

std.STYLES[
    "fraction_better"
] = std.Style(
    "RdBu",
    "Fraction of 537 cases",
    "continuous",
    vmin=0.25,
    vmax=0.75,
)

std.STYLES[
    "delta_abs_bias"
] = std.Style(
    "RdBu_r",
    "Change in absolute bias (mm/week)",
    "diverging",
    vmin=-1.0,
    vmax=1.0,
    extend="both",
)


# =============================================================================
# FIGURES — SAME CANVAS / LAYOUT ENGINE AS PREVIOUS HYBRID
# =============================================================================

FIGURES = [

    # -----------------------------------------------------------------
    # 1. MAIN RMSE COMPARISON
    # -----------------------------------------------------------------

    std.Figure(
        "01_RMSE_FINAL_HYBRID7_VS_ATMOS37_ICPAC",
        [
            std.Layer(
                "Final Hybrid7",
                F(
                    FINAL7,
                    "RMSE",
                    "Final Hybrid7 RMSE",
                ),
                "rmse",
            ),

            std.Layer(
                "Atmospheric Hybrid37",
                F(
                    ATM37,
                    "RMSE",
                    "Atmospheric37 RMSE",
                ),
                "rmse",
            ),
        ],
        (
            "Week-2 Rainfall RMSE: "
            "Final Hybrid7 vs Atmospheric Hybrid37"
        ),
        ncols=2,
    ),


    # -----------------------------------------------------------------
    # 2. FOUR-MODEL RMSE
    # -----------------------------------------------------------------

    std.Figure(
        "02_RMSE_RAW_MBC_FINAL7_ATMOS37_ICPAC",
        [
            std.Layer(
                "Raw ECMWF",
                F(
                    RAW,
                    "RMSE",
                    "Raw ECMWF RMSE",
                ),
                "rmse",
            ),

            std.Layer(
                "Multiplicative Bias Correction",
                F(
                    MBC,
                    "RMSE",
                    "MBC RMSE",
                ),
                "rmse",
            ),

            std.Layer(
                "Final Hybrid7",
                F(
                    FINAL7,
                    "RMSE",
                    "Final Hybrid7 RMSE",
                ),
                "rmse",
            ),

            std.Layer(
                "Atmospheric Hybrid37",
                F(
                    ATM37,
                    "RMSE",
                    "Atmospheric37 RMSE",
                ),
                "rmse",
            ),
        ],
        (
            "Week-2 Rainfall RMSE — "
            "Corrected ICPAC-11 Domain"
        ),
        ncols=2,
    ),


    # -----------------------------------------------------------------
    # 3. ABSOLUTE RMSE DIFFERENCE
    # -----------------------------------------------------------------

    std.Figure(
        "03_ATMOS37_MINUS_FINAL7_RMSE_ICPAC",
        [
            std.Layer(
                (
                    "Atmospheric37 − Final Hybrid7\n"
                    "Blue = Atmospheric37 improvement"
                ),
                F(
                    ADDED,
                    "Delta_RMSE_mm",
                    "Atmos37 minus Final7 RMSE",
                ),
                "delta_rmse_atmos",
            ),
        ],
        "Spatial Added Value of Atmospheric Predictors",
        ncols=1,
    ),


    # -----------------------------------------------------------------
    # 4. PERCENT RMSE GAIN
    # -----------------------------------------------------------------

    std.Figure(
        "04_ATMOS37_RMSE_GAIN_VS_FINAL7_ICPAC",
        [
            std.Layer(
                (
                    "RMSE improvement vs Final Hybrid7\n"
                    "Blue = Atmospheric37 improvement"
                ),
                F(
                    ADDED,
                    "RMSE_gain_vs_FinalHybrid7_pct",
                    "Atmos37 gain vs Final7",
                ),
                "gain_final7",
            ),
        ],
        "Atmospheric Predictor RMSE Added Value",
        ncols=1,
    ),


    # -----------------------------------------------------------------
    # 5. CORRELATION CHANGE
    # -----------------------------------------------------------------

    std.Figure(
        "05_ATMOS37_MINUS_FINAL7_CORRELATION_ICPAC",
        [
            std.Layer(
                (
                    "Atmospheric37 − Final Hybrid7\n"
                    "Blue = higher correlation"
                ),
                F(
                    ADDED,
                    "Delta_Correlation",
                    "Atmos37 minus Final7 correlation",
                ),
                "delta_corr_atmos",
            ),
        ],
        "Change in Week-2 Rainfall Correlation with CHIRPS",
        ncols=1,
    ),


    # -----------------------------------------------------------------
    # 6. CASE-WIN FRACTION
    # -----------------------------------------------------------------

    std.Figure(
        "06_ATMOS37_CASE_WIN_FRACTION_ICPAC",
        [
            std.Layer(
                (
                    "Atmospheric37 lower absolute error\n"
                    "> 0.50 = wins more than half of cases"
                ),
                F(
                    ADDED,
                    "Fraction_cases_Atmos37_lower_error_than_FinalHybrid7",
                    "Atmos37 lower-error fraction",
                ),
                "fraction_better",
            ),
        ],
        "Frequency of Atmospheric37 Improvement",
        ncols=1,
    ),


    # -----------------------------------------------------------------
    # 7. ABSOLUTE BIAS CHANGE
    # -----------------------------------------------------------------

    std.Figure(
        "07_ATMOS37_ABSOLUTE_BIAS_CHANGE_ICPAC",
        [
            std.Layer(
                (
                    "Change in absolute bias\n"
                    "Blue = reduced bias magnitude"
                ),
                F(
                    ADDED,
                    "Delta_abs_Bias_mm",
                    "Atmos37 absolute bias change",
                ),
                "delta_abs_bias",
            ),
        ],
        "Atmospheric37 Change in Absolute Bias",
        ncols=1,
    ),


    # -----------------------------------------------------------------
    # 8. PRESENTATION SUMMARY
    #
    # Mixed styles intentionally use individual colourbars,
    # but map geometry remains exactly the frozen ICPAC standard.
    # -----------------------------------------------------------------

    std.Figure(
        "08_ATMOS37_ADDED_VALUE_SUMMARY_ICPAC",
        [
            std.Layer(
                "Final Hybrid7 RMSE",
                F(
                    FINAL7,
                    "RMSE",
                    "Final Hybrid7 RMSE",
                ),
                "rmse",
            ),

            std.Layer(
                "Atmospheric Hybrid37 RMSE",
                F(
                    ATM37,
                    "RMSE",
                    "Atmospheric37 RMSE",
                ),
                "rmse",
            ),

            std.Layer(
                (
                    "Atmospheric37 − Final Hybrid7 RMSE\n"
                    "Blue = improvement"
                ),
                F(
                    ADDED,
                    "Delta_RMSE_mm",
                    "Atmos37 minus Final7 RMSE",
                ),
                "delta_rmse_atmos",
            ),

            std.Layer(
                (
                    "Atmospheric37 lower-error frequency\n"
                    "> 0.50 = more cases improved"
                ),
                F(
                    ADDED,
                    "Fraction_cases_Atmos37_lower_error_than_FinalHybrid7",
                    "Atmos37 case win fraction",
                ),
                "fraction_better",
            ),
        ],
        (
            "Atmospheric Predictor Added Value "
            "for Week-2 Rainfall"
        ),
        ncols=2,
    ),
]


# =============================================================================
# BUILD
# =============================================================================

def main():

    print("=" * 110)
    print("ATMOSPHERIC37 MAPS — FROZEN ICPAC CARTOGRAPHIC STANDARD")
    print("=" * 110)

    print()
    print(
        "Output:",
        OUT,
    )

    print(
        "Boundary source:",
        std.BOUNDARIES,
    )

    print(
        "Logo:",
        std.LOGO,
    )

    print(
        "Frozen extent:",
        std.FROZEN_EXTENT,
    )

    print()

    # The spatial files already contain the verified corrected-domain
    # validity mask. We therefore do not introduce another raster-validity
    # mask here. The frozen Canvas still clips display geometry to the
    # official vector union.
    canvas = std.Canvas(
        use_valid_mask=False
    )

    failed = 0

    for spec in FIGURES:

        try:

            output = std.build(
                canvas,
                spec,
            )

            print(
                "PASS:",
                output.name,
                flush=True,
            )

        except Exception as exc:

            failed += 1

            print(
                "FAIL:",
                spec.name,
                type(exc).__name__,
                str(exc),
                flush=True,
            )

    print()
    print("=" * 110)

    if failed:
        raise RuntimeError(
            f"{failed} figure(s) failed"
        )

    print(
        f"ALL {len(FIGURES)} ICPAC-STANDARD FIGURES BUILT"
    )

    print("=" * 110)


if __name__ == "__main__":
    main()
