#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
@author: christian

python version 3.12

'''

# =============================================================================
# Standard Python modules
# =============================================================================
import logging
from typing import Dict, Literal, override
# =============================================================================
# External Python modules
# =============================================================================
import numpy as np

# =============================================================================
# Extension modules
# =============================================================================

# =====================================
# script-wide declarations
# =====================================
logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.DEBUG)


def has_value(v) -> bool:
    """ helper to avoid different kinds of empty fields
    """
    if v is None:
        return False
    # pandas NA / numpy nan
    try:
        if np.isnan(v):
            return False
    except Exception:
        pass
    if isinstance(v, str) and v.strip().lower() in ["none", "null", ""]:
        return False
    return True

class AbstractProcessor:
    def get_all_admin_boundaries(self, gdf):
        raise NotImplementedError("overwrite in implementing class")

    def is_admin_level_subcity(self, gdf_row):
        raise NotImplementedError("overwrite in implementing class")

### OSM Processor plus some look ups
OSM_ECON_LANDUSE = {"industrial", "commercial", "retail", "construction", "farmyard"}
OSM_GREEN_LANDUSE = {"forest", "grass", "meadow", "recreation_ground", "village_green", "allotments", "farmland"}
OSM_GREEN_NATURAL = {"wood", "grassland", "heath", "scrub", "wetland"}
# leisure/tourism is usually "special_use", but parks are "green" instead.
OSM_GREEN_LEISURE = {"park", "garden", "nature_reserve"}

class ProcessorOSM(AbstractProcessor):
    @override
    def get_all_admin_boundaries(self, gdf):
        return gdf[
            (gdf.get("boundary")=="administrative") &
            (gdf.get("name").notna())
        ].copy()
    
    @override
    def is_admin_level_subcity(self, gdf):
        # super ugly hack for now with string comparison, whatever - osm data 
        # is clean I hope...
        return gdf['admin_level'].map(lambda x: str(x) == "10")

    @override
    def not_admin_boundary(self, gdf):
        return gdf["boundary"].map(lambda x: x!= "administrative")
   
    def get_use_priority(self):
        #residential fairly low because the areas in my test set are very big
        return [
                "special_use", 
                "economic", 
                "water", 
                "green", 
                "residential", 
                "building_only",
                "null"
        ]

    def classify_use(self, row) -> str:
        amenity = row.get("amenity", None)
        leisure = row.get("leisure", None)
        tourism = row.get("tourism", None)
        public_transport = row.get("public_transport", None)
        landuse = row.get("landuse", None)
        natural = row.get("natural", None)
        building = row.get("building", None)
        other_tags = row.get("other_tags", None)

        # special_use 
        if has_value(amenity) or has_value(public_transport) or has_value(tourism):
            return "special_use"

        if has_value(landuse) and landuse == "cemetery":
            return "special_use"

        if has_value(leisure):
            # park/garden/nature_reserve is "green", the rest special_use
            if str(leisure) in OSM_GREEN_LEISURE:
                return "green"
            return "special_use"

        # economic
        if has_value(landuse) and str(landuse) in OSM_ECON_LANDUSE:
            return "economic"

        # residential
        if has_value(landuse) and str(landuse) == "residential":
            return "residential"

        # green
        if has_value(natural) and str(natural) in OSM_GREEN_NATURAL:
            return "green"
        if has_value(landuse) and str(landuse) in OSM_GREEN_LANDUSE:
            return "green"

        # building_only
        if has_value(building):
            return "building_only"
       
        # water
        if (
                (has_value(other_tags) and "water" in other_tags) or 
                (has_value(natural) and natural=="water")
        ):
            return "water"

        # null 
        # in my test set, these where mostly highways, memorials, bare rocks
        # and benches
        #if row["boundary"]!= "administrative":
        #    print(row)
        return "null"


