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
# ------------------------------------------------------------------------------
from abc import ABC, abstractmethod
import os
from mpi4py import MPI

from EBRAINS_InterscaleHUB.Interscale_hub.communicator_nest_to_tvb import CommunicatorNestTvb
from EBRAINS_InterscaleHUB.Interscale_hub.communicator_tvb_to_nest import CommunicatorTvbNest
from EBRAINS_InterscaleHUB.Interscale_hub.analyzer import Analyzer
from EBRAINS_InterscaleHUB.Interscale_hub.transformer import Transformer
from EBRAINS_InterscaleHUB.Interscale_hub.interscalehub_buffer_manager import InterscaleHubBufferManager
from EBRAINS_InterscaleHUB.Interscale_hub.interscaleHub_mediator import InterscaleHubMediator
from EBRAINS_InterscaleHUB.Interscale_hub.intercomm_manager import IntercommManager
from EBRAINS_InterscaleHUB.Interscale_hub.interscalehub_enums import DATA_EXCHANGE_DIRECTION

from EBRAINS_ConfigManager.global_configurations_manager.xml_parsers.default_directories_enum import DefaultDirectories
from EBRAINS_ConfigManager.workflow_configurations_manager.xml_parsers.xml2class_parser import Xml2ClassParser


class InterscaleHubBaseManager(ABC):
    """
    Abstract Base Class which
    1) Interacts with InterscaleHub Facade to steer the execution
    2) Manages the InterscaleHub functionality.
    """

    def __init__(self, parameters, direction, configurations_manager, log_settings,
                 sci_params_xml_path_filename=''):
        """
        Init params, create buffer, open ports, accept connections
        """

        self._log_settings = log_settings
        self._configurations_manager = configurations_manager
        self._logger = self._configurations_manager.load_log_configurations(
            name="InterscaleHub -- Base Manager",
            log_configurations=self._log_settings,
            target_directory=DefaultDirectories.SIMULATION_RESULTS)

        self._parameters = parameters
        # Sci-Params
        self._sci_params = Xml2ClassParser(sci_params_xml_path_filename, self._logger)

        # 1) param stuff, create IntercommManager
        # MPI and IntercommManager
        self._intra_comm = MPI.COMM_WORLD  # INTRA communicator
        self._root = 0  # hardcoded!
        self._intercomm_manager = IntercommManager(
            self._intra_comm,
            self._root,
            self._configurations_manager,
            self._log_settings)

        self._path = self._parameters['path']

        # instances for mediation
        # Data Buffer Manager
        self._interscalehub_buffer_manager = InterscaleHubBufferManager(
            self._configurations_manager,
            self._log_settings)
        self._interscalehub_buffer = None
        # InterscaleHub Transformer
        self._interscale_transformer = Transformer(
            self._parameters,
            self._configurations_manager,
            self._log_settings,
            sci_params=self._sci_params)
        # Analyzer
        self._analyzer = Analyzer(
            self._parameters,
            self._configurations_manager,
            self._log_settings,
            sci_params=self._sci_params)
        # Mediator
        self._mediator = InterscaleHubMediator(
            self._configurations_manager,
            self._log_settings,
            self._interscale_transformer,
            self._analyzer,
            self._interscalehub_buffer_manager)

        # Simulators Managers
        # Case a: NEST to TVB Manager
        if direction == DATA_EXCHANGE_DIRECTION.NEST_TO_TVB:
            self._nest_tvb_communicator = CommunicatorNestTvb(
                self._configurations_manager,
                self._log_settings,
                self._interscalehub_buffer_manager,
                self._mediator)
        # Case b: TVB to NEST Manager
        elif direction == DATA_EXCHANGE_DIRECTION.TVB_TO_NEST:
            self._tvb_nest_communicator = CommunicatorTvbNest(
                self._configurations_manager,
                self._log_settings,
                parameters,
                self._interscalehub_buffer_manager,
                self._mediator)

        # TODO: set via XML settings.
        # NOTE consider the scenario when handling the data larger than the buffer size
        # self._max_events = 1000000  # max. expected number of events per step
        # self._max_events = self._sci_params.max_events  # NOTE: it could be functional rather than scientific one

        # to be removed: self._parameters = parameters
        self._transformer_id = 0  # NOTE: hardcoded
        self._id_proxy_nest_region = self._parameters['id_nest_region']
        self._logger.info("initialized")

    def _get_mpi_shared_memory_buffer(self, buffer_size):
        """
        Creates shared memory buffer for MPI One-sided-Communication.
        This is wrapper to buffer manager function which creates the mpi
        shared memory buffer.
        """

        # create an MPI shared memory buffer
        self._interscalehub_buffer = \
            self._interscalehub_buffer_manager.create_mpi_shared_memory_buffer(
                buffer_size,
                self._intra_comm)
        return self._interscalehub_buffer

    def _set_up_connection(self, direction, intercomm_type):
        """
        Open ports and register connection details.
        Accept connection on ports and create INTER communicators.

        MVP: register = write port details to file.
        MVP: Two connections
            - input = incoming simulation data
            - output = outgoing simulation data
        """
        return self._intercomm_manager.open_port_accept_connection(
            direction, intercomm_type)

    @abstractmethod
    def start(self):
        """
        1) init pivot objects depending on the use case (direction)
        2) start pivot with INTRA communicator (M:N mapping)
        """
        raise NotImplementedError

    @abstractmethod
    def stop(self):
        """
        Receive stop command.
        Call stop on the pivot operation loop (receiving and sending)
        
        TODO: add error handling and fail checks
        """
        raise NotImplementedError
