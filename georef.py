#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
@author: christian

python version 3.12

'''

# =============================================================================
# Standard Python modules
# =============================================================================
import argparse
import logging
import os
import json 
from typing import Dict, Literal

# =============================================================================
# External Python modules
# =============================================================================
import fiona
import geopandas as gpd
import pandas as pd
from pydantic import BaseModel
import rapidfuzz

# =============================================================================
# Extension modules
# =============================================================================
from processors import ProcessorOSM

# =====================================
# script-wide declarations
# =====================================
logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.DEBUG)

PATH_CACHE_DIR = "./georef_cache/"
os.makedirs(PATH_CACHE_DIR, exist_ok=True)
PATH_CACHE_META = "./georef_cache/META.json"

STATE_MAPPING = {
        "city_extracted":1,
        "boundaries_fixed":2,
        "use_type_added":3,
        }

class MetaDictCity(BaseModel):
    name:str
    state:Literal[*STATE_MAPPING.keys()]
    # though these are introduced only at the end of step 1, they are still 
    #   required - no need to cache anything before that.
    filename_city:str
    filename_boundaries_within:str
    filename_all_mp_within:str

class MetaDict(BaseModel):
    cities:Dict[str,MetaDictCity]

class GeoStat():
    '''
    current limitations:
    - input file id is not cached, so any cache items simply assume its the same 
    input file as before
    - the only processor implemented is for osm data, thus the only data 
    structure supported is osm data
    - cache is only saved for the most recent step and overwrites data from 
    earlier steps, meaning I can only start from scratch or the last step
    '''
    def __init__(self, path_in, processor):
        self.processor = processor
        self.path_in = path_in
        if not os.path.isfile(self.path_in):
            raise ValueError("file does not exist")
        if os.path.splitext(path_in)[-1].lower() != ".gpkg":
            raise ValueError("file is not .gpkg type (by name)")
        if os.path.isfile(PATH_CACHE_META):
            logging.debug(f"trying to read {PATH_CACHE_META}")
            with open(PATH_CACHE_META) as f:
                data = f.read()
                self.cache_meta = MetaDict.model_validate_json(data)
        else:
            logging.info(f"creating new {PATH_CACHE_META}")
            self.cache_meta = MetaDict(cities=dict())
            self._dump_meta()

   
    def _dump_meta(self):
        with open(PATH_CACHE_META, "w") as f:
            f.write(self.cache_meta.model_dump_json(indent=2))


    def _debug_print_layers(self):
        logging.debug(f"layers in input file: {fiona.listlayers(self.path_in)}")

    def get_gdf(self, layer="multipolygons"):
        logging.info("reading file (could take a second)")
        gdf = gpd.read_file(self.path_in, layer=layer)
        logging.debug(f"columns: {gdf.columns}")
        logging.debug(f"CRS: {gdf.crs}")
        logging.debug(f"#rows: {len(gdf)}")
        return gdf

    def _set_state(self, state):
        self.cache_meta.cities[self.name].state = state

    def cache_get_state(self, city_name):
        if city_name not in self.cache_meta.cities:
            return None
        mdc = self.cache_meta.cities.get(city_name, None)
        return mdc.state

    def _get_cache_filepaths(self, name):
        city_path = os.path.join(PATH_CACHE_DIR, f"{name}_city.gpkg")
        boundaries_within_path = os.path.join(PATH_CACHE_DIR, f"{name}_boundaries_within.gpkg")
        all_mp_within_path = os.path.join(PATH_CACHE_DIR, f"{name}_all_mp_within.gpkg")
        return city_path, boundaries_within_path, all_mp_within_path

    def fetch_boundaries_only(self):
        return self.processor.fetch_boundaries_only(self.path_in)

    def extract_city(self, name, gdf):
        """This extracts, saves in self and caches as gpkg:

        self.city_m : administrative boundary of the city 

        self.boundaries_within: sub boundaries within self.city_m

        self.all_mp_within : all multipolygons that are mostly self.city_m and 
            not administrative boundaries
        """
        known_admin_boundaries =self.processor.get_all_admin_boundaries(gdf)
        logging.debug(f"admin boundaries: {len(known_admin_boundaries)}")
        self.name = name
        candidates = known_admin_boundaries[known_admin_boundaries["name"] == name].copy()
        logging.info(f"found {len(candidates)} places with that name")
        if len(candidates)==0:
            logging.error("{name} not found, exiting")
            exit()
        candidates_m = candidates.to_crs(25832)
        candidates["area_m2"] = candidates_m.area
        city = candidates.sort_values("area_m2", ascending=False).iloc[[0]].copy()
        #self.name = self.city.name.iloc[0]
        admin_m = known_admin_boundaries.to_crs(25832)
        city_m = city.to_crs(25832)
        city_area = float(city_m.iloc[0]['area_m2'])
        logging.info(f"admin border (level {city_m.iloc[0]['admin_level']}) picked has area {city_area}")

        ## get sub boundaries

        others = admin_m[admin_m.index != city_m.index[0]].copy()
        bbox = city_m.total_bounds #minx miny maxx maxy

        others = others.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]
        boundaries_within = others[others.intersects(city_m.geometry.iloc[0])].copy()
        boundaries_within["area_m2"] = boundaries_within.area
        boundaries_within = boundaries_within[
                (boundaries_within.centroid.within(city_m.geometry.iloc[0])) &
                (boundaries_within["area_m2"]<=city_area) &
                (self.processor.is_admin_level_subcity(boundaries_within))
        ].copy()
        logging.info(f"found {len(boundaries_within)} sub boundaries")
        if len(boundaries_within) == 0:
            logging.error("aborting, no sub boundaries")

        ## get all non-boundary multipolygons (mostly) within city limits

        bbox_og_crs = city.total_bounds
        # I use the orig crs to save RAM
        all_polygons = gdf.cx[bbox_og_crs[0]:bbox_og_crs[2], bbox_og_crs[1]:bbox_og_crs[3]]
        # I reproject the intersects view, creating a copy without explicitly calling .copy()
        all_mp_within = all_polygons[all_polygons.intersects(city.geometry.iloc[0])].to_crs(25832)
        # now I need to switch from city to city_m
        all_mp_within["area_m2"] = all_mp_within.area
        all_mp_within = all_mp_within[
                (all_mp_within.centroid.within(city_m.geometry.iloc[0])) &
                (all_mp_within["area_m2"]<=city_area) &
                (self.processor.not_admin_boundary(all_mp_within))
        ].copy()
        logging.info(f"extracted {len(all_mp_within)} multipolygons within city boundaries")

        ## save and cache 

        cp, wp, ap = self._get_cache_filepaths(self.name)
        logging.info("caching filtered gpkg")
        city_m.to_file(cp, driver="GPKG")
        self.city_m = city_m
        boundaries_within.to_file(wp, driver="GPKG")
        self.boundaries_within = boundaries_within
        all_mp_within.to_file(ap, driver="GPKG")
        self.all_mp_within = all_mp_within

        self.cache_meta.cities[self.name] = MetaDictCity(
                name=self.name, 
                filename_city = cp,
                filename_boundaries_within = wp,
                filename_all_mp_within = ap,
                state="city_extracted"
        )
        self._dump_meta()

    def load_cached_mp(self, name):
        """ mirrors extract_city, but loads the data from cache
        """
        logging.info("reading from cache")
        self.name = name
        mdc = self.cache_meta.cities.get(name, None)
        if mdc is None:
            raise ValueError("did the cache vanish or what?")
        self.city_m = gpd.read_file(mdc.filename_city)
        logging.info(f"admin border loaded has area {float(self.city_m.iloc[0]['area_m2'])}")
        self.boundaries_within = gpd.read_file(mdc.filename_boundaries_within)
        logging.info(f"loaded {len(self.boundaries_within)} sub boundaries")
        self.all_mp_within = gpd.read_file(mdc.filename_all_mp_within)
        logging.info(f"loaded {len(self.all_mp_within)} multipolygons within city boundaries")

    # step 2 - "fix" sub boundaries

    def fix_sub_boundaries(self):
        logging.info("fixing sub boundaries, adding Restgebiet if neccessary")
        mdc = self.cache_meta.cities.get(self.name, None)
        if mdc is None:
            raise ValueError("fr, why is there no cache at his point?")
        city_m_geom = self.city_m.geometry.make_valid().iloc[0]
        self.boundaries_within["geometry"] = self.boundaries_within.geometry.make_valid()
        boundaries_union = self.boundaries_within.geometry.union_all()
        boundaries_union = boundaries_union.intersection(city_m_geom)
        rest_geom = city_m_geom.difference(boundaries_union)
        if rest_geom.is_empty or rest_geom.area == 0:
            logging.debug("nothing to fix, empty rest area")
        else:
            logging.debug(f"fixing, rest has an area of {rest_geom.area}")
            # add to boundaries_within
            tmp = self.boundaries_within.iloc[[0]].copy()
            tmp["name"] = "Restgebiet"
            for colname in ["id", "osm_id"]:
                if colname in tmp.columns:
                    tmp[colname] = None
            tmp["geometry"] = rest_geom

            self.boundaries_within = gpd.GeoDataFrame(
                    pd.concat([self.boundaries_within, tmp], ignore_index=True),
                    crs = self.boundaries_within.crs
            )
            self.boundaries_within.to_file(mdc.filename_boundaries_within)
        mdc.state = "boundaries_fixed"
        self._dump_meta()

    def add_use_classification(self):
        logging.debug("adding use classification")
        mdc = self.cache_meta.cities.get(self.name, None)
        if mdc is None:
            raise ValueError("frfr, why is there no cache at his point?")
        self.all_mp_within["georef_use_type"] = self.all_mp_within.apply(
                self.processor.classify_use, 
                axis=1
            )
        logging.debug(self.all_mp_within["georef_use_type"].value_counts(dropna=False))
        self.all_mp_within.to_file(mdc.filename_all_mp_within)
        mdc.state = "use_type_added"
        self._dump_meta()

    def compute_statistics(self):
        prio_list = self.processor.get_use_priority()
        use_type_unions = dict()
        self.all_mp_within["geometry"] = self.all_mp_within.geometry.make_valid()
        full_union = self.all_mp_within.geometry.union_all()
        full_area = full_union.area
        for prio in prio_list:
            part = self.all_mp_within[self.all_mp_within["georef_use_type"] == prio]
            if len(part) == 0:
                use_type_unions[prio] = None
            else:
                use_type_unions[prio] = part.geometry.union_all()

        diffed_areas = dict()
        higher_prio_union = None
        for prio in prio_list:
            geom = use_type_unions[prio]
            if geom is None:
                diffed_areas[prio] = None
                continue
            if higher_prio_union is None:
                diffed_areas[prio] = geom
                higher_prio_union = geom
            else:
                diffed_areas[prio] = geom.difference(higher_prio_union)
                higher_prio_union = higher_prio_union.union(geom)

        # compute statistics for each sub boundary
        def _get_area_dict(geom):
            ret = dict()
            # we use diffed_areas and priority from surrounding scope
            remaining = geom.area
            computed_total = 0
            for prio in prio_list:
                d_geom = diffed_areas[prio]
                if d_geom is None:
                    ret[prio] = 0.0
                    continue

                area = geom.intersection(d_geom).area
                ret[prio] = area
                computed_total += area
                remaining -= area
            null_area = max(0.0, remaining)
            if "null" in ret:
                ret["null"] += null_area
            else:
                ret["null"] = null_area
            ret["total_area"] = geom.area
            return ret

        main = _get_area_dict(full_union)
        main["name"] = f"all ({self.name})"
        stat_rows = [main]
        for i, row in self.boundaries_within.iterrows():
            sub_name = row["name"]
            sub_geom = row.geometry
            rec = _get_area_dict(sub_geom)
            rec["name"] = sub_name
            stat_rows.append(rec)
        stats_df = pd.DataFrame(stat_rows)
        for prio in prio_list:
            stats_df[f"{prio}_pct"] = (stats_df[prio] / stats_df["total_area"])*100.0
        stats_df = stats_df.round(2)
        stats_df.to_csv(f"{self.name}_stats_output.csv", index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('inputfile', metavar='input', type=str, 
                        help='set input')
    parser.add_argument('-n', '--no_cache', default=False, 
                        action="store_true",
                        help='ignore cache and force starting from scratch')
    
    args = parser.parse_args() # parses cmd-line args
    
    c = GeoStat(args.inputfile, ProcessorOSM())
    names_to_levels = c.fetch_boundaries_only()
    city_name = input("Stadtname (wie in OSM, case sensitive): ").strip()
    if city_name not in names_to_levels:
        e = rapidfuzz.process.extract(
                city_name, 
                names_to_levels.keys(), 
                scorer=rapidfuzz.fuzz.WRatio,
                limit=2
            )
        ql = [x[0] for x in e]
        print(f"unknown, maybe you meant one of these? {ql}")
        q= 'n'
        if e[0][1] > 80:
            q = input(f"continue with {e[0][0]}? [Y/n]")
        if q == 'n':
            logging.error("unknown city, please rerun")
            return 1
        logging.info(f'going with {e[0][0]}')
        city_name = e[0][0]

    cached_state = c.cache_get_state(city_name)
    #c._debug_print_layers()
    state_index = STATE_MAPPING.get(cached_state, 0)
    if args.no_cache:
        state_index = 0
    if state_index < 1:
        gdf = c.get_gdf()
        c.extract_city(city_name, gdf)
    else:
        c.load_cached_mp(city_name)
    if state_index < 2:
        c.fix_sub_boundaries()
    else:
        # we dont need an else because the data loaded already has the update
        logging.debug("skipping step 2")
    if state_index < 3:
        c.add_use_classification()
    else:
        # we dont need an else because the data loaded already has the update
        logging.debug("skipping step 3")
    if state_index < 4:
        c.compute_statistics()



if __name__ == '__main__':
	main()
