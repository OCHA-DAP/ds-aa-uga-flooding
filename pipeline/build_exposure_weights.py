"""Population weight matrix: population per (district x FloodScan cell), built once.

Flood exposure is population living where the satellite sees water. The team's
ds-floodexposure-monitoring pipeline computes it by interpolating each daily SFED
raster onto the WorldPop grid and summing per admin; Uganda has never been run
through it (its WorldPop input is on blob, but `app.floodscan_exposure` holds no
UGA rows), so it is computed here on the same input.

Rather than re-gridding 10,000+ daily rasters, the geometry is done once: for every
district, exactextract gives the coverage fraction of each 1 km WorldPop cell, each
WorldPop cell is mapped to the FloodScan cell containing it, and the products are
accumulated into a matrix W[district, fs_cell] = population of that district inside
that FloodScan cell. Daily exposure is then W @ sfed_flat — a matrix-vector product
(the weight-matrix trick from ds-raster-stats PR #49).

Writes (dev blob):
  {PROJECT_PREFIX}/processed/exposure/pop_weights.npz   W (dense float32), pcodes, grid spec

Run:  uv run python pipeline/build_exposure_weights.py
"""

import io
import sys
from pathlib import Path

import numpy as np
import ocha_stratus as stratus
import rasterio
from exactextract import exact_extract

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.constants import PROJECT_PREFIX
from src.zonal import read_windowed
from src.zones import load_adm2

WORLDPOP = "ds-floodexposure-monitoring/raw/worldpop/uga_ppp_2020_1km_Aggregated_UNadj.tif"
OUT_BLOB = f"{PROJECT_PREFIX}/processed/exposure/pop_weights.npz"
SAMPLE_SFED = "floodscan/daily/v5/processed/aer_area_300s_v2020-10-15_v05r01.tif"


def main() -> None:
    adm = load_adm2()[["ADM2_PCODE", "ADM2_EN", "geometry"]].reset_index(drop=True)

    # canonical FloodScan grid: the same window every daily read produces
    _, bounds, _ = read_windowed(SAMPLE_SFED)
    arr, _, _ = read_windowed(SAMPLE_SFED)
    ny, nx = arr.shape
    xmin, ymin, xmax, ymax = bounds
    resx, resy = (xmax - xmin) / nx, (ymax - ymin) / ny
    print(f"FloodScan grid {ny}x{nx}, bounds {bounds}, res {resx:.5f}")

    raw = stratus.load_blob_data(WORLDPOP, container_name="projects", stage="dev")
    with rasterio.open(io.BytesIO(raw)) as ds:
        pop = ds.read(1).astype("float64")
        pop[pop == ds.nodata] = 0.0
        pop[~np.isfinite(pop)] = 0.0
        wp_transform = ds.transform
        print(f"WorldPop {pop.shape}, total {pop.sum():,.0f}")
        res = exact_extract(
            ds, adm, ["cell_id", "coverage"], output="pandas", include_cols=["ADM2_PCODE"]
        )

    W = np.zeros((len(adm), ny * nx), dtype="float64")
    pop_flat = pop.ravel()
    wp_ncols = pop.shape[1]
    pcode_row = {p: i for i, p in enumerate(adm.ADM2_PCODE)}
    for _, r in res.iterrows():
        cells = np.asarray(r["cell_id"], dtype="int64")
        cov = np.asarray(r["coverage"], dtype="float64")
        if cells.size == 0:
            continue
        wrow, wcol = np.divmod(cells, wp_ncols)
        # WorldPop cell centre -> FloodScan cell index
        x, y = rasterio.transform.xy(wp_transform, wrow, wcol)
        fx = np.clip(((np.asarray(x) - xmin) / resx).astype(int), 0, nx - 1)
        fy = np.clip(((ymax - np.asarray(y)) / resy).astype(int), 0, ny - 1)
        np.add.at(W[pcode_row[r["ADM2_PCODE"]]], fy * nx + fx, cov * pop_flat[cells])

    print(f"weight matrix {W.shape}; population captured {W.sum():,.0f} of {pop.sum():,.0f}")
    buf = io.BytesIO()
    np.savez_compressed(
        buf,
        W=W.astype("float32"),
        pcodes=adm.ADM2_PCODE.to_numpy().astype("U12"),
        bounds=np.array(bounds),
        shape=np.array([ny, nx]),
    )
    stratus.upload_blob_data(buf.getvalue(), OUT_BLOB, stage="dev")
    print("wrote", OUT_BLOB)


if __name__ == "__main__":
    main()
