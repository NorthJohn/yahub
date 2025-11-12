

import logging, argparse
import csv,re,yaml
import atexit, signal
import math,time
import asyncio

from config import Config

from yrun import Yrun

NAME = 'yahub'
VERSION = 0.34

# the concept of topic and payload concept comes from node-red

class Msg() :
  topic = 'etc'
  payload = None
  def __init__(self,t, p):
    self.topic = t
    self.payload = str(p)
  def __repr__(self):
    return f'{self.topic} : {self.payload}'


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
  tasks = set()
  logger = None

  def __init__(self, args):

    logging.basicConfig(level=args.log.upper(),
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


  def start(self):
    try:
      asyncio.run(self.run(), debug=False)
    except* TerminateTaskGroup as tge:
      self.logger.debug(f"async taskgroup terminated")

    self.logger.info(f"shutdown complete")


  async def ask_exit(self, tg, signame):
    self.logger.info(f"shutdown initiated, {signame} received")
    raise TerminateTaskGroup()


  async def run(self):
    config = None
    configFile = 'yahub.yaml'
    self.logger.info(f'{NAME} version {VERSION}, loading config from {configFile}')
    with open(configFile) as yfile:
      config = Config(yaml.safe_load(yfile))

    async with asyncio.TaskGroup() as tg:
      loop = asyncio.get_event_loop()
      for signame in ('SIGINT', 'SIGTERM'):
          loop.add_signal_handler(getattr(signal, signame),
                                  lambda signame=signame: tg.create_task(self.ask_exit(tg, signame),name='SignalHandler'))

      from yrun import getIP
      self.logger.info(f'IP address {getIP()}')

      self.yrun = Yrun(self, config, 'yrun')
      self.stask = tg.create_task(self.yrun.run(), name='yrun')

      from mqtt import Ymqtt
      mqtt = Ymqtt(self, config,'cloudMQTT',)
      self.qtask = tg.create_task(mqtt.run(), name='cloudMQTTX')

      self.queueLogHandler.addListener(mqtt)
      self.ltask = tg.create_task(self.queueLogHandler.run(), name='AsyncioQueueLogHandler')

      self.consumersOfData.append(mqtt)
      self.consumersOfControl.append(mqtt)


      mqtt.subscribe('request/#')

      if config.get('cloudInflux','enable', False):
        from influx import Yinflux
        influx = Yinflux(config, 'cloudInflux')
        self.itask = tg.create_task(influx.run(), name='cloudInflux')
        self.consumersOfData.append(influx)

      if config.get('serialModbus','enable', False):
        from modbus import Ymodbus
        self.modbus = Ymodbus(self, config, 'serialModbus')
        self.mtask = tg.create_task(self.modbus.run(), name='serialModbusX')

      if config.get('oneWire', 'enable', False):
        from onewire import Yonewire
        self.onewire = Yonewire(self, config,'oneWire')
        #if false and self.yonewire.enable:
        self.otask = tg.create_task(self.onewire.run(), name='oneWire')

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

        self.logger.debug(f"Broadcasting {msg} to {len(self.consumersOfData)}")
        for consumer in self.consumersOfData:
          consumer.enqueue(msg)


 
if __name__ == "__main__":

  usage = "%prog <commands>"
  parser = argparse.ArgumentParser(description='Yahub - Yet Another HUB')

  parser.add_argument('-l','--log', default='INFO', help="Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL), default is %(default)s.")

  parser.add_argument("-H", "--more-help", dest="help",
  help="display more help text, not written")

  args = parser.parse_args()

  yahub = Yahub(args)
  yahub.start()


