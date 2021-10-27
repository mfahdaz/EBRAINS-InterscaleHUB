# ------------------------------------------------------------------------------
#  Copyright 2020 Forschungszentrum Jülich GmbH
# "Licensed to the Apache Software Foundation (ASF) under one or more contributor
#  license agreements; and to You under the Apache License, Version 2.0. "
#
# Forschungszentrum Jülich
#  Institute: Institute for Advanced Simulation (IAS)
#    Section: Jülich Supercomputing Centre (JSC)
#   Division: High Performance Computing in Neuroscience
# Laboratory: Simulation Laboratory Neuroscience
#       Team: Multi-scale Simulation and Design
#
# ------------------------------------------------------------------------------ 

from mpi4py import MPI
import numpy as np
import copy

from placeholders.parameter import Parameter
import Interscale_hub.pivot as piv
import Interscale_hub.IntercommManager as icm
#import placeholders.Intercomm_dummy as ic


class InterscaleHub:
    '''
    InterscaleHub for connecting cosim applications (two simulators).
    MVP: Expose INIT, START, STOP functionality
    
    Init:
    - Parameter reading and initialisation
    - Buffer creation, MPI shared memory, layout depending on the parameter
    - Open MPi ports (write to file) and accept connections
    - create (two) MPI intercommunicators, one for each applications
    
    Start:
    - initialise the pivot operation
    - start receive and send (data channels)
    - TODO: multiplexing 
    - proper M:N mapping of MPI ranks in the Pivot-operation
        - How many MPI ranks on the sending simulation (M ranks)
        - How many MPI ranks on the InterscaleHub (N ranks)
        -> This contains: parallel buffer access, transformation, analysis and sending
    - M:N:O mapping -> How many MPI ranks on the receiving simulation (O ranks)
    - multiple transformers, second pivot?
    
    
    Stop:
    - Call stop on the pivot operation and therefore the receiving and sending loop.
    - NOTE: This is currently not bound to the simulation,
        i.e. the actual simulation has stopped
    
    
    MVP: NEST-TVB cosim showcase
    '''
    
    def __init__(self, param, direction):
        '''
        Init params, create buffer, open ports, accept connections
        '''
        # 1) param stuff, create IntercommManager
        self._init_params(param,direction)
        
        # 2) create buffer in self.__databuffer
        self._create_buffer()
        
        # 3) Data channel setup
        self._data_channel_setup()
        

    def start(self):
        '''
        InterscaleHub:
        1) receive
        2) pivot data from buffer (
        '''
        # start -> pivot, transform, analysis, transform, pivot
        # pivot = split receiving ranks and transformer/sending ranks
        # 
        # stop -> loop with either interrupt or waiting for normal end/stop.
        if self.__direction == 1:
            self.__pivot = piv.NestTvbPivot(
                self.__param, 
                self.__input_comm, 
                self.__output_comm, 
                self.__databuffer)
        elif self.__direction == 2:
            self.__pivot = piv.TvbNestPivot(
                self.__param, 
                self.__input_comm, 
                self.__output_comm, 
                self.__databuffer)
            
        if self.__comm.Get_rank() == 0: # Receiver from input sim, rank 0
            self.__pivot.receive()
        else: #  Science/analyse and sender to TVB, rank 1-x
            self.__pivot.send()
        

    def stop(self):
        '''
        Receive stop command.
        Call stop on the pivot operation loop (receiving and sending)
        '''
        
        self.__pivot.stop()
        self.__ic.close_and_finalize(self.__input_comm, self.__input_port)
        self.__ic.close_and_finalize(self.__output_comm, self.__output_port)
        
        '''
        # Disconnect and close ports
        print('InterscaleHUB: disconnect communicators and close ports...')
        self.__input_comm.Disconnect()
        self.__output_comm.Disconnect()
        MPI.Close_port(self.__input_port)
        MPI.Close_port(self.__output_port) 
        '''
    
    def _create_buffer(self):
        '''
        Create shared memory buffer. MPI One-sided-Communication.
        MVP: datasize ist MPI.Double, buffersize is set with param init
        '''
        if self.__comm.Get_rank() == 0:
            bufbytes = self.__datasize * self.__buffersize
        else: 
            bufbytes= 0
        # rank 0: create the shared block
        # rank 1-x: get a handle to it
        win = MPI.Win.Allocate_shared(bufbytes, self.__datasize, comm=self.__comm)
        buf, self.__datasize = win.Shared_query(0)
        assert self.__datasize == MPI.DOUBLE.Get_size()
        # create a 1D numpy array (buffer) whose data points to the shared mem
        self.__databuffer = np.ndarray(buffer=buf, dtype='d', shape=(self.__buffersize,))
        
    
    def _data_channel_setup(self):
        '''
        Open ports and register connection details.
        Accept connection on ports and create INTER communicators.
        
        MVP: register = write port details to file.
        MVP: Two connections 
            - input = incoming simulation data
            - output = outgoing simulation data
        '''
        self.__input_comm, self.__input_port = self.__ic.open_port_accept_connection(self.__input_path)
        self.__output_comm, self.__output_port = self.__ic.open_port_accept_connection(self.__output_path)
        #self.__input_comm, self.__input_port = ic.open_port_accept_connection(self.__comm, self.__root, self.__info, self.__input_path)
        #self.__output_comm, self.__output_port = ic.open_port_accept_connection(self.__comm, self.__root, self.__info, self.__output_path)
        
        
    def _init_params(self, p, direction):
        '''
        Init MPI, buffer parameter and science parameter. 
        The science parameter are taken from the TVB-NEST implementation
        in the co-sim github (refactored usecase from Lionel).
        # TODO: MPI and buffer init needs to be here, but all parameter are passed through by the 
        Launcher->Orchestrator->AppCompanion
        '''
        # MPI and IntercommManager
        self.__comm = MPI.COMM_WORLD  # INTRA communicator
        self.__root = 0 # hardcoded!
        self.__ic = icm.IntercommManager(self.__comm, self.__root)
        
        # Buffer
        # TODO: needs to be a global cosim setting. more information needed!
        max_events = 1000000 # max. expected number of events per step
        self.__datasize = MPI.DOUBLE.Get_size()
        
        # science parameter
        self.__direction = direction
        # TODO: used as global param dict for now and passed all the way to pivot._analyse()
        # TODO: align this with the rest of the implementation and below param init
        self.__param = p.get_param(direction)
        
        # nest to tvb
        if direction == 1:
            self.__buffersize = max_events * 3 # 3 doubles per event
            self.__input_path = p.get_nest_path()
            self.__output_path = p.get_tvb_path()
            
            self.synch=self.__param['synch']                # time of synchronization between 2 run
            self.dt=self.__param['resolution']              # the resolution of the integrator
            self.shape = (int(self.synch/self.dt),1) # the shape of the buffer/histogram
            self.hist = np.zeros(self.shape)         # the initialisation of the histogram
            self.width = int(self.__param['width']/self.__param['resolution']) # the window of the average in time
            self.synch = self.__param['synch']                          # synchronize time between simulator
            self.buffer = np.zeros((self.width,))                  #initialisation/ previous result for a good result
            self.coeff = 1 / ( self.__param['nb_neurons'] * self.__param['resolution'] ) # for the mean firing rate in in KHZ
        # tvb to nest
        elif direction == 2:
            self.__buffersize = 2 + max_events # 2 doubles: [start_time,end_time] of simulation step
            self.__input_path = p.get_tvb_path()
            self.__output_path = p.get_nest_path()
            
            self.percentage_shared = self.__param['percentage_shared']  # percentage of shared rate between neurons
            self.nb_spike_generator = self.__param['nb_spike_generator']         # number of spike generator
            self.nb_synapse = self.__param['nb_synapses']               # number of synapses by neurons
            self.function_translation = self.__param['function_select'] # choose the function for the translation
    
    
    def _temp_protocol_translation():
        '''
        TODO: temporary translation of protocol behaviour
        from current NEST i/o to cosim 
        and from current TVB i/o to cosim.
        '''
        raise NotImplementedError
