#! /usr/bin/python
# -*- coding: UTF-8 -*-
__author__      = "David Hasenfratz <hasenfratz@tik.ee.ethz.ch>"
__copyright__   = "Copyright 2011, ETH Zurich, Switzerland, David Hasenfratz"
__license__     = "GPL"
__version__     = "$Revision$"
__date__        = "$Date$"
__id__          = "$Id$"
__source__      = "$URL$"

import BackLogMessage
from AbstractPlugin import AbstractPluginClass

import STEVALDriver
import numpy
import time
from threading import Event

DEFAULT_BACKLOG = True

# Query accelerometer to detect whether vehicle is moving or not
class MotionDetectionPluginClass(AbstractPluginClass):

    def __init__(self, parent, config):

        AbstractPluginClass.__init__(self, parent, config, DEFAULT_BACKLOG)

        self._sleeper = Event()
        self._stopped = False
        self._std_x = float(0)
        self._std_y = float(0)
        self._std_z = float(0)
        self._moving = 0
        self._data = [[],[],[]]
        self._numPolls = 0

        self.info('Init MotionDetectionPlugin...')

        self._stdThreshold = float(self.getOptionValue('std_threshold'))
        self._pollInterval = float(self.getOptionValue('poll_interval'))
        self._pollDuration = float(self.getOptionValue('poll_duration'))
        self._sendStatistic = int(self.getOptionValue('send_statistic'))
        self._deviceStr = self.getOptionValue('acc_device')

        if self._pollInterval <= self._pollDuration:
            self.warning('Bad configuration, poll interval is smaller equal than poll duration!')
            self._pollInterval = self._pollDuration + 5
            
        if self._pollInterval >= 10:
            self.info('poll interval: %s seconds' % (self._pollInterval,))
        else:
            self.warning('poll interval: %s seconds (are you sure you want such a small interval?)' % (self._pollInterval,))

        self.steval = STEVALDriver.STEVALDriver([self._deviceStr])
        #self.steval._setSensor()
        
        self.info("Done init")

    def isBusy(self):
        return False

    def run(self):
        self.name = 'MotionDetectionPlugin-Thread'
        self.debug('started')
        t = time.time()

        while not self._stopped:
            self._sleeper.wait(self._pollInterval - (time.time() - t))
            if self._sleeper.isSet():
                continue
            t = time.time()
            self.action('')
        self.info('died')

    def action(self, parameters):

        #self.steval._openDevice()
        #self._data = self.steval._startDataAcquisition(self._pollDuration)
        #self.detectMotion()

        #self.steval._closeDevice()
        #self._numPolls = self._numPolls + 1
        
        pluginList = ['OZ47Plugin1', 'GPSPluginNAV', 'AlphasensePlugin', 'STEVALPlugin']
        num = 0
        time_id = self.getTimeStamp()
        for pluginName in pluginList:
            try:
                self.sendInterPluginCommand(pluginName, time_id)
            except Exception, e:
                self.error(str(e))
            else:
                num += 1
        self.debug('recvInterPluginCommand successfully called from ' + str(num) + ' of ' + str(len(pluginList)) + ' plugins')

    def isBusy(self):
        return False

    def needsWLAN(self):
        return False

    def stop(self):
        self._stopped = True
        self._sleeper.set()
        self.info('stopped')

    def detectMotion(self):

        std_x = float(numpy.std(self._data[0]))
        std_y = float(numpy.std(self._data[1]))
        std_z = float(numpy.std(self._data[2]))

        self.debug('xStd is ' + str(std_x) + ' yStd is ' + str(std_y) + ' and zStd is ' + str(std_z));

        if std_x <= self._stdThreshold and std_y <= self._stdThreshold and std_z <= self._stdThreshold:
            self.debug('Vehicle is not moving')
            # Execute action function of the specified plugins
            pluginList = ['OZ47Plugin1', 'GPSPluginNAV', 'AlphasensePlugin']
            #pluginList = ['GPSPluginNAV']
            num = 0
            time_id = self.getTimeStamp()
            for pluginName in pluginList:
                try:
                    self.sendInterPluginCommand(pluginName, time_id)
                except Exception, e:
                    self.error(str(e))
                else:
                    num += 1
            self.debug('recvInterPluginCommand successfully called from ' + str(num) + ' of ' + str(len(pluginList)) + ' plugins')
        else:
            self.debug('Vehicle is moving')
            # Execute action function of the specified plugins
            pluginListMoving = ['STEVALPlugin']
            num = 0
            for pluginName in pluginListMoving:
                try:
                    self.sendInterPluginCommand(pluginName, self.getTimeStamp())
                except Exception, e:
                    self.error(str(e))
                else:
                    num += 1
            self.debug('recvInterPluginCommand successfully called from ' + str(num) + ' of ' + str(len(pluginListMoving)) + ' plugins')

            #self._moving = self._moving + 1
            # Store std values from the last motion detection
            self._std_x = std_x
            self._std_y = std_y
            self._std_z = std_z
