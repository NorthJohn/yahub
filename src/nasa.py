import serial
import time
import sys
import asyncio
import logging
import datetime

from yahub import Msg

# --- PROTOCOL CONSTANTS ---
FRAME_LENGTH = 13 # Start(1) + Src(1) + Dst(1) + Cmd(1) + Data(8) + Chksum(1)
START_BYTE = b'0x32'

# --- DECODING MAPS (Based on reverse engineering community efforts, highly simplified) ---
COMMAND_A0_DECODER = {
    0x00: "Auto", 0x01: "Cool", 0x02: "Dry", 0x03: "Fan", 0x04: "Heat",
}

def decode_temperature(byte_value : int):
  """
  Simulated temperature decoding: (value - 55) for °C.
  """
  try:
    temp = byte_value - 55
    if 15 <= temp <= 30: # Check for reasonable temp range
      return f"{temp}°C"
    return f"Raw: {byte_value} Hex:{hex(byte_value)}   "
  except TypeError:
    return "N/A"

addressClass = { 'Outdoor' : 0x10, 'HTU' : 0x11, 'Indoor' : 0x20, 'ERV' : 0x30, 'Diffuser' : 0x35, \
  'MCU' : 0x38, 'RMC' : 0x40, 'WiredRemote' : 0x50, 'PIM' : 0x58, 'SIM' : 0x59, 'Peak' : 0x5A, 'PowerDivider' : 0x5B }

dataTypes = { 'Undefined' : 0, 'Read' : 1, 'Write' : 2, 'Request' : 3, 'Notification' : 4, 'Response' : 5, 'Ack' : 6, 'Nack' : 7 }

class Nasa_frame:

  @staticmethod
  def calculate_checksum(frame_bytes):
    """
    Calculates a simple 8-bit checksum for the frame data (Sum bytes 1 through 11).
    """
    # Sum bytes 1 through 11 (Source, Destination, Command, Data 1-8)
    checksum_sum = sum(frame_bytes[1:12])
    # Use the lower 8 bits of the sum.
    return checksum_sum & 0xFF

  def encode(src, dst, cmd, payload):
    frame = Nasa_frame()
    frame.raw_bytes = bytearray()
    frame.raw_bytes.append(src)
    frame.raw_bytes.append(dst)
    frame.raw_bytes.append(cmd)
    frame.raw_bytes.extend(payload)
    frame.raw_bytes =  - Nasa_frame.calculate_checksum(self.raw_bytes) # fix
    return frame.raw_bytes

  @staticmethod
  def decode(full_frame : bytearray):

#   if len(full_frame) != FRAME_LENGTH:
#     raise Exception(f"invalid frame length: {len(full_frame)}")

    if full_frame[0] != b'2'[0]:
      raise Exception("invalid start byte")

    frame = Nasa_frame()
    frame.bites = full_frame
    frame.size = int.from_bytes(full_frame[1:3])

    frame.srcClass = full_frame[3]
    frame.srcChannel = full_frame[4]
    frame.srcAddress = full_frame[5]

    frame.dstClass = full_frame[6]
    frame.dstChannel = full_frame[7]
    frame.dstAddress = full_frame[8]

    frame.dataType = full_frame[10]
    frame.packetNumber = full_frame[11]
    frame.capacity = full_frame[12]

    frame.messageNumber = int.from_bytes(full_frame[13:14])

    crcLoc = len(full_frame) - 2
    frame.CRC16 = int.from_bytes(full_frame[crcLoc:crcLoc+2])

    return frame, 'Success'

    calculated_checksum = frame.calculate_checksum(full_frame)

    if calculated_checksum != frame.checksum:
      return None, f"Frame: {frame.bites.hex()} Checksum Mismatch! Calculated: {hex(calculated_checksum)}, Received: {hex(frame.checksum)}"

    match frame.cmd:

      # Example decoding logic for Command 52 (Status Request Response)

      case 0x50 | 0x52:
        frame.cmdDescrip = "Status Report (Cmd 52)"
        frame.set_temp  = decode_temperature(frame.bites[4+0])
        frame.room_temp = decode_temperature(frame.bites[4+1])
        frame.output_air_temp = decode_temperature(frame.bites[4+2])
        frame.power_status = "ON" if (frame.bites[4+4] & 0x80) else "OFF"
        frame.mode = COMMAND_A0_DECODER.get(frame.bites[4+3] & 0x07, f"Raw:{hex(frame.bites[4+3])}")
      # Example decoding logic for Command A0 (Control Command)
      case 0xA0:
        frame.cmdDescrip = "Control Command (Cmd A0)"
        setting_byte = frame.bites[4+1] #### & 0x1F # Assuming lower 5 bits hold temp
        frame.temp_setpoint = decode_temperature(setting_byte)
        frame.power_state = "ON" if (frame.bites[4+4] & 0xF4) == 0xF4 else "OFF"

      case _ :
        frame.cmdDescrip = "Unknown Command"

    return frame, "Success"

  @staticmethod
  def addrToString(clas,channel,address):
    amap = dict((v,k) for k,v in addressClass.items())
    clasName = amap[clas] if clas in amap else clas
    return (f'{clasName}.{channel}.{address}')

  @staticmethod
  def toString(frame):
    return (f'size:{frame.size} {Nasa_frame.addrToString(frame.srcClass,frame.srcChannel,frame.srcAddress)} to {Nasa_frame.addrToString(frame.dstClass,frame.dstChannel,frame.dstAddress)} tipe:{Nasa_frame.dataTypeToString(frame.dataType)} packetNum:{frame.packetNumber} capacity:{frame.capacity} messageNum:{frame.messageNumber}')

  @staticmethod
  def dataTypeToString(dt):
    amap = dict((v,k) for k,v in dataTypes.items())
    return amap[dt] if dt in amap else dt

def getHex(ba) :
  h = ' '.join(format(bite, '02x') for bite in ba) if ba else ''
  return (f'len:{len(ba) if ba else 0} .. {h}')


def printHex(ba) :
  print(getHex(ba))

class YNasa:
  """
  An asynchronous task for reading the Samsung NASA RS-485 protocol.
  It uses asyncio.to_thread() to handle the blocking serial read operation.
  """
  queue = asyncio.Queue(maxsize=100)

  def __init__(self, yahub, config, root):
    self.config = config
    self.root = root
    self.yahub = yahub
    self.logger = logging.getLogger()
    self.ser = None
    self.frame_buffer = bytearray()

  def read_frame_blocking(self):
    if self.ser is None:
      raise Exception(f'Serial port not open')
    try :
      # Read all available data byte at a time, or block  if nothing is available immediately
      inPacket = False
      while True :
        avail = self.ser.in_waiting

        ## fix, don't seem to be able to handle larger buffers
        bites = self.ser.read( min(64, max(1,avail)))  # 1 to 512 bytes at a time
        self.frame_buffer += bites
        #self.logger.debug(f'Received {getHex(self.frame_buffer)}')

        # work through all available bytes until we have a frame
        if not inPacket :
          start_bite = b'2'
          start_index = self.frame_buffer.find(start_bite)

          if start_index < 0 :
            continue    # no start byte, read more bytes
          self.logger.debug(f'got start index {start_index}')

          # Discard unexpected junk bytes before the start byte
          if start_index > 0:
            # Optionally log discarded junk:
            self.logger.debug(f'Discarding preamble {getHex(self.frame_buffer[:start_index])}')
            del self.frame_buffer[:start_index]
          inPacket = True

        else:
          self.logger.debug(f'frame so far {getHex(self.frame_buffer)}')
          if len(self.frame_buffer) < 3 :
            continue

          packLen = int.from_bytes(self.frame_buffer[1:3])
          if packLen > 500 :
            self.logger.warn(f'packet len needed is too large, discarding buffer {packLen}')
            del self.frame_buffer[:]
            inPacket = False
            continue

          self.logger.debug(f'packet len needed {packLen}')

          #breakpoint()
          if len(self.frame_buffer) < packLen :
            continue

          full_frame = self.frame_buffer[:(packLen-4)]
          #self.logger.info(f'frame finally {getHex(full_frame)}')
          del self.frame_buffer[:(packLen-4)]
          #inPacket = False
          return full_frame



    except Exception as e:
      # catch exceptions that would otherwise not be caught in coroutine
      self.logger.exception(e)
      return None


	


  async def run(self):
    self.logger.info('Samsung NASA Protocol RS-485 coroutine started')
    with serial.Serial(
        port=self.config.get(    self.root, 'device', '/dev/ttyUSB0'),
        baudrate=self.config.get(self.root, 'baudrate', 9600),
        parity=self.config.get(  self.root, 'parity',   serial.PARITY_NONE),
        stopbits=self.config.get(self.root, 'stopbits', serial.STOPBITS_ONE),
        bytesize=self.config.get(self.root, 'bytesize', serial.EIGHTBITS),
        timeout=self.config.get (self.root, 'timeout',  1)
      ) as self.ser :
      self.ser.reset_input_buffer()
      self.logger.info(f"{repr(self.ser)}")

      """ read and queue nasa frames forever """
      while True :
        try:
          full_frame =  await asyncio.to_thread(self.read_frame_blocking)
          self.logger.info(f"frame {getHex(full_frame)}")
          frame, status = Nasa_frame.decode(full_frame)

          print(Nasa_frame.toString(frame))
          continue;

          if status != "Success" :
            self.logger.warn(status)
          else:
            payload = frame.bites.hex()
            msg = Msg(f"nasa/dataframe", payload)
            msg.frame = frame
            msg.timestamp = datetime.datetime.now()
            # measurement not specified, mesage won't be written to influx
            # put the successfully decoded frame into the asyncio Queue
            await self.queue.put(msg)
          continue    # look for the next frame

        except Exception as e:
          self.logger.exception(f"In read loop: {e}")
          raise(e)

        finally :
          pass    # serial port should be automatically closed






