
import logging,asyncio,queue,time
import urllib3

from yahub import Msg, TerminateTaskGroup

from influxdb_client import InfluxDBClient, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.client.exceptions import InfluxDBError



class Yinflux :

  def __init__(self, config, root):
    self.clientInflux = None
    self.clientInfluxWrite = None
    self.config = config
    self.root = root
    self.queue = asyncio.Queue(maxsize=100)
    self.logger = logging.getLogger()

    #self.mapper = mapper = load_config("solis_modbus.yaml");

    self.clientInflux = InfluxDBClient(url=config.get(root,'url'),
                                       token=config.get(root,'token'),
                                       org=config.get(root,'org'))
    self.bucket = self.config.get(self.root,'bucket')
    self.numPoints = 0
    self.numErrors = 0


  def enqueue(self, msg):
    try :
      self.queue.put_nowait(msg)
    except asyncio.QueueFull as ex :
      self.logger.warning(ex)   # but just discard and carry on

  async def run(self):
    self.logger.debug('coroutine started')
    while True:    # the restart loop
      try :
        with self.clientInflux.write_api(
          write_options=SYNCHRONOUS
          #write_options=WriteOptions(
          #    batch_size=self.config.get(self.root,'batch_size'),
          #    flush_interval=self.config.get(self.root,'flush_interval')
          #)
        ) as self.clientInfluxWrite :
          logging.info(f"influxDB instantiated, bucket '{self.bucket}'");
          while True:   # the message loop
            msg = await self.queue.get()
            logging.debug(f"writing {msg}");
            await self.writeFieldSet(msg)
            self.queue.task_done()
            await asyncio.sleep(0.5)        # limit the message rate to 2 per sec in case there's loooping

      # make sure we escape run loop if taskgroup is closing down
      except asyncio.CancelledError as ce:
        self.logger.debug('coroutine cancelled')
        break                               # but exit through finally

      except (ConnectionRefusedError, NewConnectionError) as acceptableException:
        self.logger.warning(f'{acceptableException}')

      except Exception as ex :
        self.numErrors += 1
        self.logger.exception(f'error count:{self.numErrors} {ex}')
        if self.numErrors > 100 :
          raise TerminateTaskGroup();
        else :
          await asyncio.sleep(30 * 60)         # sleep for a while then close & reopen client

      finally:
        self.clientInfluxWrite.close()      # have to call close() to save all data
        logging.info(f"write buffer flushed and closed");


  async def writeFieldSet(self, msg):
    if getattr(msg, 'measurement', False) == False :
      self.logger.debug(f"Skipping {msg.topic}, no measurement specified");
      return

    if not self.clientInfluxWrite:
      self.__enter__()

    self.logger.debug(f"write fieldset");

    # we're just repackaging another version of msg which is probably unnecessary
    point = {   'measurement' : msg.measurement,
                'fields' :      msg.fields,
                'tags'   :      msg.tags,
                'timestamp':    msg.timestamp * 1000 * 1000 * 1000
    };
    try:
      self.clientInfluxWrite.write(self.bucket, record=point)
      self.logger.debug(f"written {str(point)}");
      self.numPoints = self.numPoints + 1
      self.numErrors = max(self.numErrors - 1, 0)  # decrement error counter down to zero

    except asyncio.CancelledError as ce:
      pass

    except (InfluxDBError, ValueError, TimeoutError) as er:
      #self.logger.warning(er);
      self.logger.warning(f"{str(er)} write failed. Point:{str(point)}");
      self.numErrors += 1
      self.logger.exception(f'error count:{self.numErrors} {er}')
      if self.numErrors > 10 :
        raise TerminateTaskGroup();
      else :
        await asyncio.sleep(1 * 60)
	
