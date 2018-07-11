from death.post.qdata import *
from torch.utils.data import Dataset, DataLoader
import numpy as np
import pandas as pd
import copy

# we can only assume that all deaths are recorded

# torch integration reference: https://github.com/utkuozbulak/pytorch-custom-dataset-examples

def get_timestep_location(earliest, time):
    '''
    Uses numpy instead of panda.

    :param earliest: pandas.Timestamp
    :param time: ndarray of datetime64
    :return: cc: int numpy array, the index location of the corresponding records
    '''
    earliest=earliest.to_datetime64()
    time=time.values
    cc=(time-earliest).astype('timedelta64[M]')
    return cc.astype("int")

# multiple inheritance
class InputGen(Dataset,DFManager):
    '''
    take a data frame manager object and produce inputs wrapped in torch objects
    '''
    def __init__(self,load_pickle=True,verbose=False,debug=False):
        super(InputGen, self).__init__()
        self.load_pickle(verbose=verbose)
        self.rep_person_id=self.demo.index.values
        self.verbose=verbose
        # 46872
        self.input_dim=None
        # manual format: (dfname,colname,starting_index)
        self.input_dim_manual=None
        self.get_input_dim()
        # this df has no na
        self.earla=pd.read_csv("/infodev1/rep/projects/jason/earla.csv",parse_dates=["earliest","latest"])
        self.earla.set_index("rep_person_id",inplace=True)

    def get_input_dim(self):
        # pre allocate a whole vector of input
        input_dim_manual=[]
        dimsize = 0
        for dfn in self.dfn:
            df = getattr(self, dfn)
            # get all columns and column dtypes, allocate depending on the dtypes
            for colname, dtype in zip(df.dtypes.index, df.dtypes):
                if colname == "rep_person_id" or self.is_date_column(colname):
                    # no memory needed for these values.
                    # either index that is ignored, or contained in the time series.
                    pass
                else:
                    dtn = dtype.name
                    input_dim_manual.append((dfn, colname, dimsize))
                    if self.verbose:
                        print("accounting for", dfn, colname)
                    if dtn == 'bool':
                        dimsize += 1
                    if dtn == "category":
                        dimsize += len(self.get_dict(dfn, colname))
                    if dtn == "object":
                        dimsize += len(self.get_dict(dfn, colname))
                    if dtn == "float64":
                        dimsize += 1
                    if dtn == "datetime64[ns]":
                        raise ValueError("No, I should not see this")

        # # the last index is a binary flag whether there is time-dependent record on this location
        # dimsize=dimsize+1

        self.input_dim=dimsize
        self.input_dim_manual=input_dim_manual

    def get_column_index_range(self, dfn, coln):
        '''
        standard notation [start,end)
        modifies self.input_dim_manual and self.input_base_size
        :param dfn:
        :param coln:
        :return: start, end: integer, memory index
        '''
        idx=0
        start=None
        end=None
        while(idx<len(self.input_dim_manual)):
            if self.input_dim_manual[idx][0]==dfn and self.input_dim_manual[idx][1]==coln:
                start=self.input_dim_manual[idx][2]
            idx+=1
        if idx<len(self.input_dim_manual):
            end=self.input_dim_manual[idx][2]
        else:
            end=self.input_dim

        return start,end

    def batch_get(self,index,debug=False):
        '''
        time-wise batch version of __getitem__()
        notably, I will access timestamp as a whole a see if I can use it effectively in the end.

        :param index:
        :return:
        '''
        id = self.rep_person_id[index]
        # plus 2 should not bring problem? I am not sure
        month_interval = self.earla.loc[id]["int"] + 1
        earliest=self.earla.loc[id]["earliest"]
        latest=self.earla.loc[id]["latest"]
        input = np.zeros((month_interval, self.input_dim))

        ### we pull all relevant data
        # demo, will span all time stamps
        demorow = self.demo.loc[id]
        race = demorow['race']
        educ_level = demorow['educ_level']
        birth_date = demorow['birth_date']
        male = demorow['male']
        # TODO this is not done

        # all others, will insert at specific timestamps
        # diagnosis
        dias = self.dia.loc[id]
        for index, row in dias.iterrows():
            date = row['dx_date']
            dx_codes = row["dx_codes"]

        others = [dfn for dfn in self.dfn if dfn not in ("death", "demo")]
        for dfn in others:
            # any df is processed here
            if debug:
                dfn="dhos"
                df= self.dhos
            else:
                df = self.__getattribute__(dfn)
            allrows = df.loc[id]

            # get the index for all dates first
            date_coln = [coln for coln in df if self.is_date_column(coln)]

            if debug:
                assert len(date_coln) == 1
            datacolns = [coln for coln in df if not self.is_date_column(coln) and coln != "rep_person_id"]
            date_coln = date_coln[0]

            all_dates=allrows[date_coln]
            tsloc=get_timestep_location(earliest,all_dates)

            # we bucket the columns so we know how to process them.
            direct_insert = []
            barsep = []
            nobarsep = []

            for coln in datacolns:
                if (dfn, coln) in self.no_bar:
                    nobarsep.append(coln)
                elif (dfn, coln) in self.bar_separated:
                    barsep.append(coln)
                else:
                    direct_insert.append(coln)
                    if debug:
                        try:
                            assert (self.dtypes[dfn][coln] in ("int", "bool", "float"))
                        except (KeyError, AssertionError) as e:
                            raise

            print("ready")

            # we need two things: index and values
            for coln in direct_insert:
                index=


            # deal with direct insert




        # exception handling: high frequency visitors

        ### we compile it into time series

        print("get item finished")


    def __getitem__(self, index):
        '''
        pulls a row in demographics
        pulls all data from all files
        compile it into a longest vector
        construct label from death records

        We do not use sliding window augmentation here.
        We do sliding window augmentation probably in the training stage.
        Simply because we cannot find the index for a window without loading the series.

        input will be variable length, with a unit of a month

        for missing data, the whole vector will be zero. There should not be gradient backprop. TODO make sure.
        :param index:
        :return: (time, longest)
        '''
        id=self.rep_person_id[index]
        # plus 2 should not bring problem? I am not sure
        month_interval=self.earla.loc[10]["int"]+1
        input=np.zeros((month_interval,self.input_dim))

        ### we pull all relevant data
        # demo, will span all time stamps
        demorow=self.demo.loc[id]
        race=demorow['race']
        educ_level=demorow['educ_level']
        birth_date=demorow['birth_date']
        male=demorow['male']
        # TODO this is not done

        # all others, will insert at specific timestamps
        # diagnosis
        dias=self.dia.loc[id]
        for index, row in dias.iterrows():
            date=row['dx_date']
            dx_codes=row["dx_codes"]

        others=[dfn for dfn in self.dfn if dfn not in ("death","demo")]
        for dfn in others:
            # any df is processed here
            df=self.__getattribute__(dfn)
            # figure out which column is the date in this df
            date_coln=[coln for coln in df if self.is_date_column(coln)]
            if debug:
                assert len(date_coln)==1
            datacolns=[coln for coln in df if not self.is_date_column(coln) and coln!="rep_person_id"]
            date_coln=date_coln[0]

            # query
            allrows = df.loc[id]

            # we bucket the columns so we know how to process them.
            direct_insert=[]
            barsep=[]
            nobarsep=[]

            for coln in datacolns:
                if (dfn,coln) in self.no_bar:
                    nobarsep.append(coln)
                if (dfn,coln) in self.bar_separated:
                    barsep.append(coln)
                else:
                    direct_insert.append(coln)
                    if debug:
                        assert(self.dtypes[dfn][coln] in ("int","bool","float"))

            for row in allrows:
                # can we vectorize this computation?
                for coln in datacolns:
                    if coln in direct_insert:
                        pass


        # exception handling: high frequency visitors

        ### we compile it into time series

        print("get item finished")


    def __len__(self):
        '''
        Length of the demographics dataset
        :return:
        '''
        pass

if __name__=="__main__":
    ig=InputGen(load_pickle=True,verbose=True)
    ig.batch_get(0,debug=True)
    print("script finished")