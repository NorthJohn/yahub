
import logging,asyncio,queue,time

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


  def enqueue(self, msg):
    try :
      self.queue.put_nowait(msg)
    except asyncio.QueueFull as ex :
      self.logger.warning(ex)   # but just discard and carry on

  async def run(self):
    try :
      self.logger.debug('coroutine started')

      with self.clientInflux.write_api(
        write_options=SYNCHRONOUS
        #write_options=WriteOptions(
        #    batch_size=self.config.get(self.root,'batch_size'),
        #    flush_interval=self.config.get(self.root,'flush_interval')
        #)
      ) as self.clientInfluxWrite :
        logging.info(f"influxDB instantiated, bucket '{self.bucket}'");
        while True:
          msg = await self.queue.get()
          logging.debug(f"writing {msg}");
          self.writeFieldSet(msg)
          self.queue.task_done()
          await asyncio.sleep(0.5)        # limit the message rate to 2 per sec in case there's loooping

    except Exception as ex :
      self.logger.exception(f'coroutine stopping {ex}')
      raise TerminateTaskGroup();
    finally:
      self.clientInfluxWrite.close()      # have to call close() to save all data
      logging.info(f"write buffer flushed and closed");


  def writeFieldSet(self, msg):
    if getattr(msg, 'measurement', False) == False :
      self.logger.debug(f"Skipping {msg.topic}, no measurement specified");

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

    except InfluxDBError as e:
      raise Exception(f"Error {e.response.status}")

    except ValueError as er:
      #self.logger.warning(er);
      self.logger.info(f"{str(er)} write failed. Point:{str(point)}");

