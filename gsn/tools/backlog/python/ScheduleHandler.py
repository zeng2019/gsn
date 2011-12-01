# -*- coding: UTF-8 -*-
__author__      = "Tonio Gsell <tgsell@tik.ee.ethz.ch>"
__copyright__   = "Copyright 2010, ETH Zurich, Switzerland, Tonio Gsell"
__license__     = "GPL"
__version__     = "$Revision$"
__date__        = "$Date$"
__id__          = "$Id$"
__source__      = "$URL$"


# as soon as the subprocess.Popen() bug has been fixed the functionality related
# to this variable should be removed
SUBPROCESS_BUG_BYPASS = True

import time
import string
import struct
import os
import signal
import pickle
import shlex

if SUBPROCESS_BUG_BYPASS:
    import SubprocessFake
    subprocess = SubprocessFake
else:
    import subprocess
    
import logging
import thread
from datetime import datetime, timedelta
from threading import Event, Lock, Thread

import tos
import TOSTypes
from BackLogMessage import SCHEDULE_MESSAGE_TYPE
from crontab import CronTab
from SpecialAPI import Statistics

############################################
# Some Constants

MESSAGE_PRIORITY = 5

# The GSN packet types
GSN_TYPE_NO_SCHEDULE_AVAILABLE = 0
GSN_TYPE_NO_NEW_SCHEDULE = 1
GSN_TYPE_SCHEDULE = 2
GSN_TYPE_GET_SCHEDULE = 3

# ping and watchdog timing
PING_INTERVAL_SEC = 60
WATCHDOG_TIMEOUT_SEC = 300

# Schedule file format
SCHEDULE_TYPE_PLUGIN = 'plugin'
SCHEDULE_TYPE_SCRIPT = 'script'
BACKWARD_TOLERANCE_NAME = 'backward_tolerance_minutes'
MAX_RUNTIME_NAME = 'max_runtime_minutes'
MIN_RUNTIME_NAME = 'min_runtime_minutes'
############################################

class Callable:
    def __init__(self, anycallable):
        self.__call__ = anycallable


class ScheduleHandlerClass(Thread, Statistics):
    '''
    The ScheduleHandler offers the functionality to schedule different
    jobs (bash scripts, programs, etc.) on the deployment system in a
    well defined interval. The schedule is formated in a crontab-like
    manner and can be defined and altered on side of GSN as needed using
    the virtual sensors web input. A new schedule will be directly
    transmitted to the deployment if a connection exists or will be
    requested as soon as a connection opens.
    
    This handler can be run in duty-cycle mode or not. If the duty-cycle mode
    is enabled the plugin controls the duty-cycling of the deployment system.
    Scheduled jobs in a configurable time interval will be executed in a
    controlled environment. After their execution the system will be shutdown
    and taken from the power supply. A TinyNode running BBv2PowerControl
    offers the functionality (timers, startup/shutdown commands, etc.) to
    manage the power supply of the deployment system. Thus, job scheduling
    combined with duty-cycling can be used to minimize the energy consumption
    of the system. If the duty-cycle mode is disabled the ScheduleHandler only
    schedules jobs without offering any duty-cycling functionality.


    data/instance attributes:
    _backlogMain
    _connectionEvent
    _newScheduleEvent
    _scheduleLock
    _waitForNextJob
    _allJobsFinished
    _resendFinished
    _waitForGSNFinished
    _schedule
    _newSchedule
    _duty_cycle_mode
    _service_wakeup_disabled
    _max_next_schedule_wait_delta
    _max_job_runtime_min
    _shutdownThread
    _pingThread
    _config
    _beacon
    _servicewindow
    _logger
    _scheduleHandlerStop
    _tosMessageLock
    _tosMessageAckReceived
    _tosSentCmd
    _tosLastReceivedCmd
    _tosNodeState
    _tosOnline
    '''
    
    def __init__(self, parent, dutycyclemode, options):
        Thread.__init__(self, name='ScheduleHandler-Thread')
        self._logger = logging.getLogger(self.__class__.__name__)
        Statistics.__init__(self)
        
        self._backlogMain = parent
        self._duty_cycle_mode = dutycyclemode
        self._config = options

        self._logger.info('max_gsn_connect_wait_minutes: %s' % (self._getOptionValue('max_gsn_connect_wait_minutes', self._config),))
        self._logger.info('max_gsn_get_schedule_wait_minutes: %s' % (self._getOptionValue('max_gsn_get_schedule_wait_minutes', self._config),))
        
        if dutycyclemode:
            self._logger.info('service_wakeup_schedule: %s' % (self._getOptionValue('service_wakeup_schedule', self._config),))
            self._logger.info('service_wakeup_minutes: %s' % (self._getOptionValue('service_wakeup_minutes', self._config),))
            
            self._service_wakeup_disabled = False
            service_wakeup_disable = self._getOptionValue('service_wakeup_disable', self._config)
            if service_wakeup_disable == None or int(service_wakeup_disable) == 0:
                self._logger.info('service window is enabled')
            else:
                self._logger.warning('service window is disabled')
                self._service_wakeup_disabled = True

            self._logger.info('max_next_schedule_wait_minutes: %s' % (self._getOptionValue('max_next_schedule_wait_minutes', self._config),))
            self._logger.info('hard_shutdown_offset_minutes: %s' % (self._getOptionValue('hard_shutdown_offset_minutes', self._config),))
            self._logger.info('approximate_startup_seconds: %s' % (self._getOptionValue('approximate_startup_seconds', self._config),))
            self._logger.info('max_db_resend_runtime: %s' % (self._getOptionValue('max_db_resend_runtime', self._config),))
            
            self._max_next_schedule_wait_delta = timedelta(minutes=int(self._getOptionValue('max_next_schedule_wait_minutes', self._config)))
        
        try:
            self._backlogMain.registerTOSListener(self, [TOSTypes.AM_CONTROLCOMMAND, TOSTypes.AM_BEACONCOMMAND])
            self._tosOnline = True
        except Exception, e:
            self._tosOnline = False
            if self._duty_cycle_mode:
                raise e
            else:
                self._logger.warning(str(e))
        
        self._connectionEvent = Event()
        self._newScheduleEvent = Event()
        self._scheduleLock = Lock()
        self._waitForNextJob = Event()
        self._allJobsFinished = Event()
        self._allJobsFinished.set()
        self._resendFinished = Event()
        self._waitForGSNFinished = Event()
        self._tosMessageLock = Lock()
        self._tosMessageAckReceived = Event()
        self._tosSentCmd = None
        self._tosLastReceivedCmd = None
        self._tosNodeState = None
        
        self._shutdownThread = None
        self._schedule = None
        self._newSchedule = False
        self._scheduleHandlerStop = False
        self._beacon = False
        self._servicewindow = False
        
        self._pluginScheduleCounterId = self.createCounter()
        self._scriptScheduleCounterId = self.createCounter()
        self._scheduleCreationTime = None
        
        if self._duty_cycle_mode:
            self._pingThread = TOSPingThread(self, PING_INTERVAL_SEC, WATCHDOG_TIMEOUT_SEC)
        
        if os.path.isfile('%s.parsed' % (self._getOptionValue('schedule_file', self._config),)):
            try:
                # Try to load the parsed schedule
                parsed_schedule_file = open('%s.parsed' % (self._getOptionValue('schedule_file', self._config),), 'r')
                self._schedule = pickle.load(parsed_schedule_file)
                parsed_schedule_file.close()
                self._scheduleCreationTime = self._schedule.getCreationTime()
            except Exception, e:
                self.exception(str(e))
        else:
            self._logger.info('there is no local schedule file available')
            
            
    def checkConfig(dutycyclemode, config):
        max_gsn_connect_wait_minutes = ScheduleHandlerClass._getOptionValue('max_gsn_connect_wait_minutes', config)
        if max_gsn_connect_wait_minutes is None:
            raise TypeError('max_gsn_connect_wait_minutes not specified in config file')
        elif not max_gsn_connect_wait_minutes.isdigit() or int(max_gsn_connect_wait_minutes) < 0:
            raise TypeError('max_gsn_connect_wait_minutes has to be a positive integer')
        
        max_gsn_get_schedule_wait_minutes = ScheduleHandlerClass._getOptionValue('max_gsn_get_schedule_wait_minutes', config)
        if max_gsn_get_schedule_wait_minutes is None:
            raise TypeError('max_gsn_get_schedule_wait_minutes not specified in config file')
        elif not max_gsn_get_schedule_wait_minutes.isdigit() or int(max_gsn_connect_wait_minutes) < 0:
            raise TypeError('max_gsn_get_schedule_wait_minutes has to be a positive integer')
        
        if dutycyclemode:
            service_wakeup_schedule = ScheduleHandlerClass._getOptionValue('service_wakeup_schedule', config)
            if service_wakeup_schedule is None:
                raise TypeError('service_wakeup_schedule not specified in config file')
            try:
                hour, minute = service_wakeup_schedule.split(':')
                hour = int(hour)
                minute = int(minute)
            except:
                raise TypeError('service_wakeup_schedule is not in the format HOUR:MINUTE')
            
            service_wakeup_minutes = ScheduleHandlerClass._getOptionValue('service_wakeup_minutes', config)
            if service_wakeup_minutes is None:
                raise TypeError('service_wakeup_minutes not specified in config file')
            elif not service_wakeup_minutes.isdigit() or int(service_wakeup_minutes) < 0:
                raise TypeError('service_wakeup_minutes has to be a positive integer')
            
            service_wakeup_disable = ScheduleHandlerClass._getOptionValue('service_wakeup_disable', config)
            if service_wakeup_disable is not None and int(service_wakeup_disable) != 0 and int(service_wakeup_disable) != 1:
                raise TypeError('service_wakeup_disable has to be set to 1 or 0 in config file')
            
            max_next_schedule_wait_minutes = ScheduleHandlerClass._getOptionValue('max_next_schedule_wait_minutes', config)
            if max_next_schedule_wait_minutes is None:
                raise TypeError('max_next_schedule_wait_minutes not specified in config file')
            elif not max_next_schedule_wait_minutes.isdigit() or int(max_next_schedule_wait_minutes) < 0:
                raise TypeError('max_next_schedule_wait_minutes has to be a positive integer')
            
            hard_shutdown_offset_minutes = ScheduleHandlerClass._getOptionValue('hard_shutdown_offset_minutes', config)
            if hard_shutdown_offset_minutes is None:
                raise TypeError('hard_shutdown_offset_minutes not specified in config file')
            elif not hard_shutdown_offset_minutes.isdigit() or int(hard_shutdown_offset_minutes) < 0:
                raise TypeError('hard_shutdown_offset_minutes has to be a positive integer')
            
            approximate_startup_seconds = ScheduleHandlerClass._getOptionValue('approximate_startup_seconds', config)
            if approximate_startup_seconds is None:
                raise TypeError('approximate_startup_seconds not specified in config file')
            elif not approximate_startup_seconds.isdigit() or int(approximate_startup_seconds) < 0:
                raise TypeError('approximate_startup_seconds has to be a positive integer')
            
            max_db_resend_runtime = ScheduleHandlerClass._getOptionValue('max_db_resend_runtime', config)
            if max_db_resend_runtime is None:
                raise TypeError('max_db_resend_runtime not specified in config file')
            elif not max_db_resend_runtime.isdigit() or int(max_db_resend_runtime) < 0:
                raise TypeError('max_db_resend_runtime has to be a positive integer')
    checkConfig = Callable(checkConfig)
            
            
    def setSchedule(self, pluginname, schedule, merge):
        self._logger.info('new schedule from %s received' % (pluginname,))
        creationtime = int(time.time()*1000)
        return self._setSchedule(pluginname, creationtime, schedule, merge)
    
    
    def connectionToGSNestablished(self):
        self._logger.debug('connection established')
        self._logger.debug('request schedule from gsn')
        if self._schedule:
            self._backlogMain.gsnpeer.processMsg(self.getMsgType(), self._schedule.getCreationTime(), [GSN_TYPE_GET_SCHEDULE], MESSAGE_PRIORITY, False)
        else:
            self._backlogMain.gsnpeer.processMsg(self.getMsgType(), 0, [GSN_TYPE_GET_SCHEDULE], MESSAGE_PRIORITY, False)
        self._connectionEvent.set()
        
        
    def run(self):
        self._logger.info('started')
        
        if self._duty_cycle_mode:
            self._pingThread.start()
            self.tosMsgSend(TOSTypes.CONTROL_CMD_WAKEUP_QUERY)
            if self._scheduleHandlerStop:
                self._logger.info('died')
                return
        else:
            if self._tosOnline:
                self.tosMsgSend(TOSTypes.CONTROL_CMD_RESET_WATCHDOG, 0)
                self._tosOnline = False
                self._backlogMain.deregisterTOSListener(self)
        
        if self._schedule and self._duty_cycle_mode:  
            # Schedule duty wake-up after this session, for safety reasons.
            # (The scheduled time here could be in this session if schedules are following
            # each other in short intervals. In this case it could be possible, that
            # we have to wait for the next service window in case of an unexpected shutdown.)
            min = int(self._getOptionValue('max_gsn_connect_wait_minutes', self._config))
            min += int(self._getOptionValue('max_gsn_get_schedule_wait_minutes', self._config))
            min += int(self._getOptionValue('max_next_schedule_wait_minutes', self._config))
            min += int(self._getOptionValue('hard_shutdown_offset_minutes', self._config))
            sec = int(self._getOptionValue('approximate_startup_seconds', self._config))
            maxruntime = self._backlogMain.jobsobserver.getOverallJobsMaxRuntimeSec()
            if maxruntime is not None:
                sec += maxruntime
            td = timedelta(minutes=min, seconds=sec)
            nextschedule, error = self._schedule.getNextSchedules(datetime.utcnow() + td)
            if error:
                for e in error:
                    self.error('error while parsing the schedule file: %s' % (e,))
            if nextschedule:
                nextdt, pluginclassname, commandstring, runtimemax, runtimemin = nextschedule[0]
                self._scheduleNextDutyWakeup(nextdt - datetime.utcnow(), '%s %s' % (pluginclassname, commandstring))
                
        if self._schedule:
            thread.start_new_thread(self._waitForGSN, (None,))
        else:
            self._waitForGSN()
        
        lookback = True
        service_time = timedelta()
        self._waitForNextJob.clear()
        while not self._scheduleHandlerStop:
            dtnow = datetime.utcnow()
            
            nextschedules = None
            if self._schedule:
                # get the next schedule(s) in time
                self._scheduleLock.acquire()
                nextschedules, error = self._schedule.getNextSchedules(dtnow, lookback)
                for e in error:
                    self.error('error while parsing the schedule file: %s' % (e,))
                self._newScheduleEvent.clear()
                lookback = False
                self._scheduleLock.release()
                
            # if there is no schedule shutdown again and wait for next service window or wait for a schedule
            if not nextschedules:
                if self._duty_cycle_mode and not self._beacon:
                    self._logger.warning('no schedule or empty schedule available -> shutdown')
                    if self._shutdownThread:
                        self._shutdownThread.stop()
                    self._shutdownThread = ShutdownThread(self)
                    self._shutdownThread.start()
                    break
                else:
                    self._logger.info('no schedule or empty schedule available -> waiting for a schedule')
                    self._newScheduleEvent.clear()
                    self._newScheduleEvent.wait()
                    continue
            
            for nextdt, pluginclassname, commandstring, runtimemax, runtimemin in nextschedules:
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug('(%s,%s,%s,%s,%s)' % (nextdt, pluginclassname, commandstring, runtimemax, runtimemin))
                dtnow = datetime.utcnow()
                timediff = nextdt - dtnow
                
                
                if self._duty_cycle_mode and not self._beacon:
                    if self._service_wakeup_disabled and not self._servicewindow:
                        service_time = timedelta()
                    else:
                        service_time = self._serviceTime()
                        
                    if timediff > self._max_next_schedule_wait_delta and timediff > service_time:
                        if self._shutdownThread:
                            self._shutdownThread.stop()
                        if service_time <= self._max_next_schedule_wait_delta:
                            self._logger.info('nothing more to do in the next %s minutes (max_next_schedule_wait_minutes)' % (self._getOptionValue('max_next_schedule_wait_minutes', self._config),))
                        else:
                            self._logger.info('nothing more to do in the next %f minutes (rest of service time plus max_next_schedule_wait_minutes)' % (service_time.seconds/60.0 + service_time.days * 1440.0 + int(self._getOptionValue('max_next_schedule_wait_minutes')),))
                        self._shutdownThread = ShutdownThread(self)
                        self._shutdownThread.start()
                    
                if nextdt > dtnow:
                    if pluginclassname:
                        if self._duty_cycle_mode:
                            self._logger.info('executing >%s.action("%s")< in %f seconds if not shutdown before' % (pluginclassname, commandstring, timediff.seconds + timediff.days * 86400 + timediff.microseconds/1000000.0))
                        else:
                            if self._logger.isEnabledFor(logging.DEBUG):
                                self._logger.debug('executing >%s.action("%s")< in %f seconds' % (pluginclassname, commandstring, timediff.seconds + timediff.days * 86400 + timediff.microseconds/1000000.0))
                    else:
                        if self._duty_cycle_mode:
                            self._logger.info('executing >%s< in %f seconds if not shutdown before' % (commandstring, timediff.seconds + timediff.days * 86400 + timediff.microseconds/1000000.0))
                        else:
                            if self._logger.isEnabledFor(logging.DEBUG):
                                self._logger.debug('executing >%s< in %f seconds' % (commandstring, timediff.seconds + timediff.days * 86400 + timediff.microseconds/1000000.0))
                    self._waitForNextJob.wait(timediff.seconds + timediff.days * 86400 + timediff.microseconds/1000000.0)
                    if self._waitForNextJob.isSet():
                        self._waitForNextJob.clear()
                        if self._newSchedule:
                            lookback = True
                            self._newSchedule = False
                        break
                
                if pluginclassname:
                    if self._duty_cycle_mode:
                        self._logger.info('executing >%s.action("%s")< now' % (pluginclassname, commandstring))
                    else:
                        if self._logger.isEnabledFor(logging.DEBUG):
                            self._logger.debug('executing >%s.action("%s")< now' % (pluginclassname, commandstring))
                    try:
                        self._backlogMain.pluginAction(pluginclassname, commandstring, runtimemax, runtimemin)
                    except Exception, e:
                        self.error('error in scheduled plugin >%s %s<: %s' % (pluginclassname, commandstring, e))
                    else:
                        self.counterAction(self._pluginScheduleCounterId)
                else:
                    if self._duty_cycle_mode:
                        self._logger.info('executing >%s< now' % (commandstring,))
                    else:
                        if self._logger.isEnabledFor(logging.DEBUG):
                            self._logger.debug('executing >%s< now' % (commandstring,))
                    try:
                        job = subprocess.Popen(shlex.split(commandstring), stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
                    except Exception, e:
                        self.error('error in scheduled script >%s<: %s' % (commandstring, e))
                    else:
                        self._backlogMain.jobsobserver.observeJob(job, commandstring, False, runtimemax)
                        self.counterAction(self._scriptScheduleCounterId)
            
        if self._duty_cycle_mode:
            self._pingThread.join()
                
        self._logger.info('died')
            
            
    def getStatus(self):
        '''
        Returns the status of the schedule handler as list:
        
        @return: status of the schedule handler [schedule creation time,
                                                 plugin schedule counter,
                                                 script schedule counter]
        '''
        return [self._scheduleCreationTime, \
                self.getCounterValue(self._pluginScheduleCounterId), \
                self.getCounterValue(self._scriptScheduleCounterId)]
    
    
    def stop(self):
        self._scheduleHandlerStop = True
        if self._shutdownThread:
            self._shutdownThread.stop()
        self._waitForGSNFinished.set()
        self._connectionEvent.set()
        self._newScheduleEvent.set()
        self._allJobsFinished.set()
        self._resendFinished.set()
        self._waitForNextJob.set()
        
        if self._duty_cycle_mode:
            self._pingThread.stop()
            
        if self._tosOnline:
            self._backlogMain.deregisterTOSListener(self)
            
        self._logger.info('stopped')
        
        
    def allJobsFinished(self):
        if self._duty_cycle_mode:
            self._logger.info('all jobs finished')
        else:
            self._logger.debug('all jobs finished')
        self._allJobsFinished.set()
        
        
    def newJobStarted(self):
        self._allJobsFinished.clear()
        
        
    def backlogResendFinished(self):
        self._resendFinished.set()
    
    
    def getMsgType(self):
        return SCHEDULE_MESSAGE_TYPE


    def msgReceived(self, data):
        '''
        Try to interpret a new received Config-Message from GSN
        '''

        # Is the Message filled with content or is it just an emty response?
        pktType = data[0]
        if pktType == GSN_TYPE_NO_SCHEDULE_AVAILABLE:
            self._logger.info('GSN has no schedule available')
        elif pktType == GSN_TYPE_NO_NEW_SCHEDULE:
            self._logger.info('no newer schedule from GSN')
        elif pktType == GSN_TYPE_SCHEDULE:
            self._logger.info('new schedule from GSN received')
            self._setSchedule('GSN', data[1], data[2], False)
            
        self._newScheduleEvent.set()
            
            
    def tosMsgReceived(self, timestamp, packet):
        response = tos.Packet(TOSTypes.CONTROL_CMD_STRUCTURE, packet['data'])
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug('rcv (cmd=%s, argument=%s)' % (response['command'], response['argument']))
        if response['command'] == TOSTypes.CONTROL_CMD_WAKEUP_QUERY:
            node_state = response['argument']
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug('CONTROL_CMD_WAKEUP_QUERY response received with argument: %s' % (node_state,))
            if node_state != self._tosNodeState:
                s = ''
                if (node_state & TOSTypes.CONTROL_WAKEUP_TYPE_SCHEDULED) == TOSTypes.CONTROL_WAKEUP_TYPE_SCHEDULED:
                    s += 'SCHEDULE '
                if (node_state & TOSTypes.CONTROL_WAKEUP_TYPE_SERVICE) == TOSTypes.CONTROL_WAKEUP_TYPE_SERVICE:
                    s += 'SERVICE '
                    self._servicewindow = True
                if (node_state & TOSTypes.CONTROL_WAKEUP_TYPE_BEACON) == TOSTypes.CONTROL_WAKEUP_TYPE_BEACON:
                    self._beacon = True
                    if self._shutdownThread:
                        self._shutdownThread.stop()
                    if self._duty_cycle_mode:
                        self._backlogMain.beaconSet()
                    s += 'BEACON '
                elif self._beacon:
                    self._beacon = False
                    if self._duty_cycle_mode:
                        self._waitForNextJob.set()
                        self._backlogMain.beaconCleared()
                if (node_state & TOSTypes.CONTROL_WAKEUP_TYPE_NODE_REBOOT) == TOSTypes.CONTROL_WAKEUP_TYPE_NODE_REBOOT:
                    s += 'NODE_REBOOT'
                if s:
                    self._logger.info('TinyNode wake-up states are: %s' % (s,))
                self._tosNodeState = node_state
        elif response['command'] == TOSTypes.CONTROL_CMD_SERVICE_WINDOW:
            self._logger.info('CONTROL_CMD_SERVICE_WINDOW response received with argument: %s' % (response['argument'],))
        elif response['command'] == TOSTypes.CONTROL_CMD_NEXT_WAKEUP:
            self._logger.info('CONTROL_CMD_NEXT_WAKEUP response received with argument: %s' % (response['argument'],))
        elif response['command'] == TOSTypes.CONTROL_CMD_SHUTDOWN:
            self._logger.info('CONTROL_CMD_SHUTDOWN response received with argument: %s' % (response['argument'],))
        elif response['command'] == TOSTypes.CONTROL_CMD_NET_STATUS:
            self._logger.info('CONTROL_CMD_NET_STATUS response received with argument: %s' % (response['argument'],))
        elif response['command'] == TOSTypes.CONTROL_CMD_RESET_WATCHDOG:
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug('CONTROL_CMD_RESET_WATCHDOG response received with argument: %s' % (response['argument'],))
        else:
            return False
        
             
        if packet['type'] == TOSTypes.AM_CONTROLCOMMAND:
            if response['command'] == self._tosSentCmd:
                self._logger.debug('TOS packet acknowledge received')
                self._tosSentCmd = None
                self._tosLastReceivedCmd = response['command'];
                self._tosMessageAckReceived.set()
            elif self._tosSentCmd != None:
                if self._tosLastReceivedCmd == response['command']:
                    self._logger.debug('TOS packet acknowledge already received')
                else:
                    self.error('received TOS message type (%s) does not match the sent command type (%s)' % (response['command'], self._tosSentCmd))
                    return False
                
        return True
        
        
    def tosMsgSend(self, cmd, argument=0):
        '''
        Send a command to the TinyNode
        
        @param cmd: the 1 Byte Command Code
        @param argument: the 4 byte argument for the command
        '''
        if self._tosOnline:
            self._tosMessageLock.acquire()
            resendCounter = 1
            self._tosSentCmd = cmd
            while True:
                if self._logger.isEnabledFor(logging.DEBUG):
                    self._logger.debug('snd (cmd=%s, argument=%s)' % (cmd, argument))
                try:
                    self._backlogMain._tospeer.sendTOSMsg(tos.Packet(TOSTypes.CONTROL_CMD_STRUCTURE, [cmd, argument]), TOSTypes.AM_CONTROLCOMMAND, 1)
                except Exception, e:
                    self.exception(e)
                    return False
                    
                self._tosMessageAckReceived.wait(3)
                if self._scheduleHandlerStop:
                    break
                elif self._tosMessageAckReceived.isSet():
                    self._tosMessageAckReceived.clear()
                    break
                else:
                    if resendCounter == 5:
                        self.error('no answer for TOS command (%s) received from TOS node' % (self._tosSentCmd,))
                        self._tosMessageLock.release()
                        return False
                    self._logger.info('resend command (%s) to TOS node' % (self._tosSentCmd,))
                    resendCounter += 1
            self._tosMessageLock.release()
            return True
        else:
            return False
        
        
    def exception(self, exception):
        self._backlogMain.incrementExceptionCounter()
        self._logger.exception(exception)
        
        
    def error(self, msg):
        self._backlogMain.incrementErrorCounter()
        self._logger.error(msg)
        
        
    def ackReceived(self, timestamp):
        pass
        
        
    def _setSchedule(self, origin, creationtime, schedule, merge):
        # Get the schedule creation time
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug('creation time: ' + str(creationtime) + ' and origin: ' + origin)

        oldschedule = self._schedule
        try:
            if merge and self._schedule:
                sc = ScheduleCron(creationtime, fake_tab=self._mergeSchedule(origin, schedule, self._schedule.getScheduleList()))
            else:
                sc = ScheduleCron(creationtime, fake_tab=schedule)
            self._scheduleLock.acquire()   
            self._schedule = sc
            self._scheduleLock.release()
           
            # Write schedule to disk (the plaintext one for debugging and the parsed one for better performance)
            schedule_file = open(self._getOptionValue('schedule_file', self._config), 'w')
            schedule_file.write(schedule)
            schedule_file.close()
        
            compiled_schedule_file = open('%s.parsed' % (self._getOptionValue('schedule_file', self._config),), 'w')
            pickle.dump(self._schedule, compiled_schedule_file)
            compiled_schedule_file.close()

            self._scheduleCreationTime = creationtime
        except Exception, e:
            self.error('received schedule can not be used: %s' % (e.__str__(),))
            if oldschedule:
                self._schedule = oldschedule
                self._logger.warning('reusing previous schedule')
            return False
        else:
            self._logger.info('updated internal schedule with the new one.')
            if origin == 'GSN':
                s = 'GSN'
            else:
                s = 'CoreStation (%s)' % (origin,)
            self._backlogMain.gsnpeer.processMsg(self.getMsgType(), self._schedule.getCreationTime(), [GSN_TYPE_SCHEDULE, s, self._schedule.getScheduleString()], MESSAGE_PRIORITY, True)
            self._backlogMain.newScheduleSet(origin, self._schedule.getScheduleString())
            self._newSchedule = True
            self._waitForNextJob.set()
            if self._shutdownThread:
                self._shutdownThread.stop()
            return True
        
        
    def _mergeSchedule(self, plugin, newSchedule, existingScheduleList):
        # parse new schedule and check for correctness
        sc = ScheduleCron(0, fake_tab=newSchedule)
        
        # check the new schedule for its change rights
        for newsc in sc.getScheduleList():
            if newsc[0] == SCHEDULE_TYPE_PLUGIN and newsc[1] != plugin:
                raise TypeError('%s is not allowed to change the schedule for %s' % (plugin, newsc[1]))
        
        # create merged schedule
        mergedSchedule = ''
        for oldsc in existingScheduleList:
            if oldsc[0] == SCHEDULE_TYPE_SCRIPT:
                new = False
                for newsc in sc.getScheduleList():
                    if newsc[0] == SCHEDULE_TYPE_SCRIPT:
                        if oldsc[1] == newsc[1]:
                            new = True
                            mergedSchedule += newsc[2] + '\n'
                if not new:
                    mergedSchedule += oldsc[2] + '\n'
            elif oldsc[1] != plugin:
                mergedSchedule += oldsc[2] + '\n'
        
        for newsc in sc.getScheduleList():
            if newsc[0] == SCHEDULE_TYPE_PLUGIN:
                mergedSchedule += newsc[2] + '\n'
                
        return mergedSchedule
           
        
        
    def _waitForGSN(self, param=None):
        # wait some time for GSN to connect
        if not self._backlogMain.gsnpeer.isConnected():
            self._logger.info('waiting for gsn to connect for a maximum of %s minutes' % (self._getOptionValue('max_gsn_connect_wait_minutes', self._config),))
            self._connectionEvent.wait((int(self._getOptionValue('max_gsn_connect_wait_minutes', self._config)) * 60))
            self._connectionEvent.clear()
            if self._scheduleHandlerStop:
                return
        
        # if GSN is connected try to get a new schedule for a while
        if self._backlogMain.gsnpeer.isConnected():
            if not self._newScheduleEvent.isSet():
                timeout = 0
                self._logger.info('waiting for gsn to answer a schedule request for a maximum of %s minutes' % (self._getOptionValue('max_gsn_get_schedule_wait_minutes', self._config),))
                while timeout < (int(self._getOptionValue('max_gsn_get_schedule_wait_minutes', self._config)) * 60):
                    self._newScheduleEvent.wait(30)
                    if self._scheduleHandlerStop:
                        return
                    if self._newScheduleEvent.isSet():
                        self._newScheduleEvent.clear()
                        break
                    self._logger.debug('request schedule from gsn')
                    if self._schedule:
                        self._backlogMain.gsnpeer.processMsg(self.getMsgType(), self._schedule.getCreationTime(), [GSN_TYPE_GET_SCHEDULE], MESSAGE_PRIORITY, False)
                    else:
                        self._backlogMain.gsnpeer.processMsg(self.getMsgType(), 0, [GSN_TYPE_GET_SCHEDULE], MESSAGE_PRIORITY, False)
                    timeout += 30
                
                if timeout >= int(self._getOptionValue('max_gsn_get_schedule_wait_minutes', self._config)) * 60:
                    self._logger.warning('gsn has not answered on any schedule request')
        else:
            self._logger.warning('gsn has not connected')
            self._resendFinished.set()
            
        self._waitForGSNFinished.set()
        

    def _getOptionValue(key, config):
        for entry in config:
            entry_key = entry[0]
            entry_value = entry[1]
            if key == entry_key:
                return entry_value
        return None
    _getOptionValue = Callable(_getOptionValue)
        
        
    def _serviceTime(self):
        now = datetime.utcnow()
        start, end = self._getNextServiceWindowRange()
        if start < (now + self._max_next_schedule_wait_delta):
            return end - now
        else:
            return timedelta()
    
    
    def _getNextServiceWindowRange(self):
        wakeup_minutes = timedelta(minutes=int(self._getOptionValue('service_wakeup_minutes', self._config)))
        hour, minute = self._getOptionValue('service_wakeup_schedule', self._config).split(':')
        now = datetime.utcnow()
        service_time = datetime(now.year, now.month, now.day, int(hour), int(minute))
        if (service_time + wakeup_minutes) < now:
            twentyfourhours = timedelta(hours=24)
            return (service_time + twentyfourhours, service_time + twentyfourhours + wakeup_minutes)
        else:
            return (service_time, service_time + wakeup_minutes)
        
        
    def _scheduleNextDutyWakeup(self, time_delta, schedule_name):
        if self._duty_cycle_mode:
            time_to_wakeup = time_delta.seconds + time_delta.days * 86400 - int(self._getOptionValue('approximate_startup_seconds', self._config))
            if self.tosMsgSend(TOSTypes.CONTROL_CMD_NEXT_WAKEUP, time_to_wakeup):
                self._logger.info('successfully scheduled the next duty wake-up for >%s< (that\'s in %d seconds)' % (schedule_name, time_to_wakeup))
            else:
                self.error('could not schedule the next duty wake-up for >%s<' % (schedule_name,))
            

class ShutdownThread(Thread):
    
    def __init__(self, parent, sleepdelta=timedelta()):
        Thread.__init__(self, name='%s-Thread' % (self.__class__.__name__,))
        self._logger = logging.getLogger(self.__class__.__name__)
        self._scheduleHandler = parent
        self._sleepdelta = sleepdelta
        self._stopShutdown = Event()
        self._shutdownThreadStop = False
        
        
    def run(self):
        self._logger.info('starting shutdown thread')
        now = datetime.utcnow()
        if now + self._sleepdelta > now:
            waitfor = self._sleepdelta.seconds + self._sleepdelta.days * 86400 + self._sleepdelta.microseconds/1000000.0
            self._logger.info('waiting %f minutes for service window to finish' % (waitfor/60.0,))
            self._stopShutdown.wait(waitfor)
            if self._shutdownThreadStop:
                return
            else:
                self._logger.info('service window finished')
        
        # wait for jobs to finish
        maxruntime = self._scheduleHandler._backlogMain.jobsobserver.getOverallJobsMaxRuntimeSec()
        if not self._scheduleHandler._allJobsFinished.isSet() and maxruntime:
            if maxruntime != -1:
                self._logger.info('waiting for all active jobs to finish for a maximum of %f seconds' % (maxruntime,))
                self._scheduleHandler._allJobsFinished.wait(5+maxruntime)
            else:
                self._logger.info('waiting for all active jobs to finish indefinitely')
                self._scheduleHandler._allJobsFinished.wait()
            if self._shutdownThreadStop:
                return
            if not self._scheduleHandler._allJobsFinished.isSet():
                self.error('not all jobs have been killed (should not happen)')
                
        if not self._scheduleHandler._waitForGSNFinished.isSet():
            self._logger.info('waiting for GSN')
            self._scheduleHandler._waitForGSNFinished.wait()
                
        # wait for backlog to finish resend data
        max_wait = int(self._scheduleHandler._getOptionValue('max_db_resend_runtime', self._scheduleHandler._config))*60.0
        if not self._scheduleHandler._resendFinished.isSet() and max_wait > self._scheduleHandler._backlogMain.getUptime():
            self._logger.info('waiting for database resend process to finish for a maximum of %f seconds' % (max_wait-self._scheduleHandler._backlogMain.getUptime(),))
            self._scheduleHandler._resendFinished.wait(max_wait-self._scheduleHandler._backlogMain.getUptime())
            if self._shutdownThreadStop:
                return
            if not self._scheduleHandler._resendFinished.isSet():
                self._logger.warning('backlog database is not finish with resending')
            else:
                self._logger.warning('backlog database finished resending')
                
        if self._scheduleHandler._schedule:
            dtnow = datetime.utcnow()
            nextschedules, error = self._scheduleHandler._schedule.getNextSchedules(dtnow)
            if nextschedules and nextschedules[0][0] - dtnow < self._scheduleHandler._max_next_schedule_wait_delta:
                self._logger.info('next schedule is coming soon => wait for it')
                return

        # Synchronize Service Wakeup Time
        time_delta = self._scheduleHandler._getNextServiceWindowRange()[0] - datetime.utcnow()
        time_to_service = time_delta.seconds + time_delta.days * 86400 - int(self._scheduleHandler._getOptionValue('approximate_startup_seconds', self._scheduleHandler._config))
        if time_to_service < 0-int(self._scheduleHandler._getOptionValue('approximate_startup_seconds', self._scheduleHandler._config)):
            time_to_service += 86400
        if not self._scheduleHandler._service_wakeup_disabled:
            self._logger.info('next service window is in %f minutes' % (time_to_service/60.0,))
        if self._scheduleHandler.tosMsgSend(TOSTypes.CONTROL_CMD_SERVICE_WINDOW, time_to_service):
            if not self._scheduleHandler._service_wakeup_disabled:
                self._logger.info('successfully scheduled the next service window wake-up (that\'s in %d seconds)' % (time_to_service,))
        else:
            self.error('could not schedule the next service window wake-up')
        if self._scheduleHandler._service_wakeup_disabled:
            if self._scheduleHandler.tosMsgSend(TOSTypes.CONTROL_CMD_SERVICE_WINDOW, 0xffffffff):
                self._logger.info('successfully disabled service window wake-up')
            else:
                self.error('could not disable service window wake-up')
        if self._shutdownThreadStop:
            return

        # Schedule next duty wake-up
        if self._scheduleHandler._schedule:
            td = timedelta(seconds=int(self._scheduleHandler._getOptionValue('approximate_startup_seconds', self._scheduleHandler._config)))
            nextschedule, error = self._scheduleHandler._schedule.getNextSchedules(datetime.utcnow() + td)
            for e in error:
                self.error('error while parsing the schedule file: %s' % (e,))
            if nextschedule:
                nextdt, pluginclassname, commandstring, runtimemax, runtimemin = nextschedule[0]
                self._logger.info('schedule next duty wake-up')
                self._scheduleHandler._scheduleNextDutyWakeup(nextdt - datetime.utcnow(), '%s %s' % (pluginclassname, commandstring))
            if self._shutdownThreadStop:
                return
                
        # last possible moment to check if a beacon has been sent to the node
        # (if so, we do not want to shutdown)
        self._logger.info('get node wake-up states')
        self._scheduleHandler.tosMsgSend(TOSTypes.CONTROL_CMD_WAKEUP_QUERY)
        if self._shutdownThreadStop:
            return
             
        # point of no return!   
        # Tell TinyNode to shut us down in X seconds
        self._scheduleHandler._pingThread.stop()
        shutdown_offset = int(self._scheduleHandler._getOptionValue('hard_shutdown_offset_minutes', self._scheduleHandler._config))*60
        if self._scheduleHandler.tosMsgSend(TOSTypes.CONTROL_CMD_SHUTDOWN, shutdown_offset):
            self._logger.info('we\'re going to do a hard shut down in %s seconds ...' % (shutdown_offset,))
        else:
            self.error('could not communicate the hard shut down time with the TOS node')

        self._scheduleHandler._backlogMain.shutdown = True
        parentpid = os.getpid()
        self._logger.info('sending myself._scheduleHandler (pid=%d) SIGINT' % (parentpid,))
        os.kill(parentpid, signal.SIGINT)


    def stop(self):
        if not self._shutdownThreadStop:
            self._shutdownThreadStop = True
            self._stopShutdown.set()
            self._logger.info('stop shutdown')
        
        
    def error(self, msg):
        self._scheduleHandler._backlogMain.incrementErrorCounter()
        self._logger.error(msg)
        
        
        
class TOSPingThread(Thread):
    
    def __init__(self, parent, ping_interval_seconds=30, watchdog_timeout_seconds=300):
        Thread.__init__(self, name='%s-Thread' % (self.__class__.__name__,))
        self._logger = logging.getLogger(self.__class__.__name__)
        self._ping_interval_seconds = ping_interval_seconds
        self._watchdog_timeout_seconds = watchdog_timeout_seconds
        self._scheduleHandler = parent
        self._work = Event()
        self._pingThreadStop = False
        
        
    def run(self):
        self._logger.info('started')
        while not self._pingThreadStop:
            self._scheduleHandler.tosMsgSend(TOSTypes.CONTROL_CMD_RESET_WATCHDOG, self._watchdog_timeout_seconds)
            self._logger.debug('reset watchdog')
            self._work.wait(self._ping_interval_seconds)
        self._logger.info('died')


    def stop(self):
        self._pingThreadStop = True
        self._work.set()
        self._logger.info('stopped')
        
        
        
            
class ScheduleCron(CronTab):
    
    def __init__(self, creation_time, user=None, fake_tab=None):
        CronTab.__init__(self, user, fake_tab)
        self._schedule_string = fake_tab
        self._creation_time = creation_time
        self._schedules = []
        for schedule in self.crons:
            self._schedules.append(self._scheduleSanityCheck(schedule))
            
            
    def getCreationTime(self):
        return self._creation_time
            
            
    def getScheduleString(self):
        return self._schedule_string
    
    
    def getScheduleList(self):
        return self._schedules
        
    
    def getNextSchedules(self, date_time, look_backward=False):
        future_schedules = []
        backward_schedules = []
        now = datetime.utcnow()
        error = []
        for schedule in self.crons:
            runtimemax = None
            runtimemin = None
            commandstring = str(schedule.command).strip()
            
            try:
                backwardmin, commandstring = self._getSpecialParameter(commandstring, BACKWARD_TOLERANCE_NAME)
                runtimemax, commandstring = self._getSpecialParameter(commandstring, MAX_RUNTIME_NAME)
                runtimemin, commandstring = self._getSpecialParameter(commandstring, MIN_RUNTIME_NAME)
            except TypeError, e:
                error.append(e)
            
            splited = commandstring.split(None, 1)
            type = splited[0]
            try:
                commandstring = splited[1]
            except IndexError:
                error.append('PLUGIN or SCRIPT definition is missing in the current schedule >%s<' % (schedule,))
                continue
            pluginclassname = ''
            if type.lower() == SCHEDULE_TYPE_PLUGIN:
                splited = commandstring.split(None, 1)
                pluginclassname = splited[0]
                try:
                    commandstring = splited[1]
                except IndexError:
                    commandstring = ''
            elif type.lower() != SCHEDULE_TYPE_SCRIPT:
                error.append('PLUGIN or SCRIPT definition is missing in the current schedule >%s<' % (schedule,))
                continue
            
            if look_backward and backwardmin:
                td = timedelta(minutes=backwardmin)
                nextdt = self._getNextSchedule(date_time - td, schedule)
                if nextdt < now:
                    backward_schedules.append((nextdt, pluginclassname, commandstring.strip(), runtimemax, runtimemin))
                
            nextdt = self._getNextSchedule(date_time, schedule)
            if not future_schedules or nextdt < future_schedules[0][0]:
                future_schedules = []
                future_schedules.append((nextdt, pluginclassname, commandstring.strip(), runtimemax, runtimemin))
            elif nextdt == future_schedules[0][0]:
                future_schedules.append((nextdt, pluginclassname, commandstring.strip(), runtimemax, runtimemin))
            
        return ((backward_schedules + future_schedules), error)


    def _getSpecialParameter(self, commandstring, param_name):
        param_start_index = commandstring.lower().find(param_name)
        if param_start_index == -1:
            return (None, commandstring)
        param_end_index = param_start_index+len(param_name)
        
        try:
            if commandstring[param_end_index] != '=':
                raise TypeError('wrongly formatted \'%s\' parameter in the schedule file (format: %s=INTEGER)' % (param_name, param_name))
            else:
                param_end_index += 1
        except IndexError, e:
            raise TypeError('wrongly formatted \'%s\' parameter in the schedule file (format: %s=INTEGER)' % (param_name, param_name))
            
        digit = ''
        while True:
            try:
                if commandstring[param_end_index] in string.digits:
                    digit += commandstring[param_end_index]
                    param_end_index += 1
                elif commandstring[param_end_index] in string.whitespace:
                    param_end_index += 1
                    break
                else:
                    raise TypeError('wrongly formatted \'%s\' parameter in the schedule file (format: %s=INTEGER)' % (param_name, param_name))
            except IndexError:
                break
            
        if not digit:
            raise TypeError('wrongly formatted \'%s\' parameter in the schedule file (format: %s=INTEGER)' % (param_name, param_name))
            
        commandstring = '%s %s' % (commandstring[:param_start_index].strip(), commandstring[param_end_index:].strip())
        return (int(digit), commandstring)
        
    
    def _getNextSchedule(self, date_time, schedule):
        second = 0
        year = date_time.year
        date_time_month = datetime(date_time.year, date_time.month, 1)
        date_time_day = datetime(date_time.year, date_time.month, date_time.day)
        date_time_hour = datetime(date_time.year, date_time.month, date_time.day, date_time.hour)
        date_time_min = datetime(date_time.year, date_time.month, date_time.day, date_time.hour, date_time.minute)
        
        firsttimenottoday = True
        stop = False
        while not stop:
            for month in self._getRange(schedule.month()):
                if datetime(year, month, 1) >= date_time_month:
                    for day in self._getRange(schedule.dom()):
                        try:
                            nextdatetime = datetime(year, month, day)
                        except ValueError:
                            continue
                        if nextdatetime >= date_time_day:
                            
                            if nextdatetime.isoweekday() in self._getRange(schedule.dow()):
                                try:
                                    dt = datetime(date_time.year, date_time.month, date_time.day+1)
                                except ValueError:
                                    try:
                                        dt = datetime(date_time.year, date_time.month+1, 1)
                                    except ValueError:
                                        dt = datetime(date_time.year+1, 1, 1)
                                        
                                if nextdatetime < dt:
                                    for hour in self._getRange(schedule.hour()):
                                        if datetime(year, month, day, hour) >= date_time_hour:
                                            for minute in self._getRange(schedule.minute()):
                                                nextdatetime = datetime(year, month, day, hour, minute)
                                                if nextdatetime < date_time_min+timedelta(seconds=59):
                                                    continue
                                                else:
                                                    stop = True
                                                    break
                                        if stop:
                                            break
                                elif firsttimenottoday:
                                    minute = self._getFirst(schedule.minute())
                                    hour = self._getFirst(schedule.hour())
                                    firsttimenottoday = False
                                    stop = True
                            if stop:
                                break
                    if stop:
                        break
            if stop:
                break
            else:
                year += 1
        
        return datetime(year, month, day, hour, minute)
    
    
    def _scheduleSanityCheck(self, schedule):
        ret = [None]*3
        try:
            self._scheduleSanityCheckHelper(schedule.minute(), 0, 59)
            self._scheduleSanityCheckHelper(schedule.hour(), 0, 23)
            self._scheduleSanityCheckHelper(schedule.dow(), 0, 7)
            self._scheduleSanityCheckHelper(schedule.month(), 1, 12)
            self._scheduleSanityCheckHelper(schedule.dom(), 1, 31)
        except ValueError, e:
            raise ValueError(str(e) + ' in >' + str(schedule) + '<')
        
        commandstring = str(schedule.command).strip()
        
        backwardmin, commandstring = self._getSpecialParameter(commandstring, BACKWARD_TOLERANCE_NAME)
        runtimemax, commandstring = self._getSpecialParameter(commandstring, MAX_RUNTIME_NAME)
        runtimemin, commandstring = self._getSpecialParameter(commandstring, MIN_RUNTIME_NAME)
        
        splited = commandstring.split(None, 1)
        type = splited[0]
        try:
            commandstring = splited[1].strip()
        except IndexError:
            raise ValueError('PLUGIN or SCRIPT definition is missing in the current schedule >%s<' % (schedule,))
        
        pluginclassname = ''
        if type.lower() == SCHEDULE_TYPE_PLUGIN:
            splited = commandstring.split(None, 1)
            pluginclassname = splited[0].strip()
            ret[0] = SCHEDULE_TYPE_PLUGIN
            ret[1] = pluginclassname
        elif type.lower() == SCHEDULE_TYPE_SCRIPT:
            ret[0] = SCHEDULE_TYPE_SCRIPT
            ret[1] = commandstring
        else:
            raise ValueError('PLUGIN or SCRIPT definition is missing in the current schedule >%s<' % (schedule,))
        ret[2] = schedule.render().encode('utf8')
        
        return ret
        
        
    def _scheduleSanityCheckHelper(self, cronslice, min, max):
        for part in cronslice.parts:
            if str(part).find("/") > 0 or str(part).find("-") > 0 or str(part).find('*') > -1:
                if part.value_to > max or part.value_from < min:
                    raise ValueError('Invalid value %s' % (part,))
            else:
                if part > max or part < min:
                    raise ValueError('Invalid value %s' % (part,))
        
    
    
    def _getFirst(self, cronslice):
        smallestPart = None
        for part in cronslice.parts:
            if str(part).find("/") > 0 or str(part).find("-") > 0 or str(part).find('*') > -1:
                smallestPart = part.value_from
            else:
                if not smallestPart or part < smallestPart:
                    smallestPart = part
        return smallestPart
    
    
    def _getRange(self, cronslice):
        result = []
        for part in cronslice.parts:
            if str(part).find("/") > 0 or str(part).find("-") > 0 or str(part).find('*') > -1:
                result += range(part.value_from,part.value_to+1,int(part.seq))
            else:
                result.append(part)
        return result
