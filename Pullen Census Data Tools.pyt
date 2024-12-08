# -*- coding: utf-8 -*-
"""=============================================================================
   Code: Pullen Census Data Tools.pyt
 Author: Randy Pullen, Planning Analyst II (rpullen@chattanooga.gov)
         Chattanooga-Hamilton County Regional Planning Agency
         1250 Market St, Suite 2000
         Chattanooga, TN 37402
   Date: 2023-04-24
Version: ArcGIS Pro 3.1.1
         Python 3.9.16
  Level: GIS Professional Basic
================================================================================ 
Summary: This toolbox contains a tool for extracting up to 50 estimates from the
         U.S. Census Bureau American Community Survey (ACS) 5-year estimates.
         Within an existing file geodatabase, estimates and, if selected, mar-
         gins of errors are either written to a stand alone table or are perman-
         ently joined to an automated download of the appropriate geometries
         based upon user preferences.
--------------------------------------------------------------------------------         
  Notes: The tool can be implemented from the Python Window of ArcGIS Pro if the
         following steps are taken.  First, import the toolbox and then execute
         the tool with its parameters.
         > arcpy.ImportToolbox(<path to .pyt>)
         > arcpy.toolname_toolboxalias(params)
--------------------------------------------------------------------------------
Caveats: The toolbox is incompatible with ArcMap.

         Versions of ArcGIS Pro prior to 3.1 will crash if hyperlinks embedded
         in the help info boxes are clicked (Esri BUG-000151931).  In this case,
         users should utilize the hyperlinks only via the Catalog View.
--------------------------------------------------------------------------------
  Usage: Pullen Census Data Tools - A Geoprocessing Toolbox for Census Data
         Copyright (C) 2022  Randolph Pullen
         
         This program is free software: you can redistribute it and/or modify
         it under the terms of the GNU General Public License as published by
         the Free Software Foundation, either version 3 of the License, or
         (at your option) any later version.

         This program is distributed in the hope that it will be useful,
         but WITHOUT ANY WARRANTY; without even the implied warranty of
         MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
         GNU General Public License for more details.

         You should have received a copy of the GNU General Public License
         along with this program.  If not, see <https://www.gnu.org/licenses/>.
--------------------------------------------------------------------------------
History: 2023-06-13 Updated the code that populates to drop down menus for
         states and counties to accommodate changes made on the Census' website.

         2023-04-24 Added the ability to download Block Group data.  Due to the
         deprecation of some tools in ArcGIS Pro 3.1, some sections were re-
         done to be compatible with future releases of the software.  Attempted
         to restrict the drop down list of variables to only those availble for
         the selected geography.  Currently, only B tables are supported.  Re-
         worked the joining of the tabular data to the geography download such
         that lock files do not persist and the scratch folder may be deleted.
         Added new methods to make the code easier to read.

         2022-12-08 Added 2021 to the list of available years to select in the
         year parameter drop down as the Census has released data for this 
         year.

         2022-11-08 Fixed the inability of the tool to be called successfully
         from the Geoprocessing History by removing the lines setting the county
         & variable parameters to None in the updateParameters method.  Added
         new checks in the updateMessages method to control potential errors
         that might arise from not resetting the parameters.

         Added additional checks to the updateMessages method that ensures the
         output is being directed to a file geodatabase & that the geodatabase
         &/or feature dataset actually exists.

         Reworked the messages to be more informative.

         2022-11-03 Fixed the fatal error of a field alias exceeding 255 charac-
         ters and made field aliases an optional choice, True by default.
================================================================================
"""


import arcpy
import os
import pandas
import requests
import shutil
import lxml.html
from collections import Counter
from zipfile import ZipFile


class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = "Pullen Census Data"
        self.alias = "PullenCensusData"

        # List of tool classes associated with this toolbox
        self.tools = [ACS5Yr]


class ACS5Yr(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "5-Year ACS"
        self.description = ""
        self.canRunInBackground = False

        # Specify that tables that contain data for at the tract & block group
        # levels.
        self.specifyTables()

    def getParameterInfo(self):
        """Define parameter definitions"""
        global state_df
        
        # The year of interest.  The range must be updated whenever new data be-
        # comes available.
        param0 = arcpy.Parameter(
            displayName='Year',
            name='year',
            datatype='GPLong',
            parameterType='Required',
            direction='Input')
        param0.filter.type = 'ValueList'
        param0.filter.list = [i for i in range(2021, 2013, -1)]        

        # The state of interest.  In the user dialogue, the selections are pre-
        # sented as "[FIPS] Name (Postal Abbv.)," e.g., "[47] Tennessee (TN)."
        # States and FIPS are pulled dynamically from a Census website.
        param1 = arcpy.Parameter(
            displayName='State',
            name='state',
            datatype='GPString',
            parameterType='Required',
            direction='Input')
        state_name = self.stateNames()
        url = ('https://www2.census.gov/geo/docs/reference/codes2020/'
               'national_county2020.txt')
        state_df = pandas.read_csv(url, sep='|')
        cols = ['STATEFP', 'STATE']
        d = state_df[cols].groupby(cols).count().reset_index()
        d = d[d['STATE'].isin(state_name)]
        state_list = [['[{:02d}] {} ({})'.format(r['STATEFP'],
                                                 state_name[r['STATE']],
                                                 r['STATE'])]
                      for i, r in d.iterrows()]
        state_list.sort()
        param1.filter.type = 'ValueList'
        param1.filter.list = [i[0] for i in state_list]

        # The counties of interest.  County values are set dynamically based up-
        # on the selection of state.  See updateParameters().
        param2 = arcpy.Parameter(
            displayName='Counties',
            name='counties',
            datatype='GPValueTable',
            parameterType='Required',
            direction='Input')
        param2.columns = [['GPString', 'Name']]
        param2.filters[0].type = 'ValueList'
        
        # The Census level of aggregation of interest.  Currently, the only
        # available levels are tract & block group.
        param3 = arcpy.Parameter(
            displayName='Census Level',
            name='level',
            datatype='GPString',
            parameterType='Required',
            direction='Input')
        param3.filter.type = 'ValueList'
        param3.filter.list = ['Tract', 'Block Group']

        # The ACS variables of interest.  The variable list is set within the
        # updateParameters function so that if the year is changed, the list
        # will reset.
        param4 = arcpy.Parameter(
            displayName='Variables (select up to 50 variables)',
            name='census_variables',
            datatype='GPValueTable',
            parameterType='Required',
            direction='Input')
        param4.columns = [['GPString', 'Name']]
        param4.filters[0].type = 'ValueList'

        # Boolean to indicate if descriptive field alias should be used.
        param5 = arcpy.Parameter(
            displayName='Use descriptive field aliases.',
            name='use_alias',
            datatype='GPBoolean',
            parameterType='Optional',
            direction='Input')
        param5.value = True

        # Boolean to indicate whether variables for which all records are null
        # should be excluded from the final output.
        param6 = arcpy.Parameter(
            displayName='Drop variables where all records are null.',
            name='null_records',
            datatype='GPBoolean',
            parameterType='Optional',
            direction='Input')

        # Boolean to indicate whether the margin of errors should be downloaded
        # alongside the estimates of interest.
        param7 = arcpy.Parameter(
            displayName='Include margins of error (if available).',
            name='margin_of_error',
            datatype='GPBoolean',
            parameterType='Optional',
            direction='Input')

        # Boolean to indicate whether the tract geometries should be downloaded
        # alongside the variables of interest.
        param8 = arcpy.Parameter(
            displayName='Include geometries.',
            name='geometries',
            datatype='GPBoolean',
            parameterType='Optional',
            direction='Input')
        param8.value = True

        # The output name.  A file geodatabase must already exist in which
        # to create either the table or the feature class.
        param9 = arcpy.Parameter(
            displayName='Output (must be within a file geodatabase)',
            name='output',
            datatype=['DETable', 'DEFeatureClass'],
            parameterType='Required',
            direction='Output')

        params = [param0, param1, param2, param3, param4, param5, param6,
                  param7, param8, param9]
        return params

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""
        global all_counties

        # Determine the variables to display for selection once the year & geo-
        # graphy level have been selected.
        if parameters[0].altered and parameters[3].altered:
            self.setVariables(parameters)

        # Once a state selection is made, populate the county drop-down menu.
        # Add an option to include all counties within the state.
        if parameters[1].altered and not parameters[1].hasBeenValidated:
            abbv = parameters[1].valueAsText[-3:-1]
            fldA = 'COUNTYFP'
            fldB = 'COUNTYNAME'
            suf = ' County'
            cnty = [('[{:03d}] {}'.format(r[fldA], r[fldB].removesuffix(suf)))
                     for i, r in state_df.iterrows() if r['STATE'] == abbv]
            all_counties = set(['[*] All Counties'] + cnty)
            parameters[2].filters[0].list = sorted(all_counties)
        return 

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""
        global avail_moe
        
        # Raise an error if the selected counties don't match the county list
        # created from the state selection.
        if parameters[2].values:
            cnty = set([i[0] for i in parameters[2].values])
            # If the tool remains open after its first initialization & is exe-
            # cuted again, the circumstance may arise whereby the global vari-
            # able "all_counties" is not defined.  This try-except block will
            # correct that condition.  See updateParameters() for the primary
            # initialization of "all_counties".
            try:
                all_counties
            except:
                self.createCountyList(parameters)
            errors = sorted(cnty.difference(all_counties))
            if errors:
                state = ' '.join(parameters[1].value.split()[1:-1])
                msg = ('The selection contains counties not found within '
                       '{}:'.format(state))
                for item in errors:
                    msg += '\n{}'.format(item)
                parameters[2].setErrorMessage(msg)

        # Raise an error if there are duplicates in the county selection.
        if parameters[2].values and len(parameters[2].values) > 1:
            cnty = [i[0] for i in parameters[2].values]
            if len(cnty) > len(set(cnty)):
                msg = ('The selection should not contain duplicates.  The '
                       'following counties are duplicated one or more times:')
                counts = dict(Counter(cnty))
                dups = {k: v for k, v in counts.items() if v > 1}
                for k in sorted(dups):
                    msg += '\n{}'.format(k)
                parameters[2].setErrorMessage(msg)
                
        # Check that the variable selection is valid.
        if parameters[4].values and len(parameters[4].values) > 1:
            # Create a list of only the selected variable names.
            variables = [i[0][1:i[0].find(']')] for i in parameters[4].values]
            num_var = len(variables)
            
            # Create a set of the name component of the selected variables.
            sel_var = set(i[0][1:i[0].index(']')] for i in parameters[4].values)

            # Check if there is a difference between the names of the selected
            # variables & those that were determined using the year value.
            errors = sel_var.difference(all_var)
            if errors:
                desc = {i[0][1:i[0].index(']')]: i[0] for i in parameters[4].values}
                msg = ('The selection contains variables not available for '
                       '{}:'.format(parameters[0].value))
                for name in errors:
                    msg += '\n{}'.format(desc[name])
                parameters[4].setErrorMessage(msg)
            
            # Duplicates produce a data retrieval failure with Census servers.
            if num_var > len(set(variables)):
                msg = ('The selection should not contain duplicates.  The '
                       'following variables are duplicated one or more times:')
                counts = dict(Counter(variables))
                dups = {k: v for k, v in counts.items() if v > 1}
                for k in sorted(dups):
                    msg += '\n[{}] {}'.format(k, alias[k][0])
                parameters[4].setErrorMessage(msg)

            # The get command of the URL supports a maximum of 50 variables.
            if num_var > 50:
                msg = ('There are {:,d} variables selected.  The Census API '
                       'only allows for 50 variables.'.format(num_var))
                parameters[4].setErrorMessage(msg)

        # Requests for the margins of error cannot bring the total number of
        # variables above 50.  If no variables have been selected, then there's
        # no reason to perform the check.
        if parameters[7].value and parameters[4].values:
            # Create a list of only the selected variable names.
            variables = [i[0][1:i[0].find(']')] for i in parameters[4].values]
            num_var = len(variables)
            
            # MOE have the same name as estimate variables except they end
            # in 'M'.  Convert the variable names into potential MOE names.
            potential_moe = set(i[:-1] + 'M' for i in variables)
            
            # Intersect a set of potential MOE names with the set of all
            # published MOE variable names to determine which MOE are avail-
            # able.  Not all estimate variables have MOE uniformly across
            # all years, so membership must always be checked.
            avail_moe = all_moe.intersection(potential_moe)
            num_moe = len(avail_moe)
            total = num_var + num_moe
            if total > 50:
                msg = ('There are {:,d} variables selected ({:,d} '
                       'estimates + {:,d} margins of error), exceeding the '
                       '50 variable limit imposed by the Census '
                       'API.'.format(total, num_var, num_moe))
                parameters[4].setErrorMessage(msg)            

        # Ensure that the output is going to a file geodatabase & that the file
        # geodatabase &, optionally, feature dataset both exists.
        if parameters[9].value:
            msg = ''
            path = arcpy.Describe(parameters[9].value).path
            if path.rfind('.gdb') == -1:
                msg = 'Output must be to a file geodatabase.'
            else:
                gdb = path[:path.index('.gdb') + 4]
                if not arcpy.Exists(gdb):
                    msg = 'Output file geodatabase not found.'
                elif not arcpy.Exists(path):
                    msg = 'Output feature dataset not found.'
            if msg:
                parameters[9].setErrorMessage(msg)
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # During the tool execution, informative information is added to the
        # tool's messages.  Here, the year is added.
        year = parameters[0].value
        arcpy.AddMessage('Year: {}'.format(year))

        # Add the state FIPS & state name to the tool messages.
        v = parameters[1].value
        state_fips = v[1:3]
        state_name = ' '.join(v.split()[1:-1])
        arcpy.AddMessage('State: {} {}'.format(state_fips, state_name))

        # Add the counties to the tool messages.
        counties = [i[0].split()[0][1:-1] for i in parameters[2].values]
        if '*' in counties:
            counties = ['*']
            msg = 'Counties: *'
        else:
            desc_counties = [i[0] for i in parameters[2].values]
            desc_counties.sort()
            desc_counties = [i[1:i.index(']')] + ' ' + i[i.index(']') + 2:] for
                             i in desc_counties]
            msg = 'Counties: {}'.format(desc_counties[0])
            for county in desc_counties[1:]:
                msg += '\n{:>10}{}'.format(' ', county)
        arcpy.AddMessage(msg)

        # Obtain a list of the variable names, not descriptive names, selected
        # by the user to use in the construction of the data retrieval URL.  Add
        # to the list the available margins of error, if selected.  For how the
        # available MOE are determined, see updateMessages().
        variables = [i[0][1:i[0].find(']')] for i in parameters[4].values]
        if parameters[7].value:
            variables = sorted(set(variables).union(avail_moe))

        # Once all variables have been identified, construct a URL that will
        # fetch the raw data from the Census Bureau.
        level = parameters[3].value
        url = self.createDataURL(level, year, variables, state_fips, counties)
       
        # Add to the tool messages the variables and their descriptive names.
        msg = 'Variable\tDescription'
        for var in variables:
            if var.endswith('E'):
                msg += '\n{}\t{}'.format(var, alias[var][0])
            elif var.endswith('M'):
                k = var[:-1] + 'E'
                msg += '\n{}\t{}'.format(var, alias[k][1])
            else:
                msg += '\n{}\tUNDEFINED'.format(var)
        arcpy.AddMessage(msg)

        # Create a Pandas data frame that is cleaned up & ready for conversion.
        df = self.createDataFrame(parameters, url, variables)

        # Analyze each variable chosen by the user.  If selected, remove vari-
        # ables that only contain null records.  Determine the approriate data
        # type of each variable.
        dic_dtypes, df = self.analyzeVariables(parameters, df)

        # Convert the Pandas data frame to a NumPy array using data type defini-
        # tions.
        dts = {'names': dic_dtypes['names'], 'formats': dic_dtypes['formats']}
        arr = numpy.core.records.fromarrays(df.to_numpy().transpose(),
                                            dtype=dts)

        # Sort the array based upon GEOID.
        arr = arr[arr['GEOID'].argsort()]

        # If geometries are not desired, the output will be a table using the
        # parameter value.  If geometeries were selected, then the table name
        # will be a temporary name and the output feature class will be named
        # the parameter value.  In theory, the table name should be unique when
        # created using CreateScratchName.  In practice, this is not always the
        # case, so an attempt is made to delete any existing table with the
        # same name as the output.
        ws = parameters[9].valueAsText
        ws = ws[:ws.rfind('.gdb') + 4]
        if parameters[8].value:
            prefix = 'xxxCensusAPITable_'
            tbl = arcpy.CreateUniqueName(prefix, ws)
        else:
            tbl = os.path.join(ws, parameters[9].valueAsText)
        if arcpy.Exists(tbl):
            arcpy.management.Delete(tbl)

        # Convert the NumPy array into a stand alone table.
        arcpy.da.NumPyArrayToTable(arr, tbl)

        # If the output is a table, then the script will terminate.  Before ter-
        # minating the script, check & change the field aliases as selected.
        if not parameters[8].value:
            if parameters[5].value:
                self.changeFieldAliases(tbl)         
            arcpy.AddMessage('Table: {}'.format(tbl))            
            return

        # Create the url to download the shapefile zip archive.
        url = self.createShpURL(parameters, year, state_name, state_fips)

        # Create a scratch workspace directory inside the folder containting the
        # file geodatabase specified by the user.
        root = ws[:ws.rfind(os.sep)]
        scratch = arcpy.CreateScratchName('xxxCensusAPI', '', 'Folder', root)
        os.mkdir(scratch)

        # Isolate the name of the zip archive, e.g., cb_2020_47_tract_500k.zip,
        # which will also be the name of the shapefile within, & fully qualify
        # the zip archive file and scratch directory.
        zip_archive = url[url.rfind('/') + 1:]
        zip_archive = os.path.join(scratch, zip_archive)

        # Download the zip archive containing the shapefile of geometries.
        r = requests.get(url, stream=True)
        size = 16 * 1024
        with open(zip_archive, 'wb') as f:
            for chunk in r.iter_content(chunk_size=size):
                f.write(chunk)

        # Extract the shapefile from the zip archive in the scratch directory.
        ZipFile(zip_archive, 'r').extractall(scratch)
        shp = zip_archive.replace('.zip', '.shp')

        # Create two temporary feature classes.  Delete any existing feature
        # class that  may already have that name.
        xxxfc00 = arcpy.CreateScratchName('xxxCensusAPIFC00_', '',
                                          'FeatureClass', ws)
        xxxfc01 = arcpy.CreateScratchName('xxxCensusAPIFC01_', '',
                                          'FeatureClass', ws)       
        for fc in [xxxfc00, xxxfc01]:
            if arcpy.Exists(fc):
                arcpy.management.Delete(fc)
                
        # Export the shapefile as a temporary feature class in the file geodata-
        # base.  This is done before making the join as joining to the shape-
        # file creates a lock file that is not removed after deleting the
        # temporary feature class & results in an inability to delete the
        # scratch directory.
        arcpy.conversion.ExportFeatures(shp, xxxfc00, '', 'NOT_USE_ALIAS')

        # Delete the the scratch directory containing the zip archive & shape-
        # file.
        shutil.rmtree(scratch, ignore_errors=True)

        # Create an in-memory layer of the geometries to use in making the join
        # to the stand alone table of the tabular Census data.  Create a query
        # that restricts the layer to only those counties of interest.
        lyr = 'CensusAPIJoin'
        if counties != ['*']:
            qry = "COUNTYFP IN ('{}')".format("', '".join(i for i in counties))
        else:
            qry = None
        arcpy.management.MakeFeatureLayer(xxxfc00, lyr, qry)

        # Join the stand alone table created from the Census data to the feature
        # class of the Census geometries.
        join_fc = arcpy.management.AddJoin(lyr, 'GEOID', tbl, 'GEOID',
                                           'KEEP_ALL', 'INDEX_JOIN_FIELDS')

        # Make the join permanent by exporting the feature class.
        arcpy.conversion.ExportFeatures(join_fc, xxxfc01, '', 'NOT_USE_ALIAS')

        # Delete the join inputs
        arcpy.management.Delete(xxxfc00)
        arcpy.management.Delete(tbl)

        # Remove unnecesary fields by exporting again & using a field mapping
        # to restrict the output fields.
        output = parameters[9].valueAsText        
        fieldmapping = arcpy.FieldMappings()
        fieldmapping.addTable(xxxfc01)
        for i in range(fieldmapping.fieldCount - 1, -1, -1):
            field = fieldmapping.fields[i].name
            if field == 'OBJECTID' or field.endswith('_1'):
                fieldmapping.removeFieldMap(i)
        arcpy.conversion.ExportFeatures(xxxfc01, output, '', 'NOT_USE_ALIAS',
                                        fieldmapping, 'GEOID ASCENDING')

        # Delete the temporary feature class.
        arcpy.management.Delete(xxxfc01)

        # Alter the field aliases if selected.
        if parameters[5].value:
            self.changeFieldAliases(output)
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""
        return
    
    def stateNames(self):
        name = {'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona',
                'AR': 'Arkansas', 'CA': 'California', 'CO': 'Colorado',
                'CT': 'Connecticut', 'DE': 'Delaware',
                'DC': 'District of Columbia', 'FL': 'Florida', 'GA': 'Georgia',
                'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois',
                'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas', 'KY': 'Kentucky',
                'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
                'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota',
                'MS': 'Mississippi', 'MO': 'Missouri', 'MT': 'Montana',
                'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire',
                'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
                'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
                'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania',
                'RI': 'Rhode Island', 'SC': 'South Carolina',
                'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas',
                'UT': 'Utah', 'VT': 'Vermont', 'VA': 'Virginia',
                'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin',
                'WY': 'Wyoming'}
        return name

    def specifyTables(self):
        """Define the tables that contain all variables for the tract and block
        group geography levels."""
        
        global tract_tbls
        global blkgp_tbls

        # The 2021-2019 "B" tables available at the tract level.  This
        # list of 2021 "B" tables was compared to 2020 & 2019 "B" tables & found
        # to be identical.
        tract_tbls = {'B992701', 'B14007F', 'B15011', 'B11002F', 'B20001',
                      'B19113C', 'B19101D', 'B25032', 'B10051D', 'B25061',
                      'B99181', 'B25048', 'B25035', 'B17017', 'B22005A',
                      'B10063', 'B25067', 'B19080', 'B25074', 'B12002G',
                      'B07012', 'B08303', 'B17010I', 'B25133', 'B25021',
                      'B01002H', 'B10056', 'B25051', 'B17019', 'B99183',
                      'B25043', 'B19062', 'B29003', 'B19037I', 'B01001B',
                      'B99163', 'B19202A', 'B17020', 'B17013', 'B25045',
                      'B11001F', 'B11012', 'B25122', 'B20005F', 'B24041',
                      'B24090', 'B12002C', 'B19313G', 'B99051', 'B19301I',
                      'B11008', 'B08130', 'B28004', 'B28006', 'B25070',
                      'B11002A', 'B17020G', 'B19301G', 'B07004B', 'B99092',
                      'B99281', 'B19081', 'B15003', 'B25100', 'B99072',
                      'B01002I', 'B25037', 'B17001A', 'B01002F', 'B992518',
                      'B06004C', 'B19101F', 'B25004', 'B25057', 'B11002D',
                      'B99253', 'B25065', 'B16003', 'B08017', 'B10010',
                      'B25079', 'B01002C', 'B10051C', 'B25014', 'B01001C',
                      'B25113', 'B25078', 'B20017A', 'B16008', 'B20017H',
                      'B99245', 'B05003H', 'B992511', 'B18104', 'B08201',
                      'B19013G', 'B12006', 'B25053', 'B13014', 'B08011',
                      'B08113', 'B13012', 'B19313F', 'B25105', 'B992523',
                      'B19301', 'B99084', 'B99123', 'B13002G', 'B992708',
                      'B25015', 'B11001A', 'B19101H', 'B27011', 'B22010',
                      'B25014F', 'B10051E', 'B99232', 'B08105I', 'B23024',
                      'B25082', 'B08016', 'B25134', 'B07008', 'B16005H',
                      'B17010A', 'B25040', 'B992706', 'B19001I', 'B25009',
                      'B25104', 'B19313H', 'B12002E', 'B19301A', 'B16004',
                      'B02014', 'B19101I', 'B05003A', 'B19113I', 'B99162',
                      'B99246', 'B19058', 'B06001', 'B17020D', 'B05011',
                      'B22005C', 'B08008', 'B12002I', 'B24031', 'B21100',
                      'B18135', 'B14001', 'B13002B', 'B17010H', 'B23003',
                      'B12002F', 'B25119', 'B09001', 'B25086', 'B25114',
                      'B25135', 'B23013', 'B99085', 'B25003E', 'B10051A',
                      'B19313B', 'B25115', 'B25003B', 'B25094', 'B992516',
                      'B19101B', 'B17016', 'B28007', 'B19313A', 'B12002B',
                      'B18102', 'B25032F', 'B09018', 'B99184', 'B25014E',
                      'B992521', 'B06004H', 'B01001F', 'B08007', 'B25003D',
                      'B17024', 'B25111', 'B26001', 'B99132', 'B17010B',
                      'B992709', 'B01001G', 'B08105G', 'B19202D', 'B19037D',
                      'B25098', 'B06004E', 'B25123', 'B25076', 'B19069',
                      'B10051B', 'B99259', 'B99252', 'B27022', 'B22005F',
                      'B99104', 'B19119', 'B29002', 'B20017F', 'B29004',
                      'B99212', 'B25013', 'B28009C', 'B08105B', 'B992515',
                      'B14007I', 'B13002E', 'B08131', 'B24082', 'B17008',
                      'B20017C', 'B24012', 'B08121', 'B20005', 'B25003G',
                      'B16005D', 'B19113F', 'B25054', 'B25011', 'B19037G',
                      'B02013', 'B25128', 'B25003I', 'B25044', 'B05006',
                      'B18101', 'B28009D', 'B25019', 'B17101', 'B18101F',
                      'B01002G', 'B13002F', 'B16005E', 'B19202H', 'B19001H',
                      'B25008', 'B11013', 'B25072', 'B12002A', 'B18101C',
                      'B02012', 'B99254', 'B09021', 'B06004D', 'B08134',
                      'B19013D', 'B27023', 'B16005A', 'B27010', 'B19202E',
                      'B18101H', 'B19037E', 'B10058', 'B25058', 'B23018',
                      'B25034', 'B08126', 'B25101', 'B05003', 'B25050',
                      'B25036', 'B19001D', 'B25124', 'B11002C', 'B05010',
                      'B99282', 'B21004', 'B99102', 'B05001', 'B08132',
                      'B16005B', 'B25018', 'B22001', 'B20017E', 'B19055',
                      'B05013', 'B11001E', 'B08141', 'B14007C', 'B19202F',
                      'B19123', 'B10051I', 'B08103', 'B25068', 'B99187',
                      'B01002', 'B19313I', 'B14007A', 'B05003B', 'B06009',
                      'B03001', 'B08009', 'B13002A', 'B19113H', 'B25071',
                      'B25089', 'B99194', 'B08111', 'B10051G', 'B16005C',
                      'B10053', 'B19301F', 'B07004A', 'B06010', 'B17010C',
                      'B99071', 'B99125', 'B25063', 'B99124', 'B16009',
                      'B99172', 'B25087', 'B23026', 'B25112', 'B19313D',
                      'B13002C', 'B25022', 'B25075', 'B27003', 'B19202G',
                      'B25032I', 'B19121', 'B20003', 'B19050', 'B17026',
                      'B02009', 'B02011', 'B19001B', 'B17022', 'B01001H',
                      'B992512', 'B19001A', 'B08135', 'B19037H', 'B99061',
                      'B15002', 'B02010', 'B17001F', 'B25093', 'B20017D',
                      'B25132', 'B17020E', 'B25020', 'B17001H', 'B11001',
                      'B25052', 'B11010', 'B20004', 'B07004H', 'B25003A',
                      'B05004', 'B19325', 'B11001G', 'B19001E', 'B25032E',
                      'B14007G', 'B23022', 'B19037F', 'B17001B', 'B19052',
                      'B14007', 'B99161', 'B25032G', 'B05003I', 'B25041',
                      'B25047', 'B20005D', 'B05014', 'B25085', 'B99256',
                      'B06011', 'B11003', 'B19082', 'B19202B', 'B99141',
                      'B08105E', 'B19001', 'B27001', 'B19001F', 'B17010E',
                      'B28008', 'B28009B', 'B99233', 'B02008', 'B08133',
                      'B20005A', 'B20017G', 'B99031', 'B16005', 'B22005B',
                      'B10050', 'B25125', 'B05003C', 'B05005', 'B06004B',
                      'B02019', 'B17020A', 'B99255', 'B05007', 'B06004I',
                      'B99012', 'B99053', 'B17001D', 'B07009', 'B27020',
                      'B07004F', 'B25024', 'B10051', 'B25039', 'B22002',
                      'B25120', 'B28010', 'B24081', 'B25077', 'B11001H',
                      'B25001', 'B25117', 'B13002D', 'B11002G', 'B99052',
                      'B19301E', 'B24022', 'B992519', 'B22005G', 'B28012',
                      'B08105C', 'B10057', 'B19013I', 'B25081', 'B10059',
                      'B12002H', 'B17011', 'B09002', 'B08136', 'B17010',
                      'B08006', 'B19127', 'B25088', 'B19051', 'B12002D',
                      'B16007', 'B19301H', 'B19129', 'B28009F', 'B19083',
                      'B25017', 'B25046', 'B99234', 'B25064', 'B20017I',
                      'B25005', 'B13010', 'B19013', 'B99231', 'B18101A',
                      'B99131', 'B99171', 'B99257', 'B17020F', 'B09020',
                      'B99011', 'B06004F', 'B17001', 'B19131', 'B21001',
                      'B05008', 'B07004D', 'B01002B', 'B19128', 'B11001B',
                      'B25127', 'B25003C', 'B99185', 'B06012', 'B19130',
                      'B25062', 'B06004G', 'B09019', 'B19059', 'B25056',
                      'B07001', 'B28003', 'B19070', 'B07004G', 'B25102',
                      'B08015', 'B08122', 'B02018', 'B17007', 'B11002H',
                      'B25006', 'B992707', 'B25066', 'B19013C', 'B19064',
                      'B17020C', 'B08013', 'B05003G', 'B28011', 'B09010',
                      'B19025C', 'B17012', 'B18106', 'B07011', 'B11002',
                      'B19065', 'B19049', 'B01002A', 'B25129', 'B17001E',
                      'B10001', 'B25032D', 'B07201', 'B11001D', 'B25016',
                      'B25049', 'B25095', 'B13002H', 'B17001G', 'B22007',
                      'B99122', 'B17020H', 'B11002B', 'B24021', 'B99021',
                      'B14004', 'B11004', 'B16005I', 'B19215', 'B19113E',
                      'B19301B', 'B25031', 'B19037A', 'B08301', 'B16006',
                      'B99244', 'B17021', 'B23027', 'B25010', 'B19301D',
                      'B25069', 'B25096', 'B25014C', 'B18140', 'B11014',
                      'B19001G', 'B25032C', 'B25032H', 'B23001', 'B14003',
                      'B24091', 'B19214', 'B99126', 'B18101D', 'B19067',
                      'B992520', 'B19313C', 'B99083', 'B20005B', 'B08014',
                      'B25110', 'B01002D', 'B19025', 'B99243', 'B10054',
                      'B11015', 'B08302', 'B08105A', 'B25007', 'B25003F',
                      'B17001C', 'B99221', 'B99182', 'B07004E', 'B25014A',
                      'B11002E', 'B14007H', 'B23006', 'B99242', 'B13015',
                      'B19122', 'B21005', 'B28002', 'B02015', 'B20005C',
                      'B16005G', 'B25108', 'B25106', 'B99142', 'B17015',
                      'B17005', 'B17010D', 'B19025H', 'B01001I', 'B07003',
                      'B06002', 'B12002', 'B18101E', 'B19013E', 'B02001',
                      'B11011', 'B25060', 'B25116', 'B19101A', 'B99191',
                      'B19057', 'B19101G', 'B19113D', 'B19001C', 'B24042',
                      'B28009G', 'B08105H', 'B20005G', 'B992703', 'B99283',
                      'B24092', 'B19113', 'B28009H', 'B13002I', 'B04007',
                      'B25090', 'B17003', 'B19313', 'B08119', 'B25097',
                      'B19060', 'B25107', 'B19313E', 'B17018', 'B18101B',
                      'B25027', 'B27015', 'B25014D', 'B17010G', 'B07013',
                      'B05003E', 'B08128', 'B07204', 'B17009', 'B06003',
                      'B19037', 'B24011', 'B19113G', 'B01001A', 'B19025A',
                      'B19101', 'B19037C', 'B22005D', 'B25118', 'B15001',
                      'B19037B', 'B10051H', 'B04004', 'B17010F', 'B11001C',
                      'B11016', 'B992514', 'B11001I', 'B17001I', 'B08137',
                      'B05003F', 'B22005I', 'B992513', 'B14002', 'B19066',
                      'B14007D', 'B20017B', 'B992522', 'B14007E', 'B19202C',
                      'B11006', 'B17020B', 'B19019', 'B19013H', 'B25059',
                      'B25083', 'B07004C', 'B18105', 'B20002', 'B01001',
                      'B09005', 'B05002', 'B23025', 'B25032A', 'B99258',
                      'B20005E', 'B25002', 'B11002I', 'B25080', 'B02017',
                      'B08124', 'B28001', 'B13016', 'B05003D', 'B05015',
                      'B19013A', 'B19202I', 'B19216', 'B19101C', 'B25014G',
                      'B99241', 'B01001D', 'B08202', 'B20005I', 'B25121',
                      'B13002', 'B04006', 'B19053', 'B08018', 'B19013F',
                      'B20017', 'B24032', 'B21002', 'B19054', 'B07203',
                      'B06004A', 'B18101I', 'B03003', 'B19013B', 'B25126',
                      'B19025F', 'B19063', 'B07007', 'B17020I', 'B28009I',
                      'B28005', 'B25042', 'B99201', 'B25014H', 'B12001',
                      'B19126', 'B17023', 'B29001', 'B22008', 'B99081',
                      'B99193', 'B22005E', 'B01001E', 'B992702', 'B16010',
                      'B19056', 'B23010', 'B20005H', 'B02016', 'B22003',
                      'B15012', 'B99082', 'B08105F', 'B17004', 'B25014I',
                      'B28009A', 'B28009E', 'B19125', 'B16005F', 'B99121',
                      'B19113A', 'B25033', 'B23020', 'B07010', 'B25003',
                      'B992704', 'B25109', 'B11005', 'B19101E', 'B24080',
                      'B25012', 'B25091', 'B19025E', 'B03002', 'B992705',
                      'B14006', 'B19326', 'B99186', 'B27002', 'B10002',
                      'B19301C', 'B23007', 'B99211', 'B23009', 'B05012',
                      'B18107', 'B99151', 'B19025B', 'B992510', 'B08101',
                      'B17025', 'B05009', 'B19061', 'B99192', 'B07202',
                      'B99103', 'B08105D', 'B25092', 'B13004', 'B25032B',
                      'B14007B', 'B01002E', 'B18101G', 'B17014', 'B27019',
                      'B10051F', 'B14005', 'B25038', 'B07004I', 'B23008',
                      'B25014B', 'B11007', 'B25003H', 'B10052', 'B22005H',
                      'B25099', 'B07002', 'B01003', 'B19025G', 'B99080',
                      'B19025D', 'B17006', 'B06007', 'B25055', 'B06008',
                      'B18103', 'B19025I', 'B19113B', 'B21003', 'B25026',
                      'B19202', 'B04005', 'B20018', 'B19201', 'B99152',
                      'B08012', 'B08203', 'B13008', 'B25103'}

        # The 2018-2015 "B" tables available at the tract level that are not
        # listed in the 2021-2019 "B" tables.
        tbls_2018 = {'B00001', 'B00002', 'B09008'}

        # The 2014 "B" tables available at the tract level that are not listed
        # in the 2021-2019 "B" tables nor the 2018-1015 "B" tables.
        tbls_2014 = {'B02005', 'B02006', 'B02007', 'B10060', 'B10061', 'B12005',
                     'B13001', 'B19113', 'B20005G'}

        # Update the tract tables to contain all "B" tables across all years.
        tract_tbls.update(tbls_2018, tbls_2014)

        # The 2021-2019 "B" tables available at the block group level.  This
        # list of 2021 "B" tables was compared to 2020 & 2019 "B" tables & found
        # to be identical.  The code above  was used to isolate the "B" tables
        # from all other data products.  Trial & error was used to identify
        # which restrictions produced the correct results.
        blkgp_tbls = {'B14007F', 'B15011', 'B11002F', 'B20001', 'B25032',
                      'B25061', 'B25035', 'B17017', 'B25067', 'B25074',
                      'B08303', 'B25021', 'B01002H', 'B25051', 'B25043',
                      'B19062', 'B29003', 'B99163', 'B25045', 'B11001F',
                      'B11012', 'B19313G', 'B99051', 'B19301I', 'B11008',
                      'B28006', 'B28004', 'B25070', 'B11002A', 'B19301G',
                      'B99281', 'B99092', 'B99072', 'B15003', 'B01002I',
                      'B25037', 'B01002F', 'B992518', 'B25004', 'B25057',
                      'B11002D', 'B99253', 'B25065', 'B08017', 'B25079',
                      'B01002C', 'B25014', 'B25078', 'B992511', 'B25053',
                      'B19313F', 'B19301', 'B99084', 'B25015', 'B11001A',
                      'B22010', 'B99232', 'B23024', 'B25082', 'B08016',
                      'B25040', 'B25009', 'B19313H', 'B99162', 'B19301A',
                      'B16004', 'B19058', 'B08008', 'B23003', 'B25086',
                      'B25003E', 'B19313B', 'B25003B', 'B992516', 'B28007',
                      'B19313A', 'B09018', 'B992521', 'B25003D', 'B08007',
                      'B25076', 'B19069', 'B99259', 'B99252', 'B99104',
                      'B29002', 'B29004', 'B99212', 'B28009C', 'B992515',
                      'B14007I', 'B25003G', 'B25054', 'B02013', 'B25003I',
                      'B25044', 'B28009D', 'B25019', 'B17101', 'B25008',
                      'B01002G', 'B25072', 'B02012', 'B99254', 'B09021',
                      'B08134', 'B27010', 'B25058', 'B25034', 'B25050',
                      'B25036', 'B11002C', 'B99282', 'B99102', 'B25018',
                      'B19055', 'B11001E', 'B14007C', 'B25068', 'B19123',
                      'B01002', 'B19313I', 'B14007A', 'B25089', 'B08009',
                      'B25071', 'B99194', 'B19301F', 'B99071', 'B25063',
                      'B99172', 'B25087', 'B23026', 'B19313D', 'B25022',
                      'B25075', 'B20003', 'B19050', 'B02009', 'B02011',
                      'B992512', 'B08135', 'B99061', 'B15002', 'B02010',
                      'B25093', 'B25020', 'B11001', 'B25003A', 'B11001G',
                      'B14007G', 'B23022', 'B19052', 'B14007', 'B99161',
                      'B25041', 'B25047', 'B25085', 'B99256', 'B11003',
                      'B99141', 'B19001', 'B28008', 'B28009B', 'B99233',
                      'B02008', 'B99031', 'B99255', 'B99012', 'B99053',
                      'B25024', 'B25039', 'B28010', 'B25077', 'B25001',
                      'B11001H', 'B11002G', 'B99052', 'B19301E', 'B992519',
                      'B28012', 'B25081', 'B17011', 'B09002', 'B08136',
                      'B17010', 'B19127', 'B25088', 'B19051', 'B19301H',
                      'B28009F', 'B25017', 'B25046', 'B99234', 'B25064',
                      'B19013', 'B99231', 'B99171', 'B99257', 'B09020',
                      'B99011', 'B21001', 'B01002B', 'B11001B', 'B25003C',
                      'B25062', 'B09019', 'B19059', 'B25056', 'B28003',
                      'B19070', 'B11002H', 'B25006', 'B25066', 'B19064',
                      'B28011', 'B19025C', 'B11002', 'B19065', 'B19049',
                      'B01002A', 'B07201', 'B11001D', 'B25016', 'B25049',
                      'B11002B', 'B99021', 'B11004', 'B19301B', 'B08301',
                      'B17021', 'B23027', 'B25010', 'B19301D', 'B25069',
                      'B19214', 'B19067', 'B992520', 'B19313C', 'B99083',
                      'B99243', 'B01002D', 'B19025', 'B11015', 'B08302',
                      'B25007', 'B25003F', 'B11002E', 'B14007H', 'B99242',
                      'B28002', 'B99142', 'B19025H', 'B02001', 'B25060',
                      'B99191', 'B19057', 'B28009G', 'B99283', 'B28009H',
                      'B19113', 'B19313', 'B19060', 'B19313E', 'B19037',
                      'B19025A', 'B19101', 'B11001C', 'B11016', 'B992514',
                      'B11001I', 'B992513', 'B14002', 'B19066', 'B14007D',
                      'B992522', 'B14007E', 'B25083', 'B11006', 'B25059',
                      'B20002', 'B01001', 'B23025', 'B99258', 'B25002',
                      'B11002I', 'B25080', 'B28001', 'B99241', 'B19053',
                      'B08018', 'B20017', 'B21002', 'B19054', 'B07203',
                      'B03003', 'B19025F', 'B19063', 'B28009I', 'B28005',
                      'B25042', 'B99201', 'B12001', 'B29001', 'B99081',
                      'B99193', 'B19056', 'B15012', 'B99082', 'B28009E',
                      'B28009A', 'B99121', 'B25033', 'B25003', 'B11005',
                      'B24080', 'B25091', 'B19025E', 'B03002', 'B19301C',
                      'B23007', 'B99211', 'B23009', 'B99151', 'B19025B',
                      'B992510', 'B19061', 'B99192', 'B07202', 'B99103',
                      'B25092', 'B14007B', 'B01002E', 'B14005', 'B25038',
                      'B23008', 'B11007', 'B25003H', 'B19025G', 'B01003',
                      'B99080', 'B19025D', 'B25055', 'B19025I', 'B19202',
                      'B99152', 'B19201'}

        # The 2018-2015 "B" tables available at the block group level that are
        # not listed in the 2021-2019 "B" tables.
        blkgp_2018 = {'B00001', 'B00002'}

        # The 2014 "B" tables available at the block group level that are not
        # listed in the 2021-2019 "B" tables nor the 2018-1015 "B" tables.
        blkgp_2014 = {'B19113'}

        # Update the block group tables to contain all "B" tables across all
        # years.  This is still acceptable as a filter because the tables only
        # available for certain years will not be in the list of variables for
        # other years, e.g., the list of 2021 variables will not contain B19113.
        blkgp_tbls.update(blkgp_2018, blkgp_2014)
        return
    
    def setVariables(self, parameters):
        """Return the list of variables available for that geography level."""
        global all_var
        global all_moe
        global alias

        # Read the webpage defining the variables for the selected year.
        url = ('https://api.census.gov/data/{}/acs/acs5/'
               'variables.html'.format(parameters[0].value))
        page = requests.get(url)
        doc = lxml.html.fromstring(page.content)
        tr_elements = doc.xpath('//tr')

        # Using the webpage elements, isolate& format the variable name & its
        # description.  Ensure that each description is 255 characters or less.
        # Determine the correct formating for the margins of errors (MOE), too.
        variables = []
        all_var = set()
        all_moe = set()
        alias = {}
        for j in range(2, len(tr_elements)):
            T = tr_elements[j]
            if len(T) != 8 or T[6].text_content() != 'int':
                continue
            name = T[0].text_content()
            label = ' '.join(T[1].text_content().split('!!')[2:])
            label = label.replace(':', '')
            concept = T[2].text_content().replace(':', '')
            tmp = '{} {}'.format(concept, label)
            if len(tmp) <= 255:
                alt = tmp
                if len('MOE {}'.format(alt)) <= 255:
                    alt_moe = 'MOE {}'.format(alt)
                elif len('MOE {}'.format(label)) <= 255:
                    alt_moe = 'MOE {}'.format(label)
                else:
                    alt_moe = 'MOE {}'.format(name)
            elif len(label) <= 255:
                alt = label
                if len('MOE {}'.format(label)) <= 255:
                    alt_moe = 'MOE {}'.format(label)
                else:
                    alt_moe = 'MOE {}'.format(name)
            else:
                alt = name
                alt_moe = 'MOE {}'.format(name)   
            if parameters[3].valueAsText == 'Tract':
                tbl_universe = tract_tbls
            elif parameters[3].valueAsText == 'Block Group':
                tbl_universe = blkgp_tbls
            if name.split('_')[0] in tbl_universe:
                alias[name] = [alt, alt_moe]
                variables.append('[{}] {} {}'.format(name, concept, label))
                all_var.update([name])
                flds = [i.strip() for i in T[4].text_content().split(',\n')]
                all_moe.update(i for i in flds if i.endswith('M'))

        parameters[4].filters[0].list = variables
        return 

    def createDataURL(self, level, year, variables, fips, counties):
        """Create the URL to fetch the raw data from the Census API."""
        if level == 'Tract':
            url = ('https://api.census.gov/data/{}/acs/acs5?get={}'
                   '&for=tract:*&in=state:{}'
                   '&in=county:{}'.format(year, ','.join(variables), fips,
                                          ','.join(counties)))
        elif level == 'Block Group':
            url = ('https://api.census.gov/data/{}/acs/acs5?get={}'
                   '&for=block%20group:*&in=state:{}&in=county:{}'
                   '&in=tract:*'.format(year, ','.join(variables), fips,
                                        ','.join(counties)))

        arcpy.AddMessage('Data URL: {}'.format(url))
        return url

    def createDataFrame(self, parameters, url, variables):
        """Create and format the Pandas dataframe with Census API Data."""
        # Load the raw Census data into a Pandas DataFrame.
        df = pandas.read_json(url)

        # Null values or Not a Number (NaN) will cause the conversion to the
        # NumPy array to fail.  Convert all nulls to -9999.  
        df.fillna(-9999, inplace=True)

        # Modify the data frame such that the first row becomes the header row.
        df.columns = df.iloc[0]
        df = df.drop(0)
        df = df.reset_index(drop=True)

        # Convert the "state", "county", "tract", and "block group" (if present)
        # nomenclature used in the raw data pull to match that used in the geo-
        # metry downloads.
        dic = {'state': 'STATEFP',
               'county': 'COUNTYFP',
               'tract': 'TRACTCE',
               'block group': 'BLKGRPCE'}
        col_names = list(df.columns)
        new_names = [dic[i] if i in dic else i for i in col_names]
        df = df.set_axis(new_names, axis='columns')

        # Define a new column, GEOID, which matches the GEOID attribute in the
        # geometry shapefiles and feature classes available from the Census.  
        # Then re-order the dataframe to the desired column order
        level = parameters[3].value
        if level == 'Block Group':
            df['GEOID'] = df['STATEFP'] + df['COUNTYFP'] + df['TRACTCE'] + \
                          df['BLKGRPCE']
            names = ['GEOID', 'STATEFP', 'COUNTYFP', 'TRACTCE', 'BLKGRPCE'] + \
                    variables
        elif level == 'Tract':
            df['GEOID'] = df['STATEFP'] + df['COUNTYFP'] + df['TRACTCE']
            names = ['GEOID', 'STATEFP', 'COUNTYFP', 'TRACTCE'] + variables
        df = df[names]
        return df

    def analyzeVariables(self, parameters, df):
        """Analyze the requested Census variables to determine data types.
        Remove variables that only contain nulls."""          
        # Strucutured arrays are needed when performing the conversions.  Deter-
        # mine the correct data type for each array element, resulting in eith-
        # a Long or Double in the final table or feature class output.  Create a
        # message that shows the minimum and maximum values for each variable.
        level = parameters[3].value
        dic_dtypes = {'names': [], 'formats': [], 'min': [], 'max': []}
        dic_dtypes['names'] = ['GEOID', 'STATEFP', 'COUNTYFP', 'TRACTCE']
        dic_dtypes['formats'] = ['|S11', '|S2', '|S3', '|S6']
        if level == 'Block Group':
            # The GEOID field must have an additional space to hold the block
            # group information.
            dic_dtypes['formats'][0] = '|S12'
            dic_dtypes['names'] += ['BLKGRPCE']
            dic_dtypes['formats']+= ['|S1']
        dic_dtypes['min'] += len(dic_dtypes['names']) * [0]
        dic_dtypes['max'] += len(dic_dtypes['names']) * [0]
        msg = '{:>11}    {:>15}    {:>15}'.format('Variable', 'Minimum',
                                                  'Maximum')
        
        # Analyze each variable chosen by the user.  If selected, remove vari-
        # ables that only contain null records.  Determine the approriate data
        # type of each variable.
        remove_cols = []
        col_names = list(df.columns)
        if level == 'Block Group':
            idx = col_names.index('BLKGRPCE') + 1
        elif level == 'Tract':
            idx = col_names.index('TRACTCE') + 1
        for col in df.columns[idx:]:
            minimum = min(df[col].astype(float))
            maximum = max(df[col].astype(float))
            if parameters[6].value:
                if minimum == -9999 and maximum == -9999:
                    remove_cols += [col]
                    continue
            dic_dtypes['names'] += [col]
            if minimum > -2147483648 and maximum < 2147483647:
                dic_dtypes['formats'] += [numpy.int32]
            elif minimum > -2.2e308 and maximum < 1.8e308:
                dic_dtypes['formats'] += [numpy.float64]
            else:
                dic_dtypes['formats'] += ['ERROR']
            dic_dtypes['min'] += [minimum]
            dic_dtypes['max'] += [maximum]
            msg += '\n{:>11}    {:>15,.0f}    {:>15,.0f}'.format(col, minimum,
                                                                 maximum)
        arcpy.AddMessage(msg)

        # Remove null variables from the data frame if the array is populated.
        if remove_cols:
            msg = ('The following variables were dropped because all '
                   'records were null: ')
            for col in remove_cols:
                msg += '\n\t{}'.format(col)              
            arcpy.AddMessage(msg)
            df = df.drop(columns=remove_cols)

        # Check for errors in determining the data types.
        errors = []
        for i in range(idx, len(dic_dtypes['formats'])):
            if dic_dtypes['formats'][i] == 'ERROR':
                errors += dic_dtypes['names'][i]
        if errors:
            msg = ('Unable to determine the data type for the following '
                   'variables:{}'.format('\n'.join(errors)))
            arcpy.AddMessage(msg)
            return ### NEED TO HANDLE THIS ERROR BETTER ###
        return dic_dtypes, df

    def createShpURL(self, parameters, year, state, fips):
        """Create the URL used to retrieve data from the Census API."""
        # The tool currently only works from 2014 onwards.  However, it is hoped
        # that it will eventually be modified to work beginning from 2009.
        if parameters[3].valueAsText == 'Block Group':
            level = 'bg'
        elif parameters[3].valueAsText == 'Tract':
            level = 'tract'

        if int(year) >= 2014:
            url = ('https://www2.census.gov/geo/tiger/GENZ{}/shp/'
                   'cb_{}_{}_{}_500k.zip'.format(year, year, fips, level))
        elif 2011 <= int(year) <= 2013:
            url = ('https://www2.census.gov/geo/tiger/TIGER{}/TRACT/'
                   'tl_{}_{}_tract.zip'.format(year, year, fips))
        elif int(year) == 2010:
            url = ('https://www2.census.gov/geo/tiger/TIGER2010/TRACT/2010/'
                   'tl_2010_{}_tract10.zip'.format(fips))
        elif int(year) == 2009:
            url = ('https://www2.census.gov/geo/tiger/TIGER2009/'
                   '{}_{}/tl_2009_{}_tract00.zip'.format(fips, state, fips))
        arcpy.AddMessage('Geometry URL: {}'.format(url))
        return url

    def changeFieldAliases(self, data):
        """Change the estimate field aliases to descriptive names."""
        flds = [fld.name for fld in arcpy.Describe(data).Fields]
        for fld in flds:
            if fld in alias:
                arcpy.management.AlterField(data, fld, '', alias[fld][0])
                fld_moe = fld[:-1] + 'M'
                if fld_moe in flds:
                    arcpy.management.AlterField(data, fld_moe, '',
                                                alias[fld][1])
