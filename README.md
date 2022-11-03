<a href="http://chcrpa.org"><img src="https://chcrpa.org/wp-content/uploads/2017/01/chc-rpa-logo-1.png" title="Chattanooga-Hamilton County Regional Planning" alt="Chattanooga-Hamilton County Regional Planning"></a>


# <a name="pullen-census-data-tools"></a> Pullen Census Data Tools
This Python toolbox is designed to work within Esri ArcGIS Pro software to provide a pleasant user experience when extracting Census data, in particular the 5-year estimates from the American Community Survey (ACS).  The extracted data will either take the form of a stand alone table inside an existing file geodatabase or, if geometries were selected, as a feature class with the selected variables appended to the attribute table.  


# <a name="installation"></a>Installation
Save the toolbox (```.pyt```) and accompanying metadata files (```.xml```) to a location that can be accessed by ArcGIS Pro.  Within ArcGIS Pro, right-click on Toolboxes within the Catalog pane, then ```Add Toolbox```.  Navigate to the location where the toolbox has been saved and add it to the project.


# <a name="team-members"></a>Team Members
Randolph Pullen (<rpullen@chattanooga.gov>)

Planning Analyst II, Research & Analysis

<a href="http://chcrpa.org">Chattanooga-Hamilton County Regional Planning Agency</a>


# <a name="installation"></a>License
- **[GPLv3 license](https://www.gnu.org/licenses/gpl-3.0.en.html)**
- Copyright 2022 © Randolph Pullen


# <a name="history"></a>History
- **2022-11-03** Fixed the fatal error resulting from a field alias exceeding 255 characters.  Added the option to use or not use descriptive field aliases.
