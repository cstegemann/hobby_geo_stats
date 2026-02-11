
## Hobby project to dive into GIS with python
>This is a hobby project, the code is provided without any claims as to its safety or usefulness. I made this public on github simply as an addon to my CV ; )

This is a simple hobby project to extract data about a city from a gpkg and 
classify area use split by administrative sub-levels. It was tested on osm-data 
of a German federal state and will (so far) only work for similar types of data.


### Main learnings covered in this project
> Note that these learnings are not "covered" or described, but building this yourself may produce these learnings
 * Using qgis to check and inspect data
 * Getting and parsing data in python with geopandas
 * Different types of mapping data, e.g. OSM vs cadastral data 
 * Specific style of OSM data, layers
 * Impact of CRS, (broken) Geometries, overlaying objects
 * Classifications of types of use on mapped areas using hierarchies
 * being aware of double counting, some performance considerations
