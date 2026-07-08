
import os
import glob

import asyncio
import logging
import math
from yahub import Msg, Yahub, TerminateTaskGroup
from downsampler import Downsampler

import time
from datetime import datetime



import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BCM)
GPIO_pin = 22 # physical pin 15,  3.3v pin 17
GPIO.setup(GPIO_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

toFix = lambda x, p : round(x, p)

class Pulses:

  queue = asyncio.Queue(maxsize=100)
  loop = asyncio.get_running_loop()
  timeZero  = time.time()
  numWindows = 0
  numPulses = 0
  totalNumPulses = 0
  totalDiscardedPulses = 0

  hhCount = 0
  last_boundary = 0

  def __init__(self, yahub, config, root):
    self.config = config
    self.root = root
    self.yahub = yahub
    self.logger = logging.getLogger(root)
    self.downsampler = Downsampler()
    self.lastRisingEdge = None
    self.lastFallingEdge = None
    self.units = self.config.get(self.root,'units','rate')
    self.maxPulsesPerSec = self.config.get(self.root,'maxPulsesPerSec',10)
    self.multiplier = eval(self.config.get(self.root,'multiplier',1000))
    self.windowSizeSec = self.config.get(self.root,'windowSizeSecs',10)

  async def run(self):
    try :
      GPIO.add_event_detect(GPIO_pin, GPIO.BOTH, callback=self.pulse, bouncetime=50)
      self.logger.info(f'started waiting for events')
      #await asyncio.sleep(-1)
    except Exception as ex:
      self.logger.exception(f'coroutine stopping {ex}')
      raise TerminateTaskGroup();
    finally:
      pass

  def pulse(self,channel):
    pinState = GPIO.input(GPIO_pin)
    timestamp = time.time()
    if pinState:
      self.loop.call_soon_threadsafe(self.halfHourCount, timestamp, channel, pinState, context=None)
    self.loop.call_soon_threadsafe(self.pulseCount, timestamp, channel, pinState, context=None)

  def pulseCount(self, timestamp, channel, pinState):

    if pinState :
      # largely ignore rising edges just save timestamp
      self.lastRisingEdge = timestamp

    else:
      # fallingEdge
      if self.lastFallingEdge and self.lastRisingEdge :
        lastPulseWidth = toFix(timestamp - self.lastRisingEdge,3)
        period = toFix(timestamp - self.lastFallingEdge,2)
        self.numPulses += 1   #
        # have we reached window size ?
        if period <  self.windowSizeSec :
          return              # no

        # minimum period reached
        else :
          pulseRate = min(self.numPulses/period, self.maxPulsesPerSec)
          rate = toFix(self.multiplier * pulseRate, 2)
          self.totalNumPulses += self.numPulses
          status = f"channel:{channel} {self.units}:{toFix(rate,2)} count:{self.numPulses} period:{toFix(period,2)} pulseWidth:{toFix(lastPulseWidth,4)} hh:{self.hhCount}"

          self.numWindows += 1
          self.logger.info(status) if (self.numWindows % 10 == 0 or period > 10 * self.windowSizeSec) else self.logger.debug(status)

          msg = Msg(f"pulses/{self.units}", rate)
          msg.timestamp = int(timestamp)
          msg.time = datetime.fromtimestamp(msg.timestamp)  # round to a second
          msg.reportOnDiff = self.config.get(self.root,'reportOnDiff', 50)
          msg.minPeriodSecs = self.config.get(self.root,'minPeriodSecs', 60)
          msg.maxPeriodSecs = self.config.get(self.root,'maxPeriodSecs', 1800)

          # influx
          msg.measurement = self.config.get(self.root,'measurement','count')
          msg.fields = { self.units : rate, 'count': self.numPulses, 'period': period,  'hh' : self.hhCount, 'lastPulseWidth': lastPulseWidth }
          msg.tags   = { 'source': f'ch{channel}' }

          dmsg = self.downsampler.digest(msg)
          if dmsg:
            self.logger.debug(f'queued: {dmsg}')
            self.yahub.route([dmsg])

          self.numPulses = 0

      self.lastFallingEdge = timestamp


  def halfHourCount(self, timestamp, channel, pinState):
      # Initialise state attributes on the function object if they don't exist
      if not hasattr(self, "last_boundary"):
          self.hhCount = 0
          self.last_boundary = timestamp

      self.hhCount += 1
      current_boundary = timestamp

      # get time of the start of a half hour period
      timeSegment = lambda timestamp : 30 * 60 * (int(timestamp) // (30 * 60))

      # Check if we have moved into a new 30-minute time segment
      if timeSegment(current_boundary) > timeSegment(self.last_boundary) :
          result = self.hhCount
          self.logger.info(f"channel:{channel} hh:{self.hhCount}")
          msg = Msg(f"pulses/hh", self.hhCount)
          msg.time = datetime.fromtimestamp(timeSegment(current_boundary))
          # influx
          msg.measurement = 'HalfHour'
          msg.fields = { 'hh' : self.hhCount }
          msg.tags   = { 'source': f'ch{channel}' }
          self.yahub.route([msg])
          self.hhCount = 0
          self.last_boundary = current_boundary



