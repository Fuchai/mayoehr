'''Opens DNCcrash.pkl'''

import torch
import numpy as np
from pathlib import Path
import os
from os.path import abspath
from death.post.inputgen_planD import InputGenD, train_valid_split
from torch.utils.data import DataLoader
import torch.nn as nn
from death.DNC.trashcan.frankenstein import Frankenstein as DNC
from torch.autograd import Variable
import traceback
from collections import deque
import datetime

batch_size = 1

class dummy_context_mgr():
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc_value, traceback):
        return False

def save_model(net, optim, epoch, iteration):
    epoch = int(epoch)
    task_dir = os.path.dirname(abspath(__file__))
    pickle_file = Path(task_dir).joinpath("saves/DNCfull_" + str(epoch) +  "_" + str(iteration) + ".pkl")
    pickle_file = pickle_file.open('wb')
    torch.save((net,  optim, epoch, iteration), pickle_file)
    print('model saved at', pickle_file)

def load_model(computer, optim, starting_epoch, starting_iteration):
    task_dir = os.path.dirname(abspath(__file__))
    pickle_file = Path(task_dir).joinpath("saves/DNCNA_0_235.pkl")
    print("loading model at", pickle_file)
    pickle_file = pickle_file.open('rb')
    computer, optim, epoch, iteration = torch.load(pickle_file)

    return computer, optim, epoch, iteration


global_exception_counter=0
def run_one_patient(computer, input, target, target_dim, optimizer, loss_type, real_criterion,
                    binary_criterion, validate=False):
    global global_exception_counter
    patient_loss=None
    try:
        optimizer.zero_grad()
        input = Variable(torch.Tensor(input).cuda())
        target = Variable(torch.Tensor(target).cuda())

        # we have no critical index, becuase critical index are those timesteps that
        # DNC is required to produce outputs. This is not the case for our project.
        # criterion does not need to be reinitiated for every story, because we are not using a mask

        time_length = input.size()[1]
        # with torch.no_grad if validate else dummy_context_mgr():
        patient_output = Variable(torch.Tensor(1, time_length, target_dim)).cuda()
        for timestep in range(time_length):
            # first colon is always size 1
            feeding = input[:, timestep, :]
            output = computer(feeding)
            assert not (output != output).any()
            patient_output[0, timestep, :] = output

        # patient_output: (batch_size 1, time_length, output_dim ~4000)
        time_to_event_output = patient_output[:, :, 0]
        cause_of_death_output = patient_output[:, :, 1:]
        time_to_event_target = target[:, :, 0]
        cause_of_death_target = target[:, :, 1:]

        # this block will not work for batch input,
        # you should modify it so that the loss evaluation is not determined by logic but function.
        # def toe_loss_calc(real_criterion,time_to_event_output,time_to_event_target, patient_length):
        #
        # if loss_type[0] == 0:
        #     # in record
        #     toe_loss = real_criterion(time_to_event_output, time_to_event_target)
        #     cod_loss = binary_criterion(cause_of_death_output, cause_of_death_target)
        #     patient_loss = toe_loss/100 + cod_loss
        # else:
        #     # not in record
        #     # be careful with the sign, penalize when and only when positive
        #     underestimation = time_to_event_target - time_to_event_output
        #     underestimation = nn.functional.relu(underestimation)
        #     toe_loss = real_criterion(underestimation, torch.zeros_like(underestimation).cuda())
        #     cod_loss = binary_criterion(cause_of_death_output, cause_of_death_target)
        #     patient_loss = toe_loss/100 + cod_loss
        patient_loss= binary_criterion(cause_of_death_output, cause_of_death_target)

        if not validate:
            patient_loss.backward()
            optimizer.step()

        if global_exception_counter>-1:
            global_exception_counter-=1
    except ValueError:
        traceback.print_exc()
        print("Value Error reached")
        print(datetime.datetime.now().time())
        global_exception_counter+=1
        if global_exception_counter==10:
            save_model(computer,optimizer,epoch=0,iteration=np.random.randint(0,1000))
            raise ValueError("Global exception counter reached 10. Likely the model has nan in weights")
        else:
            pass

    return patient_loss


def train(computer, optimizer, real_criterion, binary_criterion,
          train, valid_iterator, starting_epoch, total_epochs, starting_iter, iter_per_epoch, logfile=False):
    print_interval=10
    val_interval=50
    save_interval=100
    target_dim=None
    rldmax_len=50
    running_loss_deque=deque(maxlen=rldmax_len)
    if logfile:
        open(logfile, 'w').close()

    for epoch in range(starting_epoch, total_epochs):
        for i, (input, target, loss_type) in enumerate(train):
            i=starting_iter+i
            if target_dim is None:
                target_dim=target.shape[2]

            if i < iter_per_epoch:
                train_story_loss = run_one_patient(computer, input, target, target_dim, optimizer, loss_type,
                                                   real_criterion, binary_criterion)
                if train_story_loss is not None:
                    printloss=float(train_story_loss[0])
                else:
                    printloss=10000
                computer.new_sequence_reset()
                del input, target, loss_type
                running_loss_deque.appendleft(printloss)
                if i % print_interval == 0:
                    running_loss=np.mean(running_loss_deque)
                    if logfile:
                        with open(logfile, 'a') as handle:
                            handle.write("learning.   count: %4d, training loss: %.10f \n" %
                                         (i, printloss))
                    print("learning.   count: %4d, training loss: %.10f" %
                          (i, printloss))
                    if i!=0:
                        print("count: %4d, running loss: %.10f" % (i, running_loss))

                if i % val_interval == 0:
                    # we should consider running validation multiple times and average. TODO
                    (input,target,loss_type)=next(valid_iterator)
                    val_loss = run_one_patient(computer, input, target, target_dim, optimizer, loss_type,
                                                   real_criterion, binary_criterion, validate=True)
                    if val_loss is not None:
                        printloss = float(val_loss[0])
                    if logfile:
                        with open(logfile, 'a') as handle:
                            handle.write("validation. count: %4d, val loss     : %.10f \n" %
                                         (i, printloss))
                    print("validation. count: %4d, training loss: %.10f" %
                          (i, printloss))

                if i % save_interval == 0:
                    save_model(computer, optimizer, epoch, i)
                    print("model saved for epoch", epoch, "input", i)
            else:
                break

def forevermain():
    print("Will run main() forever in a loop.")
    while True:
        try:
            main(True)
        except ValueError:
            pass


def probe():
    total_epochs = 10
    iter_per_epoch = 100000
    lr = 1e-3
    optim = None
    starting_epoch = 0
    starting_iteration= 0
    logfile = "log.txt"

    num_workers = 3
    ig = InputGenD()
    # multiprocessing disabled, because socket request seems unstable.
    # performance should not be too bad?
    trainds,validds=train_valid_split(ig,split_fold=10)
    traindl = DataLoader(dataset=trainds, batch_size=1, num_workers=num_workers)
    validdl = DataLoader(dataset=validds, batch_size=1)
    print("Using", num_workers, "workers for training set")
    computer=DNC()

    # load model:
    print("loading model")
    computer, optim, starting_epoch, starting_iteration = load_model(computer, optim, starting_epoch, starting_iteration)

    computer = computer.cuda()
    if optim is None:
        optimizer = torch.optim.Adam(computer.parameters(), lr=lr)
    else:
        # print('use Adadelta optimizer with learning rate ', lr)
        # optimizer = torch.optim.Adadelta(computer.parameters(), lr=lr)
        optimizer = optim

    real_criterion = nn.SmoothL1Loss()
    binary_criterion = nn.BCEWithLogitsLoss(size_average=False)

    # starting with the epoch after the loaded one

    train(computer, optimizer, real_criterion, binary_criterion,
          traindl, iter(validdl), int(starting_epoch), total_epochs,int(starting_iteration), iter_per_epoch, logfile)


if __name__ == "__main__":
    with torch.cuda.device(1):
        probe()
