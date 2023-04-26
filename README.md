<a href="http://chcrpa.org"><img src="https://chcrpa.org/wp-content/uploads/2017/01/chc-rpa-logo-1.png" title="Chattanooga-Hamilton County Regional Planning" alt="Chattanooga-Hamilton County Regional Planning"></a>


# <a name="pullen-census-data-tools"></a> Pullen Census Data Tools
This Python toolbox is designed to work within Esri ArcGIS Pro software to provide a pleasant user experience when extracting Census data, in particular the 5-year estimates from the American Community Survey (ACS).  The extracted data will either take the form of a stand alone table inside an existing file geodatabase or, if geometries were selected, as a feature class with the selected variables appended to the attribute table.  


# <a name="installation"></a>Installation
Save the toolbox (```.pyt```) and accompanying metadata files (```.xml```) to a location that can be accessed by ArcGIS Pro.  Within ArcGIS Pro, right-click on Toolboxes within the Catalog pane, then ```Add Toolbox```.  Navigate to the location where the toolbox has been saved and add it to the project.


# <a name="resources"></a>Resources
The following U.S. Census Bureau publication is an indispensible reference for American Community Survey data.  Chapter 8, <i>Calculating Measures of Error for Derived Estimates</i>, provides guidance on how to work with margins of error.

<a href="https://www.census.gov/programs-surveys/acs/library/handbooks/general.html">Understanding and Using American Community Survey Data: What All Data Users Need to Know</a>


# <a name="Command Line"></a>Command Line
The tool can be run from the Python Window of ArcGIS Pro with a little work.  An easy method for getting the correct syntax, including the toolbox import, is to fill out the tool interface and then, instead of clicking **Run**, click on the caron beside **Run** then **Copy Python Command**.

<img src="https://chcrpa.org/wp-content/uploads/2023/04/ACS5Yr-GUI.png" title="Pullen Census Data Tool ACS 5-Yr Example" alt="Alternate Text"></a>

Here is the result.  The user should modify the paths, variables, etc. to achieve the desired result.
```
arcpy.ImportToolbox(r"C:\User\<user>\Documents\ArcGIS\Projects\Demo\Demo.atbx")
arcpy.PullenCensusData.ACS5Yr(
    year=2021,
    state="[47] Tennessee (TN)",
    counties="'[065] Hamilton'",
    level="Tract",
    census_variables="'[B01001_002E] SEX BY AGE Male';'[B01001_026E] SEX BY AGE Female';'[B01003_001E] TOTAL POPULATION'",
    use_alias=True,
    null_records=None,
    margin_of_error=True,
    geometries=True,
    output=r"C:\Users\<user>\Documents\ArcGIS\Projects\Demo\Demo.gdb\TN_Hamilton_Tract_2021"
)
```

**NOTE:**  When using **Copy Python Command**, the tool import path may be to a ```.atbx``` file, typically within and having the same name as the project (```.aprx```) itself.  The qualified path to ```Pullen Census Data Tools.pyt``` may be substituted, however.

```arcpy.ImportToolbox(r"C:\Users\<user>\Documents\GitHub\pullen-census-data-tools\Pullen Census Data Tools.pyt")```

# <a name="known-issues"></a>Known Issues
- The tool is incompatible with ArcMap.
- The newest version of the tool currently only supports B Tables.


# <a name="team-members"></a>Team Members
Randolph Pullen (<rpullen@chattanooga.gov>)

Planning Analyst II, Research & Analysis

<a href="http://chcrpa.org">Chattanooga-Hamilton County Regional Planning Agency</a>


# <a name="installation"></a>License
- **[GPLv3 license](https://www.gnu.org/licenses/gpl-3.0.en.html)**
- Copyright 2022 © Randolph Pullen


# <a name="history"></a>History
- **2023-04-26** Included instructions on how to run the tool from the Python Window.
- **2023-04-24** Added the ability to select between tracts and block groups.  Working to limit the variables presented in the drop down to only those available for the selected geography.  Currently only supporting B tables.  Addressed code negatively impacted by ArcGIS Pro 3.1 tool deprecations.
- **2022-12-08** As the Census Bureau has now released 2021 data, that year is now an option in the year parameter drop down.
- **2022-11-09** Fixed issues with the tool behavior such that it will now work without being re-initialized or if called from the Geoprocessing History.  Modified the updateParamters method to address the issue of not all estimates being available across all years and to ensure that outputs are directed to an existing file geodatabase.  Modified the runtime messages to be more informative.  
- **2022-11-03** Fixed the fatal error resulting from a field alias exceeding 255 characters.  Added the option to use or not use descriptive field aliases.
