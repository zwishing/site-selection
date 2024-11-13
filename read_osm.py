import geopandas as gpd
import pandas as pd
import shapely
import os
from osgeo import gdal

def read_osm(fpath:str):
    layers = ['points', 'lines', 'multilinestrings', 'multipolygons', 'other_relations']
    gdfs = []
    for layer in layers:
        try:
            gdf = gpd.read_file(filename=fpath, engine="pyogrio", layer=layer, 
                               on_invalid="ignore")
            gdfs.append(gdf)
        except (shapely.errors.GEOSException, RuntimeError):
            print(f"Skipping layer {layer} due to invalid geometry")
            continue

    if not gdfs:
        raise ValueError("No valid layers found in the OSM file")

    combined_gdf = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))
    out_path = fpath.replace('.osm', '.gpkg')
    combined_gdf.to_file(out_path, driver="GPKG")
    return combined_gdf


def read_osm_from_gdal(fpath: str):
    out_path = fpath.replace('.osm', '.gpkg')

    # Convert OSM to GPKG using ogr2ogr with progress callback
    def progress_callback(complete, message, data):
        pct = complete * 100
        print(f"\rConversion progress: {pct:.1f}%", end='')
        return 1

    # Convert OSM to GPKG using ogr2ogr
    gdal.VectorTranslate(
        out_path,
        fpath,
        format='GPKG',
        layerCreationOptions=['OVERWRITE=YES'],
        skipFailures=True,
        callback=progress_callback
    )
    print() # New line after progress

    if not os.path.exists(out_path):
        raise ValueError("Failed to convert OSM file to GPKG")

    return gpd.read_file(out_path)


if __name__ == '__main__':
    fpath = 'osm_data/长沙.osm'
    gdf = read_osm_from_gdal(fpath)
    print(gdf.head())