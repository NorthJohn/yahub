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
    self.logger = logging.getLogger(root)

    # setting debug prints all PDUs
    pymodbus_apply_logging_config(logging.CRITICAL)

    self.port = config.get(root,'port')
    framer=FramerType.RTU
    self.mclient = AsyncModbusSerialClient(
        self.port,
        framer=framer,
        timeout=2,
        retries=0,
        baudrate=9600,
        bytesize=8,
        parity='E',  # MODBUS standard
        stopbits=1
    )
    self.slavesSchedule = self.config.get(self.root, 'slaves')
    # schedule an immediate poll for all slaves

    for sla in self.slavesSchedule:
      sla['nextPoll'] = 0

    print(self.slavesSchedule)

  async def run(self):

    try:
      self.logger.debug('coroutine started')
      self.loadRegisterDefinitions()


      while True:
        await asyncio.sleep(2)  # loop safety valve, not necessary but wait for MQTT and influx to connect
        self.slavesSchedule = sorted(self.slavesSchedule, key=lambda slave: slave['nextPoll'])
        if len(self.slavesSchedule) <= 0 :
          continue

        slave = self.slavesSchedule[0]
        timeDelta =  slave['nextPoll'] - time.time()
        if timeDelta > 2 :
          self.logger.debug(f"timeDelta sleeping for {timeDelta:<4} secs")
          await asyncio.sleep(timeDelta)
          continue

        slave = self.slavesSchedule.pop(0)
        self.logger.debug(f"polling {slave['name']}")
        for rrange in self.ranges :
          await self.pollOneSlaveAllRegisters(slave, rrange)


    except asyncio.CancelledError as ce:
      self.logger.debug('coroutine cancelled')

    except Exception as ex:
      self.logger.exception(f'coroutine stopping {ex}')

    finally:
      pass
      #await self.disconnect()


  def loadRegisterDefinitions(self):
    mapName = self.config.get(self.root, 'map')
    self.modbusRegAll = {}
    with open(mapName, newline='') as csvfile:
      reader = csv.DictReader(csvfile)
      for row in reader :
        try :
          self.modbusRegAll[row['name']] = int(row['register'])
        except Exception as e :
          pass
    registerRanges = self.config.get(self.root, 'registers')
    self.ranges = []
    numRegisters = 0
    for rrange in registerRanges :        # copy across known registers
      nameFirst = rrange[0]
      nameLast = rrange[1]
      if nameFirst in self.modbusRegAll and nameLast in self.modbusRegAll:
        first = self.modbusRegAll[nameFirst]
        last = self.modbusRegAll[nameLast]
        numRegisters += last - first + 1
        self.ranges.append([nameFirst, nameLast])
      else:
        self.logger.debug(f'{rrange} not mapped to numeric value')

    self.logger.info(f"Scanning {numRegisters} registers in {len(self.ranges)} ranges selected from {mapName}")

    # rows = [(row) =>  for row in rows]

#  for row in rows:
#    m = re.search("\.[\d]+$",f"{row['Default value']}")
#    # self.logging.debug(f"{row['Mnem.']} default {row['Default value']} m {m}")
#    row['Scale'] = 1 if m else 0


  async def disconnect(self):
    if self.mclient.connected:
      await self.mclient.close()
    self.logger.debug(f"disconnected")


  async def pollOneSlaveAllRegisters(self, slave, rrange):
    try:

      if not self.mclient.connected :
        await self.mclient.connect()
        self.logger.debug(f"re-connected")

        # raise(ConnectionException(f'not connected via {self.port}'))
      timestamp = (math.floor(time.time()/6)) * 6  # round to nearest 10 second
      regToAddr = lambda x : x - 1
      source = f"{slave['name']}"
      topic = f"{rrange[0]}"
      nameFirst = rrange[0]
      nameLast = rrange[1]
      first = self.modbusRegAll[nameFirst]
      last = self.modbusRegAll[nameLast]
      namedRange = f"{slave['name']} {rrange[0]} → {rrange[1]}"
      first = self.modbusRegAll[nameFirst]
      last = self.modbusRegAll[nameLast]
      rr = await self.mclient.read_input_registers(regToAddr(first), count=last-first+1, device_id=slave['address'])
      if rr.isError():
        self.logger.warning(f"{namedRange}: {rr}")
        return
      msgs = []
      payload = {}
      for i in range(last-first+1) :
        payload[nameFirst + str(i)] = float(rr.registers[i])/10
      msg = Msg(f"{source}/{topic}", payload)
      msg.timestamp = timestamp
      msg.source = source

      # setup downsampling
      msg.measurement = self.config.get(self.root,'measurement',None) ;
      msg.reportOnDiff = 0.5
      msg.maxPeriodSecs = 10 * 60

      # set influx specific fields
      msg.fields = payload
      msg.tags   = {'source': source}

      self.logger.debug(f"created msg {msg}")
      msgs.append(msg)

      self.yahub.route(msgs)
      self.logger.debug(f"range read from  {namedRange}")
      slave['nextPoll']  = time.time() + self.config.get(self.root, 'poll_interval_short', 20)

    except ModbusIOException as me :
      if 'Request cancelled outside library.' in me.message :
        raise asyncio.CancelledError('re-raised')

      self.logger.warning(f"{namedRange}: {me.message[:60]}")
      slave['nextPoll']  = time.time() + self.config.get(self.root, 'poll_interval_long', 600)

    except (ConnectionException, ModbusException) as ce :
      self.logger.warning(f"{ce.message}, sleeping ")
      slave['nextPoll']  = time.time() + self.config.get(self.root, 'poll_interval_long', 600)


    finally :
      self.slavesSchedule.append(slave)
