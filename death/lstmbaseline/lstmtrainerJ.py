import pandas as pd
import torch
import numpy as np
import pdb
from pathlib import Path
import os
from os.path import abspath
from death.post.inputgen_planI import InputGenI, pad_collate
from death.post.inputgen_planH import InputGenH
from death.post.inputgen_planJ import InputGenJ
from torch.utils.data import DataLoader
import torch.nn as nn
from torch.nn.modules import LSTM
from torch.autograd import Variable
import pickle
from shutil import copy
import traceback
from collections import deque
import datetime
from death.DNC.seqtrainer import logprint, datetime_filename
import pdb
from death.final.losses import TOELoss, WeightedBCELLoss
from death.final.killtime import out_of_time
from death.final.metrics import ConfusionMatrixStats



def sv(var):
    return var.data.cpu().numpy()

class dummy_context_mgr():
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc_value, traceback):
        return False

def save_model(net, optim, epoch, iteration, savestr):
    epoch = int(epoch)
    task_dir = os.path.dirname(abspath(__file__))
    if not os.path.isdir(Path(task_dir) / "saves" / savestr):
        os.mkdir(Path(task_dir) / "saves" / savestr)
    pickle_file = Path(task_dir).joinpath("saves/" + savestr + "/lstmnorm_" + str(epoch) + "_" + str(iteration) + ".pkl")
    with pickle_file.open('wb') as fhand:
        torch.save((net, optim, epoch, iteration), fhand)
    print('model saved at', pickle_file)

def load_model(computer, optim, starting_epoch, starting_iteration, savestr):
    task_dir = os.path.dirname(abspath(__file__))
    save_dir = Path(task_dir) / "saves" / savestr
    highestepoch = 0
    highestiter = 0
    for child in save_dir.iterdir():
        try:
            epoch = str(child).split("_")[3]
            iteration = str(child).split("_")[4].split('.')[0]
        except IndexError:
            print(str(child))
        iteration = int(iteration)
        epoch = int(epoch)
        # some files are open but not written to yet.
        if child.stat().st_size > 20480:
            if epoch > highestepoch or (iteration > highestiter and epoch == highestepoch):
                highestepoch = epoch
                highestiter = iteration
    if highestepoch == 0 and highestiter == 0:
        print("nothing to load")
        return computer, optim, starting_epoch, starting_iteration
    pickle_file = Path(task_dir).joinpath(
        "saves/" + savestr + "/lstmnorm_" + str(highestepoch) + "_" + str(highestiter) + ".pkl")
    print("loading model at", pickle_file)
    with pickle_file.open('rb') as pickle_file:
        computer, optim, epoch, iteration = torch.load(pickle_file)
    print('Loaded model at epoch ', highestepoch, 'iteartion', iteration)

    return computer, optim, highestepoch, highestiter
#
# def salvage():
#     # this function will pick up the last two highest epoch training and save them somewhere else,
#     # this is to prevent unexpected data loss.
#     # We are working in a /tmp folder, and we write around 1Gb per minute.
#     # The loss of data is likely.
#
#     task_dir = os.path.dirname(abspath(__file__))
#     save_dir = Path(task_dir) / "lstmsaves"
#     highestepoch = -1
#     secondhighestiter = -1
#     highestiter = -1
#     for child in save_dir.iterdir():
#         epoch = str(child).split("_")[3]
#         iteration = str(child).split("_")[4].split('.')[0]
#         iteration = int(iteration)
#         epoch = int(epoch)
#         # some files are open but not written to yet.
#         if epoch > highestepoch and iteration > highestiter and child.stat().st_size > 20480:
#             highestepoch = epoch
#             highestiter = iteration
#     if highestepoch == -1 and highestiter == -1:
#         print("no file to salvage")
#         return
#     if secondhighestiter != -1:
#         pickle_file2 = Path(task_dir).joinpath("lstmsaves/lstm_" + str(highestepoch) + "_" + str(secondhighestiter) + ".pkl")
#         copy(pickle_file2, "/infodev1/rep/projects/jason/pickle/lstmsalvage2.pkl")
#
#     pickle_file1 = Path(task_dir).joinpath("lstmsaves/lstm_" + str(highestepoch) + "_" + str(highestiter) + ".pkl")
#     copy(pickle_file1, "/infodev1/rep/projects/jason/pickle/salvage1.pkl")
#
#     print('salvaged, we can start again with /infodev1/rep/projects/jason/pickle/lstmsalvage1.pkl')

global_exception_counter=0
def run_one_patient(computer, input, target, optimizer, loss_type, real_criterion,
                    binary_criterion, beta, cm, validate=False):
    global global_exception_counter
    patient_loss=None
    try:
        optimizer.zero_grad()
        input = Variable(torch.Tensor(input).cuda())
        target = Variable(torch.Tensor(target).cuda())
        loss_type = Variable(torch.Tensor(loss_type).cuda())

        # we have no critical index, becuase critical index are those timesteps that
        # criterion does not need to be reinitiated for every story, because we are not using a mask

        patient_output=computer(input)
        cause_of_death_output = patient_output[:, 1:]
        cause_of_death_target = target[:, 1:]
        # pdb.set_trace()
        cod_loss= binary_criterion(cause_of_death_output, cause_of_death_target)
        sigoutput = torch.sigmoid(cause_of_death_output)

        toe_output=patient_output[:,0]
        toe_target=target[:,0]
        toe_loss=real_criterion(toe_output,toe_target,loss_type)

        total_loss=cod_loss+beta*toe_loss

        if not validate:
            total_loss.backward()
            optimizer.step()

        cod_loss = float(cod_loss.data)
        toe_loss = float(toe_loss.data)
        cm.update_one_pass(sigoutput, cause_of_death_target, cod_loss, toe_loss)

        if global_exception_counter>-1:
            global_exception_counter-=1
    except ValueError:
        traceback.print_exc()
        print("Value Error reached")
        print(datetime.datetime.now().time())
        global_exception_counter+=1
        if global_exception_counter==10:
            save_model(computer,optimizer,epoch=0,iteration=global_exception_counter)
            raise ValueError("Global exception counter reached 10. Likely the model has nan in weights")
        else:
            pass


def train(computer, optimizer, real_criterion, binary_criterion,
          train, valid, starting_epoch, total_epochs, starting_iter, iter_per_epoch, savestr, beta, param_vt, logfile=False):
    valid_iterator=iter(valid)
    print_interval=10
    val_interval=200
    save_interval=500
    target_dim=None
    rldmax_len=50
    val_batch=100
    traincm=ConfusionMatrixStats(param_vt-1)
    validcm=ConfusionMatrixStats(param_vt-1)
    if logfile:
        open(logfile, 'w').close()

    for name, param in computer.named_parameters():
        logprint(logfile,name)
        logprint(logfile,param.data.shape)


    for epoch in range(starting_epoch, total_epochs):
        for i, (input, target, loss_type) in enumerate(train):
            i=starting_iter+i
            out_of_time()

            if i < iter_per_epoch:
                run_one_patient(computer, input, target, optimizer, loss_type,
                                                   real_criterion, binary_criterion, beta, traincm)

                if i % print_interval == 0:
                    cod_loss, toe_loss = traincm.running_loss()
                    logprint(logfile, "lstmJ" + " epoch %4d, batch %4d. running cod: %.5f, toe: %.5f, total: %.5f" %
                             (epoch, i, cod_loss, toe_loss, cod_loss + beta * toe_loss))
                    logprint(logfile, "lstmJ" + " train sen: %.6f, spe: %.6f, roc: %.6f" %
                             tuple(traincm.running_stats()))

                if i % val_interval == 0:

                    for _ in range(val_batch):
                        # we should consider running validation multiple times and average. TODO
                        try:
                            (input,target,loss_type)=next(valid_iterator)
                        except StopIteration:
                            valid_iterator=iter(valid)
                            (input,target,loss_type)=next(valid_iterator)

                        run_one_patient(computer, input, target, optimizer, loss_type,
                                                       real_criterion, binary_criterion, beta, validcm, validate=True)
                        cod_loss, toe_loss=validcm.running_loss()

                    logprint(logfile, "lstmJ" + " validation. cod: %.10f, toe: %.10f, total: %.10f" %
                             (cod_loss, toe_loss, cod_loss + beta * toe_loss))
                    logprint(logfile, "lstmJ" + " validate sen: %.6f, spe: %.6f, roc: %.6f" %
                             tuple(validcm.running_stats()))

                if i % save_interval == 0:
                    save_model(computer, optimizer, epoch, i, savestr)
                    print("model saved for epoch", epoch, "input", i)
            else:
                break
        starting_epoch=0

def validate(computer, optimizer, real_criterion, binary_criterion,
             train, valid_dl, starting_epoch, total_epochs, starting_iter, iter_per_epoch, beta, logfile=False):
    running_loss=[]
    target_dim=None
    valid_iterator=iter(valid_dl)

    for i in valid_iterator:
        input, target, loss_type=next(valid_iterator)
        val_loss = run_one_patient(computer, input, target, target_dim, optimizer, loss_type,
                                   real_criterion, binary_criterion, validate=True)
        if val_loss is not None:
            printloss = float(val_loss[0])
            running_loss.append((printloss))
        if logfile:
            with open(logfile, 'a') as handle:
                handle.write("validation. count: %4d, val loss     : %.10f \n" %
                             (i, printloss))
        print("validation. count: %4d, val loss: %.10f" %
              (i, printloss))
    print(np.mean(running_loss))


class lstmwrapperJ(nn.Module):
    def __init__(self,input_size=52686, output_size=2976,hidden_size=128,num_layers=16,batch_first=True,
                 dropout=0.1):
        super(lstmwrapperJ, self).__init__()
        self.lstm=LSTM(input_size=input_size,hidden_size=hidden_size,num_layers=num_layers,
                       batch_first=batch_first,dropout=dropout)
        self.bn = nn.BatchNorm1d(input_size)
        self.output=nn.Linear(hidden_size,output_size)
        self.reset_parameters()

        for name, param in self.named_parameters():
            print(name, param.data.shape)

    def reset_parameters(self):
        self.lstm.reset_parameters()
        self.output.reset_parameters()

    def forward(self, input, hx=None):
        input=input.permute(0,2,1).contiguous()
        try:
            bnout=self.bn(input)
            bnout[(bnout != bnout).detach()] = 0
        except ValueError:
            if step_input.shape[0]==1:
                print("Somehow the batch size is one for this input")
                bnout=step_input
            else:
                raise
        input=bnout.permute(0,2,1).contiguous()
        output,statetuple=self.lstm(input,hx)
        output=self.output(output)
        # (batch_size, seq_len, target_dim)
        # pdb.set_trace()
        # output=output.sum(1)
        output=output.max(1)[0]
        return output



def validationonly(savestr):
    '''
    :return:
    '''

    lr = 1e-2
    optim = None
    logfile = "vallog.txt"

    num_workers = 8
    ig = InputGenH()
    trainds = ig.get_train()
    validds = ig.get_valid()
    testds = ig.get_test()
    validdl = DataLoader(dataset=validds, batch_size=8, num_workers=num_workers, collate_fn=pad_collate)
    print("Using", num_workers, "workers for validation set")
    # testing whether this LSTM works is basically a question whether
    lstm = lstmwrapperJ()

    # load model:
    print("loading model")
    lstm, optim, starting_epoch, starting_iteration = load_model(lstm, optim, 0, 0, savestr)

    lstm = lstm.cuda()
    if optim is None:
        optimizer = torch.optim.Adam(lstm.parameters(), lr=lr)
    else:
        # print('use Adadelta optimizer with learning rate ', lr)
        # optimizer = torch.optim.Adadelta(computer.parameters(), lr=lr)
        optimizer = optim

    real_criterion = nn.SmoothL1Loss()
    binary_criterion = nn.BCEWithLogitsLoss()

    traindl=None
    total_epochs=None
    iter_per_epoch=None

    # starting with the epoch after the loaded one
    validate(lstm, optimizer, real_criterion, binary_criterion,
             traindl, validdl, int(starting_epoch), total_epochs, int(starting_iteration), iter_per_epoch, logfile)

def main(load,savestr,lr = 1e-3, beta=1e-3):
    total_epochs = 10
    iter_per_epoch = 2019
    optim = None
    starting_epoch = 0
    starting_iteration= 0

    logfile = "log/lstm_"+savestr+"_"+datetime_filename()+".txt"

    num_workers = 16
    ig = InputGenJ()
    trainds = ig.get_train()
    validds = ig.get_valid()
    testds = ig.get_test()
    validdl = DataLoader(dataset=validds, batch_size=8, num_workers=num_workers//2, collate_fn=pad_collate, shuffle=True)
    traindl = DataLoader(dataset=trainds, batch_size=8, num_workers=num_workers, collate_fn=pad_collate, shuffle=True)

    print("Using", num_workers, "workers for training set")
    # testing whether this LSTM works is basically a question whether
    lstm=lstmwrapperJ(input_size=ig.input_dim, output_size=ig.output_dim)

    # load model:
    if load:
        print("loading model")
        lstm, optim, starting_epoch, starting_iteration = load_model(lstm, optim, starting_epoch, starting_iteration, savestr)

    lstm = lstm.cuda()
    if optim is None:
        optimizer = torch.optim.Adam(lstm.parameters(), lr=lr)
    else:
        # print('use Adadelta optimizer with learning rate ', lr)
        # optimizer = torch.optim.Adadelta(computer.parameters(), lr=lr)
        optimizer = optim
        for group in optimizer.param_groups:
            print("Currently using a learing rate of ", group["lr"])

    real_criterion = TOELoss()

    # creating the positive_weights
    # with open("/infodev1/rep/projects/jason/pickle/dcc.pkl","rb") as f:
    #     # loaded here is a vector where v_i is the number of times death label i has occured
    #     weights=pickle.load(f)
    # negs=59652-weights
    # weights[weights<4]=3
    # weights=negs/weights
    # weights=torch.from_numpy(weights).float().cuda()
    # weights=Variable(weights)

    # binary_criterion = WeightedBCELLoss(pos_weight=weights)
    binary_criterion = nn.BCEWithLogitsLoss()
    # starting with the epoch after the loaded one

    train(lstm, optimizer, real_criterion, binary_criterion,
          traindl, validdl, int(starting_epoch), total_epochs,
          int(starting_iteration), iter_per_epoch, savestr, beta, ig.output_dim, logfile)



if __name__ == "__main__":
    # main(load=True
    # main(False,'lstmG')
    pass

    '''
    3/31
    This plan is created to analyze whether J's data is not processable by LSTM.
    LSTMG runs just fine, goes down below prior and more. But with the new data, somehow the loss is stuck at 0.17
    '''