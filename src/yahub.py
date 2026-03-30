

import logging, argparse
import csv,re,yaml
import atexit, signal
import math,time
import asyncio

from config import Config

from yrun import Yrun

NAME = 'yahub'
VERSION = 0.40

# the concept of topic and payload concept comes from node-red

class Msg() :
  topic = 'etc'
  payload = None
  def __init__(self,t, p):
    self.topic = t
    self.payload = p
  def __repr__(self):
    return f'{self.topic} : {str(self.payload)}'


def prepareDataForInflux(msg):
  msg.measurement = 'sensor'
  msg.fieldSet = {}
  msg.tags = { 'inverter' : 'A' }
  msg.timestamp = (math.floor(time.time()/60)) * 60  # round to nearest minute
  msg.topic = msg.topic.replace(" ","_") if msg.topic else 'notopic'
  return msg


class TerminateTaskGroup(Exception):
    """Exception raised to terminate a task group."""


class Yahub:
  consumersOfData = []
  consumersOfControl = []
  #threads = []
  hostname = 'unknown'
  tasks = set()
  logger = None

  def __init__(self, args):

    logging.basicConfig(level=args.loglevel.upper(),
                      format='%(asctime)s %(levelname)-3s %(module)s %(message)s',
                      datefmt='%H:%M:%S')

    # create a log handler that writes to an intermediate queue
    from asyncioQueueLogHandler import AsyncioQueueLogHandler
    self.queueLogHandler = AsyncioQueueLogHandler()
    # set a format
    formatter = logging.Formatter('%(asctime)s %(levelname)-3s %(module)s %(message)s', datefmt='%H:%M:%S')
    self.queueLogHandler.setFormatter(formatter)
    logging.getLogger('').addHandler(self.queueLogHandler)
    self.logger = logging.getLogger('yahub')
    self.configFile = args.config


  def start(self):
    try:
      asyncio.run(self.run(), debug=False)
    except* TerminateTaskGroup as tge:
      self.logger.debug(f"async taskgroup terminated")
    finally:
      self.logger.info(f"async taskgroup shutdown complete")

  async def ask_exit(self, tg, signame):
    self.logger.info(f"shutdown initiated, {signame} received")
    raise TerminateTaskGroup()

  async def run(self):
    config = None
    self.logger.info(f'{NAME} version {VERSION}, loading config from {self.configFile}')
    with open(self.configFile) as yfile:
      config = Config(yaml.safe_load(yfile))

    async with asyncio.TaskGroup() as tg:
      loop = asyncio.get_event_loop()
      for signame in ('SIGINT', 'SIGTERM'):
          loop.add_signal_handler(getattr(signal, signame),
                                  lambda signame=signame: tg.create_task(self.ask_exit(tg, signame),name='SignalHandler'))
      from yrun import getIP
      host = getIP()
      self.hostname = host['hostname']
      self.logger.info(f'{host}')

      self.yrun = Yrun(self, config, 'yrun')
      self.stask = tg.create_task(self.yrun.run(), name='yrun')

      from mqtt import Ymqtt
      mqtt = Ymqtt(self, config,'mqttCloud',)
      self.qtask = tg.create_task(mqtt.run(), name='mqttCloud')

      self.queueLogHandler.addListener(mqtt)
      self.ltask = tg.create_task(self.queueLogHandler.run(), name='AsyncioQueueLogHandler')

      self.consumersOfData.append(mqtt)
      self.consumersOfControl.append(mqtt)

      mqtt.subscribe('request/#')

      if config.get('influxLocal','enable', False):
        from influx import Yinflux
        influx = Yinflux(config, 'influxLocal')
        self.itask = tg.create_task(influx.run(), name='influxLocal')
        self.consumersOfData.append(influx)

      if config.get('influxCloud','enable', False):
        from influx import Yinflux
        influx = Yinflux(config, 'influxCloud')
        self.itask = tg.create_task(influx.run(), name='influxCloud')
        self.consumersOfData.append(influx)

      if config.get('serialModbus','enable', False):
        from modbus import Ymodbus
        self.modbus = Ymodbus(self, config, 'serialModbus')
        self.mtask = tg.create_task(self.modbus.run(), name='serialModbus')

      if config.get('oneWire', 'enable', False):
        from onewire import Yonewire
        self.onewire = Yonewire(self, config,'oneWire')
        #if false and self.yonewire.enable:
        self.otask = tg.create_task(self.onewire.run(), name='oneWire')

      if config.get('nasa', 'enable', False):
        from nasa import YNasa
        self.nasa = YNasa(self, config,'nasa')
        #if false and self.yonewire.enable:
        self.ntask = tg.create_task(self.nasa.run(), name='nasa')

      self.logger.info('startup completed')


  def route(self, msg):
    msgs = msg if type(msg) is list else [msg]
    for msg in msgs:
      #self.logger.debug(f"route: {msg}")

      if re.match(r"^(response)", msg.topic):
        pass   # yahub generates responses so we don't want to re=process them

      elif re.match(r"^(request/subprocess/run)", msg.topic):
        self.yrun.enqueue(msg)
        #self.logger.debug(f"route: {msg}")

      elif re.match(r"^(sys|log)", msg.topic):
        for consumer in self.consumersOfControl:
          consumer.enqueue(msg)

      else:  # broadcast message
        listeners = [x.root for x in self.consumersOfData]
        self.logger.debug(f"broadcasting {msg} to {' '.join(listeners)}")
        for consumer in self.consumersOfData:
          consumer.enqueue(msg)


 
if __name__ == "__main__":

  usage = "%prog <commands>"
  parser = argparse.ArgumentParser(description='Yahub - Yet Another HUB')

  parser.add_argument('-l','--loglevel', default='INFO', help="Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL), default is %(default)s.")

  parser.add_argument('-c','--config', default='yahub.yaml', help="Use configuration file %(default)s.")

  args = parser.parse_args()

  yahub = Yahub(args)
  yahub.start()


