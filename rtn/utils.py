# -*- coding: utf-8 -*-

import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt

from six import integer_types
from statsmodels.nonparametric.smoothers_lowess import lowess
import logging
from math import pi, log
import pylab
from scipy import fft, ifft
from scipy.optimize import curve_fit
from scipy.signal import cspline1d_eval, cspline1d

#%% Colors dictionnaries

phyColorsDic = {
    0:(53./255, 127./255, 255./255),
    1:(255./255, 0./255, 0./255),
    2:(255./255,215./255,0./255),
    3:(238./255, 53./255, 255./255),
    4:(84./255, 255./255, 28./255),
    5:(255./255,165./255,0./255),
    -1:(0., 0., 0.),
    }

seabornColorsDic = {
    0:sns.color_palette()[0],
    1:sns.color_palette()[1],
    2:sns.color_palette()[2],
    3:sns.color_palette()[3],
    4:sns.color_palette()[4],
    5:sns.color_palette()[5],
    6:sns.color_palette()[6],
    7:sns.color_palette()[7],
    8:sns.color_palette()[8],
    9:sns.color_palette()[9]
    }

mpl_colors=plt.rcParams['axes.prop_cycle'].by_key()['color']

DistinctColors20 = [(127,127,127),(0,0,143),(182,0,0),(0,140,0),(195,79,255),(1,165,202),(236,157,0),(118,255,0),(255,127,0),
    (255,117,152),(148,0,115),(0,243,204),(72,83,255),(0,127,255),(0,67,1),(237,183,255),(138,104,0),(97,0,163),(92,0,17),(255,245,133)]
DistinctColors20 = [(c[0]/255, c[1]/255, c[2]/255) for c in DistinctColors20]
DistinctColors15 = [(127,127,127),(255,255,0),(0,0,143),(255,0,0),(50,255,255),(255,0,255),(94,0,33),(0,67,0),
    (255,218,248),(0,178,0),(124,72,255),(211,145,0),(5,171,253),(126,73,0),(147,0,153)]
DistinctColors15 = [(c[0]/255, c[1]/255, c[2]/255) for c in DistinctColors15]

mark_dict = {
".":"point",
",":"pixel",
"o":"circle",
"v":"triangle_down",
"^":"triangle_up",
"<":"triangle_left",
">":"triangle_right",
"1":"tri_down",
"2":"tri_up",
"3":"tri_left",
"4":"tri_right",
"8":"octagon",
"s":"square",
"p":"pentagon",
"*":"star",
"h":"hexagon1",
"H":"hexagon2",
"+":"plus",
"D":"diamond",
"d":"thin_diamond",
"|":"vline",
"_":"hline"
}
                          

#%% Utils

_ACCEPTED_ARRAY_DTYPES = (np.float, np.float32, np.float64,
                          np.int, np.int8, np.int16, np.uint8, np.uint16,
                          np.int32, np.int64, np.uint32, np.uint64,
                          np.bool)

def npa(arr=[], **kwargs):
    '''Returns np.array(param).
    Optional aprams:
        - zeros: tuple. If provided, returns np.zeros(zeros)
        - ones: tuple. If provided, returns np.ones(ones)
        - empty: tuple. If provided, returns np.empty(empty)
        - dtype: numpy datatype. If provided, returns np.array(arr, dtype=dtype) .'''
    if 'zeros' in kwargs.keys():
        arr = np.zeros(kwargs['zeros'])
    elif 'ones' in kwargs.keys():
        arr = np.ones(kwargs['ones'])
    elif 'empty' in kwargs.keys():
        arr = np.empty(kwargs['empty'])
    else:
        arr=np.array(arr)
    if 'dtype' in kwargs.keys():
        arr = np.array(arr, dtype=kwargs['dtype'])
    return arr

def sign(x):
    "Returns the sign of the input number (1 or -1). 1 for 0 or -0."
    x=npa(x)
    x[x==0]=1
    return (x/np.abs(x)).astype(int)

def minus_is_1(x):
    return abs(1-1*x)*1./2

def any_n_consec(X, n_consec, where=False):
    '''
    The trick below finds whether there are n_consec consecutive ones in the array comp
    by adding each element with its neighbour.
    At least 2 consec ones: add them 1 time and check if there is a 2=2**1 somewhere.
    At least 2 consec ones: add them 3 times and check if there is a 4=2**2 somewhere.
    ...
    Parameters:
        - X: array of booleans or binary
        - n_consec: int, number of consecutive True/False values to find
        - where: bool, returns array of indices if True
    '''
    X=npa(X).astype(np.int)
    assert np.all((X==0)|(X==1)), 'X array should be only 0s and 1s!'
    for i in range(n_consec-1):
        X = X[:-1]+X[1:]
    b=np.any(X==2**(n_consec-1))
    if not where:
        return b
    if b:
        i=np.nonzero(X==2**(n_consec-1))[0]
        i_edges1=i[np.append(0,np.diff(i))!=1]
        i_edges2=(i+n_consec-1)[np.append(np.diff(i), 0)!=1]
        return b, [np.arange(i_edges1[e],i_edges2[e]+1) for e in range(len(i_edges1))]
    return b, npa([])

def thresh_consec0(arr, th, n_consec, sgn=1, exclude_edges=True):
    '''
    SLOWER THAN thresh_consec AND FORCED TO PROVIDE N_CONSEC -> SHITTY
    Returns indices and values of threshold crosses lasting >=n_consec consecutive samples in arr.
    Parameters:
        - arr: numpy array to threshold
        - th: float, threshold
        - n_consec: int, minimum number of consecutive elements beyond threshold
        - sgn: int, positive (for cases above threshold) or negative (below threshold)
        - exclude_edges: bool, if true edges of arr are not considered as threshold crosses
                         in cases where arr starts or ends beyond threshold
    '''
    arr=npa(arr)
    if not arr.ndim==1:
        assert 1 in arr.shape
        arr=arr.flatten()
    
    arr= (arr-th)*sign(sgn)+th # Flips the array around threshold if sgn==-1
    comp = (arr>=th)
        
    crosses=any_n_consec(comp, n_consec, where=True)[1]
    
    if exclude_edges:
        if crosses[0][0]==0: # starts beyond threshold and lasts >=n_consec_bins
            crosses=crosses[1:]
        if crosses[-1][-1]==len(arr)-1: # starts beyond threshold and lasts >=n_consec_bins
            crosses=crosses[:-1]
    
    return [np.vstack([cross, arr[cross]]) for cross in crosses]

def thresh(arr, th, sgn=1, pos=1):
    '''Returns indices of the data points closest to a directed crossing of th.
    - data: numpy array.
    - th: threshold value.
    - sgn: 1 or -1, direction of the threshold crossing, either positive (1) or negative (-1).
    - pos: 1 or -1, position of closest value, just following or just preceeding.'''
    assert pos in [-1,1]
    assert sgn in [-1,1]
    arr=npa(arr)
    assert arr.ndim==1
    arr= (arr-th)*sgn+th # Flips the array around threshold if sgn==-1
    
    i=np.nonzero(arr>=th)[0] if pos==1 else np.nonzero(arr<=th)[0]
    # If no value is above the threshold or all of them are already above the threshold
    if len(i)==0 or len(i)==len(arr): 
        return np.array([])
    return  i[arr[np.clip(i-1, 0, len(arr)-1)]<th] if pos==1 else i[arr[np.clip(i+1, 0, len(arr)-1)]>th]


def thresh_consec(arr, th, sgn=1, n_consec=0, exclude_edges=True, only_max=False):
    '''
    Returns indices and values of threshold crosses lasting >=n_consec consecutive samples in arr.
    Parameters:
        - arr: numpy array to threshold
        - th: float, threshold
        - sgn: 1 or -1, positive (for cases above threshold) or negative (below threshold)
        - n_consec: optional int, minimum number of consecutive elements beyond threshold | Defult 0 (any cross)
        - exclude_edges: bool, if true edges of arr are not considered as threshold crosses
                         in cases where arr starts or ends beyond threshold
        - only_max: bool, if True returns only the most prominent threshold cross.
    Returns:
        - crosses, list of 2d np arrays [indices, array values]
    '''
    def thresh_cons(arr, th, sgn=1, n_consec=0, exclude_edges=True):
        arr=npa(arr)
        if not arr.ndim==1:
            assert 1 in arr.shape
            arr=arr.flatten()
            
        assert sgn in [-1,1]
        arr= (arr-th)*sgn+th # Flips the array around threshold if sgn==-1
        
        cross_thp, cross_thn = thresh(arr, th, 1, 1), thresh(arr, th, -1, -1)
        if exclude_edges:
            if len(cross_thp)+len(cross_thn)<=1: cross_thp, cross_thn = [], [] # Only one cross at the beginning or the end e.g.
            else:
                flag0, flag1=False,False
                if cross_thp[-1]>cross_thn[-1]: flag1=True # if + cross at the end
                if cross_thn[0]<cross_thp[0]: flag0=True # if - cross at the beginning
                if flag1: cross_thp=cross_thp[:-1] # remove last + cross
                if flag0: cross_thn=cross_thn[1:] # remove first - cross
        else:
            if len(cross_thp)+len(cross_thn)<=1: cross_thp, cross_thn = [], [] # Only one cross at the beginning or the end e.g.
            else:
                flag0, flag1=False,False
                if cross_thp[-1]>cross_thn[-1]: flag1=True # if + cross at the end
                if cross_thn[0]<cross_thp[0]: flag0=True # if - cross at the beginning
                if flag1: cross_thn=np.append(cross_thn, len(arr)) # add fake - cross at the end
                if flag0: cross_thp=np.append(0,cross_thp) # add fake + cross at the beginning
    
        assert len(cross_thp)==len(cross_thn)
            
        crosses=[np.vstack([np.arange(cross_thp[i], cross_thn[i]+1, 1), ((arr-th)*sgn+th)[cross_thp[i]:cross_thn[i]+1]]) for i in range(len(cross_thp)) if cross_thn[i]+1-cross_thp[i]>=n_consec]
        
        return crosses
    
    sgn=[-1,1] if sgn==0 else [sgn]
    crosses=[]
    for s in sgn:
        crosses+=thresh_cons(arr, th, s, n_consec, exclude_edges)
            
    if only_max and len(crosses)>0:
        cross=crosses[0]
        for c in crosses[1:]:
            if max(abs(c[1,:]))>max(abs(cross[1,:])): cross = c
        crosses=[cross]
        assert len(crosses)==1
        
    return crosses


def zscore(arr, frac=4./5, mn_ext=None, sd_ext=None):
    '''
    Returns z-scored (centered, reduced) array using outer edges of array to compute mean and std.
    Parameters:
        - arr: 1D np array
        - frac: fraction of array used to compute mean and standard deviation
        - mn_ext: optional, provide mean computed outside of function
        - sd_ext: optional, provide standard deviation computed outside of function
    '''
    assert 0<frac<=1, 'Z-score fraction should be between 0 and 1!'
    mn = np.mean(np.append(arr[:int(len(arr)*frac/2)], arr[int(len(arr)*(1-frac/2)):])) if mn_ext is None else mn_ext
    sd = np.std(np.append(arr[:int(len(arr)*frac/2)], arr[int(len(arr)*(1-frac/2)):])) if sd_ext is None else sd_ext
    return (arr-mn)*1./sd

def smooth(arr, frac=0.06, it=0, frac2=0.005, spec='acg', cbin=0.1, cwin=100, lms=3):
    '''cbin and cwin in milliseconds.
    frac is the fraction looked ahead for smoothing on the sides on the array, frac2 between -lms and + lms in milliseconds.'''
    arr=np.asarray(arr)
    if spec=='acg' or spec=='ccg': # smooth the central bins with a low frac, sides with high frac
        halfcenter= (lms/cbin)# Left smoothing difference limit, in milliseconds
        l = int((cwin/cbin)*1./2 - halfcenter); r = int(l+halfcenter*2);
        sarr1=lowess(arr, np.arange(len(arr)), is_sorted=True, frac=frac, it=it)[:,1].flatten()[:l]
        sarr2=lowess(arr, np.arange(len(arr)), is_sorted=True, frac=frac2, it=it)[:,1].flatten()[l:r]
        sarr3=lowess(arr, np.arange(len(arr)), is_sorted=True, frac=frac, it=it)[:,1].flatten()[r:]
        sarr = np.append(np.append(sarr1, sarr2), sarr3)
    else:
        sarr=lowess(arr, np.arange(len(arr)), is_sorted=True, frac=frac, it=it)[:,1].flatten()
    return sarr

def get_bins(cwin, cbin):
    mod2=(cwin/cbin)%2
    if mod2==0: # even
        return np.arange(-cwin/2, cwin/2+cbin, cbin)
    else: # odd
        return np.arange(-cwin/2+cbin/2, cwin/2+cbin/2, cbin)

def align_timeseries(timeseries, sync_signals):
    '''
    Re-aligns in time series based on provided sync signals.
    - timeseries: list of numpy arrays of time stamps (e.g. spikes)
    - sync_signals: list of numpy arrays of synchronization time stamps,
      ordered with respect to timeseries
      
      The FIRST sync_signal is used as a reference.
      
    Returns:
     timeseries, aligned accordingly to sync signals.
    
    '''
    assert type(timeseries) is type(sync_signals) is list, "You must provide timeseries and sync_signals as lists of arrays!"
    assert len(timeseries)==len(sync_signals)>=2, "There must be as many time series as sync signals, at least 2 of each!"
    for ss in sync_signals:
        assert len(sync_signals[0])==len(ss), "WARNING all sync signals do not have the same size, the acquisition must have been faulty!"
    assert len(sync_signals[0])>=1, "Only one synchronization signal has been provided - this is dangerous practice as this does not account for cumulative time drift."
    
    Nevents, totDft, avDft, stdDft = len(sync_signals[0]), (sync_signals[1]-sync_signals[0])[-1], np.mean(np.diff(sync_signals[1]-sync_signals[0])), np.std(np.diff(sync_signals[1]-sync_signals[0]))
    print("{} sync events used for alignement - start-end drift of {}ms, \
          av. drift between consec. sync events of {}+/-{}ms.".format(Nevents, totDft, avDft, stdDft))
    
    for dataset_i in range(len(timeseries)):
        array0, syncs=timeseries[dataset_i], sync_signals[dataset_i]
        array=array0-syncs[0]
        for i, sync in enumerate(syncs):
            if i==0: pass
            else:
                array1=array0-sync # refer to own sync stamp, sync
                # re-time to where own sync stamp should be with respect to reference dataset (the 1st one)
                first_sync_ref0=sync_signals[0][i]-sync_signals[0][0]
                array=np.append(array[array1<0], array1[array1>=0]+first_sync_ref0)
        timeseries[dataset_i]=array
        
    return timeseries

#%% Stolen from phy
def _as_array(arr, dtype=None):
    """Convert an object to a numerical NumPy array.
    Avoid a copy if possible.
    """
    if arr is None:
        return None
    if isinstance(arr, np.ndarray) and dtype is None:
        return arr
    if isinstance(arr, integer_types + (float,)):
        arr = [arr]
    out = np.asarray(arr)
    if dtype is not None:
        if out.dtype != dtype:
            out = out.astype(dtype)
    if out.dtype not in _ACCEPTED_ARRAY_DTYPES:
        raise ValueError("'arr' seems to have an invalid dtype: "
                         "{0:s}".format(str(out.dtype)))
    return out

def _unique(x):
    """Faster version of np.unique().
    This version is restricted to 1D arrays of non-negative integers.
    It is only faster if len(x) >> len(unique(x)).
    """
    if x is None or len(x) == 0:
        return np.array([], dtype=np.int64)
    # WARNING: only keep positive values.
    # cluster=-1 means "unclustered".
    x = _as_array(x)
    x = x[x >= 0]
    bc = np.bincount(x)
    return np.nonzero(bc)[0]

def _index_of(arr, lookup):
    """Replace scalars in an array by their indices in a lookup table.
    Implicitely assume that:
    * All elements of arr and lookup are non-negative integers.
    * All elements or arr belong to lookup.
    This is not checked for performance reasons.
    """
    # Equivalent of np.digitize(arr, lookup) - 1, but much faster.
    lookup = np.asarray(lookup, dtype=np.int32)
    m = (lookup.max() if len(lookup) else 0) + 1
    tmp = np.zeros(m + 1, dtype=np.int)
    # Ensure that -1 values are kept.
    tmp[-1] = -1
    if len(lookup):
        tmp[lookup] = np.arange(len(lookup))
    return tmp[arr]

#%% Peakdetect functions

__all__ = [
        "peakdetect",
        "peakdetect_fft",
        "peakdetect_parabola",
        "peakdetect_sine",
        "peakdetect_sine_locked",
        "peakdetect_spline",
        "peakdetect_zero_crossing",
        "zero_crossings",
        "zero_crossings_sine_fit"
        ]



def _datacheck_peakdetect(x_axis, y_axis):
    if x_axis is None:
        x_axis = range(len(y_axis))
    
    if len(y_axis) != len(x_axis):
        raise ValueError( 
                "Input vectors y_axis and x_axis must have same length")
    
    #needs to be a numpy array
    y_axis = np.array(y_axis)
    x_axis = np.array(x_axis)
    return x_axis, y_axis
    

def _pad(fft_data, pad_len):
    """
    Pads fft data to interpolate in time domain
    
    keyword arguments:
    fft_data -- the fft
    pad_len --  By how many times the time resolution should be increased by
    
    return: padded list
    """
    l = len(fft_data)
    n = _n(l * pad_len)
    fft_data = list(fft_data)
    
    return fft_data[:l // 2] + [0] * (2**n-l) + fft_data[l // 2:]
    
def _n(x):
    """
    Find the smallest value for n, which fulfils 2**n >= x
    
    keyword arguments:
    x -- the value, which 2**n must surpass
    
    return: the integer n
    """
    return int(log(x)/log(2)) + 1
    
    
def _peakdetect_parabola_fitter(raw_peaks, x_axis, y_axis, points):
    """
    Performs the actual parabola fitting for the peakdetect_parabola function.
        
    keyword arguments:
    raw_peaks -- A list of either the maxima or the minima peaks, as given
        by the peakdetect functions, with index used as x-axis
    
    x_axis -- A numpy array of all the x values
    
    y_axis -- A numpy array of all the y values
    
    points -- How many points around the peak should be used during curve
        fitting, must be odd.
    
    
    return: A list giving all the peaks and the fitted waveform, format:
        [[x, y, [fitted_x, fitted_y]]]
        
    """
    func = lambda x, a, tau, c: a * ((x - tau) ** 2) + c
    fitted_peaks = []
    distance = abs(x_axis[raw_peaks[1][0]] - x_axis[raw_peaks[0][0]]) / 4
    for peak in raw_peaks:
        index = peak[0]
        x_data = x_axis[index - points // 2: index + points // 2 + 1]
        y_data = y_axis[index - points // 2: index + points // 2 + 1]
        # get a first approximation of tau (peak position in time)
        tau = x_axis[index]
        # get a first approximation of peak amplitude
        c = peak[1]
        a = np.sign(c) * (-1) * (np.sqrt(abs(c))/distance)**2
        """Derived from ABC formula to result in a solution where A=(rot(c)/t)**2"""
        
        # build list of approximations
        
        p0 = (a, tau, c)
        popt, pcov = curve_fit(func, x_data, y_data, p0)
        # retrieve tau and c i.e x and y value of peak
        x, y = popt[1:3]
        
        # create a high resolution data set for the fitted waveform
        x2 = np.linspace(x_data[0], x_data[-1], points * 10)
        y2 = func(x2, *popt)
        
        fitted_peaks.append([x, y, [x2, y2]])
        
    return fitted_peaks
    
    
def peakdetect_parabole(*args, **kwargs):
    """
    Misspelling of peakdetect_parabola
    function is deprecated please use peakdetect_parabola
    """
    logging.warn("peakdetect_parabole is deprecated due to misspelling use: peakdetect_parabola")
    
    return peakdetect_parabola(*args, **kwargs)
    
    
def peakdetect(y_axis, x_axis = None, lookahead = 200, delta=0):
    """
    Converted from/based on a MATLAB script at: 
    http://billauer.co.il/peakdet.html
    
    function for detecting local maxima and minima in a signal.
    Discovers peaks by searching for values which are surrounded by lower
    or larger values for maxima and minima respectively
    
    keyword arguments:
    y_axis -- A list containing the signal over which to find peaks
    
    x_axis -- A x-axis whose values correspond to the y_axis list and is used
        in the return to specify the position of the peaks. If omitted an
        index of the y_axis is used.
        (default: None)
    
    lookahead -- distance to look ahead from a peak candidate to determine if
        it is the actual peak
        (default: 200) 
        '(samples / period) / f' where '4 >= f >= 1.25' might be a good value
    
    delta -- this specifies a minimum difference between a peak and
        the following points, before a peak may be considered a peak. Useful
        to hinder the function from picking up false peaks towards to end of
        the signal. To work well delta should be set to delta >= RMSnoise * 5.
        (default: 0)
            When omitted delta function causes a 20% decrease in speed.
            When used Correctly it can double the speed of the function
    
    
    return: two lists [max_peaks, min_peaks] containing the positive and
        negative peaks respectively. Each cell of the lists contains a tuple
        of: (position, peak_value) 
        to get the average peak value do: np.mean(max_peaks, 0)[1] on the
        results to unpack one of the lists into x, y coordinates do: 
        x, y = zip(*max_peaks)
    """
    max_peaks = []
    min_peaks = []
    dump = []   #Used to pop the first hit which almost always is false
       
    # check input data
    x_axis, y_axis = _datacheck_peakdetect(x_axis, y_axis)
    # store data length for later use
    length = len(y_axis)
    
    
    #perform some checks
    if lookahead < 1:
        raise ValueError("Lookahead must be '1' or above in value")
    if not (np.isscalar(delta) and delta >= 0):
        raise ValueError("delta must be a positive number")
    
    #maxima and minima candidates are temporarily stored in
    #mx and mn respectively
    mn, mx = np.Inf, -np.Inf
    
    #Only detect peak if there is 'lookahead' amount of points after it
    for index, (x, y) in enumerate(zip(x_axis[:-lookahead], 
                                        y_axis[:-lookahead])):
        if y > mx:
            mx = y
            mxpos = x
        if y < mn:
            mn = y
            mnpos = x
        
        ####look for max####
        if y < mx-delta and mx != np.Inf:
            #Maxima peak candidate found
            #look ahead in signal to ensure that this is a peak and not jitter
            if y_axis[index:index+lookahead].max() < mx:
                max_peaks.append([mxpos, mx])
                dump.append(True)
                #set algorithm to only find minima now
                mx = np.Inf
                mn = np.Inf
                if index+lookahead >= length:
                    #end is within lookahead no more peaks can be found
                    break
                continue
            #else:  #slows shit down this does
            #    mx = ahead
            #    mxpos = x_axis[np.where(y_axis[index:index+lookahead]==mx)]
        
        ####look for min####
        if y > mn+delta and mn != -np.Inf:
            #Minima peak candidate found 
            #look ahead in signal to ensure that this is a peak and not jitter
            if y_axis[index:index+lookahead].min() > mn:
                min_peaks.append([mnpos, mn])
                dump.append(False)
                #set algorithm to only find maxima now
                mn = -np.Inf
                mx = -np.Inf
                if index+lookahead >= length:
                    #end is within lookahead no more peaks can be found
                    break
            #else:  #slows shit down this does
            #    mn = ahead
            #    mnpos = x_axis[np.where(y_axis[index:index+lookahead]==mn)]
    
    
    #Remove the false hit on the first value of the y_axis
    try:
        if dump[0]:
            max_peaks.pop(0)
        else:
            min_peaks.pop(0)
        del dump
    except IndexError:
        #no peaks were found, should the function return empty lists?
        pass
        
    return [max_peaks, min_peaks]
    
    
def peakdetect_fft(y_axis, x_axis, pad_len = 20):
    """
    Performs a FFT calculation on the data and zero-pads the results to
    increase the time domain resolution after performing the inverse fft and
    send the data to the 'peakdetect' function for peak 
    detection.
    
    Omitting the x_axis is forbidden as it would make the resulting x_axis
    value silly if it was returned as the index 50.234 or similar.
    
    Will find at least 1 less peak then the 'peakdetect_zero_crossing'
    function, but should result in a more precise value of the peak as
    resolution has been increased. Some peaks are lost in an attempt to
    minimize spectral leakage by calculating the fft between two zero
    crossings for n amount of signal periods.
    
    The biggest time eater in this function is the ifft and thereafter it's
    the 'peakdetect' function which takes only half the time of the ifft.
    Speed improvements could include to check if 2**n points could be used for
    fft and ifft or change the 'peakdetect' to the 'peakdetect_zero_crossing',
    which is maybe 10 times faster than 'peakdetct'. The pro of 'peakdetect'
    is that it results in one less lost peak. It should also be noted that the
    time used by the ifft function can change greatly depending on the input.
    
    keyword arguments:
    y_axis -- A list containing the signal over which to find peaks
    
    x_axis -- A x-axis whose values correspond to the y_axis list and is used
        in the return to specify the position of the peaks.
    
    pad_len -- By how many times the time resolution should be
        increased by, e.g. 1 doubles the resolution. The amount is rounded up
        to the nearest 2**n amount
        (default: 20)
    
    
    return: two lists [max_peaks, min_peaks] containing the positive and
        negative peaks respectively. Each cell of the lists contains a tuple
        of: (position, peak_value) 
        to get the average peak value do: np.mean(max_peaks, 0)[1] on the
        results to unpack one of the lists into x, y coordinates do: 
        x, y = zip(*max_peaks)
    """
    # check input data
    x_axis, y_axis = _datacheck_peakdetect(x_axis, y_axis)
    zero_indices = zero_crossings(y_axis, window_len = 11)
    #select a n amount of periods
    last_indice = - 1 - (1 - len(zero_indices) & 1)
    ###
    # Calculate the fft between the first and last zero crossing
    # this method could be ignored if the beginning and the end of the signal
    # are unnecessary as any errors induced from not using whole periods
    # should mainly manifest in the beginning and the end of the signal, but
    # not in the rest of the signal
    # this is also unnecessary if the given data is an amount of whole periods
    ###
    fft_data = fft(y_axis[zero_indices[0]:zero_indices[last_indice]])
    padd = lambda x, c: x[:len(x) // 2] + [0] * c + x[len(x) // 2:]
    n = lambda x: int(log(x)/log(2)) + 1
    # pads to 2**n amount of samples
    fft_padded = padd(list(fft_data), 2 ** 
                n(len(fft_data) * pad_len) - len(fft_data))
    
    # There is amplitude decrease directly proportional to the sample increase
    sf = len(fft_padded) / float(len(fft_data))
    # There might be a leakage giving the result an imaginary component
    # Return only the real component
    y_axis_ifft = ifft(fft_padded).real * sf #(pad_len + 1)
    x_axis_ifft = np.linspace(
                x_axis[zero_indices[0]], x_axis[zero_indices[last_indice]],
                len(y_axis_ifft))
    # get the peaks to the interpolated waveform
    max_peaks, min_peaks = peakdetect(y_axis_ifft, x_axis_ifft, 500,
                                    delta = abs(np.diff(y_axis).max() * 2))
    #max_peaks, min_peaks = peakdetect_zero_crossing(y_axis_ifft, x_axis_ifft)
    
    # store one 20th of a period as waveform data
    data_len = int(np.diff(zero_indices).mean()) / 10
    data_len += 1 - data_len & 1
    
    
    return [max_peaks, min_peaks]
    
    
def peakdetect_parabola(y_axis, x_axis, points = 31):
    """
    Function for detecting local maxima and minima in a signal.
    Discovers peaks by fitting the model function: y = k (x - tau) ** 2 + m
    to the peaks. The amount of points used in the fitting is set by the
    points argument.
    
    Omitting the x_axis is forbidden as it would make the resulting x_axis
    value silly, if it was returned as index 50.234 or similar.
    
    will find the same amount of peaks as the 'peakdetect_zero_crossing'
    function, but might result in a more precise value of the peak.
    
    keyword arguments:
    y_axis -- A list containing the signal over which to find peaks
    
    x_axis -- A x-axis whose values correspond to the y_axis list and is used
        in the return to specify the position of the peaks.
    
    points -- How many points around the peak should be used during curve
        fitting (default: 31)
    
    
    return: two lists [max_peaks, min_peaks] containing the positive and
        negative peaks respectively. Each cell of the lists contains a tuple
        of: (position, peak_value) 
        to get the average peak value do: np.mean(max_peaks, 0)[1] on the
        results to unpack one of the lists into x, y coordinates do: 
        x, y = zip(*max_peaks)
    """
    # check input data
    x_axis, y_axis = _datacheck_peakdetect(x_axis, y_axis)
    # make the points argument odd
    points += 1 - points % 2
    #points += 1 - int(points) & 1 slower when int conversion needed
    
    # get raw peaks
    max_raw, min_raw = peakdetect_zero_crossing(y_axis)
    
    # define output variable
    max_peaks = []
    min_peaks = []
    
    max_ = _peakdetect_parabola_fitter(max_raw, x_axis, y_axis, points)
    min_ = _peakdetect_parabola_fitter(min_raw, x_axis, y_axis, points)
    
    max_peaks = map(lambda x: [x[0], x[1]], max_)
    max_fitted = map(lambda x: x[-1], max_)
    min_peaks = map(lambda x: [x[0], x[1]], min_)
    min_fitted = map(lambda x: x[-1], min_)
    
    return [max_peaks, min_peaks]
    

def peakdetect_sine(y_axis, x_axis, points = 31, lock_frequency = False):
    """
    Function for detecting local maxima and minima in a signal.
    Discovers peaks by fitting the model function:
    y = A * sin(2 * pi * f * (x - tau)) to the peaks. The amount of points used
    in the fitting is set by the points argument.
    
    Omitting the x_axis is forbidden as it would make the resulting x_axis
    value silly if it was returned as index 50.234 or similar.
    
    will find the same amount of peaks as the 'peakdetect_zero_crossing'
    function, but might result in a more precise value of the peak.
    
    The function might have some problems if the sine wave has a
    non-negligible total angle i.e. a k*x component, as this messes with the
    internal offset calculation of the peaks, might be fixed by fitting a 
    y = k * x + m function to the peaks for offset calculation.
    
    keyword arguments:
    y_axis -- A list containing the signal over which to find peaks
    
    x_axis -- A x-axis whose values correspond to the y_axis list and is used
        in the return to specify the position of the peaks.
    
    points -- How many points around the peak should be used during curve
        fitting (default: 31)
    
    lock_frequency -- Specifies if the frequency argument of the model
        function should be locked to the value calculated from the raw peaks
        or if optimization process may tinker with it.
        (default: False)
    
    
    return: two lists [max_peaks, min_peaks] containing the positive and
        negative peaks respectively. Each cell of the lists contains a tuple
        of: (position, peak_value) 
        to get the average peak value do: np.mean(max_peaks, 0)[1] on the
        results to unpack one of the lists into x, y coordinates do: 
        x, y = zip(*max_peaks)
    """
    # check input data
    x_axis, y_axis = _datacheck_peakdetect(x_axis, y_axis)
    # make the points argument odd
    points += 1 - points % 2
    #points += 1 - int(points) & 1 slower when int conversion needed
    
    # get raw peaks
    max_raw, min_raw = peakdetect_zero_crossing(y_axis)
    
    # define output variable
    max_peaks = []
    min_peaks = []
    
    # get global offset
    offset = np.mean([np.mean(max_raw, 0)[1], np.mean(min_raw, 0)[1]])
    # fitting a k * x + m function to the peaks might be better
    #offset_func = lambda x, k, m: k * x + m
    
    # calculate an approximate frequency of the signal
    Hz_h_peak = np.diff(zip(*max_raw)[0]).mean()
    Hz_l_peak = np.diff(zip(*min_raw)[0]).mean()
    Hz = 1 / np.mean([Hz_h_peak, Hz_l_peak])
    
    
    
    # model function
    # if cosine is used then tau could equal the x position of the peak
    # if sine were to be used then tau would be the first zero crossing
    if lock_frequency:
        func = lambda x_ax, A, tau: A * np.sin(
            2 * pi * Hz * (x_ax - tau) + pi / 2)
    else:
        func = lambda x_ax, A, Hz, tau: A * np.sin(
            2 * pi * Hz * (x_ax - tau) + pi / 2)
    #func = lambda x_ax, A, Hz, tau: A * np.cos(2 * pi * Hz * (x_ax - tau))
    
    
    #get peaks
    fitted_peaks = []
    for raw_peaks in [max_raw, min_raw]:
        peak_data = []
        for peak in raw_peaks:
            index = peak[0]
            x_data = x_axis[index - points // 2: index + points // 2 + 1]
            y_data = y_axis[index - points // 2: index + points // 2 + 1]
            # get a first approximation of tau (peak position in time)
            tau = x_axis[index]
            # get a first approximation of peak amplitude
            A = peak[1]
            
            # build list of approximations
            if lock_frequency:
                p0 = (A, tau)
            else:
                p0 = (A, Hz, tau)
            
            # subtract offset from wave-shape
            y_data -= offset
            popt, pcov = curve_fit(func, x_data, y_data, p0)
            # retrieve tau and A i.e x and y value of peak
            x = popt[-1]
            y = popt[0]
            
            # create a high resolution data set for the fitted waveform
            x2 = np.linspace(x_data[0], x_data[-1], points * 10)
            y2 = func(x2, *popt)
            
            # add the offset to the results
            y += offset
            y2 += offset
            y_data += offset
            
            peak_data.append([x, y, [x2, y2]])
       
        fitted_peaks.append(peak_data)
    
    # structure date for output
    max_peaks = map(lambda x: [x[0], x[1]], fitted_peaks[0])
    max_fitted = map(lambda x: x[-1], fitted_peaks[0])
    min_peaks = map(lambda x: [x[0], x[1]], fitted_peaks[1])
    min_fitted = map(lambda x: x[-1], fitted_peaks[1])
    
    
    return [max_peaks, min_peaks]

    
def peakdetect_sine_locked(y_axis, x_axis, points = 31):
    """
    Convenience function for calling the 'peakdetect_sine' function with
    the lock_frequency argument as True.
    
    keyword arguments:
    y_axis -- A list containing the signal over which to find peaks
    x_axis -- A x-axis whose values correspond to the y_axis list and is used
        in the return to specify the position of the peaks.
    points -- How many points around the peak should be used during curve
        fitting (default: 31)
    
    return: see the function 'peakdetect_sine'
    """
    return peakdetect_sine(y_axis, x_axis, points, True)
    
    
def peakdetect_spline(y_axis, x_axis, pad_len=20):
    """
    Performs a b-spline interpolation on the data to increase resolution and
    send the data to the 'peakdetect_zero_crossing' function for peak 
    detection.
    
    Omitting the x_axis is forbidden as it would make the resulting x_axis
    value silly if it was returned as the index 50.234 or similar.
    
    will find the same amount of peaks as the 'peakdetect_zero_crossing'
    function, but might result in a more precise value of the peak.
    
    keyword arguments:
    y_axis -- A list containing the signal over which to find peaks
    
    x_axis -- A x-axis whose values correspond to the y_axis list and is used
        in the return to specify the position of the peaks. 
        x-axis must be equally spaced.
    
    pad_len -- By how many times the time resolution should be increased by,
        e.g. 1 doubles the resolution.
        (default: 20)
    
    
    return: two lists [max_peaks, min_peaks] containing the positive and
        negative peaks respectively. Each cell of the lists contains a tuple
        of: (position, peak_value) 
        to get the average peak value do: np.mean(max_peaks, 0)[1] on the
        results to unpack one of the lists into x, y coordinates do: 
        x, y = zip(*max_peaks)
    """
    # check input data
    x_axis, y_axis = _datacheck_peakdetect(x_axis, y_axis)
    # could perform a check if x_axis is equally spaced
    #if np.std(np.diff(x_axis)) > 1e-15: raise ValueError
    # perform spline interpolations
    dx = x_axis[1] - x_axis[0]
    x_interpolated = np.linspace(x_axis.min(), x_axis.max(), len(x_axis) * (pad_len + 1))
    cj = cspline1d(y_axis)
    y_interpolated = cspline1d_eval(cj, x_interpolated, dx=dx,x0=x_axis[0])
    # get peaks
    max_peaks, min_peaks = peakdetect_zero_crossing(y_interpolated, x_interpolated)
    
    return [max_peaks, min_peaks]
    
def peakdetect_zero_crossing(y_axis, x_axis = None, window = 11):
    """
    Function for detecting local maxima and minima in a signal.
    Discovers peaks by dividing the signal into bins and retrieving the
    maximum and minimum value of each the even and odd bins respectively.
    Division into bins is performed by smoothing the curve and finding the
    zero crossings.
    
    Suitable for repeatable signals, where some noise is tolerated. Executes
    faster than 'peakdetect', although this function will break if the offset
    of the signal is too large. It should also be noted that the first and
    last peak will probably not be found, as this function only can find peaks
    between the first and last zero crossing.
    
    keyword arguments:
    y_axis -- A list containing the signal over which to find peaks
    
    x_axis -- A x-axis whose values correspond to the y_axis list
        and is used in the return to specify the position of the peaks. If
        omitted an index of the y_axis is used.
        (default: None)
    
    window -- the dimension of the smoothing window; should be an odd integer
        (default: 11)
    
    
    return: two lists [max_peaks, min_peaks] containing the positive and
        negative peaks respectively. Each cell of the lists contains a tuple
        of: (position, peak_value) 
        to get the average peak value do: np.mean(max_peaks, 0)[1] on the
        results to unpack one of the lists into x, y coordinates do: 
        x, y = zip(*max_peaks)
    """
    # check input data
    x_axis, y_axis = _datacheck_peakdetect(x_axis, y_axis)
    
    zero_indices = zero_crossings(y_axis, window_len = window)
    period_lengths = np.diff(zero_indices)
            
    bins_y = [y_axis[index:index + diff] for index, diff in 
        zip(zero_indices, period_lengths)]
    bins_x = [x_axis[index:index + diff] for index, diff in 
        zip(zero_indices, period_lengths)]
        
    even_bins_y = bins_y[::2]
    odd_bins_y = bins_y[1::2]
    even_bins_x = bins_x[::2]
    odd_bins_x = bins_x[1::2]
    hi_peaks_x = []
    lo_peaks_x = []
    
    #check if even bin contains maxima
    if abs(even_bins_y[0].max()) > abs(even_bins_y[0].min()):
        hi_peaks = [bin.max() for bin in even_bins_y]
        lo_peaks = [bin.min() for bin in odd_bins_y]
        # get x values for peak
        for bin_x, bin_y, peak in zip(even_bins_x, even_bins_y, hi_peaks):
            hi_peaks_x.append(bin_x[np.where(bin_y==peak)[0][0]])
        for bin_x, bin_y, peak in zip(odd_bins_x, odd_bins_y, lo_peaks):
            lo_peaks_x.append(bin_x[np.where(bin_y==peak)[0][0]])
    else:
        hi_peaks = [bin.max() for bin in odd_bins_y]
        lo_peaks = [bin.min() for bin in even_bins_y]
        # get x values for peak
        for bin_x, bin_y, peak in zip(odd_bins_x, odd_bins_y, hi_peaks):
            hi_peaks_x.append(bin_x[np.where(bin_y==peak)[0][0]])
        for bin_x, bin_y, peak in zip(even_bins_x, even_bins_y, lo_peaks):
            lo_peaks_x.append(bin_x[np.where(bin_y==peak)[0][0]])
    
    max_peaks = [[x, y] for x,y in zip(hi_peaks_x, hi_peaks)]
    min_peaks = [[x, y] for x,y in zip(lo_peaks_x, lo_peaks)]
    
    return [max_peaks, min_peaks]
        
    
def _smooth(x, window_len=11, window="hanning"):
    """
    smooth the data using a window of the requested size.
    
    This method is based on the convolution of a scaled window on the signal.
    The signal is prepared by introducing reflected copies of the signal 
    (with the window size) in both ends so that transient parts are minimized
    in the beginning and end part of the output signal.
    
    keyword arguments:
    x -- the input signal 
    
    window_len -- the dimension of the smoothing window; should be an odd
        integer (default: 11)
    
    window -- the type of window from 'flat', 'hanning', 'hamming', 
        'bartlett', 'blackman', where flat is a moving average
        (default: 'hanning')
    
    return: the smoothed signal
        
    example:
    t = linspace(-2,2,0.1)
    x = sin(t)+randn(len(t))*0.1
    y = _smooth(x)
    
    see also: 
    
    numpy.hanning, numpy.hamming, numpy.bartlett, numpy.blackman, 
    numpy.convolve, scipy.signal.lfilter 
    """
    if x.ndim != 1:
        raise ValueError("smooth only accepts 1 dimension arrays.")

    if x.size < window_len:
        raise ValueError("Input vector needs to be bigger than window size.")
    
    if window_len<3:
        return x
    #declare valid windows in a dictionary
    window_funcs = {
        "flat": lambda _len: np.ones(_len, "d"),
        "hanning": np.hanning,
        "hamming": np.hamming,
        "bartlett": np.bartlett,
        "blackman": np.blackman
        }
    
    s = np.r_[x[window_len-1:0:-1], x, x[-1:-window_len:-1]]
    try:
        w = window_funcs[window](window_len)
    except KeyError:
        raise ValueError(
            "Window is not one of '{0}', '{1}', '{2}', '{3}', '{4}'".format(
            *window_funcs.keys()))
    
    y = np.convolve(w / w.sum(), s, mode = "valid")
    
    return y
    
    
def zero_crossings(y_axis, window_len = 11, 
    window_f="hanning", offset_corrected=False):
    """
    Algorithm to find zero crossings. Smooths the curve and finds the
    zero-crossings by looking for a sign change.
    
    
    keyword arguments:
    y_axis -- A list containing the signal over which to find zero-crossings
    
    window_len -- the dimension of the smoothing window; should be an odd
        integer (default: 11)
    
    window_f -- the type of window from 'flat', 'hanning', 'hamming', 
        'bartlett', 'blackman' (default: 'hanning')
    
    offset_corrected -- Used for recursive calling to remove offset when needed
    
    
    return: the index for each zero-crossing
    """
    # smooth the curve
    length = len(y_axis)
    
    # discard tail of smoothed signal
    y_axis = _smooth(y_axis, window_len, window_f)[:length]
    indices = np.where(np.diff(np.sign(y_axis)))[0]
    
    # check if zero-crossings are valid
    diff = np.diff(indices)
    if diff.std() / diff.mean() > 0.1:
        #Possibly bad zero crossing, see if it's offsets
        if ((diff[::2].std() / diff[::2].mean()) < 0.1 and 
        (diff[1::2].std() / diff[1::2].mean()) < 0.1 and
        not offset_corrected):
            #offset present attempt to correct by subtracting the average
            offset = np.mean([y_axis.max(), y_axis.min()])
            return zero_crossings(y_axis-offset, window_len, window_f, True)
        #Invalid zero crossings and the offset has been removed
        print(diff.std() / diff.mean())
        print(np.diff(indices))
        raise ValueError(
            "False zero-crossings found, indicates problem {0!s} or {1!s}".format(
            "with smoothing window", "unhandled problem with offset"))
    # check if any zero crossings were found
    if len(indices) < 1:
        raise ValueError("No zero crossings found")
    #remove offset from indices due to filter function when returning
    return indices - (window_len // 2 - 1)
    # used this to test the fft function's sensitivity to spectral leakage
    #return indices + np.asarray(30 * np.random.randn(len(indices)), int)
    
############################Frequency calculation#############################
#    diff = np.diff(indices)
#    time_p_period = diff.mean()
#    
#    if diff.std() / time_p_period > 0.1:
#        raise ValueError(
#            "smoothing window too small, false zero-crossing found")
#    
#    #return frequency
#    return 1.0 / time_p_period
##############################################################################


def zero_crossings_sine_fit(y_axis, x_axis, fit_window = None, smooth_window = 11):
    """
    Detects the zero crossings of a signal by fitting a sine model function
    around the zero crossings:
    y = A * sin(2 * pi * Hz * (x - tau)) + k * x + m
    Only tau (the zero crossing) is varied during fitting.
    
    Offset and a linear drift of offset is accounted for by fitting a linear
    function the negative respective positive raw peaks of the wave-shape and
    the amplitude is calculated using data from the offset calculation i.e.
    the 'm' constant from the negative peaks is subtracted from the positive
    one to obtain amplitude.
    
    Frequency is calculated using the mean time between raw peaks.
    
    Algorithm seems to be sensitive to first guess e.g. a large smooth_window
    will give an error in the results.
    
    
    keyword arguments:
    y_axis -- A list containing the signal over which to find peaks
    
    x_axis -- A x-axis whose values correspond to the y_axis list
        and is used in the return to specify the position of the peaks. If
        omitted an index of the y_axis is used. (default: None)
    
    fit_window -- Number of points around the approximate zero crossing that
        should be used when fitting the sine wave. Must be small enough that
        no other zero crossing will be seen. If set to none then the mean
        distance between zero crossings will be used (default: None)
    
    smooth_window -- the dimension of the smoothing window; should be an odd
        integer (default: 11)
    
    
    return: A list containing the positions of all the zero crossings.
    """
    # check input data
    x_axis, y_axis = _datacheck_peakdetect(x_axis, y_axis)
    #get first guess
    zero_indices = zero_crossings(y_axis, window_len = smooth_window)
    #modify fit_window to show distance per direction
    if fit_window == None:
        fit_window = np.diff(zero_indices).mean() // 3
    else:
        fit_window = fit_window // 2
    
    #x_axis is a np array, use the indices to get a subset with zero crossings
    approx_crossings = x_axis[zero_indices]
    
    
    
    #get raw peaks for calculation of offsets and frequency
    raw_peaks = peakdetect_zero_crossing(y_axis, x_axis)
    #Use mean time between peaks for frequency
    ext = lambda x: list(zip(*x)[0])
    _diff = map(np.diff, map(ext, raw_peaks))
    
    
    Hz = 1 / np.mean(map(np.mean, _diff))
    #Hz = 1 / np.diff(approx_crossings).mean() #probably bad precision
    
    
    #offset model function
    offset_func = lambda x, k, m: k * x + m
    k = []
    m = []
    amplitude = []
    
    for peaks in raw_peaks:
        #get peak data as nparray
        x_data, y_data = map(np.asarray, zip(*peaks))
        #x_data = np.asarray(x_data)
        #y_data = np.asarray(y_data)
        #calc first guess
        A = np.mean(y_data)
        p0 = (0, A)
        popt, pcov = curve_fit(offset_func, x_data, y_data, p0)
        #append results
        k.append(popt[0])
        m.append(popt[1])
        amplitude.append(abs(A))
    
    #store offset constants
    p_offset = (np.mean(k), np.mean(m))
    A = m[0] - m[1]
    #define model function to fit to zero crossing
    #y = A * sin(2*pi * Hz * (x - tau)) + k * x + m
    func = lambda x, tau: A * np.sin(2 * pi * Hz * (x - tau)) + offset_func(x, *p_offset)
    
    
    #get true crossings
    true_crossings = []
    for indice, crossing in zip(zero_indices, approx_crossings):
        p0 = (crossing, )
        subset_start = max(indice - fit_window, 0.0)
        subset_end = min(indice + fit_window + 1, len(x_axis) - 1.0)
        x_subset = np.asarray(x_axis[subset_start:subset_end])
        y_subset = np.asarray(y_axis[subset_start:subset_end])
        #fit
        popt, pcov = curve_fit(func, x_subset, y_subset, p0)
        
        true_crossings.append(popt[0])
    
    
    return true_crossings
        
        
    
    
def _test_zero():
    _max, _min = peakdetect_zero_crossing(y,x)
def _test():
    _max, _min = peakdetect(y,x, delta=0.30)
    
    
def _test_graph():
    i = 10000
    x = np.linspace(0,3.7*pi,i)
    y = (0.3*np.sin(x) + np.sin(1.3 * x) + 0.9 * np.sin(4.2 * x) + 0.06 *
    np.random.randn(i))
    y *= -1
    x = range(i)
    
    _max, _min = peakdetect(y,x,750, 0.30)
    xm = [p[0] for p in _max]
    ym = [p[1] for p in _max]
    xn = [p[0] for p in _min]
    yn = [p[1] for p in _min]
    
    plot = pylab.plot(x,y)
    pylab.hold(True)
    pylab.plot(xm, ym, "r+")
    pylab.plot(xn, yn, "g+")
    
    _max, _min = peak_det_bad.peakdetect(y, 0.7, x)
    xm = [p[0] for p in _max]
    ym = [p[1] for p in _max]
    xn = [p[0] for p in _min]
    yn = [p[1] for p in _min]
    pylab.plot(xm, ym, "y*")
    pylab.plot(xn, yn, "k*")
    pylab.show()
    
def _test_graph_cross(window = 11):
    i = 10000
    x = np.linspace(0,8.7*pi,i)
    y = (2*np.sin(x) + 0.006 *
    np.random.randn(i))
    y *= -1
    pylab.plot(x,y)
    #pylab.show()
    
    
    crossings = zero_crossings_sine_fit(y,x, smooth_window = window)
    y_cross = [0] * len(crossings)
    
    
    plot = pylab.plot(x,y)
    pylab.hold(True)
    pylab.plot(crossings, y_cross, "b+")
    pylab.show()
    
def _is_array_like(arr):
    return isinstance(arr, (list, np.ndarray))

