from death.DNC.trainerD3 import *
# from death.DNC.notmysamtrainer import *
import os
from shutil import copy
import traceback
import datetime

if __name__ == "__main__":
    with torch.cuda.device(0):
        print("Using the second CUDA device")
        print("Salvage mode, will attempt to save the most recent weights you have")
        try:
            forevermain(False, 1e-3, savestr="loss",palette=True)
        except:
            traceback.print_exc()
            with open("error.log", 'a') as f:
                f.write(str(datetime.datetime.now().time()))
                traceback.print_exc(file=f)
            salvage("loss")