

import logging,asyncio,queue,time,random,json,socket

import paho.mqtt.client as mqtt

from config import Config

from yahub import Msg, TerminateTaskGroup

class Ymqtt:
  connected = False
  mqttc = None
  connectComplete = asyncio.Event()
  publishComplete = asyncio.Event()
  queue = asyncio.Queue(maxsize=100)
  thread = None
  loop = asyncio.get_running_loop()

  def __init__(self, yahub, config, root):
    self.yahub = yahub
    self.config = config
    self.root = root
    self.unacked_publish = set()
    self.logger = logging.getLogger(root)
    self.subscribeTopics = []

  def enqueue(self, msg):
    try :
      self.queue.put_nowait(msg)
    except asyncio.QueueFull as ex :
      self.logger.warning(f"queue full {str(ex)}")   # but just discard and carry on

  async def run(self):
    self.logger.debug('coroutine started')
    self.initMqttc()
    try :
      while True :
        if not self.mqttc.is_connected():
          await self.yahub.networkAvailable.wait()
          self.connect()
          await self.connectComplete.wait()
          self.connectComplete.clear()
          if not self.mqttc.is_connected():
            await asyncio.sleep(self.config.get(self.root, 'poll_interval_long', 40))
            continue

        [_, msg] = await asyncio.gather(
            self.yahub.networkAvailable.wait(),
            self.queue.get()
        )
        self.publish(msg)
        await self.publishComplete.wait()
        self.publishComplete.clear()
        self.queue.task_done()
        await asyncio.sleep(0.5)        # limit the message rate to 2 in case there's loooping
    except asyncio.CancelledError as ce:
      self.logger.debug('coroutine cancelled')
    except TimeoutError as te:
      self.logger.warning(f'connection timeout {te}')
      await asyncio.sleep(60)           # possibly no internet
    except Exception as ex:
      self.logger.exception(f'coroutine stopping {ex}')
      raise TerminateTaskGroup();
    finally:
      if self.mqttc and self.mqttc.is_connected():
        self.mqttc.disconnect()       # this will generate a log message


  def initMqttc(self):
    config = self.config
    root = self.root
    clientID = config.get(root,'clientID', f'cli-{random.randint(1000,9999)}')
    self.mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, clean_session=True, client_id=clientID)
    self.mqttc.username_pw_set(config.get(root,'username'), config.get(root,'password'))

    if config.get(root,'use_ssl', False):
      self.mqttc.tls_set()
      self.mqttc.tls_insecure_set(True)

    #disable_logger()
    self.mqttc.on_connect = self.onConnect
    self.mqttc.on_connect_fail = self.onConnectFail
    self.mqttc.on_disconnect = self.onDisconnect
    #self.mqttc.on_log     = lambda client, userdata, paho_log_level, messages : logging.info(messages)
    self.mqttc.on_subscribe = lambda client, userdata, mid, reason_code_list, properties: \
      self.onSubscribe(reason_code_list, f'subscribe mid:{mid} {reason_code_list}')
    self.mqttc.on_publish = lambda client, userdata, mid, reason_code, properties: \
      self.onPublish(userdata, mid, reason_code)
    self.mqttc.on_message = self.onMessage

#    self.mqttc.user_data_set(unacked_publish)

    self.mqttc.loop_start()   # this handles the threading behind the scenes

  def connect(self):
    try:
      config = self.config
      root = self.root
      self.mqttc.connect(config.get(root,'host'),
                        config.get(root,'port'),
                        config.get(root,'keepalive', 600))

    except socket.gaierror as error :
      self.logger.warning(error)

  def onConnect(self, client, userdata, flags, reason_code, properties):
    h = self.config.get(self.root,'host')
    self.logger.info(f"connected to {h}")
    for topic in self.subscribeTopics:
      self.subscribe(topic)
    self.connectComplete.set()    
  
  def onDisconnect(self, client, userdata, flags, reason_code, properties):
    h = self.config.get(self.root,'host')
    self.logger.info(f"disconnected from {h}")

  def onConnectFail(self, client, userdata, flags, reason_code, properties):
    self.logger.debug(f"connect fail")   # necessary, needs more work
    self.connectComplete.set()   

  def subscribe(self, topic):
    if self.mqttc and self.mqttc.is_connected():   # replace this wth something from api
      self.mqttc.subscribe(topic, qos=1)
      self.logger.debug(f'subcribing to {topic}')
    else:
      self.subscribeTopics.append(topic)

  def onSubscribe(self, reason_code_list, text):
      self.logger.debug(f"subscribed {str(reason_code_list)}")   # needs more work

  def publish(self, msg):
    if self.mqttc and self.mqttc.is_connected():
      payload = json.dumps(msg.payload)  if type(msg.payload) is dict else msg.payload
      topic = f"{self.yahub.hostname}/{msg.topic}"
      msg_info = self.mqttc.publish(topic, payload, qos=1)
      self.unacked_publish.add(msg_info.mid)

  def onPublish(self, userdata, mid, reason_code):
    text=  f'mid:{mid}'
    if reason_code == 'Success' :
      pass
      #self.logger.debug(text)
    else:
      self.logger.error(text)
    self.publishComplete.set()

  def onMessage(self, client, userdata, message):
    msg = Msg(message.topic, str(message.payload, 'utf-8'))
    if 'request' in msg.topic:  # should already be filtered by route()
      self.logger.debug(msg)
      self.loop.call_soon_threadsafe(self.yahub.route, msg, context=None)
      #self.yahub.route(msg)

  def stop(self):
    self.queue.join() # wait for queue to empty
    if self.mqttc.is_connected():
      self.mqttc.disconnect()
