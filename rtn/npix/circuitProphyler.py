# -*- coding: utf-8 -*-
"""
2019-06-13
@author: Maxime Beau, Neural Computations Lab, University College London

WARNING - DO NOT TRY TO ACTUALLY STORE DATA IN THE DATASET OBJECT, THIS WAS THE FLAW OF XTRADATAMANAGER!
INSTEAD, MEMORYMAP EVERYTHING IN THE ROUTINESMEMORY FOLDER
THE DATASET AND SUBSEQUENT CLASSES SHOULD BE CONECPTUALLY NOTHING BUT
1) WAYS TO INITIATE HIGH DATA PROCESSING
2) SYMBOLIC LINKS TO THE PROCESSED DATA STORED ON THE MACHINE

Circuit prophyler class: embeds a set of functions whose end goal is to represent a Neuropixels Dataset as a network
with nodes being characterized as cell types
and edges as putative connections.

It is exploiting all the basic Neuropixels routines as well as the python module NetworkX.

The way to use it is as follow:

# initiation
DPs = {'dataset name 1': path/to/dataset1,...} # dic listing the datasets paths
pro = Prophyler(DPs['dataset name 1'])

# Connect the graph
pro.connect_graph()

# Plot the graph
pro.plot_graph()

# Get N of putative connections of a given node spotted on the graph
pro.get_node_edges(node)

# Only keep a set of relevant nodes or edges and plot it again
pro.keep_edges(edges_list)
pro.keep_nodes_list(nodes_list)
pro.plot_graph()

# every graph operation of circuit prophyler can be performed on external networkx graphs
# provided with the argument 'src_graph'
g=pro.get_graph_copy(prophylerGraph='undigraph')
pro.keep_nodes_list(nodes_list, src_graph=g) # g itself will be modified, not need to do g=...
pro.plot_graph(graph_src=g)


"""


import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

import os
from ast import literal_eval as ale
import operator
import time
import imp
import os.path as op; opj=op.join
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
import numpy as np
import pandas as pd

import rtn
from rtn.utils import npa, sign, align_timeseries

from rtn.npix.io import read_spikeglx_meta, get_npix_sync, chan_map
from rtn.npix.gl import load_units_qualities
from rtn.npix.spk_wvf import get_depthSort_peakChans, get_peak_chan
                    
import networkx as nx

class Prophyler:
    '''
    For single probe recording:
    >>> dp = path/to/kilosort/output
    >>> pro = Prophyler(dp)
    
    Structure of pro: pro generated a networkx graph whose nodes correspond to the dataset units labeled as good.
    Bear in mind that the graph nodes are actual objects, instances of Unit(), making this structure more powerful
    Because the relevant rtn methods can be integrated either in the Dataset class (connections related stuff) or the Units class (individual units related stuff)
    
    If you want to access unit u:
    >>> pro.units[u]
    >>> pro.units[u].trn(): equivalent to rtn.npix.spk_t.trn(dp,u)
    
    The units can also be accessed through the 'unit' attributes of the graph nodes:
    >>> pro.graph.nodes[u]]['unit'].trn() returns the same thing as ds.units[u].trn()
    
    For multi probes recordings:
    >>> dp_dic = {'name_probe_1':'path/to/kilosort/output', ...
            }
    >>> multipro = Prophyler(dp_dic)
    
    multipro has the same structure as pro, but
    - nested into dictionaries for dataset-specific items: pro.dp becomes multipro.dp['name_probe_1'], pro.units becomes multipro.units['name_probe_1'] etc
    - still accessible directly for across-datasets items: pro.graph remains multipro.graph
    
    The way it works is:
        Thanks to the Unit class which takes in independently a given dataset and a given graph,
        it is possible to instanciate the Units with their own datasets but the same graph.
        
        The reference for the channel map is the
    '''
    
    
    def __init__(self, datapaths, sync_idx3A=2):

        # Handle datapaths format 
        typ_e=TypeError('''datapathd should be either a string to a kilosort path:
                        'path/to/kilosort/output1'
                        or a dict of such datapath strings:
                        {'name_probe_1':'path/to/kilosort/output1', ...}''')
        if type(datapaths) is dict:
            for i, v in datapaths.items():
                if type(i) is not str or type(v) is not str:
                    raise typ_e
                if not op.isdir(op.expanduser(v)):
                    raise FileNotFoundError('Directory {} not found!'.format(v))
        elif type(datapaths) is str:
            if not op.isdir(op.expanduser(datapaths)):
                    raise FileNotFoundError('{} not found!'.format(datapaths))
            else:
                datapaths={'prb1':datapaths}
        else:
            raise typ_e
        
        # Make an alphabetically indexed table of all fed datasets (if several)
        self.ds_table=pd.DataFrame(columns=['dataset_name', 'dp', 'probe'])
        for i, (prb, dp) in enumerate(datapaths.items()):
            self.ds_table.loc[i, 'dataset_name']=op.basename(dp)
            self.ds_table.loc[i, 'dp']=dp
            self.ds_table.loc[i, 'probe']=prb
        self.ds_table.insert(0, 'dataset_i', self.ds_table['dataset_name'].argsort()) # sort table by dataset_name alphabetically
        self.ds_table.sort_values('dataset_i', axis=0, inplace=True)
        self.ds_table.set_index('dataset_i', inplace=True)
        
        # Instanciate datasets and define the prophyler path, where the 'merged' data will be saved,
        # together with the dataset table, holding information about the datasets (indices, names, source paths etc)
        ds_names=''
        predirname=op.dirname(self.ds_table['dp'][0])
        self.ds={}
        for ds_i in self.ds_table.index:
            dp, prb = self.ds_table.loc[ds_i, 'dp'], self.ds_table.loc[ds_i, 'probe']
            self.ds[ds_i]=Dataset(dp, prb, ds_i)
            ds_names+='_'+self.ds[ds_i].name
            if predirname!=op.dirname(dp):
                print('WARNING: all your datasets are not stored in the same pre-directory - {} is picked anyway.'.format(predirname))
        self.dp_pro=opj(predirname, 'prophyler'+ds_names)
        print('Prophyler data (shared across {} dataset(s)) will be saved here: {}.'.format(len(self.ds_table.index), self.dp_pro))
        if not op.isdir(self.dp_pro):
            os.mkdir(self.dp_pro)
        else:
            ds_table=pd.read_csv(opj(self.dp_pro, 'datasets_table.csv'), index_col='dataset_i')
            for ds_i in ds_table.index:
                try:
                    assert self.ds_table.loc[ds_i, 'probe']==ds_table.loc[ds_i, 'probe']
                except:
                    print('''WARNING you ran circuit prophyler on these {} datasets in the past \
                              but used the probe names {} for datasets {} ({} currently)!! Using new probe names. \
                              If you wish to use the same probe names as before, re-instanciate prophyler with these.\
                              '''.format(len(self.ds_table.index), ds_table['probe'].tolist(), ds_table.index.tolist(), self.ds_table['probe'].tolist()))
            del ds_table
        self.ds_table.to_csv(opj(self.dp_pro, 'datasets_table.csv'))
        
        # Load and save units qualities
        # + check whether datasets have been re-spike sorted if not first instanciation
        re_spksorted=False
        qualities=pd.DataFrame(columns=['dataset_i', 'cluster_id', 'group'])
        for ds_i in self.ds_table.index:
            cl_grp = load_units_qualities(self.ds[ds_i].dp)
            cl_grp.insert(0, 'dataset_i', ds_i)
            qualities=qualities.append(cl_grp, ignore_index=True)
        qualities.set_index('dataset_i', inplace=True)
        qualities_dp=opj(self.dp_pro, 'merged_cluster_group.tsv')
        if op.exists(qualities_dp):
            qualities_old=pd.read_csv(qualities_dp, sep='	')
            # only consider re-spike sorted if cluster indices have been changed, do not if only qualities were changed (spike times are unimpacted by that)
            if not np.all(qualities.loc[:, 'dataset_i':'cluster_id']==qualities_old).loc[:, 'dataset_i':'cluster_id']:
                re_spksorted=True
        qualities.to_csv(qualities_dp, sep='	')

        # If several datasets are fed to the prophyler, align their spike times.
        if len(self.ds_table.index)>1:
            # Only if merged_clusters_times does not exist already or does but re-spikesorting has been detected
            merge_fname='merged_clusters_spikes'
            if (not op.exists(opj(self.dp_pro, merge_fname+'.npy'))) or re_spksorted:
                print("Loading independent spike trains of {} datasets...".format(len(self.ds_table.index)))
                spike_times, spike_clusters, sync_signals = [], [], []
                for ds_i in self.ds_table.index:
                    ds=self.ds[ds_i]
                    ons, offs = get_npix_sync(ds.dp)
                    spike_times.append(np.load(opj(ds.dp, 'spike_times.npy')).flatten())
                    spike_clusters.append(np.load(opj(ds.dp, 'spike_clusters.npy')).flatten())
                    if ds.probe_version == '3A':
                        ds.sync_chan_ons=ons[sync_idx3A]
                    elif ds.probe_version in ['1.0_staggered', '1.0_aligned', '2.0_singleshank', '2.0_fourshanked']:
                        ds.sync_chan_ons=ons[6]
                    sync_signals.append(ds.sync_chan_ons)
                NspikesTotal=0
                for i in range(len(spike_times)): NspikesTotal+=len(spike_times[i])
                
                print("Aligning spike trains of {} datasets...".format(len(self.ds_table.index)))
                spike_times = align_timeseries(spike_times, sync_signals)
                merged_clusters_spikes=npa(zeros=(NspikesTotal, 3), dtype=np.uint64) # 1:dataset index, 2:unit index
                cum_Nspikes=0
                for ds_i in self.ds_table.index:
                    Nspikes=len(spike_times[ds_i])
                    merged_clusters_spikes[cum_Nspikes:cum_Nspikes+Nspikes, 0]=npa(ones=(Nspikes))*ds_i
                    merged_clusters_spikes[cum_Nspikes:cum_Nspikes+Nspikes, 1]=spike_clusters[ds_i]
                    merged_clusters_spikes[cum_Nspikes:cum_Nspikes+Nspikes, 2]=spike_times[ds_i]
                    cum_Nspikes+=Nspikes
                merged_clusters_spikes=merged_clusters_spikes[np.argsort(merged_clusters_spikes[:,2])]
                np.save(opj(self.dp_pro, merge_fname+'.npy'), merged_clusters_spikes)
                print('{} saved at {}.'.format(merge_fname+'.npy', self.dp_pro))
                self.merged_clusters_spikes=np.memmap(opj(self.dp_pro, merge_fname+'.npy'))
                del spike_times, spike_clusters, sync_signals, merged_clusters_spikes
            
            print('{} found at {} and memory mapped at self.merged_clusters_spikes.'.format(merge_fname+'.npy', self.dp_pro))
            self.merged_clusters_spikes=np.memmap(opj(self.dp_pro, merge_fname+'.npy'))
        
        # CREATE A KEYWORD IN CCG FUNCTION: MERGED_DATASET=TRUE OR FALSE - IF TRUE, HANDLES LOADED FILE AS 3xNspikes ARRAY RATHER THAN 2 LOADED ARRAYS
        
        # Create a networkX graph whose nodes are Units()
        self.undigraph=nx.MultiGraph() # Undirected multigraph - directionality is given by uSrc and uTrg. Several peaks -> several edges -> multigraph.
        self.dpnet=opj(self.dp_pro, 'network')
        if not op.isdir(self.dpnet): os.mkdir(self.dpnet)
        
        self.units={}
        for ds_i in self.ds_table.index:
            ds=self.ds[ds_i]
            ds.get_peak_positions()
            for u in ds.get_good_units():
                unit=Unit(ds, u, self.undigraph) # Units are added to the same graph when initialized, even from different source datasets
                self.units[unit.nodename]=unit
    
    def get_graph(self, prophylerGraph='undigraph'):
        assert prophylerGraph in ['undigraph', 'digraph']
        if prophylerGraph=='undigraph':
            return self.undigraph
        elif prophylerGraph=='digraph':
            return self.digraph
        else:
            print("WARNING graph should be either 'undigraphundigraph=nx.MultiGraph()' to pick self.undigraph or 'digraph' to pick self.digaph. Aborting.")
            return
        
    def get_graph_copy(self, prophylerGraph='undigraph'):
        return self.get_graph(prophylerGraph).copy()
        
    ##TODO
    def connect_graph(self, cbin=0.2, cwin=100, threshold=2, n_consec_bins=3, rec_section='all', again=False, againCCG=False, plotsfcdf=False, prophylerGraph='undigraph', src_graph=None):
        
        g=self.get_graph(prophylerGraph) if src_graph is None else src_graph
        if g is None: return
        
        g.remove_edges_from(list(g.edges)) # reset
        graphs=[]
        for f in os.listdir(self.dpnet):
            if 'graph' in f:
                graphs.append(f)
        if len(graphs)>0:
            while 1:
                load_choice=input("""Saved graphs found in {}:{}.
                      Dial a filename index to load it, or <sfc> to build it from the significant functional correlations table:""".format(opj(self.dp, 'graph'), ["{}:{}".format(gi, g) for gi, g in enumerate(graphs)]))
                try: # works if an int is inputed
                    load_choice=int(ale(load_choice))
                    g=self.import_graph(opj(self.dpnet, graphs[load_choice]))
                    print("Building Dataset.graph from file {}.".format(graphs[load_choice]))
                    if graphs[load_choice].split('.')[-1]!='gpickle':
                        print("WARNING loaded does not have gpickle format - 'unit' attribute of graph nodes are not saved in this file.")
                    break
                except: # must be a normal or empty string
                    if load_choice=='sfc':
                        print("Building graph connections from significant functional correlations table with cbin={}, cwin={}, threshold={}, n_consec_bins={}".format(cbin, cwin, threshold, n_consec_bins))
                        ## TODO: JUST ALTER THIS FUNCTION
                        SFCDF, SFCM1, gu, bestChs, SFCMtime = rtn.npix.corr.gen_sfc(self.dp_pro, cbin, cwin, threshold, n_consec_bins, rec_section, again=again, againCCG=againCCG)
                        g = map_sfcdf_on_graph(SFCDF, g, cbin, cwin, threshold, n_consec_bins)
                        del SFCDF, SFCM1, gu, bestChs, SFCMtime
                        if plotsfcdf:rtn.npix.plot.plot_sfcdf(self.dp_pro, cbin, cwin, threshold, n_consec_bins, text=False, markers=False, 
                                                     rec_section=rec_section, ticks=False, again = again, saveFig=True, saveDir=self.dpnet)
                        break
                    elif op.isfile(opj(self.dpnet, load_choice)):
                        g=self.import_graph(opj(self.dpnet, load_choice))
                        print("Building Dataset.graph from file {}.".format(load_choice))
                        if load_choice.split('.')[-1]!='gpickle':
                            print("WARNING loaded does not have gpickle format - 'unit' attribute of graph nodes are not saved in this file.")
                        break
                    else:
                        print("Filename or 'sfc' misspelled. Try again.")
        else:
            ## TODO: JUST ALTER THIS FUNCTION
            print("Building graph connections from significant functional correlations table with cbin={}, cwin={}, threshold={}, n_consec_bins={}".format(cbin, cwin, threshold, n_consec_bins))
            rtn.npix.corr.gen_sfc(self.dp_pro, cbin, cwin, threshold, n_consec_bins, rec_section, graph=g, again=again, againCCG=againCCG)
            if plotsfcdf: rtn.npix.plot.plot_sfcdf(self.dp_pro, cbin, cwin, threshold, n_consec_bins, text=False, markers=False, 
                                                     rec_section=rec_section, ticks=False, again=again, saveFig=True, saveDir=self.dpnet)
    
    def make_directed_graph(self, src_graph=None, only_main_edges=False):
        '''
        Should be called once the edges have been manually curated:
        - if several edges remain between pairs of nodes and only_main_edge is set to True, the one with the biggest standard deviation is kept
        - if the edge a->b has t<-t_asym ms: directed b->a, >t_asym ms: directed a->b, -t_asym ms<t<t_asym ms: a->b AND b->a (use uSrc and uTrg to figure out who's a and b)
        
        The directed graph is built on the basis of the undirected graph hence no amplitude criteria (except from the case where only_main_edge is True)is used to build it, only time asymmetry criteria.
        To modify the 'significance' criteria of modulated crosscorrelograms, use self.connect_graph() parameters.
        
        if t_asym is negative, peaks within the -t_asym, t_asym span will be bidirectionally drawn.
        '''
        g=self.get_graph('undigraph') if src_graph is None else src_graph
        if g is None: return
        
            
            
        # self.undigraph becomes a directed graph, its undirected version is saved as self.undigraph
        digraph=nx.MultiDiGraph()
        digraph.add_nodes_from(g.nodes(data=True))
        
        # - if several edges between pairs of nodes, keep the one with the biggest standard deviation
        # - if the edge a->b has t<-1ms: directed b->a, >1ms: directed a->b, -1ms<t<1ms: a->b AND b->a (use uSrc and uTrg to figure out who's a and b)
        
        if only_main_edges:
            self.keep_edges(prophylerGraph='undigraph', src_graph=g, edges_type='main')
        for edge in self.get_edges(frmt='list', src_graph=g):
            uSrc=self.get_edge_attribute(edge, 'uSrc', prophylerGraph='undigraph', src_graph=src_graph)
            uTrg=self.get_edge_attribute(edge, 'uTrg', prophylerGraph='undigraph', src_graph=src_graph)
            t=self.get_edge_attribute(edge, 't', prophylerGraph='undigraph', src_graph=src_graph)
            amp=self.get_edge_attribute(edge, 'amp', prophylerGraph='undigraph', src_graph=src_graph)
            width=self.get_edge_attribute(edge, 'width', prophylerGraph='undigraph', src_graph=src_graph)
            label=self.get_edge_attribute(edge, 'label', prophylerGraph='undigraph', src_graph=src_graph)
            criteria=self.get_edge_attribute(edge, 'criteria', prophylerGraph='undigraph', src_graph=src_graph)
            
            # Just make all the edges directed
            if t>0: # if close to 0 bidirectional, if >1 
                digraph.add_edge(uSrc, uTrg, uSrc=uSrc, uTrg=uTrg, 
                                                   amp=amp, t=t, sign=sign(amp), width=width, label=label,
                                                   criteria=criteria)
            if t<0:
                digraph.add_edge(uTrg, uSrc, uSrc=uSrc, uTrg=uTrg, 
                                                   amp=amp, t=t, sign=sign(amp), width=width, label=label,
                                                   criteria=criteria)
        
        if src_graph is None:
            self.digraph=digraph.copy()
        else:
            return digraph
            

    def get_nodes(self, frmt='array', prophylerGraph='undigraph', src_graph=None):
        g=self.get_graph(prophylerGraph) if src_graph is None else src_graph
        if g is None: return
        
        assert frmt in ['list', 'array', 'dict', 'dataframe']
        
        if frmt=='dict':
            nodes={}
            for n, na in g.nodes(data=True):
                nodes[n]=na
            if frmt=='dataframe':
                nodes=pd.DataFrame(data=nodes) # multiIndexed dataframe where lines are attributes and collumns edges
                nodes=nodes.T
        else:
            nodes=list(g.nodes())
            if frmt=='array':
                nodes=npa(nodes)
        
        return nodes
    
    def get_edges(self, frmt='array', keys=True, prophylerGraph='undigraph', src_graph=None):
        g=self.get_graph(prophylerGraph) if src_graph is None else src_graph
        if g is None: return
        
        assert frmt in ['list', 'array', 'dict', 'dataframe']
        
        if frmt in ['dict', 'dataframe']:
            edges={}
            for e in g.edges(data=True, keys=keys):
                edges[e[0:-1]]=e[-1]
            if frmt=='dataframe':
                edges=pd.DataFrame(data=edges) # multiIndexed dataframe where lines are attributes and collumns edges
                edges=edges.T
                edges.index.names=['node1', 'node2', 'key']
        else:
            edges=list(g.edges(keys=keys))
            if frmt=='array':
                edges=npa(edges)
        return edges
    
    def get_node_attributes(self, n, prophylerGraph='undigraph', src_graph=None):
        return self.get_nodes(frmt='dict', prophylerGraph=prophylerGraph, src_graph=src_graph)[n]
    
    def get_node_attribute(self, n, at, prophylerGraph='undigraph', src_graph=None):        
        assert at in ['unit', 'groundtruthCellType', 'classifiedCellType']
        return self.get_node_attributes(n, prophylerGraph, src_graph)[at]

    def set_node_attribute(self, n, at, at_val, prophylerGraph='undigraph', src_graph=None):
        g=self.get_graph(prophylerGraph) if src_graph is None else src_graph
        if g is None: return
        
        assert at in ['unit', 'groundtruthCellType', 'classifiedCellType']
        nx.set_node_attributes(g, {n:{at:at_val}})

    def get_edge_keys(self, e, prophylerGraph='undigraph', src_graph=None):
        assert len(e)==2
        npe=self.get_edges(prophylerGraph=prophylerGraph, src_graph=src_graph)
        keys=npe[((npe[:,0]==e[0])&(npe[:,1]==e[1]))|((npe[:,0]==e[1])&(npe[:,1]==e[0]))][:,2]
        return keys

    def get_edge_attributes(self, e, prophylerGraph='undigraph', src_graph=None):
        
        assert len(e)==2 or len(e)==3
        if len(e)==3:
            try: # check that nodes are in the right order - multi directed graph
                return self.get_edges(frmt='dict', prophylerGraph=prophylerGraph, src_graph=src_graph)[e]
            except:
                return self.get_edges(frmt='dict', prophylerGraph=prophylerGraph, src_graph=src_graph)[(e[1],e[0],e[2])]
        elif len(e)==2:
            keys=self.get_edge_keys(e, prophylerGraph=prophylerGraph, src_graph=src_graph)
            edges={}
            for k in keys:
                try: # check that nodes are in the right order - multi directed graph
                    edges[k]=self.get_edges(frmt='dict', prophylerGraph=prophylerGraph, src_graph=src_graph)[(e[0],e[1],k)]
                except:
                    edges[k]=self.get_edges(frmt='dict', prophylerGraph=prophylerGraph, src_graph=src_graph)[(e[1],e[0],k)]
            return edges

    def get_edge_attribute(self, e, at, prophylerGraph='undigraph', src_graph=None):
        
        assert at in ['uSrc','uTrg','amp','t','sign','width','label','criteria']
        return self.get_edge_attributes(e, prophylerGraph, src_graph)[at]

    def set_edge_attribute(self, e, at, at_val, prophylerGraph='undigraph', src_graph=None):
        g=self.get_graph(prophylerGraph) if src_graph is None else src_graph
        if g is None: return
        
        assert at in ['uSrc','uTrg','amp','t','sign','width','label','criteria']
        nx.set_edge_attributes(g, {e:{at:at_val}})

    def get_edges_with_attribute(self, at, at_val, logical='==', tolist=True, prophylerGraph='undigraph', src_graph=None):
        edges=self.get_edges(frmt='dataframe', keys=True, prophylerGraph=prophylerGraph, src_graph=src_graph) # raws are attributes, columns indices
        assert at in edges.index
        ops={'==':operator.eq, '!=':operator.ne, '<':operator.lt, '<=':operator.le, '>':operator.gt, '>=':operator.ge}
        assert logical in ops.keys()
        ewa=edges.columns[ops[logical](edges.loc[at,:], at_val)]
        return ewa.to_list() if tolist else ewa
    

    def get_node_edges(self, u, prophylerGraph='undigraph', src_graph=None):
        g=self.get_graph(prophylerGraph) if src_graph is None else src_graph
        if g is None: return
        node_edges={}
        for dsiunt, e_unt in g[u].items():
            dsi, unt = dsiunt.split('_')
            node_edges[unt]=[len(e_unt), '@{}'.format(self.ds[dsi].peak_channels[self.ds[dsi].peak_channels[:,0]==unt, 0])]
            
        return node_edges
    
    def keep_nodes_list(self, nodes_list, prophylerGraph='undigraph', src_graph=None):
        '''
        Remove edges not in edges_list if provided.
        edges_list can be a list of [(u1, u2),] 2elements tuples or [(u1,u2,key),] 3 elements tuples.
        If 3 elements, the key is ignored and all edges between u1 and u2 already present in self.undigraph are kept.
        
        if src_graph is provided, operations are performed on it and the resulting graph is returned.
        else, nothing is returned since operations are performed on self attribute undigraph or digraph.
        '''
        g=self.get_graph(prophylerGraph) if src_graph is None else src_graph
        if g is None: return
        
        if len(nodes_list)==0:
            return g
        npn=npa(self.get_nodes(prophylerGraph=prophylerGraph, src_graph=src_graph))
        nodes_list_idx=npa([])
        for n in nodes_list:
            try:
                #keys=self.get_edge_keys(e, prophylerGraph=prophylerGraph)
                #assert np.any((((npe[:,0]==e[0])&(npe[:,1]==e[1]))|((npe[:,0]==e[1])&(npe[:,1]==e[0]))))
                nodes_list_idx=np.append(nodes_list_idx, np.nonzero(npn==n)[0])
            except:
                print('WARNING edge {} does not exist in graph {}! Abort.'.format(n, g))
        nodes_list_idx=npa(nodes_list_idx, dtype=np.int64)
        nodes_to_remove=npn[~np.isin(np.arange(len(npn)),nodes_list_idx)]
        g.remove_nodes_from(nodes_to_remove) 
        
        # if g is set as self.undigraph or self.digraph, they actually point to the same object and self attribute gets updated!
        # So no need to explicit 'if src_graph is None: self.undigraph=g' or whatever
        if src_graph is not None:
            return g
    
    def keep_edges(self, edges_list=None, edges_type=None, prophylerGraph='undigraph', src_graph=None, use_edge_key=True, t_asym=1):
        '''
        Remove edges not in edges_list if provided.
        edges_list can be a list of [(u1, u2),] 2elements tuples or [(u1,u2,key),] 3 elements tuples.
        If 3 elements, the key is ignored and all edges between u1 and u2 already present in self.undigraph are kept.
        
        if src_graph is provided, operations are performed on it and the resulting graph is returned.
        else, nothing is returned since operations are performed on self attribute undigraph or digraph.
        
        edges_type must be in ['main', '-', '+', 'ci']# ci stands for common input.
        If edges_list is not None, the edges_list is kept and edges_type argument is ignored.
        '''
        g=self.get_graph(prophylerGraph) if src_graph is None else src_graph
        if g is None: return
        if edges_list is None and edges_type is None:
            print('WARNING you should not call keep_edges() without providing any edges_list or edges_type to keep. Aborting.')
            return
        assert edges_type in ['main', '-', '+', 'ci']# ci stands for common input
        
        # Select edges to keep if necessary
        if edges_list is None:
            dfe=self.get_edges(frmt='dataframe', prophylerGraph=prophylerGraph, src_graph=src_graph)
            amp=dfe.loc[:,'amp']
            t=dfe.loc[:, 't']
            if edges_type=='main':
                if not np.any(dfe):
                    print('WARNING no edges found in graph{}! Use the method connect_graph() first. aborting.')
                    return
                #dfe.reset_index(inplace=True) # turn node1, node 2 and key in columns
                keys=dfe.index.get_level_values('key')
                # multiedges are rows where key is 1 or more - to get the list of edges with more than 1 edge, get unit couples with key=1
                multiedges=npa(dfe.index[keys==1].tolist())
                multiedges[:,:2]=np.sort(multiedges[:,:2], axis=1)
                multiedges=np.unique(multiedges, axis=0)
                multiedges=[tuple(me) for me in multiedges]
                npe=self.get_edges(prophylerGraph='undigraph', src_graph=src_graph)
                for me in multiedges:
                    me_subedges=npe[(((npe[:,0]==me[0])&(npe[:,1]==me[1]))|((npe[:,0]==me[1])&(npe[:,1]==me[0])))]
                    me_subedges=[tuple(mese) for mese in me_subedges]
                    me_amps=dfe['amp'][me_subedges]
                    subedge_to_keep=me_amps.index[me_amps.abs()==me_amps.abs().max()]
                    subedges_to_drop=me_amps.drop(subedge_to_keep).index.tolist()
                    dfe.drop(subedges_to_drop, inplace=True)
                edges_list=dfe.index.tolist()
            
            elif edges_type=='-':
                edges_list=dfe.index[(amp<0)&((t<-t_asym)|(t>t_asym))].tolist()
                
            elif edges_type=='+':
                ci=dfe.index[(amp>0)&(t>-t_asym)&(t<t_asym)].tolist()
                edges_list=dfe.index[(amp>0)&((t<-t_asym)|(t>t_asym))].tolist()
                [edges_list.remove(ci_e) for ci_e in ci]
                
            elif edges_type=='ci':
                edges_list=dfe.index[(amp>0)&(t>-t_asym)&(t<t_asym)].tolist()
                
            else: # includes 'all'
                edges_list=[]
        
        # Drop edges not in the list of edges to keep
        if use_edge_key and len(edges_list[0])!=3:
            print('WARNING use_edge_key is set to True but edges of provided edges_list do not contain any key. Setting use_edge_key to False-> every edges between given pairs of nodes will be kept.')
            use_edge_key=False
        if len(edges_list)==0:
            return g
        npe=self.get_edges(prophylerGraph=prophylerGraph, src_graph=src_graph)
        edges_list_idx=npa([])
        for e in edges_list:
            try:
                if use_edge_key:
                    if g.__class__ is nx.classes.multidigraph.MultiDiGraph:
                        edges_list_idx=np.append(edges_list_idx, np.nonzero(((npe[:,0]==e[0])&(npe[:,1]==e[1])&(npe[:,2]==e[2])))[0])
                    elif g.__class__ is nx.classes.multigraph.MultiGraph:
                        edges_list_idx=np.append(edges_list_idx, np.nonzero((((npe[:,0]==e[0])&(npe[:,1]==e[1])&(npe[:,2]==e[2]))|((npe[:,0]==e[1])&(npe[:,1]==e[0])&(npe[:,2]==e[2]))))[0])
                else:
                    if g.__class__ is nx.classes.multidigraph.MultiDiGraph:
                        edges_list_idx=np.append(edges_list_idx, np.nonzero(((npe[:,0]==e[0])&(npe[:,1]==e[1])))[0])
                    elif g.__class__ is nx.classes.multigraph.MultiGraph:
                        edges_list_idx=np.append(edges_list_idx, np.nonzero((((npe[:,0]==e[0])&(npe[:,1]==e[1]))|((npe[:,0]==e[1])&(npe[:,1]==e[0]))))[0])
            except:
                print('WARNING edge {} does not exist in graph {}! Abort.'.format(e, g))
        edges_list_idx=npa(edges_list_idx, dtype=np.int64).flatten()
        edges_to_remove=npe[~np.isin(np.arange(len(npe)),edges_list_idx)]
        g.remove_edges_from(edges_to_remove)
    
    def label_nodes(self, prophylerGraph='undigraph', src_graph=None):
        g=self.get_graph(prophylerGraph) if src_graph is None else src_graph
        if g is None: return
        
        for node in g.nodes:
            label=''
            while label=='': # if enter is hit
                label=input("\n\n || Unit {}- label?(<n> to skip):".format(node))
                if label=='n':
                    label=0 # status quo
                    break
            
            if src_graph is not None:
                g=self.set_node_attribute(node, 'groundtruthCellType', label, prophylerGraph=prophylerGraph, src_graph=src_graph) # update graph
            else:
                self.set_node_attribute(node, 'groundtruthCellType', label, prophylerGraph=prophylerGraph, src_graph=src_graph) # update graph
            dsi, idx = node.split('_')
            self.units[dsi][idx].groundtruthCellType=label # Update class
            print("Label of node {} was set to {}.\n".format(node, label))
            
    def label_edges(self, prophylerGraph='undigraph', src_graph=None):
        g=self.get_graph(prophylerGraph) if src_graph is None else src_graph
        if g is None: return
        
        edges_types=['asym_inh', 'sym_inh', 'asym_exc', 'sym_exc', 'inh_exc', 'PC_CNC', 'CS_SS', 'oscill']
        
        if g.number_of_edges==0:
            print("""No edge detected - connect the graph first by calling
                  Dataset.connect_graph(cbin, cwin, threshold, n_consec_bins, rec_section, again)
                  You will be offered to load a pre-labelled graph if you ever saved one.""")
            return
        
        n_edges_init=g.number_of_edges()
        for ei, edge in enumerate(list(g.edges)):
            ea=self.get_edge_attributes(edge, prophylerGraph=prophylerGraph, src_graph=src_graph) # u1, u2, i unpacked
            
            ##TODO - plt ccg from shared directory
            rtn.npix.plot.plot_ccg(self.dp, [ea['uSrc'],ea['uTrg']], ea['criteria']['cbin'], ea['criteria']['cwin'])
            
            label=''
            while label=='': # if enter is hit
                print(" \n\n || Edge {}/{} ({} deleted so far)...".format(ei, n_edges_init, n_edges_init-g.number_of_edges()))
                print(" || {0}->{1} (multiedge {2}) sig. corr.: \x1b[1m\x1b[36m{3:.2f}\x1b[0msd high, \x1b[1m\x1b[36m{4:.2f}\x1b[0mms wide, @\x1b[1m\x1b[36m{5:.2f}\x1b[0mms".format(ea['uSrc'], ea['uTrg'], edge[2], ea['amp'], ea['width'], ea['t']))
                print(" || Total edges of source unit: {}".format(self.get_node_edges(ea['uSrc'], prophylerGraph=prophylerGraph)))
                label=input(" || Current label: {}. New label? ({},\n || <s> to skip, <del> to delete edge, <done> to exit):".format(self.get_edge_attribute(edge,'label'), ['<{}>:{}'.format(i,v) for i,v in enumerate(edges_types)]))
                try: # Will only work if integer is inputted
                    label=ale(label)
                    label=edges_types[label]
                    self.set_edge_attribute(edge, 'label', label, prophylerGraph=prophylerGraph, src_graph=src_graph) # if src_graph is None, nothing will be returned
                    print(" || Label of edge {} was set to {}.\n".format(edge, label))
                except:
                    if label=='del':
                        g.remove_edge(*edge)
                        print(" || Edge {} was deleted.".format(edge))
                        break
                    elif label=='s':
                        self.set_edge_attribute(edge, 'label', 0, prophylerGraph=prophylerGraph, src_graph=src_graph) # status quo
                        break
                    elif label=='':
                        print("Whoops, looks like you hit enter. You cannot leave unnamed edges. Try again.")
                    elif label=="done":
                        print(" || Done - exitting.")
                        break
                    else:
                        self.set_edge_attribute(edge, 'label', label, prophylerGraph=prophylerGraph, src_graph=src_graph)
                        print(" || Label of edge {} was set to {}.\n".format(edge, label))
                        break
            if label=="done":
                break
        
        while 1:
            save=input("\n\n || Do you wish to save your graph with labeled edges? <any>|<enter> to save it, else <n>:")
            if save=='n':
                print(" || Not saving. You can still save the graph later by running ds.export_graph(name, frmt) with frmt in ['edgelist', 'adjlist', 'gexf', 'gml'] (default gpickle).")
                break
            else:
                pass
            name=input(" || Saving graph with newly labelled edges as graph_<name>. Name (<t> for aaaa-mm-dd_hh:mm:ss format):")
            while 1:
                formats=['gpickle', 'gexf', 'edgelist', 'adjlist', 'gml']
                frmt=input(" || In which format? {}".format(['<{}>:{}'.format(i,v) for i,v in enumerate(formats)]))
                try: # Will only work if integer is inputted
                    frmt=ale(frmt)
                    frmt=formats[frmt]
                    break
                except:
                    print(" || Pick an integer between {} and {}!".format(0, len(formats)-1))
                    pass
            
            file='graph_{}.{}'.format(name, frmt)
            if op.isfile(opj(self.dpnet,file)):
                ow=input(" || Warning, name already taken - overwrite? <y>/<n>:")
                if ow=='y':
                    print(" || Overwriting graph {}.".format(file))
                    self.export_graph(name, frmt, ow=True, prophylerGraph=prophylerGraph, src_graph=src_graph) # 'graph_' is always appended at the beginning of the file names. It allows to spot presaved graphs.
                    break
                elif ow=='n':
                    print(' || Ok, pick another name.')
                    pass
            else:
                print(" || Saving graph {}.".format(file))
                self.export_graph(name, frmt, prophylerGraph=prophylerGraph, src_graph=src_graph) # 'graph_' is always appended at the beginning of the file names. It allows to spot presaved graphs.
                break
    
    ## TODO - remove self.peakchannels from drawing - handle datasets independently
    def plot_graph(self, edge_labels=False, node_labels=True, prophylerGraph='undigraph', keep_edges_types=None, edges_list=None, src_graph=None, t_asym=1,
                   nodes_size=400, nodes_color='grey', nodes_outline_color='k', edges_width=5, edge_vmin=-7, edge_vmax=7, arrowsize=25, arrowstyle='-|>',
                   ylim=[4000, 0], figsize=(6, 24), show_cmap=True, png=False, pdf=True, saveDir='~/Desktop', saveFig=False):
        '''
        2 ways to select edges:
            - Provide a list of edges (fully customizable). Can be used with self.get_edges_with_attribute(at, at_val)
            - Pick a edges_type (predefined groups of edges): 'all' for everyone (default)
              '+': edges whose t is >1ms or <-1ms and sign is 1,
              '-': edges whose t is >1ms or <-1ms and sign is -1,
              'sync': edges whose t is >1ms or <-1ms and sign is 1
        
        edges_list has the priority over edges_types.
        edges_type must be '-', '+', 'main', 'ci' or a list of either combination of these. Edges will be filtered ('kept') sequentially with respect to the order of these categories.
        '''
        g=self.get_graph(prophylerGraph) if src_graph is None else src_graph
        if g is None: return
        
        g_plt=g.copy() # careful, do not create an alias but a copy or the original graph itself will be altered!
        
        # Remove edges not in edges_list if provided.
        # edges_list can be a list of [(u1, u2),] 2elements tuples or [(u1,u2,key),] 3 elements tuples.
        # If 3 elements, the key is ignored and all edges between u1 and u2 already present in self.undigraph are kept.
        if edges_list is not None:
            self.keep_edges(edges_list=edges_list, src_graph=g_plt, use_edge_key=True, t_asym=t_asym)
        if keep_edges_types is not None:
            if type(keep_edges_types)!=list: keep_edges_types = [keep_edges_types]
            for et in keep_edges_types:
                assert et in ['-', '+', 'ci', 'main']
                self.keep_edges(edges_type=et, src_graph=g_plt, use_edge_key=True, t_asym=t_asym)
        
        ew = [self.get_edge_attribute(e, 'amp', prophylerGraph=prophylerGraph, src_graph=src_graph) for e in g_plt.edges]
        e_labels={e[0:2]:str(np.round(self.get_edge_attribute(e, 'amp', prophylerGraph=prophylerGraph, src_graph=src_graph), 2))\
                  +'@'+str(np.round(self.get_edge_attribute(e, 't', prophylerGraph=prophylerGraph, src_graph=src_graph), 1))+'ms' for e in g_plt.edges}
        
        fig, ax = plt.subplots(figsize=figsize)
        if node_labels:
            nlabs={}
            for node in list(g_plt.nodes):
                pct=self.get_node_attribute(node, 'groundtruthCellType', prophylerGraph=prophylerGraph, src_graph=src_graph)
                cct=self.get_node_attribute(node, 'classifiedCellType', prophylerGraph=prophylerGraph, src_graph=src_graph)
                l="{}".format(node)
                if pct!='':
                    l+="\nput:{}".format(pct)
                if cct!='':
                    l+="\ncla:{}".format(cct)
                nlabs[node]=l
                
            nx.draw_networkx_labels(g_plt,self.peak_positions,nlabs, font_weight='bold', font_color='#000000FF', font_size=8)
            #nx.draw_networkx(g, pos=peak_pos, node_color='#FFFFFF00', edge_color='white', alpha=1, with_labels=True, font_weight='bold', font_color='#000000FF', font_size=6)
        nx.draw_networkx_nodes(g_plt, pos=self.peak_positions, node_color=nodes_color, edgecolors=nodes_outline_color, alpha=0.8, node_size=nodes_size)
        
        edges_cmap=plt.cm.RdBu_r
        nx.draw_networkx_edges(g_plt, pos=self.peak_positions, edge_color=ew, width=edges_width, alpha=1, 
                               edge_cmap=edges_cmap, edge_vmin=edge_vmin, edge_vmax=edge_vmax, arrowsize=arrowsize, arrowstyle=arrowstyle)
        if show_cmap:
            sm = plt.cm.ScalarMappable(cmap=edges_cmap, norm=plt.Normalize(vmin = edge_vmin, vmax=edge_vmax))
            sm._A = []
            axins = inset_axes(ax,
                   width="5%",  # width = 5% of parent_bbox width
                   height="10%",  # height : 50%
                   loc='lower left',
                   bbox_to_anchor=(1.15, 0., 1, 1),
                   bbox_transform=ax.transAxes,
                   borderpad=0,
                   )
            fig.colorbar(sm, cax=axins)#, ticks=np.arange(edge_vmin, edge_vmax, 2))
            axins.set_ylabel("z-score", labelpad=10, rotation=270, fontsize=12)

        if edge_labels:
            nx.draw_networkx_edge_labels(g_plt, pos=self.peak_positions, edge_labels=e_labels,font_color='black', font_size=8, font_weight='bold')

        ax.set_ylabel('Depth (um)', fontsize=16, fontweight='bold')
        ax.set_xlabel('Lat. position (um)', fontsize=16, fontweight='bold')
        ax.set_ylim(ylim)
        ax.set_xlim([0,70])
        ax.tick_params(axis='both', reset=True, labelsize=12)
        ax2 = ax.twinx()
        ax2.set_ylabel('Channel #', fontsize=16, fontweight='bold', rotation=270)
        ax2.set_yticks(ax.get_yticks())
        ax2.set_yticklabels([int(yt/10 - 16) for yt in ax.get_yticks()], fontsize=12)
        ax2.set_ylim(ylim[::-1])
        try:
            criteria=self.get_edge_attribute(list(g_plt.edges)[0], 'criteria', prophylerGraph=prophylerGraph, src_graph=src_graph)
            ax.set_title("Dataset:{}\n Significance criteria:{}".format(self.name, criteria))
        except:
            print('Graph not connected! Run self.connect_graph()')
        plt.tight_layout()
        
        if saveFig:
            saveDir=op.expanduser(saveDir)
            if not os.path.isdir(saveDir): os.mkdir(saveDir)
            if pdf: fig.savefig(saveDir+'/{}_graph_{}_{}-{}-{}-{}.pdf'.format(self.name, keep_edges_types, *criteria.values()))
            if png: fig.savefig(saveDir+'/{}_graph_{}_{}-{}-{}-{}.png'.format(self.name, keep_edges_types, *criteria.values()))
        
        return fig
    

    def export_graph(self, name='', frmt='gpickle', ow=False, prophylerGraph='undigraph', src_graph=None):
        '''
        name: any srting. If 't': will be graph_aaaa-mm-dd_hh:mm:ss
        frmt: any in ['edgelist', 'adjlist', 'gexf', 'gml'] (default gpickle)'''
        g=self.get_graph(prophylerGraph) if src_graph is None else src_graph
        if g is None: return
        
        assert frmt in ['edgelist', 'adjlist', 'gexf', 'gml', 'gpickle']
        file=opj(self.dpnet, prophylerGraph+'_'+name+'_'+op.basename(self.dp_pro)+'.'+frmt)
        filePickle=opj(self.dpnet, prophylerGraph+'_'+name+'_'+op.basename(self.dp_pro)+'.gpickle')
        
        if op.isfile(filePickle) and not ow:
            print("File name {} already taken. Pick another name or run the function with ow=True to overwrite file.")
            return
        
        nx_exp={'edgelist':nx.write_edgelist, 'adjlist':nx.write_adjlist,'gexf':nx.write_gexf, 'gml':nx.write_gml, 'gpickle':nx.write_gpickle}
        print(1, name)
        if name=='t':
            name=time.strftime("%Y-%m-%d_%H:%M:%S")
            print(2, name)
        nx_exp['gpickle'](g, filePickle) # Always export in edges list for internal compatibility
        
        if frmt!='gpickle':
            if frmt=='gml' or frmt=='gexf':
                print("GML or GEXF files can only process elements convertable into strings. Getting rid of nodes 'unit' attributes.")
                gc=g.copy()
                for n in g.nodes:
                    del gc.nodes[n]['unit']
                if frmt=='gml':
                    nx_exp[frmt](gc, file, stringizer=str) # np.int not handled... Need to explicitely tell it to use str() for non native python data types...
                elif frmt=='gexf':
                    nx_exp[frmt](gc, file)
            else:
                nx_exp[frmt](g, file)
    
    @staticmethod
    def import_graph(name):
        '''
        name: path to file to import, ending in '.edgelist', '.adjlist', '.gexf', '.gml' or '.gpickle'
        '''
        assert op.isfile(name)
        frmt=name.split('.')[-1]
        assert frmt in ['edgelist', 'adjlist', 'gexf', 'gml', 'gpickle']
        nx_exp={'edgelist':nx.read_edgelist, 'adjlist':nx.read_adjlist,'gexf':nx.read_gexf, 'gml':nx.read_gml, 'gpickle':nx.read_gpickle}
        
        return nx_exp[frmt](name)
                
    ## TODO - adapt export feat table by handling the new waveform function (and main channels finders etc)
    def export_feat(self, rec_section='all'):
        # TO SET HERE - RECORDING SECTIONS TO CONSIDER TO COMPUTE THE FEATURES TABLE
        endTime = int(np.load(opj(self.dp, 'spike_times.npy'))[-1]*1./self.fs +1)# above max in seconds
#                t1 = 0 # in seconds
#                t2 = 2000 # in seconds
#                rec_section = [(t1, t2)] # list of tuples (t1, t2) delimiting the recording sections in seconds
        rec_section = 'all' # Whole recording
        print('Recording sections used to perform units features extraction:{}'.format(rec_section))
        # Select the relevant clusters, either the ones selected in phy or the ones sorted as good
        allClusters = np.unique(controller.model.spike_clusters)
        goodClusters = np.array([])
        sortedClusters = np.array([])
        for unt in allClusters:
            quality = controller.supervisor.cluster_meta.get('group', unt)
            if quality=='good':
                goodClusters = np.append(goodClusters, unt)
            if quality=='good' or quality=='mua':
                sortedClusters = np.append(sortedClusters, unt)


        # Create or load FeaturesTable
        # All the Nans will be substituted by the mean of the axis at the end.
        Features = OrderedDict()
        
        Features["ISI-mfr"] = "Mean firing rate (Hz)." 
        Features["ISI-mifr"] = "Mean instantaneous firing rate (Hz)." 
        Features["ISI-med"] = "Median of the interspike intervals distribution."
        Features["ISI-mode"] = "Mode of the interspike intervals distribution."
        Features["ISI-prct5"] = "5th percentile of the interspike intervals distribution - low 5th percentile -> more burstiness."
        Features["ISI-entropy"] = "entropy (bits/ISI), see DugueTihyLena2017 or Dorval 2009 - large entropy -> neuron fires irregularly."
        Features["ISI-cv2"] = "Average coefficient of variation for a sequence of 2 ISIs."
        Features["ISI-cv"] = "Coefficient of variation of the interspike intervals distribution (sd in units of mean)."
        Features["ISI-ir"] = "Instantaneous irregularity - average of the absolute diff between the natural log of consecutive ISIs."
        Features["ISI-lv"] = "Local variation of ISIs."
        Features["ISI-lvr"] = "Revised local variation of ISIs."
        Features["ISI-lcv"] = "Coefficient of variation of the log ISIs."
        Features["ISI-si"] = "Geometric average of the rescaled cross-correlation of ISIs."
        Features["ISI-skew"] = "Skewness of the interspike intervals distribution (ms^3)"
        Features["ISI-ra"] = "Refractory area of the max-normalized ISI distribution, from 0 to the mode (a.u.*ms)."
        Features["ISI-rp"] = "Refractory period of the ISI distribution, from 0 to when it crosses 5% of max (ms)."

        Features["ACG-burst"] = "Presence of burst or not (0 or 1)"
        Features["ACG-mode"] = "Mode of the ACG, only if mode is found meaningful. Else, Nan."
        Features["ACG-do_a"] = "Autocorrelogram dampened oscillation amplitude (AU)"
        Features["ACG-do_t"] = "Autocorrelogram dampened oscillation decay constant (ms)"
        Features["ACG-do_f"] = "Autocorrelogram dampened oscillation frequency (Hz)"
        Features["ACG-Oscillatory"] = "Autocorrelogram considered oscillatory (do_a>=30 and do_t>=2 and do_f>=3) or not (0 or 1)"
        Features["ACG-class"] = "..."
        
        Features["WVF-tpw"] = "Waveform trough to peak width (us)"
        Features["WVF-ptr"] = "Waveform peak to trough ratio (unitless)"
        Features["WVF-es"] = "Waveform end slope (uV/us)"
        Features["WVF-MainChannel"] = "Channel where average waveform has max amplitude (Irrelevant for clustering unless coupled to histology)" # PSDpeaks
        Features["WVF-spat.dis"] = "Waveform spatial distribution (um - range where amplitude undershoots 10% of maximum)"
        
        FeaturesList = Features.keys()
        dp = controller.model.dir_path
        direct = dp+"/FeaturesTable"
        ft = load_featuresTable(direct, sortedClusters, FeaturesList)

        if custom:
            if os.path.isfile(direct+'featuresTable_custom.npy'):
                pass
            
        # Set the features extractors parameters
        # CAREFUL for ACG features: have to be calculated with window=80ms, binsize=0.1ms!!
        # fs = float(controller.model.sample_rate)
        acgw = 80 #ms, by definition to compute the acg features
        acgb = 0.2 #ms, by definition to compute acg features
        # max_waveforms_per_cluster=1e3

        # Fill the table with all the features of relevant clusters
        print("Start computing the features of all %d units."%len(sortedClusters))
        bar = progressbar.ProgressBar(maxval=len(sortedClusters), \
                widgets=[progressbar.Bar('=', '[', ']'), ' ', progressbar.Percentage()])
        bar.start()
        bar.update(0)
        
        # clustersSubset = sortedClusters[:10]
        for i, clust in enumerate(sortedClusters):
            print('WORKING ON CLUSTER %d...'%clust)
            bar.update(i+1)
            clust = int(clust)

            try:
                # InterSpike Intervals histogram features
                isint = isi(dp, clust, ret=True, sav=True, prnt=False, rec_section=rec_section)
                MFR, MIFR, medISI, modeISI, prct5ISI, entropyD, CV2, CV, IR, Lv, LvR, LcV, SI, SKW, ra, rp = compute_isi_features(isint)
                ft.loc[clust, 'ISI-mfr':'ISI-rp'] = [MFR, MIFR, medISI, modeISI, prct5ISI, entropyD, CV2, CV, IR, Lv, LvR, LcV, SI, SKW, ra, rp]
                #print(MFR, MIFR, medISI, modeISI, prct5ISI, entropyD, CV2, CV, IR, Lv, LvR, LcV, SI, SKW, ra, rp)
            except:
                print("    WARNING ISI Features of cluster %d could not be computed, and are set to NaN."%(clust))
                ft.loc[clust, 'ISI-mfr':'ISI-rp']=[np.nan]*16
            try:
                # Autocorrelogram features
#                        cluster_ids, bin_size, window_size = [clust], acgb*1./1000, acgw*1./1000
#                        spike_ids = controller.selector.select_spikes(cluster_ids,
#                                                                controller.n_spikes_correlograms,
#                                                                subset='random',
#                                                                )
#                        st = controller.model.spike_times[spike_ids]
#                        sc = controller.supervisor.clustering.spike_clusters[spike_ids]
#                        acgr = correlograms(st,
#                                            sc,
#                                            sample_rate=controller.model.sample_rate,
#                                            cluster_ids=cluster_ids,
#                                            bin_size=bin_size,
#                                            window_size=window_size,
#                                            )
                ACG=acg(dp, clust, acgb, acgw, fs=30000, normalize='Hertz', prnt=False, rec_section=rec_section)
                modes, smoothCCG, ACGburst, sm_storage, modeType = find_modes(ACG, acgw*1./1000, acgb*1./1000)#acgr[0,0,:], acgw*1./1000, acgb*1./1000)
                CCG_fitX, CCG_fitY, corParams, Oscillatory = evaluate_oscillation(smoothCCG, modes, acgb*1./1000, initial_guess=[2,2,2,2])
                ACGburst = int(ACGburst)
                ACGmode = max(modes) if (modeType=='Meaningful Mode' or Oscillatory) and max(modes)>4.5 else np.nan
                if Oscillatory:
                    ACGdo_a, ACGdo_t, ACGdo_f = corParams[0], corParams[1], corParams[2]
                else:
                    ACGdo_a, ACGdo_t, ACGdo_f = np.nan, np.nan, np.nan
                Oscillatory=1 if Oscillatory else 0 # Takes into account the None case (no fit possible) and the False case (thoughtfully considered non oscilatory)
                #print([ACGburst, ACGmode, ACGdo_a, ACGdo_t, ACGdo_f, Oscillatory, ACGrp])
                ft.loc[clust, "ACG-burst":"ACG-class"] = [ACGburst, ACGmode, ACGdo_a, ACGdo_t, ACGdo_f, Oscillatory, np.nan]
        
            except:
                print("    WARNING ACG Features of cluster %d could not be computed, and are set to NaN."%(clust))
                ft.loc[clust, "ACG-burst":"ACG-class"]=[np.nan]*7
            
            try:
                # Waveform features
                '''spike_ids = controller.selector.select_spikes([clust],
                                            max_waveforms_per_cluster,
                                            controller.batch_size_waveforms)
                channel_ids=np.arange(controller.model.n_channels_dat) #gets all channels
                wave = controller.model.get_waveforms(spike_ids, channel_ids)'''
                map_nchannels = np.load(opj(dp, 'channel_map.npy'), mmap_mode='r').squeeze().shape[0]
                bunchs_set = controller._get_waveforms(clust, channel_ids=np.arange(0, map_nchannels, 1)) ## HERE IT SHOULD BE 384 FOR REGULAR NEUROPIXELS RECORDINGS
                wave = bunchs_set.data #
                spl, peak, trough, sp_width, pt_ratio, endslope, ind_endslope, best_channel, wvf_amp = compute_waveforms_features(wave)
                if np.isnan(sp_width):
                    best_channel = int(np.squeeze(best_channel)) # They all remain nan except from best_channel
                else:
                    sp_width, pt_ratio, endslope, best_channel = float(np.squeeze(sp_width)), float(np.squeeze(pt_ratio)), float(np.squeeze(endslope)), int(np.squeeze(best_channel))
                ft.loc[clust, "WVF-tpw":"WVF-spat.dis"] = sp_width, pt_ratio, endslope, best_channel, np.nan
                #print('sp_width, pt_ratio, endslope' , sp_width, pt_ratio, endslope)
            except:
                print("    WARNING WVF Features of cluster %d could not be computed, and are set to NaN."%(clust))
                ft.loc[clust, "WVF-tpw":"WVF-spat.dis"]=[np.nan]*5
        bar.finish()


        # Save the updated features table
        save_featuresTable(direct, ft, goodClusters, Features)                              

def map_sfcdf_on_graph(sfcdf, g, cbin, cwin, threshold, n_consec_bins):
    # If called in the context of CircuitProphyler, add the connection to the graph
    for u1 in sfcdf.index:
        for u2 in sfcdf.index:
            pks=sfcdf.loc[u1, str(u2)]
            if type(pks) is str:
                pks=ale(pks)
                # pks with positive and negative peaks are present twice in the SFCDF (cf. case where pks='all' in find_significant_hist_peak)
                # these need to be only added if u1<u2
                pkSgns=npa([sign(p[2]) for p in pks])
                make_edges=False
                if np.all(pkSgns==1) or np.all(pkSgns==-1):
                    make_edges=True
                else:
                    if u1<u2:
                        make_edges=True
                if make_edges:
                    for p in pks:
                        g.add_edge(u1, u2, uSrc=u1, uTrg=u2, 
                                   amp=p[2], t=p[3], sign=sign(p[2]), width=p[1]-p[0], label=0,
                                   criteria={'cbin':cbin, 'cwin':cwin, 'threshold':threshold, 'nConsecBins':n_consec_bins})
    return g

class Dataset:
    
    def __repr__(self):
        return 'Neuropixels dataset at {}.'.format(self.dp)
    
    def __init__(self, datapath, probe_name='prb1', dataset_index=0, dataset_name=None):

        # Handle datapaths format 
        if type(datapath) is str:
            if not op.isdir(op.expanduser(datapath)):
                    raise FileNotFoundError('{} not found!'.format(datapath))
        else:
            raise TypeError('''datapath should be either a string to a kilosort path:
                        'path/to/kilosort/output1'.''')
        
        self.dp = op.expanduser(datapath)
        self.meta=read_spikeglx_meta(self.dp)
        self.probe_version=self.meta['probe_version']
        self.ds_i=dataset_index
        self.name=self.dp.split('/')[-1] if dataset_name is None else dataset_name
        self.prb_name=probe_name
        self.params={}; params=imp.load_source('params', opj(self.dp,'params.py'))
        for p in dir(params):
            exec("if '__'not in '{}': self.params['{}']=params.{}".format(p, p, p))
        self.fs=self.meta['sRateHz']
        self.endTime=int(np.load(opj(self.dp, 'spike_times.npy'))[-1]*1./self.fs +1)
        self.chan_map=chan_map(self.dp, y_orig='surface')
        assert np.all(np.isin(chan_map(self.dp, y_orig='surface', probe_version='local')[:,0], self.chan_map[:,0])), \
        "Local channel map comprises channels not found in expected channels given matafile probe type."
        
    def get_units(self):
        return rtn.npix.gl.get_units(self.dp)
    
    def get_good_units(self):
        return rtn.npix.gl.get_units(self.dp, quality='good')
    
    def get_peak_channels(self):
        self.peak_channels = get_depthSort_peakChans(self.dp, quality='good')# {mainChans[i,0]:mainChans[i,1] for i in range(mainChans.shape[0])}

        
    def get_peak_positions(self):
        self.get_peak_channels()
        peak_pos=npa(zeros=(self.peak_channels.shape[0], 3), dtype=np.int64)
        peak_pos[:,0]=self.peak_channels[:,0] # units
        pos_idx=[] # how to get rid of for loop??
        for ch in self.peak_channels[:,1]:
            pos_idx.append(np.nonzero(np.isin(self.chan_map[:,0], ch))[0][0])
        peak_pos[:,1:]=self.chan_map[:,1:][pos_idx, :]
        self.peak_positions_real=peak_pos
        
        # Homogeneously distributes neurons on same channels around mother channel to prevent overlap
        for pp in np.unique(peak_pos[:,1:], axis=0): # space positions if several units per channel
            boolarr=(pp[0]==peak_pos[:,1])&(pp[1]==peak_pos[:,2])
            n1=sum(x > 0 for x in boolarr)
            if n1>1:
                for i in range(n1):
                    x_spacing=16# x spacing is 32um
                    spacing=x_spacing*1./(n1+1) 
                    boolidx=np.nonzero(boolarr)[0][i]
                    peak_pos[boolidx,1]=peak_pos[boolidx,1]-x_spacing*1./2+(i+1)*spacing # 1 is index of x value
        self.peak_positions={int(pp[0]):pp[1:] for pp in peak_pos}
        
        
        
        
class Unit:
    '''The object Unit does not store anything itself except from its dataset and index.
    It makes it possible to call its various features.
    '''
    
    def __repr__(self):
        return 'Unit {} from dataset {}.'.format(self.idx, self.ds.name)
    
    def __init__(self, dataset, index, graph):
        self.ds=dataset
        self.dp = self.ds.dp
        self.idx=index
        self.putativeCellType='' # Set by the experimentalist manually
        self.groundtruthCellType='' # Either opto or because of cs/ss pause motif
        self.classifiedCellType='' # Output of the classifier
        self.undigraph = graph
        self.get_peak_position()
        # self refers to the instance not the class, hehe
        self.nodename=str(self.ds.ds_i)+'_'+str(self.idx)
        self.undigraph.add_node(self.nodename, unit=self, X=self.peak_position_real[0], Y=self.peak_position_real[1], posReal=self.peak_position_real, putativeCellType=self.putativeCellType, groundtruthCellType=self.groundtruthCellType, classifiedCellType=self.classifiedCellType) 
    
    def get_peak_channel(self):
        self.peak_channel=get_peak_chan(self.dp, self.idx)
        
    def get_peak_position(self):
        self.get_peak_channel()
        
        # Get peak channel xy positions
        self.peak_position_real=self.ds.peak_positions_real[self.idx==self.ds.peak_positions_real[:,0], 1:].flatten()
                    
    def trn(self, rec_section='all'):
        return rtn.npix.spk_t.trn(self.dp, self.idx, rec_section=rec_section)
    
    def trnb(self, bin_size, rec_section='all'):
        return rtn.npix.spk_t.trnb(self.dp, self.idx, bin_size, rec_section=rec_section)
    
    def ids(self):
        return rtn.npix.spk_t.ids(self.dp, self.idx)
    
    def isi(self, rec_section='all'):
        return rtn.npix.spk_t.isi(self.dp, self.idx, rec_section=rec_section)
    
    def acg(self, cbin, cwin, normalize='Hertz', rec_section='all'):
        return rtn.npix.corr.acg(self.dp, self.idx, bin_size=cbin, win_size=cwin, normalize=normalize, rec_section=rec_section)
    
    def ccg(self, U, cbin, cwin, fs=30000, normalize='Hertz', ret=True, sav=True, prnt=True, rec_section='all', again=False):
        return rtn.npix.corr.ccg(self.dp, [self.idx]+list(U), cbin, cwin, fs, normalize, ret, sav, prnt, rec_section, again)
    
    def wvf(self, n_waveforms=100, t_waveforms=82, wvf_subset_selection='regular', wvf_batch_size=10):
        return rtn.npix.spk_wvf.wvf(self.dp, self.idx, n_waveforms, t_waveforms, wvf_subset_selection, wvf_batch_size, True, True)
    
    def plot_acg(self, cbin=0.2, cwin=80, normalize='Hertz', color=0, saveDir='~/Downloads', saveFig=True, prnt=False, show=True, 
             pdf=True, png=False, rec_section='all', labels=True, title=None, ref_per=True, saveData=False, ylim=0):
        
        rtn.npix.plot.plot_acg(self.dp, self.idx, cbin, cwin, normalize, color, saveDir, saveFig, prnt, show, 
             pdf, png, rec_section, labels, title, ref_per, saveData, ylim)
    
    def plot_ccg(self, units, cbin=0.2, cwin=80, normalize='Hertz', saveDir='~/Downloads', saveFig=False, prnt=False, show=True,
             pdf=False, png=False, rec_section='all', labels=True, std_lines=True, title=None, color=-1, CCG=None, saveData=False, ylim=0):
        
        rtn.npix.plot.plot_ccg(self.dp, [self.idx]+list(units), cbin, cwin, normalize, saveDir, saveFig, prnt, show,
                 pdf, png, rec_section, labels, std_lines, title, color, CCG, saveData, ylim)
    
    def connections(self):
        return dict(self.undigraph[self.idx])
    
        

    # a=npa([ 0,  1,  2,  3,  9, 13, 16, 29])
    # aa=npa([ 0,  2, 13])
    
    # b=npa([ 3,  4,  5,  7, 13, 17, 21, 34]) # should be exactly a, but 2-shifted + 1 of drift after 6, 2 of drift after 18
    # bb=npa([3, 6, 18])
    
