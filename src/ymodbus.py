import logging
import csv,yaml
import atexit, signal
import math,time
import asyncio
import time

from config import Config
from yahub import Msg, Yahub

from pymodbus.client import AsyncModbusSerialClient

from pymodbus import (
    FramerType,
    ModbusException,
    pymodbus_apply_logging_config,
)

from pymodbus.exceptions import ConnectionException, ModbusIOException


class Ymodbus:

  queue = asyncio.Queue(maxsize=100)

  def __init__(self, yahub, config, root):
    self.config = config
    self.root = root
    self.yahub = yahub
    self.modbusMap = []
    self.logger = logging.getLogger()

    # setting debug prints all PDUs
    pymodbus_apply_logging_config("CRITICAL")

    port = config.get(root,'port')
    framer=FramerType.RTU
    self.mclient = AsyncModbusSerialClient(
        port,
        framer=framer,
        # timeout=10,
        # retries=3,
        baudrate=9600,
        bytesize=8,
        parity="N",
        stopbits=1
    )

#  def start(self):
#    self.thread = asyncio.run(self.run)
#    #self.thread.start()

  async def run(self):
    try:
      self.logger.debug('coroutine started')
      self.loadRegisterDefinitions()
      await self.connect()
      while True:
        val = await self.poll()
        await asyncio.sleep(self.config.get(self.root, 'poll_interval', 60))
    except Exception as ex:
      self.logger.exception(f'coroutine stopping {ex}')


  def loadRegisterDefinitions(self):
    #rows = None
    mapName = self.config.get(self.root, 'map')
    with open(mapName, newline='') as csvfile:
      reader = csv.DictReader(csvfile)
      self.modbusMap = [row for row in reader]
    self.logger.info(f"Modbus register map loaded {mapName}")

  # rows = [(row) =>  for row in rows]

#  for row in rows:
#    m = re.search("\.[\d]+$",f"{row['Default value']}")
#    # self.logging.debug(f"{row['Mnem.']} default {row['Default value']} m {m}")
#    row['Scale'] = 1 if m else 0

  async def connect(self):
    await self.mclient.connect()

  def poll3JUNK(self):
    rr = self.mclient.read_holding_registers(4, count=12, slave=1)
    if rr.isError():
      self.logger.warning(f"Received exception from device ({rr})")
    assert rr.registers[0] == 17
    assert rr.registers[1] == 17

    return rr

  async def poll(self):
    slaves = self.config.get(self.root, 'slaves')
    registers = self.config.get(self.root, 'registers')
    timestamp = (math.floor(time.time()/60)) * 60  # round to nearest minute
    #self.logger.debug(f"slaves {slaves}")
    for slave in slaves :
      try :
        self.logger.debug(f"slave {slave}")
        msgs = []
        firstTopic = None
        lastTopic = None
        try :
          for r in registers:
            rr = await self.mclient.read_holding_registers(2, count=12, slave=slave['address'])
            if rr.isError():
              self.logger.warning(f"Received exception from device ({rr})")
              break
            source = f"slave{r}"
            topic = f"{r}"
            if not firstTopic:
              firstTopic = topic
            lastTopic = topic
            msg = Msg(f"{source}/{topic}", rr.registers[0])
            msg.timestamp = timestamp
            msg.topic = topic   # lookup caxton influx handler !!!!!
            msg.source = source
    #       self.logger.debug(f"Created msg {msg}")
            msgs.append(msg)

        except ModbusIOException as me :
          self.logger.warning(me.message)

          # timeouts and task shutdowns throw the SAME exception
          # so have to test the string to determine action

          if 'No response received' in me.message :
            await asyncio.sleep(60)
          else:
            raise(me)

        except ModbusException as me :
          self.logger.exception(f"Received exception from device ({me})")

        self.yahub.route(msgs)
        self.logger.info(f"{slave['name']}: {len(msgs)} modbus registers read: {firstTopic} → {lastTopic}")

      except ConnectionException as me :
        self.logger.warning(str(me))
        await asyncio.sleep(30)
