import logging, asyncio
import subprocess


class Yrun:

  queue = asyncio.Queue(maxsize=100)

  def __init__(self, yahub, config, root):
    self.yahub = yahub
    logging.basicConfig(level=logging.DEBUG)
    self.logger = logging.getLogger(__name__)

  def start(self):
    try:
      asyncio.run(self.run())
    except RuntimeError as re:
      self.logger.error(re)
    except ExceptionGroup as eg:
      self.logger.exception(eg)

  def enqueue(self, msg):
    try :
      self.queue.put_nowait(msg)
    except asyncio.QueueFull as ex :
      self.logger.warning(ex) # but just discard and carry on

  async def run(self):
    self.logger.debug('coroutine started')
    while True :
      msg = await self.queue.get()
      args = msg.payload.strip().split(' ')
      self.logger.debug(f"excecuting: {args}")
      res = subprocess.run(args, capture_output=True, encoding="UTF-8")
      from yahub import Msg

      replies = []
      if res.returncode:
        replies.append(Msg('response/run/subprocess', res.returncode))
        self.logger.warning(f"result    : {res.returncode} {res}")
      else :
        logLines = res.stdout.split('\n')
        for line in logLines:
            replies.append(Msg('response/run/subprocess', line))
            self.logger.debug(f"result    : {line}")
      for reply in replies:
        for consumer in self.yahub.consumersOfControl:
          consumer.enqueue(reply)
      self.queue.task_done()


def getIP():
  import socket
  hostname = socket.gethostname()
  ip = socket.gethostbyname_ex(hostname)
  fieldSet = {
    'hostname' : hostname,
    'ip' : repr(ip)
  }
  return fieldSet
