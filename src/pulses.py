
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
pin = 22 # physical pin 15
GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

toFix = lambda x, p : round(x, p)

class Pulses:

  queue = asyncio.Queue(maxsize=100)
  loop = asyncio.get_running_loop()
  timeZero  = time.time()
  numPulses = 0
  discardedPulses = 0

  def __init__(self, yahub, config, root):
    self.config = config
    self.root = root
    self.yahub = yahub
    self.logger = logging.getLogger(root)
    self.downsampler = Downsampler()
    self.risingEdge = None
    self.fallingEdge = None
    self.multiplier = eval(self.config.get(self.root,'multiplier',1000))

  async def run(self):
    try :
      GPIO.add_event_detect(pin, GPIO.BOTH, callback=self.countup)
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
    pinState = GPIO.input(pin)
    msg = Msg(f"pulses/ch{channel}", 0)
    msg.timestamp = time.time()
    msg.measurement = self.config.get(self.root,'measurement','count')
    msg.reportOnDiff = self.config.get(self.root,'reportOnDiff', 50)
    msg.minPeriodSecs = self.config.get(self.root,'minPeriodSecs', 60)
    msg.maxPeriodSecs = self.config.get(self.root,'minPeriodSecs', 1800)

    if pinState :
      self.risingEdge = msg.timestamp
      self.numPulses += 1
      if self.numPulses % 10 == 0 :
        self.logger.info(f"channel:{channel} num pulses:{self.numPulses}")
    else:
      # fallingEdge
      if self.risingEdge and self.fallingEdge:
        #self.logger.debug(f"channel: {channel}, state: {pinState}, rise:{zero(self.risingEdge)} fall: {zero(self.fallingEdge)}")
        width = toFix(msg.timestamp - self.risingEdge,3)
        period = toFix(msg.timestamp - self.fallingEdge,2)
        if period <  0.05 :
          self.discardedPulses += 1
          if self.discardedPulses % 10 == 0 :
            self.logger.debug(f"channel:{channel} discarded pulses:{self.discardedPulses}, possibly noise")
          self.risingEdge = None
          self.fallingEdge = None
          return ;
        else :
          rate = toFix(self.multiplier/period, 2)
          self.logger.debug(f"channel:{channel} rate:{toFix(rate,2)} period:{toFix(period,2)} pulse width:{toFix(width,4)}")

          msg.payload = rate
          msg.fields = { 'rate': rate, 'period' : period, 'width' : width }
          msg.tags   = { 'source': f'ch{channel}' }

          dmsg = self.downsampler.digest(msg)
          if dmsg:
            self.logger.debug(f'queued: {dmsg}')
            self.yahub.route([dmsg]);

      self.fallingEdge = msg.timestamp



