###############################################################################
# Language Modeling on Penn Tree Bank
#
# This file generates new sentences sampled from the language model
#
###############################################################################

import os
import math

import argparse

import torch
from torch.autograd import Variable

from apex.reparameterization import apply_weight_norm, remove_weight_norm

import model

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
sns.set_style({'font.family': 'monospace'})

def get_neuron_and_polarity(sd, neuron):
    """return a +/- 1 indicating the polarity of the specified neuron in the module"""
    if neuron == -1:
        neuron = None
    if 'classifier' in sd:
        sd = sd['classifier']
        if 'weight' in sd:
            weight = sd['weight']
        else:
            return neuron, 1
    else:
        return neuron, 1
    if neuron is None:
        val, neuron = torch.max(torch.abs(weight[0].float()), 0)
        # IndexError: invalid index of a 0-dim tensor. Use tensor.item() to convert a 0-dim tensor to a Python number
        #neuron = neuron.item[0]
        neuron = neuron.item()
    val = weight[0][neuron]
    if val >= 0:
        polarity = 1
    else:
        polarity = -1
    return neuron, polarity

def process_hidden(cell, hidden, neuron, mask=False, mask_value=1, polarity=1):
    feat = cell.data[:, neuron]
    rtn_feat = feat.clone()
    if mask:
#        feat.fill_(mask_value*polarity)
        hidden.data[:, neuron].fill_(mask_value*polarity)
    return rtn_feat[0]

def model_step(model, input, neuron=None, mask=False, mask_value=1, polarity=1):
    out, _ = model(input)
    if neuron is not None:
        hidden = model.rnn.rnns[-1].hidden
        if len(hidden) > 1:
            hidden, cell = hidden
        else:
            hidden = cell = hidden
        feat = process_hidden(cell, hidden, neuron, mask, mask_value, polarity)
        return out, feat
    return out

def sample(out, temperature):
    if temperature == 0:
        char_idx = torch.max(out.squeeze().data, 0)[1][0]
    else:
        word_weights = out.float().squeeze().data.div(temperature).exp().cpu()
        char_idx = torch.multinomial(word_weights, 1)[0]
    return char_idx

def process_text(text, model, input, temperature, neuron=None, mask=False, overwrite=1, polarity=1):
    chrs = []
    vals = []
    for c in text:
        input.data.fill_(int(ord(c)))
        if neuron:
            ch, val = model_step(model, input, neuron, mask, overwrite, polarity)
            vals.append(val)
        else:
            ch = model_step(model, input, neuron, mask, overwrite, polarity)
#        ch = sample(ch, temperature)
    input.data.fill_(sample(ch, temperature))
    chrs = list(text)
#    chrs.append(chr(ch))
    return chrs, vals

def make_heatmap(text, values, save=None, polarity=1):
    cell_height=.325
    cell_width=.15
    n_limit = 74
    text = list(map(lambda x: x.replace('\n', '\\n'), text))
    num_chars = len(text)
    total_chars = math.ceil(num_chars/float(n_limit))*n_limit
    mask = np.array([0]*num_chars + [1]*(total_chars-num_chars))
    text = np.array(text+[' ']*(total_chars-num_chars))
    values = np.array(values+[0]*(total_chars-num_chars))
    values *= polarity

    # error again
    values = np.array([value.item() if type(value) != int else value for value in values])

    values = values.reshape(-1, n_limit)
    text = text.reshape(-1, n_limit)
    mask = mask.reshape(-1, n_limit)
    num_rows = len(values)
    plt.figure(figsize=(cell_width*n_limit, cell_height*num_rows))
    hmap=sns.heatmap(values, annot=text, mask=mask, fmt='', vmin=-1, vmax=1, cmap='RdYlGn',
                     xticklabels=False, yticklabels=False, cbar=False)
    plt.tight_layout()
    if save is not None:
        plt.savefig(save)
    # clear plot for next graph since we returned `hmap`
    plt.clf()
    return hmap

class Sentiment:
    def __init__(self, load_model, visualize):
        self.data_size = 256
        self.seed = -1
        self.model_nn = 'mLSTM'
        self.emsize = 64
        self.nhid = 4096
        self.nlayers = 1
        self.dropout = 0.0
        self.tied = False
        self.neuron = -1
        self.overwrite = None
        self.temperature = 1
        self.visualize = visualize
        self.gen_length = 0
        # Load the model
        self.load_model = load_model

    def initialize(self):
        
        cuda = torch.cuda.is_available()

        self.model_test = model.RNNModel(self.model_nn, self.data_size, self.emsize, self.nhid, self.nlayers, self.dropout, self.tied)
        
        if cuda:
            self.model_test.cuda()

        with open(self.load_model, 'rb') as f:
            self.sd = torch.load(f)

        try:
            self.model_test.load_state_dict(self.sd)
            print('Model loaded state dict')
        except:
            apply_weight_norm(self.model_test.rnn)
            self.model_test.load_state_dict(sd)
            remove_weight_norm(self.model_test)
        
        # Get the neuron and polarity
        self.neuron, self.polarity = get_neuron_and_polarity(self.sd, self.neuron)
        self.neuron = self.neuron if self.visualize or self.overwrite is not None else None
        self.mask = self.overwrite is not None

        # model_test train ?   
        self.model_test.eval()
        
        # Computing

        self.hidden = self.model_test.rnn.init_hidden(1)
        self.input = Variable(torch.LongTensor([int(ord('\n'))]))

        if cuda:
            self.input = self.input.cuda()

        self.input = self.input.view(1,1).contiguous()
        model_step(self.model_test, self.input, self.neuron, self.mask, self.overwrite, self.polarity)
        self.input.data.fill_(int(ord(' ')))
        out = model_step(self.model_test, self.input, self.neuron, self.mask, self.overwrite, self.polarity)
        if self.neuron is not None:
            out = out[0]
        self.input.data.fill_(sample(out, self.temperature))

        print(self.input)
        
    def process(self, text):
        outchrs = []
        outvals = []

        with torch.no_grad():
            
            chrs, vals = process_text(text, self.model_test, self.input, self.temperature, self.neuron, self.mask, self.overwrite, self.polarity)
            outchrs += chrs
            outvals += vals


            outstr = ''.join(outchrs)
            # Get each val
            outvals_list = [val.item() if type(val) != int else val for val in outvals]

            #make_heatmap(outstr, outvals, 'test')

        return outvals                                                            