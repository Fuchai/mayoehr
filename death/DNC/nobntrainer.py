import pandas as pd
import torch
import numpy as np
import pdb
from pathlib import Path
import os
from os.path import abspath
from death.post.inputgen_planG import InputGenG, pad_collate
from death.post.inputgen_planH import InputGenH
from death.DNC.nobnDNC import SeqDNC
from torch.utils.data import DataLoader
import torch.nn as nn
from torch.nn.modules import LSTM
from torch.autograd import Variable
import pickle
from shutil import copy
import traceback
from collections import deque
import datetime
from death.DNC.tsDNCtrainer import logprint
import pdb
from death.final.losses import TOELoss, WeightedBCELLoss
from death.final.killtime import out_of_time

param_x = 66529
param_h = 64  # 64
param_L = 4  # 4
param_v_t = 2976 # 5952
param_W = 8  # 8
param_R = 8  # 8
param_N = 64  # 64
param_bs = 8
# this is the empirical saturation level when positive weights are not used.
saturation=20000
val_bat_cons=800

import torch.multiprocessing

torch.multiprocessing.set_sharing_strategy('file_system')


def datetime_filename():
    return datetime.datetime.now().strftime("%m_%d_%X")


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
    pickle_file = Path(task_dir).joinpath("saves/" + savestr + "/seqDNC_" + str(epoch) + "_" + str(iteration) + ".pkl")
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
    if starting_epoch==0 and starting_iteration==0:
        pickle_file = Path(task_dir).joinpath(
            "saves/" + savestr + "/seqDNC_" + str(highestepoch) + "_" + str(highestiter) + ".pkl")
    else:
        pickle_file = Path(task_dir).joinpath(
            "saves/" + savestr + "/seqDNC_" + str(starting_epoch) + "_" + str(starting_iteration) + ".pkl")
    print("loading model at", pickle_file)
    with pickle_file.open('rb') as pickle_file:
        computer, optim, epoch, iteration = torch.load(pickle_file)
    print('Loaded model at epoch ', highestepoch, 'iteration', iteration)

    return computer, optim, highestepoch, highestiter

global_exception_counter = 0


def run_one_patient(computer, input, target, optimizer, loss_type, real_criterion,
                    binary_criterion, beta, validate=False):
    global global_exception_counter
    patient_loss = None
    try:
        optimizer.zero_grad()

        input = Variable(torch.Tensor(input).cuda())
        target = Variable(torch.Tensor(target).cuda())
        loss_type = Variable(torch.Tensor(loss_type).cuda())

        # we have no critical index, becuase critical index are those timesteps that
        # DNC is required to produce outputs. This is not the case for our project.
        # criterion does not need to be reinitiated for every story, because we are not using a mask

        patient_output = computer(input)
        cause_of_death_output = patient_output[:, 1:]
        cause_of_death_target = target[:, 1:]
        # pdb.set_trace()
        cod_loss = binary_criterion(cause_of_death_output, cause_of_death_target)

        toe_output=patient_output[:,0]
        toe_target=target[:,0]
        toe_loss=real_criterion(toe_output,toe_target,loss_type)

        total_loss=cod_loss+beta*toe_loss

        if not validate:
            total_loss.backward()
            optimizer.step()

        if global_exception_counter > -1:
            global_exception_counter -= 1
    except ValueError:
        traceback.print_exc()
        print("Value Error reached")
        print(datetime.datetime.now().time())
        global_exception_counter += 1
        if global_exception_counter == 10:
            save_model(computer, optimizer, epoch=0, iteration=global_exception_counter)
            raise ValueError("Global exception counter reached 10. Likely the model has nan in weights")
        else:
            pass

    return float(cod_loss.data), float(toe_loss.data)


def train(computer, optimizer, real_criterion, binary_criterion,
          train, valid_dl, starting_epoch, total_epochs, starting_iter, iter_per_epoch, savestr, beta, logfile=False):
    valid_iterator = iter(valid_dl)
    print_interval = 10
    val_interval = 400
    save_interval = int(8000/param_bs)
    target_dim = None
    rldmax_len = 50
    val_batch = int(val_bat_cons/param_bs)
    running_cod_loss=deque(maxlen=rldmax_len)
    running_toe_loss=deque(maxlen=rldmax_len)
    if logfile:
        open(logfile, 'w').close()

    for name, param in computer.named_parameters():
        logprint(logfile, name)
        logprint(logfile, param.data.shape)

    for epoch in range(starting_epoch, total_epochs):
        for i, (input, target, loss_type) in enumerate(train):
            i = starting_iter + i
            out_of_time()

            if target_dim is None:
                target_dim = target.shape[1]

            if i < iter_per_epoch:
                cod_loss, toe_loss = run_one_patient(computer, input, target, optimizer, loss_type,
                                                   real_criterion, binary_criterion, beta)
                total_loss=cod_loss+toe_loss
                running_cod_loss.appendleft(cod_loss)
                running_toe_loss.appendleft(toe_loss)
                if i % print_interval == 0:
                    running_cod=np.mean(running_cod_loss)
                    running_toe=np.mean(running_toe_loss)
                    logprint(logfile,
                             "batch %4d. batch cod: %.5f, toe: %.5f, total: %.5f. running cod: %.5f, toe: %.5f, total: %.5f" %
                             (i, cod_loss, toe_loss, cod_loss + beta*toe_loss, running_cod, running_toe,
                              running_cod + beta*running_toe))

                if i % val_interval == 0:
                    total_cod=0
                    total_toe=0
                    for _ in range(val_batch):
                        # we should consider running validation multiple times and average. TODO
                        try:
                            (input, target, loss_type) = next(valid_iterator)
                        except StopIteration:
                            valid_iterator = iter(valid_dl)
                            (input, target, loss_type) = next(valid_iterator)

                        cod_loss, toe_loss = run_one_patient(computer, input, target, optimizer, loss_type,
                                                   real_criterion, binary_criterion, beta, validate=True)
                        total_cod+=cod_loss
                        total_toe+=toe_loss
                    total_cod=total_cod/val_batch
                    total_toe=total_toe/val_batch
                    # TODO this validation is not printing correctly. Way too big.
                    logprint(logfile, "validation. cod: %.10f, toe: %.10f, total: %.10f" %
                             (total_cod, total_toe, total_cod + beta*total_toe))


                if i % save_interval == 0:
                    save_model(computer, optimizer, epoch, i, savestr)
                    print("model saved for epoch", epoch, "input", i)
            else:
                break


def validationonly(savestr, beta, epoch=0, iteration=0):
    """

    :param savestr:
    :param epoch: default to 0 if loading the highest model
    :param iteration: ditto
    :return:
    """

    lr = 1e-3
    optim = None
    logfile = "vallog.txt"

    num_workers = 8
    ig = InputGenH()
    # multiprocessing disabled, because socket request seems unstable.
    # performance should not be too bad?
    validds=ig.get_valid()
    validdl = DataLoader(dataset=validds,num_workers=num_workers, batch_size=param_bs, collate_fn=pad_collate)
    valid_iterator=iter(validdl)

    print("Using", num_workers, "workers for validation set")
    computer = SeqDNC(x=param_x,
                      h=param_h,
                      L=param_L,
                      v_t=param_v_t,
                      W=param_W,
                      R=param_R,
                      N=param_N,
                      bs=param_bs)
    # load model:
    print("loading model")
    computer, optim, starting_epoch, starting_iteration = load_model(computer, optim, epoch, iteration, savestr)

    computer = computer.cuda()

    real_criterion = nn.SmoothL1Loss()
    binary_criterion = nn.BCEWithLogitsLoss()

    # starting with the epoch after the loaded one
    running_loss=[]
    valid_batches=500
    for i in range(valid_batches):
        input, target, loss_type = next(valid_iterator)
        val_loss = run_one_patient(computer, input, target, None, None, loss_type,
                                   real_criterion, binary_criterion, beta, validate=True)
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

def main(load, savestr='default', lr=1e-3, beta=0.01):
    """
    :param load:
    :param savestr:
    :param lr:
    :param curri:
    :return:
    """


    total_epochs = 1
    iter_per_epoch = int(saturation/param_bs)
    optim = None
    starting_epoch = 0
    starting_iteration = 0
    logfile = "log/dnc_" + savestr + "_" + datetime_filename() + ".txt"

    num_workers = 16
    # ig=InputGenG(small_target=True)
    ig = InputGenH(small_target=True)
    trainds = ig.get_train()
    validds = ig.get_valid()
    traindl = DataLoader(dataset=trainds, batch_size=param_bs, num_workers=num_workers, collate_fn=pad_collate,pin_memory=True)
    validdl = DataLoader(dataset=validds, batch_size=param_bs, num_workers=num_workers//2, collate_fn=pad_collate,pin_memory=True)

    print("Using", num_workers, "workers for training set")
    computer = SeqDNC(x=param_x,
                      h=param_h,
                      L=param_L,
                      v_t=param_v_t,
                      W=param_W,
                      R=param_R,
                      N=param_N)
    # load model:
    if load:
        print("loading model")
        computer, optim, starting_epoch, starting_iteration = load_model(computer, optim, starting_epoch,
                                                                         starting_iteration, savestr)

    computer = computer.cuda()
    if optim is None:
        optimizer = torch.optim.Adam(computer.parameters(), lr=lr)
    else:
        # print('use Adadelta optimizer with learning rate ', lr)
        # optimizer = torch.optim.Adadelta(computer.parameters(), lr=lr)
        optimizer = optim
        for group in optimizer.param_groups:
            print("Currently using a learing rate of ", group["lr"])

    # creating the positive_weights
    with open("/infodev1/rep/projects/jason/pickle/dcc.pkl","rb") as f:
        # loaded here is a vector where v_i is the number of times death label i has occured
        weights=pickle.load(f)
    negs=59652-weights
    weights[weights<4]=3
    weights=negs/weights
    weights=torch.from_numpy(weights).float().cuda()
    weights=Variable(weights)

    real_criterion = TOELoss()
    # this parameter does not appear in PyTorch 0.3.1
    binary_criterion = WeightedBCELLoss(pos_weight=weights)
    # starting with the epoch after the loaded one

    train(computer, optimizer, real_criterion, binary_criterion,
          traindl, validdl, int(starting_epoch), total_epochs,
          int(starting_iteration), iter_per_epoch, savestr, beta, logfile)


if __name__ == "__main__":
    main(False)

    """
    1/7
    This file has nan problem
    """