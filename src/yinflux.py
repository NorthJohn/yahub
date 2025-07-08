
from influxdb_client import InfluxDBClient, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.client.exceptions import InfluxDBError

import logging,threading,queue,time


class Yinflux :

  def __init__(self, config, root):
    self.clientInflux = None
    self.clientInfluxWrite = None
    self.config = config
    self.root = root
    self.queue = queue.Queue(maxsize=100)

    #self.mapper = mapper = load_config("solis_modbus.yaml");

    self.clientInflux = InfluxDBClient(url=config.get(root,'url'),
                                        token=config.get(root,'token'),
                                        org=config.get(root,'org'))

    self.blackList = ['solar/system_datetime']
    self.numPoints = 0

  # invoked by with statement !
  def __enter__(self):
    self.clientInfluxWrite = self.clientInflux.write_api(
        write_options=SYNCHRONOUS
        #write_options=WriteOptions(
        #    batch_size=self.config.get(self.root,'batch_size'),
        #    flush_interval=self.config.get(self.root,'flush_interval')
        #)
    )
    logging.info("influxDB instantiated");
    return self

  def start(self):
    self.thread = threading.Thread(target=self.run, daemon=True, name=self.root)
    self.thread.start()

  def enqueue(self, msg):
    try :
      self.queue.put(msg, block=False)
    except queue.Full as ex :
      logging.error(ex)

  def run(self):
    while True:
      msg = self.queue.get()
      self.writeFieldSet(msg)
      self.queue.task_done()

  def writeFieldSet(self, msg):
    if not self.clientInfluxWrite:
      self.__enter__()
    logging.debug(f"Influx write fieldset");

    # we're just repackaging another version of msg which is probably unnecessary
    point = {   'measurement' : msg.measurement,
                'fields' :      msg.fieldSet,
                'tags'   :      msg.tags,
                'timestamp' :   msg.timestamp
    };
    try:
        #self.logger.info(f"Trying write :{topic}, value:{value}, point:{str(point)}");
        self.clientInfluxWrite.write(self.config.get(self.root,'bucket'), record=point)
        logging.debug(f"looks OK {str(point)}");
        self.numPoints = self.numPoints + 1

    except InfluxDBError as e:
        raise Exception(f"Error {e.response.status}")

    except ValueError as er:
        #self.logger.warning(er);
        self.logger.info(f"{str(er)} write failed. Point:{str(point)}");

  def stop(self):
    self.queue.join() # wait for queue to empty
    logging.info(f"closing influx");
    self.clientInfluxWrite.close()      # have to close down influx cleanly to save all data
    # self.thread.join()     # this isn't quite right
    time.sleep(1)

  def __exit__(self, *args):
    pass

