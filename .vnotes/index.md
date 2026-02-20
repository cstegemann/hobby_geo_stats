for the osm admin levels
https://wiki.openstreetmap.org/wiki/Tag:boundary%3Dadministrative#Country_specific_values_%E2%80%8B%E2%80%8Bof_the_key_admin_level=*


some quick notes on sqlite(3) in python for rapid gpkg inspection

get tables (layers):
"SELECT table_name, identifier FROM gpkg_contents"
Sample:
```
with sqlite3.connect(gpkgfilepath) as con:
    print(con.execute("SELECT table_name, identifier FROM gpkg_contents").fetchall())
```

Get columns for a layer (sqlite specific -> pragma)
"SELECT name FROM pragma_table_info('multipolygons')"

Next todo: make loading quicker via sqlite stuff