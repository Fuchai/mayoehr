# parameters for this task
import archi.param as param
from archi.computer import Computer
import torch
import numpy
import archi.param as param
import pdb
from pathlib import Path
import os
from os.path import abspath
from traversal.datagen import PreGenData

param.x=92
param.v_t=90
param.bs=64

diff=1


class dummy_context_mgr():
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def save_model(net, optim, epoch):
    epoch = int(epoch)
    task_dir = os.path.dirname(abspath(__file__))
    pickle_file = Path(task_dir).joinpath("saves/DNCfull_" + str(epoch) + ".pkl")
    pickle_file = pickle_file.open('wb')
    torch.save((net, optim, epoch), pickle_file)


def load_model(computer):
    task_dir = os.path.dirname(abspath(__file__))
    save_dir = Path(task_dir) / "saves"
    highestepoch = -1
    for child in save_dir.iterdir():
        epoch = str(child).split("_")[2].split('.')[0]
        epoch = int(epoch)
        # some files are open but not written to yet.
        if epoch > highestepoch and child.stat().st_size > 2048:
            highestepoch = epoch
    if highestepoch == -1:
        return computer, None, -1
    pickle_file = Path(task_dir).joinpath("saves/DNCfull_" + str(highestepoch) + ".pkl")
    print("loading model at ", pickle_file)
    pickle_file = pickle_file.open('rb')
    model, optim, epoch = torch.load(pickle_file)

    print('Loaded model at epoch ', highestepoch)

    for child in save_dir.iterdir():
        epoch = str(child).split("_")[1].split('.')[0]
        if int(epoch) != highestepoch:
            os.remove(child)
    print('Removed incomplete save file and all else.')

    return model, optim, epoch


def save_model_old(net, optim, epoch):
    state_dict = net.state_dict()
    for key in state_dict.keys():
        state_dict[key] = state_dict[key].cpu()
    task_dir = os.path.dirname(abspath(__file__))
    print(task_dir)
    pickle_file = Path("../saves/DNC_" + str(epoch) + ".pkl")
    pickle_file = pickle_file.open('wb')

    torch.save({
        'epoch': epoch,
        'state_dict': state_dict,
        'optimizer': optim},
        pickle_file)


def load_model_old(net):
    task_dir = os.path.dirname(abspath(__file__))
    save_dir = Path(task_dir).parent / "saves"
    highestepoch = -1
    for child in save_dir.iterdir():
        epoch = str(child).split("_")[1].split('.')[0]
        # some files are open but not written to yet.
        if int(epoch) > highestepoch and child.stat().st_size > 2048:
            highestepoch = int(epoch)
    pickle_file = Path("../saves/DNC_" + str(highestepoch) + ".pkl")
    pickle_file = pickle_file.open('rb')
    ret = torch.load(pickle_file)

    net.load_state_dict(ret['state_dict'])
    print('Loaded model at epoch ', highestepoch)

    for child in save_dir.iterdir():
        epoch = str(child).split("_")[1].split('.')[0]
        if int(epoch) != highestepoch:
            os.remove(child)
    print('Removed incomplete save file and all else.')

    return ret['epoch'], ret['optimizer']


def run_one_story(computer, optimizer, difficulty, batch_size, pgd, validate=False):
    # this variable needs to correspond to Datagen class definition on travlen
    seq_len=difficulty*8

    # to promote code reuse
    if not validate:
        input_data, target_output, critical_index = pgd.get_train()
    else:
        input_data, target_output, critical_index = pgd.get_validate()

    input_data = torch.Tensor(input_data).cuda()
    target_output = torch.Tensor(target_output).cuda()
    stairs = torch.Tensor(numpy.arange(0, param.bs * seq_len, seq_len))
    critical_index = critical_index + stairs.unsqueeze(1)
    critical_index = critical_index.view(-1)
    critical_index = critical_index.long().cuda()

    criterion = torch.nn.CrossEntropyLoss()

    with torch.no_grad if validate else dummy_context_mgr():

        story_output = torch.Tensor(batch_size, seq_len, param.v_t).cuda()
        computer.new_sequence_reset()
        # a single story
        for timestep in range(seq_len):
            # feed the batch into the machine
            batch_input_of_same_timestep = input_data[:, timestep, :]

            # usually batch does not interfere with each other's logic
            batch_output = computer(batch_input_of_same_timestep)
            if torch.isnan(batch_output).any():
                pdb.set_trace()
                raise ValueError("nan is found in the batch output.")
            story_output[:, timestep, :] = batch_output

        target_output = target_output.view(-1,9)
        story_output = story_output.view(-1, param.v_t)
        story_output = story_output[critical_index, :]
        target_output = target_output[critical_index,:].long()

        story_output=story_output.view(-1,10)
        target_output=target_output.view(-1)

        story_loss = criterion(story_output, target_output)

        pred=torch.argmax(story_output,dim=1)
        correct=torch.sum(pred==target_output)
        precision=float(correct)/target_output.size()[0]
        if precision>0.9:
            difficulty+=1
        if not validate:
            # I chose to backward a derivative only after a whole story has been taken in
            # This should lead to a more stable, but initially slower convergence.
            story_loss.backward()
            optimizer.step()

    return story_loss,precision


def train(computer, optimizer, difficulty, batch_size, pgd, starting_epoch):
    for epoch in range(starting_epoch, epochs_count):

        running_loss = 0
        running_prec=0

        for batch in range(epoch_batches_count):

            train_story_loss,precision = run_one_story(computer, optimizer, difficulty, batch_size, pgd)
            print("learning. epoch: %4d, batch number: %4d, training loss: %.4f, precision: %.4f" %
                  (epoch, batch, train_story_loss.item(),precision))
            running_loss += train_story_loss
            running_prec+=precision
            val_freq = 16
            if batch % val_freq == val_freq - 1:
                print('summary.  epoch: %4d, batch number: %4d, running loss: %.4f, running prec: %.4f' %
                      (epoch, batch, running_loss / val_freq, running_prec/val_freq))
                running_loss = 0
                running_prec=0
                # also test the model
                val_loss,precision = run_one_story(computer, optimizer, difficulty, batch_size, pgd, validate=False)
                print('validate. epoch: %4d, batch number: %4d, validation loss: %.4f, precision: %.4f' %
                      (epoch, batch, val_loss, precision))

        save_model(computer, optimizer, epoch)
        print("model saved for epoch ", epoch)


if __name__ == "__main__":

    epoch_batches_count = 64
    epochs_count = 1024
    lr = 1e-7
    starting_epoch = -1
    difficulty=1
    param.x = 92
    param.v_t = 90
    param.bs=64



    pgd = PreGenData(param.bs)
    computer = Computer()
    optim = None
    # if load model
    # computer, optim, starting_epoch = load_model(computer)

    computer = computer.cuda()
    if optim is None:
        optimizer = torch.optim.Adam(computer.parameters(), lr=lr)
    else:
        print('use Adadelta optimizer with learning rate ', lr)
        optimizer = torch.optim.Adadelta(computer.parameters(), lr=lr)

    # starting with the epoch after the loaded one
    train(computer, optimizer, difficulty, param.bs, pgd, int(starting_epoch) + 1)
