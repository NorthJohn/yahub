
import os
import glob
import time
import asyncio
import logging
import math
from yahub import Msg, Yahub, TerminateTaskGroup
from downsampler import Downsampler

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

  def __init__(self, yahub, config, root):
    self.config = config
    self.root = root
    self.yahub = yahub
    self.logger = logging.getLogger(root)
    self.downsampler = Downsampler()
    self.lastRisingEdge = None
    self.lastFallingEdge = None
    self.windowSizeSec = self.config.get(self.root,'windowSizeSec',10)
    self.maxPulsesPerSec = self.config.get(self.root,'maxPulsesPerSec',10)
    self.multiplier = eval(self.config.get(self.root,'multiplier',1000))

  async def run(self):
    try :
      GPIO.add_event_detect(GPIO_pin, GPIO.BOTH, callback=self.countup)
      self.logger.info(f'started listening')
      #await asyncio.sleep(-1)
    except Exception as ex:
      self.logger.exception(f'coroutine stopping {ex}')
      raise TerminateTaskGroup();
    finally:
      pass

  def countup(self,channel):
    self.loop.call_soon_threadsafe(self.async_countup, channel, context=None)


  def async_countup(self, channel):
    pinState = GPIO.input(GPIO_pin)
    msg = Msg(f"pulses/ch{channel}", 0)
    msg.timestamp = time.time()
    msg.measurement = self.config.get(self.root,'measurement','count')
    msg.reportOnDiff = self.config.get(self.root,'reportOnDiff', 50)
    msg.minPeriodSecs = self.config.get(self.root,'minPeriodSecs', 60)
    msg.maxPeriodSecs = self.config.get(self.root,'maxPeriodSecs', 1800)
    #msg.passThrough = True

    if pinState :
      # largely ignore rising edges just save timestamp
      self.lastRisingEdge = msg.timestamp

    else:
      # fallingEdge
      if self.lastRisingEdge and self.lastFallingEdge:
        #self.logger.debug(f"channel: {channel}, state: {pinState}, rise:{zero(self.lastRisingEdge)} fall: {zero(self.lastFallingEdge)}")
        lastPulseWidth = toFix(msg.timestamp - self.lastRisingEdge,3)
        period = toFix(msg.timestamp - self.lastFallingEdge,2)
        self.numPulses += 1   #

        # have we reached window size ?
        if period <  self.windowSizeSec :
          return              # no

        # minimum period reached
        else :
          pulseRate = min(self.numPulses/period, self.maxPulsesPerSec)
          rate = toFix(self.multiplier * pulseRate, 2)
          self.totalNumPulses += self.numPulses
          status = f"channel:{channel} rate:{toFix(rate,2)} count:{self.numPulses} period:{toFix(period,2)} pulseWidth:{toFix(lastPulseWidth,4)} total:{self.totalNumPulses}"
          self.numWindows += 1
          self.logger.info(status) if self.numWindows % 10 == 0 else self.logger.debug(status)

          msg.payload = rate
          msg.fields = { 'rate': rate, 'count': self.numPulses, 'period': period, 'lastPulseWidth': lastPulseWidth }
          msg.tags   = { 'source': f'ch{channel}' }

          dmsg = self.downsampler.digest(msg)
          if dmsg:
            self.logger.debug(f'queued: {dmsg}')
            self.yahub.route([dmsg])

          self.numPulses = 0

      self.lastFallingEdge = msg.timestamp



