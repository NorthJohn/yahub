
import logging,asyncio,queue,time
import urllib3

from yahub import Msg, TerminateTaskGroup

from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client import WriteOptions
from influxdb_client.client.exceptions import InfluxDBError


class Yinflux :

  def __init__(self, yahub, config, root):
    self.yahub = yahub
    self.config = config
    self.root = root
    self.clientInflux = None
    self.clientInfluxWrite = None

    self.queue = asyncio.Queue(self.config.get(self.root, 'queueSize',100))
    self.logger = logging.getLogger(root)

    #self.mapper = mapper = load_config("solis_modbus.yaml");

    self.bucket = self.config.get(self.root,'bucket')
    self.numPoints = 0
    self.numErrors = 0


  def enqueue(self, msg):
    try :
      self.queue.put_nowait(msg)
    except asyncio.QueueFull as ex :
      self.logger.warning(f"queue full {str(ex)}")   # but just discard and carry on

  async def run(self):
    self.logger.debug('coroutine started')

    async with InfluxDBClientAsync(url=self.config.get(self.root,'url'),
                                  token=self.config.get(self.root,'token'),
                                  org=self.config.get(self.root,'org')) as self.clientInflux :

      self.clientInfluxWrite = self.clientInflux.write_api()
      #write_options=WriteOptions(
      #    batch_size=self.config.get(self.root,'batch_size'),
      #    flush_interval=self.config.get(self.root,'flush_interval')
      #)
      self.logger.info(f"influxDB instantiated, bucket '{self.bucket}'");
      
      while True:   # the message loop
        try: 
          [_, msg] = await asyncio.gather(
              self.yahub.networkAvailable.wait(),
              self.queue.get()
          )
          self.logger.debug(f"writing {msg}");
          await self.writeFieldSet(msg)
          self.queue.task_done()
          await asyncio.sleep(0.5)        # limit the message rate to 2 per sec in case there's loooping

        # make sure we escape run loop if taskgroup is closing down
        except asyncio.CancelledError as ce:
          self.logger.debug('coroutine cancelled')
          break                               # but exit through finally

        except (ConnectionRefusedError, ConnectionError) as acceptableException:
          self.logger.warning(f'{acceptableException}')

        except Exception as ex :
          self.numErrors += 1
          if self.numErrors < 100 :
            self.logger.error(f'error count:{self.numErrors} {str(ex)}, sleeping')
            await asyncio.sleep(2 * 60)       # sleep for a while then close & reopen client
          else:
            self.logger.error(f'error count exceeded :{self.numErrors} {str(ex)}')
            raise TerminateTaskGroup();
      
        finally:
          pass

    self.logger.info(f"write buffer flushed and closed");


  async def writeFieldSet(self, msg):
    if getattr(msg, 'measurement', False) == False :
      self.logger.debug(f"Skipping {msg.topic}, no measurement specified");
      return

    if not self.clientInfluxWrite:
      self.__enter__()

    # self.logger.debug(f"write fieldset");

    # we're just repackaging another version of msg which is probably unnecessary
    point = {   'measurement' : msg.measurement,
                'fields' :      msg.fields,
                'tags'   :      msg.tags,
                'time'   :      msg.time
    };

    await self.clientInfluxWrite.write(self.bucket, record=point)
    self.logger.debug(f"written {str(point)}");
    self.numPoints = self.numPoints + 1
    self.numErrors = max(self.numErrors - 1, 0)  # decrement error counter down to zero

