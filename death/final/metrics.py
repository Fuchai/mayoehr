# The metrics are extremely important. I'm relying on them more than the loss function to evaluate the models.
# They have to be right and behave as expected.


import torch
import numpy as np
from torch.autograd import Variable
from collections import deque

class ConfusionMatrixStats():
    """
    For my usages, only sensitivity and specificity are implemented.
    Uncomment for complete confusion matrix memory and implement the statis
    """
    def __init__(self,dims,memory_len=50, string=None, test=False, AUROC_alpha=None, *args):
        """

        :param dims:
        :param memory_len:
        :param string:
        :param args: the names of the losses that you want to keep track of
        """

        self.memory_len=memory_len
        self.dims=dims
        self.string=string
        self.test=test
        self.AUROC_alpha=AUROC_alpha
        self.ruler=np.arange(0,1,AUROC_alpha)
        self.steps=self.ruler.shape[0]
        self.ruler=np.expand_dims(self.ruler, axis=1)
        self.ruler=np.repeat(self.ruler,self.dims,axis=1)
        self.ruler=np.expand_dims(self.ruler, axis=0)

        if not self.test:
            # self.positive=np.zeros(dims,memory_len)
            # self.negative=np.zeros(dims,memory_len)
            self.true_positive=np.zeros((dims,memory_len))
            self.true_negative=np.zeros((dims,memory_len))
            self.conditional_positives=np.zeros((dims,memory_len))
            self.conditional_negatives=np.zeros((dims,memory_len))
        else:
            self.true_positive=np.zeros((self.steps, dims)).astype(np.long)
            self.true_negative=np.zeros((self.steps, dims)).astype(np.long)
            self.false_positive=np.zeros((self.steps, dims)).astype(np.long)
            self.false_negative=np.zeros((self.steps, dims)).astype(np.long)
            self.conditional_positives=np.zeros((dims, )).astype(np.long)
            self.conditional_negatives=np.zeros((dims, )).astype(np.long)

        # self.running_cod_loss = deque(maxlen=memory_len)
        # self.running_toe_loss = deque(maxlen=memory_len)

        self.dequenames= args + ("cod", "toe")
        for arg in self.dequenames:
            name="running_"+arg+"_loss"
            if not self.test:
                dq=deque(maxlen=memory_len)
            else:
                dq=deque()
            self.__setattr__(name, dq)

        self.idx=0
        self.all=False

    def __str__(self):
        if self.string is not None:
            return self.string
        else:
            return super(ConfusionMatrixStats, self).__str__()

    def update_one_pass(self, output, target, *args):
        """
        record the confusion matrix statistics for each label.
        average is done on the final metrics of all labels, not before
        :param output: PyTorch 0.3.1 Variables, [0-1]
        :param target: ditto
        :return:
        """
        if not self.test:
            assert (output<=1).all()
            assert (output>=0).all()
            for dequename, loss in zip(self.dequenames, args):
                assert(not isinstance(loss, Variable))
                deque=self.__getattribute__("running_"+dequename+"_loss")
                deque.appendleft(loss)

            positive=output.data.cpu().numpy()
            conditional_positive=target.data.cpu().numpy()
            true_positive=positive*conditional_positive
            true_negative=(1-positive)*(1-conditional_positive)
            conditional_negative=1-conditional_positive

            conditional_positive=conditional_positive.sum(0)
            true_positive=true_positive.sum(0)
            true_negative=true_negative.sum(0)
            conditional_negative=conditional_negative.sum(0)

            # self.positive[:,self.idx]=positive
            # self.negative[:,self.idx]=negative
            self.conditional_positives[:,self.idx]=conditional_positive
            self.conditional_negatives[:,self.idx]=conditional_negative
            self.true_positive[:,self.idx]=true_positive
            self.true_negative[:,self.idx]=true_negative

            batch_sensitivity=np.mean(true_positive/conditional_positive.clip(1e-8,None), axis=0)
            batch_specificity=np.mean(true_negative/conditional_negative.clip(1e-8,None), axis=0)
            batch_ROC=batch_sensitivity+batch_specificity

            assert((batch_sensitivity>=0).all())
            assert((batch_sensitivity<=1).all())
            assert((batch_specificity>=0).all())
            assert((batch_specificity<=1).all())
            assert((batch_ROC>=0).all())
            assert((batch_ROC<=2).all())
            self.idx+=1
            if self.idx==self.memory_len:
                self.idx=0
                self.all=True

            return batch_sensitivity, batch_specificity, batch_ROC
        else:

            for dequename, loss in zip(self.dequenames, args):
                assert(not isinstance(loss, Variable))
                deque=self.__getattribute__("running_"+dequename+"_loss")
                deque.appendleft(loss)

            # during test time, no running stats is kept.
            assert (output<=1).all()
            assert (output>=0).all()
            assert (target<=1).all()
            assert (target>=0).all()
            output=output.detach().cpu().numpy()
            target=target.detach().cpu().numpy().astype(np.bool)
            output=np.expand_dims(output,axis=1)
            output=np.repeat(output, self.steps, axis=1)
            positive=output>self.ruler

            target_repeat=np.expand_dims(target,axis=1)
            target_repeat=np.repeat(target_repeat, self.steps, axis=1)

            true_positive=positive * target_repeat
            true_negative=np.invert(positive)*np.invert(target_repeat)
            false_positive=positive * np.invert(target_repeat)
            false_negative=np.invert(positive)*target_repeat

            true_positive=true_positive.sum(axis=0)
            true_negative=true_negative.sum(axis=0)
            false_positive=false_positive.sum(axis=0)
            false_negative=false_negative.sum(axis=0)

            conditional_positive=target.sum(axis=0)
            conditional_negative=np.invert(target).sum(axis=0)

            self.true_positive+=true_positive
            self.conditional_positives+=conditional_positive
            self.true_negative+=true_negative
            self.conditional_negatives+=conditional_negative

            self.false_positive+=false_positive
            self.false_negative+=false_negative

            self.idx+=1


    def running_stats(self):
        if not self.test:
            if self.all:
                running_sensitivity=np.mean(np.sum(self.true_positive,axis=1)/np.sum(self.conditional_positives,axis=1).clip(min=1e-8), axis=0)
                running_specificity=np.mean(np.sum(self.true_negative,axis=1)/np.sum(self.conditional_negatives,axis=1).clip(min=1e-8), axis=0)
                running_ROC=running_sensitivity+running_specificity
            else:
                running_sensitivity=np.mean(np.sum(self.true_positive[:,:self.idx],axis=1)/
                                            np.sum(self.conditional_positives[:,:self.idx],axis=1).clip(min=1e-8), axis=0)
                running_specificity=np.mean(np.sum(self.true_negative[:,:self.idx],axis=1)/
                                            np.sum(self.conditional_negatives[:,:self.idx],axis=1).clip(min=1e-8), axis=0)
                running_ROC=running_sensitivity+running_specificity
            assert((running_sensitivity>=0).all())
            assert((running_sensitivity<=1).all())
            assert((running_specificity>=0).all())
            assert((running_specificity<=1).all())
            assert((running_ROC>=0).all())
            assert((running_ROC<=2).all())

            return running_sensitivity, running_specificity, running_ROC

        else:
            sens=self.true_positive/self.conditional_positives.clip(min=1e-8)
            spec=self.true_negative/self.conditional_negatives.clip(min=1e-8)

            return sens.mean(), spec.mean(), spec.mean()+sens.mean()


    def running_loss(self):
        if len(self.running_cod_loss)==0:
            return (0,)*len(self.dequenames)
        else:
            # deque=self.__getattribute__("running_"+dequename+"_loss")
            return tuple(np.mean(self.__getattribute__("running_"+dq+"_loss")) for dq in self.dequenames)
            #np.mean(self.running_cod_loss), np.mean(self.running_toe_loss)


def sensitivity(output, target):
    # TODO I do not think these formula are correct either.
    # Confusion matrix always lose information if projected to these statistics
    '''
    Because batches have varied number of positive labels, we must keep that information for weighted averages.

    :param target: np array of bool
    :param output: np array of float
    :return:
    batch sensitivity
    true positive and positive are needed, because not all batches have the same positive counts
    '''

    # target is one

    truepositive=target*output
    condition_positive=target
    condition_positive=condition_positive.clamp(min=1e-8)

    sensitivity_for_each_class=truepositive/condition_positive
    # across batch dimension
    batch_sensitivity=torch.mean(sensitivity_for_each_class,dim=0)

    return batch_sensitivity.data[0], truepositive.data.numpy(), condition_positive.data.numpy()

def specificity(output, target):
    truenegative=(1-target)*(1-output)
    condition_negative=1-target
    condition_negative=condition_negative.clamp(min=1e-8)

    specificity_for_each_class=truenegative/condition_negative
    batch_specificity=torch.mean(specificity_for_each_class)

    return batch_specificity.data[0], truenegative.data.numpy(), condition_negative.data.numpy()


def precision(output, target):
    truepositive = output * target
    positives = output

    batch_precision = torch.mean(truepositive / positives)

    return batch_precision

def recall(output, target):
    return sensitivity(output, target)


def f1score(output, target):
    # lol where did I get this formula before?
    rec=recall(output,target)
    if rec<1e-6:
        rec=1e-6
    prec=precision(output,target)
    if prec<1e-6:
        prec=1e-6
    f1=1/((1/rec+1/prec)/2)
    return f1

def accuracy(output,target):
    truepositive=torch.sum(output*target).data[0]
    truenegative=torch.sum((1-target)*(1-output)).data[0]
    inc=target.nelement()

    return (truenegative+truepositive)/inc

def smalltest():
    target=Variable(torch.Tensor([1,1,1,1,0,0]))
    output=Variable(torch.Tensor([0,1,1,1,1,0]))
    # sensitivity: 75%
    # specificity: 50%
    # precision: 75%

    print(sensitivity(target,output))
    print(specificity(target,output))
    print(precision(target,output))


if __name__=="__main__":
    smalltest()
