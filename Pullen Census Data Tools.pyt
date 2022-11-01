# -*- coding: utf-8 -*-
"""
   Code: Pullen Census Data Tools.pyt
 Author: Randy Pullen, Planning Analyst II (rpullen@chattanooga.gov)
         Chattanooga-Hamilton County Regional Planning Agency
         1250 Market St, Suite 2000
         Chattanooga, TN 37402
   Date: 2022-10-31
Version: Python 3.9.11
         ArcGIS Pro 3.0.2
License: GIS Professional Basic
================================================================================
Summary: This toolbox contains a tool for extracting up to 50 estimates from the
         U.S. Census Bureau American Community Survey (ACS) 5-year estimates.
         Values are written to a table within an existing file geodatabase.

         The tool scrapes Census web pages to populate tool interfaces for
         state, counties, and variables available to download.  The margins of
         error may be optionally downloaded as well.  A URL is constructed that
         works with the Census API to acquire the desired variables.  That data
         may either be converted to a stand alone table, or, if the user wishes, it
         may be combined with a downloaded shapefile of census tract geometries
         and converted into a feature class within an existing file geodatabase
         containing all of the desired attributes.
--------------------------------------------------------------------------------
Caveats: This tool is incompatible with ArcMap.

         In some circumstances, the global variable moe_all is set to None if
         the tool is re-run without being reinitialized, causing the tool to
         fail during execution.

         The tool will fail if called from the geoprocessing history.

         The tool does not work from the Python command line.

         The following  warning applies to the tool metadata (.xml) and not this
         actual script.  If the user clicks on the embedded hyperlinks to see
         the variable definitions from the help info box (the box that appears
         when hovering over the blue "i" mark left of the paramter name in the
         tool dialogue window), ArcGIS Pro will crash.  Esri has confirmed this behavior
         as BUG-000151931.  If the hyperlinks are accessed via Catalog View,
         however, then they work as intended.
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
================================================================================
"""

import arcpy
import os
import pandas
import requests
import lxml.html
from collections import Counter
from zipfile import ZipFile

class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = 'Toolbox'
        self.alias = 'toolbox'

        # List of tool classes associated with this toolbox
        self.tools = [ACS5Yr]

class ACS5Yr(object):
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = '5-Year ACS'
        self.description = ''
        self.canRunInBackground = False

    def getParameterInfo(self):
        """Define parameter definitions"""

        # Global declaration of the set variables used to keep track of all mar-
        # gins of error (MOEs) for a given year & the MOEs available for the
        # specific variables selected by the user.
        global moe_all
        global moe_avail

        # The year of interest.  The range must be updated whenever new data be-
        # comes available.
        param0 = arcpy.Parameter(
            displayName='Year',
            name='year',
            datatype='GPLong',
            parameterType='Required',
            direction='Input')
        param0.filter.type = 'ValueList'
        param0.filter.list = [i for i in range(2020, 2013, -1)]

        # The state of interest.  In the user dialogue, the selections are pre-
        # sented as "[FIPS] Name (Postal Abbv.)," e.g., "[47] Tennessee (TN)."
        # States and FIPS are pulled dynamically from the Census website.  The
        # element index ranges were determined by trial & error.
        param1 = arcpy.Parameter(
            displayName='State',
            name='state',
            datatype='GPString',
            parameterType='Required',
            direction='Input')
        url = 'https://www.census.gov/library/reference/code-lists/ansi.html'
        page = requests.get(url)
        doc = lxml.html.fromstring(page.content)
        tr_elements = doc.xpath('//tr')
        states = []
        for n in range(40, 91):
            states.append(tr_elements[n].text_content().split('\n')[:-1])
        states = [['[{}] {} ({})'.format(i[1], i[0], i[2])] for i in states]
        param1.filter.type = 'ValueList'
        param1.filter.list = [i[0] for i in states]

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

        # The ACS variables of interest.  The variable list is set within the
        # updateParameters function so that if the year is changed, the list
        # will reset.
        param3 = arcpy.Parameter(
            displayName='Variables (select up to 50 variables)',
            name='census_variables',
            datatype='GPValueTable',
            parameterType='Required',
            direction='Input')
        param3.columns = [['GPString', 'Name']]
        param3.filters[0].type = 'ValueList'

        # Boolean to indicate whether variables for which all records are null
        # should be excluded from the final output.
        param4 = arcpy.Parameter(
            displayName='Drop variables where all records are null.',
            name='null_records',
            datatype='GPBoolean',
            parameterType='Optional',
            direction='Input')

        # Boolean to indicate whether the margin of errors should be downloaded
        # alongside the variables of interest.
        param5 = arcpy.Parameter(
            displayName='Include margins of error (if available).',
            name='margin_of_error',
            datatype='GPBoolean',
            parameterType='Optional',
            direction='Input')

        # Boolean to indicate whether the tract geometries should be downloaded
        # alongside the variables of interest.
        param6 = arcpy.Parameter(
            displayName='Include tract geometries.',
            name='geometries',
            datatype='GPBoolean',
            parameterType='Optional',
            direction='Input')

        # The output name.  A file geodatabase must already exist in which
        # to create either the table or the feature class. 
        param7 = arcpy.Parameter(
            displayName='Output (must be within a file geodatabase)',
            name='output',
            datatype=['DETable', 'DEFeatureClass'],
            parameterType='Required',
            direction='Output')
        
        params = [param0, param1, param2, param3, param4, param5, param6,
                  param7]
        return params

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""

        # Dynamically populates the tool drop down of Census estimates from the
        # official page of estimate definitions.  Actual variable elements on
        # the page are identified by having a length of 8 and a Predicate Type
        # of "int."  The loop start value was determined by trial and error.  A
        # collection is also made of all MOE for the given year, which is global
        # in scope.  The MOE is identified in the Attributes column by having an
        # "M" suffix versus an "EA" or "MA."
        if parameters[0].altered and not parameters[0].hasBeenValidated:
            parameters[3].values = None
            url = ('https://api.census.gov/data/{}/acs/acs5/'
                   'variables.html'.format(parameters[0].value))
            page = requests.get(url)
            doc = lxml.html.fromstring(page.content)
            tr_elements = doc.xpath('//tr')
            variables = []
            desc = []
            global moe_all
            moe_all = set()
            for j in range(2, len(tr_elements)):
                T = tr_elements[j]
                if len(T) != 8 or T[6].text_content() != 'int':
                    continue
                ID = T[0].text_content()
                tbl = T[2].text_content()
                var = ' '.join(T[1].text_content().split('!!')[2:])
                variables.append('[{}] {} {}'.format(ID, tbl, var))
                flds = [i.strip() for i in T[4].text_content().split(',\n')]
                moe_all.update(i for i in flds if i.endswith('M'))
            parameters[3].filters[0].list = variables

        # Dynamically populate the tool drop down of state counties based upon
        # the user's selection of state.  The data source, from the Census web
        # site, contains geographies more detailed than counties, so a set is
        # utilized to remove duplicate listings.  The "County" suffix, where
        # applicable, is removed to clean up the drop down.  Counties are pre-
        # sented as "[FIPS] Name," e.g., "[065] Hamilton."
        if parameters[1].altered and not parameters[1].hasBeenValidated:
            parameters[2].values = None
            fips = parameters[1].value[1:3]
            abbv = parameters[1].value[-3:-1].lower()
            url = ('https://www2.census.gov/geo/docs/reference/codes/files/'
                   'st{}_{}_cousub.txt'.format(fips, abbv))
            page = requests.get(url)
            doc = lxml.html.fromstring(page.content)
            T = doc.text_content().split('\r\r')
            t = sorted(set(tuple(i.split(',')[2:4]) for i in T))
            s = 'County'
            cnty = ['[{}] {}'.format(i[0], i[1][:i[1].rfind(s) - 1]
                                     if i[1].rfind(s) > 0 else i[1]) for i in t]
            parameters[2].filters[0].list = ['[*] All Counties'] + cnty
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""

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
        if parameters[3].values and len(parameters[3].values) > 1:
            variables = [i[0][1:i[0].find(']')] for i in parameters[3].values]
            num_var = len(variables)
            # Duplicates produce a data retrieval failure with Census servers.
            if num_var > len(set(variables)):
                msg = ('The selection should not contain duplicates.  The '
                       'following variables are duplicated one or more times:')
                counts = dict(Counter(variables))
                dups = {k: v for k, v in counts.items() if v > 1}
                for k in sorted(dups):
                    msg += '\n{}'.format(k)
                parameters[3].setErrorMessage(msg)
            # The get command of the URL supports a maximum of 50 variables.
            if num_var > 50:
                msg = ('There are {:,d} variables selected.  The Census web '
                       'site only allows for 50 variables.'.format(num_var))
                parameters[3].setErrorMessage(msg)
            # Requests for the margins of error cannot bring the total number of
            # variables above 50.
            if parameters[5].value:
                # MOE have the same name as estimate variables except they end
                # in 'M'.  Convert the variable names into potential MOE names.
                moe_conv = set(i[:-1] + 'M' for i in variables)
                # Intersect a set of converted MOE names with the set of all
                # published MOE variable names to determine which MOE are avail-
                # able.  Not all estimate variables have MOE uniformly across
                # years, so membership must always be checked.
                global moe_all
                global moe_avail
                moe_avail = moe_all.intersection(moe_conv)
                num_moe = len(moe_avail)
                total = num_var + num_moe
                if total > 50:
                    msg = ('There are {:,d} variables selected ({:,d} '
                           'estimates + {:,d} margins of error), exceeding the '
                           '50 variable limit imposed by the Census '
                           'Bureau.'.format(total, num_var, num_moe))
                    parameters[3].setErrorMessage(msg)            
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        year = parameters[0].value
        arcpy.AddMessage('Year: {}'.format(year))
        val = parameters[1].value
        state_fips = val[1:3]
        state_name = ' '.join(val.split()[1:-1])        
        arcpy.AddMessage('State: {} ({})'.format(state_fips, state_name))
        counties = [i[0].split()[0][1:-1] for i in parameters[2].values]
        counties = ['*'] if '*' in counties else counties
        arcpy.AddMessage('Counties: {}'.format(', '.join(counties)))

        # Obtain a list of the variables selected by the user.  Add to the
        # variable list the available margins of error if optionally selected.
        variables = [i[0][1:i[0].find(']')] for i in parameters[3].values]
        if parameters[5].value:
            global moe_avail
            variables = sorted(set(variables).union(moe_avail))

        # Create a dictionary of the variable and its description.
        alias = {}
        for i in parameters[3].values:
            idx = i[0].find(']')
            ID = i[0][1:idx]
            desc = i[0][idx + 2:]
            alias[ID] = desc
        msg = 'Variable\tDescription'
        for k in sorted(alias.keys()):
            msg += '\n{}\t{}'.format(k, alias[k])
        arcpy.AddMessage(msg)
        
        # Once all variables have been identified, construct a URL that will
        # fetch the raw data from the Census Bureau.
        url = ('https://api.census.gov/data/{}/acs/acs5?get={}&for=tract:*'
       '&in=state:{}&in=county:{}'.format(year, ','.join(variables),
                                          state_fips, ','.join(counties)))
        arcpy.AddMessage('Data URL: {}'.format(url))        

        # Load the raw Census data into a Pandas dataframe.
        df = pandas.read_json(url)

        # Convert the "state", "county", and "tract" columns, which are always
        # the last columns, in that order, to match the nomenclature used in
        # the geometry downloads.
        i = df.shape[1] - 1
        df[i] = df[i].replace(['tract'], 'TRACTCE')
        i = df.shape[1] - 2
        df[i] = df[i].replace(['county'], 'COUNTYFP')
        i = df.shape[1] - 3
        df[i] = df[i].replace(['state'], 'STATEFP')

        # Null values, or Not a Number (NaN), will cause the conversion to the
        # NumPy array to fail.  Convert all nulls to -9999.  
        df.fillna(-9999, inplace=True)

        # Modify the data frame such that the first row becomes the header row.
        df.columns = df.iloc[0]
        df = df.drop(0)
        df = df.reset_index(drop=True)

        # Define a new column, GEOID, which matches the GEOID attribute in the
        # tract shapefiles and feature classes available from the Census.
        df['GEOID'] = df['STATEFP'] + df['COUNTYFP'] + df['TRACTCE']

        # Re-order the dataframe to the desired column order.
        names = ['GEOID', 'STATEFP', 'COUNTYFP', 'TRACTCE'] + variables
        df = df[names]

        # Strucutured arrays are needed when performing the conversions.  Deter-
        # mine the correct data type for each array element, resulting in eith-
        # a Long or Double in the final table or feature class output.  Create a
        # message that shows the minimum and maximum values for each variable.
        dic_dtypes = {'names': [], 'formats': [], 'min': [], 'max': []}
        dic_dtypes['names'] += ['GEOID', 'STATEFP', 'COUNTYFP', 'TRACTCE']
        dic_dtypes['formats']+= ['|S11', '|S2', '|S3', '|S6']
        dic_dtypes['min'] += [0, 0, 0, 0]
        dic_dtypes['max'] += [0, 0, 0, 0]
        msg = '{:>11}    {:>15}    {:>15}'.format('Variable', 'Minimum',
                                                  'Maximum')

        # Analyze each variable chosen by the user.  If selected, remove vari-
        # ables that only contain null records.  Determine the approriate data
        # type of each variable.
        remove_cols = []
        for col in df.columns[4:]:
            minimum = min(df[col].astype(float))
            maximum = max(df[col].astype(float))
            if parameters[4].value:
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
            msg = ('The following variables were dropeed because all '
                   'records were null: ')
            for col in remove_cols:
                msg += '\n\t{}'.format(col)
            arcpy.AddMessage(msg)
            df = df.drop(columns=remove_cols)

        # Check for errors in determining the data types.
        errors = []
        for i in range(4, len(dic_dtypes['formats'])):
            if dic_dtypes['formats'][i] == 'ERROR':
                errors += dic_dtypes['names'][i]
        if errors:
            msg = ('Unable to determine the data type for the following '
                   'variables:{}'.format('\n'.join(errors)))
            arcpy.AddMessage(msg)
            return

        # Convert the Pandas data frame to a NumPy array using the data type
        # definitions.
        dts = {'names': dic_dtypes['names'], 'formats': dic_dtypes['formats']}
        arr = numpy.core.records.fromarrays(df.to_numpy().transpose(),
                                            dtype=dts)

        # Sort the array based upon GEOID.
        arr = arr[arr['GEOID'].argsort()]

        # Convert the NumPy array into a table.  If the geometries are request-
        # ed, use a scratch name for the table.
        ws = parameters[7].valueAsText
        ws = ws[:ws.rfind('.gdb') + 4]
        orig_ws = arcpy.env.workspace
        arcpy.env.workspace = ws
        if parameters[6].value:
            prefix =  'xxxCensusAPITable_'
            tbl = arcpy.CreateScratchName(prefix, '', 'ArcInfoTable', ws)
        else:
            tbl = parameters[7].valueAsText
            
        # In theory, this shouldn't be needed, but even using CreateScratchName,
        # ArcPy will create a non-unique table name, so it's best to delete any
        # previous version of the table that may exist.
        if arcpy.Exists(tbl):
            arcpy.management.Delete(tbl)
        arcpy.da.NumPyArrayToTable(arr, tbl)

        # Index the GEOID attribute in the file geodatabase table.
        arcpy.management.AddIndex(tbl, 'GEOID', 'idx_GEOID')

        # If the geometries are not required, terminate the script.
        if not parameters[6].value:
            arcpy.env.workspace = orig_ws
            # Alter the field aliases. 
            flds = [fld.name for fld in arcpy.Describe(tbl).Fields]
            for fld in flds:
                if fld in alias:
                    arcpy.management.AlterField(tbl, fld, '', alias[fld])
                    # Update the margin of error alias, if present.
                    moe_fld = fld[:-1] + 'M'
                    if moe_fld in flds:
                        moe_alias = 'MOE ' + alias[fld]
                        arcpy.management.AlterField(tbl, moe_fld, '',
                                                    moe_alias)
            return

        # Create the url to download the shapefile zip archive.
        url = ('https://www2.census.gov/geo/tiger/GENZ{}/shp/'
               'cb_{}_{}_tract_500k.zip'.format(year, year, state_fips))
        arcpy.AddMessage('Geometry URL: {}'.format(url))

        # Isolate just the name of the zip archive, which will be the shapefile
        # name as well, e.g., cb_2020_47_tract_500k.zip
        zip_archive = url[url.rfind('/') + 1:]

        # Create a scratch folder within the folder containing the output file
        # geodatabase to hold the zip archive.  Change the active Python dir-
        # ectory to that folder.
        orig_dir = os.getcwd()
        home = ws[:ws.rfind(os.sep)]
        scratch = arcpy.CreateScratchName('xxxCensusAPI', '', 'Folder', home)
        os.mkdir(scratch)
        os.chdir(scratch)
        
        # Download the shapefile zip archive to the folder contining the file
        # geodatabase specified in the output parameter.
        r = requests.get(url, stream=True)
        size = 16 * 1024
        with open(zip_archive, 'wb') as f:
            for chunk in r.iter_content(chunk_size=size):
                f.write(chunk)

        # Extract the shapefile into the current directory.
        ZipFile(zip_archive, 'r').extractall()

        # Make an in-memory feature layer from the shapefile.  Use a query to
        # restrict the counties to only those requested.
        zip_archive_full_path = os.path.join(scratch, zip_archive)
        shp = zip_archive_full_path.replace('.zip', '.shp')
        tracts = 'CensusTracts'
        if counties != ['*']:
            qry = "COUNTYFP IN ('{}')".format("', '".join(i for i in counties))
        else:
            qry = None
        arcpy.management.MakeFeatureLayer(shp, tracts, qry)
        
        # Join the stand alone table to the feature layer.
        shp_join = arcpy.management.AddJoin(tracts, 'GEOID', tbl, 'GEOID',
                                            'KEEP_ALL', 'INDEX_JOIN_FIELDS')

        # There are tools available in ArcGIS Pro 3.0 that are not available in
        # 2.9.  This script utilizes tools that will work with earlier versions
        # of ArcGIS Pro.
        
        # The Feature Class to Feature Class tool messes up the ObjectID
        # field.  OBJECTID_1 becomes the actual OID and OBJECTID is just another
        # integer field.  So far, the best work around is to run the Feature
        # Class to Feature Class tool a second time after removing the unwanted
        # fields to get everything set correctly.
        xxxfc = arcpy.CreateScratchName('xxxCensusAPIFeatureClass_', '',
                                        'FeatureClass')
        if arcpy.Exists(xxxfc):
            arcpy.management.Delete(xxxfc)

        # Convert the joined feature class to a temporary feature class    
        arcpy.conversion.FeatureClassToFeatureClass(shp_join,
                                                    os.path.dirname(xxxfc),
                                                    os.path.basename(xxxfc))
        
        # Determine the fields to be deleted and delete those fields.
        flds = arcpy.Describe(xxxfc).Fields
        remove_flds = [f.name for f in flds if (f.type != 'OID' and
                                                not f.required and
                                                f.name.endswith('_1'))]
        remove_flds += [f.name for f in flds if (f.type != 'OID' and
                                                 not f.required and
                                                 f.name == 'OBJECTID')]
        arcpy.management.DeleteField(xxxfc, remove_flds, 'DELETE_FIELDS')

        # After the fields have been removed, use the Feature Class to Feature
        # Class geoprocessing tool again to correct the ObjectID error.
        output = parameters[7].valueAsText
        arcpy.AddMessage('Output: {}'.format(output))
        path = os.path.dirname(output)
        name = os.path.basename(output)
        arcpy.conversion.FeatureClassToFeatureClass(xxxfc, path, name)

        # Delete the temporary feature class.
        arcpy.management.Delete(xxxfc)

        # Alter the field aliases. 
        flds = [fld.name for fld in arcpy.Describe(output).Fields]
        for fld in flds:
            if fld in alias:
                arcpy.management.AlterField(output, fld, '', alias[fld])
                # Update the margin of error alias, if present.
                moe_fld = fld[:-1] + 'M'
                if moe_fld in flds:
                    moe_alias = 'MOE ' + alias[fld]
                    arcpy.management.AlterField(output, moe_fld, '', moe_alias)
                
        # Index the GEOID attribute in the output feature class.
        arcpy.management.AddIndex(output, 'GEOID', 'idx_GEOID')

        # Reset the workspace to its original setting.
        arcpy.env.workspace = orig_ws

        # Reset Python to its original directory.  If the current Python dir-
        # ectory is provided in Delete geoprocessing tool, the tool will return
        # true but the directory will not actually be deleted.
        os.chdir(orig_dir)

        # Delete the scratch stand alone table.
        msg = 'Scratch table: {}'.format(tbl)
        result = arcpy.management.Delete(tbl)
        msg += '\nDeleted scratch table: {}'.format(result)
        arcpy.AddMessage(msg)

        # Delete the scratch feature class.
        msg = 'Scratch feature class: {}'.format(xxxfc)
        result = arcpy.management.Delete(os.path.normpath(xxxfc))
        msg += '\nDeleted scratch feature class: {}'.format(result)
        arcpy.AddMessage(msg)

        # Delete the scratch workspace containing the zip archive and shapefile.
        msg = 'Scratch folder: {}'.format(scratch)
        result = arcpy.management.Delete(os.path.normpath(scratch))
        msg += '\nDeleted scratch folder: {}'.format(result)
        arcpy.AddMessage(msg)
        
        return
