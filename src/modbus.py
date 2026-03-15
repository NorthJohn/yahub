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
        # parity='N',
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
    self.modbusRegAll = {}
    with open(mapName, newline='') as csvfile:
      reader = csv.DictReader(csvfile)
      for row in reader :  
        try :
      	  self.modbusRegAll[row['name']] = int(row['register'])
        except Exception as e :
          pass 

    registers = self.config.get(self.root, 'registers')
    self.modbusReg = {}
    for rname in registers :  # copy across known registers
      if rname in self.modbusRegAll:
        self.modbusReg[rname] = self.modbusRegAll[rname]
      else:
        self.logger.debug(f'{r} not mapped to numeric value')


    self.logger.info(f"{len(self.modbusReg)} out of {len(self.modbusRegAll)} registers selected from {mapName}")
    print(self.modbusReg)
    # rows = [(row) =>  for row in rows]

#  for row in rows:
#    m = re.search("\.[\d]+$",f"{row['Default value']}")
#    # self.logging.debug(f"{row['Mnem.']} default {row['Default value']} m {m}")
#    row['Scale'] = 1 if m else 0

  async def connect(self):
    await self.mclient.connect()
    self.logger.debug(f"connected")


  async def poll(self):
    slaves = self.config.get(self.root, 'slaves')
    timestamp = (math.floor(time.time()/60)) * 60  # round to nearest minute
    #self.logger.debug(f"slaves {slaves}")
    for slave in slaves :
      try :
        self.logger.debug(f"slave {slave}")
        msgs = []
        firstTopic = None
        lastTopic = None
        for r in self.modbusReg :
          try :
            source = f"slave{r}"
            topic = f"{r}"
            if not firstTopic:
              firstTopic = topic
            lastTopic = topic

            raddress = self.modbusReg[r]
            if self.mclient.connected :
              rr = await self.mclient.read_holding_registers(raddress, count=2, device_id=slave['address'])
              if rr.isError():
                self.logger.warning(f"{slave['name']}.{raddress}: {rr}")
                break
              msg = Msg(f"{source}/{topic}", rr.registers[0])
              msg.timestamp = timestamp
              msg.topic = topic   # lookup caxton influx handler !!!!!
              msg.source = source
      #       self.logger.debug(f"Created msg {msg}")
              msgs.append(msg)
            else :
              self.logger.warning(f"socket is closed")


          except ModbusIOException as me :
            self.logger.warning(f"{slave['name']}.{raddress}: {me.message}")

            # timeouts and task shutdowns throw the SAME exception
            # so have to test the string to determine action

            if 'No response received' in me.message :
              await asyncio.sleep(60)
            else:
              raise(me)

          except ModbusException as me :
            self.logger.exception(f"{slave['name']}.{raddress}: {me})")

        self.yahub.route(msgs)
        self.logger.info(f"{len(msgs)} modbus registers read from {slave['name']} {firstTopic} → {lastTopic}")

      except ConnectionException as ce :
        self.logger.warning(f"{slave['name']}: {ce.message}")
        await asyncio.sleep(30)
