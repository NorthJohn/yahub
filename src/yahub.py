

import logging, argparse
import csv,yaml,re
import atexit, signal
import math,time
import asyncio
import time

from config import Config

#from ymodbus import Ymodbus
from yinflux import Yinflux
from yrun import Yrun

NAME = 'yahub'
VERSION = 0.33

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
    #self.queueLogHandler.setLevel('INFO')
    logging.getLogger('').addHandler(self.queueLogHandler)


    self.logger = logging.getLogger('yahub')


  def start(self):
    try:
      asyncio.run(self.run(), debug=False)
    except TerminateTaskGroup as tge:
      texxt = f"signame received : stopping"
      self.logger.info(texxt)

    except RuntimeError as re:
      self.logger.error(re)
    except ExceptionGroup as eg:
      self.logger.exception(eg)
    except KeyboardInterrupt:
      self.logger.info("interrupted.")
      #await asyncio.sleep(2.0)  # simulate some async clean-up

    self.logger.info(f"Shutdown complete")   # never reached


  async def ask_exit(self, signame):
    self.logger.info(f"{signame} received : stopping")

    #await asyncio.sleep(2.0)  # simulate some async clean-up
    #loop = asyncio.get_event_loop()
    #loop.stop()

  '''
  The code below seems to deliver clean exit, however bizarre it is
  It seems important to not cancel Task-1
  '''

  async def ask_exit(self, tg, signame):
    names = []
    for task in asyncio.all_tasks():
      name = task.get_name()
      if name != 'Task-1' :
        names.append(name)
        task.cancel()
    self.logger.info(f"terminating: {' '.join(names)}")

  async def ask_exit3(self, tg, signame):
    tg.cancel()
    self.logger.info(f'terminating')


  async def run(self):

    config = None
    configFile = 'yahub.yaml'
    with open(configFile) as yfile:
      config = Config(yaml.safe_load(yfile))
    self.logger.info(f'loaded config from {configFile}')

    async with asyncio.TaskGroup() as tg:
      loop = asyncio.get_event_loop()
      for signame in ('SIGINT', 'SIGTERM'):
          loop.add_signal_handler(getattr(signal, signame),
                                  lambda signame=signame: tg.create_task(self.ask_exit(tg, signame),name='SignalHandler'))

      from yrun import getIP
      self.logger.info(f'IP address {getIP()}')

      self.yrun = Yrun(self, config, 'yrun')
      self.stask = tg.create_task(self.yrun.run(), name='yrun')

      from ymqtt import Ymqtt
      ymqtt = Ymqtt(self, config,'cloudMQTT',)
      self.qtask = tg.create_task(ymqtt.run(), name='cloudMQTTX')

      self.queueLogHandler.addListener(ymqtt)
      self.ltask = tg.create_task(self.queueLogHandler.run(), name='AsyncioQueueLogHandler')

      self.consumersOfData.append(ymqtt)
      self.consumersOfControl.append(ymqtt)

      ymqtt.subscribe('request/#')

      if False:
        yinflux = Yinflux(config, 'cloudInflux')
        #yinflux.start()
        #tasks.append(yinflux.thread)
        self.consumersOfData.append(yinflux)

      from ymodbus import Ymodbus
      self.ymodbus = Ymodbus(self, config,'serialModbus')
      self.mtask = asyncio.create_task(self.ymodbus.run(), name='serialModbusX')

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

      elif re.match(r"^(|sys|log|__main__)", msg.topic):
        for consumer in self.consumersOfControl:
          consumer.enqueue(msg)

      else:  # broadcast message
        msgPrepped = prepareDataForInflux(msg)
        #self.logger.debug(f"Broadcasting {msgPrepped}")
        for consumer in self.consumersOfData:
          consumer.enqueue(msgPrepped)


 
if __name__ == "__main__":

  print(f"{NAME} version {VERSION}")

  usage = "%prog <commands>"
  parser = argparse.ArgumentParser(description='Yahub - Yet Another HUB')

  parser.add_argument('-l','--log', default='INFO', help="Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL), default is %(default)s.")

  parser.add_argument("-H", "--more-help", dest="help",
  help="display more help text, not written")

  args = parser.parse_args()

  yahub = Yahub(args)
  yahub.start()


