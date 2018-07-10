from death.post.qdata import DFManager
from torch.utils.data import Dataset, DataLoader
import numpy as np
import pandas as pd

# we can only assume that all deaths are recorded

# torch integration reference: https://github.com/utkuozbulak/pytorch-custom-dataset-examples

class InputGen(Dataset):
    '''
    take a data frame manager object and produce inputs wrapped in torch objects
    '''
    def __init__(self,load_pickle=True,verbose=False):
        self.dfm=DFManager()
        self.dfm.load_pickle(verbose=verbose)
        self.rep_person_id=self.dfm.demo.index.values
        self.verbose=verbose
        self.input_dim=None
        # manual format: (dfname,colname,starting_index)
        self.input_dim_manual=None
        self.get_input_dim()

    def get_input_dim(self):
        # pre allocate a whole vector of input
        input_dim_manual=[]
        dimsize = 0
        for dfn in self.dfm.dfs:
            df = getattr(self.dfm, dfn)
            # get all columns and column dtypes, allocate depending on the dtypes
            for colname, dtype in zip(df.dtypes.index, df.dtypes):
                if colname == "rep_person_id" or self.dfm.is_date_column(colname):
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
                        dimsize += len(self.dfm.get_dict(dfn, colname))
                    if dtn == "object":
                        dimsize += len(self.dfm.get_dict(dfn, colname))
                    if dtn == "float64":
                        dimsize += 1
                    if dtn == "datetime64[ns]":
                        raise ValueError("No, I should not see this")
        self.input_dim=dimsize
        self.input_dim_manual=input_dim_manual

    def get_input_index_range(self,dfn,coln):
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

        ### we pull all relevant data
        # demo
        id=self.rep_person_id[index]
        demorow=self.dfm.demo.loc[id]
        race=demorow['race']
        educ_level=demorow['educ_level']
        birth_date=demorow['birth_date']
        male=demorow['male']

        self.dfm.death.loc[10]


        # get the earliest record time and the latest record time, calculate how many months that would be

        earliest=None
        latest=None

        # exception handling: high frequency visitors
        # allocate now





        # pull demographics

        ### we compile it into time series

        print("get item finished")

    # def _time_helper(self,earliest,latest):


    def __len__(self):
        '''
        Length of the demographics dataset
        :return:
        '''

if __name__=="__main__":
    ig=InputGen(load_pickle=True,verbose=True)
    ig.__getitem__(0)
    print("script finished")