# Issue #238: headless CgPoints QA (2026-09-26)

Tested repository commit: `4d04727768a5341b06b62c1e3f7184baebbbed59`. This check covers only `envmon export-civil3d --landxml`.

Nine real terrain elevations were sampled from a local USGS 1 m 3DEP DEM downloaded through OpenTopography in the Billings, Montana area. ArcGIS Pro Python prepared the input by projecting DEM cell centers to EPSG:2256 and converting elevations from assumed meters to international feet (`z / 0.3048`). The CLI itself ran in ordinary workspace Python, where `importlib.util.find_spec('arcpy')` returned `None`.

```text
python -m autogis envmon export-civil3d --points <local-elevation-points.csv> --crs EPSG:2256 --out-dir <local-evidence-dir> --landxml --units foot
Exit code: 0
9 PNEZD point(s); projection note; LandXML CgPoints; Status: PASS
```

Stdlib XML parsing confirmed a well-formed LandXML 1.2 document with nine `CgPoint` elements, EPSG code 2256, `linearUnit="foot"`, `elevationUnit="feet"`, sequential point numbers, and coordinates/elevations matching the input and PNEZD CSV. It contains no TIN surface.

| Private evidence artifact | SHA256 |
|---|---|
| Input elevation-points CSV | `4E0C3935451691704171318F3C7F6D70B7C3A0329E189D3C0D0A5DED2D30D070` |
| PNEZD CSV | `2E9086FBBF309B4AB1CA5198A5B04156E507933DA8046BB5BD6ACAA547EDDA5E` |
| Projection note | `E5B6ED017C19EE0D0AC827EA96C20B93EF7A714381CBBC6A52BDB430D11F728B` |
| CgPoints LandXML | `851CDBE02B32C43E302B26E86639E65804D932703C342FE698EA478C13198229` |
| Run-history CSV | `F81A287CD9D45080E299C381E62D34024FA2B5E61F4889F01BB18D3B3EDD15C7` |

The detailed inputs and outputs are retained in a private task-specific TEMP evidence folder for owner QA. The source has no defined vertical CRS in this evidence, so the meter interpretation was not independently surveyed. This run did not validate LandXML against an XSD or import it into Civil 3D; those checks remain separate.
