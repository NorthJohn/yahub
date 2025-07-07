

import logging, asyncio, socket
import time
import paho.mqtt.client as mqtt

from config import Config
from yahub import Msg

class Ymqtt:
  connected = False
  mqttc = None
  queue = asyncio.Queue(maxsize=100)
  thread = None
  loop = asyncio.get_running_loop()

  def __init__(self, yahub, config, root):
    self.yahub = yahub
    self.config = config
    self.root = root
    self.unacked_publish = set()
    self.logger = logging.getLogger()
    self.subscribeTopics = []

  def startJUNK(self):
    self.thread = threading.Thread(target=self.run, daemon=True, name=self.root)
    self.thread.start()

  def enqueue(self, msg):
    try :
      self.queue.put_nowait(msg)
    except asyncio.QueueFull as ex :
      self.logger.warning(ex) # but just discard and carry on


  async def run(self):
    self.logger.debug('coroutine started')
    self.connect()
    while True :
      msg = await self.queue.get()
      self.publish(msg)
      self.queue.task_done()
      await asyncio.sleep(0.5)        # limit the message rate to 2 in case there's loooping


  def connect(self):
    config = self.config
    root = self.root

    self.mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, clean_session=True, client_id='yahub-1')
    self.mqttc.username_pw_set(config.get(root,'username'), config.get(root,'password'))

    if config.get(root,'use_ssl', False):
      self.mqttc.tls_set()
      self.mqttc.tls_insecure_set(True)

    #disable_logger()
    self.mqttc.on_connect = self.onConnectDisconnect
    self.mqttc.on_disconnect = self.onConnectDisconnect
    #self.mqttc.on_log     = lambda client, userdata, paho_log_level, messages : logging.info(messages)
    self.mqttc.on_subscribe = lambda client, userdata, mid, reason_code_list, properties: \
      self.onSubcribe(reason_code_list, f'subscribe mid:{mid} {reason_code_list}')
    self.mqttc.on_publish = lambda client, userdata, mid, reason_code, properties: \
      self.onPublish(userdata, mid, reason_code)
    self.mqttc.on_message = self.onMessage

#    self.mqttc.user_data_set(unacked_publish)

    self.mqttc.loop_start()   # this handles the threading behind the scenes

    try:
      self.mqttc.connect(config.get(root,'host'),
                        config.get(root,'port'),
                        config.get(root,'keepalive', 600))

    except socket.gaierror as error :
      self.logger.warning(error)

  def onConnectDisconnect(self, client, userdata, flags, reason_code, properties):
    h = self.config.get(self.root,'host')
    self.logger.info(f"connected to {h}" if self.mqttc.is_connected() else f"disconnected from {h}")
    if self.mqttc.is_connected() :
      for topic in self.subscribeTopics:
        self.subscribe(topic)

  def subscribe(self, topic):
    if self.mqttc and self.mqttc.is_connected():   # replace this wth something from api
      self.mqttc.subscribe(topic, qos=1)
      self.logger.debug(f'subcribing to {topic}')
    else:
      self.subscribeTopics.append(topic)

  def onSubcribe(self, reason_code_list, text):
      self.logger.info(str(reason_code_list))   # needs more work

  def publish(self, msg):
    if self.mqttc and self.mqttc.is_connected():
      msg_info = self.mqttc.publish(msg.topic, msg.payload, qos=1)
      self.unacked_publish.add(msg_info.mid)
      msg_info.wait_for_publish()

  def onPublish(self, userdata, mid, reason_code):
    text=  f'mid:{mid}'
    if reason_code == 'Success' :
      pass
      #self.logger.debug(text)
    else:
      self.logger.error(text)

  def onMessage(self, client, userdata, message):
    msg = Msg(message.topic, str(message.payload, 'utf-8'))
    if 'request' in msg.topic:  # shouldn't be necessary
      self.logger.debug(msg)
      self.loop.call_soon_threadsafe(self.yahub.route, msg, context=None)
      #self.yahub.route(msg)

  def stop(self):
    self.queue.join() # wait for queue to empty
    if self.mqttc.is_connected():
      self.mqttc.disconnect()
    # self.thread.join()     # this isn't quite right
    time.sleep(1)


