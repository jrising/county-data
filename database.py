from __future__ import unicode_literals
import os, csv
import numpy as np
import pandas as pd
from metainfo import *
from prompt_toolkit import prompt
from prompt_toolkit.contrib.completers import WordCompleter

def standardize_fips(fips):
    if isinstance(fips, list) or isinstance(fips, np.ndarray) or isinstance(fips, pd.core.series.Series):
        return map(standardize_fips, fips)

    if isinstance(fips, str):
        return '0' + fips if len(fips) < 5 else fips

    return standardize_fips(str(int(fips)))

def localpath(relative):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), relative)

def variable_filtermap(column2variable):
    return lambda columns: set(filter(lambda variable: variable is not None, map(column2variable, columns)))

class RawDatabase(object):
    def get_variables(self):
        """Return a list of variables."""
        raise NotImplementedError()

    def get_fips(self):
        """Return an ordered list of FIPS codes for the data.  FIPS should always be 5 character strings."""
        raise NotImplementedError()

    def get_years(self, variable):
        """Return a list of years available."""
        raise NotImplementedError()

    def get_data(self, variable, year):
        """Return an ordered list of data values, in the same order as the FIPS codes."""
        raise NotImplementedError()

class Database(RawDatabase):
    def __init__(self):
        self.metainfo = Metainfo()

    def set_metainfo(self, metainfo):
        self.metainfo = metainfo

    def describe_variable(self, variable):
        """Text description of a variable."""
        return self.metainfo.describe_variable(variable)

    def get_unit(self, variable):
        """Canonical unit for variable."""
        return self.metainfo.get_unit(variable)

    def get_tags(self, variable):
        """Return a list of tags for each variable."""
        return self.metainfo.get_tags(variable)

class CSVDatabase(Database):
    def __init__(self, filepath, variable_filter=lambda vars: vars, index_col=False, **readkw):
        super(CSVDatabase, self).__init__()

        self.filepath = filepath
        self.variable_filter = variable_filter
        self.df = CSVDatabase.guess_read_csv(filepath, index_col=index_col, **readkw)

    @staticmethod
    def guess_read_csv(filepath, **kw):
        if filepath[-4:] == '.csv':
            return pd.read_csv(filepath, **kw)
        elif filepath[-5:] == '.xlsx':
            return pd.read_excel(filepath, **kw)
        elif filepath[-4:] == '.txt':
            return pd.read_csv(filepath, **kw)            
        else:
            raise RuntimeError("Do not know how to read files of type of " + filepath)

    def get_variables(self):
        return self.variable_filter(list(self.df))

    def make_index_column(self, id_func, indexcol='index'):
        self.df[indexcol] = self.df.apply(id_func, axis=1)
        self.df.set_index(indexcol)

    @staticmethod
    def smart_import(filepath):
        df = CSVDatabase.guess_read_csv(filepath)
        column_completer = WordCompleter(list(df))
        
        # Try to guess the FIPS column
        if 'FIPS' in df:
            fips_column = 'FIPS'
        elif 'fips' in df:
            fips_column = 'fips'
        else:
            fips_column = prompt('Enter the FIPS column: ', completer=column_completer)

        # Try to guess a year column structure
        if 'YEAR' in df:
            year_column = 'YEAR'
        elif 'year' in df:
            year_column = 'year'
        else:
            year_column = None
            for year in range(1960, 2050):
                if str(year) in df:
                    year_column = 'columns'
                    break

            if year_column is None:
                year_column = prompt('How are years represented (none/columns/indexed)? ', completer=WordCompleter(['none', 'columns', 'indexed']))
                if year_column == 'indexed':
                    year_column = prompt('Enter the year column: ', completer=column_completer)

        # Instantiate an appropriate class
        if year_column == 'none':
            return StaticCSVDatabase(filepath, fips_column)
        if year_column == 'columns':
            return MatrixCSVDatabase(filepath, fips_column)

        return ObservationsCSVDatabase(filepath, fips_column, year_column)
                    
class StaticCSVDatabase(CSVDatabase):
    """A simple CSV file, with a row for every county and a column for every variable."""
    
    def __init__(self, filepath, fips_column, variable_filter=lambda vars: vars, year=None, **readkw):
        super(StaticCSVDatabase, self).__init__(filepath, variable_filter=variable_filter, **readkw)
        self.fips_column = fips_column
        self.year = year

    def get_fips(self):
        if callable(self.fips_column):
            return self.fips_column(self.df)
        else:
            return self.df[self.fips_column]

    def get_years(self, variable):
        if self.year is None:
            return None
        else:
            return [self.year]

    def get_data(self, variable, year):
        return self.df[variable]

class MatrixCSVDatabase(CSVDatabase):
    """CSV file with a row for each county and potentially the same
    variables repeated over multiple years in the columns.
    """
    
    def __init__(self, filepath, fips_column, variable_filter=lambda
                 vars: vars, get_varyears=lambda df, var: None,
                 get_datarows=lambda df, var, yr: df[var], **readkw):

        if fips_column is not None:
            with open(filepath, 'rU') as fp:
                reader = csv.reader(fp)
                header = reader.next()
                index_col = header.index(fips_column)

            super(MatrixCSVDatabase, self).__init__(filepath, variable_filter=variable_filter, index_col=index_col, **readkw)
        else:
            super(MatrixCSVDatabase, self).__init__(filepath, variable_filter=variable_filter, **readkw)

        self.standard_fips = None
        self.get_varyears = get_varyears
        self.get_datarows = get_datarows

    def get_fips(self):
        if self.standard_fips is None:
            self.standard_fips = standardize_fips(self.df.index.values)

        return self.standard_fips

    def get_years(self, variable):
        return self.get_varyears(self.df, variable)

    def get_data(self, variable, year):
        return self.get_datarows(self.df, variable, year)

class ObservationsCSVDatabase(CSVDatabase):
    """A CSV file which contains multiple instances of each county, with different rows
    referring to different years."""
    
    def __init__(self, filepath, fips_column, year_column,
                 variable_filter=lambda vars: vars, **readkw):
        super(ObservationsCSVDatabase, self).__init__(filepath, variable_filter=variable_filter, **readkw)
        self.fips_column = fips_column
        self.year_column = year_column

    def get_fips(self):
        return self.df[self.fips_column].unique()

    def get_years(self, variable):
        return self.df[self.year_column].unique()

    def get_data(self, variable, year):
        ## This would be very slow because of constant re-ordering.  Use get_fipsdata(variable, year)
        raise NotImplementedError()

    def get_fipsdata(self, variable, year):
        """Return a tuple of the fips codes available and the data for those corresponding fips codes."""
        rows = self.df[self.year_column] == year
        return self.df[self.fips_column][rows], self.df[variable][rows]

class InterlevedCSVDatabase(CSVDatabase):
    """
    Like an ObservationCSVDatabase, but where each variable type has a
    given specified year, and there is no year column.
    """
    def __init__(self, filepath, fips_column, filter_column, year, **readkw):
        super(InterlevedCSVDatabase, self).__init__(filepath, **readkw)
        self.fips_column = fips_column
        self.filter_column = filter_column
        self.year = year

    def describe_variable(self, variable):
        """Text description of a variable."""
        column, group = tuple(variable.split('.'))
        return super(InterlevedCSVDatabase, self).describe_variable(column) + " for group " + group

    def get_unit(self, variable):
        """Canonical unit for variable."""
        column, group = tuple(variable.split('.'))
        return super(InterlevedCSVDatabase, self).get_unit(column)

    def get_fips(self):
        return self.df[self.fips_column].unique()

    def get_variables(self):
        variables = list(self.df)
        variables.remove(self.fips_column)
        variables.remove(self.filter_column)

        allvars = []
        for group in self.df[self.filter_column].unique():
            allvars.extend([variable + '.' + str(group) for variable in variables])

        return allvars
    
    def get_years(self, variable):
        return [self.year]

    def get_data(self, variable, year):
        ## This would be very slow because of constant re-ordering.  Use get_fipsdata(variable, year)
        raise NotImplementedError()

    def get_fipsdata(self, variable, year):
        """Return a tuple of the fips codes available and the data for those corresponding fips codes."""
        column, group = tuple(variable.split('.'))
        
        rows = self.df[self.filter_column] == group
        return self.df[self.fips_column][rows], self.df[column][rows]

class IDReferenceCSVDatabase(MatrixCSVDatabase):
    def __init__(self, filepath1, id_column1, filepath2, id_column2, fips_column2, *args, **kwargs):
        super(IDReferenceCSVDatabase, self).__init__(filepath1, id_column1, *args, **kwargs)

        idref = pd.read_csv(filepath2)
        self.idorder = idref[id_column2]
        self.fipsorder = standardize_fips(idref[fips_column2])

    def get_fips(self):
        return self.fipsorder

    def get_data(self, variable, year):
        data = super(IDReferenceCSVDatabase, self).get_data(variable, year)
        return data.loc[self.idorder]

class OrderedDatabase(Database):
    """Database with the order pre-specified."""

    def __init__(self, fips, db):
        super(OrderedDatabase, self).__init__()

        self.fips = fips
        self.db = db
        self.set_metainfo(db.metainfo)

    def get_variables(self):
        return self.db.get_variables()

    def get_fips(self):
        return self.fips

    def get_years(self, variable):
        return self.db.get_years(variable)

    def get_data(self, variable, year):
        return self.db.get_data(variable, year)

    @staticmethod
    def use_fips(fipsdb, db):
        return OrderedDatabase(fipsdb.get_fips(), db)

class OrderedVectorDatabase(OrderedDatabase):
    def __init__(self, vector, variable, year, fips):
        super(OrderedVectorDatabase, self).__init__(fips, self)
        self.variable = variable
        self.vector = vector
        self.year = year

    def get_variables(self):
        return [self.variable]

    def get_years(self, variable):
        return [self.year]

    def get_data(self, variable, year):
        return self.vector

    @staticmethod
    def read_text(filepath, variable, year, fipsdb):
        return OrderedVectorDatabase(np.loadtxt(filepath), variable, year, fipsdb.get_fips())

class ConcatenatedDatabase(Database):
    """All database must have the same order of fips."""

    def __init__(self, dbs):
        super(ConcatenatedDatabase, self).__init__()

        self.dbs = dbs
        assert not isinstance(dbs[0], ObservationsCSVDatabase), "Cannot use randomly indexed data for master dataset."

        catalog = {} # variable -> db
        for db in dbs:
            assert np.all(db.get_fips() == dbs[0].get_fips())
            for variable in db.get_variables():
                catalog[variable] = db

        self.catalog = catalog

    def get_variables(self):
        """Return a list of variables."""
        return self.catalog.keys()

    def describe_variable(self, variable):
        """Text description of a variable."""
        return self.catalog[variable].describe_variable(variable)

    def get_unit(self, variable):
        """Canonical unit for variable."""
        return self.catalog[variable].get_unit(variable)

    def get_fips(self):
        """Return an ordered list of FIPS codes for the data."""
        return self.dbs[0].get_fips()

    def get_years(self, variable):
        return self.catalog[variable].get_years(variable)

    def get_data(self, variable, year):
        """Return an ordered list of data values, in the same order as the FIPS codes."""
        return self.catalog[variable].get_data(variable, year)

class CombinedDatabase(Database):
    """Always uses first database for fips codes."""

    def __init__(self, dbs, prefixes, infix):
        super(CombinedDatabase, self).__init__()

        self.dbs = dbs
        self.prefixes = prefixes
        self.infix = infix
        self.indices = {} # {db: [indices]}

        assert not isinstance(dbs[0], ObservationsCSVDatabase), "Cannot use randomly indexed data for master dataset."

    def get_variables(self):
        """Return a list of variables."""
        variables = []
        for ii in range(len(self.dbs)):
            dbvars = ["%s%s%s" % (self.prefixes[ii], self.infix, variable) for variable in self.dbs[ii].get_variables()]
            variables.extend(dbvars)

        return variables

    def get_database(self, variable):
        chunks = variable.split(self.infix)
        return self.dbs[self.prefixes.index(chunks[0])], '.'.join(chunks[1:])

    def get_indices_byfips(self, dbfips, values):
        fips = self.dbs[0].get_fips()
        result = np.empty(len(fips))
        for ii in range(len(fips)):
            try:
                result[ii] = values[dbfips.index(fips[ii])]
            except Exception as ex:
                result[ii] = np.nan

        return result

    def get_indices(self, db, values):
        if db not in self.indices:
            fips = self.dbs[0].get_fips()
            dbfips = pd.Index(db.get_fips())
            indices = np.empty(len(fips), dtype=int)
            for ii in range(len(fips)):
                try:
                    indices[ii] = dbfips.get_loc(fips[ii])
                except Exception as ex:
                    indices[ii] = -1
            self.indices[db] = indices

        if isinstance(values, pd.Series):
            return [values.iloc[index] if index != -1 else np.nan for index in self.indices[db]]
        else:
            return [values[index] if index != -1 else np.nan for index in self.indices[db]]


    def describe_variable(self, variable):
        """Text description of a variable."""
        db, dbvar = self.get_database(variable)
        return db.describe_variable(dbvar)

    def get_unit(self, variable):
        """Canonical unit for variable."""
        db, dbvar = self.get_database(variable)
        return db.get_unit(dbvar)

    def get_fips(self):
        """Return an ordered list of FIPS codes for the data."""
        return self.dbs[0].get_fips()

    def get_years(self, variable):
        db, dbvar = self.get_database(variable)
        return db.get_years(dbvar)

    def get_data(self, variable, year):
        """Return an ordered list of data values, in the same order as the FIPS codes."""
        db, dbvar = self.get_database(variable)
        if db == self.dbs[0]:
            return db.get_data(dbvar, year)

        if 'get_fipsdata' in dir(db):
            fips, data = db.get_fipsdata(dbvar, year)
            return self.get_indices_byfips(fips, data)

        data = db.get_data(dbvar, year)

        # Match up the data along the fips
        return self.get_indices(db, data)

class CombinedYearsDatabase(Database):
    def __init__(self, dbs, fips):
        super(CombinedYearsDatabase, self).__init__()

        self.dbs = dbs
        self.fips = fips
        self.indices = {} # {db: [indices]}

    def get_variables(self):
        """Return a list of variables."""
        variables = set([])
        for ii in range(len(self.dbs)):
            variables.update(self.dbs[ii].get_variables())

        return variables

    def get_database(self, variable, year):
        for db in self.dbs:
            if year in db.get_years(variable):
                return db

    def get_indices_byfips(self, dbfips, values):
        result = np.empty(len(self.fips))
        for ii in range(len(self.fips)):
            try:
                result[ii] = values[dbfips.index(self.fips[ii])]
            except:
                result[ii] = np.nan

        return result

    def get_indices(self, db, values):
        if db not in self.indices:
            dbfips = list(db.get_fips())
            indices = np.empty(len(self.fips), dtype=int)
            for ii in range(len(self.fips)):
                try:
                    indices[ii] = dbfips.index(self.fips[ii])
                except:
                    indices[ii] = -1
            self.indices[db] = indices

        return [values.iloc[index] if index != -1 else np.nan for index in self.indices[db]]

    def describe_variable(self, variable):
        """Text description of a variable."""
        return self.dbs[0].describe_variable(variable)

    def get_unit(self, variable):
        """Canonical unit for variable."""
        return self.dbs[0].get_unit(variable)

    def get_fips(self):
        """Return an ordered list of FIPS codes for the data."""
        return self.fips

    def get_years(self, variable):
        years = []
        for db in self.dbs:
            years.extend(db.get_years(variable))
        return years

    def get_data(self, variable, year):
        """Return an ordered list of data values, in the same order as the FIPS codes."""
        db = self.get_database(variable, year)

        if 'get_fipsdata' in dir(db):
            fips, data = db.get_fipsdata(variable, year)
            return self.get_indices_byfips(fips, data)

        data = db.get_data(variable, year)

        # Match up the data along the fips
        return self.get_indices(db, data)
