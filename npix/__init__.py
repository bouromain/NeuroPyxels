# -*- coding: utf-8 -*-

from . import utils, io, gl, spk_t, spk_wvf, corr, plot, ml, behav, circuitProphyler, stats

import os, sys

import numpy as np
import scipy as sp
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import seaborn as sns

from .utils import phyColorsDic, seabornColorsDic, DistinctColors20, DistinctColors15, mpl_colors, mark_dict,\
                    npa, sign, minus_is_1, thresh, smooth, zscore, \
                    _as_array, _unique, _index_of

__doc__="""

npix submodules:
    npix.utils

    npix.io
    
    npix.gl
    
    npix.spk_t
    
    npix.spk_wvf
    
    npix.corr
    
    npix.plot
    
    npix.ml
    
    npix.behav

    npix.stats
"""